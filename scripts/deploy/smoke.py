"""Local same-origin smoke; --auth creates one synthetic ordinary test account."""

import argparse
import json
import secrets
from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener
from uuid import uuid4


class SmokeError(RuntimeError):
    pass


def probe(base_url, *, origin=None, auth=False):
    origin = origin or base_url
    cookies = CookieJar()
    client = build_opener(HTTPCookieProcessor(cookies))

    def request(route, *, method="GET", payload=None, token=None, status=200, html=False):
        headers = {"Origin": origin}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if token:
            headers["X-CSRF-Token"] = token
        req = Request(
            base_url.rstrip("/") + route,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers=headers,
            method=method,
        )
        try:
            response = client.open(req, timeout=15)
        except HTTPError as exc:
            response = exc
        except URLError:
            raise SmokeError(f"Cannot connect at {route}") from None
        with response:
            if response.status != status:
                raise SmokeError(
                    f"Unexpected status at {route}: {response.status}, expected {status}"
                )
            body = response.read()
            if status == 204:
                return None
            if html:
                if (
                    "text/html" not in response.headers.get("Content-Type", "")
                    or b'id="app"' not in body
                ):
                    raise SmokeError(f"Application HTML missing at {route}")
                return None
            if "application/json" not in response.headers.get("Content-Type", ""):
                raise SmokeError(f"JSON missing at {route}; check reverse proxy routing")
            try:
                return json.loads(body)
            except ValueError:
                raise SmokeError(f"Invalid JSON at {route}") from None

    for route, expected in [("/health/live", "ok"), ("/health/ready", "ready")]:
        if request(route).get("status") != expected:
            raise SmokeError(f"Dependency not ready at {route}")
    for route in ["/login", "/chat/test-deep-link", "/admin/users"]:
        request(route, html=True)
    request("/api/v1/runtime-missing", status=404)
    print("PASS health, frontend deep links, API routing")
    if not auth:
        return
    username = "runtime-smoke-" + uuid4().hex[:12]
    password = secrets.token_hex(24)
    csrf = request("/api/v1/auth/csrf")["csrf_token"]
    request(
        "/api/v1/auth/register", method="POST", token=csrf, status=201,
        payload={"username": username, "password": password, "display_name": "本地验收账号"},
    )
    login = request(
        "/api/v1/auth/login", method="POST", token=csrf,
        payload={"username": username, "password": password},
    )
    if request("/api/v1/auth/me")["id"] != login["user"]["id"]:
        raise SmokeError("Session identity was not restored")
    session = next((cookie for cookie in cookies if cookie.name == "qa_session"), None)
    if session is None or not session.has_nonstandard_attr("HttpOnly"):
        raise SmokeError("HttpOnly session cookie missing")
    if session.get_nonstandard_attr("SameSite", "").lower() != "lax":
        raise SmokeError("SameSite session cookie missing")
    request("/api/v1/auth/logout", method="POST", token="invalid", status=403)
    request("/api/v1/auth/me")
    request("/api/v1/auth/logout", method="POST", token=login["csrf_token"], status=204)
    request("/api/v1/auth/me", status=401)
    print("PASS real registration/login/session, HttpOnly/SameSite, rejected CSRF, logout")
    print("Created one synthetic ordinary account; no credentials were retained or printed.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url")
    parser.add_argument("--origin")
    parser.add_argument("--auth", action="store_true")
    args = parser.parse_args()
    try:
        probe(args.base_url, origin=args.origin, auth=args.auth)
    except SmokeError as exc:
        print(f"FAIL {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
