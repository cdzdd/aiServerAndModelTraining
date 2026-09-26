"""Durable request-count budgets; callers hold the user's row lock."""

from datetime import UTC, timedelta, timezone

from sqlalchemy import func, select

from app.core.security import AuthError
from app.modules.chat.models import GenerationUsage

SHANGHAI = timezone(timedelta(hours=8), "Asia/Shanghai")


def check_budget(db, user_id, now, *, requests_per_minute, requests_per_day):
    # An already accepted request still counts if the wall clock moves backwards.
    day_start = now.astimezone(SHANGHAI).replace(hour=0, minute=0, second=0, microsecond=0)
    for start, inclusive, maximum in [
        (now - timedelta(seconds=60), False, requests_per_minute),
        (day_start.astimezone(UTC), True, requests_per_day),
    ]:
        boundary = (
            GenerationUsage.accepted_at >= start
            if inclusive
            else GenerationUsage.accepted_at > start
        )
        count = db.scalar(
            select(func.count())
            .select_from(GenerationUsage)
            .where(
                GenerationUsage.user_id == user_id,
                boundary,
            )
        )
        if count >= maximum:
            raise AuthError(429, "CHAT_RATE_LIMITED", "问答请求已达限额，请稍后再试")
