"""Read-only snapshots and deliberately narrow audit projections."""

from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text

from app.core.models import AuditEvent
from app.core.request_context import safe_error_code
from app.core.security import AuthError
from app.modules.analytics import repository as repo
from app.modules.analytics.schemas import AuditEventView, AuditPage, RangeView, StatsView
from app.modules.auth.models import User

SHANGHAI = ZoneInfo("Asia/Shanghai")
ACTIONS = {
    "auth.bootstrap": "初始化管理员",
    "auth.register": "注册账号",
    "auth.login": "登录",
    "auth.logout": "退出登录",
    "user.update": "修改账号",
    "knowledge.create": "创建知识库",
    "knowledge.update": "修改知识库",
    "knowledge.members": "修改知识库成员",
    "faq.create": "创建常见问题",
    "faq.update": "修改常见问题",
    "faq.disable": "停用常见问题",
    "document.upload": "上传文档",
    "document.replace": "替换文档",
    "document.enable": "启用文档",
    "document.disable": "停用文档",
    "document.delete": "删除文档",
    "document.retry": "重试文档",
    "conversation.create": "创建会话",
    "conversation.delete": "删除会话",
    "conversation.transition": "变更会话状态",
    "generation.accept": "受理问答",
    "generation.finish": "记录问答结果",
    "generation.recover": "恢复中断问答",
    "handoff.request": "申请人工服务",
    "handoff.claim": "接单",
    "handoff.close": "结束人工服务",
    "feedback.create": "提交回答反馈",
    "feedback.update": "修改回答反馈",
    "feedback.resolve": "处理回答反馈",
    "feedback.reopen": "重新打开反馈",
}


def make_range(start=None, end=None, *, now=None):
    if start is None and end is None:
        midnight = (
            (now or datetime.now(UTC))
            .astimezone(SHANGHAI)
            .replace(hour=0, minute=0, second=0, microsecond=0)
        )
        start, end = midnight - timedelta(days=29), midnight + timedelta(days=1)
    if start is None or end is None or start.tzinfo is None or end.tzinfo is None:
        raise AuthError(422, "VALIDATION_ERROR", "请提供完整的带时区起止时间")
    try:
        start, end = start.astimezone(UTC), end.astimezone(UTC)
        # Both the database instants and business-day boundaries must be representable.
        start.astimezone(SHANGHAI)
        end.astimezone(SHANGHAI)
    except OverflowError:
        raise AuthError(422, "VALIDATION_ERROR", "时间超出支持的时区范围") from None
    if not start < end or end - start > timedelta(days=366):
        raise AuthError(422, "VALIDATION_ERROR", "时间范围须为正且不超过366天")
    return RangeView(start=start, end=end)


def require_admin(db, actor):
    current = db.scalar(
        select(User.id).where(
            User.id == actor.user_id, User.is_active.is_(True), User.role == "admin"
        )
    )
    if actor.role != "admin" or current is None:
        raise AuthError(403, "FORBIDDEN", "没有访问权限")


def ratio(numerator, denominator):
    return dict(
        numerator=numerator,
        denominator=denominator,
        value=numerator / denominator if denominator else None,
    )


def get_stats(session_factory, actor, period):
    with session_factory() as db:
        db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        db.execute(text("SET TRANSACTION READ ONLY"))
        require_admin(db, actor)
        as_of = db.scalar(select(func.transaction_timestamp()))
        states, answers, distinct, latency, fields, rows, popular = repo.generations(db, period)
        logins, handoffs, backlog, feedback_rows, jobs, documents = repo.other_metrics(db, period)
        state_counts = {
            key: states.get(key, 0) for key in ("complete", "failed", "cancelled", "generating")
        }
        classified = {key: answers.get(key, 0) for key in ("answered", "clarify", "no_answer")}
        complete = state_counts["complete"]
        terminal = complete + state_counts["failed"] + state_counts["cancelled"]
        tokens = {}
        for key, (known_sum, known_count) in fields.items():
            tokens[key] = dict(
                value=int(known_sum) if terminal and known_count == terminal else None,
                known_sum=int(known_sum or 0),
                known_count=known_count,
                missing_count=terminal - known_count,
                coverage=known_count / terminal if terminal else None,
            )
        daily = {}
        day = period.start.astimezone(SHANGHAI).date()
        last = (period.end - timedelta(microseconds=1)).astimezone(SHANGHAI).date()
        while day <= last:
            daily[day] = dict(
                date=day, accepted=0, complete=0, failed=0, cancelled=0, generating=0, no_answer=0
            )
            if day == last:
                break
            day += timedelta(days=1)
        for day, status, answer, amount in rows:
            daily[day]["accepted"] += amount
            daily[day][status] += amount
            if status == "complete" and answer == "no_answer":
                daily[day]["no_answer"] += amount
        feedback = dict(total=0, up=0, down=0, open=0, resolved=0)
        for rating, status, amount in feedback_rows:
            feedback["total"] += amount
            feedback[rating] += amount
            feedback[status] += amount
        feedback["satisfaction"] = ratio(feedback["up"], feedback["total"])
        job_counts = {"parse": {}, "index": {}}
        for kind, state, amount in jobs:
            job_counts[kind][state] = amount
        return StatsView(
            range=period,
            as_of=as_of,
            logins={"successful": logins},
            generations=dict(
                accepted=sum(state_counts.values()),
                distinct_users=distinct,
                **state_counts,
                **classified,
                unclassified_complete=complete - sum(classified.values()),
                no_answer_ratio=ratio(classified["no_answer"], sum(classified.values())),
            ),
            latency=dict(
                average_ms=float(latency[0]) if latency[0] is not None else None,
                sample_count=latency[1],
                missing_count=complete - latency[1],
            ),
            tokens=dict(
                terminal_count=terminal, pending_count=state_counts["generating"], **tokens
            ),
            handoffs=dict(
                period=handoffs, current={key: backlog.get(key, 0) for key in ("queued", "human")}
            ),
            feedback=feedback,
            ingestion=dict(period_jobs=job_counts, current_documents=documents),
            daily=list(daily.values()),
            popular_questions=[
                dict(preview=content[:200], count=amount, truncated=len(content) > 200)
                for content, amount in popular
            ],
        )


def _uuid(value):
    try:
        return UUID(value) if isinstance(value, str) else None
    except ValueError:
        return None


def safe_metadata(action, raw):
    if not isinstance(raw, dict) or action not in ACTIONS:
        return {}
    result = {}
    allowed = {}
    if action == "user.update":
        allowed = {"fields": {"role", "is_active", "display_name"}}
        for key in ("before", "after"):
            value = raw.get(key)
            if isinstance(value, dict):
                result[key] = {}
                if value.get("role") in ("user", "agent", "admin"):
                    result[key]["role"] = value["role"]
                if type(value.get("is_active")) is bool:
                    result[key]["is_active"] = value["is_active"]
    elif action.startswith("knowledge."):
        allowed = {
            "version": "positive",
            "member_count": "count",
            "fields": {"name", "description", "visibility", "is_active"},
        }
    elif action.startswith("faq."):
        allowed = {
            "kb_id": "uuid",
            "version": "positive",
            "fields": {"question", "answer", "is_active"},
        }
    elif action.startswith("document."):
        allowed = {"kb_id": "uuid"}
    elif action.startswith("handoff."):
        allowed = {"conversation_id": "uuid"}
    elif action.startswith("feedback."):
        allowed = {
            "conversation_id": "uuid",
            "rating": ("up", "down"),
            "status": ("open", "resolved"),
            "changed_fields": {"rating", "comment", "status", "resolution"},
        }
    elif action in ("generation.finish", "generation.recover"):
        allowed = {
            "status": ("complete", "failed", "cancelled", "generating"),
            "latency_ms": "count",
            "error_code": "error",
        }
    elif action == "conversation.transition":
        allowed = {key: ("bot", "queued", "human", "closed") for key in ("from", "to")}
    for key, rule in allowed.items():
        value = raw.get(key)
        if rule == "error":
            parsed = safe_error_code(value)
            if parsed != "UNKNOWN_ERROR":
                result[key] = parsed
        elif rule == "uuid":
            parsed = _uuid(value)
            if parsed is not None:
                result[key] = parsed
        elif rule in ("positive", "count"):
            if type(value) is int and value >= (1 if rule == "positive" else 0):
                result[key] = value
        elif isinstance(rule, set):
            if isinstance(value, list):
                result[key] = [item for item in value if isinstance(item, str) and item in rule][
                    :10
                ]
        elif isinstance(rule, tuple) and isinstance(value, str) and value in rule:
            result[key] = value
    return result


def project_audit(row):
    action = row.action if row.action in ACTIONS else "unknown"
    parsed_request_id = _uuid(row.request_id)
    request_id = str(parsed_request_id) if parsed_request_id is not None else None
    return AuditEventView(
        id=row.id,
        actor_id=row.actor_id,
        action=action,
        summary=ACTIONS.get(action, "其他审计事件"),
        target_type=row.target_type
        if row.target_type
        in ("user", "knowledge_base", "faq", "document", "conversation", "feedback", "handoff")
        else "unknown",
        target_id=_uuid(row.target_id),
        outcome=row.outcome if row.outcome in ("success", "failure", "rate_limited") else "unknown",
        request_id=request_id,
        created_at=row.created_at,
        metadata=safe_metadata(action, row.event_metadata),
    )


def list_audit_events(db, actor, period, filters, page=1, page_size=20):
    require_admin(db, actor)
    query = select(AuditEvent).where(*repo.interval(AuditEvent.created_at, period))
    for field, value in filters.items():
        if value is not None:
            query = query.where(
                getattr(AuditEvent, field) == (str(value) if field == "target_id" else value)
            )
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(
        query.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return AuditPage(
        items=[project_audit(row) for row in rows], total=total, page=page, page_size=page_size
    )


def get_audit_event(db, actor, event_id):
    require_admin(db, actor)
    row = db.get(AuditEvent, event_id)
    if row is None:
        raise AuthError(404, "NOT_FOUND", "记录不存在")
    return project_audit(row)
