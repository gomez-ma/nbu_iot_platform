"""Add project-scoped membership and roles.

Revision ID: 20261118_0003
Revises: 20261118_0002
Create Date: 2026-11-18
"""
from alembic import op
import sqlalchemy as sa

revision = "20261118_0003"
down_revision = "20261118_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_members",
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role_id", sa.Integer(), sa.ForeignKey("roles.id"), nullable=False),
        sa.UniqueConstraint("project_id", "user_id", name="uq_project_member"),
    )
    op.create_index("ix_project_members_user_id", "project_members", ["user_id"])
    connection = op.get_bind()
    roles = [
        ("project_owner", "Own and fully manage this project"),
        ("project_admin", "Manage project settings, devices, and members"),
        ("project_member", "View project and manage its devices"),
        ("project_viewer", "View project and devices"),
    ]
    for name, description in roles:
        connection.execute(sa.text("INSERT INTO roles (name, scope, description) VALUES (:name, 'project', :description) ON CONFLICT (name, scope) DO NOTHING"), {"name": name, "description": description})
    connection.execute(sa.text("""
        INSERT INTO project_members (project_id, user_id, role_id)
        SELECT p.id, p.created_by, r.id
        FROM projects p JOIN roles r ON r.name = 'project_owner' AND r.scope = 'project'
        ON CONFLICT (project_id, user_id) DO NOTHING
    """))
    connection.execute(sa.text("""
        INSERT INTO project_members (project_id, user_id, role_id)
        SELECT p.id, om.user_id, r.id
        FROM projects p
        JOIN organization_members om ON om.organization_id = p.organization_id
        JOIN roles org_role ON org_role.id = om.role_id
        JOIN roles r ON r.scope = 'project' AND r.name = CASE
            WHEN org_role.name IN ('owner', 'organization_admin') THEN 'project_admin'
            WHEN org_role.name = 'viewer' THEN 'project_viewer'
            ELSE 'project_member'
        END
        WHERE om.user_id <> p.created_by
        ON CONFLICT (project_id, user_id) DO NOTHING
    """))


def downgrade() -> None:
    op.drop_index("ix_project_members_user_id", table_name="project_members")
    op.drop_table("project_members")
