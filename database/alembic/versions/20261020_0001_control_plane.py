"""add Experience registry and researcher audit trail"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261020_0001"
down_revision = "20261019_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "control_experiences",
        sa.Column("experience_id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("allowed_origins", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("updated_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_control_experiences_status", "control_experiences", ["status"])
    op.create_table(
        "control_plane_audit_events",
        sa.Column("audit_id", sa.String(length=36), primary_key=True),
        sa.Column("actor_id", sa.String(length=255), nullable=False),
        sa.Column("actor_role", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("target_type", sa.String(length=80), nullable=False),
        sa.Column("target_id", sa.String(length=255), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=False),
    )
    op.create_index(
        "ix_control_audit_target_time",
        "control_plane_audit_events",
        ["target_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_control_audit_target_time", table_name="control_plane_audit_events")
    op.drop_table("control_plane_audit_events")
    op.drop_index("ix_control_experiences_status", table_name="control_experiences")
    op.drop_table("control_experiences")
