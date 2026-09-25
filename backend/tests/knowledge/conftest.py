import pytest
from fastapi.testclient import TestClient

from tests.auth import conftest as auth_fixtures
from tests.auth.conftest import csrf, login, register

admin = auth_fixtures.admin
auth_app = auth_fixtures.auth_app
client = auth_fixtures.client
user = auth_fixtures.user


@pytest.fixture
def reader(auth_app):
    with TestClient(auth_app) as other:
        person = register(other).json()
        assert login(other, person["username"]).status_code == 200
        yield other, person


def create_kb(client, **changes):
    response = client.post(
        "/api/v1/knowledge-bases",
        json={
            "name": "虚构校园服务",
            "description": "仅测试",
            "visibility": "restricted",
            **changes,
        },
        headers=csrf(client),
    )
    assert response.status_code == 201, response.text
    return response.json()


def members(client, kb, ids):
    return client.put(
        f"/api/v1/knowledge-bases/{kb['id']}/members",
        json={"user_ids": ids, "expected_version": kb["version"]},
        headers=csrf(client),
    )


def create_faq(client, kb, **changes):
    response = client.post(
        f"/api/v1/knowledge-bases/{kb['id']}/faqs",
        json={"question": "虚构图书馆何时开放？", "answer": "本样例设定为九点。", **changes},
        headers=csrf(client),
    )
    assert response.status_code == 201, response.text
    return response.json()
