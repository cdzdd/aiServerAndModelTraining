"""Persist owner feedback, source identities and administrator resolution."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "011"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "feedback",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("message_id", sa.Uuid(), sa.ForeignKey("messages.id"), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("rating", sa.String(4), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("source_versions", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("resolution", sa.Text(), nullable=False),
        sa.Column("resolved_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "message_id", name="feedback_user_message"),
        sa.CheckConstraint("rating IN ('up','down')", name="feedback_rating"),
        sa.CheckConstraint("status IN ('open','resolved')", name="feedback_status"),
    )
    op.create_index("ix_feedback_message_id", "feedback", ["message_id"])
    op.create_index("ix_feedback_status_created_id", "feedback", ["status", "created_at", "id"])


def downgrade():
    op.drop_index("ix_feedback_status_created_id", table_name="feedback")
    op.drop_index("ix_feedback_message_id", table_name="feedback")
    op.drop_table("feedback")
