from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text


def test_migrations_upgrade_repeatedly_and_enable_pgvector(migrated_engine):
    config = Config("alembic.ini")
    with migrated_engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
        assert "audit_events" in inspect(connection).get_table_names()
        assert connection.scalar(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        )
        distance = connection.scalar(text("SELECT '[1,0,0]'::vector <=> '[1,0,0]'::vector"))
        assert distance == 0


def test_offline_upgrade_generates_postgresql_schema_without_connecting(monkeypatch, tmp_path):
    from io import StringIO

    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://unused:unused@127.0.0.1:1/test")
    monkeypatch.setenv("SESSION_SECRET", "test-only-secret")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    output = StringIO()
    config = Config("alembic.ini", output_buffer=output)
    command.upgrade(config, "head", sql=True)
    sql = output.getvalue()
    assert "CREATE TABLE audit_events" in sql
    assert "CREATE EXTENSION IF NOT EXISTS vector" in sql
    assert "TIMESTAMP WITH TIME ZONE" in sql


def test_migrated_schema_matches_models_without_deleting_version_table(migrated_engine):
    config = Config("alembic.ini")
    with migrated_engine.begin() as connection:
        config.attributes["connection"] = connection
        command.check(config)
