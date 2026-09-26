import pytest


@pytest.mark.parametrize("path", ["/api/v1/admin/stats", "/api/v1/admin/audit-events"])
def test_analytics_requires_authentication(client, path):
    assert client.get(path).status_code == 401


@pytest.mark.parametrize("path", ["/api/v1/admin/stats", "/api/v1/admin/audit-events"])
def test_analytics_rejects_nonadmin(client, signed_in, path):
    assert client.get(path).status_code == 403


def test_audit_projection_filters_pagination_and_null_actor(client, admin, auth_app):
    from datetime import timedelta
    from uuid import UUID, uuid4

    from app.core.models import AuditEvent
    from tests.analytics.metrics_helpers import PARAMS, START

    target = uuid4()
    with auth_app.state.session_factory() as db:
        for i in range(3):
            db.add(
                AuditEvent(
                    id=UUID(int=i + 1),
                    actor_id=None,
                    action="feedback.resolve",
                    target_type="feedback",
                    target_id=str(target),
                    outcome="success",
                    request_id="safe-id",
                    created_at=START + timedelta(hours=1),
                    event_metadata={
                        "rating": "down",
                        "status": "resolved",
                        "changed_fields": ["resolution", "secret-sentinel"],
                        "resolution": "secret-sentinel",
                        "conversation_id": {"nested": "secret-sentinel"},
                        "other": "secret-sentinel",
                    },
                )
            )
        db.commit()
    query = {**PARAMS, "action": "feedback.resolve", "target_id": str(target), "page_size": 2}
    response = client.get("/api/v1/admin/audit-events", params=query)
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert [item["id"] for item in data["items"]] == [str(UUID(int=3)), str(UUID(int=2))]
    item = data["items"][0]
    assert item["actor_id"] is None
    assert item["metadata"] == {
        "rating": "down",
        "status": "resolved",
        "changed_fields": ["resolution"],
    }
    assert "secret-sentinel" not in response.text
    assert client.get(f"/api/v1/admin/audit-events/{item['id']}").json() == item
    assert (
        len(client.get("/api/v1/admin/audit-events", params={**query, "page": 2}).json()["items"])
        == 1
    )
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "raw",
    [
        {"version": True, "member_count": -1, "fields": ["name", {"bad": "secret"}]},
        {"version": "secret", "before": {"role": "secret"}},
    ],
)
def test_metadata_values_are_checked_not_just_key_names(raw):
    from app.modules.analytics.service import safe_metadata

    result = safe_metadata("knowledge.update", raw)
    assert "version" not in result and "member_count" not in result
    assert "secret" not in str(result)


@pytest.mark.parametrize(
    "code",
    [
        "PROCESS_RESTARTED",
        "AUTHORITY_CHANGED",
        "CANCELLED",
        "INCOMPLETE_STREAM",
        "GENERATION_FAILED",
        "GENERATION_REVOKED",
        "PROVIDER_TIMEOUT",
    ],
)
def test_real_generation_error_codes_preserved(code):
    from app.modules.analytics.service import safe_metadata

    assert safe_metadata("generation.finish", {"error_code": code}) == {"error_code": code}
    assert safe_metadata("generation.finish", {"error_code": "SECRET_SENTINEL"}) == {}


@pytest.mark.parametrize(
    "params",
    [
        {"action": "bad space"},
        {"outcome": "x" * 31},
        {"target_id": "invalid"},
        {"page_size": 101},
        {"page": 0},
    ],
)
def test_audit_strict_filters(client, admin, params):
    assert client.get("/api/v1/admin/audit-events", params=params).status_code == 422


def test_agent_and_missing_detail_access(client, signed_in, auth_app):
    from uuid import UUID, uuid4

    from sqlalchemy import update

    from app.modules.auth.models import User

    with auth_app.state.session_factory() as db:
        db.execute(update(User).where(User.id == UUID(signed_in["id"])).values(role="agent"))
        db.commit()
    for path in (
        "/api/v1/admin/stats",
        "/api/v1/admin/audit-events",
        f"/api/v1/admin/audit-events/{uuid4()}",
    ):
        assert client.get(path).status_code == 403


def test_handoff_target_and_legacy_request_secret_projection():
    from datetime import UTC, datetime
    from uuid import uuid4

    from app.core.models import AuditEvent
    from app.modules.analytics.service import project_audit

    row = AuditEvent(
        id=uuid4(),
        actor_id=None,
        action="handoff.claim",
        target_type="handoff",
        target_id=str(uuid4()),
        outcome="success",
        request_id="sk-secret-sentinel",
        created_at=datetime.now(UTC),
        event_metadata={},
    )
    value = project_audit(row)
    assert value.target_type == "handoff"
    assert value.request_id is None


def test_unknown_audit_metadata_never_echoes_secrets_and_read_is_readonly(client, admin, auth_app):
    from datetime import UTC, datetime
    from uuid import uuid4

    from sqlalchemy import func, select

    from app.core.models import AuditEvent

    request_id = str(uuid4())
    with auth_app.state.session_factory() as db:
        row = AuditEvent(
            action="secret-sentinel",
            target_type="secret-sentinel",
            target_id="secret-sentinel",
            outcome="secret-sentinel",
            request_id=request_id,
            created_at=datetime.now(UTC),
            event_metadata={"status": "secret-sentinel", "comment": "secret-sentinel"},
        )
        db.add(row)
        db.commit()
        key = row.id
        before = db.scalar(select(func.count()).select_from(AuditEvent))
    response = client.get(f"/api/v1/admin/audit-events/{key}")
    assert response.status_code == 200
    assert "secret-sentinel" not in response.text
    assert response.json()["request_id"] == request_id
    assert response.json()["metadata"] == {}
    assert response.json()["target_id"] is None
    with auth_app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(AuditEvent)) == before
    assert client.get(f"/api/v1/admin/audit-events/{uuid4()}").status_code == 404


def test_real_conversation_create_and_transition_audit_projection():
    from datetime import UTC, datetime
    from uuid import uuid4

    from app.core.models import AuditEvent
    from app.modules.analytics.service import project_audit

    row = AuditEvent(
        id=uuid4(),
        actor_id=None,
        action="conversation.create",
        target_type="conversation",
        target_id=str(uuid4()),
        outcome="success",
        request_id=str(uuid4()),
        created_at=datetime.now(UTC),
        event_metadata={},
    )
    assert project_audit(row).action == "conversation.create"
    row.action, row.event_metadata = (
        "conversation.transition",
        {"from": "bot", "to": "queued", "extra": "secret"},
    )
    assert project_audit(row).model_dump(mode="json", by_alias=True)["metadata"] == {
        "from": "bot",
        "to": "queued",
    }


def test_browser_fixture_persists_legacy_secret_but_api_never_returns_it(client, admin, auth_app):
    from sqlalchemy import select

    from app.core.models import AuditEvent
    from tests.analytics.metrics_helpers import PARAMS, seed_metrics

    sentinel = "analytics-raw-secret-sentinel"
    with auth_app.state.session_factory() as db:
        seed_metrics(db)
        db.commit()
        dirty = db.scalars(select(AuditEvent).where(AuditEvent.action == "auth.login")).all()
        assert any(
            row.event_metadata.get("password") == sentinel
            and row.event_metadata.get("comment") == sentinel
            for row in dirty
        )
    response = client.get("/api/v1/admin/audit-events", params={**PARAMS, "action": "auth.login"})
    assert response.status_code == 200 and response.json()["total"] == 3
    assert sentinel not in response.text
    for item in response.json()["items"]:
        assert item["metadata"] == {}
        detail = client.get(f"/api/v1/admin/audit-events/{item['id']}")
        assert detail.status_code == 200 and sentinel not in detail.text
