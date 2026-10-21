"""Persist bounded desktop generation jobs and hashed machine credentials."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "021_compute"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "messages",
        "latency_ms",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=True,
    )
    op.create_table(
        "compute_workers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("model_id", sa.String(200), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "compute_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("assistant_message_id", sa.Uuid(), sa.ForeignKey("messages.id"), nullable=False),
        sa.Column("generation_token", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("actor_role", sa.String(10), nullable=False),
        sa.Column("session_hash", sa.String(64), nullable=False),
        sa.Column("model_id", sa.String(200), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("payload", JSONB(), nullable=True),
        sa.Column("result", JSONB(), nullable=True),
        sa.Column("result_digest", sa.String(64), nullable=True),
        sa.Column("error_code", sa.String(50), nullable=True),
        sa.Column("worker_id", sa.Uuid(), sa.ForeignKey("compute_workers.id"), nullable=True),
        sa.Column("lease_hash", sa.String(64), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued','running','succeeded','failed','cancelled','consumed')",
            name="compute_job_status",
        ),
    )
    op.create_index("ix_compute_jobs_status_created", "compute_jobs", ["status", "created_at"])
    op.create_index("ix_compute_jobs_created", "compute_jobs", ["created_at"])


def downgrade():
    # PostgreSQL rejects out-of-range values rather than truncating recovery evidence.
    op.alter_column(
        "messages",
        "latency_ms",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=True,
    )
    op.drop_table("compute_jobs")
    op.drop_table("compute_workers")
