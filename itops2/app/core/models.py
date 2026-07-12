"""Phase 1/2 core models.

Fixed roles (Admin, Manager, Technician, Viewer) — seeded, not user-creatable.
Permission matrix: core_role_permissions rows toggled in Settings UI.
Audit log is infrastructure from day one: every mutation writes a row.
company_id columns appear from the start so multi-company can be toggled
later without schema surgery (off = organisational label only).
"""

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RoleName(str, enum.Enum):
    admin = "admin"
    manager = "manager"
    technician = "technician"
    viewer = "viewer"


class AuthSource(str, enum.Enum):
    local = "local"
    oidc = "oidc"
    ldap = "ldap"


class Company(Base):
    __tablename__ = "core_companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Role(Base):
    __tablename__ = "core_roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[RoleName] = mapped_column(Enum(RoleName, name="core_role_name"), unique=True)
    description: Mapped[str | None] = mapped_column(String(255))

    permissions: Mapped[list["RolePermission"]] = relationship(back_populates="role")


class RolePermission(Base):
    """One row per (role, permission-key) grant. The Settings grid toggles these.

    Permission keys are dotted strings, e.g. 'assets.create', 'assets.delete',
    'checkout.perform', 'settings.manage', 'import.run'. The full registry
    lives in app/core/permissions.py.
    """

    __tablename__ = "core_role_permissions"
    __table_args__ = (UniqueConstraint("role_id", "permission", name="uq_role_permission"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("core_roles.id"), index=True)
    permission: Mapped[str] = mapped_column(String(100), index=True)

    role: Mapped[Role] = relationship(back_populates="permissions")


class User(Base):
    __tablename__ = "core_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(150), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), index=True)
    display_name: Mapped[str | None] = mapped_column(String(255))
    auth_source: Mapped[AuthSource] = mapped_column(Enum(AuthSource, name="core_auth_source"))
    # Only for auth_source == local; OIDC/LDAP users have no local hash.
    password_hash: Mapped[str | None] = mapped_column(String(255))
    role_id: Mapped[int] = mapped_column(ForeignKey("core_roles.id"))
    company_id: Mapped[int | None] = mapped_column(ForeignKey("core_companies.id"), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_breakglass: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    role: Mapped[Role] = relationship()
    company: Mapped[Company | None] = relationship()


class AppSetting(Base):
    """Key/value runtime settings edited in the Settings UI.

    Namespaced keys: 'smtp.host', 'auth.oidc.enabled', 'currency.default',
    'company.multi_enabled', 'company.scoped_users', 'asset_tag.format', ...
    Values stored as text; typed accessors in app/core/settings_store.py.
    """

    __tablename__ = "core_settings"

    key: Mapped[str] = mapped_column(String(150), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AuditLog(Base):
    __tablename__ = "core_audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("core_users.id"), index=True)
    action: Mapped[str] = mapped_column(String(50), index=True)  # create/update/delete/checkout/...
    entity_type: Mapped[str] = mapped_column(String(50), index=True)  # asset/user/setting/...
    entity_id: Mapped[str | None] = mapped_column(String(50), index=True)
    detail: Mapped[str | None] = mapped_column(Text)  # JSON diff / free text
