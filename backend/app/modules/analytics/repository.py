"""Bounded grouped SQL over persisted business records, without join multiplication."""

from sqlalchemy import Date, cast, func, select
from sqlalchemy.orm import aliased

from app.core.models import AuditEvent
from app.modules.chat.models import Conversation, GenerationUsage, Message
from app.modules.feedback.models import Feedback
from app.modules.handoff.models import Handoff
from app.modules.ingestion.models import Document, IngestionJob


def interval(column, period):
    return (column >= period.start, column < period.end)


def count(db, model, *conditions):
    return db.scalar(select(func.count()).select_from(model).where(*conditions))


def generation_rows(period):
    return select(GenerationUsage).where(*interval(GenerationUsage.accepted_at, period)).subquery()


def generations(db, period):
    usage = generation_rows(period)
    joined = usage.join(Message, Message.id == usage.c.assistant_message_id)
    states = dict(
        db.execute(
            select(Message.status, func.count()).select_from(joined).group_by(Message.status)
        ).all()
    )
    answers = dict(
        db.execute(
            select(Message.answer_status, func.count())
            .select_from(joined)
            .where(Message.status == "complete")
            .group_by(Message.answer_status)
        ).all()
    )
    distinct = db.scalar(select(func.count(func.distinct(usage.c.user_id))))
    latency = db.execute(
        select(func.avg(Message.latency_ms), func.count(Message.latency_ms))
        .select_from(joined)
        .where(Message.status == "complete")
    ).one()
    fields = {}
    for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
        column = usage.c[name]
        fields[name] = db.execute(
            select(func.sum(column), func.count(column))
            .select_from(joined)
            .where(Message.status.in_(["complete", "failed", "cancelled"]))
        ).one()
    day = cast(func.timezone("Asia/Shanghai", usage.c.accepted_at), Date)
    daily = db.execute(
        select(day, Message.status, Message.answer_status, func.count())
        .select_from(joined)
        .group_by(day, Message.status, Message.answer_status)
    ).all()
    question = aliased(Message)
    popular = db.execute(
        select(question.content, func.count().label("count"))
        .select_from(usage)
        .join(question, question.id == usage.c.user_message_id)
        .join(Conversation, Conversation.id == usage.c.conversation_id)
        .where(Conversation.deleted_at.is_(None), question.role == "user")
        .group_by(question.content)
        .order_by(func.count().desc(), question.content)
        .limit(10)
    ).all()
    return states, answers, distinct, latency, fields, daily, popular


def other_metrics(db, period):
    logins = count(
        db,
        AuditEvent,
        AuditEvent.action == "auth.login",
        AuditEvent.outcome == "success",
        *interval(AuditEvent.created_at, period),
    )
    handoffs = {
        name: count(db, Handoff, *interval(getattr(Handoff, name + "_at"), period))
        for name in ("requested", "claimed", "closed")
    }
    backlog = dict(
        db.execute(
            select(Conversation.mode, func.count())
            .where(Conversation.deleted_at.is_(None), Conversation.mode.in_(["queued", "human"]))
            .group_by(Conversation.mode)
        ).all()
    )
    feedback = db.execute(
        select(Feedback.rating, Feedback.status, func.count())
        .where(*interval(Feedback.created_at, period))
        .group_by(Feedback.rating, Feedback.status)
    ).all()
    jobs = db.execute(
        select(IngestionJob.kind, IngestionJob.state, func.count())
        .where(*interval(IngestionJob.created_at, period))
        .group_by(IngestionJob.kind, IngestionJob.state)
    ).all()
    documents = dict(
        db.execute(select(Document.status, func.count()).group_by(Document.status)).all()
    )
    return logins, handoffs, backlog, feedback, jobs, documents
