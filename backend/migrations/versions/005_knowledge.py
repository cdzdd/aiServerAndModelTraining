"""Knowledge bases, membership and versioned FAQ content."""

import sqlalchemy as sa
from alembic import op

revision = "005_knowledge"
down_revision = "002_auth"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "knowledge_bases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(2000), nullable=False),
        sa.Column("visibility", sa.String(10), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("visibility IN ('public','restricted')", name="knowledge_visibility"),
        sa.CheckConstraint("version >= 1", name="knowledge_version"),
    )
    op.create_table(
        "knowledge_memberships",
        sa.Column("kb_id", sa.Uuid(), sa.ForeignKey("knowledge_bases.id"), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), primary_key=True),
    )
    op.create_index("ix_knowledge_memberships_user_id", "knowledge_memberships", ["user_id"])
    op.create_table(
        "faqs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("kb_id", sa.Uuid(), sa.ForeignKey("knowledge_bases.id"), nullable=False),
        sa.Column("question", sa.String(500), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("indexed_version", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version >= 1", name="faq_version"),
        sa.CheckConstraint(
            "indexed_version IS NULL OR (indexed_version >= 1 AND indexed_version <= version)",
            name="faq_indexed_version",
        ),
    )
    op.create_index("ix_faqs_kb_id", "faqs", ["kb_id"])


def downgrade():
    op.drop_table("faqs")
    op.drop_table("knowledge_memberships")
    op.drop_table("knowledge_bases")
