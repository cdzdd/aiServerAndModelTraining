"""Reconcile a small trusted Markdown directory into this integration's dedicated FAQ KB."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.database import create_db_engine
from app.modules.auth import models as auth_models  # noqa: F401
from app.modules.fund_assistant.knowledge_contract import KB_DESCRIPTION, KB_MARKER, KB_NAME
from app.modules.knowledge.models import FAQ, KnowledgeBase
from app.modules.retrieval.jobs import enqueue_faq_index


def load_markdown(directory):
    path = Path(directory)
    if path.is_symlink() or not path.is_dir():
        raise ValueError("Use one ordinary Markdown directory")
    files = sorted(path.iterdir())
    if not 1 <= len(files) <= 32:
        raise ValueError("Expected 1 to 32 Markdown files")
    documents, size = {}, 0
    for item in files:
        if item.is_symlink() or not item.is_file() or item.suffix.lower() != ".md":
            raise ValueError("Only ordinary Markdown files are permitted")
        length = item.stat().st_size
        size += length
        if length > 65536 or size > 262144:
            raise ValueError("Knowledge input is too large")
        body = item.read_text(encoding="utf-8-sig").strip()
        if not body or len(body) > 10000 or "\0" in body:
            raise ValueError("Markdown must contain 1 to 10000 valid characters")
        question = body.splitlines()[0].lstrip("# ").strip()
        if not 1 <= len(question) <= 500 or question in documents:
            raise ValueError("Each document needs a unique title of 1 to 500 characters")
        documents[question] = body
    return documents


def import_documents(db, documents, kb_id):
    kb = db.get(KnowledgeBase, kb_id, with_for_update=True)
    if kb is None:
        kb = KnowledgeBase(
            id=kb_id,
            name=KB_NAME,
            description=KB_DESCRIPTION,
            visibility="restricted",
            is_active=True,
            version=1,
        )
        db.add(kb)
        db.flush()
    elif (
        kb.name != KB_NAME
        or not kb.description.startswith(KB_MARKER)
        or kb.visibility != "restricted"
        or not kb.is_active
    ):
        raise ValueError("Refusing to modify a KB not owned by this integration")
    existing = {row.question: row for row in db.scalars(select(FAQ).where(FAQ.kb_id == kb_id))}
    changed, indexed = 0, 0
    for question, answer in documents.items():
        faq = existing.get(question)
        if faq is None:
            faq = FAQ(kb_id=kb_id, question=question, answer=answer, is_active=True, version=1)
            db.add(faq)
            db.flush()
            changed += 1
        elif not faq.is_active or faq.answer != answer:
            faq.answer, faq.is_active = answer, True
            faq.version += 1
            faq.updated_at = datetime.now(UTC)
            changed += 1
        if faq.indexed_version != faq.version:
            enqueue_faq_index(db, faq, retry_failed=True)
            indexed += 1
    for question, faq in existing.items():
        if question not in documents and faq.is_active:
            faq.is_active = False
            faq.version += 1
            faq.updated_at = datetime.now(UTC)
            changed += 1
    db.flush()
    return dict(
        kb_id=str(kb_id),
        faqCount=len(documents),
        changedCount=changed,
        indexJobsQueued=indexed,
        indexedByThisCommand=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--knowledge-dir", type=Path, required=True)
    parser.add_argument("--kb-id", type=UUID)
    args = parser.parse_args()
    # Validate every file before reading DB settings or mutating data.
    documents = load_markdown(args.knowledge_dir)
    settings = Settings()
    kb_id = args.kb_id or settings.fund_assistant_kb_id or uuid4()
    engine = create_db_engine(settings)
    try:
        with sessionmaker(engine).begin() as db:
            result = import_documents(db, documents, kb_id)
        print(json.dumps(result, ensure_ascii=False))
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, SQLAlchemyError):
        raise SystemExit(
            "Knowledge import failed; validate the private operator input and target KB"
        ) from None
