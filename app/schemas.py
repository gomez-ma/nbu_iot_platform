from datetime import datetime

from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=160)
    password: str = Field(min_length=10, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserView(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    is_platform_admin: bool
    is_platform_auditor: bool = False
    model_config = ConfigDict(from_attributes=True)


class PlatformUserView(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    is_active: bool
    is_platform_admin: bool
    is_platform_auditor: bool = False
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class PlatformUsersPage(BaseModel):
    items: list[PlatformUserView]
    total: int


class UserActivationUpdate(BaseModel):
    is_active: bool


class PlatformAuditorUpdate(BaseModel):
    is_platform_auditor: bool


class PlatformAdminUpdate(BaseModel):
    is_platform_admin: bool


class PlatformSettingsUpdate(BaseModel):
    registration_enabled: bool


class PlatformUserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=160)
    password: str = Field(min_length=10, max_length=128)

    @field_validator("full_name")
    @classmethod
    def trim_admin_created_name(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Name must contain at least 2 characters")
        return value


class PlatformUserUpdate(BaseModel):
    email: EmailStr | None = None
    full_name: str | None = Field(default=None, min_length=2, max_length=160)
    password: str | None = Field(default=None, min_length=10, max_length=128)

    @field_validator("full_name")
    @classmethod
    def trim_admin_updated_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Name must contain at least 2 characters")
        return value


class ProfileUpdate(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)

    @field_validator("full_name")
    @classmethod
    def trim_profile_name(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Name must contain at least 2 characters")
        return value


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=10, max_length=128)


class TokenView(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserView


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    slug: str = Field(min_length=2, max_length=180, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    description: str | None = Field(default=None, max_length=2000)


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    slug: str | None = Field(default=None, min_length=2, max_length=180, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    description: str | None = Field(default=None, max_length=2000)


class OrganizationView(BaseModel):
    id: int
    name: str
    slug: str
    description: str | None
    created_at: datetime
    role: str | None = None
    model_config = ConfigDict(from_attributes=True)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    slug: str = Field(min_length=2, max_length=180, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    description: str | None = Field(default=None, max_length=2000)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    slug: str | None = Field(default=None, min_length=2, max_length=180, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    description: str | None = Field(default=None, max_length=2000)


class ProjectView(BaseModel):
    id: int
    organization_id: int
    name: str
    slug: str
    description: str | None
    created_at: datetime
    can_manage: bool = False
    model_config = ConfigDict(from_attributes=True)


class DeviceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    client_id: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._:-]+$")


class DeviceUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=160)


class DeviceTopicCreate(BaseModel):
    topic: str = Field(min_length=1, max_length=512)
    action: Literal["publish", "subscribe", "all"]
    qos: list[int] = Field(default_factory=lambda: [0, 1, 2], min_length=1, max_length=3)
    retain: Literal["all", "true", "false"] = "all"

    @field_validator("qos")
    @classmethod
    def validate_qos(cls, values: list[int]) -> list[int]:
        if any(value not in (0, 1, 2) for value in values):
            raise ValueError("QoS values must be 0, 1, or 2")
        if len(set(values)) != len(values):
            raise ValueError("QoS values must be unique")
        return values


class DeviceTopicView(BaseModel):
    id: int
    topic: str
    action: str
    qos: list[int]
    retain: str
    model_config = ConfigDict(from_attributes=True)


class DeviceView(BaseModel):
    id: int
    project_id: int
    name: str
    topic_name: str
    client_id: str
    is_active: bool
    status: Literal["online", "offline", "unknown"] = "unknown"
    heartbeat_status: Literal["waiting", "active", "stale"] = "waiting"
    heartbeat_timeout_seconds: int = 90
    last_connection_port: int | None = None
    last_connection_tls: bool | None = None
    last_seen_at: datetime | None
    last_heartbeat_at: datetime | None
    created_at: datetime
    topics: list[DeviceTopicView]
    model_config = ConfigDict(from_attributes=True)


class DeviceCredentialView(BaseModel):
    device: DeviceView
    username: str
    password: str
    active_session_disconnected: bool = True


class MemberView(BaseModel):
    user_id: int
    email: EmailStr
    full_name: str
    role: str


class AddMember(BaseModel):
    email: EmailStr
    role: str = Field(pattern=r"^(organization_admin|member|viewer)$")


class _MemberUpdateFields(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=160)

    @field_validator("full_name")
    @classmethod
    def trim_member_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Member name must contain at least 2 characters")
        return value


class UpdateMemberRole(_MemberUpdateFields):
    role: str | None = Field(default=None, pattern=r"^(organization_admin|member|viewer)$")


class ProjectMemberView(BaseModel):
    user_id: int
    email: EmailStr
    full_name: str
    role: str


class ProjectMembersView(BaseModel):
    project_id: int
    can_manage: bool
    members: list[ProjectMemberView]


class AddProjectMember(BaseModel):
    email: EmailStr
    role: str = Field(pattern=r"^(project_admin|project_member|project_viewer)$")


class UpdateProjectMemberRole(_MemberUpdateFields):
    role: str | None = Field(default=None, pattern=r"^(project_admin|project_member|project_viewer)$")
