import pytest
from sqlalchemy import text

from tests.knowledge import conftest as fixtures

admin = fixtures.admin
auth_app = fixtures.auth_app
client = fixtures.client
user = fixtures.user
reader = fixtures.reader


@pytest.fixture(autouse=True)
def clean_ingestion(migrated_engine):
    with migrated_engine.begin() as db:
        for table in ("chunks", "ingestion_jobs", "document_revisions", "documents"):
            db.execute(text(f"DELETE FROM {table}"))
