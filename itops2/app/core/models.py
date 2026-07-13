"""Phase 1/2 core models.

Fixed roles (Admin, Manager, Technician, Viewer) — seeded, not user-creatable.
Permission matrix: core_role_permissions rows toggled in Settings UI.
Audit log is infrastructure from day one: every mutation writes a row.
company_id columns appear from the start so multi-company can be toggled
later without schema surgery (off = organisational label only).
"""

import enum
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
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


class StatusType(str, enum.Enum):
    """Workflow bucket a status label belongs to. Asset workflow rules
    (Phase 5) hang off this, not the free-text label name."""

    deployable = "deployable"
    deployed = "deployed"
    pending = "pending"
    archived = "archived"


class Company(Base):
    __tablename__ = "core_companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Location(Base):
    __tablename__ = "core_locations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Manufacturer(Base):
    __tablename__ = "core_manufacturers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    models: Mapped[list["AssetModel"]] = relationship(back_populates="manufacturer")


class Category(Base):
    __tablename__ = "core_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    models: Mapped[list["AssetModel"]] = relationship(back_populates="category")


class StatusLabel(Base):
    __tablename__ = "core_status_labels"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    status_type: Mapped[StatusType] = mapped_column(Enum(StatusType, name="core_status_type"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AssetModel(Base):
    """A hardware/software model (Snipe-IT-style): Manufacturer + Category,
    with optional per-model overrides of the global policy defaults
    (depreciation.default_months / warranty.alert_days settings).
    Name is unique per manufacturer, not globally (different makers can
    both ship a model called e.g. "Pro").
    """

    __tablename__ = "core_models"
    __table_args__ = (UniqueConstraint("name", "manufacturer_id", name="uq_model_name_manufacturer"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    manufacturer_id: Mapped[int] = mapped_column(ForeignKey("core_manufacturers.id"), index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("core_categories.id"), index=True)
    depreciation_months: Mapped[int | None] = mapped_column(Integer)
    eol_months: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    manufacturer: Mapped[Manufacturer] = relationship(back_populates="models")
    category: Mapped[Category] = relationship(back_populates="models")


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


class Currency(Base):
    """ISO 4217 code as primary key — money fields (Phase 5+) store this
    code directly rather than an FK id, matching general.default_currency."""

    __tablename__ = "core_currencies"

    code: Mapped[str] = mapped_column(String(3), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(10))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExchangeRate(Base):
    """Manual DATED rate: 1 from_currency = rate * to_currency, effective
    from effective_date. No API — admin-entered, historical value at
    purchase date is looked up by nearest effective_date <= the date needed.
    """

    __tablename__ = "core_exchange_rates"
    __table_args__ = (
        UniqueConstraint("from_currency", "to_currency", "effective_date", name="uq_exchange_rate_from_to_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    from_currency: Mapped[str] = mapped_column(ForeignKey("core_currencies.code"), index=True)
    to_currency: Mapped[str] = mapped_column(ForeignKey("core_currencies.code"), index=True)
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    effective_date: Mapped[date] = mapped_column(Date, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Asset(Base):
    """A tracked hardware/software unit. `checked_out_to_*` is a denormalized
    "current state" pointer (fast "who has this?" lookups without a join);
    `core_checkouts` is the full history ledger. Invariant enforced at the
    DB level for the target columns, and at the app level (routers) for the
    cross-table piece — `checked_out_at IS NOT NULL` iff
    `status_label.status_type == deployed` — since a CHECK constraint can't
    reach across tables.

    No hard delete unless zero checkout history AND zero attachments exist
    (enforced by plain FK RESTRICT from core_checkouts/core_attachments,
    same friendly-toast-on-IntegrityError pattern as Catalog). Otherwise
    "delete" = move status to an archived-type label.
    """

    __tablename__ = "core_assets"
    __table_args__ = (
        UniqueConstraint("asset_tag", name="uq_asset_tag"),
        CheckConstraint(
            "num_nonnulls(checked_out_to_user_id, checked_out_to_location_id, checked_out_to_asset_id) <= 1",
            name="ck_asset_checkout_target_singular",
        ),
        CheckConstraint(
            "checked_out_to_asset_id IS NULL OR checked_out_to_asset_id <> id",
            name="ck_asset_no_self_checkout",
        ),
        CheckConstraint(
            "(checked_out_at IS NULL) = "
            "(num_nonnulls(checked_out_to_user_id, checked_out_to_location_id, checked_out_to_asset_id) = 0)",
            name="ck_asset_checkout_at_matches_target",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_tag: Mapped[str] = mapped_column(String(50), index=True)
    serial: Mapped[str | None] = mapped_column(String(200), index=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("core_models.id"), index=True)
    status_label_id: Mapped[int] = mapped_column(ForeignKey("core_status_labels.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("core_companies.id"), index=True)
    location_id: Mapped[int | None] = mapped_column(ForeignKey("core_locations.id"), index=True)
    purchase_date: Mapped[date | None] = mapped_column(Date, index=True)
    purchase_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    purchase_currency: Mapped[str | None] = mapped_column(ForeignKey("core_currencies.code"))
    warranty_months: Mapped[int | None] = mapped_column(Integer)
    depreciation_months_override: Mapped[int | None] = mapped_column(Integer)
    eol_months_override: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)
    checked_out_to_user_id: Mapped[int | None] = mapped_column(ForeignKey("core_users.id"), index=True)
    checked_out_to_location_id: Mapped[int | None] = mapped_column(ForeignKey("core_locations.id"), index=True)
    checked_out_to_asset_id: Mapped[int | None] = mapped_column(ForeignKey("core_assets.id"), index=True)
    checked_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    model: Mapped[AssetModel] = relationship(foreign_keys=[model_id])
    status_label: Mapped[StatusLabel] = relationship(foreign_keys=[status_label_id])
    company: Mapped[Company | None] = relationship(foreign_keys=[company_id])
    location: Mapped[Location | None] = relationship(foreign_keys=[location_id])
    checked_out_to_user: Mapped[User | None] = relationship(foreign_keys=[checked_out_to_user_id])
    checked_out_to_location: Mapped[Location | None] = relationship(foreign_keys=[checked_out_to_location_id])
    checked_out_to_asset: Mapped["Asset | None"] = relationship(
        foreign_keys=[checked_out_to_asset_id], remote_side=[id]
    )


class Checkout(Base):
    """Append-only history ledger — one row per checkout, closed on checkin.
    `status_label_id_at_checkout` / `checkin_status_label_id` snapshot the
    status assigned at each event, since `core_assets.status_label_id`
    itself keeps changing. The partial unique index is the DB-level
    guarantee that an asset can only have one *open* checkout at a time —
    stronger than an app-level check alone.
    """

    __tablename__ = "core_checkouts"
    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(target_user_id, target_location_id, target_asset_id) <= 1",
            name="ck_checkout_target_singular",
        ),
        Index(
            "uq_checkout_one_open_per_asset",
            "asset_id",
            unique=True,
            postgresql_where=text("checked_in_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("core_assets.id"), index=True)
    target_user_id: Mapped[int | None] = mapped_column(ForeignKey("core_users.id"), index=True)
    target_location_id: Mapped[int | None] = mapped_column(ForeignKey("core_locations.id"), index=True)
    target_asset_id: Mapped[int | None] = mapped_column(ForeignKey("core_assets.id"), index=True)
    status_label_id_at_checkout: Mapped[int] = mapped_column(ForeignKey("core_status_labels.id"))
    checked_out_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    checked_out_by: Mapped[int] = mapped_column(ForeignKey("core_users.id"))
    expected_checkin_at: Mapped[date | None] = mapped_column(Date)
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checked_in_by: Mapped[int | None] = mapped_column(ForeignKey("core_users.id"))
    checkin_status_label_id: Mapped[int | None] = mapped_column(ForeignKey("core_status_labels.id"))
    notes: Mapped[str | None] = mapped_column(Text)

    asset: Mapped[Asset] = relationship(foreign_keys=[asset_id])
    target_user: Mapped[User | None] = relationship(foreign_keys=[target_user_id])
    target_location: Mapped[Location | None] = relationship(foreign_keys=[target_location_id])
    target_asset: Mapped[Asset | None] = relationship(foreign_keys=[target_asset_id])


class Attachment(Base):
    """Generic/polymorphic like core_audit_log (entity_type + entity_id as
    text, not a real FK) rather than the 3-FK style used for checkout
    targets — future entities (Contracts, Maintenance) will want
    attachments too, so this shouldn't need a schema change later. See
    CLAUDE.md for the rationale on using both polymorphism styles.
    Disk layout: {settings.attachments_dir}/{entity_type}/{entity_id}/{stored_filename}
    — entity_type used raw, no pluralization.
    """

    __tablename__ = "core_attachments"
    __table_args__ = (Index("ix_core_attachments_entity", "entity_type", "entity_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[str] = mapped_column(String(50))
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_filename: Mapped[str] = mapped_column(String(255), unique=True)
    content_type: Mapped[str | None] = mapped_column(String(150))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    description: Mapped[str | None] = mapped_column(String(255))
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("core_users.id"), index=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    uploader: Mapped[User] = relationship(foreign_keys=[uploaded_by])


class MaintenanceType(str, enum.Enum):
    repair = "repair"
    maintenance = "maintenance"
    upgrade = "upgrade"


class Maintenance(Base):
    """Generic maintenance/repair/upgrade record against any asset (not
    printer-specific). Attachments (receipts, photos) reuse
    core_attachments with entity_type='maintenance', entity_id=str(id) —
    the same polymorphic table assets use, no new attachment machinery.
    performed_by is free text, not a User FK: external vendors do this
    work too, and they're not accounts in this system.
    """

    __tablename__ = "core_maintenance"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("core_assets.id"), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    maintenance_type: Mapped[MaintenanceType] = mapped_column(Enum(MaintenanceType, name="core_maintenance_type"))
    description: Mapped[str] = mapped_column(Text)
    cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str | None] = mapped_column(ForeignKey("core_currencies.code"))
    performed_by: Mapped[str | None] = mapped_column(String(200))
    created_by: Mapped[int] = mapped_column(ForeignKey("core_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    asset: Mapped[Asset] = relationship(foreign_keys=[asset_id])
    creator: Mapped[User] = relationship(foreign_keys=[created_by])


class PrinterDetails(Base):
    """1:1 extension of core_assets for assets in the Printer category.
    asset_id is both PK and FK, enforcing 1:1 at the schema level.
    Created lazily on first save from the asset detail page's Printer
    Details section. Chosen over nullable columns on core_assets (would
    make the central table wider with every future asset-type field) or
    a generic key-value asset-extras table (loses typing/indexing for a
    flexibility need that doesn't exist — asset types needing extra
    fields are a small, dev-curated set, not runtime-configurable) — see
    CLAUDE.md for the full rationale, decided 2026-07 with Alex.
    """

    __tablename__ = "core_printer_details"

    asset_id: Mapped[int] = mapped_column(ForeignKey("core_assets.id"), primary_key=True)
    ip_address: Mapped[str | None] = mapped_column(String(45))  # fits IPv6
    hostname: Mapped[str | None] = mapped_column(String(255))
    consumable_notes: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    asset: Mapped[Asset] = relationship(foreign_keys=[asset_id])
