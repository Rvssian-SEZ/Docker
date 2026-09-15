"""App-state models. See app/core/audit.py for the (physically separate)
audit trail database — nothing in there is an FK target from here.

Fixed roles per the spec's suggested tiers (Helpdesk L1/L2, Admin) — seeded,
not user-creatable, same "fixed roles + editable permission matrix" pattern
as every other app in this repo. Break-glass is deliberately NOT a Role row
here ("Break-glass is separate, not a role" — spec) — see
app/core/breakglass.py for its own standalone credential store.
"""

import calendar
import enum
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware_utc(dt: datetime) -> datetime:
    """SQLite doesn't actually persist tzinfo despite DateTime(timezone=True)
    — a row written with an aware datetime.now(timezone.utc) comes back
    naive after a fresh SELECT (confirmed live 2026-09-15, see
    OffboardingRecord.is_overdue), which raised "can't compare offset-naive
    and offset-aware datetimes" the moment a reloaded record's
    delete_eligible_at was compared against utcnow(). Every datetime this
    app writes to this column is already UTC (utcnow()), so a naive value
    read back is safely assumed to already be UTC, not local time."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def add_months(dt: datetime, months: int) -> datetime:
    """Calendar-accurate month addition (not a fixed 30/31-day span) — used
    for the offboarding 6-month deletion-eligible date. Clamps the day if
    the target month is shorter (e.g. Aug 31 + 6mo -> Feb 28/29, not an
    OverflowError)."""
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


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


class OffboardingRecord(Base):
    """Tracks an in-progress (or completed) user offboarding — see
    app/routers/offboarding.py. One row per "Start Offboarding" run.

    Steps 1/2/4 (disable, reset password, remove all group memberships)
    are performed automatically when the record is created — disable_ok/
    reset_password_ok capture whether each sub-step actually succeeded
    (a partial failure doesn't abort the whole bundle, same tolerant
    pattern as Create User's own multi-step LDAP sequence), and
    removed_groups_json is a permanent snapshot of exactly which groups
    the account was in at that moment and whether each removal succeeded
    — the account's live AD group membership can't answer that later once
    it's been reset for a different purpose or the account is deleted.

    Steps 5/8 (mailbox -> shared, license removal) are Exchange Online/
    Entra actions this app has no automation for yet (see
    CLAUDE_CONTEXT.md "Offboarding") — mailbox_converted/licenses_removed
    are admin-ticked checkboxes recording that those were done manually
    elsewhere, not something this app verifies.

    completed_at being set is what moves a record out of the active list
    into history — set only when an admin clicks "Mark Deleted /
    Complete" after actually deleting the AD account by hand (step 12,
    also manual, also not something this app automates)."""

    __tablename__ = "offboarding_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    sam: Mapped[str] = mapped_column(String(150), index=True)
    display_name: Mapped[str | None] = mapped_column(String(255))
    dn: Mapped[str] = mapped_column(String(500))
    initiated_by: Mapped[str] = mapped_column(String(150))
    initiated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    reason: Mapped[str] = mapped_column(Text)

    disable_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    reset_password_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    # JSON list of {"sam", "name", "dn", "removed": bool, "error": str|None} —
    # see resolve_groups_by_dn()'s shape in ldap_client.py, extended with
    # the per-group removal outcome.
    removed_groups_json: Mapped[str] = mapped_column(Text, default="[]")

    mailbox_converted: Mapped[bool] = mapped_column(Boolean, default=False)
    mailbox_converted_by: Mapped[str | None] = mapped_column(String(150))
    mailbox_converted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    licenses_removed: Mapped[bool] = mapped_column(Boolean, default=False)
    licenses_removed_by: Mapped[str | None] = mapped_column(String(150))
    licenses_removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    completed_by: Mapped[str | None] = mapped_column(String(150))
    completed_reason: Mapped[str | None] = mapped_column(Text)

    @property
    def delete_eligible_at(self) -> datetime:
        return add_months(_as_aware_utc(self.initiated_at), 6)

    @property
    def is_overdue(self) -> bool:
        return self.completed_at is None and utcnow() >= self.delete_eligible_at


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
