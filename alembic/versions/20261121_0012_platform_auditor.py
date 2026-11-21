"""Add read-only platform auditor role.

Revision ID: 20261121_0012
Revises: 20261121_0011
"""
from alembic import op
import sqlalchemy as sa


revision = "20261121_0012"
down_revision = "20261121_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("is_platform_auditor", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("users", "is_platform_auditor")
