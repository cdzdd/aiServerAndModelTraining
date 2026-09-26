"""Persistent conversations, messages and accepted-request accounting."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "009"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(50), nullable=False),
        sa.Column("kb_ids", postgresql.JSONB(), nullable=False),
        sa.Column("mode", sa.String(10), nullable=False),
        sa.Column("assigned_agent_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("generation_token", sa.Uuid(), nullable=True),
        sa.CheckConstraint("mode IN ('bot','queued','human','closed')", name="conversation_mode"),
    )
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])
    op.create_index("ix_conversations_assigned_agent_id", "conversations", ["assigned_agent_id"])
    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column("author_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("citations", postgresql.JSONB(), nullable=False),
        sa.Column("client_message_id", sa.Uuid(), nullable=True),
        sa.Column("in_reply_to_id", sa.Uuid(), sa.ForeignKey("messages.id"), nullable=True),
        sa.Column("generation_token", sa.Uuid(), nullable=True),
        sa.Column("answer_status", sa.String(12), nullable=True),
        sa.Column("evidence_level", sa.String(12), nullable=True),
        sa.Column("intent", sa.String(12), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(50), nullable=True),
        sa.Column("request_id", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('user','assistant','agent','system')", name="message_role"),
        sa.CheckConstraint(
            "status IN ('generating','complete','failed','cancelled')", name="message_status"
        ),
        sa.UniqueConstraint(
            "conversation_id", "author_id", "client_message_id", name="message_client_key"
        ),
        sa.UniqueConstraint("in_reply_to_id", name="message_reply"),
    )
    op.create_index(
        "ix_messages_one_generation",
        "messages",
        ["conversation_id"],
        unique=True,
        postgresql_where=sa.text("role = 'assistant' AND status = 'generating'"),
    )
    op.create_index(
        "ix_messages_conversation_order", "messages", ["conversation_id", "created_at", "id"]
    )
    op.create_table(
        "generation_usage",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("user_message_id", sa.Uuid(), sa.ForeignKey("messages.id"), nullable=False),
        sa.Column("assistant_message_id", sa.Uuid(), sa.ForeignKey("messages.id"), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(12), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.UniqueConstraint("user_message_id", name="generation_usage_request"),
    )
    op.create_index(
        "ix_generation_usage_user_accepted", "generation_usage", ["user_id", "accepted_at"]
    )


def downgrade():
    op.drop_table("generation_usage")
    op.drop_table("messages")
    op.drop_table("conversations")
