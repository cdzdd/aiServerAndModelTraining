"""512-dimensional retrieval vectors and initial FAQ indexing."""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("chunks", sa.Column("embedding", Vector(512), nullable=True))
    op.create_check_constraint(
        "chunk_embedding_metadata",
        "chunks",
        "embedding IS NULL OR (embedding_model IS NOT NULL AND embedding_version IS NOT NULL)",
    )
    op.execute("""
        INSERT INTO ingestion_jobs
            (id, kind, faq_id, faq_version, state, attempts, created_at)
        SELECT gen_random_uuid(), 'index', f.id, f.version, 'queued', 0, now()
        FROM faqs f JOIN knowledge_bases k ON k.id = f.kb_id
        WHERE f.is_active AND k.is_active
        ON CONFLICT (kind, faq_id, faq_version) DO NOTHING
    """)


def downgrade():
    op.drop_constraint("chunk_embedding_metadata", "chunks", type_="check")
    op.drop_column("chunks", "embedding")
