from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.models import (
    BillingAccount,
    BillingPlan,
    BillingSubscription,
    Device,
    DeviceTopic,
    Organization,
    OrganizationMember,
    Project,
    User,
)


LIMIT_FIELDS = ("max_organizations", "max_projects", "max_members", "max_devices", "max_topic_acls")
PLAN_CATALOG = (
    {"code": "trial", "name": "ทดลองใช้", "description": "ทดลองใช้งาน 30 วัน", "duration_days": 30, "max_organizations": 1, "max_projects": 2, "max_members": 5, "max_devices": 10, "max_topic_acls": 20, "is_public": True},
    {"code": "starter", "name": "เริ่มต้น", "description": "สำหรับบุคคลหรือทีมขนาดเล็ก · รายปี", "duration_days": 365, "max_organizations": 1, "max_projects": 5, "max_members": 5, "max_devices": 50, "max_topic_acls": 100, "is_public": True},
    {"code": "business", "name": "ธุรกิจ", "description": "สำหรับบริษัทที่มีหลายทีม · รายปี", "duration_days": 365, "max_organizations": 3, "max_projects": 20, "max_members": 20, "max_devices": 500, "max_topic_acls": 1000, "is_public": True},
    {"code": "enterprise", "name": "องค์กร", "description": "โควตาและเงื่อนไขกำหนดตามสัญญา", "duration_days": None, "max_organizations": None, "max_projects": None, "max_members": None, "max_devices": None, "max_topic_acls": None, "is_public": False},
)


def seed_billing_plans(db: Session) -> None:
    for definition in PLAN_CATALOG:
        plan = db.scalar(select(BillingPlan).where(BillingPlan.code == definition["code"]))
        if plan is None:
            db.add(BillingPlan(**definition, is_active=True))
        # Preserve administrator customizations across application restarts.
    db.commit()


def create_trial_subscription(db: Session, account: BillingAccount) -> BillingSubscription:
    plan = db.scalar(select(BillingPlan).where(BillingPlan.code == "trial", BillingPlan.is_active.is_(True)))
    if plan is None:
        raise HTTPException(status_code=503, detail="ยังไม่ได้ตั้งค่าแพ็กเกจทดลอง กรุณาติดต่อผู้ดูแลระบบ")
    now = datetime.now(timezone.utc)
    subscription = BillingSubscription(
        billing_account_id=account.id,
        plan_id=plan.id,
        status="trial",
        starts_at=now,
        ends_at=now + timedelta(days=plan.duration_days or 30),
        grace_until=now + timedelta(days=(plan.duration_days or 30) + 30),
        limits_snapshot={field: getattr(plan, field) for field in LIMIT_FIELDS},
        quota_overrides={},
    )
    db.add(subscription)
    db.flush()
    return subscription


def get_or_create_owner_account(db: Session, user: User, account_name: str) -> BillingAccount:
    # Lock the user row so parallel first-organization requests cannot create
    # duplicate billing accounts and bypass the trial/organization quota.
    locked_user = db.scalar(select(User).where(User.id == user.id).with_for_update())
    account = db.scalar(select(BillingAccount).where(BillingAccount.owner_user_id == user.id).order_by(BillingAccount.id).limit(1).with_for_update())
    if account is None:
        account = BillingAccount(name=account_name.strip()[:160], owner_user_id=locked_user.id)
        db.add(account)
        db.flush()
        create_trial_subscription(db, account)
    return account


def provision_accounts_for_approved_plan_requests(db: Session) -> int:
    users = db.scalars(
        select(User).where(
            User.is_active.is_(True),
            User.is_platform_admin.is_(False),
            User.is_platform_auditor.is_(False),
            User.requested_plan_code.is_not(None),
            ~User.billing_accounts.any(),
        )
    ).all()
    for user in users:
        get_or_create_owner_account(db, user, f"บัญชีลูกค้า · {user.full_name}")
    if users:
        db.commit()
    return len(users)


def account_for_organization(db: Session, organization_id: int, *, lock: bool = False) -> BillingAccount:
    query = select(BillingAccount).join(Organization, Organization.billing_account_id == BillingAccount.id).where(Organization.id == organization_id)
    if lock:
        query = query.with_for_update()
    account = db.scalar(query)
    if account is None:
        raise HTTPException(status_code=409, detail="องค์กรนี้ยังไม่ได้ผูกกับบัญชีแพ็กเกจ กรุณาติดต่อผู้ดูแลระบบ")
    return account


def get_subscription(db: Session, account_id: int, *, lock: bool = False) -> BillingSubscription:
    query = select(BillingSubscription).where(BillingSubscription.billing_account_id == account_id)
    if lock:
        query = query.with_for_update()
    subscription = db.scalar(query)
    if subscription is None:
        raise HTTPException(status_code=409, detail="บัญชีลูกค้านี้ยังไม่มีแพ็กเกจ กรุณาติดต่อผู้ดูแลระบบ")
    return subscription


def effective_status(subscription: BillingSubscription, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    status = subscription.status
    if status in {"active", "trial", "grace"} and subscription.ends_at and subscription.ends_at <= now:
        if subscription.grace_until and subscription.grace_until > now:
            return "grace"
        return "expired"
    return status


def resolved_limits(subscription: BillingSubscription) -> dict[str, int | None]:
    limits = {field: (subscription.limits_snapshot or {}).get(field, getattr(subscription.plan, field)) for field in LIMIT_FIELDS}
    for field, value in (subscription.quota_overrides or {}).items():
        if field in LIMIT_FIELDS and (value is None or isinstance(value, int) and not isinstance(value, bool) and value >= 0):
            limits[field] = value
    return limits


def account_usage(db: Session, account_id: int) -> dict[str, int]:
    org_count = db.scalar(select(func.count(Organization.id)).where(Organization.billing_account_id == account_id)) or 0
    project_count = db.scalar(select(func.count(Project.id)).join(Organization, Project.organization_id == Organization.id).where(Organization.billing_account_id == account_id)) or 0
    member_count = db.scalar(select(func.count(distinct(OrganizationMember.user_id))).join(Organization, OrganizationMember.organization_id == Organization.id).where(Organization.billing_account_id == account_id)) or 0
    device_count = db.scalar(select(func.count(Device.id)).join(Project, Device.project_id == Project.id).join(Organization, Project.organization_id == Organization.id).where(Organization.billing_account_id == account_id)) or 0
    topic_acl_count = db.scalar(select(func.count(DeviceTopic.id)).join(Device, DeviceTopic.device_id == Device.id).join(Project, Device.project_id == Project.id).join(Organization, Project.organization_id == Organization.id).where(Organization.billing_account_id == account_id, DeviceTopic.is_system.is_(False))) or 0
    return {"max_organizations": org_count, "max_projects": project_count, "max_members": member_count, "max_devices": device_count, "max_topic_acls": topic_acl_count}


def ensure_subscription_writable(subscription: BillingSubscription) -> None:
    status = effective_status(subscription)
    if status not in {"active", "trial"}:
        raise HTTPException(status_code=403, detail={"code": "subscription_inactive", "message": "แพ็กเกจหมดอายุหรือถูกระงับ จึงไม่สามารถเพิ่มทรัพยากรได้ กรุณาต่ออายุหรือติดต่อผู้ดูแลระบบ", "status": status})


def ensure_quota(db: Session, account: BillingAccount, resource: str, *, increment: int = 1) -> tuple[BillingSubscription, dict[str, int]]:
    subscription = get_subscription(db, account.id, lock=True)
    ensure_subscription_writable(subscription)
    usage = account_usage(db, account.id)
    limits = resolved_limits(subscription)
    limit = limits.get(resource)
    used = usage[resource]
    if limit is not None and used + increment > limit:
        label = {"max_organizations": "องค์กร", "max_projects": "โปรเจ็กต์", "max_members": "สมาชิก", "max_devices": "อุปกรณ์", "max_topic_acls": "Topic ACL"}.get(resource, resource)
        raise HTTPException(status_code=409, detail={"code": "quota_exceeded", "message": f"ใช้โควตา{label}ครบแล้ว ({used}/{limit}) กรุณาอัปเกรดแพ็กเกจ", "resource": resource, "used": used, "limit": limit})
    return subscription, usage


def subscription_payload(db: Session, account: BillingAccount) -> dict:
    subscription = get_subscription(db, account.id)
    return {
        "billing_account_id": account.id,
        "billing_account_name": account.name,
        "plan_code": subscription.plan.code,
        "plan_name": subscription.plan.name,
        "plan_description": subscription.plan.description,
        "status": effective_status(subscription),
        "starts_at": subscription.starts_at,
        "ends_at": subscription.ends_at,
        "grace_until": subscription.grace_until,
        "limits": resolved_limits(subscription),
        "quota_overrides": subscription.quota_overrides or {},
        "usage": account_usage(db, account.id),
    }

