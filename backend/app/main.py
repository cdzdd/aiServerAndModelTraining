import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from http import HTTPStatus
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException

from app.core.config import Settings
from app.core.database import create_db_engine
from app.core.errors import error_response
from app.core.request_context import configure_logging, log_failure, log_http, request_id_context
from app.core.security import AuthError
from app.modules.analytics.router import router as analytics_router
from app.modules.auth.limits import LoginLimiter
from app.modules.auth.router import router as auth_router
from app.modules.auth.service import check_csrf
from app.modules.chat.router import router as chat_router
from app.modules.chat.runtime import ChatRuntime
from app.modules.chat.service import recover_generations
from app.modules.feedback.router import router as feedback_router
from app.modules.handoff.router import router as handoff_router
from app.modules.ingestion.router import router as ingestion_router
from app.modules.ingestion.upload_limit import UploadLimitMiddleware
from app.modules.knowledge.router import router as knowledge_router
from app.modules.providers.factory import create_provider
from app.modules.rag.service import RAGService
from app.modules.retrieval.embedding import BGEEmbedder
from app.modules.retrieval.service import RetrievalService

request_logger = logging.getLogger("app.requests")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else Settings()
    engine = create_db_engine(settings)
    configure_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        recovery_operation_id = uuid4()
        try:
            try:
                await run_in_threadpool(
                    recover_generations, app.state.session_factory, app.state.chat_clock()
                )
                app.state.chat_ready = True
            except SQLAlchemyError:
                # Liveness remains available, but no chat traffic starts after failed recovery.
                log_failure(
                    logging.getLogger("app.lifecycle"),
                    "chat_recovery_failed",
                    "CHAT_RECOVERY_FAILED",
                    request_id=None,
                    operation_id=recovery_operation_id,
                )
            yield
        finally:
            try:
                await app.state.chat_runtime.shutdown()
            finally:
                engine.dispose()

    app = FastAPI(title="Knowledge QA API", lifespan=lifespan)
    app.add_middleware(UploadLimitMiddleware)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    app.state.auth_clock = lambda: datetime.now(UTC)
    app.state.chat_clock = lambda: datetime.now(UTC)
    app.state.chat_ready = False
    app.state.chat_runtime = ChatRuntime(max_active=settings.chat_global_concurrency)
    retrieval = RetrievalService(
        app.state.session_factory,
        BGEEmbedder(settings.embedding_model_path),
        threshold=settings.retrieval_threshold,
    )
    app.state.chat_rag = RAGService(retrieval.search, retrieval.validate_hits, create_provider())
    app.state.login_limiter = LoginLimiter(
        account_limit=settings.login_account_limit,
        ip_limit=settings.login_ip_limit,
        window_seconds=settings.login_window_seconds,
        max_entries=settings.login_max_entries,
    )
    app.include_router(analytics_router)
    app.include_router(auth_router)
    app.include_router(knowledge_router)
    app.include_router(ingestion_router)
    app.include_router(chat_router)
    app.include_router(feedback_router)
    app.include_router(handoff_router)

    @app.exception_handler(AuthError)
    async def auth_error(request: Request, exc: AuthError):
        return error_response(request, exc.status, exc.code, exc.message)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        try:
            request_id = str(UUID(request.headers.get("X-Request-ID", "")))
        except ValueError:
            request_id = str(uuid4())
        request.state.request_id = request_id
        token = request_id_context.set(request_id)
        try:
            try:
                if request.url.path.startswith("/api/v1/") and request.method not in (
                    "GET",
                    "HEAD",
                    "OPTIONS",
                ):
                    await run_in_threadpool(check_csrf, request)
                response = await call_next(request)
            except AuthError as exc:
                response = error_response(request, exc.status, exc.code, exc.message)
            except Exception:
                response = error_response(request, 500, "INTERNAL_ERROR", "服务暂时不可用")
            response.headers["X-Request-ID"] = request_id
            if request.url.path.startswith("/api/v1/"):
                response.headers["Cache-Control"] = "no-store"
            route = request.scope.get("route")
            log_http(
                request_logger,
                request_id=request_id,
                method=request.method,
                route=getattr(route, "path", "<unmatched>"),
                status_code=response.status_code,
                error_code=getattr(request.state, "error_code", None),
            )
            return response
        finally:
            request_id_context.reset(token)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        status = HTTPStatus(exc.status_code)
        response = error_response(request, exc.status_code, status.name, status.phrase)
        if exc.headers:
            response.headers.update(exc.headers)
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return error_response(
            request,
            422,
            "VALIDATION_ERROR",
            "请求参数无效",
            details=[
                {"location": list(error["loc"]), "code": error["type"]} for error in exc.errors()
            ],
        )

    @app.get("/health/live")
    def liveness():
        return {"status": "ok"}

    @app.get("/health/ready")
    def readiness(request: Request):
        if not app.state.chat_ready:
            return error_response(request, 503, "DEPENDENCY_UNAVAILABLE", "服务启动恢复尚未完成")
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except SQLAlchemyError:
            return error_response(request, 503, "DEPENDENCY_UNAVAILABLE", "数据库暂不可用")
        return {"status": "ready"}

    return app
