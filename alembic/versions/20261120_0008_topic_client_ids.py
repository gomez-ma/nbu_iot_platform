"""Add target device Client IDs to MQTT topic paths.

Revision ID: 20261120_0008
Revises: 20261119_0007
"""
from alembic import op
import sqlalchemy as sa

revision = "20261120_0008"
down_revision = "20261119_0007"
branch_labels = None
depends_on = None


def _rewrite(add_client_id: bool) -> None:
    bind = op.get_bind()
    devices = bind.execute(sa.text(
        "SELECT d.id, d.project_id, d.client_id, d.topic_name, p.slug AS project_slug, o.slug AS organization_slug "
        "FROM devices d JOIN projects p ON p.id = d.project_id JOIN organizations o ON o.id = p.organization_id"
    )).mappings().all()
    device_by_topic = {(row["project_id"], row["topic_name"]): row for row in devices}
    topics = bind.execute(sa.text("SELECT t.id, t.device_id, t.topic, d.project_id "
                                  "FROM device_topics t JOIN devices d ON d.id = t.device_id ORDER BY t.id")).mappings().all()

    for item in topics:
        topic = item["topic"]
        for (project_id, topic_name), target in device_by_topic.items():
            if project_id != item["project_id"]:
                continue
            prefix = f"{target['organization_slug']}/{target['project_slug']}/{topic_name}/"
            if not topic.startswith(prefix):
                continue
            rest = topic[len(prefix):]
            if add_client_id:
                if rest.startswith(target["client_id"] + "/"):
                    break
                new_topic = prefix + target["client_id"] + "/" + rest
            else:
                client_prefix = target["client_id"] + "/"
                if not rest.startswith(client_prefix):
                    break
                new_topic = prefix + rest[len(client_prefix):]
            bind.execute(sa.text("UPDATE device_topics SET topic = :topic WHERE id = :id"),
                         {"topic": new_topic, "id": item["id"]})
            break


def upgrade() -> None:
    _rewrite(add_client_id=True)


def downgrade() -> None:
    _rewrite(add_client_id=False)
