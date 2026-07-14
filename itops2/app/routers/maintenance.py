"""Maintenance/repair/upgrade records — generic against any asset (not
printer-specific), shown as a section on the asset detail page.
Attachments (receipts, photos) reuse core_attachments via the shared
app.core.attachments helpers, with entity_type='maintenance'.

Deleting a maintenance record also deletes its attachments (DB rows +
files) explicitly, since core_attachments has no FK to cascade through
(see app/core/attachments.py / CLAUDE.md).
"""

from datetime import date as date_cls
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.attachments import attachment_dir, save_upload
from app.core.auth import CurrentUser, require
from app.core.db import get_db
from app.core.models import Asset, Attachment, AuditLog, Currency, Maintenance, MaintenanceType
from app.templating import templates

router = APIRouter(prefix="/assets/{asset_id}/maintenance")


def _toast(request: Request, ok: bool, message: str):
    return templates.TemplateResponse(request, "partials/toast.html", {"ok": ok, "message": message})


def _refresh():
    return Response(status_code=204, headers={"HX-Refresh": "true"})


def _parse_date(value: str, field: str):
    value = (value or "").strip()
    if not value:
        return None, f"{field} is required."
    try:
        return date_cls.fromisoformat(value), None
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


async def _validate_fields(db: AsyncSession, date: str, maintenance_type: str, description: str, cost: str, currency: str):
    """Returns (d, mtype, cost_val, currency_val, error)."""
    if maintenance_type not in MaintenanceType.__members__:
        return None, None, None, None, "Unknown maintenance type."
    d, err = _parse_date(date, "Date")
    if err:
        return None, None, None, None, err
    if not description.strip():
        return None, None, None, None, "Description is required."
    cost_val, err = _parse_optional_decimal(cost, "Cost")
    if err:
        return None, None, None, None, err
    currency_val = currency.strip().upper() or None
    if currency_val is not None and await db.get(Currency, currency_val) is None:
        return None, None, None, None, "Unknown currency."
    if cost_val is not None and currency_val is None:
        return None, None, None, None, "Pick a currency for the cost."
    return d, MaintenanceType(maintenance_type), cost_val, currency_val, None


@router.post("/create", response_class=HTMLResponse)
async def maintenance_create(
    request: Request,
    asset_id: int,
    date: str = Form(""),
    maintenance_type: str = Form(""),
    description: str = Form(""),
    cost: str = Form(""),
    currency: str = Form(""),
    performed_by: str = Form(""),
    user: CurrentUser = Depends(require("maintenance.manage")),
    db: AsyncSession = Depends(get_db),
):
    asset = await db.get(Asset, asset_id)
    if asset is None:
        return _toast(request, False, "Asset not found.")

    d, mtype, cost_val, currency_val, err = await _validate_fields(
        db, date, maintenance_type, description, cost, currency
    )
    if err:
        return _toast(request, False, err)

    row = Maintenance(
        asset_id=asset_id, date=d, maintenance_type=mtype, description=description.strip(),
        cost=cost_val, currency=currency_val, performed_by=performed_by.strip() or None,
        created_by=user.id,
    )
    db.add(row)
    await db.flush()
    db.add(
        AuditLog(
            user_id=user.id, action="create", entity_type="maintenance", entity_id=str(row.id),
            detail=f"asset:{asset_id} {mtype.value}",
        )
    )
    await db.commit()
    return _refresh()


@router.post("/{maintenance_id}/update", response_class=HTMLResponse)
async def maintenance_update(
    request: Request,
    asset_id: int,
    maintenance_id: int,
    date: str = Form(""),
    maintenance_type: str = Form(""),
    description: str = Form(""),
    cost: str = Form(""),
    currency: str = Form(""),
    performed_by: str = Form(""),
    user: CurrentUser = Depends(require("maintenance.manage")),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(Maintenance, maintenance_id)
    if row is None or row.asset_id != asset_id:
        return _toast(request, False, "Maintenance record not found.")

    d, mtype, cost_val, currency_val, err = await _validate_fields(
        db, date, maintenance_type, description, cost, currency
    )
    if err:
        return _toast(request, False, err)

    row.date = d
    row.maintenance_type = mtype
    row.description = description.strip()
    row.cost = cost_val
    row.currency = currency_val
    row.performed_by = performed_by.strip() or None
    db.add(
        AuditLog(
            user_id=user.id, action="update", entity_type="maintenance", entity_id=str(maintenance_id),
            detail=f"asset:{asset_id} {mtype.value}",
        )
    )
    await db.commit()
    return _refresh()


@router.post("/{maintenance_id}/delete", response_class=HTMLResponse)
async def maintenance_delete(
    request: Request,
    asset_id: int,
    maintenance_id: int,
    user: CurrentUser = Depends(require("maintenance.manage")),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(Maintenance, maintenance_id)
    if row is None or row.asset_id != asset_id:
        return _toast(request, False, "Maintenance record not found.")

    attachments = (
        await db.execute(
            select(Attachment).where(
                Attachment.entity_type == "maintenance", Attachment.entity_id == str(maintenance_id)
            )
        )
    ).scalars().all()
    paths_to_unlink = [attachment_dir(a.entity_type, a.entity_id) / a.stored_filename for a in attachments]
    for a in attachments:
        await db.delete(a)

    db.add(
        AuditLog(
            user_id=user.id, action="delete", entity_type="maintenance", entity_id=str(maintenance_id),
            detail=f"asset:{asset_id}",
        )
    )
    await db.delete(row)
    await db.commit()
    for path in paths_to_unlink:
        path.unlink(missing_ok=True)
    return _refresh()


# ---- attachments (reuse the shared polymorphic table) ----

@router.post("/{maintenance_id}/attachments", response_class=HTMLResponse)
async def maintenance_attachment_upload(
    request: Request,
    asset_id: int,
    maintenance_id: int,
    file: UploadFile | None = File(None),
    description: str = Form(""),
    user: CurrentUser = Depends(require("maintenance.manage")),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(Maintenance, maintenance_id)
    if row is None or row.asset_id != asset_id:
        return _toast(request, False, "Maintenance record not found.")
    if file is None or not file.filename:
        return _toast(request, False, "No file selected.")

    stored_name, size, err = await save_upload(file, "maintenance", str(maintenance_id))
    if err:
        return _toast(request, False, err)

    att = Attachment(
        entity_type="maintenance",
        entity_id=str(maintenance_id),
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
            user_id=user.id, action="attachment_add", entity_type="maintenance", entity_id=str(maintenance_id),
            detail=file.filename,
        )
    )
    await db.commit()
    return _refresh()


@router.get("/{maintenance_id}/attachments/{attachment_id}/download")
async def maintenance_attachment_download(
    asset_id: int,
    maintenance_id: int,
    attachment_id: int,
    user: CurrentUser = Depends(require("assets.view")),
    db: AsyncSession = Depends(get_db),
):
    att = await db.get(Attachment, attachment_id)
    if att is None or att.entity_type != "maintenance" or att.entity_id != str(maintenance_id):
        raise HTTPException(status_code=404, detail="Attachment not found.")
    path = attachment_dir(att.entity_type, att.entity_id) / att.stored_filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File missing on disk.")
    return FileResponse(path, filename=att.original_filename, media_type=att.content_type or "application/octet-stream")


@router.post("/{maintenance_id}/attachments/{attachment_id}/delete", response_class=HTMLResponse)
async def maintenance_attachment_delete(
    request: Request,
    asset_id: int,
    maintenance_id: int,
    attachment_id: int,
    user: CurrentUser = Depends(require("maintenance.manage")),
    db: AsyncSession = Depends(get_db),
):
    att = await db.get(Attachment, attachment_id)
    if att is None or att.entity_type != "maintenance" or att.entity_id != str(maintenance_id):
        return _toast(request, False, "Attachment not found.")

    filename = att.original_filename
    path = attachment_dir(att.entity_type, att.entity_id) / att.stored_filename
    await db.delete(att)
    db.add(
        AuditLog(
            user_id=user.id, action="attachment_delete", entity_type="maintenance", entity_id=str(maintenance_id),
            detail=filename,
        )
    )
    await db.commit()
    path.unlink(missing_ok=True)
    return _refresh()
