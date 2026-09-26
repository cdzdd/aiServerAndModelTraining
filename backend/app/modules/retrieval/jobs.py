from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert

from app.modules.ingestion.models import IngestionJob


def enqueue_faq_index(db, faq, *, retry_failed=False):
    """Caller holds the KB/source lock and commits the transaction."""
    if not faq.is_active:
        return
    db.execute(
        insert(IngestionJob)
        .values(kind="index", faq_id=faq.id, faq_version=faq.version)
        .on_conflict_do_nothing(constraint="job_faq_kind_version")
    )
    if retry_failed:
        db.execute(
            update(IngestionJob)
            .where(
                IngestionJob.kind == "index",
                IngestionJob.faq_id == faq.id,
                IngestionJob.faq_version == faq.version,
                IngestionJob.state == "failed",
            )
            .values(
                state="queued",
                error_code=None,
                finished_at=None,
                lease_until=None,
                lease_token=None,
            )
        )
