"""Install the curated service desk dataset into a QA application database."""

import argparse
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid5

from app.core.config import Settings
from app.core.database import create_db_engine
from app.modules.auth.models import User
from app.modules.chat.models import Conversation, Message
from app.modules.handoff.models import Handoff
from app.modules.ingestion.models import Chunk
from app.modules.knowledge.models import FAQ, KnowledgeBase
from app.modules.rag.schemas import Citation
from app.modules.retrieval.embedding import MODEL_ID, MODEL_REVISION
from app.modules.retrieval.jobs import enqueue_faq_index
from sqlalchemy import or_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

NAMESPACE = UUID("af0dd200-8785-4e97-afbd-ca56a73cc74c")
CONTENT_SHA256 = "554f8239dbf45f121d1375a3e2246290022e99a4f6ece764e6ae50d553f156a1"


class Conflict(Exception):
    """Safe operator-facing error."""


def install_row(db, model, key, values, *, create):
    """Insert missing deterministic IDs, otherwise verify the existing row exactly."""
    row_id = uuid5(NAMESPACE, key)
    row = db.get(model, row_id, with_for_update=True)
    if row is None and create:
        row = model(id=row_id, **values)
        db.add(row)
        db.flush()
    if row is None or any(getattr(row, field) != value for field, value in values.items()):
        raise Conflict(f"{key}: missing or different from this delivery; transaction stopped")
    return row


def install_knowledge(db, libraries, *, create, need_index):
    sources = {}
    for lib in libraries:
        key = lib["key"]
        kb = install_row(
            db,
            KnowledgeBase,
            key,
            dict(
                name=lib["name"],
                description=lib["description"],
                visibility="public",
                version=1,
                is_active=True,
            ),
            create=create,
        )
        duplicate = select(KnowledgeBase.id).where(
            KnowledgeBase.name == kb.name,
            KnowledgeBase.id != kb.id,
        )
        if db.scalar(duplicate):
            raise Conflict(f"{key}: same name already belongs to another knowledge base")
        for item in lib["faqs"]:
            faq_key = item["key"]
            faq = install_row(
                db,
                FAQ,
                faq_key,
                dict(
                    kb_id=kb.id,
                    question=item["question"],
                    answer=item["answer"],
                    is_active=True,
                    version=1,
                ),
                create=create,
            )
            if create and faq.indexed_version != faq.version:
                enqueue_faq_index(db, faq, retry_failed=True)
            if not need_index:
                continue
            if faq.indexed_version != faq.version:
                raise Conflict(f"{faq_key}: wait for the running index worker")
            query = select(Chunk).where(
                Chunk.faq_id == faq.id,
                Chunk.kb_id == kb.id,
                Chunk.faq_version == faq.version,
                Chunk.embedding.is_not(None),
                Chunk.embedding_model == MODEL_ID,
                Chunk.embedding_version == MODEL_REVISION,
            )
            chunks = [chunk for chunk in db.scalars(query) if faq.answer in chunk.text]
            if len(chunks) != 1:
                raise Conflict(f"{faq_key}: no unique current indexed passage for the quotation")
            chunk = chunks[0]
            citation = Citation(
                index=1,
                kb_id=kb.id,
                source_type="faq",
                source_id=faq.id,
                chunk_id=chunk.id,
                title=chunk.title,
                quote=faq.answer,
                faq_version=faq.version,
                page_number=chunk.page_number,
                paragraph_number=chunk.paragraph_number,
                line_number=chunk.line_number,
            )
            sources[faq_key] = (str(kb.id), citation.model_dump(mode="json"))
    return sources


def check_actors(db, actors, data):
    if len(set(actors.values())) != 3:
        raise Conflict("Three distinct dedicated accounts are required")
    for role, user_id in actors.items():
        actor = db.get(User, user_id, with_for_update=True)
        if (
            actor is None
            or not actor.is_active
            or actor.role != role
            or actor.username.startswith(("kb-e2e-", "local_demo_"))
        ):
            raise Conflict(f"Dedicated {role} account is missing, disabled or has another role")
    known = [uuid5(NAMESPACE, s["key"]) for s in data]
    # Do not attach imported history to a user's unrelated conversations or handed-off work.
    unrelated = select(Conversation.id).where(
        Conversation.id.not_in(known),
        or_(
            Conversation.user_id.in_(actors.values()),
            Conversation.assigned_agent_id.in_(actors.values()),
        ),
    )
    if db.scalar(unrelated):
        raise Conflict("At least one selected account has unrelated conversations; check mapping")


def install_history(db, stories, sources, actors, *, create):
    for story in stories:
        kb_id, citation = sources[story["source"]]
        key, mode, owner = story["key"], story["mode"], actors[story["owner"]]
        agent = actors["agent"] if mode in {"human", "closed"} else None
        start = datetime.fromisoformat(story["created"])
        handoff = story.get("handoff", {})
        updated = max([m["after"] for m in story["messages"]] + list(handoff.values()))
        conv = install_row(
            db,
            Conversation,
            key,
            dict(
                user_id=owner,
                title=story["title"],
                mode=mode,
                kb_ids=[kb_id],
                assigned_agent_id=agent,
                created_at=start,
                updated_at=start + timedelta(seconds=updated),
                deleted_at=None,
                generation_token=None,
            ),
            create=create,
        )
        msg_ids = []
        for i, item in enumerate(story["messages"]):
            msg_key = f"{key}/message/{i}"
            role = item["role"]
            answer = role == "assistant"
            msg = install_row(
                db,
                Message,
                msg_key,
                dict(
                    conversation_id=conv.id,
                    content=item["text"],
                    role=role,
                    status="complete",
                    author_id=None if answer else (agent if role == "agent" else owner),
                    in_reply_to_id=msg_ids[-1] if answer else None,
                    citations=[citation] if answer else [],
                    created_at=start + timedelta(seconds=item["after"]),
                    intent="knowledge" if answer else None,
                    answer_status="answered" if answer else None,
                    evidence_level="sufficient" if answer else None,
                    client_message_id=None if answer else uuid5(NAMESPACE, msg_key + "/client"),
                    request_id=str(uuid5(NAMESPACE, msg_key + "/request")),
                ),
                create=create,
            )
            msg_ids.append(msg.id)
        if db.scalar(
            select(Message.id).where(Message.conversation_id == conv.id, Message.id.not_in(msg_ids))
        ):
            raise Conflict(f"{key}: conversation has additional messages; preserved")
        if handoff:
            times = {
                name + "_at": start + timedelta(seconds=seconds)
                for name, seconds in handoff.items()
            }
            install_row(
                db,
                Handoff,
                key + "/handoff",
                dict(
                    conversation_id=conv.id,
                    claimed_at=None,
                    closed_at=None,
                    claimed_by_id=agent,
                    closed_by_id=agent if mode == "closed" else None,
                )
                | times,
                create=create,
            )
        elif db.scalar(select(Handoff.id).where(Handoff.conversation_id == conv.id)):
            raise Conflict(f"{key}: unexpected handoff; preserved")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("knowledge", "history", "verify"))
    for role in ("user", "agent", "admin"):
        parser.add_argument(f"--{role}-id", type=UUID)
    args = parser.parse_args()
    actors = {role: getattr(args, role + "_id") for role in ("user", "agent", "admin")}
    history = args.phase != "knowledge"
    if history and not all(actors.values()):
        parser.error("history/verify require --user-id, --agent-id and --admin-id")
    raw = Path(__file__).with_name("service-content.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != CONTENT_SHA256:
        raise Conflict("Content digest does not match the reviewed release")
    data = json.loads(raw)
    engine = create_db_engine(Settings())
    try:
        with Session(engine) as db, db.begin():
            db.execute(text("select pg_advisory_xact_lock(719367125)"))
            if history:
                check_actors(db, actors, data["conversations"])
            sources = install_knowledge(
                db, data["libraries"], create=not history, need_index=history
            )
            if history:
                install_history(
                    db, data["conversations"], sources, actors, create=args.phase == "history"
                )
        print(
            f"{args.phase}: OK; 6 libraries, 36 FAQs"
            + (
                ", 36 conversations, 139 messages, 17 handoffs, 55 citations"
                if history
                else "; wait for indexing"
            )
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        main()
    except Conflict as exc:
        raise SystemExit(str(exc)) from None
    except SQLAlchemyError:
        raise SystemExit(
            "Database operation failed. Check connectivity, migrations and identity conflicts."
        ) from None
