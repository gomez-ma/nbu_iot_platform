"""Add billing accounts, package catalog, and subscriptions.

Revision ID: 20261122_0013
Revises: 20261121_0012
"""
from alembic import op
import sqlalchemy as sa


revision = "20261122_0013"
down_revision = "20261121_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "billing_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=40), nullable=False, unique=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("duration_days", sa.Integer(), nullable=True),
        sa.Column("max_organizations", sa.Integer(), nullable=True),
        sa.Column("max_projects", sa.Integer(), nullable=True),
        sa.Column("max_members", sa.Integer(), nullable=True),
        sa.Column("max_devices", sa.Integer(), nullable=True),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_billing_plans_code", "billing_plans", ["code"])
    op.create_table(
        "billing_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_billing_accounts_owner_user_id", "billing_accounts", ["owner_user_id"])
    op.add_column("organizations", sa.Column("billing_account_id", sa.Integer(), nullable=True))
    op.create_index("ix_organizations_billing_account_id", "organizations", ["billing_account_id"])
    op.create_table(
        "billing_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("billing_account_id", sa.Integer(), sa.ForeignKey("billing_accounts.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("billing_plans.id"), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("grace_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("limits_snapshot", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("quota_overrides", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_billing_subscriptions_billing_account_id", "billing_subscriptions", ["billing_account_id"])

    bind = op.get_bind()
    plan_table = sa.table("billing_plans", sa.column("id", sa.Integer), sa.column("code", sa.String), sa.column("name", sa.String), sa.column("description", sa.String))
    legacy_plan_id = bind.execute(
        sa.insert(plan_table).values(
            code="legacy", name="แพ็กเกจเดิม", description="สิทธิ์เดิมสำหรับองค์กรที่มีอยู่ก่อนเปิดใช้ระบบแพ็กเกจ"
        ).returning(plan_table.c.id)
    ).scalar_one()

    organizations = sa.table("organizations", sa.column("id", sa.Integer), sa.column("name", sa.String), sa.column("billing_account_id", sa.Integer))
    users = sa.table("users", sa.column("id", sa.Integer), sa.column("full_name", sa.String))
    memberships = sa.table("organization_members", sa.column("organization_id", sa.Integer), sa.column("user_id", sa.Integer), sa.column("role_id", sa.Integer))
    roles = sa.table("roles", sa.column("id", sa.Integer), sa.column("name", sa.String))
    owners = bind.execute(
        sa.select(organizations.c.id, organizations.c.name, sa.func.coalesce(
            sa.func.min(sa.case((roles.c.name == "owner", memberships.c.user_id))),
            sa.func.min(memberships.c.user_id),
        ).label("owner_id"))
        .select_from(organizations.outerjoin(memberships, memberships.c.organization_id == organizations.c.id)
                     .outerjoin(roles, roles.c.id == memberships.c.role_id))
        .group_by(organizations.c.id, organizations.c.name)
    ).all()
    fallback_owner = bind.execute(sa.select(users.c.id).order_by(users.c.id).limit(1)).scalar_one_or_none()
    account_ids: dict[int, int] = {}
    for org_id, org_name, owner_id in owners:
        owner_id = owner_id or fallback_owner
        if owner_id is None:
            continue
        if owner_id not in account_ids:
            owner_name = bind.execute(sa.select(users.c.full_name).where(users.c.id == owner_id)).scalar_one_or_none() or "ผู้ใช้เดิม"
            account_id = bind.execute(
                sa.text("INSERT INTO billing_accounts (name, owner_user_id) VALUES (:name, :owner_id) RETURNING id"),
                {"name": f"บัญชีเดิม · {owner_name}"[:160], "owner_id": owner_id},
            ).scalar_one()
            account_ids[owner_id] = account_id
            bind.execute(sa.text(
                "INSERT INTO billing_subscriptions (billing_account_id, plan_id, status, starts_at, quota_overrides) "
                "VALUES (:account_id, :plan_id, 'active', now(), '{}'::json)"
            ), {"account_id": account_id, "plan_id": legacy_plan_id})
        bind.execute(sa.update(organizations).where(organizations.c.id == org_id).values(billing_account_id=account_ids[owner_id]))

    # Existing installations must keep working. If orphan organizations exist,
    # attach them to the first existing account after the owner backfill.
    orphan_org_ids = bind.execute(sa.select(organizations.c.id).where(organizations.c.billing_account_id.is_(None))).scalars().all()
    if orphan_org_ids:
        account_id = next(iter(account_ids.values()), None)
        if account_id is None:
            raise RuntimeError("Cannot backfill organization billing accounts without an existing user")
        bind.execute(sa.update(organizations).where(organizations.c.id.in_(orphan_org_ids)).values(billing_account_id=account_id))

    op.create_foreign_key("fk_organizations_billing_account_id_billing_accounts", "organizations", "billing_accounts", ["billing_account_id"], ["id"], ondelete="CASCADE")
    op.alter_column("organizations", "billing_account_id", nullable=False)


def downgrade() -> None:
    op.drop_constraint("fk_organizations_billing_account_id_billing_accounts", "organizations", type_="foreignkey")
    op.drop_index("ix_organizations_billing_account_id", table_name="organizations")
    op.drop_column("organizations", "billing_account_id")
    op.drop_index("ix_billing_subscriptions_billing_account_id", table_name="billing_subscriptions")
    op.drop_table("billing_subscriptions")
    op.drop_index("ix_billing_accounts_owner_user_id", table_name="billing_accounts")
    op.drop_table("billing_accounts")
    op.drop_index("ix_billing_plans_code", table_name="billing_plans")
    op.drop_table("billing_plans")
