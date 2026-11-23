"""Store a customer's selected public plan when registering.

Revision ID: 20261123_0016
Revises: 20261122_0015
"""
from alembic import op
import sqlalchemy as sa


revision = "20261123_0016"
down_revision = "20261122_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("requested_plan_code", sa.String(length=40), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "requested_plan_code")
