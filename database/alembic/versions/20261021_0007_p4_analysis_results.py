"""persist versioned P4 AnalysisResult records"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261021_0007"
down_revision = "20261020_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "p4_analysis_results",
        sa.Column("analysis_id", sa.String(length=36), nullable=False),
        sa.Column("analysis_request_id", sa.String(length=200), nullable=False),
        sa.Column("study_id", sa.String(length=200), nullable=False),
        sa.Column("feature_set_version", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_payload", postgresql.JSONB(), nullable=False),
        sa.Column("result_payload", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("analysis_id"),
        sa.UniqueConstraint("analysis_request_id", "study_id", name="uq_p4_analysis_request_study"),
    )
    op.create_index(
        "ix_p4_analysis_study_created",
        "p4_analysis_results",
        ["study_id", "created_at", "analysis_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_p4_analysis_study_created", table_name="p4_analysis_results")
    op.drop_table("p4_analysis_results")
