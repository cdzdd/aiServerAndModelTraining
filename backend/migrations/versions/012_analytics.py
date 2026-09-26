"""Add range/order indexes for read-only administrator analytics."""

from alembic import op

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_audit_events_created_id", "audit_events", ["created_at", "id"])
    op.create_index("ix_generation_usage_accepted", "generation_usage", ["accepted_at"])


def downgrade():
    op.drop_index("ix_generation_usage_accepted", table_name="generation_usage")
    op.drop_index("ix_audit_events_created_id", table_name="audit_events")
