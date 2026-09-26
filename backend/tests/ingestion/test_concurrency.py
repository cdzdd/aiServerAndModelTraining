from io import BytesIO
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import UploadFile
from sqlalchemy import func, select

from app.core.security import AuthError
from app.modules.auth.schemas import Actor
from app.modules.ingestion import service
from app.modules.ingestion.models import Document, DocumentRevision
from tests.ingestion.test_uploads import upload
from tests.knowledge.conftest import create_kb


@pytest.mark.parametrize("state,expected_status", [("disabled", 409), ("deleted", 404)])
def test_revision_rechecks_state_after_route_read(client, admin, auth_app, state, expected_status):
    kb = create_kb(client)
    document_id = UUID(upload(client, kb).json()["document_id"])
    actor = Actor(user_id=UUID(admin["id"]), role="admin")
    request = SimpleNamespace(app=auth_app, state=SimpleNamespace(request_id="stale-revision-test"))
    factory = auth_app.state.session_factory
    with factory() as stale:
        # Exactly the route's initial unlocked lookup; retain its identity-map object.
        cached_document = service.get_document(stale, actor, document_id)
        with factory() as concurrent:
            concurrent.get(Document, document_id).status = state
            concurrent.commit()
        assert cached_document.status == "uploaded"
        with pytest.raises(AuthError) as error:
            service.upload(
                stale,
                request,
                actor,
                cached_document.kb_id,
                UploadFile(filename="replacement.txt", file=BytesIO(b"new version")),
                document_id,
            )
        assert error.value.status == expected_status
    with factory() as verify:
        assert verify.get(Document, document_id).status == state
        assert (
            verify.scalar(
                select(func.count())
                .select_from(DocumentRevision)
                .where(DocumentRevision.document_id == document_id)
            )
            == 1
        )
    assert len(list(auth_app.state.settings.upload_dir.iterdir())) == 1


def test_revision_rechecks_cached_knowledge_state(client, admin, auth_app):
    from app.modules.knowledge.models import KnowledgeBase

    kb = create_kb(client)
    document_id = UUID(upload(client, kb).json()["document_id"])
    actor = Actor(user_id=UUID(admin["id"]), role="admin")
    request = SimpleNamespace(app=auth_app, state=SimpleNamespace(request_id="stale-kb-test"))
    factory = auth_app.state.session_factory
    with factory() as stale:
        cached_document = service.get_document(stale, actor, document_id)
        cached_kb = stale.get(KnowledgeBase, UUID(kb["id"]))
        with factory() as concurrent:
            concurrent.get(KnowledgeBase, cached_kb.id).is_active = False
            concurrent.commit()
        assert cached_kb.is_active
        with pytest.raises(AuthError) as error:
            service.upload(
                stale,
                request,
                actor,
                cached_document.kb_id,
                UploadFile(filename="replacement.txt", file=BytesIO(b"new version")),
                document_id,
            )
        assert error.value.status == 404
    with factory() as verify:
        assert not verify.get(KnowledgeBase, UUID(kb["id"])).is_active
        assert (
            verify.scalar(
                select(func.count())
                .select_from(DocumentRevision)
                .where(DocumentRevision.document_id == document_id)
            )
            == 1
        )
