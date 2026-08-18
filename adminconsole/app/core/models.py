"""App-state models. See app/core/audit.py for the (physically separate)
audit trail database — nothing in there is an FK target from here.

Fixed roles per the spec's suggested tiers (Helpdesk L1/L2, Admin) — seeded,
not user-creatable, same "fixed roles + editable permission matrix" pattern
as every other app in this repo. Break-glass is deliberately NOT a Role row
here ("Break-glass is separate, not a role" — spec) — see
app/core/breakglass.py for its own standalone credential store.
"""

import enum
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RoleName(str, enum.Enum):
    helpdesk_l1 = "helpdesk_l1"
    helpdesk_l2 = "helpdesk_l2"
    admin = "admin"


class AuthSource(str, enum.Enum):
    local = "local"
    oidc = "oidc"


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[RoleName] = mapped_column(Enum(RoleName, name="role_name"), unique=True)
    description: Mapped[str | None] = mapped_column(String(255))

    permissions: Mapped[list["RolePermission"]] = relationship(back_populates="role")


class RolePermission(Base):
    """One row per (role, permission-key) grant, toggled in the Settings
    permissions grid. Registry lives in app/core/permissions.py."""

    __tablename__ = "role_permissions"
    __table_args__ = (UniqueConstraint("role_id", "permission", name="uq_role_permission"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), index=True)
    permission: Mapped[str] = mapped_column(String(100), index=True)

    role: Mapped[Role] = relationship(back_populates="permissions")


class User(Base):
    """Normal users only — local helpdesk accounts or OIDC (Authentik) sign-
    ins. The break-glass admin is never a row in this table (see
    app/core/breakglass.py), so a bug that lists/edits Users can never touch
    it, and the OU-scoping story (per-role, per-OU) below only needs to
    reason about real roles.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(150), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), index=True)
    display_name: Mapped[str | None] = mapped_column(String(255))
    auth_source: Mapped[AuthSource] = mapped_column(Enum(AuthSource, name="auth_source"))
    # Only for auth_source == local; OIDC users have no local hash.
    password_hash: Mapped[str | None] = mapped_column(String(255))
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    role: Mapped[Role] = relationship()


class BreakGlassCredential(Base):
    """The break-glass admin's own local credential store — deliberately
    NOT a row in `users` and NOT tied to any AD account (spec: "not tied to
    any AD account... lives only in the app's local auth store"). A single
    row is expected (id=1, enforced by bootstrap always upserting id=1
    rather than inserting new rows); TOTP is mandatory, not optional, per
    the spec's break-glass requirements.
    """

    __tablename__ = "breakglass_credential"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(150), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    # Encrypted at rest with the same FERNET_KEY as Settings secrets — a
    # TOTP seed is exactly as sensitive as a client secret.
    totp_secret_encrypted: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AppSetting(Base):
    """Key/value runtime settings edited in the Settings UI. Namespaced
    keys: 'graph.tenant_id', 'auth.oidc.client_secret', 'ad.bind_password', ...

    Values that are secrets (see settings_store.ENCRYPTED_KEYS) are stored
    Fernet-encrypted in `value` and are write-only in the UI — the getter
    used to render a form never returns the decrypted value, only whether
    one is currently set (see settings_store.SettingsStore.is_set).
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(150), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(150))
