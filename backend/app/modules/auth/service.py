import hmac
import secrets
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.database import get_db
from app.core.security import (
    PRELOGIN_COOKIE,
    SESSION_COOKIE,
    SESSION_SECONDS,
    AuthError,
    csrf_token,
    dummy_password_hash,
    origin,
    password_hasher,
    token_hash,
    valid_prelogin,
    verify_password,
)
from app.modules.auth.models import AuthSession, User
from app.modules.auth.schemas import Actor, RegisterInput


def audit(db, request, action, user=None, outcome="success", metadata=None):
    record_audit(
        db,
        actor_id=user.id if user else None,
        action=action,
        target_type="user",
        target_id=str(user.id) if user else None,
        outcome=outcome,
        request_id=request.state.request_id,
        metadata=metadata or {},
    )


def find_session(db: Session, request: Request):
    raw = request.cookies.get(SESSION_COOKIE, "")
    if not raw or len(raw) > 128:
        return None
    return db.execute(
        select(AuthSession, User)
        .join(User, User.id == AuthSession.user_id)
        .where(
            AuthSession.token_hash == token_hash(raw),
            AuthSession.expires_at > request.app.state.auth_clock(),
            User.is_active.is_(True),
        )
    ).first()


def current_user(request: Request, db: Annotated[Session, Depends(get_db)]) -> User:
    row = find_session(db, request)
    if row is None:
        raise AuthError(401, "UNAUTHENTICATED", "请先登录")
    return row[1]


def current_actor(user: Annotated[User, Depends(current_user)]) -> Actor:
    return Actor(user_id=user.id, role=user.role)


def csrf_binding(db: Session, request: Request) -> str | None:
    if find_session(db, request) is not None:
        return request.cookies[SESSION_COOKIE]
    raw = request.cookies.get(PRELOGIN_COOKIE, "")
    secret = request.app.state.settings.session_secret.get_secret_value()
    if len(raw) < 256 and valid_prelogin(secret, raw, request.app.state.auth_clock().timestamp()):
        return raw
    return None


def check_csrf(request: Request) -> None:
    settings = request.app.state.settings
    expected = origin(settings.public_origin or str(request.base_url))
    supplied = request.headers.get("origin")
    if supplied is None:
        supplied = request.headers.get("referer", "")
    if not expected or origin(supplied) != expected:
        raise AuthError(403, "CSRF_FAILED", "请求来源或安全令牌无效")
    with request.app.state.session_factory() as db:
        binding = csrf_binding(db, request)
    candidate = request.headers.get("x-csrf-token", "")
    expected_token = csrf_token(settings.session_secret.get_secret_value(), binding or "")
    if not binding or len(candidate) != 64 or not hmac.compare_digest(candidate, expected_token):
        raise AuthError(403, "CSRF_FAILED", "请求来源或安全令牌无效")


def register_user(db: Session, request: Request, data: RegisterInput) -> User:
    user = User(
        username=data.username,
        display_name=data.display_name,
        password_hash=password_hasher.hash(data.password.get_secret_value()),
        role="user",
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise AuthError(409, "CONFLICT", "用户名不可用") from None
    audit(db, request, "auth.register", user)
    db.commit()
    return user


def revoke_cookie(db: Session, request: Request):
    raw = request.cookies.get(SESSION_COOKIE, "")
    if raw:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == token_hash(raw)))


def login_user(db: Session, request: Request, username: str, password: str):
    user = db.scalar(select(User).where(User.username == username))
    valid = verify_password(user.password_hash if user else dummy_password_hash(), password)
    if not valid or user is None or not user.is_active:
        audit(db, request, "auth.login", outcome="failure")
        db.commit()
        raise AuthError(401, "INVALID_CREDENTIALS", "用户名或密码错误")
    if password_hasher.check_needs_rehash(user.password_hash):
        user.password_hash = password_hasher.hash(password)
    revoke_cookie(db, request)
    now = request.app.state.auth_clock()
    db.execute(delete(AuthSession).where(AuthSession.expires_at <= now))
    raw = secrets.token_urlsafe(32)
    db.add(
        AuthSession(
            user_id=user.id,
            token_hash=token_hash(raw),
            created_at=now,
            expires_at=now + timedelta(seconds=SESSION_SECONDS),
        )
    )
    audit(db, request, "auth.login", user)
    db.commit()
    return user, raw
