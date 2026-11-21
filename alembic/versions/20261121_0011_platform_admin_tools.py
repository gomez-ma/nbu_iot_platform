"""Add platform settings, audit logs, and session revocation version.

Revision ID: 20261121_0011
Revises: 20261120_0010
"""
from alembic import op
import sqlalchemy as sa


revision = "20261121_0011"
down_revision = "20261120_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"))
    op.create_table(
        "platform_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("registration_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.execute(sa.text("INSERT INTO platform_settings (id, registration_enabled) VALUES (1, TRUE)"))
    op.create_table(
        "admin_audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("actor_email", sa.String(length=320), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("target_type", sa.String(length=40), nullable=False),
        sa.Column("target_id", sa.String(length=80), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_admin_audit_logs_action", "admin_audit_logs", ["action"])
    op.create_index("ix_admin_audit_logs_created_at", "admin_audit_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_admin_audit_logs_created_at", table_name="admin_audit_logs")
    op.drop_index("ix_admin_audit_logs_action", table_name="admin_audit_logs")
    op.drop_table("admin_audit_logs")
    op.drop_table("platform_settings")
    op.drop_column("users", "token_version")
