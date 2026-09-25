"""Synthetic users for the real browser suite, never a production bootstrap."""

import json
import sys

from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import create_db_engine
from app.core.security import password_hasher
from app.modules.auth.models import User

settings = Settings()
url = make_url(settings.database_url.get_secret_value())
if settings.app_env == "production" or url.host not in ("127.0.0.1", "localhost"):
    raise RuntimeError("Browser fixtures require a local development database")
payload = json.load(sys.stdin)
prefix = payload["prefix"]
if not prefix.startswith("kb-e2e-") or len(prefix) > 35:
    raise ValueError("Invalid test prefix")
engine = create_db_engine(settings)
with Session(engine) as db:
    users = [
        User(
            username=f"{prefix}-{role}",
            display_name=f"虚构验收-{role}",
            role=role,
            password_hash=password_hasher.hash("synthetic-browser-password"),
        )
        for role in ("admin", "user", "agent")
    ]
    db.add_all(users)
    db.flush()
    result = {user.role: {"id": str(user.id), "username": user.username} for user in users}
    db.commit()
    print(json.dumps(result))
engine.dispose()
