from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.core.models import AuditEvent
from app.modules.auth.models import User
from app.modules.chat.models import Conversation, GenerationUsage, Message
from app.modules.feedback.models import Feedback
from app.modules.handoff.models import Handoff
from app.modules.ingestion.models import Document, DocumentRevision, IngestionJob
from app.modules.knowledge.models import KnowledgeBase

START = datetime(2024, 1, 1, 16, tzinfo=UTC)
END = START + timedelta(days=2)
PARAMS = {"from": START.isoformat(), "to": END.isoformat()}


def seed_metrics(db):
    people = [
        User(
            username=f"metric-{uuid4().hex}",
            display_name="虚构用户",
            password_hash="unusable",
            role="user",
        )
        for _ in range(3)
    ]
    staff = [
        User(
            username=f"metric-{role}-{uuid4().hex}",
            display_name="虚构处理人员",
            password_hash="unusable",
            role=role,
        )
        for role in ("agent", "admin")
    ]
    db.add_all(people + staff)
    kb = KnowledgeBase(name="虚构统计资料", visibility="public")
    db.add(kb)
    db.flush()
    conversations, replies, usages = [], [], []
    for i in range(14):
        person = people[i % 3]
        when = START + timedelta(hours=1 if i < 7 else 25)
        state = (
            "complete"
            if i < 10
            else "failed"
            if i < 12
            else "cancelled"
            if i == 12
            else "generating"
        )
        conv = Conversation(
            user_id=person.id,
            kb_ids=[str(kb.id)],
            created_at=when,
            generation_token=uuid4() if state == "generating" else None,
        )
        db.add(conv)
        db.flush()
        question = Message(
            conversation_id=conv.id,
            author_id=person.id,
            role="user",
            content="虚构：图书馆开放吗？" if i < 4 else f"虚构问题{i}",
            request_id="metric-fixture",
            created_at=when,
        )
        db.add(question)
        db.flush()
        answer = Message(
            conversation_id=conv.id,
            role="assistant",
            content="虚构回答",
            status=state,
            generation_token=conv.generation_token,
            answer_status=("answered" if i < 7 else "clarify" if i == 7 else "no_answer")
            if i < 10
            else None,
            latency_ms=800 if i < 9 else None,
            in_reply_to_id=question.id,
            request_id="metric-fixture",
            created_at=when + timedelta(microseconds=1),
        )
        db.add(answer)
        db.flush()
        usage = GenerationUsage(
            user_id=person.id,
            conversation_id=conv.id,
            user_message_id=question.id,
            assistant_message_id=answer.id,
            accepted_at=when,
            finished_at=when + timedelta(seconds=1) if i < 13 else None,
            outcome=state if i < 13 else None,
            prompt_tokens=100 if i < 12 else None,
            completion_tokens=20 if i < 13 else None,
            total_tokens=130 if i < 11 else None,
        )
        db.add(usage)
        conversations.append(conv)
        replies.append(answer)
        usages.append(usage)
    for i in range(4):
        db.add(
            Feedback(
                message_id=replies[i].id,
                conversation_id=conversations[i].id,
                user_id=conversations[i].user_id,
                rating="up" if i < 3 else "down",
                comment="虚构评价",
                status="open" if i == 0 else "resolved",
                resolution="虚构核查完成" if i else "",
                resolved_by=staff[1].id if i else None,
                resolved_at=START + timedelta(hours=3) if i else None,
                created_at=START + timedelta(hours=2),
                updated_at=START + timedelta(hours=3),
            )
        )
    for action, outcome in [
        ("auth.login", "success"),
        ("auth.login", "success"),
        ("auth.login", "failure"),
        ("generation.finish", "success"),
        ("generation.recover", "success"),
    ]:
        db.add(
            AuditEvent(
                action=action,
                outcome=outcome,
                target_type="user",
                request_id="metric-fixture",
                created_at=START,
                # Deliberately bypass writer redaction to model legacy dirty audit data.
                event_metadata={
                    "password": "analytics-raw-secret-sentinel",
                    "comment": "analytics-raw-secret-sentinel",
                }
                if action == "auth.login"
                else {},
            )
        )
    for i, mode in enumerate(("human", "human", "closed", "queued")):
        conversation = Conversation(
            user_id=people[0].id,
            kb_ids=[str(kb.id)],
            mode=mode,
            assigned_agent_id=staff[0].id if i < 3 else None,
            created_at=START - timedelta(days=2),
        )
        db.add(conversation)
        db.flush()
        db.add(
            Handoff(
                conversation_id=conversation.id,
                requested_at=START + timedelta(hours=2) if i < 2 else START - timedelta(days=1),
                claimed_at=START + timedelta(hours=3) if i < 3 else None,
                claimed_by_id=staff[0].id if i < 3 else None,
                closed_at=START + timedelta(hours=4) if i == 2 else None,
                closed_by_id=staff[1].id if i == 2 else None,
            )
        )
    for i, state in enumerate(
        [
            "uploaded",
            "processing",
            "parsed",
            "parsed",
            "ready",
            "ready",
            "ready",
            "failed",
            "disabled",
            "deleted",
            "deleted",
        ]
    ):
        doc = Document(
            kb_id=kb.id,
            filename=f"fixture{i}.txt",
            status=state,
            created_at=START - timedelta(days=90),
        )
        db.add(doc)
        db.flush()
        revision = DocumentRevision(
            document_id=doc.id,
            filename=doc.filename,
            content_sha256=f"{i:064x}",
            storage_key=str(uuid4()),
            file_type="txt",
        )
        db.add(revision)
        db.flush()
        if i < 6:
            db.add(
                IngestionJob(
                    document_id=doc.id,
                    revision_id=revision.id,
                    kind="parse",
                    state=["queued", "running", "succeeded", "succeeded", "succeeded", "failed"][i],
                    attempts=3,
                    created_at=START,
                )
            )
        if i < 7:
            db.add(
                IngestionJob(
                    document_id=doc.id,
                    revision_id=revision.id,
                    kind="index",
                    state=[
                        "running",
                        "succeeded",
                        "succeeded",
                        "succeeded",
                        "succeeded",
                        "failed",
                        "failed",
                    ][i],
                    attempts=4,
                    created_at=START,
                )
            )
    db.flush()
    return {"users": people, "conversations": conversations, "replies": replies, "usages": usages}
