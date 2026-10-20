"""add durable participant session and consent state foundation"""

import sqlalchemy as sa
from alembic import op

revision = "20261020_0004"
down_revision = "20261020_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "participant_sessions",
        sa.Column("session_id", sa.String(length=255), primary_key=True),
        sa.Column("experience_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_participant_sessions_experience_id", "participant_sessions", ["experience_id"])
    op.create_table(
        "participant_consent_records",
        sa.Column("session_id", sa.String(length=255), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("policy_version", sa.String(length=255), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["participant_sessions.session_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("session_id", "scope"),
    )


def downgrade() -> None:
    op.drop_table("participant_consent_records")
    op.drop_index("ix_participant_sessions_experience_id", table_name="participant_sessions")
    op.drop_table("participant_sessions")
