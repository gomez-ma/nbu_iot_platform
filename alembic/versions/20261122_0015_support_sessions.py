"""Add audited, expiring customer support sessions.

Revision ID: 20261122_0015
Revises: 20261122_0014
"""
from alembic import op
import sqlalchemy as sa

revision = "20261122_0015"
down_revision = "20261122_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "support_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("billing_account_id", sa.Integer(), sa.ForeignKey("billing_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_support_sessions_actor_user_id", "support_sessions", ["actor_user_id"])
    op.create_index("ix_support_sessions_target_user_id", "support_sessions", ["target_user_id"])
    op.create_index("ix_support_sessions_billing_account_id", "support_sessions", ["billing_account_id"])
    op.create_index("ix_support_sessions_expires_at", "support_sessions", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_support_sessions_expires_at", table_name="support_sessions")
    op.drop_index("ix_support_sessions_billing_account_id", table_name="support_sessions")
    op.drop_index("ix_support_sessions_target_user_id", table_name="support_sessions")
    op.drop_index("ix_support_sessions_actor_user_id", table_name="support_sessions")
    op.drop_table("support_sessions")
