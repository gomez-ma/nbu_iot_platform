from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.emqx import EMQXError, get_emqx
from app.models import Device, Organization, OrganizationMember, Permission, Project, ProjectMember, Role, User
from app.schemas import AddMember, AddProjectMember, LoginRequest, MemberView, OrganizationCreate, OrganizationUpdate, OrganizationView, PasswordChange, PlatformUserCreate, PlatformUserUpdate, PlatformUserView, PlatformUsersPage, ProfileUpdate, ProjectCreate, ProjectMemberView, ProjectMembersView, ProjectUpdate, ProjectView, TokenView, UpdateMemberRole, UpdateProjectMemberRole, UserActivationUpdate, UserCreate, UserView
from app.security import create_access_token, decode_access_token, hash_password, verify_password

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


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentication required", headers={"WWW-Authenticate": "Bearer"})
    try:
        user_id = decode_access_token(credentials.credentials)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired access token", headers={"WWW-Authenticate": "Bearer"}) from exc
    user = db.get(User, user_id)
    if not user or not user.is_active:
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
    organization_member = require_org(db, user, organization_id, "organizations:read")
    if organization_member.role.name in {"owner", "organization_admin"}:
        return True
    project_member = db.get(ProjectMember, (project_id, user.id))
    return bool(project_member and project_member.role.name in {"project_owner", "project_admin"})


@router.post("/auth/register", status_code=201)
def register(data: UserCreate, db: Session = Depends(get_db)):
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
        return TokenView(access_token=create_access_token(user.id), user=user)
    return {"pending_approval": True, "message": "สมัครสมาชิกสำเร็จ บัญชีอยู่ระหว่างรอผู้ดูแลระบบตรวจสอบและเปิดใช้งาน"}


@router.post("/auth/login", response_model=TokenView)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == data.email.lower()))
    if user is None or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email or password is incorrect")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="บัญชีถูกระงับหรือกำลังรอผู้ดูแลระบบตรวจสอบและเปิดใช้งาน")
    return TokenView(access_token=create_access_token(user.id), user=user)


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
    require_platform_admin(user)
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    query = select(User)
    if q.strip():
        search = f"%{q.strip()}%"
        query = query.where(User.email.ilike(search) | User.full_name.ilike(search))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = db.scalars(query.order_by(User.id).offset(offset).limit(limit)).all()
    return PlatformUsersPage(items=items, total=total)


@router.post("/admin/users", response_model=PlatformUserView, status_code=201)
def create_platform_user(data: PlatformUserCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_platform_admin(user)
    target = User(email=data.email.lower(), full_name=data.full_name, password_hash=hash_password(data.password))
    db.add(target)
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
    # Keep projects intact while removing their creator foreign-key dependency.
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
    organization = Organization(name=data.name.strip(), slug=data.slug, description=data.description)
    db.add(organization)
    try:
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
        raise HTTPException(status_code=400, detail="Add this user to the organization before assigning the project")
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
