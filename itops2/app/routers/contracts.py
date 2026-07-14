"""Licenses & Contracts: ONE unified simple module (not Snipe-IT
seat-tracking). List page sorted by next renewal (end_date) with an
"expiring soon" / "expired" visual state driven by the
contracts.renewal_alert_days setting. Optional M2M coverage of assets
(core_contract_assets, CASCADE both sides — see CLAUDE.md). Attachments
reuse the shared app.core.attachments helpers with entity_type='contract'.

Deleting a contract explicitly cleans up its attachments (DB rows +
files, same as Maintenance) — its asset-links clean up on their own via
ON DELETE CASCADE, no app-level guard or cleanup needed for those.
"""

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.attachments import MAX_ATTACHMENT_SIZE, attachment_dir, save_upload
from app.core.auth import CurrentUser, require
from app.core.db import get_db
from app.core.models import (
    Asset,
    Attachment,
    AuditLog,
    Company,
    Contract,
    ContractAsset,
    ContractType,
    Currency,
    Location,
)
from app.core.settings_store import load_settings
from app.templating import templates

router = APIRouter(prefix="/contracts")


def _toast(request: Request, ok: bool, message: str):
    return templates.TemplateResponse(request, "partials/toast.html", {"ok": ok, "message": message})


def _refresh():
    return Response(status_code=204, headers={"HX-Refresh": "true"})


def _redirect(path: str):
    return Response(status_code=204, headers={"HX-Redirect": path})


def _parse_date(value: str, field: str, required: bool = True):
    value = (value or "").strip()
    if not value:
        if required:
            return None, f"{field} is required."
        return None, None
    try:
        return date.fromisoformat(value), None
    except ValueError:
        return None, f"{field} must be a valid date."


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


def _parse_optional_int(value: str, field: str):
    value = (value or "").strip()
    if not value:
        return None, None
    if not value.isdigit():
        return None, f"{field} must be a whole number."
    return int(value), None


async def _form_context(db: AsyncSession) -> dict:
    store = await load_settings(db)
    companies = (await db.execute(select(Company).order_by(Company.name))).scalars().all()
    locations = (await db.execute(select(Location).order_by(Location.name))).scalars().all()
    currencies = (
        await db.execute(select(Currency).where(Currency.active.is_(True)).order_by(Currency.code))
    ).scalars().all()
    return {
        "companies": companies,
        "locations": locations,
        "currencies": currencies,
        "contract_types": list(ContractType),
        "multi_company": store.get_bool("company.multi_enabled"),
        "default_currency": store.get("general.default_currency"),
    }


def _renewal_state(end_date: date, today: date, alert_days: int) -> str:
    if end_date < today:
        return "expired"
    if end_date <= today + timedelta(days=alert_days):
        return "expiring_soon"
    return "normal"


async def _validate_fields(
    db: AsyncSession, contract_type: str, start_date: str, end_date: str,
    cost: str, currency: str, renewal_period_months: str,
):
    """Returns (start, end, cost_val, currency_val, renewal_val, ctype, error)."""
    if contract_type not in ContractType.__members__:
        return None, None, None, None, None, None, "Unknown contract type."
    start, err = _parse_date(start_date, "Start date", required=False)
    if err:
        return None, None, None, None, None, None, err
    end, err = _parse_date(end_date, "End/renewal date", required=True)
    if err:
        return None, None, None, None, None, None, err
    cost_val, err = _parse_optional_decimal(cost, "Cost")
    if err:
        return None, None, None, None, None, None, err
    currency_val = currency.strip().upper() or None
    if currency_val is not None and await db.get(Currency, currency_val) is None:
        return None, None, None, None, None, None, "Unknown currency."
    if cost_val is not None and currency_val is None:
        return None, None, None, None, None, None, "Pick a currency for the cost."
    renewal_val, err = _parse_optional_int(renewal_period_months, "Renewal period")
    if err:
        return None, None, None, None, None, None, err
    return start, end, cost_val, currency_val, renewal_val, ContractType(contract_type), None


# ---- list ----

@router.get("", response_class=HTMLResponse)
async def contracts_list(
    request: Request,
    state: str | None = None,
    user: CurrentUser = Depends(require("contracts.view")),
    db: AsyncSession = Depends(get_db),
):
    """`state` query param (added for the Dashboard's card, Phase 8):
    "expiring_soon" or "expired", filtering to just that renewal state."""
    store = await load_settings(db)
    alert_days = store.get_int("contracts.renewal_alert_days")
    today = date.today()

    contracts = (
        (
            await db.execute(
                select(Contract)
                .options(selectinload(Contract.company), selectinload(Contract.location))
                .order_by(Contract.end_date)
            )
        )
        .scalars()
        .all()
    )
    rows = [{"contract": c, "state": _renewal_state(c.end_date, today, alert_days)} for c in contracts]
    if state in ("expiring_soon", "expired"):
        rows = [r for r in rows if r["state"] == state]

    return templates.TemplateResponse(
        request, "contracts/list.html", {"user": user, "rows": rows, "filter_active": state in ("expiring_soon", "expired")},
    )


# ---- create ----

@router.get("/new", response_class=HTMLResponse)
async def contracts_new(
    request: Request,
    user: CurrentUser = Depends(require("contracts.manage")),
    db: AsyncSession = Depends(get_db),
):
    ctx = await _form_context(db)
    ctx.update({"user": user})
    return templates.TemplateResponse(request, "contracts/new.html", ctx)


@router.post("/create", response_class=HTMLResponse)
async def contracts_create(
    request: Request,
    name: str = Form(""),
    contract_type: str = Form(""),
    vendor: str = Form(""),
    company_id: str = Form(""),
    location_id: str = Form(""),
    start_date: str = Form(""),
    end_date: str = Form(""),
    cost: str = Form(""),
    currency: str = Form(""),
    renewal_period_months: str = Form(""),
    auto_renews: str = Form("false"),
    notes: str = Form(""),
    user: CurrentUser = Depends(require("contracts.manage")),
    db: AsyncSession = Depends(get_db),
):
    if not name.strip():
        return _toast(request, False, "Name is required.")
    start, end, cost_val, currency_val, renewal_val, ctype, err = await _validate_fields(
        db, contract_type, start_date, end_date, cost, currency, renewal_period_months
    )
    if err:
        return _toast(request, False, err)
    company_id_val = int(company_id) if company_id.isdigit() else None
    if company_id_val is not None and await db.get(Company, company_id_val) is None:
        return _toast(request, False, "Unknown company.")
    location_id_val = int(location_id) if location_id.isdigit() else None
    if location_id_val is not None and await db.get(Location, location_id_val) is None:
        return _toast(request, False, "Unknown location.")

    row = Contract(
        name=name.strip(), contract_type=ctype, vendor=vendor.strip() or None,
        company_id=company_id_val, location_id=location_id_val,
        start_date=start, end_date=end, cost=cost_val, currency=currency_val,
        renewal_period_months=renewal_val, auto_renews=auto_renews == "true",
        notes=notes.strip() or None, created_by=user.id,
    )
    db.add(row)
    await db.flush()
    db.add(AuditLog(user_id=user.id, action="create", entity_type="contract", entity_id=str(row.id), detail=row.name))
    await db.commit()
    return _redirect(f"/contracts/{row.id}")


# ---- detail / edit ----

@router.get("/{contract_id}", response_class=HTMLResponse)
async def contract_detail(
    request: Request,
    contract_id: int,
    user: CurrentUser = Depends(require("contracts.view")),
    db: AsyncSession = Depends(get_db),
):
    contract = (
        await db.execute(
            select(Contract)
            .options(selectinload(Contract.company), selectinload(Contract.location))
            .where(Contract.id == contract_id)
        )
    ).scalar_one_or_none()
    if contract is None:
        return templates.TemplateResponse(
            request, "partials/toast.html", {"ok": False, "message": "Contract not found."}, status_code=404,
        )

    store = await load_settings(db)
    alert_days = store.get_int("contracts.renewal_alert_days")
    state = _renewal_state(contract.end_date, date.today(), alert_days)

    linked = (
        (
            await db.execute(
                select(ContractAsset)
                .options(selectinload(ContractAsset.asset))
                .where(ContractAsset.contract_id == contract_id)
            )
        )
        .scalars()
        .all()
    )
    linked_asset_ids = {la.asset_id for la in linked}
    linkable_query = select(Asset).order_by(Asset.asset_tag)
    if linked_asset_ids:
        linkable_query = linkable_query.where(~Asset.id.in_(linked_asset_ids))
    linkable_assets = (await db.execute(linkable_query)).scalars().all()

    attachments = (
        (
            await db.execute(
                select(Attachment)
                .where(Attachment.entity_type == "contract", Attachment.entity_id == str(contract_id))
                .order_by(Attachment.uploaded_at.desc())
                .options(selectinload(Attachment.uploader))
            )
        )
        .scalars()
        .all()
    )

    ctx = await _form_context(db)
    ctx.update(
        {
            "user": user,
            "contract": contract,
            "state": state,
            "linked_assets": linked,
            "linkable_assets": linkable_assets,
            "attachments": attachments,
            "max_attachment_mb": MAX_ATTACHMENT_SIZE // (1024 * 1024),
        }
    )
    return templates.TemplateResponse(request, "contracts/detail.html", ctx)


@router.post("/{contract_id}/update", response_class=HTMLResponse)
async def contract_update(
    request: Request,
    contract_id: int,
    name: str = Form(""),
    contract_type: str = Form(""),
    vendor: str = Form(""),
    company_id: str = Form(""),
    location_id: str = Form(""),
    start_date: str = Form(""),
    end_date: str = Form(""),
    cost: str = Form(""),
    currency: str = Form(""),
    renewal_period_months: str = Form(""),
    auto_renews: str = Form("false"),
    notes: str = Form(""),
    user: CurrentUser = Depends(require("contracts.manage")),
    db: AsyncSession = Depends(get_db),
):
    contract = await db.get(Contract, contract_id)
    if contract is None:
        return _toast(request, False, "Contract not found.")
    if not name.strip():
        return _toast(request, False, "Name is required.")
    start, end, cost_val, currency_val, renewal_val, ctype, err = await _validate_fields(
        db, contract_type, start_date, end_date, cost, currency, renewal_period_months
    )
    if err:
        return _toast(request, False, err)
    company_id_val = int(company_id) if company_id.isdigit() else None
    if company_id_val is not None and await db.get(Company, company_id_val) is None:
        return _toast(request, False, "Unknown company.")
    location_id_val = int(location_id) if location_id.isdigit() else None
    if location_id_val is not None and await db.get(Location, location_id_val) is None:
        return _toast(request, False, "Unknown location.")

    contract.name = name.strip()
    contract.contract_type = ctype
    contract.vendor = vendor.strip() or None
    contract.company_id = company_id_val
    contract.location_id = location_id_val
    contract.start_date = start
    contract.end_date = end
    contract.cost = cost_val
    contract.currency = currency_val
    contract.renewal_period_months = renewal_val
    contract.auto_renews = auto_renews == "true"
    contract.notes = notes.strip() or None

    db.add(AuditLog(user_id=user.id, action="update", entity_type="contract", entity_id=str(contract_id), detail=contract.name))
    await db.commit()
    return _toast(request, True, "Saved.")


@router.post("/{contract_id}/delete", response_class=HTMLResponse)
async def contract_delete(
    request: Request,
    contract_id: int,
    user: CurrentUser = Depends(require("contracts.manage")),
    db: AsyncSession = Depends(get_db),
):
    contract = await db.get(Contract, contract_id)
    if contract is None:
        return _toast(request, False, "Not found.")

    attachments = (
        await db.execute(
            select(Attachment).where(Attachment.entity_type == "contract", Attachment.entity_id == str(contract_id))
        )
    ).scalars().all()
    paths_to_unlink = [attachment_dir(a.entity_type, a.entity_id) / a.stored_filename for a in attachments]
    for a in attachments:
        await db.delete(a)

    name = contract.name
    await db.delete(contract)
    db.add(AuditLog(user_id=user.id, action="delete", entity_type="contract", entity_id=str(contract_id), detail=name))
    await db.commit()
    for path in paths_to_unlink:
        path.unlink(missing_ok=True)
    return _redirect("/contracts")


# ---- asset linking ----

@router.post("/{contract_id}/assets/link", response_class=HTMLResponse)
async def contract_link_asset(
    request: Request,
    contract_id: int,
    asset_id: int | None = Form(None),
    user: CurrentUser = Depends(require("contracts.manage")),
    db: AsyncSession = Depends(get_db),
):
    contract = await db.get(Contract, contract_id)
    if contract is None:
        return _toast(request, False, "Contract not found.")
    if asset_id is None:
        return _toast(request, False, "Pick an asset to link.")
    asset = await db.get(Asset, asset_id)
    if asset is None:
        return _toast(request, False, "Unknown asset.")
    existing = await db.get(ContractAsset, {"contract_id": contract_id, "asset_id": asset_id})
    if existing is not None:
        return _toast(request, False, f"'{asset.asset_tag}' is already linked.")

    db.add(ContractAsset(contract_id=contract_id, asset_id=asset_id))
    db.add(
        AuditLog(
            user_id=user.id, action="link_asset", entity_type="contract", entity_id=str(contract_id),
            detail=asset.asset_tag,
        )
    )
    await db.commit()
    return _refresh()


@router.post("/{contract_id}/assets/{asset_id}/unlink", response_class=HTMLResponse)
async def contract_unlink_asset(
    request: Request,
    contract_id: int,
    asset_id: int,
    user: CurrentUser = Depends(require("contracts.manage")),
    db: AsyncSession = Depends(get_db),
):
    link = await db.get(ContractAsset, {"contract_id": contract_id, "asset_id": asset_id})
    if link is None:
        return _toast(request, False, "Not linked.")
    asset = await db.get(Asset, asset_id)
    await db.delete(link)
    db.add(
        AuditLog(
            user_id=user.id, action="unlink_asset", entity_type="contract", entity_id=str(contract_id),
            detail=asset.asset_tag if asset else str(asset_id),
        )
    )
    await db.commit()
    return _refresh()


# ---- attachments (reuse the shared polymorphic table) ----

@router.post("/{contract_id}/attachments", response_class=HTMLResponse)
async def contract_attachment_upload(
    request: Request,
    contract_id: int,
    file: UploadFile | None = File(None),
    description: str = Form(""),
    user: CurrentUser = Depends(require("contracts.manage")),
    db: AsyncSession = Depends(get_db),
):
    contract = await db.get(Contract, contract_id)
    if contract is None:
        return _toast(request, False, "Contract not found.")
    if file is None or not file.filename:
        return _toast(request, False, "No file selected.")

    stored_name, size, err = await save_upload(file, "contract", str(contract_id))
    if err:
        return _toast(request, False, err)

    att = Attachment(
        entity_type="contract",
        entity_id=str(contract_id),
        original_filename=file.filename,
        stored_filename=stored_name,
        content_type=file.content_type,
        size_bytes=size,
        description=description.strip() or None,
        uploaded_by=user.id,
    )
    db.add(att)
    await db.flush()
    db.add(
        AuditLog(
            user_id=user.id, action="attachment_add", entity_type="contract", entity_id=str(contract_id),
            detail=file.filename,
        )
    )
    await db.commit()
    return _refresh()


@router.get("/{contract_id}/attachments/{attachment_id}/download")
async def contract_attachment_download(
    contract_id: int,
    attachment_id: int,
    user: CurrentUser = Depends(require("contracts.view")),
    db: AsyncSession = Depends(get_db),
):
    att = await db.get(Attachment, attachment_id)
    if att is None or att.entity_type != "contract" or att.entity_id != str(contract_id):
        raise HTTPException(status_code=404, detail="Attachment not found.")
    path = attachment_dir(att.entity_type, att.entity_id) / att.stored_filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File missing on disk.")
    return FileResponse(path, filename=att.original_filename, media_type=att.content_type or "application/octet-stream")


@router.post("/{contract_id}/attachments/{attachment_id}/delete", response_class=HTMLResponse)
async def contract_attachment_delete(
    request: Request,
    contract_id: int,
    attachment_id: int,
    user: CurrentUser = Depends(require("contracts.manage")),
    db: AsyncSession = Depends(get_db),
):
    att = await db.get(Attachment, attachment_id)
    if att is None or att.entity_type != "contract" or att.entity_id != str(contract_id):
        return _toast(request, False, "Attachment not found.")

    filename = att.original_filename
    path = attachment_dir(att.entity_type, att.entity_id) / att.stored_filename
    await db.delete(att)
    db.add(
        AuditLog(
            user_id=user.id, action="attachment_delete", entity_type="contract", entity_id=str(contract_id),
            detail=filename,
        )
    )
    await db.commit()
    path.unlink(missing_ok=True)
    return _refresh()
