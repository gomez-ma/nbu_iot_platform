"""Clean up tables from a withdrawn feature revision.

Revision ID: 20261119_0006
Revises: 20261119_0005
"""
from alembic import op

revision = "20261119_0006"
down_revision = "20261119_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in (
        "alert_events",
        "alert_rules",
        "dashboard_widgets",
        "dashboards",
        "device_metrics",
        "telemetry_ingest_issues",
        "telemetry_samples",
    ):
        op.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')


def downgrade() -> None:
    pass
