"""create durable P3 gaze associations and feature records"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261019_0002"
down_revision = "20261015_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gaze_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.String(length=255), nullable=False),
        sa.Column("sample_id", sa.String(length=255), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("coordinate_space", sa.String(length=64), nullable=False),
        sa.Column("x_normalized", sa.Float(), nullable=True),
        sa.Column("y_normalized", sa.Float(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("valid", sa.Boolean(), nullable=False),
        sa.Column("calibration_status", sa.String(length=32), nullable=False),
        sa.Column("quality_flags", postgresql.JSONB(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.UniqueConstraint("session_id", "sample_id", name="uq_gaze_record_identity"),
    )
    op.create_index(
        "ix_gaze_records_order",
        "gaze_records",
        ["session_id", "occurred_at", "sample_id"],
    )

    op.create_table(
        "gaze_observation_associations",
        sa.Column("association_id", sa.String(length=255), primary_key=True),
        sa.Column("session_id", sa.String(length=255), nullable=False),
        sa.Column("study_id", sa.String(length=255), nullable=False),
        sa.Column("trial_id", sa.String(length=255), nullable=False),
        sa.Column("aoi_set_version", sa.String(length=255), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
    )
    op.create_index(
        "ix_gaze_associations_session_scope",
        "gaze_observation_associations",
        ["session_id", "study_id", "trial_id", "window_start", "window_end"],
    )

    op.create_table(
        "gaze_observation_association_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("association_id", sa.String(length=255), nullable=False),
        sa.Column("session_id", sa.String(length=255), nullable=False),
        sa.Column("sample_id", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(
            ["association_id"],
            ["gaze_observation_associations.association_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "sample_id"],
            ["gaze_records.session_id", "gaze_records.sample_id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "association_id", "session_id", "sample_id",
            name="uq_gaze_association_record",
        ),
    )

    op.create_table(
        "feature_records",
        sa.Column("feature_record_id", sa.String(length=255), primary_key=True),
        sa.Column("experience_id", sa.String(length=255), nullable=False),
        sa.Column("study_id", sa.String(length=255), nullable=False),
        sa.Column("session_id", sa.String(length=255), nullable=False),
        sa.Column("feature_set_version", sa.String(length=64), nullable=False),
        sa.Column("config_version", sa.String(length=255), nullable=True),
        sa.Column("aoi_set_version", sa.String(length=255), nullable=True),
        sa.Column("modality", sa.String(length=64), nullable=False),
        sa.Column("window", postgresql.JSONB(), nullable=True),
        sa.Column("features", postgresql.JSONB(), nullable=False),
        sa.Column("quality", postgresql.JSONB(), nullable=False),
        sa.Column("source_event_count", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_feature_records_session_scope",
        "feature_records",
        ["session_id", "study_id", "created_at", "feature_record_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_feature_records_session_scope", table_name="feature_records")
    op.drop_table("feature_records")
    op.drop_table("gaze_observation_association_records")
    op.drop_index(
        "ix_gaze_associations_session_scope",
        table_name="gaze_observation_associations",
    )
    op.drop_table("gaze_observation_associations")
    op.drop_index("ix_gaze_records_order", table_name="gaze_records")
    op.drop_table("gaze_records")
