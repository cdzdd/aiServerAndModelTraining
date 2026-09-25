from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import text

from .conftest import create_faq, create_kb, csrf, members


def test_scoped_lists_details_and_immediate_revocation(client, admin, reader):
    other, person = reader
    allowed = create_kb(client)
    denied = create_kb(client)
    public = create_kb(client, visibility="public")
    faq = create_faq(client, allowed)
    granted = members(client, allowed, [person["id"]])
    assert granted.status_code == 200
    assert granted.json()["version"] == 2
    visible = other.get("/api/v1/knowledge-bases").json()
    ids = {item["id"] for item in visible["items"]}
    assert {allowed["id"], public["id"]} <= ids
    assert denied["id"] not in ids
    assert other.get(f"/api/v1/knowledge-bases/{allowed['id']}").status_code == 200
    assert other.get(f"/api/v1/knowledge-bases/{denied['id']}").status_code == 404
    assert other.get(f"/api/v1/knowledge-bases/{denied['id']}/faqs").status_code == 404
    assert (
        other.get(f"/api/v1/knowledge-bases/{allowed['id']}/faqs").json()["items"][0]["id"]
        == faq["id"]
    )
    assert members(client, {**allowed, "version": 2}, []).status_code == 200
    assert other.get(f"/api/v1/knowledge-bases/{allowed['id']}").status_code == 404
    assert other.get(f"/api/v1/knowledge-bases/{allowed['id']}/faqs").status_code == 404
    assert other.get("/api/v1/auth/me").status_code == 200


@pytest.mark.parametrize("role", ["user", "agent"])
def test_read_roles_cannot_mutate_or_enumerate_members(
    client, admin, reader, migrated_engine, role
):
    other, person = reader
    with migrated_engine.begin() as db:
        db.execute(
            text("UPDATE users SET role=:role WHERE id=:id"), {"role": role, "id": person["id"]}
        )
    kb = create_kb(client)
    faq = create_faq(client, kb)
    assert members(client, kb, [person["id"]]).status_code == 200
    assert other.get(f"/api/v1/knowledge-bases/{kb['id']}").status_code == 200
    for method, path, body in [
        ("POST", "/knowledge-bases", {"name": "bad", "visibility": "public"}),
        ("PATCH", f"/knowledge-bases/{kb['id']}", {"name": "bad", "expected_version": 2}),
        ("PUT", f"/knowledge-bases/{kb['id']}/members", {"user_ids": [], "expected_version": 2}),
        ("POST", f"/knowledge-bases/{kb['id']}/faqs", {"question": "bad", "answer": "bad"}),
        ("PATCH", f"/faqs/{faq['id']}", {"answer": "bad", "expected_version": 1}),
        ("DELETE", f"/faqs/{faq['id']}", None),
    ]:
        response = other.request(method, "/api/v1" + path, json=body, headers=csrf(other))
        assert response.status_code == 403
    assert other.get(f"/api/v1/knowledge-bases/{kb['id']}/members").status_code == 403
    assert other.get("/api/v1/admin/knowledge-bases").status_code == 403
    assert client.get(f"/api/v1/knowledge-bases/{kb['id']}").json()["name"] == kb["name"]
    assert (
        client.get(f"/api/v1/knowledge-bases/{kb['id']}/faqs").json()["items"][0]["answer"]
        == faq["answer"]
    )


def test_membership_conflicts_are_atomic_and_bad_users_rejected(client, admin, reader):
    _, person = reader
    kb = create_kb(client)
    assert members(client, kb, [person["id"]]).status_code == 200
    assert members(client, kb, []).status_code == 409
    assert members(client, {**kb, "version": 2}, [str(uuid4())]).status_code == 422
    result = client.get(f"/api/v1/knowledge-bases/{kb['id']}/members").json()
    assert result == {"user_ids": [person["id"]], "version": 2}
    assert members(client, {**kb, "version": 2}, [person["id"], person["id"]]).status_code == 422


def test_concurrent_membership_replacements_have_one_winner(client, admin, reader):
    _, person = reader
    kb = create_kb(client)
    headers = csrf(client)

    def replace(ids):
        return client.put(
            f"/api/v1/knowledge-bases/{kb['id']}/members",
            json={"user_ids": ids, "expected_version": 1},
            headers=headers,
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(replace, [person["id"]])
        second = pool.submit(replace, [])
        assert sorted([first.result(), second.result()]) == [200, 409]


def test_disable_blocks_all_readers_but_admin_can_restore(client, admin, reader):
    other, _ = reader
    kb = create_kb(client, visibility="public")
    create_faq(client, kb)
    path = f"/api/v1/knowledge-bases/{kb['id']}"
    result = client.patch(
        path, json={"is_active": False, "expected_version": 1}, headers=csrf(client)
    )
    assert result.status_code == 200
    for c in (client, other):
        assert c.get(path).status_code == 404
        assert c.get(path + "/faqs").status_code == 404
        assert kb["id"] not in {
            item["id"] for item in c.get("/api/v1/knowledge-bases").json()["items"]
        }
    managed = client.get("/api/v1/admin/knowledge-bases?page_size=100").json()
    assert any(item["id"] == kb["id"] and not item["is_active"] for item in managed["items"])
    assert (
        client.patch(
            path, json={"is_active": True, "expected_version": 2}, headers=csrf(client)
        ).status_code
        == 200
    )
    assert other.get(path).status_code == 200
    assert (
        client.patch(
            path, json={"name": "stale", "expected_version": 1}, headers=csrf(client)
        ).status_code
        == 409
    )


@pytest.mark.parametrize(
    "body",
    [
        {"name": " "},
        {"name": "x" * 101},
        {"description": "x" * 2001},
        {"name": "\u0000"},
        {"visibility": "private"},
        {"role": "admin"},
        {"is_active": "false"},
    ],
)
def test_bad_knowledge_input_rejected(client, admin, body):
    response = client.post(
        "/api/v1/knowledge-bases",
        json={"name": "测试", "visibility": "public", **body},
        headers=csrf(client),
    )
    assert response.status_code == 422


def test_anonymous_pagination_and_no_cache(client, admin, auth_app):
    from uuid import uuid4

    from fastapi.testclient import TestClient

    with TestClient(auth_app) as anonymous:
        assert anonymous.get("/api/v1/knowledge-bases").status_code == 401
        assert anonymous.get(f"/api/v1/knowledge-bases/{uuid4()}").status_code == 401
    create_kb(client)
    response = client.get("/api/v1/knowledge-bases?page_size=1")
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1
    assert response.json()["page_size"] == 1
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/api/v1/knowledge-bases?page_size=101").status_code == 422


def test_all_writes_require_csrf_and_same_origin(client, admin, reader):
    _, person = reader
    kb = create_kb(client)
    faq = create_faq(client, kb)
    for method, path, data in [
        ("POST", "/knowledge-bases", {"name": "bad"}),
        ("PATCH", f"/knowledge-bases/{kb['id']}", {"name": "bad", "expected_version": 1}),
        (
            "PUT",
            f"/knowledge-bases/{kb['id']}/members",
            {"user_ids": [person["id"]], "expected_version": 1},
        ),
        ("POST", f"/knowledge-bases/{kb['id']}/faqs", {"question": "bad", "answer": "bad"}),
        ("PATCH", f"/faqs/{faq['id']}", {"answer": "bad", "expected_version": 1}),
        ("DELETE", f"/faqs/{faq['id']}", None),
    ]:
        for headers in ({}, {**csrf(client), "Origin": "https://attacker.invalid"}):
            assert (
                client.request(method, "/api/v1" + path, json=data, headers=headers).status_code
                == 403
            )
    assert client.get(f"/api/v1/knowledge-bases/{kb['id']}/members").json()["user_ids"] == []
    assert client.get(f"/api/v1/knowledge-bases/{kb['id']}/faqs").json()["items"][0]["version"] == 1
