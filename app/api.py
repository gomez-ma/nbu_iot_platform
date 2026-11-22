from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import case, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.config import get_settings
from app.emqx import EMQXError, get_emqx
from app.models import AdminAuditLog, BillingAccount, BillingPlan, BillingSubscription, Device, Organization, OrganizationMember, Permission, PlatformSettings, Project, ProjectMember, Role, User
from app.device_presence import heartbeat_state
from app.schemas import AddMember, AddProjectMember, BillingPlanCreate, BillingPlanUpdate, BillingSubscriptionUpdate, LoginRequest, MemberView, OrganizationCreate, OrganizationUpdate, OrganizationView, PasswordChange, PlatformAdminUpdate, PlatformAuditorUpdate, PlatformSettingsUpdate, PlatformUserCreate, PlatformUserUpdate, PlatformUserView, PlatformUsersPage, ProfileUpdate, ProjectCreate, ProjectMemberView, ProjectMembersView, ProjectUpdate, ProjectView, TokenView, UpdateMemberRole, UpdateProjectMemberRole, UserActivationUpdate, UserCreate, UserView
from app.security import create_access_token, decode_access_token_with_version, hash_password, verify_password
from app.billing import account_for_organization, ensure_quota, get_or_create_owner_account, get_subscription, subscription_payload

router = APIRouter(prefix="/api/v1")
bearer = HTTPBearer(auto_error=False)

PERMISSIONS = {
    "organizations:read": "View organization details",
    "organizations:manage": "Manage organization settings and members",
    "projects:read": "View projects",
    "projects:manage": "Create and manage projects",
    "devices:read": "View devices and connection status",
    "devices:manage": "Register devices and manage MQTT credentials and access rules",
}
ROLES = {
    "owner": ("Full organization access", set(PERMISSIONS)),
    "organization_admin": ("Manage organization and projects", set(PERMISSIONS)),
    "member": ("View organization and manage projects and devices", {"organizations:read", "projects:read", "projects:manage", "devices:read", "devices:manage"}),
    "viewer": ("View organization, projects, and devices", {"organizations:read", "projects:read", "devices:read"}),
}
PROJECT_ROLES = {
    "project_owner": ("Own and fully manage this project", set(PERMISSIONS) - {"organizations:manage"}),
    "project_admin": ("Manage project settings, devices, and members", set(PERMISSIONS) - {"organizations:manage"}),
    "project_member": ("View project and manage its devices", {"projects:read", "devices:read", "devices:manage"}),
    "project_viewer": ("View project and devices", {"projects:read", "devices:read"}),
}


def seed_rbac(db: Session) -> None:
    permission_map = {p.key: p for p in db.scalars(select(Permission)).all()}
    for key, description in PERMISSIONS.items():
        if key not in permission_map:
            permission_map[key] = Permission(key=key, description=description)
            db.add(permission_map[key])
    db.flush()
    role_map = {r.name: r for r in db.scalars(select(Role).where(Role.scope == "organization")).all()}
    for name, (description, permission_keys) in ROLES.items():
        role = role_map.get(name)
        if role is None:
            role = Role(name=name, scope="organization", description=description)
            db.add(role)
        role.permissions = [permission_map[key] for key in permission_keys]
    project_role_map = {r.name: r for r in db.scalars(select(Role).where(Role.scope == "project")).all()}
    for name, (description, permission_keys) in PROJECT_ROLES.items():
        role = project_role_map.get(name)
        if role is None:
            role = Role(name=name, scope="project", description=description)
            db.add(role)
        role.permissions = [permission_map[key] for key in permission_keys]
    # Bootstrap one platform administrator for both new and existing installations.
    # The first account is the installation owner; once an admin exists, this never
    # grants platform access to additional users.
    if not db.scalar(select(User.id).where(User.is_platform_admin.is_(True)).limit(1)):
        first_user = db.scalar(select(User).where(User.is_active.is_(True)).order_by(User.id).limit(1))
        if first_user is not None:
            first_user.is_platform_admin = True
    db.commit()


def require_platform_admin(user: User) -> None:
    if not user.is_platform_admin:
        raise HTTPException(status_code=403, detail="สิทธิ์นี้สำหรับผู้ดูแลระบบเท่านั้น")


def require_platform_reader(user: User) -> None:
    if not (user.is_platform_admin or user.is_platform_auditor):
        raise HTTPException(status_code=403, detail="สิทธิ์นี้สำหรับผู้ดูแลหรือผู้ตรวจสอบระบบเท่านั้น")


def add_admin_audit(db: Session, actor: User, action: str, target_type: str, target_id: int | str | None = None, details: dict | None = None) -> None:
    db.add(AdminAuditLog(actor_id=actor.id, actor_email=actor.email, action=action, target_type=target_type, target_id=str(target_id) if target_id is not None else None, details=details or {}))


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentication required", headers={"WWW-Authenticate": "Bearer"})
    try:
        user_id, token_version = decode_access_token_with_version(credentials.credentials)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired access token", headers={"WWW-Authenticate": "Bearer"}) from exc
    user = db.get(User, user_id)
    if not user or not user.is_active or user.token_version != token_version:
        raise HTTPException(status_code=401, detail="User account is unavailable")
    return user


def require_org(db: Session, user: User, organization_id: int, permission: str) -> OrganizationMember:
    member = db.get(OrganizationMember, (organization_id, user.id))
    if member is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    if permission not in {p.key for p in member.role.permissions}:
        raise HTTPException(status_code=403, detail="Insufficient organization permissions")
    return member


def require_project_access(db: Session, user: User, organization_id: int, project_id: int, permission: str) -> Project:
    project = db.scalar(select(Project).where(Project.id == project_id, Project.organization_id == organization_id))
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if (user.is_platform_admin or user.is_platform_auditor) and permission in {"organizations:read", "projects:read", "devices:read"}:
        return project
    organization_member = require_org(db, user, organization_id, "organizations:read")
    if organization_member.role.name in {"owner", "organization_admin"}:
        if permission not in {p.key for p in organization_member.role.permissions}:
            raise HTTPException(status_code=403, detail="Insufficient project permissions")
        return project
    project_member = db.get(ProjectMember, (project_id, user.id))
    if project_member is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if permission not in {p.key for p in project_member.role.permissions}:
        raise HTTPException(status_code=403, detail="Insufficient project permissions")
    return project


def rewrite_project_topic_namespaces(db: Session, namespace_changes: dict[int, tuple[str, str]]) -> list[Device]:
    if not namespace_changes:
        return []
    devices = db.scalars(
        select(Device)
        .where(Device.project_id.in_(namespace_changes))
        .options(selectinload(Device.topics))
    ).all()
    for device in devices:
        old_prefix, new_prefix = namespace_changes[device.project_id]
        for topic in device.topics:
            if topic.topic.startswith(old_prefix):
                topic.topic = new_prefix + topic.topic[len(old_prefix):]
    return devices


def synchronize_device_topic_namespaces(devices: list[Device]) -> None:
    if not devices:
        return
    broker = get_emqx()
    broker.ensure_access_control()
    for device in devices:
        rules = [
            {"topic": topic.topic, "action": topic.action, "permission": "allow", "qos": topic.qos, "retain": topic.retain}
            for topic in device.topics
        ]
        broker.set_device_rules(device.client_id, rules)
        broker.disconnect_client(device.client_id)


def can_manage_project_members(db: Session, user: User, organization_id: int, project_id: int) -> bool:
    if user.is_platform_auditor:
        return False
    organization_member = db.get(OrganizationMember, (organization_id, user.id))
    if organization_member is None:
        return False
    if "organizations:read" not in {p.key for p in organization_member.role.permissions}:
        return False
    if organization_member.role.name in {"owner", "organization_admin"}:
        return True
    project_member = db.get(ProjectMember, (project_id, user.id))
    return bool(project_member and project_member.role.name in {"project_owner", "project_admin"})


@router.get("/auth/registration-status")
def registration_status(db: Session = Depends(get_db)):
    settings = db.get(PlatformSettings, 1)
    return {"enabled": settings.registration_enabled if settings else True}


@router.post("/auth/register", status_code=201)
def register(data: UserCreate, db: Session = Depends(get_db)):
    settings = db.get(PlatformSettings, 1)
    if settings is not None and not settings.registration_enabled:
        raise HTTPException(status_code=403, detail="การสมัครสมาชิกถูกปิดชั่วคราว กรุณาติดต่อผู้ดูแลระบบ")
    normalized_email = data.email.lower()
    if db.scalar(select(User).where(User.email == normalized_email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    is_first_account = db.scalar(select(User.id).limit(1)) is None
    # The first account bootstraps the platform as an active administrator.
    # Every later self-registered account must be reviewed by a platform admin.
    user = User(email=normalized_email, full_name=data.full_name.strip(), password_hash=hash_password(data.password), is_platform_admin=is_first_account, is_active=is_first_account)
    db.add(user)
    db.commit()
    db.refresh(user)
    if is_first_account:
        return TokenView(access_token=create_access_token(user.id, user.token_version), user=user)
    return {"pending_approval": True, "message": "สมัครสมาชิกสำเร็จ บัญชีอยู่ระหว่างรอผู้ดูแลระบบตรวจสอบและเปิดใช้งาน"}


@router.post("/auth/login", response_model=TokenView)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == data.email.lower()))
    if user is None or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email or password is incorrect")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="บัญชีถูกระงับหรือกำลังรอผู้ดูแลระบบตรวจสอบและเปิดใช้งาน")
    return TokenView(access_token=create_access_token(user.id, user.token_version), user=user)


@router.get("/auth/me", response_model=UserView)
def me(user: User = Depends(current_user)):
    return user


@router.patch("/auth/me", response_model=UserView)
def update_profile(data: ProfileUpdate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    user.full_name = data.full_name
    db.commit()
    db.refresh(user)
    return user


@router.post("/auth/me/password", status_code=204)
def change_password(data: PasswordChange, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if not verify_password(data.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="รหัสผ่านปัจจุบันไม่ถูกต้อง")
    if verify_password(data.new_password, user.password_hash):
        raise HTTPException(status_code=400, detail="รหัสผ่านใหม่ต้องแตกต่างจากรหัสผ่านเดิม")
    user.password_hash = hash_password(data.new_password)
    db.commit()


@router.get("/admin/users", response_model=PlatformUsersPage)
def list_platform_users(q: str = "", limit: int = 50, offset: int = 0, db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_platform_reader(user)
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    query = select(User)
    if q.strip():
        search = f"%{q.strip()}%"
        query = query.where(User.email.ilike(search) | User.full_name.ilike(search))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = db.scalars(query.order_by(User.id).offset(offset).limit(limit)).all()
    return PlatformUsersPage(items=items, total=total)


@router.get("/admin/overview")
def platform_overview(db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_platform_reader(user)
    counts = {
        "users": db.scalar(select(func.count()).select_from(User)) or 0,
        "active_users": db.scalar(select(func.count()).select_from(User).where(User.is_active.is_(True))) or 0,
        "inactive_users": db.scalar(select(func.count()).select_from(User).where(User.is_active.is_(False))) or 0,
        "organizations": db.scalar(select(func.count()).select_from(Organization)) or 0,
        "projects": db.scalar(select(func.count()).select_from(Project)) or 0,
        "devices": db.scalar(select(func.count()).select_from(Device)) or 0,
        "online_devices": db.scalar(select(func.count()).select_from(Device).where(Device.is_active.is_(True), Device.broker_connected.is_(True))) or 0,
    }
    try:
        db.execute(select(1))
        database_status = "ok"
    except Exception:
        database_status = "error"
    try:
        # EMQX /status responds with plain text, while EmqxClient.request expects
        # JSON. /nodes is an authenticated JSON endpoint and works as a health probe.
        get_emqx().request("GET", "/api/v5/nodes")
        emqx_status = "ok"
    except Exception:
        emqx_status = "error"
    return {**counts, "database_status": database_status, "emqx_status": emqx_status}


@router.get("/admin/search")
def platform_search(q: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_platform_reader(user)
    term = q.strip()
    if len(term) < 2:
        raise HTTPException(status_code=422, detail="กรุณาค้นหาอย่างน้อย 2 ตัวอักษร")
    pattern = f"%{term}%"
    users = db.scalars(select(User).where(User.full_name.ilike(pattern) | User.email.ilike(pattern)).order_by(User.full_name).limit(8)).all()
    organizations = db.scalars(select(Organization).where(Organization.name.ilike(pattern) | Organization.slug.ilike(pattern)).order_by(Organization.name).limit(8)).all()
    projects = db.execute(
        select(Project, Organization.name, Organization.slug)
        .join(Organization, Organization.id == Project.organization_id)
        .where(Project.name.ilike(pattern) | Project.slug.ilike(pattern) | Organization.name.ilike(pattern))
        .order_by(Project.name).limit(8)
    ).all()
    devices = db.execute(
        select(Device, Project.name, Organization.name, Organization.slug, Project.slug)
        .join(Project, Project.id == Device.project_id)
        .join(Organization, Organization.id == Project.organization_id)
        .where(Device.name.ilike(pattern) | Device.client_id.ilike(pattern) | Project.name.ilike(pattern) | Organization.name.ilike(pattern))
        .order_by(Device.name).limit(8)
    ).all()
    return {
        "users": [{"id": item.id, "name": item.full_name, "email": item.email, "active": item.is_active} for item in users],
        "organizations": [{"id": item.id, "name": item.name, "slug": item.slug} for item in organizations],
        "projects": [{"id": project.id, "name": project.name, "slug": project.slug, "organization_name": org_name, "organization_slug": org_slug} for project, org_name, org_slug in projects],
        "devices": [{"id": item.id, "name": item.name, "client_id": item.client_id, "status": "online" if item.is_active and item.broker_connected else "offline", "project_name": project_name, "organization_name": org_name, "organization_slug": org_slug, "project_slug": project_slug} for item, project_name, org_name, org_slug, project_slug in devices],
    }


@router.get("/admin/device-diagnostics")
def list_device_diagnostics(
    q: str = "", status: str = "all", organization_id: int | None = None,
    project_id: int | None = None, limit: int = 25, offset: int = 0,
    db: Session = Depends(get_db), user: User = Depends(current_user),
):
    require_platform_reader(user)
    if status not in {"all", "online", "offline"}:
        raise HTTPException(status_code=422, detail="สถานะตัวกรองไม่ถูกต้อง")
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    filters = []
    if q.strip():
        pattern = f"%{q.strip()}%"
        filters.append(or_(Device.name.ilike(pattern), Device.client_id.ilike(pattern), Project.name.ilike(pattern), Organization.name.ilike(pattern)))
    if organization_id is not None:
        filters.append(Organization.id == organization_id)
    if project_id is not None:
        filters.append(Project.id == project_id)
    if status == "online":
        filters.extend([Device.is_active.is_(True), Device.broker_connected.is_(True)])
    elif status == "offline":
        filters.append(or_(Device.is_active.is_(False), Device.broker_connected.is_(False)))

    joins = select(Device, Project, Organization).join(Project, Project.id == Device.project_id).join(Organization, Organization.id == Project.organization_id)
    total = db.scalar(select(func.count()).select_from(Device).join(Project, Project.id == Device.project_id).join(Organization, Organization.id == Project.organization_id).where(*filters)) or 0
    rows = db.execute(joins.where(*filters).order_by(Organization.name, Project.name, Device.name).offset(offset).limit(limit)).all()
    devices = [device for device, _, _ in rows]
    try:
        live_sessions = get_emqx().connected_client_details([device.client_id for device in devices])
        emqx_status = "ok"
    except EMQXError:
        live_sessions = None
        emqx_status = "error"

    settings = get_settings()
    items = []
    for device, project, organization in rows:
        heartbeat = heartbeat_state(device.last_heartbeat_at, settings.device_heartbeat_timeout_seconds)
        broker_status = "unknown" if live_sessions is None else "online" if device.is_active and device.client_id in live_sessions else "offline"
        if not device.is_active:
            diagnosis = "อุปกรณ์ถูกปิดใช้งานในระบบ"
        elif broker_status == "unknown":
            recorded = "ออนไลน์" if device.broker_connected else "ออฟไลน์"
            diagnosis = f"ตรวจสถานะ EMQX ไม่ได้ · ระบบบันทึกล่าสุดว่า{recorded}"
        elif broker_status == "online" and heartbeat == "active":
            diagnosis = "การเชื่อมต่อ MQTT และ heartbeat ปกติ"
        elif broker_status == "online" and heartbeat == "stale":
            diagnosis = f"เชื่อมต่อ MQTT อยู่ แต่ heartbeat เกิน {settings.device_heartbeat_timeout_seconds} วินาที"
        elif broker_status == "online":
            diagnosis = "เชื่อมต่อ MQTT อยู่ แต่ยังไม่เคยได้รับ heartbeat"
        elif heartbeat == "active":
            diagnosis = "ออฟไลน์จาก EMQX แต่เพิ่งได้รับ heartbeat · ตรวจการตัดการเชื่อมต่อ"
        else:
            diagnosis = "ออฟไลน์จาก EMQX · ตรวจไฟเลี้ยง เครือข่าย และการตั้งค่า MQTT"
        tls = device.last_connection_tls
        if tls is None and device.last_connection_port is not None:
            if device.last_connection_port == settings.emqx_mqtt_public_tls_port:
                tls = True
            elif device.last_connection_port in {settings.emqx_mqtt_public_port, settings.emqx_mqtt_port}:
                tls = False
        last_seen = device.last_seen_at or device.last_heartbeat_at or (device.connection_event_at if device.broker_connected else None)
        items.append({
            "id": device.id, "name": device.name, "client_id": device.client_id,
            "is_active": device.is_active, "broker_status": broker_status,
            "recorded_broker_status": "online" if device.is_active and device.broker_connected else "offline",
            "heartbeat_status": heartbeat, "heartbeat_timeout_seconds": settings.device_heartbeat_timeout_seconds,
            "last_connection_port": device.last_connection_port, "last_connection_tls": tls,
            "connection_event_at": device.connection_event_at, "last_seen_at": last_seen,
            "last_heartbeat_at": device.last_heartbeat_at, "diagnosis": diagnosis,
            "organization_id": organization.id, "organization_name": organization.name,
            "project_id": project.id, "project_name": project.name,
        })
    organizations = db.execute(select(Organization.id, Organization.name).order_by(Organization.name)).all()
    projects = db.execute(select(Project.id, Project.name, Project.organization_id, Organization.name).join(Organization, Organization.id == Project.organization_id).order_by(Organization.name, Project.name)).all()
    return {
        "total": total, "emqx_status": emqx_status, "items": items,
        "organizations": [{"id": item.id, "name": item.name} for item in organizations],
        "projects": [{"id": item.id, "name": item.name, "organization_id": item.organization_id, "organization_name": item[3]} for item in projects],
    }


@router.get("/admin/settings")
def get_platform_settings(db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_platform_reader(user)
    settings = db.get(PlatformSettings, 1)
    return {"registration_enabled": settings.registration_enabled if settings else True}


@router.patch("/admin/settings")
def update_platform_settings(data: PlatformSettingsUpdate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_platform_admin(user)
    settings = db.get(PlatformSettings, 1)
    if settings is None:
        settings = PlatformSettings(id=1, registration_enabled=data.registration_enabled)
        db.add(settings)
    else:
        settings.registration_enabled = data.registration_enabled
    add_admin_audit(db, user, "platform.registration.updated", "platform_settings", 1, {"registration_enabled": data.registration_enabled})
    db.commit()
    return {"registration_enabled": settings.registration_enabled}


@router.get("/billing/plans")
def list_public_billing_plans(db: Session = Depends(get_db)):
    plans = db.scalars(select(BillingPlan).where(BillingPlan.is_active.is_(True), BillingPlan.is_public.is_(True)).order_by(BillingPlan.id)).all()
    return [{
        "code": plan.code, "name": plan.name, "description": plan.description,
        "duration_days": plan.duration_days, "max_organizations": plan.max_organizations,
        "max_projects": plan.max_projects, "max_members": plan.max_members,
        "max_devices": plan.max_devices, "max_topic_acls": plan.max_topic_acls,
    } for plan in plans]


def billing_plan_payload(plan: BillingPlan) -> dict:
    return {"id": plan.id, "code": plan.code, "name": plan.name, "description": plan.description,
            "duration_days": plan.duration_days, "max_organizations": plan.max_organizations,
            "max_projects": plan.max_projects, "max_members": plan.max_members,
            "max_devices": plan.max_devices, "max_topic_acls": plan.max_topic_acls,
            "is_public": plan.is_public, "is_active": plan.is_active}


@router.get("/admin/billing/plans")
def list_billing_plans(db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_platform_admin(user)
    plans = db.scalars(select(BillingPlan).where(BillingPlan.code != "legacy").order_by(BillingPlan.id)).all()
    return {"plans": [billing_plan_payload(plan) for plan in plans]}


@router.post("/admin/billing/plans", status_code=201)
def create_billing_plan(data: BillingPlanCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_platform_admin(user)
    if data.code == "legacy":
        raise HTTPException(status_code=422, detail="รหัสแพ็กเกจนี้สงวนไว้")
    plan = BillingPlan(**data.model_dump())
    db.add(plan)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="รหัสแพ็กเกจนี้มีอยู่แล้ว") from exc
    add_admin_audit(db, user, "billing.plan.created", "billing_plan", plan.id, {"code": plan.code, "name": plan.name})
    db.commit()
    db.refresh(plan)
    return billing_plan_payload(plan)


@router.patch("/admin/billing/plans/{plan_code}")
def update_billing_plan(plan_code: str, data: BillingPlanUpdate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_platform_admin(user)
    plan = db.scalar(select(BillingPlan).where(BillingPlan.code == plan_code).with_for_update())
    if plan is None or plan.code == "legacy":
        raise HTTPException(status_code=404, detail="ไม่พบแพ็กเกจ")
    changes = data.model_dump(exclude_unset=True)
    if plan.code == "trial" and changes.get("is_active") is False:
        raise HTTPException(status_code=409, detail="ไม่สามารถปิดแพ็กเกจทดลองได้ เพราะใช้กำหนดแพ็กเกจเริ่มต้นให้บัญชีใหม่")
    for field, value in changes.items():
        setattr(plan, field, value)
    add_admin_audit(db, user, "billing.plan.updated", "billing_plan", plan.id, {"code": plan.code, "fields": list(changes)})
    db.commit()
    db.refresh(plan)
    return billing_plan_payload(plan)


@router.get("/billing/usage")
def get_my_billing_usage(db: Session = Depends(get_db), user: User = Depends(current_user)):
    accounts = db.scalars(select(BillingAccount).where(BillingAccount.owner_user_id == user.id).order_by(BillingAccount.id)).all()
    return {"accounts": [subscription_payload(db, account) for account in accounts]}


@router.get("/admin/billing/accounts")
def list_billing_accounts(db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_platform_reader(user)
    accounts = db.scalars(
        select(BillingAccount)
        .options(selectinload(BillingAccount.owner), selectinload(BillingAccount.subscription).selectinload(BillingSubscription.plan))
        .order_by(BillingAccount.created_at.desc(), BillingAccount.id.desc())
    ).all()
    results = []
    for account in accounts:
        if account.subscription is None:
            subscription = None
        else:
            subscription = subscription_payload(db, account)
        results.append({
            "id": account.id, "name": account.name,
            "owner_user_id": account.owner_user_id,
            "owner_name": account.owner.full_name, "owner_email": account.owner.email,
            "created_at": account.created_at, "subscription": subscription,
        })
    plans = db.scalars(select(BillingPlan).where(BillingPlan.is_active.is_(True), BillingPlan.code != "legacy").order_by(BillingPlan.id)).all()
    return {"accounts": results, "plans": [{"code": p.code, "name": p.name, "description": p.description, "duration_days": p.duration_days, "max_organizations": p.max_organizations, "max_projects": p.max_projects, "max_members": p.max_members, "max_devices": p.max_devices, "max_topic_acls": p.max_topic_acls} for p in plans]}


@router.put("/admin/billing/accounts/{account_id}/subscription")
def assign_billing_subscription(account_id: int, data: BillingSubscriptionUpdate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_platform_admin(user)
    account = db.scalar(select(BillingAccount).where(BillingAccount.id == account_id).with_for_update())
    if account is None:
        raise HTTPException(status_code=404, detail="ไม่พบบัญชีลูกค้า")
    plan = db.scalar(select(BillingPlan).where(BillingPlan.code == data.plan_code, BillingPlan.is_active.is_(True), BillingPlan.code != "legacy"))
    if plan is None:
        raise HTTPException(status_code=404, detail="ไม่พบแพ็กเกจที่เปิดใช้งาน")
    quota_fields = ("max_organizations", "max_projects", "max_members", "max_devices", "max_topic_acls")
    if plan.code == "enterprise" and set(data.quota_overrides) != set(quota_fields):
        raise HTTPException(status_code=422, detail="แพ็กเกจองค์กรต้องกำหนดโควตาทั้ง 5 รายการก่อนบันทึก (ใส่ 0 หากไม่อนุญาต หรือปล่อย null เมื่อตั้งใจให้ไม่จำกัด)")
    now = datetime.now(timezone.utc)
    duration_days = data.duration_days if data.duration_days is not None else plan.duration_days
    ends_at = now + timedelta(days=duration_days) if duration_days is not None else None
    grace_until = ends_at + timedelta(days=data.grace_days) if ends_at is not None else None
    status = data.status or ("trial" if plan.code == "trial" else "active")
    limits_snapshot = {field: getattr(plan, field) for field in quota_fields}
    subscription = db.scalar(select(BillingSubscription).where(BillingSubscription.billing_account_id == account.id).with_for_update())
    if subscription is None:
        subscription = BillingSubscription(billing_account_id=account.id, plan_id=plan.id, status=status, starts_at=now, ends_at=ends_at, grace_until=grace_until, limits_snapshot=limits_snapshot, quota_overrides=data.quota_overrides)
        db.add(subscription)
    else:
        subscription.plan_id = plan.id
        subscription.status = status
        subscription.starts_at = now
        subscription.ends_at = ends_at
        subscription.grace_until = grace_until
        subscription.limits_snapshot = limits_snapshot
        subscription.quota_overrides = data.quota_overrides
    add_admin_audit(db, user, "billing.subscription.updated", "billing_account", account.id, {
        "plan_code": plan.code, "status": status, "duration_days": duration_days,
        "grace_days": data.grace_days, "quota_overrides": data.quota_overrides,
    })
    db.commit()
    db.refresh(account)
    return subscription_payload(db, account)


@router.get("/admin/audit-logs")
def list_admin_audit_logs(limit: int = 50, offset: int = 0, db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_platform_reader(user)
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    total = db.scalar(select(func.count()).select_from(AdminAuditLog)) or 0
    entries = db.scalars(select(AdminAuditLog).order_by(AdminAuditLog.created_at.desc(), AdminAuditLog.id.desc()).offset(offset).limit(limit)).all()
    user_ids = {int(item.target_id) for item in entries if item.target_type == "user" and item.target_id and item.target_id.isdigit()}
    device_ids = {int(item.target_id) for item in entries if item.target_type == "device" and item.target_id and item.target_id.isdigit()}
    plan_ids = {int(item.target_id) for item in entries if item.target_type == "billing_plan" and item.target_id and item.target_id.isdigit()}
    users_by_id = {item.id: item for item in db.scalars(select(User).where(User.id.in_(user_ids))).all()} if user_ids else {}
    devices_by_id = {item.id: item for item in db.scalars(select(Device).where(Device.id.in_(device_ids))).all()} if device_ids else {}
    plans_by_id = {item.id: item for item in db.scalars(select(BillingPlan).where(BillingPlan.id.in_(plan_ids))).all()} if plan_ids else {}
    target_labels = {"platform_settings:1": "การรับสมัครสมาชิก"}
    target_labels.update({f"user:{item.id}": f"บัญชีผู้ใช้: {item.full_name} · {item.email}" for item in users_by_id.values()})
    target_labels.update({f"device:{item.id}": f"อุปกรณ์: {item.name} · {item.client_id}" for item in devices_by_id.values()})
    target_labels.update({f"billing_plan:{item.id}": f"แพ็กเกจ: {item.name} · {item.code}" for item in plans_by_id.values()})
    items = []
    for item in entries:
        target_label = target_labels.get(f"{item.target_type}:{item.target_id}")
        if target_label is None and item.target_type == "user":
            target_label = f"บัญชีผู้ใช้: {item.details.get('email', 'บัญชีที่ถูกลบ')}" if item.details.get("email") else "บัญชีผู้ใช้"
        if target_label is None and item.target_type == "device":
            target_label = f"อุปกรณ์: {item.details.get('client_id', 'ไม่ทราบ Client ID')}"
        items.append({"id": item.id, "actor_email": item.actor_email, "action": item.action, "target_type": item.target_type, "target_id": item.target_id, "target_label": target_label or item.target_type, "details": item.details, "created_at": item.created_at})
    return {"total": total, "items": items}


@router.patch("/admin/users/{user_id}/auditor", response_model=PlatformUserView)
def update_platform_auditor(user_id: int, data: PlatformAuditorUpdate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_platform_admin(user)
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="ไม่พบบัญชีผู้ใช้")
    if target.is_platform_admin:
        raise HTTPException(status_code=400, detail="บัญชีผู้ดูแลระบบเต็มรูปแบบไม่สามารถตั้งเป็นผู้ตรวจสอบได้")
    target.is_platform_auditor = data.is_platform_auditor
    target.token_version += 1
    add_admin_audit(db, user, "user.auditor.updated", "user", target.id, {"is_platform_auditor": data.is_platform_auditor})
    db.commit()
    db.refresh(target)
    return target


@router.patch("/admin/users/{user_id}/admin", response_model=PlatformUserView)
def update_platform_admin(user_id: int, data: PlatformAdminUpdate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_platform_admin(user)
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="ไม่พบบัญชีผู้ใช้")
    if target.id == user.id and not data.is_platform_admin:
        raise HTTPException(status_code=400, detail="ไม่สามารถถอดสิทธิ์ผู้ดูแลระบบของบัญชีที่กำลังใช้งานอยู่ได้")
    if target.is_platform_admin != data.is_platform_admin:
        if not data.is_platform_admin:
            other_admins = db.scalar(select(func.count()).select_from(User).where(User.is_platform_admin.is_(True), User.id != target.id)) or 0
            if other_admins == 0:
                raise HTTPException(status_code=400, detail="ต้องเหลือผู้ดูแลระบบอย่างน้อยหนึ่งบัญชี")
            if target.is_active:
                other_active_admins = db.scalar(select(func.count()).select_from(User).where(User.is_platform_admin.is_(True), User.is_active.is_(True), User.id != target.id)) or 0
                if other_active_admins == 0:
                    raise HTTPException(status_code=400, detail="ต้องเหลือผู้ดูแลระบบที่ใช้งานได้อย่างน้อยหนึ่งบัญชี")
        target.is_platform_admin = data.is_platform_admin
        if data.is_platform_admin:
            target.is_platform_auditor = False
        target.token_version += 1
        add_admin_audit(db, user, "user.admin.updated", "user", target.id, {"is_platform_admin": data.is_platform_admin})
        db.commit()
        db.refresh(target)
    return target


@router.post("/admin/devices/{device_id}/retry-acl", status_code=204)
def retry_device_acl_sync(device_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_platform_admin(user)
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="ไม่พบอุปกรณ์")
    try:
        broker = get_emqx()
        broker.ensure_access_control()
        broker.set_device_rules(device.client_id, [
            {"topic": topic.topic, "action": topic.action, "permission": "allow", "qos": topic.qos, "retain": topic.retain}
            for topic in device.topics
        ])
    except EMQXError as exc:
        raise HTTPException(status_code=503, detail=f"ซิงก์ ACL กับ EMQX ไม่สำเร็จ: {exc}") from exc
    add_admin_audit(db, user, "device.acl.retry", "device", device.id, {"client_id": device.client_id})
    db.commit()


@router.post("/admin/users/{user_id}/revoke-sessions", status_code=204)
def revoke_user_sessions(user_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_platform_admin(user)
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="ไม่พบบัญชีผู้ใช้")
    target.token_version += 1
    add_admin_audit(db, user, "user.sessions.revoked", "user", target.id)
    db.commit()


@router.post("/admin/users", response_model=PlatformUserView, status_code=201)
def create_platform_user(data: PlatformUserCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_platform_admin(user)
    target = User(email=data.email.lower(), full_name=data.full_name, password_hash=hash_password(data.password))
    db.add(target)
    add_admin_audit(db, user, "user.created", "user", details={"email": target.email})
    try:
        db.commit()
        db.refresh(target)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="อีเมลนี้มีบัญชีอยู่แล้ว") from exc
    return target


@router.patch("/admin/users/{user_id}/details", response_model=PlatformUserView)
def update_platform_user_details(user_id: int, data: PlatformUserUpdate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_platform_admin(user)
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="ไม่พบบัญชีผู้ใช้")
    if data.full_name is not None:
        target.full_name = data.full_name
    if data.email is not None:
        target.email = data.email.lower()
    if data.password is not None:
        target.password_hash = hash_password(data.password)
        target.token_version += 1
    add_admin_audit(db, user, "user.updated", "user", target.id, {"fields": [field for field, value in data.model_dump(exclude_unset=True).items() if value is not None]})
    try:
        db.commit()
        db.refresh(target)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="อีเมลนี้มีบัญชีอยู่แล้ว") from exc
    return target


@router.patch("/admin/users/{user_id}", response_model=PlatformUserView)
def update_platform_user_status(user_id: int, data: UserActivationUpdate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_platform_admin(user)
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="ไม่พบบัญชีผู้ใช้")
    if target.id == user.id and not data.is_active:
        raise HTTPException(status_code=400, detail="ไม่สามารถระงับบัญชีที่กำลังใช้งานอยู่ได้")
    if target.is_platform_admin and target.is_active and not data.is_active:
        active_admins = db.scalar(select(func.count()).select_from(User).where(User.is_platform_admin.is_(True), User.is_active.is_(True))) or 0
        if active_admins <= 1:
            raise HTTPException(status_code=400, detail="ต้องมีผู้ดูแลระบบที่ใช้งานได้อย่างน้อยหนึ่งบัญชี")
    target.is_active = data.is_active
    if not data.is_active:
        target.token_version += 1
    add_admin_audit(db, user, "user.status.updated", "user", target.id, {"is_active": data.is_active})
    db.commit()
    db.refresh(target)
    return target


@router.delete("/admin/users/{user_id}", status_code=204)
def delete_platform_user(user_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_platform_admin(user)
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="ไม่พบบัญชีผู้ใช้")
    if target.id == user.id:
        raise HTTPException(status_code=400, detail="ไม่สามารถลบบัญชีที่กำลังใช้งานอยู่ได้")
    if target.is_platform_admin and target.is_active:
        active_admins = db.scalar(select(func.count()).select_from(User).where(User.is_platform_admin.is_(True), User.is_active.is_(True))) or 0
        if active_admins <= 1:
            raise HTTPException(status_code=400, detail="ต้องมีผู้ดูแลระบบที่ใช้งานได้อย่างน้อยหนึ่งบัญชี")
    owner_role = db.scalar(select(Role).where(Role.name == "owner", Role.scope == "organization"))
    for membership in target.memberships:
        if membership.role.name != "owner":
            continue
        other_members = [member for member in membership.organization.members if member.user_id != target.id]
        if not other_members:
            raise HTTPException(status_code=409, detail=f"บัญชีนี้เป็นเจ้าขององค์กร {membership.organization.name} เพียงคนเดียว กรุณาเพิ่มสมาชิกหรือจัดการองค์กรก่อนลบบัญชี")
        successor = next((member for member in other_members if member.role.name == "organization_admin"), other_members[0])
        successor.role_id = owner_role.id
    for account in db.scalars(select(BillingAccount).where(BillingAccount.owner_user_id == target.id)).all():
        successor_id = db.scalar(
            select(OrganizationMember.user_id)
            .join(Organization, Organization.id == OrganizationMember.organization_id)
            .join(Role, Role.id == OrganizationMember.role_id)
            .where(Organization.billing_account_id == account.id, OrganizationMember.user_id != target.id)
            .order_by(case((Role.name == "owner", 0), (Role.name == "organization_admin", 1), else_=2), OrganizationMember.user_id)
            .limit(1)
        )
        if successor_id is not None:
            account.owner_user_id = successor_id
        elif db.scalar(select(func.count()).select_from(Organization).where(Organization.billing_account_id == account.id)):
            raise HTTPException(status_code=409, detail=f"ไม่สามารถโอนบัญชีแพ็กเกจ {account.name} ให้สมาชิกคนอื่นได้ กรุณาเพิ่มสมาชิกก่อนลบบัญชีนี้")
    # Keep projects intact while removing their creator foreign-key dependency.
    add_admin_audit(db, user, "user.deleted", "user", target.id, {"email": target.email})
    db.execute(update(Project).where(Project.created_by == target.id).values(created_by=user.id))
    db.delete(target)
    db.commit()


@router.get("/organizations", response_model=list[OrganizationView])
def list_organizations(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.execute(
        select(Organization, Role.name)
        .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
        .join(Role, Role.id == OrganizationMember.role_id)
        .where(OrganizationMember.user_id == user.id)
        .order_by(Organization.name)
    ).all()
    return [OrganizationView.model_validate(org).model_copy(update={"role": role}) for org, role in rows]


@router.post("/organizations", response_model=OrganizationView, status_code=201)
def create_organization(data: OrganizationCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    owner_role = db.scalar(select(Role).where(Role.name == "owner", Role.scope == "organization"))
    if owner_role is None:
        seed_rbac(db)
        owner_role = db.scalar(select(Role).where(Role.name == "owner", Role.scope == "organization"))
    try:
        account = get_or_create_owner_account(db, user, data.name)
        ensure_quota(db, account, "max_organizations")
        already_account_member = db.scalar(
            select(OrganizationMember.organization_id)
            .join(Organization, Organization.id == OrganizationMember.organization_id)
            .where(Organization.billing_account_id == account.id, OrganizationMember.user_id == user.id)
            .limit(1)
        ) is not None
        if not already_account_member:
            ensure_quota(db, account, "max_members")
        organization = Organization(name=data.name.strip(), slug=data.slug, description=data.description, billing_account_id=account.id)
        db.add(organization)
        db.flush()
        db.add(OrganizationMember(organization_id=organization.id, user_id=user.id, role_id=owner_role.id))
        db.commit()
        db.refresh(organization)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Organization slug is already in use") from exc
    return OrganizationView.model_validate(organization).model_copy(update={"role": "owner"})


@router.delete("/organizations/{organization_id}", status_code=204)
def delete_organization(organization_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_org(db, user, organization_id, "organizations:manage")
    organization = db.get(Organization, organization_id)
    db.delete(organization)
    db.commit()


@router.patch("/organizations/{organization_id}", response_model=OrganizationView)
def update_organization(organization_id: int, data: OrganizationUpdate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    membership = require_org(db, user, organization_id, "organizations:manage")
    organization = db.get(Organization, organization_id)
    old_slug = organization.slug
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(organization, field, value.strip() if field == "name" and value else value)
    devices = []
    if organization.slug != old_slug:
        projects = db.scalars(select(Project).where(Project.organization_id == organization_id)).all()
        namespace_changes = {
            project.id: (f"{old_slug}/{project.slug}/", f"{organization.slug}/{project.slug}/")
            for project in projects
        }
        devices = rewrite_project_topic_namespaces(db, namespace_changes)
    try:
        db.commit()
        db.refresh(organization)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Organization slug is already in use") from exc
    if devices:
        try:
            synchronize_device_topic_namespaces(devices)
        except EMQXError as exc:
            raise HTTPException(status_code=503, detail=f"Organization slug was saved, but MQTT ACLs could not be synchronized. Retry after EMQX is available. Details: {exc}") from exc
    return OrganizationView.model_validate(organization).model_copy(update={"role": membership.role.name})


@router.get("/organizations/{organization_id}/members", response_model=list[MemberView])
def list_members(organization_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if user.is_platform_admin or user.is_platform_auditor:
        if db.get(Organization, organization_id) is None:
            raise HTTPException(status_code=404, detail="Organization not found")
    else:
        require_org(db, user, organization_id, "organizations:read")
    members = db.scalars(select(OrganizationMember).where(OrganizationMember.organization_id == organization_id).order_by(OrganizationMember.user_id)).all()
    return [MemberView(user_id=m.user_id, email=m.user.email, full_name=m.user.full_name, role=m.role.name) for m in members]


@router.post("/organizations/{organization_id}/members", response_model=MemberView, status_code=201)
def add_member(organization_id: int, data: AddMember, db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_org(db, user, organization_id, "organizations:manage")
    target = db.scalar(select(User).where(User.email == data.email.lower()))
    if target is None:
        raise HTTPException(status_code=404, detail="Create the user account before adding them to an organization")
    if db.get(OrganizationMember, (organization_id, target.id)):
        raise HTTPException(status_code=409, detail="User is already an organization member")
    account = account_for_organization(db, organization_id, lock=True)
    already_account_member = db.scalar(
        select(OrganizationMember.organization_id)
        .join(Organization, Organization.id == OrganizationMember.organization_id)
        .where(Organization.billing_account_id == account.id, OrganizationMember.user_id == target.id)
        .limit(1)
    ) is not None
    if not already_account_member:
        ensure_quota(db, account, "max_members")
    role = db.scalar(select(Role).where(Role.name == data.role, Role.scope == "organization"))
    membership = OrganizationMember(organization_id=organization_id, user_id=target.id, role_id=role.id)
    db.add(membership)
    db.commit()
    return MemberView(user_id=target.id, email=target.email, full_name=target.full_name, role=role.name)


@router.patch("/organizations/{organization_id}/members/{member_user_id}", response_model=MemberView)
def update_member_role(organization_id: int, member_user_id: int, data: UpdateMemberRole, db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_org(db, user, organization_id, "organizations:manage")
    membership = db.get(OrganizationMember, (organization_id, member_user_id))
    if membership is None:
        raise HTTPException(status_code=404, detail="Organization member not found")
    if data.full_name is None and data.role is None:
        raise HTTPException(status_code=422, detail="Provide a member name or role to update")
    if membership.role.name == "owner":
        raise HTTPException(status_code=403, detail="The organization owner cannot be edited")
    if data.full_name is not None:
        membership.user.full_name = data.full_name
    if data.role is not None:
        role = db.scalar(select(Role).where(Role.name == data.role, Role.scope == "organization"))
        membership.role_id = role.id
        role_name = role.name
    else:
        role_name = membership.role.name
    db.commit()
    return MemberView(user_id=membership.user.id, email=membership.user.email, full_name=membership.user.full_name, role=role_name)


@router.delete("/organizations/{organization_id}/members/{member_user_id}", status_code=204)
def remove_member(organization_id: int, member_user_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_org(db, user, organization_id, "organizations:manage")
    membership = db.get(OrganizationMember, (organization_id, member_user_id))
    if membership is None:
        raise HTTPException(status_code=404, detail="Organization member not found")
    if membership.role.name == "owner":
        raise HTTPException(status_code=403, detail="The organization owner cannot be removed")
    owns_project = db.scalar(select(ProjectMember.project_id).join(Project, Project.id == ProjectMember.project_id).where(
        Project.organization_id == organization_id,
        ProjectMember.user_id == member_user_id,
        ProjectMember.role.has(name="project_owner"),
    ).limit(1))
    if owns_project is not None:
        raise HTTPException(status_code=409, detail="Transfer project ownership before removing this organization member")
    project_ids = select(Project.id).where(Project.organization_id == organization_id)
    db.execute(delete(ProjectMember).where(ProjectMember.project_id.in_(project_ids), ProjectMember.user_id == member_user_id))
    db.delete(membership)
    db.commit()


@router.get("/organizations/{organization_id}/projects", response_model=list[ProjectView])
def list_projects(organization_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if user.is_platform_auditor:
        if db.get(Organization, organization_id) is None:
            raise HTTPException(status_code=404, detail="Organization not found")
        projects = db.scalars(select(Project).where(Project.organization_id == organization_id).order_by(Project.name)).all()
        return [ProjectView.model_validate(project).model_copy(update={"can_manage": False}) for project in projects]
    if user.is_platform_admin and db.get(OrganizationMember, (organization_id, user.id)) is None:
        if db.get(Organization, organization_id) is None:
            raise HTTPException(status_code=404, detail="Organization not found")
        projects = db.scalars(select(Project).where(Project.organization_id == organization_id).order_by(Project.name)).all()
        return [ProjectView.model_validate(project).model_copy(update={"can_manage": False}) for project in projects]
    membership = require_org(db, user, organization_id, "organizations:read")
    query = select(Project).where(Project.organization_id == organization_id)
    org_can_manage = membership.role.name in {"owner", "organization_admin"}
    if not org_can_manage:
        query = query.join(ProjectMember, ProjectMember.project_id == Project.id).where(ProjectMember.user_id == user.id)
    projects = db.scalars(query.order_by(Project.name)).all()
    if org_can_manage:
        return [ProjectView.model_validate(project).model_copy(update={"can_manage": True}) for project in projects]
    project_ids = [project.id for project in projects]
    manage_ids = set(db.scalars(select(ProjectMember.project_id).join(Role, Role.id == ProjectMember.role_id).where(
        ProjectMember.project_id.in_(project_ids),
        ProjectMember.user_id == user.id,
        Role.name.in_(["project_owner", "project_admin"]),
    )).all()) if project_ids else set()
    return [ProjectView.model_validate(project).model_copy(update={"can_manage": project.id in manage_ids}) for project in projects]


@router.post("/organizations/{organization_id}/projects", response_model=ProjectView, status_code=201)
def create_project(organization_id: int, data: ProjectCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_org(db, user, organization_id, "projects:manage")
    account = account_for_organization(db, organization_id, lock=True)
    ensure_quota(db, account, "max_projects")
    owner_role = db.scalar(select(Role).where(Role.name == "project_owner", Role.scope == "project"))
    project = Project(organization_id=organization_id, name=data.name.strip(), slug=data.slug, description=data.description, created_by=user.id)
    db.add(project)
    try:
        db.flush()
        db.add(ProjectMember(project_id=project.id, user_id=user.id, role_id=owner_role.id))
        db.commit()
        db.refresh(project)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Project slug is already in use for this organization") from exc
    return ProjectView.model_validate(project).model_copy(update={"can_manage": True})


@router.patch("/organizations/{organization_id}/projects/{project_id}", response_model=ProjectView)
def update_project(organization_id: int, project_id: int, data: ProjectUpdate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    project = require_project_access(db, user, organization_id, project_id, "projects:manage")
    old_slug = project.slug
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(project, field, value.strip() if field == "name" and value else value)
    devices = []
    if project.slug != old_slug:
        organization_slug = project.organization.slug
        devices = rewrite_project_topic_namespaces(
            db,
            {project.id: (f"{organization_slug}/{old_slug}/", f"{organization_slug}/{project.slug}/")},
        )
    try:
        db.commit()
        db.refresh(project)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Project slug is already in use for this organization") from exc
    if devices:
        try:
            synchronize_device_topic_namespaces(devices)
        except EMQXError as exc:
            raise HTTPException(status_code=503, detail=f"Project slug was saved, but MQTT ACLs could not be synchronized. Retry after EMQX is available. Details: {exc}") from exc
    return ProjectView.model_validate(project).model_copy(update={"can_manage": True})


@router.delete("/organizations/{organization_id}/projects/{project_id}", status_code=204)
def delete_project(organization_id: int, project_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    project = require_project_access(db, user, organization_id, project_id, "projects:manage")
    devices = db.scalars(select(Device).where(Device.project_id == project_id).order_by(Device.id)).all()
    if devices:
        broker = get_emqx()
        try:
            broker.ensure_access_control()
            for device in devices:
                broker.disconnect_client(device.client_id)
                broker.remove_device_rules(device.client_id)
                broker.delete_device_credential(device.client_id)
        except EMQXError as exc:
            raise HTTPException(status_code=503, detail=f"Could not remove all MQTT credentials and ACLs for this project. No database records were deleted; retry after EMQX is available. Details: {exc}") from exc
    db.delete(project)
    db.commit()


def require_project_member_manager(db: Session, user: User, organization_id: int, project_id: int) -> Project:
    project = require_project_access(db, user, organization_id, project_id, "projects:read")
    if not can_manage_project_members(db, user, organization_id, project_id):
        raise HTTPException(status_code=403, detail="Only project owners, project admins, or organization admins can manage project members")
    return project


@router.get("/organizations/{organization_id}/projects/{project_id}/members", response_model=ProjectMembersView)
def list_project_members(organization_id: int, project_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_project_access(db, user, organization_id, project_id, "projects:read")
    memberships = db.scalars(select(ProjectMember).where(ProjectMember.project_id == project_id).order_by(ProjectMember.user_id)).all()
    members = [ProjectMemberView(user_id=m.user_id, email=m.user.email, full_name=m.user.full_name, role=m.role.name) for m in memberships]
    return ProjectMembersView(project_id=project_id, can_manage=can_manage_project_members(db, user, organization_id, project_id), members=members)


@router.post("/organizations/{organization_id}/projects/{project_id}/members", response_model=ProjectMemberView, status_code=201)
def add_project_member(organization_id: int, project_id: int, data: AddProjectMember, db: Session = Depends(get_db), user: User = Depends(current_user)):
    project = require_project_member_manager(db, user, organization_id, project_id)
    target = db.scalar(select(User).where(User.email == data.email.lower()))
    if target is None:
        raise HTTPException(status_code=404, detail="Create the user account and add them to this organization first")
    if db.get(OrganizationMember, (organization_id, target.id)) is None:
        raise HTTPException(status_code=400, detail="กรุณาเพิ่มผู้ใช้นี้เป็นสมาชิกองค์กรก่อน จึงจะกำหนดให้เข้าร่วมโปรเจ็กต์ได้")
    if db.get(ProjectMember, (project_id, target.id)):
        raise HTTPException(status_code=409, detail="User is already assigned to this project")
    role = db.scalar(select(Role).where(Role.name == data.role, Role.scope == "project"))
    membership = ProjectMember(project_id=project.id, user_id=target.id, role_id=role.id)
    db.add(membership)
    db.commit()
    return ProjectMemberView(user_id=target.id, email=target.email, full_name=target.full_name, role=role.name)


@router.patch("/organizations/{organization_id}/projects/{project_id}/members/{member_user_id}", response_model=ProjectMemberView)
def update_project_member_role(organization_id: int, project_id: int, member_user_id: int, data: UpdateProjectMemberRole, db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_project_member_manager(db, user, organization_id, project_id)
    if data.full_name is not None:
        organization_membership = db.get(OrganizationMember, (organization_id, user.id))
        if organization_membership is None or organization_membership.role.name not in {"owner", "organization_admin"}:
            raise HTTPException(status_code=403, detail="Only organization owners or admins can edit a member's display name")
    membership = db.get(ProjectMember, (project_id, member_user_id))
    if membership is None:
        raise HTTPException(status_code=404, detail="Project member not found")
    if data.full_name is None and data.role is None:
        raise HTTPException(status_code=422, detail="Provide a member name or role to update")
    if membership.role.name == "project_owner":
        raise HTTPException(status_code=403, detail="The project owner cannot be edited")
    if data.full_name is not None:
        membership.user.full_name = data.full_name
    if data.role is not None:
        role = db.scalar(select(Role).where(Role.name == data.role, Role.scope == "project"))
        membership.role_id = role.id
        role_name = role.name
    else:
        role_name = membership.role.name
    db.commit()
    return ProjectMemberView(user_id=membership.user.id, email=membership.user.email, full_name=membership.user.full_name, role=role_name)


@router.delete("/organizations/{organization_id}/projects/{project_id}/members/{member_user_id}", status_code=204)
def remove_project_member(organization_id: int, project_id: int, member_user_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_project_member_manager(db, user, organization_id, project_id)
    membership = db.get(ProjectMember, (project_id, member_user_id))
    if membership is None:
        raise HTTPException(status_code=404, detail="Project member not found")
    if membership.role.name == "project_owner":
        raise HTTPException(status_code=403, detail="The project owner cannot be removed")
    db.delete(membership)
    db.commit()
