"""create durable telemetry tables"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261015_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telemetry_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.String(length=255), nullable=False),
        sa.Column("event_id", sa.String(length=255), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("experience_id", sa.String(length=255), nullable=False),
        sa.Column("participant_id", sa.String(length=255), nullable=True),
        sa.Column("event_type", sa.String(length=255), nullable=False),
        sa.Column("study_ids", postgresql.JSONB(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.UniqueConstraint("session_id", "event_id", name="uq_telemetry_event_identity"),
    )
    op.create_index(
        "ix_telemetry_events_order",
        "telemetry_events",
        ["session_id", "occurred_at", "ingested_at", "event_id"],
    )
    op.create_table(
        "telemetry_session_processing",
        sa.Column("session_id", sa.String(length=255), primary_key=True),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("telemetry_session_processing")
    op.drop_index("ix_telemetry_events_order", table_name="telemetry_events")
    op.drop_table("telemetry_events")
