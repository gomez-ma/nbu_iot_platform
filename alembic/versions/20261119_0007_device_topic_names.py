"""Use stable device names in project-scoped MQTT topics.

Revision ID: 20261119_0007
Revises: 20261119_0006
"""
import re

from alembic import op
import sqlalchemy as sa

revision = "20261119_0007"
down_revision = "20261119_0006"
branch_labels = None
depends_on = None


def _topic_name(name: str, device_id: int, used: set[str]) -> str:
    base = re.sub(r"[^A-Za-z0-9_-]+", "_", name.strip()).strip("_-")[:80] or f"device_{device_id}"
    candidate = base
    if candidate in used:
        candidate = f"{base[:68]}_{device_id}"
    used.add(candidate)
    return candidate


def upgrade() -> None:
    op.add_column("devices", sa.Column("topic_name", sa.String(length=80), nullable=True))
    bind = op.get_bind()
    devices = bind.execute(sa.text("SELECT id, project_id, name FROM devices ORDER BY project_id, id")).mappings().all()
    used_by_project: dict[int, set[str]] = {}
    for device in devices:
        used = used_by_project.setdefault(device["project_id"], set())
        topic_name = _topic_name(device["name"], device["id"], used)
        bind.execute(
            sa.text("UPDATE devices SET topic_name = :topic_name WHERE id = :device_id"),
            {"topic_name": topic_name, "device_id": device["id"]},
        )

    op.alter_column("devices", "topic_name", existing_type=sa.String(length=80), nullable=False)
    op.create_unique_constraint("uq_device_project_topic_name", "devices", ["project_id", "topic_name"])

    rows = bind.execute(sa.text(
        "SELECT d.id, d.project_id, d.client_id, d.topic_name, p.slug AS project_slug, o.slug AS organization_slug "
        "FROM devices d JOIN projects p ON p.id = d.project_id JOIN organizations o ON o.id = p.organization_id"
    )).mappings().all()
    by_project_client = {(row["project_id"], row["client_id"]): row for row in rows}
    by_id = {row["id"]: row for row in rows}
    topic_rows = bind.execute(sa.text("SELECT id, device_id, topic FROM device_topics ORDER BY id")).mappings().all()
    for topic_row in topic_rows:
        source = by_id.get(topic_row["device_id"])
        if source is None:
            continue
        old_namespace = f"nbu/{source['organization_slug']}/{source['project_slug']}/devices/"
        topic = topic_row["topic"]
        if not topic.startswith(old_namespace):
            continue
        target_path = topic[len(old_namespace):]
        target_client_id, separator, suffix = target_path.partition("/")
        target = by_project_client.get((source["project_id"], target_client_id))
        if not separator or target is None:
            continue
        new_topic = f"{source['organization_slug']}/{source['project_slug']}/{target['topic_name']}/{suffix}"
        bind.execute(
            sa.text("UPDATE device_topics SET topic = :topic WHERE id = :topic_id"),
            {"topic": new_topic, "topic_id": topic_row["id"]},
        )


def downgrade() -> None:
    op.drop_constraint("uq_device_project_topic_name", "devices", type_="unique")
    op.drop_column("devices", "topic_name")
