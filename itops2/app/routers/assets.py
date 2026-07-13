"""Assets: the core inventory record. List + detail/edit page (too many
fields for Catalog's inline-row pattern) — checkout/checkin (Phase 5
chunk 4) and attachments (chunk 5) both live on the detail page.

Status lifecycle rules:
- status_type == deployed is reachable ONLY via checkout (never through
  this general create/edit form — the dropdown here excludes it).
- Editing status while checked_out_at IS NOT NULL is rejected: must
  checkin first (keeps the checked_out_at <-> deployed invariant intact;
  the DB can't enforce this cross-table itself).
- status_type == archived assets are read-only except for a restore
  action (submit a non-archived status_label_id and nothing else).
  Audit action is "archive"/"restore" when a transition crosses that
  boundary, "update" otherwise.

Hard delete requires zero checkout history AND zero attachments:
checkout history is a real FK (core_checkouts.asset_id) so that half is
an IntegrityError catch, same as Catalog. Attachments are the
entity_type/entity_id polymorphism style (like core_audit_log), which
has no enforced FK, so that half is an explicit COUNT check before the
delete is attempted. See CLAUDE.md for why attachments and checkout
targets use two different polymorphism styles.
"""

from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import CurrentUser, require
from app.core.db import get_db
from app.core.models import (
    Asset,
    AssetModel,
    Attachment,
    AuditLog,
    Company,
    Currency,
    Location,
    StatusLabel,
    StatusType,
)
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
    model_id: int = Form(...),
    status_label_id: int = Form(...),
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
    ctx.update(
        {
            "user": user,
            "asset": asset,
            "is_archived": asset.status_label.status_type == StatusType.archived,
            "is_checked_out": asset.checked_out_at is not None,
            "effective_depreciation_months": _effective_months(
                asset.depreciation_months_override,
                asset.model.depreciation_months,
                store.get_int("depreciation.default_months"),
            ),
            "effective_eol_months": _effective_months(asset.eol_months_override, asset.model.eol_months),
        }
    )
    return templates.TemplateResponse(request, "assets/detail.html", ctx)


@router.post("/{asset_id}/update", response_class=HTMLResponse)
async def asset_update(
    request: Request,
    asset_id: int,
    status_label_id: int = Form(...),
    serial: str = Form(""),
    # Optional at the FastAPI layer only so the minimal restore-only form
    # (status_label_id alone) can post without them; required below for
    # any non-restore edit.
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

    tag = asset.asset_tag
    await db.delete(asset)
    db.add(AuditLog(user_id=user.id, action="delete", entity_type="asset", entity_id=str(asset_id), detail=tag))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return _toast(request, False, f"Cannot delete '{tag}': it has checkout history — archive it instead.")
    return _redirect("/assets")
