"""Persist human handoff timestamps without duplicating conversation state."""

import sqlalchemy as sa
from alembic import op

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "handoffs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_by_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("closed_by_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.UniqueConstraint("conversation_id", name="handoff_conversation"),
        sa.CheckConstraint(
            "(claimed_at IS NULL) = (claimed_by_id IS NULL)", name="handoff_claim_pair"
        ),
        sa.CheckConstraint(
            "(closed_at IS NULL) = (closed_by_id IS NULL)", name="handoff_close_pair"
        ),
    )
    op.create_index("ix_handoffs_queue_order", "handoffs", ["requested_at", "id"])


def downgrade():
    op.drop_index("ix_handoffs_queue_order", table_name="handoffs")
    op.drop_table("handoffs")
