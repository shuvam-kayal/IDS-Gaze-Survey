"""pin immutable Experience configuration versions"""

import sqlalchemy as sa
from alembic import op

revision = "20261020_0003"
down_revision = "20261020_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("control_experiences", sa.Column("config_version", sa.String(80), nullable=True))
    op.execute("UPDATE control_experiences SET config_version = 'experience-config-v1:' || gen_random_uuid()::text WHERE status = 'published'")


def downgrade() -> None:
    op.drop_column("control_experiences", "config_version")
