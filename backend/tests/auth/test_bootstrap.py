import io
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from .conftest import PASSWORD


def test_bootstrap_interactive_hidden_passwords_and_repeat(auth_app, monkeypatch, capsys):
    from app.modules.auth import bootstrap_admin

    answers = iter([f"admin-{uuid4().hex[:10]}"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    hidden_prompts = []

    def hidden(prompt):
        hidden_prompts.append(prompt)
        return PASSWORD

    monkeypatch.setattr(bootstrap_admin, "getpass", hidden)
    monkeypatch.setattr(bootstrap_admin, "Settings", lambda: auth_app.state.settings)
    assert bootstrap_admin.main([]) == 0
    assert len(hidden_prompts) == 2
    assert bootstrap_admin.main([]) == 1
    output = capsys.readouterr()
    assert "已初始化" in output.out + output.err
    assert PASSWORD not in output.out + output.err


def test_bootstrap_stdin_password_and_arguments_do_not_leak(auth_app, monkeypatch, capsys):
    from app.modules.auth import bootstrap_admin

    monkeypatch.setattr("builtins.input", lambda prompt: f"admin-{uuid4().hex[:10]}")
    monkeypatch.setattr(bootstrap_admin.sys, "stdin", io.StringIO(PASSWORD + "\n"))
    monkeypatch.setattr(bootstrap_admin, "Settings", lambda: auth_app.state.settings)
    assert bootstrap_admin.main(["--stdin-password"]) == 0
    assert PASSWORD not in capsys.readouterr().out
    with pytest.raises(SystemExit):
        bootstrap_admin.main(["--password", PASSWORD])
    output = capsys.readouterr()
    assert PASSWORD not in output.out + output.err


def test_mismatched_passwords_create_no_admin(auth_app, monkeypatch, migrated_engine):
    from app.modules.auth import bootstrap_admin

    monkeypatch.setattr("builtins.input", lambda prompt: "first-admin")
    passwords = iter([PASSWORD, "different-password"])
    monkeypatch.setattr(bootstrap_admin, "getpass", lambda prompt: next(passwords))
    monkeypatch.setattr(bootstrap_admin, "Settings", lambda: auth_app.state.settings)
    assert bootstrap_admin.main([]) == 1
    with migrated_engine.connect() as db:
        assert (
            db.execute(text("SELECT count(*) FROM users WHERE role='admin' AND is_active")).scalar()
            == 0
        )


def test_concurrent_bootstrap_creates_only_one_admin(auth_app, migrated_engine):
    from app.core.security import AuthError
    from app.modules.auth.bootstrap_admin import bootstrap
    from app.modules.auth.schemas import RegisterInput

    def initialize():
        with Session(migrated_engine) as db:
            try:
                return bootstrap(
                    db,
                    RegisterInput(
                        username=f"admin-{uuid4().hex[:10]}",
                        password=PASSWORD,
                        display_name="管理员",
                    ),
                ).role
            except AuthError as exc:
                return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: initialize(), range(2)))
    assert sorted(results) == ["ALREADY_INITIALIZED", "admin"]
