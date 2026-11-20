"""Store whether the last device listener used TLS.

Revision ID: 20261120_0010
Revises: 20261120_0009
"""
from alembic import op
import sqlalchemy as sa

revision = "20261120_0010"
down_revision = "20261120_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("devices", sa.Column("last_connection_tls", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("devices", "last_connection_tls")
