"""persist study-scoped GeometrySnapshot v2 records"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261020_0006"
down_revision = "20261020_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "geometry_snapshots",
        sa.Column("session_id", sa.String(length=255), nullable=False),
        sa.Column("study_id", sa.String(length=255), nullable=False),
        sa.Column("snapshot_id", sa.String(length=255), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("aoi_set_version", sa.String(length=255), nullable=False),
        sa.Column("viewport_width_px", sa.Float(), nullable=False),
        sa.Column("viewport_height_px", sa.Float(), nullable=False),
        sa.Column("scroll_x_px", sa.Float(), nullable=False),
        sa.Column("scroll_y_px", sa.Float(), nullable=False),
        sa.Column("zoom", sa.Float(), nullable=False),
        sa.Column("rectangles", postgresql.JSONB(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provenance", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("session_id", "study_id", "snapshot_id"),
    )
    op.create_index(
        "ix_geometry_snapshots_scope_time",
        "geometry_snapshots",
        ["session_id", "study_id", "aoi_set_version", "captured_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_geometry_snapshots_scope_time", table_name="geometry_snapshots")
    op.drop_table("geometry_snapshots")
