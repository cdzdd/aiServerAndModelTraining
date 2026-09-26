"""App wiring must preserve health checks and isolate injected databases."""

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError


def settings_for(engine, tmp_path):
    from app.core.config import Settings

    return Settings(
        _env_file=None,
        APP_ENV="test",
        DATABASE_URL=engine.url.render_as_string(hide_password=False),
        SESSION_SECRET="chat-startup-test-only-secret",
        UPLOAD_DIR=tmp_path,
        EMBEDDING_MODEL_PATH=str(tmp_path / "model"),
        RETRIEVAL_THRESHOLD=0.12,
    )


def test_each_app_owns_its_retrieval_database_and_runtime(migrated_engine, tmp_path):
    from app.main import create_app

    first = create_app(settings_for(migrated_engine, tmp_path))
    second = create_app(settings_for(migrated_engine, tmp_path))
    try:
        retrieval = first.state.chat_rag.retriever.__self__
        assert retrieval.session_factory is first.state.session_factory
        assert retrieval.threshold == 0.12
        assert retrieval.embedder.model_path == tmp_path / "model"
        assert first.state.chat_runtime is not second.state.chat_runtime
        assert first.state.chat_rag is not second.state.chat_rag
    finally:
        first.state.engine.dispose()
        second.state.engine.dispose()


def test_failed_recovery_keeps_liveness_but_blocks_readiness(
    migrated_engine,
    tmp_path,
    monkeypatch,
    caplog,
):
    import app.main as main

    def failed_recovery(*args, **kwargs):
        raise OperationalError("private-startup-query", {}, Exception("private-startup-secret"))

    monkeypatch.setattr(main, "recover_generations", failed_recovery, raising=False)
    app = main.create_app(settings_for(migrated_engine, tmp_path))
    with TestClient(app) as client:
        live = client.get("/health/live")
        ready = client.get("/health/ready")
        assert live.status_code == 200
        assert ready.status_code == 503
        assert ready.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
        assert app.state.chat_ready is False
    assert "private-startup-query" not in caplog.text + ready.text
    assert "private-startup-secret" not in caplog.text + ready.text
