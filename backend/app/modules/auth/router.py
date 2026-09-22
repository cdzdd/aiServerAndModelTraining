from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import (
    PRELOGIN_COOKIE,
    PRELOGIN_SECONDS,
    SESSION_COOKIE,
    SESSION_SECONDS,
    csrf_token,
    new_prelogin,
)
from app.modules.auth import service
from app.modules.auth.models import User
from app.modules.auth.schemas import LoginInput, LoginResult, RegisterInput, UserSummary

router = APIRouter(prefix="/api/v1")
Database = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(service.current_user)]


def set_cookie(response: Response, request: Request, name: str, value: str, seconds: int):
    response.set_cookie(
        name,
        value,
        max_age=seconds,
        httponly=True,
        secure=request.app.state.settings.app_env == "production",
        samesite="lax",
        path="/",
    )


def clear_cookie(response: Response, request: Request, name: str):
    response.delete_cookie(
        name,
        httponly=True,
        secure=request.app.state.settings.app_env == "production",
        samesite="lax",
        path="/",
    )


@router.get("/auth/csrf")
def get_csrf(request: Request, response: Response, db: Database):
    secret = request.app.state.settings.session_secret.get_secret_value()
    binding = service.csrf_binding(db, request)
    if binding is None:
        binding = new_prelogin(secret, request.app.state.auth_clock().timestamp())
        set_cookie(response, request, PRELOGIN_COOKIE, binding, PRELOGIN_SECONDS)
    return {"csrf_token": csrf_token(secret, binding)}


@router.post("/auth/register", status_code=201, response_model=UserSummary)
def register(data: RegisterInput, request: Request, db: Database):
    return service.register_user(db, request, data)


@router.post("/auth/login", response_model=LoginResult)
def login(data: LoginInput, request: Request, response: Response, db: Database):
    user, raw = service.login_user(db, request, data.username, data.password.get_secret_value())
    set_cookie(response, request, SESSION_COOKIE, raw, SESSION_SECONDS)
    clear_cookie(response, request, PRELOGIN_COOKIE)
    return {
        "user": user,
        "csrf_token": csrf_token(request.app.state.settings.session_secret.get_secret_value(), raw),
    }


@router.get("/auth/me", response_model=UserSummary)
def me(user: CurrentUser):
    return user


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, db: Database, user: CurrentUser):
    service.revoke_cookie(db, request)
    service.audit(db, request, "auth.logout", user)
    db.commit()
    clear_cookie(response, request, SESSION_COOKIE)
    clear_cookie(response, request, PRELOGIN_COOKIE)
