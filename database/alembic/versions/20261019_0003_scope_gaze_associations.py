"""scope gaze observation association identity by session"""

import sqlalchemy as sa
from alembic import op

revision = "20261019_0003"
down_revision = "20261019_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "gaze_observation_association_records_association_id_fkey",
        "gaze_observation_association_records",
        type_="foreignkey",
    )
    op.drop_constraint(
        "gaze_observation_associations_pkey",
        "gaze_observation_associations",
        type_="primary",
    )
    op.create_primary_key(
        "gaze_observation_associations_pkey",
        "gaze_observation_associations",
        ["association_id", "session_id"],
    )
    op.create_foreign_key(
        "gaze_observation_association_records_association_scope_fkey",
        "gaze_observation_association_records",
        "gaze_observation_associations",
        ["association_id", "session_id"],
        ["association_id", "session_id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "gaze_observation_association_records_association_scope_fkey",
        "gaze_observation_association_records",
        type_="foreignkey",
    )
    connection = op.get_bind()
    duplicate = connection.execute(
        sa.text(
            """
            SELECT association_id
            FROM gaze_observation_associations
            GROUP BY association_id
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        )
    ).first()
    if duplicate is not None:
        raise RuntimeError(
            "cannot downgrade: association IDs are no longer globally unique"
        )
    op.drop_constraint(
        "gaze_observation_associations_pkey",
        "gaze_observation_associations",
        type_="primary",
    )
    op.create_primary_key(
        "gaze_observation_associations_pkey",
        "gaze_observation_associations",
        ["association_id"],
    )
    op.create_foreign_key(
        "gaze_observation_association_records_association_id_fkey",
        "gaze_observation_association_records",
        "gaze_observation_associations",
        ["association_id"],
        ["association_id"],
        ondelete="CASCADE",
    )
