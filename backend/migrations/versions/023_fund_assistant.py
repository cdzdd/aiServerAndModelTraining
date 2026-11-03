"""Isolate fund subjects and conversations; observe existing desktop activity."""

import sqlalchemy as sa
from alembic import op

revision = "023_fund_assistant"
down_revision = "021_compute"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("compute_workers", sa.Column("last_seen_at", sa.DateTime(timezone=True)))
    op.create_table(
        "fund_assistant_subjects",
        sa.Column("subject", sa.String(19), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False, unique=True),
    )
    op.create_table(
        "fund_assistant_conversations",
        sa.Column(
            "conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id"), primary_key=True
        ),
        sa.Column(
            "subject",
            sa.String(19),
            sa.ForeignKey("fund_assistant_subjects.subject"),
            nullable=False,
        ),
        sa.Column("kb_id", sa.Uuid(), sa.ForeignKey("knowledge_bases.id"), nullable=False),
    )
    op.create_index(
        "ix_fund_assistant_conversations_subject", "fund_assistant_conversations", ["subject"]
    )


def downgrade():
    op.drop_table("fund_assistant_conversations")
    op.drop_table("fund_assistant_subjects")
    op.drop_column("compute_workers", "last_seen_at")
