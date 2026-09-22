from concurrent.futures import ThreadPoolExecutor

import pytest

from app.core.security import AuthError

from .conftest import csrf, login


def test_five_failures_then_429_and_window_recovers(client, user, auth_app):
    now = [1000.0]
    auth_app.state.login_limiter.clock = lambda: now[0]
    for _ in range(5):
        assert (
            login(client, "  " + user["username"].upper(), "wrong-password-123").status_code == 401
        )
    assert login(client, user["username"]).status_code == 429
    now[0] += 301
    assert login(client, user["username"]).status_code == 200


def test_ip_limit_and_forwarded_ip_spoofing(client, auth_app):
    from app.modules.auth.limits import LoginLimiter

    auth_app.state.login_limiter = LoginLimiter(account_limit=5, ip_limit=2)
    for i in range(2):
        assert login(client, f"unknown-{i}", "wrong-password-123").status_code == 401
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "unknown-3", "password": "wrong-password-123"},
        headers={**csrf(client), "X-Forwarded-For": "192.0.2.99"},
    )
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "RATE_LIMITED"


def test_successful_logins_also_count_toward_ip_limit(client, user, auth_app):
    from app.modules.auth.limits import LoginLimiter

    auth_app.state.login_limiter = LoginLimiter(account_limit=5, ip_limit=2)
    assert login(client, user["username"]).status_code == 200
    assert login(client, user["username"]).status_code == 200
    assert login(client, user["username"]).status_code == 429


def test_concurrent_reservations_cannot_bypass_account_limit():
    from app.modules.auth.limits import LoginLimiter

    limiter = LoginLimiter(account_limit=5, ip_limit=30)

    def attempt(_):
        try:
            return limiter.reserve("127.0.0.1", "alice")
        except AuthError:
            return None

    with ThreadPoolExecutor(max_workers=12) as pool:
        reservations = list(pool.map(attempt, range(12)))
    accepted = [r for r in reservations if r is not None]
    assert len(accepted) == 5
    for reservation in accepted:
        limiter.finish(reservation, failed=True)
    with pytest.raises(AuthError) as error:
        limiter.reserve("127.0.0.1", "alice")
    assert error.value.status == 429


def test_bounded_storage_keeps_live_limits_and_recovers_after_cleanup():
    from app.modules.auth.limits import LoginLimiter

    now = [0.0]
    limiter = LoginLimiter(account_limit=1, max_entries=2, window_seconds=300, clock=lambda: now[0])
    ticket = limiter.reserve("ip1", "alice")
    limiter.finish(ticket, failed=True)
    for ip, username in [("ip2", "bob"), ("ip1", "alice")]:
        with pytest.raises(AuthError):
            limiter.reserve(ip, username)
    now[0] = 301
    assert limiter.reserve("ip2", "bob") is not None


def test_completed_success_frees_pending_account_slot_but_does_not_reset_failures():
    from app.modules.auth.limits import LoginLimiter

    limiter = LoginLimiter(account_limit=2)
    limiter.finish(limiter.reserve("ip", "alice"), failed=True)
    limiter.finish(limiter.reserve("ip", "alice"), failed=False)
    limiter.finish(limiter.reserve("ip", "alice"), failed=True)
    with pytest.raises(AuthError):
        limiter.reserve("ip", "alice")


def test_throttled_ip_cannot_fill_capacity_with_new_usernames():
    from app.modules.auth.limits import LoginLimiter

    limiter = LoginLimiter(ip_limit=1, max_entries=4)
    limiter.finish(limiter.reserve("ip1", "alice"), failed=True)
    for i in range(10):
        with pytest.raises(AuthError):
            limiter.reserve("ip1", f"other-{i}")
    assert limiter.reserve("ip2", "bob") is not None
