import json
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
from app.core.security import AuthError
from app.modules.auth.limits import LoginLimiter
from app.modules.auth.router import router as auth_router
from app.modules.auth.service import check_csrf
from app.modules.ingestion.router import router as ingestion_router
from app.modules.ingestion.upload_limit import UploadLimitMiddleware
from app.modules.knowledge.router import router as knowledge_router

request_logger = logging.getLogger("app.requests")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else Settings()
    engine = create_db_engine(settings)
    request_logger.setLevel(logging.INFO)
    if not request_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        request_logger.addHandler(handler)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            yield
        finally:
            engine.dispose()

    app = FastAPI(title="Knowledge QA API", lifespan=lifespan)
    app.add_middleware(UploadLimitMiddleware)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    app.state.auth_clock = lambda: datetime.now(UTC)
    app.state.login_limiter = LoginLimiter(
        account_limit=settings.login_account_limit,
        ip_limit=settings.login_ip_limit,
        window_seconds=settings.login_window_seconds,
        max_entries=settings.login_max_entries,
    )
    app.include_router(auth_router)
    app.include_router(knowledge_router)
    app.include_router(ingestion_router)

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
        request_logger.info(
            json.dumps(
                {
                    "event": "http_request",
                    "request_id": request_id,
                    "method": request.method,
                    "route": getattr(route, "path", "<unmatched>"),
                    "status_code": response.status_code,
                }
            )
        )
        return response

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
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except SQLAlchemyError:
            return error_response(request, 503, "DEPENDENCY_UNAVAILABLE", "数据库暂不可用")
        return {"status": "ready"}

    return app
