import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from dotenv import dotenv_values
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateSchema, DropSchema


@pytest.fixture(scope="session")
def database_url():
    root_env = Path(__file__).resolve().parents[2] / ".env"
    value = os.environ.get("TEST_DATABASE_URL") or dotenv_values(root_env).get("TEST_DATABASE_URL")
    if not value:
        pytest.fail("TEST_DATABASE_URL is required for real PostgreSQL/pgvector tests")
    if make_url(value).drivername != "postgresql+psycopg":
        pytest.fail("TEST_DATABASE_URL must use postgresql+psycopg")
    return SecretStr(value)


@pytest.fixture(scope="session")
def migrated_engine(database_url):
    # Only this unique, freshly-created schema is ever dropped. No development tables are touched.
    schema = f"test_{uuid4().hex}"
    admin_engine = create_engine(database_url.get_secret_value(), hide_parameters=True)
    with admin_engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    scoped_url = make_url(database_url.get_secret_value()).update_query_dict(
        {"options": f"-csearch_path={schema},public"}
    )
    engine = create_engine(scoped_url, hide_parameters=True)
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            command.upgrade(config, "head")
        yield engine
    finally:
        engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        admin_engine.dispose()
