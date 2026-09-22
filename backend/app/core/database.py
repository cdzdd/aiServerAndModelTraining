from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from app.core.config import Settings


def create_db_engine(settings: Settings) -> Engine:
    return create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        hide_parameters=True,
        connect_args={"connect_timeout": 3},
    )


def get_db(request: Request) -> Iterator[Session]:
    """Callers own their transaction and must commit explicitly when writing."""
    with request.app.state.session_factory() as session:
        yield session
