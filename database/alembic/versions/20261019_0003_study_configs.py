"""add studies, immutable published config snapshots, and session assignments"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261019_0003"
down_revision = "20261019_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "control_studies",
        sa.Column("study_id", sa.String(36), primary_key=True),
        sa.Column("experience_id", sa.String(36), sa.ForeignKey("control_experiences.experience_id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("eligibility_rules", postgresql.JSONB(), nullable=False),
        sa.Column("config_version", sa.String(80), nullable=True),
        sa.Column("config", postgresql.JSONB(), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_control_studies_experience_id", "control_studies", ["experience_id"])
    op.create_table(
        "control_study_assignments",
        sa.Column("session_id", sa.String(255), primary_key=True),
        sa.Column("experience_id", sa.String(36), sa.ForeignKey("control_experiences.experience_id"), nullable=False),
        sa.Column("assigned_studies", postgresql.JSONB(), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("control_study_assignments")
    op.drop_index("ix_control_studies_experience_id", table_name="control_studies")
    op.drop_table("control_studies")
