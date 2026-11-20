"""Store broker presence events and heartbeat timestamps.

Revision ID: 20261118_0004
Revises: 20261118_0003
Create Date: 2026-11-18
"""
from alembic import op
import sqlalchemy as sa

revision = "20261118_0004"
down_revision = "20261118_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("devices", sa.Column("broker_connected", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("devices", sa.Column("connection_event_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("devices", sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("devices", "last_heartbeat_at")
    op.drop_column("devices", "connection_event_at")
    op.drop_column("devices", "broker_connected")
