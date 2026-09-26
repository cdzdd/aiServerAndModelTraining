import pytest

from tests.analytics.metrics_helpers import END, PARAMS, START, seed_metrics


def test_fixed_cohort_metrics(client, admin, auth_app):
    with auth_app.state.session_factory() as db:
        seed_metrics(db)
        db.commit()
    response = client.get("/api/v1/admin/stats", params=PARAMS)
    assert response.status_code == 200
    data = response.json()
    assert data["logins"] == {"successful": 2}
    assert data["generations"] == {
        "accepted": 14,
        "distinct_users": 3,
        "complete": 10,
        "failed": 2,
        "cancelled": 1,
        "generating": 1,
        "answered": 7,
        "clarify": 1,
        "no_answer": 2,
        "unclassified_complete": 0,
        "no_answer_ratio": {"numerator": 2, "denominator": 10, "value": 0.2},
    }
    assert data["latency"] == {"average_ms": 800, "sample_count": 9, "missing_count": 1}
    tokens = data["tokens"]
    assert tokens["terminal_count"] == 13 and tokens["pending_count"] == 1
    assert tokens["prompt_tokens"] == {
        "value": None,
        "known_sum": 1200,
        "known_count": 12,
        "missing_count": 1,
        "coverage": 12 / 13,
    }
    assert tokens["completion_tokens"]["value"] == 260
    assert tokens["total_tokens"]["known_sum"] == 1430
    assert tokens["cost"]["amount"] is None and tokens["cost"]["status"] == "unknown"
    assert data["feedback"]["satisfaction"]["value"] == 0.75
    assert data["handoffs"]["period"] == {"requested": 2, "claimed": 3, "closed": 1}
    assert data["handoffs"]["current"] == {"queued": 1, "human": 2}
    assert data["ingestion"]["period_jobs"]["parse"] == {
        "queued": 1,
        "running": 1,
        "succeeded": 3,
        "failed": 1,
    }
    assert data["ingestion"]["current_documents"]["deleted"] == 2
    assert [day["accepted"] for day in data["daily"]] == [7, 7]
    assert data["popular_questions"][0]["count"] == 4
    assert len(data["popular_questions"]) == 10
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "params",
    [
        {"from": "2024-01-01T00:00:00Z"},
        {"from": "2024-01-01", "to": "2024-01-02"},
        {"from": "bad", "to": "bad"},
        {"from": "2024-01-02T00:00:00Z", "to": "2024-01-01T00:00:00Z"},
        {"from": "2020-01-01T00:00:00Z", "to": "2024-01-01T00:00:00Z"},
    ],
)
def test_invalid_ranges(client, admin, params):
    assert client.get("/api/v1/admin/stats", params=params).status_code == 422


def test_empty_range_and_default_shanghai_days(client, admin):
    from datetime import datetime, timedelta

    from app.modules.analytics.service import make_range

    value = client.get(
        "/api/v1/admin/stats", params={"from": "1990-01-01T00:00:00Z", "to": "1990-01-01T12:00:00Z"}
    ).json()
    assert value["generations"]["accepted"] == 0
    assert value["generations"]["no_answer_ratio"]["value"] is None
    assert value["feedback"]["satisfaction"]["value"] is None
    assert value["latency"]["average_ms"] is None
    assert value["tokens"]["total_tokens"] == {
        "value": None,
        "known_sum": 0,
        "known_count": 0,
        "missing_count": 0,
        "coverage": None,
    }
    assert value["popular_questions"] == []
    assert len(value["daily"]) == 1 and value["daily"][0]["accepted"] == 0
    period = make_range(now=datetime.fromisoformat("2026-09-25T18:00:00+00:00"))
    assert period.end.isoformat() == "2026-09-26T16:00:00+00:00"
    assert period.end - period.start == timedelta(days=30)


def test_half_open_boundary_timezone_unclassified_and_deleted_text(client, admin, auth_app):
    from datetime import timedelta

    from tests.analytics.metrics_helpers import END, START

    with auth_app.state.session_factory() as db:
        rows = seed_metrics(db)
        rows["usages"][0].accepted_at = START
        rows["usages"][1].accepted_at = START - timedelta(microseconds=1)
        rows["usages"][2].accepted_at = END
        rows["usages"][3].accepted_at = START + timedelta(days=1) - timedelta(microseconds=1)
        rows["usages"][4].accepted_at = START + timedelta(days=1)
        rows["replies"][0].answer_status = None
        rows["conversations"][0].deleted_at = END
        db.commit()
    params = {"from": "2024-01-02T00:00:00+08:00", "to": "2024-01-04T00:00:00+08:00"}
    data = client.get("/api/v1/admin/stats", params=params).json()
    assert data["generations"]["accepted"] == 12
    assert data["generations"]["unclassified_complete"] == 1
    assert data["generations"]["no_answer_ratio"] == {
        "numerator": 2,
        "denominator": 7,
        "value": 2 / 7,
    }
    assert data["range"]["from"] == "2024-01-01T16:00:00Z"
    assert [day["accepted"] for day in data["daily"]] == [4, 8]
    assert data["feedback"]["total"] == 4
    assert all(item["count"] == 1 for item in data["popular_questions"])


def test_popular_full_text_ties_truncated_without_merging(client, admin, auth_app):
    from app.modules.chat.models import Message

    with auth_app.state.session_factory() as db:
        rows = seed_metrics(db)
        for i, usage in enumerate(rows["usages"]):
            db.get(Message, usage.user_message_id).content = "a" * 200 + f"{i:02d}"
        db.commit()
    data = client.get("/api/v1/admin/stats", params=PARAMS).json()
    assert len(data["popular_questions"]) == 10
    assert all(
        row == {"preview": "a" * 200, "count": 1, "truncated": True}
        for row in data["popular_questions"]
    )


def test_snapshot_stays_consistent_across_concurrent_commit(client, admin, auth_app, monkeypatch):
    from sqlalchemy import delete, text

    from app.modules.analytics import repository
    from app.modules.feedback.models import Feedback

    with auth_app.state.session_factory() as db:
        seed_metrics(db)
        db.commit()
    original = repository.generations

    def concurrent(db, period):
        assert db.scalar(text("SHOW transaction_isolation")) == "repeatable read"
        assert db.scalar(text("SHOW transaction_read_only")) == "on"
        result = original(db, period)
        with auth_app.state.engine.begin() as connection:
            connection.execute(delete(Feedback))
        return result

    monkeypatch.setattr(repository, "generations", concurrent)
    data = client.get("/api/v1/admin/stats", params=PARAMS).json()
    assert data["feedback"]["total"] == 4
    monkeypatch.setattr(repository, "generations", original)
    assert client.get("/api/v1/admin/stats", params=PARAMS).json()["feedback"]["total"] == 0


@pytest.mark.parametrize("change", [{"role": "user"}, {"is_active": False}])
def test_new_snapshot_rechecks_admin_identity(client, admin, auth_app, change):
    from uuid import UUID

    from sqlalchemy import update

    from app.core.security import AuthError
    from app.modules.analytics import service
    from app.modules.auth.models import User
    from app.modules.auth.schemas import Actor

    actor = Actor(user_id=UUID(admin["id"]), role="admin")
    with auth_app.state.engine.begin() as connection:
        connection.execute(update(User).where(User.id == actor.user_id).values(**change))
    with pytest.raises(AuthError) as error:
        service.get_stats(auth_app.state.session_factory, actor, service.make_range())
    assert error.value.status == 403


def test_current_cohort_feedback_changes_and_independent_token_unknowns(client, admin, auth_app):
    from sqlalchemy import select

    from app.modules.feedback.models import Feedback

    with auth_app.state.session_factory() as db:
        rows = seed_metrics(db)
        for usage in rows["usages"]:
            usage.prompt_tokens = 0
            usage.total_tokens = None
        for entry in db.scalars(select(Feedback)):
            entry.rating, entry.status = "down", "open"
            entry.resolution, entry.resolved_at, entry.resolved_by = "", None, None
        db.commit()
    data = client.get("/api/v1/admin/stats", params=PARAMS).json()
    assert data["tokens"]["prompt_tokens"] == {
        "value": 0,
        "known_sum": 0,
        "known_count": 13,
        "missing_count": 0,
        "coverage": 1,
    }
    assert data["tokens"]["total_tokens"] == {
        "value": None,
        "known_sum": 0,
        "known_count": 0,
        "missing_count": 13,
        "coverage": 0,
    }
    assert data["feedback"] == {
        "total": 4,
        "up": 0,
        "down": 4,
        "open": 4,
        "resolved": 0,
        "satisfaction": {"numerator": 0, "denominator": 4, "value": 0},
    }


def test_range_page_explain_and_index_definitions(auth_app):
    from sqlalchemy import text

    with auth_app.state.session_factory() as db:
        seed_metrics(db)
        db.execute(text("ANALYZE generation_usage"))
        db.execute(text("ANALYZE audit_events"))
        plans = {}
        for name, query in {
            "usage_range": (
                "SELECT count(*) FROM generation_usage "
                "WHERE accepted_at >= :start AND accepted_at < :end"
            ),
            "audit_page": (
                "SELECT id FROM audit_events "
                "WHERE created_at >= :start AND created_at < :end "
                "ORDER BY created_at DESC,id DESC LIMIT 20"
            ),
        }.items():
            plans[name] = [
                row[0]
                for row in db.execute(
                    text("EXPLAIN (ANALYZE, BUFFERS) " + query),
                    {
                        "start": START,
                        "end": END,
                    },
                )
            ]
        indexes = (
            db.execute(
                text(
                    "SELECT indexname FROM pg_indexes WHERE schemaname=current_schema() "
                    "AND indexname IN ('ix_audit_events_created_id','ix_generation_usage_accepted')"
                )
            )
            .scalars()
            .all()
        )
        assert set(indexes) == {"ix_audit_events_created_id", "ix_generation_usage_accepted"}
        assert all(any("Execution Time" in line for line in plan) for plan in plans.values())
        print("ANALYTICS_EXPLAIN", plans)


@pytest.mark.parametrize("path", ["/api/v1/admin/stats", "/api/v1/admin/audit-events"])
@pytest.mark.parametrize("start,end", [("0", "3600"), ("1000000000", "1000003600")])
def test_numeric_epoch_strings_are_not_iso_ranges(client, admin, path, start, end):
    response = client.get(path, params={"from": start, "to": end})
    assert response.status_code == 422
    assert "input" not in response.json()["error"]


@pytest.mark.parametrize("path", ["/api/v1/admin/stats", "/api/v1/admin/audit-events"])
@pytest.mark.parametrize(
    "start,end",
    [
        ("9999-12-30T00:00:00Z", "9999-12-31T23:00:00Z"),
        ("0001-01-01T00:00:00+14:00", "0001-01-02T00:00:00+14:00"),
    ],
)
def test_unrepresentable_timezone_boundaries_return_safe_422(client, admin, path, start, end):
    response = client.get(path, params={"from": start, "to": end})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert start not in response.text and end not in response.text


def test_last_representable_shanghai_date_can_be_zero_filled(client, admin):
    response = client.get(
        "/api/v1/admin/stats", params={"from": "9999-12-30T16:00:00Z", "to": "9999-12-31T15:00:00Z"}
    )
    assert response.status_code == 200
    assert [day["date"] for day in response.json()["daily"]] == ["9999-12-31"]
