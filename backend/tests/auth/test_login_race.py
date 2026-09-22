from concurrent.futures import ThreadPoolExecutor
from threading import Event

from fastapi.testclient import TestClient

from .conftest import csrf, login, register


def test_disabled_during_password_check_cannot_create_session(client, admin, auth_app, monkeypatch):
    from app.modules.auth import service

    entered, proceed = Event(), Event()
    verify = service.verify_password
    with TestClient(auth_app) as other:
        target = register(other).json()

        def paused_verify(*args):
            entered.set()
            assert proceed.wait(10)
            return verify(*args)

        monkeypatch.setattr(service, "verify_password", paused_verify)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(login, other, target["username"])
            assert entered.wait(10)
            try:
                assert (
                    client.patch(
                        f"/api/v1/admin/users/{target['id']}",
                        json={"is_active": False},
                        headers=csrf(client),
                    ).status_code
                    == 200
                )
            finally:
                proceed.set()
            assert pending.result().status_code == 401
        assert (
            client.patch(
                f"/api/v1/admin/users/{target['id']}",
                json={"is_active": True},
                headers=csrf(client),
            ).status_code
            == 200
        )
        assert other.get("/api/v1/auth/me").status_code == 401
