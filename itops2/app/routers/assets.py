"""Assets: the core inventory record. List + detail/edit page (too many
fields for Catalog's inline-row pattern) — checkout/checkin and
attachments (Phase 5 chunk 5) both live on the detail page.

Status lifecycle rules:
- status_type == deployed is reachable ONLY via checkout — never through
  the general create/edit form (its dropdown excludes it), and never
  through checkin (its dropdown also excludes it, so a checkin can't
  silently re-enter "deployed" without a real matching checkout).
- Editing status via the general edit form while checked_out_at IS NOT
  NULL is rejected: must checkin first (keeps the checked_out_at <->
  deployed invariant intact; the DB can't enforce this cross-table
  itself).
- Checkout: allowed only when status_type == deployable and not already
  checked out. Exactly one of target_user_id/target_location_id/
  target_asset_id must be given, plus a destination status restricted
  to status_type == deployed (if only one such label exists, it's the
  only <option> and thus pre-selected for free — no extra code needed).
  Opens a core_checkouts row.
- Checkin: allowed only when currently checked out. Destination status
  is any non-deployed label (same pool as the general edit form).
  Closes the open core_checkouts row and clears the denormalized
  checked_out_to_* pointer on the asset.
- status_type == archived assets are read-only except for a restore
  action (submit a non-archived status_label_id and nothing else).
  Audit action is "archive"/"restore" when a transition crosses that
  boundary, "update" otherwise.

Hard delete requires zero checkout history, zero attachments, AND zero
maintenance records (Phase 6): checkout history and maintenance records
are both real FKs (core_checkouts.asset_id, core_maintenance.asset_id),
but maintenance gets its own explicit pre-check (like attachments)
rather than relying on the generic IntegrityError catch — otherwise an
asset blocked only by maintenance records would incorrectly be told it
has "checkout history" (a real bug caught during Phase 6 testing: the
catch-all message assumed checkout history was the only remaining FK).
Attachments are the entity_type/entity_id polymorphism style (like
core_audit_log), which has no enforced FK, so that one was always an
explicit COUNT check. See CLAUDE.md for why attachments and checkout
targets use two different polymorphism styles.

Attachments: disk layout is {attachments_dir}/{entity_type}/{entity_id}/
{stored_filename} — entity_type used raw ("asset"), no pluralization.
No dedicated attachments.* permission exists (not in the registry);
upload/delete reuse assets.edit, download reuses assets.view, same as
any other asset mutation/view. Uploads are capped at MAX_ATTACHMENT_SIZE
as a basic disk-fill guard — there's no size limit in the approved
design, but shipping an ITAM tool with a genuinely unbounded upload
endpoint is asking for an accidental full disk.
"""

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.attachments import MAX_ATTACHMENT_SIZE, attachment_dir, save_upload
from app.core.auth import CurrentUser, require
from app.core.db import get_db
from app.core.models import (
    Asset,
    AssetModel,
    Attachment,
    AuditLog,
    Checkout,
    Company,
    Currency,
    Location,
    Maintenance,
    MaintenanceType,
    PrinterDetails,
    StatusLabel,
    StatusType,
    User,
)
from app.core.notifications import notify_checkin, notify_checkout
from app.core.settings_store import load_settings
from app.templating import templates

router = APIRouter(prefix="/assets")


# ---- helpers ----

def _toast(request: Request, ok: bool, message: str):
    return templates.TemplateResponse(request, "partials/toast.html", {"ok": ok, "message": message})


def _refresh():
    return Response(status_code=204, headers={"HX-Refresh": "true"})


def _redirect(path: str):
    return Response(status_code=204, headers={"HX-Redirect": path})


def _parse_optional_int(value: str, field: str):
    value = (value or "").strip()
    if not value:
        return None, None
    if not value.lstrip("-").isdigit() or int(value) < 0:
        return None, f"{field} must be a whole number."
    return int(value), None


def _parse_optional_decimal(value: str, field: str):
    value = (value or "").strip()
    if not value:
        return None, None
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        return None, f"{field} must be a number."
    if parsed < 0:
        return None, f"{field} must not be negative."
    return parsed, None


def _parse_optional_date(value: str, field: str):
    value = (value or "").strip()
    if not value:
        return None, None
    try:
        return date.fromisoformat(value), None
    except ValueError:
        return None, f"{field} must be a valid date."


async def _next_asset_tag(db: AsyncSession, prefix: str, pad: int) -> str:
    tags = (
        await db.execute(select(Asset.asset_tag).where(Asset.asset_tag.like(f"{prefix}%")))
    ).scalars().all()
    max_n = 0
    for tag in tags:
        suffix = tag[len(prefix):]
        if suffix.isdigit():
            max_n = max(max_n, int(suffix))
    return f"{prefix}{max_n + 1:0{pad}d}"


async def _form_context(db: AsyncSession) -> dict:
    store = await load_settings(db)
    models = (
        (
            await db.execute(
                select(AssetModel)
                .options(selectinload(AssetModel.manufacturer), selectinload(AssetModel.category))
                .order_by(AssetModel.name)
            )
        )
        .scalars()
        .all()
    )
    # Deployed is only ever set via checkout — never offered on the general form.
    editable_status_labels = (
        (
            await db.execute(
                select(StatusLabel).where(StatusLabel.status_type != StatusType.deployed).order_by(StatusLabel.name)
            )
        )
        .scalars()
        .all()
    )
    companies = (await db.execute(select(Company).order_by(Company.name))).scalars().all()
    locations = (await db.execute(select(Location).order_by(Location.name))).scalars().all()
    currencies = (await db.execute(select(Currency).where(Currency.active.is_(True)).order_by(Currency.code))).scalars().all()
    return {
        "models": models,
        "status_labels": editable_status_labels,
        "companies": companies,
        "locations": locations,
        "currencies": currencies,
        "default_currency": store.get("general.default_currency"),
        "multi_company": store.get_bool("company.multi_enabled"),
    }


async def _get_asset_or_none(db: AsyncSession, asset_id: int) -> Asset | None:
    return (
        await db.execute(
            select(Asset)
            .options(
                selectinload(Asset.model).selectinload(AssetModel.manufacturer),
                selectinload(Asset.model).selectinload(AssetModel.category),
                selectinload(Asset.status_label),
                selectinload(Asset.company),
                selectinload(Asset.location),
                selectinload(Asset.checked_out_to_user),
                selectinload(Asset.checked_out_to_location),
                selectinload(Asset.checked_out_to_asset),
            )
            .where(Asset.id == asset_id)
        )
    ).scalar_one_or_none()


def _effective_months(override: int | None, model_value: int | None, global_default: int | None = None) -> int | None:
    """Cascade: asset override -> model override -> global default (depreciation
    only has one; EOL has no global fallback). Not stored — computed at render
    time so editing the cascade never leaves stale values on old assets."""
    for value in (override, model_value, global_default):
        if value is not None:
            return value
    return None


# ---- list ----

@router.get("", response_class=HTMLResponse)
async def assets_list(
    request: Request,
    user: CurrentUser = Depends(require("assets.view")),
    db: AsyncSession = Depends(get_db),
):
    assets = (
        (
            await db.execute(
                select(Asset)
                .options(
                    selectinload(Asset.model),
                    selectinload(Asset.status_label),
                    selectinload(Asset.location),
                    selectinload(Asset.checked_out_to_user),
                    selectinload(Asset.checked_out_to_location),
                    selectinload(Asset.checked_out_to_asset),
                )
                .order_by(Asset.asset_tag)
            )
        )
        .scalars()
        .all()
    )
    return templates.TemplateResponse(
        request, "assets/list.html", {"user": user, "assets": assets},
    )


# ---- create ----

@router.get("/new", response_class=HTMLResponse)
async def assets_new(
    request: Request,
    user: CurrentUser = Depends(require("assets.create")),
    db: AsyncSession = Depends(get_db),
):
    ctx = await _form_context(db)
    ctx.update({"user": user})
    return templates.TemplateResponse(request, "assets/new.html", ctx)


@router.post("/create", response_class=HTMLResponse)
async def assets_create(
    request: Request,
    asset_tag: str = Form(""),
    serial: str = Form(""),
    model_id: int | None = Form(None),
    status_label_id: int | None = Form(None),
    company_id: str = Form(""),
    location_id: str = Form(""),
    purchase_date: str = Form(""),
    purchase_cost: str = Form(""),
    purchase_currency: str = Form(""),
    warranty_months: str = Form(""),
    depreciation_months_override: str = Form(""),
    eol_months_override: str = Form(""),
    notes: str = Form(""),
    user: CurrentUser = Depends(require("assets.create")),
    db: AsyncSession = Depends(get_db),
):
    if model_id is None:
        return _toast(request, False, "Model is required.")
    if status_label_id is None:
        return _toast(request, False, "Status is required.")
    if await db.get(AssetModel, model_id) is None:
        return _toast(request, False, "Unknown model.")
    status_label = await db.get(StatusLabel, status_label_id)
    if status_label is None:
        return _toast(request, False, "Unknown status label.")
    if status_label.status_type == StatusType.deployed:
        return _toast(request, False, "Deployed status is only set via checkout.")
    company_id_val = int(company_id) if company_id.isdigit() else None
    if company_id_val is not None and await db.get(Company, company_id_val) is None:
        return _toast(request, False, "Unknown company.")
    location_id_val = int(location_id) if location_id.isdigit() else None
    if location_id_val is not None and await db.get(Location, location_id_val) is None:
        return _toast(request, False, "Unknown location.")
    purchase_currency_val = purchase_currency.strip().upper() or None
    if purchase_currency_val is not None and await db.get(Currency, purchase_currency_val) is None:
        return _toast(request, False, "Unknown currency.")

    p_date, err = _parse_optional_date(purchase_date, "Purchase date")
    if err:
        return _toast(request, False, err)
    p_cost, err = _parse_optional_decimal(purchase_cost, "Purchase cost")
    if err:
        return _toast(request, False, err)
    warranty, err = _parse_optional_int(warranty_months, "Warranty months")
    if err:
        return _toast(request, False, err)
    dep_override, err = _parse_optional_int(depreciation_months_override, "Depreciation months")
    if err:
        return _toast(request, False, err)
    eol_override, err = _parse_optional_int(eol_months_override, "EOL months")
    if err:
        return _toast(request, False, err)

    tag = asset_tag.strip()
    if not tag:
        store = await load_settings(db)
        tag = await _next_asset_tag(db, store.get("asset_tag.prefix"), store.get_int("asset_tag.pad"))

    row = Asset(
        asset_tag=tag,
        serial=serial.strip() or None,
        model_id=model_id,
        status_label_id=status_label_id,
        company_id=company_id_val,
        location_id=location_id_val,
        purchase_date=p_date,
        purchase_cost=p_cost,
        purchase_currency=purchase_currency_val,
        warranty_months=warranty,
        depreciation_months_override=dep_override,
        eol_months_override=eol_override,
        notes=notes.strip() or None,
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        return _toast(request, False, f"Asset tag '{tag}' already exists.")
    db.add(AuditLog(user_id=user.id, action="create", entity_type="asset", entity_id=str(row.id), detail=tag))
    await db.commit()
    return _redirect(f"/assets/{row.id}")


# ---- detail / edit ----

@router.get("/{asset_id}", response_class=HTMLResponse)
async def asset_detail(
    request: Request,
    asset_id: int,
    user: CurrentUser = Depends(require("assets.view")),
    db: AsyncSession = Depends(get_db),
):
    asset = await _get_asset_or_none(db, asset_id)
    if asset is None:
        return templates.TemplateResponse(
            request, "partials/toast.html", {"ok": False, "message": "Asset not found."}, status_code=404,
        )
    ctx = await _form_context(db)
    store = await load_settings(db)
    is_checked_out = asset.checked_out_at is not None
    deployed_labels = (
        (
            await db.execute(
                select(StatusLabel).where(StatusLabel.status_type == StatusType.deployed).order_by(StatusLabel.name)
            )
        )
        .scalars()
        .all()
    )
    other_users = (await db.execute(select(User).where(User.is_active.is_(True)).order_by(User.username))).scalars().all()
    other_assets = (
        (await db.execute(select(Asset).where(Asset.id != asset_id).order_by(Asset.asset_tag))).scalars().all()
    )
    history = (
        (
            await db.execute(
                select(Checkout)
                .options(
                    selectinload(Checkout.target_user),
                    selectinload(Checkout.target_location),
                    selectinload(Checkout.target_asset),
                )
                .where(Checkout.asset_id == asset_id)
                .order_by(Checkout.checked_out_at.desc())
            )
        )
        .scalars()
        .all()
    )
    attachments = (
        (
            await db.execute(
                select(Attachment)
                .where(Attachment.entity_type == "asset", Attachment.entity_id == str(asset_id))
                .order_by(Attachment.uploaded_at.desc())
                .options(selectinload(Attachment.uploader))
            )
        )
        .scalars()
        .all()
    )
    maintenance_records = (
        (
            await db.execute(
                select(Maintenance)
                .where(Maintenance.asset_id == asset_id)
                .order_by(Maintenance.date.desc(), Maintenance.id.desc())
            )
        )
        .scalars()
        .all()
    )
    is_printer = asset.model.category.name.strip().lower() == "printer"
    printer_details = await db.get(PrinterDetails, asset_id) if is_printer else None

    maintenance_ids = [str(m.id) for m in maintenance_records]
    maintenance_attachments = {}
    if maintenance_ids:
        rows = (
            (
                await db.execute(
                    select(Attachment)
                    .where(Attachment.entity_type == "maintenance", Attachment.entity_id.in_(maintenance_ids))
                    .order_by(Attachment.uploaded_at)
                )
            )
            .scalars()
            .all()
        )
        for a in rows:
            maintenance_attachments.setdefault(int(a.entity_id), []).append(a)
    ctx.update(
        {
            "user": user,
            "asset": asset,
            "is_archived": asset.status_label.status_type == StatusType.archived,
            "is_checked_out": is_checked_out,
            "attachments": attachments,
            "max_attachment_mb": MAX_ATTACHMENT_SIZE // (1024 * 1024),
            "can_checkout": (
                not is_checked_out
                and asset.status_label.status_type == StatusType.deployable
                and bool(deployed_labels)
            ),
            "deployed_labels": deployed_labels,
            "checkout_users": other_users,
            "checkout_assets": other_assets,
            "checkout_locations": ctx["locations"],
            "checkout_history": history,
            "effective_depreciation_months": _effective_months(
                asset.depreciation_months_override,
                asset.model.depreciation_months,
                store.get_int("depreciation.default_months"),
            ),
            "effective_eol_months": _effective_months(asset.eol_months_override, asset.model.eol_months),
            "maintenance_records": maintenance_records,
            "maintenance_types": list(MaintenanceType),
            "maintenance_attachments": maintenance_attachments,
            "maintenance_currencies": ctx["currencies"],
            "is_printer": is_printer,
            "printer_details": printer_details,
        }
    )
    return templates.TemplateResponse(request, "assets/detail.html", ctx)


@router.post("/{asset_id}/update", response_class=HTMLResponse)
async def asset_update(
    request: Request,
    asset_id: int,
    # Optional at the FastAPI layer only so the minimal restore-only form
    # (status_label_id alone) can post without the rest; each is required
    # below for whichever path actually needs it.
    status_label_id: int | None = Form(None),
    serial: str = Form(""),
    asset_tag: str | None = Form(None),
    model_id: int | None = Form(None),
    company_id: str = Form(""),
    location_id: str = Form(""),
    purchase_date: str = Form(""),
    purchase_cost: str = Form(""),
    purchase_currency: str = Form(""),
    warranty_months: str = Form(""),
    depreciation_months_override: str = Form(""),
    eol_months_override: str = Form(""),
    notes: str = Form(""),
    user: CurrentUser = Depends(require("assets.edit")),
    db: AsyncSession = Depends(get_db),
):
    asset = await db.get(Asset, asset_id, options=[selectinload(Asset.status_label)])
    if asset is None:
        return _toast(request, False, "Asset not found.")
    if status_label_id is None:
        return _toast(request, False, "Status is required.")

    new_status = await db.get(StatusLabel, status_label_id)
    if new_status is None:
        return _toast(request, False, "Unknown status label.")
    if new_status.status_type == StatusType.deployed:
        return _toast(request, False, "Deployed status is only set via checkout.")

    was_archived = asset.status_label.status_type == StatusType.archived
    now_archived = new_status.status_type == StatusType.archived

    if was_archived:
        # Restore-only path: the only thing an archived asset's form can do
        # is move to a non-archived status. Nothing else is editable.
        if now_archived:
            return _toast(request, False, "Archived — pick a status to restore it before editing.")
        asset.status_label_id = status_label_id
        db.add(
            AuditLog(
                user_id=user.id, action="restore", entity_type="asset", entity_id=str(asset_id),
                detail=f"{asset.status_label.name} -> {new_status.name}",
            )
        )
        await db.commit()
        return _toast(request, True, f"Restored to {new_status.name}.")

    if asset.checked_out_at is not None and status_label_id != asset.status_label_id:
        return _toast(request, False, "Checked out — checkin before changing status.")

    if model_id is None:
        return _toast(request, False, "Model is required.")
    if await db.get(AssetModel, model_id) is None:
        return _toast(request, False, "Unknown model.")
    tag = (asset_tag or "").strip()
    if not tag:
        return _toast(request, False, "Asset tag is required.")
    company_id_val = int(company_id) if company_id.isdigit() else None
    if company_id_val is not None and await db.get(Company, company_id_val) is None:
        return _toast(request, False, "Unknown company.")
    location_id_val = int(location_id) if location_id.isdigit() else None
    if location_id_val is not None and await db.get(Location, location_id_val) is None:
        return _toast(request, False, "Unknown location.")
    purchase_currency_val = purchase_currency.strip().upper() or None
    if purchase_currency_val is not None and await db.get(Currency, purchase_currency_val) is None:
        return _toast(request, False, "Unknown currency.")

    p_date, err = _parse_optional_date(purchase_date, "Purchase date")
    if err:
        return _toast(request, False, err)
    p_cost, err = _parse_optional_decimal(purchase_cost, "Purchase cost")
    if err:
        return _toast(request, False, err)
    warranty, err = _parse_optional_int(warranty_months, "Warranty months")
    if err:
        return _toast(request, False, err)
    dep_override, err = _parse_optional_int(depreciation_months_override, "Depreciation months")
    if err:
        return _toast(request, False, err)
    eol_override, err = _parse_optional_int(eol_months_override, "EOL months")
    if err:
        return _toast(request, False, err)

    old_status_name = asset.status_label.name
    asset.asset_tag = tag
    asset.model_id = model_id
    asset.status_label_id = status_label_id
    asset.serial = serial.strip() or None
    asset.company_id = company_id_val
    asset.location_id = location_id_val
    asset.purchase_date = p_date
    asset.purchase_cost = p_cost
    asset.purchase_currency = purchase_currency_val
    asset.warranty_months = warranty
    asset.depreciation_months_override = dep_override
    asset.eol_months_override = eol_override
    asset.notes = notes.strip() or None

    action = "archive" if now_archived else "update"
    detail = f"{old_status_name} -> {new_status.name}" if now_archived else asset.asset_tag
    db.add(AuditLog(user_id=user.id, action=action, entity_type="asset", entity_id=str(asset_id), detail=detail))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return _toast(request, False, f"Asset tag '{tag}' already exists.")
    return _toast(request, True, "Saved." if not now_archived else f"Archived ({new_status.name}).")


@router.post("/{asset_id}/delete", response_class=HTMLResponse)
async def asset_delete(
    request: Request,
    asset_id: int,
    user: CurrentUser = Depends(require("assets.delete")),
    db: AsyncSession = Depends(get_db),
):
    asset = await db.get(Asset, asset_id)
    if asset is None:
        return _toast(request, False, "Not found.")

    attachment_count = (
        await db.execute(
            select(func.count()).select_from(Attachment).where(
                Attachment.entity_type == "asset", Attachment.entity_id == str(asset_id)
            )
        )
    ).scalar_one()
    if attachment_count:
        return _toast(
            request, False,
            f"Cannot delete '{asset.asset_tag}': {attachment_count} attachment(s) attached — "
            "remove them first, or archive instead.",
        )

    maintenance_count = (
        await db.execute(select(func.count()).select_from(Maintenance).where(Maintenance.asset_id == asset_id))
    ).scalar_one()
    if maintenance_count:
        return _toast(
            request, False,
            f"Cannot delete '{asset.asset_tag}': {maintenance_count} maintenance record(s) exist — "
            "archive instead to keep the history.",
        )

    tag = asset.asset_tag
    await db.delete(asset)
    db.add(AuditLog(user_id=user.id, action="delete", entity_type="asset", entity_id=str(asset_id), detail=tag))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return _toast(request, False, f"Cannot delete '{tag}': it has checkout history — archive it instead.")
    return _redirect("/assets")


# ---- checkout / checkin ----

@router.post("/{asset_id}/checkout", response_class=HTMLResponse)
async def asset_checkout(
    request: Request,
    asset_id: int,
    background_tasks: BackgroundTasks,
    target_user_id: str = Form(""),
    target_location_id: str = Form(""),
    target_asset_id: str = Form(""),
    status_label_id: int | None = Form(None),
    expected_checkin_at: str = Form(""),
    notes: str = Form(""),
    user: CurrentUser = Depends(require("checkout.perform")),
    db: AsyncSession = Depends(get_db),
):
    asset = await db.get(Asset, asset_id, options=[selectinload(Asset.status_label)])
    if asset is None:
        return _toast(request, False, "Asset not found.")
    if asset.status_label.status_type != StatusType.deployable:
        return _toast(request, False, "Only deployable assets can be checked out.")
    if asset.checked_out_at is not None:
        return _toast(request, False, "Already checked out.")
    if status_label_id is None:
        return _toast(request, False, "Pick a valid deployed-type status.")

    targets = {
        "user": int(target_user_id) if target_user_id.isdigit() else None,
        "location": int(target_location_id) if target_location_id.isdigit() else None,
        "asset": int(target_asset_id) if target_asset_id.isdigit() else None,
    }
    chosen = [(kind, tid) for kind, tid in targets.items() if tid is not None]
    if len(chosen) != 1:
        return _toast(request, False, "Pick exactly one target: user, location, or asset.")
    target_kind, target_id = chosen[0]

    target_user_email = None
    if target_kind == "user":
        target_user = await db.get(User, target_id)
        if target_user is None:
            return _toast(request, False, "Unknown user.")
        target_user_email = target_user.email
    if target_kind == "location" and await db.get(Location, target_id) is None:
        return _toast(request, False, "Unknown location.")
    if target_kind == "asset":
        if target_id == asset_id:
            return _toast(request, False, "An asset cannot be checked out to itself.")
        if await db.get(Asset, target_id) is None:
            return _toast(request, False, "Unknown target asset.")

    dest_status = await db.get(StatusLabel, status_label_id)
    if dest_status is None or dest_status.status_type != StatusType.deployed:
        return _toast(request, False, "Pick a valid deployed-type status.")

    exp_date, err = _parse_optional_date(expected_checkin_at, "Expected checkin date")
    if err:
        return _toast(request, False, err)

    now = datetime.now(timezone.utc)
    asset.checked_out_to_user_id = targets["user"]
    asset.checked_out_to_location_id = targets["location"]
    asset.checked_out_to_asset_id = targets["asset"]
    asset.checked_out_at = now
    asset.status_label_id = status_label_id

    db.add(
        Checkout(
            asset_id=asset_id,
            target_user_id=targets["user"],
            target_location_id=targets["location"],
            target_asset_id=targets["asset"],
            status_label_id_at_checkout=status_label_id,
            checked_out_at=now,
            checked_out_by=user.id,
            expected_checkin_at=exp_date,
            notes=notes.strip() or None,
        )
    )
    db.add(
        AuditLog(
            user_id=user.id, action="checkout", entity_type="asset", entity_id=str(asset_id),
            detail=f"checked out to {target_kind}:{target_id}",
        )
    )
    try:
        await db.commit()
    except IntegrityError:
        # Partial unique index on core_checkouts (one open checkout per
        # asset) caught a race — extremely unlikely at this app's scale,
        # but fail safe rather than corrupt state.
        await db.rollback()
        return _toast(request, False, "Already checked out (concurrent request) — refresh and try again.")
    background_tasks.add_task(notify_checkout, asset.asset_tag, target_user_email)
    return _refresh()


@router.post("/{asset_id}/checkin", response_class=HTMLResponse)
async def asset_checkin(
    request: Request,
    asset_id: int,
    background_tasks: BackgroundTasks,
    status_label_id: int | None = Form(None),
    notes: str = Form(""),
    user: CurrentUser = Depends(require("checkout.perform")),
    db: AsyncSession = Depends(get_db),
):
    asset = await db.get(Asset, asset_id, options=[selectinload(Asset.status_label)])
    if asset is None:
        return _toast(request, False, "Asset not found.")
    if asset.checked_out_at is None or asset.status_label.status_type != StatusType.deployed:
        return _toast(request, False, "This asset is not currently checked out.")
    if status_label_id is None:
        return _toast(request, False, "Pick a non-deployed status to checkin to.")

    dest_status = await db.get(StatusLabel, status_label_id)
    if dest_status is None:
        return _toast(request, False, "Unknown status label.")
    if dest_status.status_type == StatusType.deployed:
        return _toast(request, False, "Pick a non-deployed status to checkin to.")

    open_checkout = (
        await db.execute(
            select(Checkout).where(Checkout.asset_id == asset_id, Checkout.checked_in_at.is_(None))
        )
    ).scalar_one_or_none()
    if open_checkout is None:
        return _toast(request, False, "No open checkout found for this asset.")

    target_user_email = None
    if open_checkout.target_user_id is not None:
        target_user = await db.get(User, open_checkout.target_user_id)
        target_user_email = target_user.email if target_user else None

    now = datetime.now(timezone.utc)
    checkin_notes = notes.strip() or None
    open_checkout.checked_in_at = now
    open_checkout.checked_in_by = user.id
    open_checkout.checkin_status_label_id = status_label_id
    if checkin_notes:
        open_checkout.notes = f"{open_checkout.notes}\n{checkin_notes}" if open_checkout.notes else checkin_notes

    asset.checked_out_to_user_id = None
    asset.checked_out_to_location_id = None
    asset.checked_out_to_asset_id = None
    asset.checked_out_at = None
    asset.status_label_id = status_label_id

    db.add(
        AuditLog(
            user_id=user.id, action="checkin", entity_type="asset", entity_id=str(asset_id),
            detail=f"checked in -> {dest_status.name}",
        )
    )
    await db.commit()
    background_tasks.add_task(notify_checkin, asset.asset_tag, target_user_email)
    return _refresh()


# ---- attachments ----

async def _get_attachment_for_asset(db: AsyncSession, asset_id: int, attachment_id: int) -> Attachment | None:
    att = await db.get(Attachment, attachment_id)
    if att is None or att.entity_type != "asset" or att.entity_id != str(asset_id):
        return None
    return att


@router.post("/{asset_id}/attachments", response_class=HTMLResponse)
async def asset_attachment_upload(
    request: Request,
    asset_id: int,
    file: UploadFile | None = File(None),
    description: str = Form(""),
    user: CurrentUser = Depends(require("assets.edit")),
    db: AsyncSession = Depends(get_db),
):
    asset = await db.get(Asset, asset_id, options=[selectinload(Asset.status_label)])
    if asset is None:
        return _toast(request, False, "Asset not found.")
    if asset.status_label.status_type == StatusType.archived:
        return _toast(request, False, "Archived — restore it before adding attachments.")
    if file is None or not file.filename:
        return _toast(request, False, "No file selected.")

    stored_name, size, err = await save_upload(file, "asset", str(asset_id))
    if err:
        return _toast(request, False, err)

    row = Attachment(
        entity_type="asset",
        entity_id=str(asset_id),
        original_filename=file.filename,
        stored_filename=stored_name,
        content_type=file.content_type,
        size_bytes=size,
        description=description.strip() or None,
        uploaded_by=user.id,
    )
    db.add(row)
    await db.flush()
    db.add(
        AuditLog(
            user_id=user.id, action="attachment_add", entity_type="asset", entity_id=str(asset_id),
            detail=file.filename,
        )
    )
    await db.commit()
    return _refresh()


@router.get("/{asset_id}/attachments/{attachment_id}/download")
async def asset_attachment_download(
    asset_id: int,
    attachment_id: int,
    user: CurrentUser = Depends(require("assets.view")),
    db: AsyncSession = Depends(get_db),
):
    att = await _get_attachment_for_asset(db, asset_id, attachment_id)
    if att is None:
        raise HTTPException(status_code=404, detail="Attachment not found.")
    path = attachment_dir(att.entity_type, att.entity_id) / att.stored_filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File missing on disk.")
    return FileResponse(path, filename=att.original_filename, media_type=att.content_type or "application/octet-stream")


@router.post("/{asset_id}/attachments/{attachment_id}/delete", response_class=HTMLResponse)
async def asset_attachment_delete(
    request: Request,
    asset_id: int,
    attachment_id: int,
    user: CurrentUser = Depends(require("assets.edit")),
    db: AsyncSession = Depends(get_db),
):
    asset = await db.get(Asset, asset_id, options=[selectinload(Asset.status_label)])
    if asset is None:
        return _toast(request, False, "Asset not found.")
    if asset.status_label.status_type == StatusType.archived:
        return _toast(request, False, "Archived — restore it before removing attachments.")
    att = await _get_attachment_for_asset(db, asset_id, attachment_id)
    if att is None:
        return _toast(request, False, "Attachment not found.")

    filename = att.original_filename
    path = attachment_dir(att.entity_type, att.entity_id) / att.stored_filename
    await db.delete(att)
    db.add(
        AuditLog(
            user_id=user.id, action="attachment_delete", entity_type="asset", entity_id=str(asset_id),
            detail=filename,
        )
    )
    await db.commit()
    path.unlink(missing_ok=True)
    return _refresh()
