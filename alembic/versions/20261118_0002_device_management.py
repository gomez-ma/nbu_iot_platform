"""Add IoT devices and MQTT topic permissions.

Revision ID: 20261118_0002
Revises: 20261118_0001
Create Date: 2026-11-18
"""
from alembic import op
import sqlalchemy as sa

revision = "20261118_0002"
down_revision = "20261118_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "devices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("credential_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("client_id", name="uq_device_client_id"),
    )
    op.create_index("ix_devices_project_id", "devices", ["project_id"])
    op.create_index("ix_devices_client_id", "devices", ["client_id"])
    op.create_table(
        "device_topics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("device_id", sa.Integer(), sa.ForeignKey("devices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("topic", sa.String(length=512), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("qos", sa.JSON(), nullable=False),
        sa.Column("retain", sa.String(length=8), nullable=False),
        sa.UniqueConstraint("device_id", "topic", "action", name="uq_device_topic_action"),
    )
    op.create_index("ix_device_topics_device_id", "device_topics", ["device_id"])


def downgrade() -> None:
    op.drop_index("ix_device_topics_device_id", table_name="device_topics")
    op.drop_table("device_topics")
    op.drop_index("ix_devices_client_id", table_name="devices")
    op.drop_index("ix_devices_project_id", table_name="devices")
    op.drop_table("devices")
