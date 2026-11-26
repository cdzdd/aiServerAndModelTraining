from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.security import AuthError
from tests.compute.test_queue import new_scope, payload, result


def test_model_status_query_exists():
    from app.modules.compute import service

    assert callable(getattr(service, "get_model_status", None))


@pytest.fixture
def model_setup(migrated_engine):
    from app.modules.compute import service

    factory = sessionmaker(migrated_engine, expire_on_commit=False)
    now = datetime.now(UTC)
    model_id = uuid4().hex
    with factory.begin() as db:
        worker, _ = service.register_worker(db, name="status-test", model_id=model_id, now=now)
    return factory, now, model_id, worker


@pytest.mark.parametrize(
    "seen_age,active,state",
    [(None, True, "offline"), (30, True, "ready"), (31, True, "offline"), (0, False, "offline")],
)
def test_recent_activity_is_required(model_setup, seen_age, active, state):
    from app.modules.compute import service
    from app.modules.compute.models import ComputeWorker

    factory, now, model_id, worker = model_setup
    with factory.begin() as db:
        current = db.get(ComputeWorker, worker.id)
        current.last_seen_at = None if seen_age is None else now - timedelta(seconds=seen_age)
        current.is_active = active
    with factory() as db:
        status = service.get_model_status(db, model_id, now=now)
        assert status["state"] == state
        assert status["available"] == (state == "ready")
        assert status["queue_depth"] == 0
        assert status["active"] == 0


def test_online_worker_for_another_model_does_not_accept_work(model_setup):
    from app.modules.compute import service
    from app.modules.compute.models import ComputeJob, ComputeWorker

    factory, now, model_id, worker = model_setup
    with factory.begin() as db:
        db.get(ComputeWorker, worker.id).last_seen_at = now
        scope = new_scope(db, now)
        request = dict(payload(), model_id=uuid4().hex)
        with pytest.raises(AuthError) as exc:
            service.enqueue(db, scope, request, now=now)
        assert exc.value.status == 503 and exc.value.code == "MODEL_OFFLINE"
        assert not list(db.query(ComputeJob).filter_by(conversation_id=scope.conversation_id))
        assert service.get_model_status(db, model_id, now=now)["state"] == "ready"


def test_valid_running_lease_proves_online_and_busy(model_setup):
    from app.modules.compute import service
    from app.modules.compute.models import ComputeJob, ComputeWorker

    factory, now, model_id, worker = model_setup
    request = dict(payload(), model_id=model_id)
    with factory.begin() as db:
        db.get(ComputeWorker, worker.id).last_seen_at = now
        scope = new_scope(db, now)
        job_id = service.enqueue(db, scope, request, now=now)
        claimed = service.claim(db, worker, now=now)
        assert claimed is not None
        # An existing/legacy node's valid lease remains stronger evidence than a stale seen time.
        db.get(ComputeWorker, worker.id).last_seen_at = now - timedelta(seconds=31)
    with factory() as db:
        status = service.get_model_status(db, model_id, now=now)
        assert status["state"] == "busy" and not status["available"]
        assert status["active"] == 1
        assert service.take_result(db, job_id, scope, now=now) is None
    with factory.begin() as db:
        job = db.get(ComputeJob, job_id)
        job.lease_until = now
    with factory() as db:
        assert service.get_model_status(db, model_id, now=now)["state"] == "offline"


def test_spare_online_worker_is_ready_and_busy_work_can_queue(model_setup):
    from app.modules.compute import service
    from app.modules.compute.models import ComputeWorker

    factory, now, model_id, worker = model_setup
    request = dict(payload(), model_id=model_id)
    with factory.begin() as db:
        db.get(ComputeWorker, worker.id).last_seen_at = now
        first = new_scope(db, now)
        service.enqueue(db, first, request, now=now)
        assert service.get_model_status(db, model_id, now=now)["state"] == "busy"
        service.claim(db, worker, now=now)
        spare, _ = service.register_worker(db, name="spare", model_id=model_id, now=now)
        spare.last_seen_at = now
        db.flush()
        assert service.get_model_status(db, model_id, now=now)["state"] == "ready"
        second = new_scope(db, now)
        assert service.enqueue(db, second, request, now=now)


def test_waiting_job_fails_and_clears_payload_when_last_node_disappears(model_setup):
    from app.modules.compute import service
    from app.modules.compute.models import ComputeJob, ComputeWorker

    factory, now, model_id, worker = model_setup
    with factory.begin() as db:
        db.get(ComputeWorker, worker.id).last_seen_at = now
        scope = new_scope(db, now)
        job_id = service.enqueue(db, scope, dict(payload(), model_id=model_id), now=now)
    with factory.begin() as db:
        with pytest.raises(AuthError) as exc:
            service.take_result(db, job_id, scope, now=now + timedelta(seconds=31))
        assert exc.value.code == "MODEL_OFFLINE"
        job = db.get(ComputeJob, job_id)
        assert job.status == "failed" and job.error_code == "MODEL_OFFLINE"
        assert job.payload is None and job.result is None


def test_completed_result_can_be_consumed_after_activity_window(model_setup):
    from app.modules.compute import service
    from app.modules.compute.models import ComputeWorker

    factory, now, model_id, worker = model_setup
    with factory.begin() as db:
        db.get(ComputeWorker, worker.id).last_seen_at = now
        scope = new_scope(db, now)
        job_id = service.enqueue(db, scope, dict(payload(), model_id=model_id), now=now)
        claimed = service.claim(db, worker, now=now)
        service.submit_result(
            db, worker, job_id, claimed["lease_token"], dict(result(), model_id=model_id), now=now
        )
    with factory.begin() as db:
        assert (
            service.take_result(db, job_id, scope, now=now + timedelta(seconds=31))["text"]
            == "answer"
        )
