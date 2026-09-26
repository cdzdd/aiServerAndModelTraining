"""Deterministic vectors and transaction-isolated PostgreSQL retrieval data."""

from math import sqrt
from uuid import uuid4

import pytest
from sqlalchemy.orm import sessionmaker

from app.modules.auth.models import User
from app.modules.auth.schemas import Actor
from app.modules.ingestion.models import Chunk, Document, DocumentRevision
from app.modules.knowledge.models import FAQ, KnowledgeBase, KnowledgeMembership

MODEL = "BAAI/bge-small-zh-v1.5"
REVISION = "7999e1d3359715c523056ef9478215996d62a620"


def vector(score=1.0):
    return [score, sqrt(1 - score * score)] + [0.0] * 510


class FixedEmbedder:
    def __init__(self, callback=None):
        self.callback = callback

    def encode_query(self, query):
        if self.callback:
            self.callback()
        return vector()


class SearchData:
    def __init__(self, factory):
        self.factory = factory
        with factory() as db:
            user = User(username=uuid4().hex, display_name="检索用户", password_hash="unused")
            db.add(user)
            db.flush()
            self.actor = Actor(user_id=user.id, role="user")
            db.commit()

    def kb(self, *, visibility="restricted", member=True, active=True):
        with self.factory() as db:
            kb = KnowledgeBase(name="测试知识", visibility=visibility, is_active=active)
            db.add(kb)
            db.flush()
            if member:
                db.add(KnowledgeMembership(kb_id=kb.id, user_id=self.actor.user_id))
            db.commit()
            return kb.id

    def document(self, kb_id, *, score=1.0, status="ready", text="文档知识", **chunk_extra):
        with self.factory() as db:
            document = Document(kb_id=kb_id, filename="服务.txt", status=status)
            db.add(document)
            db.flush()
            revision = DocumentRevision(
                document_id=document.id,
                filename="服务.txt",
                content_sha256=uuid4().hex * 2,
                storage_key=str(uuid4()),
                file_type="txt",
            )
            db.add(revision)
            db.flush()
            document.active_revision_id = revision.id
            document.candidate_revision_id = revision.id
            chunk = Chunk(
                kb_id=kb_id,
                document_id=document.id,
                revision_id=revision.id,
                chunk_index=0,
                text=text,
                title="服务",
                line_number=7,
                embedding=vector(score),
                embedding_model=MODEL,
                embedding_version=REVISION,
                **chunk_extra,
            )
            db.add(chunk)
            db.flush()
            result = (document.id, revision.id, chunk.id)
            db.commit()
            return result

    def faq(self, kb_id, *, score=1.0, active=True, version=1, indexed_version=1):
        with self.factory() as db:
            faq = FAQ(
                kb_id=kb_id,
                question="开放时间？",
                answer="九点",
                is_active=active,
                version=version,
                indexed_version=indexed_version,
            )
            db.add(faq)
            db.flush()
            chunk = Chunk(
                kb_id=kb_id,
                faq_id=faq.id,
                faq_version=1,
                chunk_index=0,
                text="开放时间？\n九点",
                title=faq.question,
                embedding=vector(score),
                embedding_model=MODEL,
                embedding_version=REVISION,
            )
            db.add(chunk)
            db.flush()
            result = (faq.id, chunk.id)
            db.commit()
            return result


@pytest.fixture
def search_data(migrated_engine):
    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        factory = sessionmaker(
            bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        yield SearchData(factory)
        transaction.rollback()
