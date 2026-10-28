"""persist authenticated participant survey responses"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261028_0008"
down_revision = "20261021_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "participant_survey_submissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("submission_id", sa.String(length=255), nullable=False),
        sa.Column("experience_id", sa.String(length=255), nullable=False),
        sa.Column("session_id", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("session_id", "submission_id", name="uq_survey_submission_session_id"),
    )
    op.create_index(
        "ix_survey_submission_session",
        "participant_survey_submissions",
        ["session_id", "created_at", "submission_id"],
    )
    op.create_table(
        "participant_survey_responses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("response_id", sa.String(length=255), nullable=False),
        sa.Column("submission_id", sa.String(length=255), nullable=False),
        sa.Column("experience_id", sa.String(length=255), nullable=False),
        sa.Column("session_id", sa.String(length=255), nullable=False),
        sa.Column("study_id", sa.String(length=255), nullable=False),
        sa.Column("question_id", sa.String(length=255), nullable=False),
        sa.Column("question_set_version", sa.String(length=255), nullable=False),
        sa.Column("answer_type", sa.String(length=32), nullable=False),
        sa.Column("answer", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("session_id", "response_id", name="uq_survey_response_session_id"),
    )
    op.create_index(
        "ix_survey_response_submission",
        "participant_survey_responses",
        ["session_id", "submission_id", "created_at"],
    )
    op.create_index(
        "ix_survey_response_study",
        "participant_survey_responses",
        ["study_id", "question_set_version", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_survey_response_study", table_name="participant_survey_responses")
    op.drop_index("ix_survey_response_submission", table_name="participant_survey_responses")
    op.drop_table("participant_survey_responses")
    op.drop_index("ix_survey_submission_session", table_name="participant_survey_submissions")
    op.drop_table("participant_survey_submissions")
