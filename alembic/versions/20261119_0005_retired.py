"""Retired revision placeholder.

Revision ID: 20261119_0005
Revises: 20261118_0004

The telemetry, dashboard, and alert feature migration was withdrawn. Keep this
revision ID as a no-op so existing Alembic chains remain valid.
"""
revision = "20261119_0005"
down_revision = "20261118_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
