"""Local-only isolated browser fixtures; stdout is a single JSON result, never credentials URLs."""

import json
import re
import sys
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from app.core.config import Settings
from app.core.security import password_hasher
from app.modules.auth.models import User
from app.modules.chat.models import GenerationUsage
from tests.analytics.metrics_helpers import PARAMS, seed_metrics

PASSWORD = "synthetic-analytics-password"


def run(payload):
    settings = Settings()
    url = make_url(settings.database_url.get_secret_value())
    if settings.app_env == "production" or url.host not in ("localhost", "127.0.0.1"):
        raise ValueError("Analytics fixtures require a local non-production database")
    action = payload.get("action", "seed")
    schema = f"analytics_e2e_{uuid4().hex}" if action == "seed" else payload.get("schema", "")
    if not isinstance(schema, str) or not re.fullmatch(r"analytics_e2e_[0-9a-f]{32}", schema):
        raise ValueError("Invalid analytics fixture schema")
    if action not in ("seed", "populate", "cleanup"):
        raise ValueError("Invalid fixture action")
    # Discard a caller search_path so management never accidentally inherits another fixture.
    admin_engine = create_engine(url.difference_update_query(["options"]), hide_parameters=True)
    scoped = create_engine(
        url.update_query_dict({"options": f"-csearch_path={schema},public"}), hide_parameters=True
    )
    try:
        if action != "seed":
            with admin_engine.connect() as connection:
                exists = connection.scalar(
                    text("SELECT 1 FROM pg_namespace WHERE nspname=:schema"), {"schema": schema}
                )
                if not exists:
                    raise ValueError("Fixture schema does not exist")
        if action == "cleanup":
            with admin_engine.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True))
            return {"schema": schema, "cleaned": True}
        if action == "seed":
            with admin_engine.begin() as connection:
                connection.execute(CreateSchema(schema))
            config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
            with scoped.begin() as connection:
                config.attributes["connection"] = connection
                command.upgrade(config, "head")
            with Session(scoped) as db:
                people = [
                    User(
                        username=f"analytics-{role}",
                        display_name=f"虚构统计验收-{role}",
                        role=role,
                        password_hash=password_hasher.hash(PASSWORD),
                    )
                    for role in ("admin", "user", "agent")
                ]
                db.add_all(people)
                db.flush()
                users = {
                    person.role: {
                        "id": str(person.id),
                        "username": person.username,
                        "password": PASSWORD,
                    }
                    for person in people
                }
                db.commit()
            return {"schema": schema, "users": users}
        with Session(scoped) as db:
            if db.scalar(select(func.count()).select_from(GenerationUsage)):
                raise ValueError("Fixture already populated")
            seed_metrics(db)
            db.commit()
        return {
            "schema": schema,
            "range": PARAMS,
            "expected": {
                "raw_audit_sentinel": "analytics-raw-secret-sentinel",
                "successful_logins": 2,
                "accepted": 14,
                "distinct_users": 3,
                "complete": 10,
                "failed": 2,
                "cancelled": 1,
                "generating": 1,
                "no_answer_ratio": 0.2,
                "satisfaction": 0.75,
                "average_ms": 800,
                "feedback_total": 4,
                "prompt_known_sum": 1200,
                "prompt_missing_count": 1,
                "popular_first_count": 4,
            },
        }
    finally:
        scoped.dispose()
        admin_engine.dispose()


if __name__ == "__main__":
    print(json.dumps(run(json.loads(sys.stdin.read() or "{}")), ensure_ascii=False))
