"""bind participant sessions to hashed opaque credentials"""

import sqlalchemy as sa
from alembic import op

revision = "20261020_0005"
down_revision = "20261020_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("participant_sessions", sa.Column("credential_hash", sa.String(length=64), nullable=True))
    op.create_unique_constraint("uq_participant_session_credential_hash", "participant_sessions", ["credential_hash"])


def downgrade() -> None:
    op.drop_constraint("uq_participant_session_credential_hash", "participant_sessions", type_="unique")
    op.drop_column("participant_sessions", "credential_hash")
