"""Add custom Topic ACL quotas and mark built-in rules.

Revision ID: 20261122_0014
Revises: 20261122_0013
"""
from alembic import op
import sqlalchemy as sa


revision = "20261122_0014"
down_revision = "20261122_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("billing_plans", sa.Column("max_topic_acls", sa.Integer(), nullable=True))
    op.add_column("device_topics", sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()))

    bind = op.get_bind()
    bind.execute(sa.text(
        "UPDATE billing_plans SET max_topic_acls = CASE code "
        "WHEN 'trial' THEN 20 WHEN 'starter' THEN 100 WHEN 'business' THEN 1000 "
        "ELSE NULL END"
    ))
    bind.execute(sa.text(
        "UPDATE billing_subscriptions AS s SET limits_snapshot = "
        "(COALESCE(s.limits_snapshot::jsonb, '{}'::jsonb) || "
        "jsonb_build_object('max_topic_acls', p.max_topic_acls))::json "
        "FROM billing_plans AS p WHERE p.id = s.plan_id"
    ))
    bind.execute(sa.text(
        "UPDATE device_topics AS dt SET is_system = TRUE "
        "FROM devices AS d JOIN projects AS p ON p.id = d.project_id "
        "JOIN organizations AS o ON o.id = p.organization_id "
        "WHERE dt.device_id = d.id AND ((dt.action = 'publish' AND dt.topic = "
        "o.slug || '/' || p.slug || '/' || d.topic_name || '/' || d.client_id || '/telemetry/#') "
        "OR (dt.action = 'subscribe' AND dt.topic = "
        "o.slug || '/' || p.slug || '/' || d.topic_name || '/' || d.client_id || '/commands/#'))"
    ))


def downgrade() -> None:
    op.drop_column("device_topics", "is_system")
    op.drop_column("billing_plans", "max_topic_acls")
