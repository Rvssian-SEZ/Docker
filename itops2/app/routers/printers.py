"""Printers: a specialized VIEW over assets in the Printer category —
not a separate entity (per CLAUDE.md). "Is this asset a printer" is
determined by its model's category name (case-insensitive match on
"Printer"); the IP/hostname/consumable-notes values themselves live in
core_printer_details, a 1:1 extension table keyed by asset_id (see
CLAUDE.md for why this table exists instead of nullable columns on
core_assets or a generic key-value table).

Also owns the printer-details upsert route, even though it's invoked
from the asset detail page (not this page) — keeps every printer-
specific route in one file.
"""

from datetime import date as date_cls
from decimal import Decimal

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import CurrentUser, require
from app.core.db import get_db
from app.core.models import (
    Asset,
    AssetModel,
    AuditLog,
    Category,
    ExchangeRate,
    Location,
    Maintenance,
    PrinterDetails,
    StatusLabel,
)
from app.core.settings_store import load_settings
from app.templating import templates

router = APIRouter()


def _toast(request: Request, ok: bool, message: str):
    return templates.TemplateResponse(request, "partials/toast.html", {"ok": ok, "message": message})


async def _convert_to_default(
    db: AsyncSession, amount: Decimal, from_currency: str, as_of: date_cls, default_currency: str
) -> Decimal | None:
    """Nearest effective_date <= as_of for (from_currency -> default_currency),
    matching the same "historical value at the record's own date" rule used
    for asset purchase costs. Returns None if no applicable rate exists —
    the caller must surface that, not silently drop it from a total."""
    if from_currency == default_currency:
        return amount
    rate = (
        await db.execute(
            select(ExchangeRate.rate)
            .where(
                ExchangeRate.from_currency == from_currency,
                ExchangeRate.to_currency == default_currency,
                ExchangeRate.effective_date <= as_of,
            )
            .order_by(ExchangeRate.effective_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if rate is None:
        return None
    return amount * rate


async def _filter_bar_context(db: AsyncSession) -> dict:
    locations = (await db.execute(select(Location).order_by(Location.name))).scalars().all()
    status_labels = (await db.execute(select(StatusLabel).order_by(StatusLabel.name))).scalars().all()
    return {"filter_locations": locations, "filter_status_labels": status_labels}


@router.get("/printers", response_class=HTMLResponse)
async def printers_list(
    request: Request,
    location_id: str = "",
    status_label_id: str = "",
    q: str = "",
    user: CurrentUser = Depends(require("printers.view")),
    db: AsyncSession = Depends(get_db),
):
    """Filter bar (location, status, free-text over hostname/IP) — all
    applied in SQL. The free-text search is the one filter that needs a
    join beyond the base Printer-category query, since hostname/IP live
    on core_printer_details (a 1:1 extension, not every printer asset
    has a row yet — "created lazily on first save", per CLAUDE.md), not
    on core_assets itself."""
    store = await load_settings(db)
    default_currency = store.get("general.default_currency")

    query = (
        select(Asset)
        .join(AssetModel, Asset.model_id == AssetModel.id)
        .join(Category, AssetModel.category_id == Category.id)
        .where(func.lower(Category.name) == "printer")
        .options(
            selectinload(Asset.model).selectinload(AssetModel.manufacturer),
            selectinload(Asset.status_label),
            selectinload(Asset.location),
        )
    )
    if location_id.isdigit():
        query = query.where(Asset.location_id == int(location_id))
    if status_label_id.isdigit():
        query = query.where(Asset.status_label_id == int(status_label_id))
    if q.strip():
        term = f"%{q.strip()}%"
        query = query.outerjoin(PrinterDetails, PrinterDetails.asset_id == Asset.id).where(
            or_(PrinterDetails.hostname.ilike(term), PrinterDetails.ip_address.ilike(term))
        )

    query = query.order_by(Asset.asset_tag)
    printer_assets = (await db.execute(query)).scalars().unique().all()
    asset_ids = [a.id for a in printer_assets]

    printer_details_map = {}
    if asset_ids:
        rows = (
            await db.execute(select(PrinterDetails).where(PrinterDetails.asset_id.in_(asset_ids)))
        ).scalars().all()
        printer_details_map = {r.asset_id: r for r in rows}

    totals: dict[int, Decimal] = {}
    excluded: dict[int, int] = {}
    if asset_ids:
        records = (
            await db.execute(
                select(Maintenance).where(Maintenance.asset_id.in_(asset_ids), Maintenance.cost.isnot(None))
            )
        ).scalars().all()
        for m in records:
            converted = await _convert_to_default(db, m.cost, m.currency, m.date, default_currency)
            if converted is None:
                excluded[m.asset_id] = excluded.get(m.asset_id, 0) + 1
                continue
            totals[m.asset_id] = totals.get(m.asset_id, Decimal("0")) + converted

    printers = [
        {
            "asset": a,
            "details": printer_details_map.get(a.id),
            "maintenance_total": totals.get(a.id),
            "maintenance_excluded": excluded.get(a.id, 0),
        }
        for a in printer_assets
    ]

    ctx = {
        "user": user,
        "printers": printers,
        "default_currency": default_currency,
        "filter_active": bool(location_id or status_label_id or q.strip()),
        "location_id": location_id,
        "status_label_id": status_label_id,
        "q": q,
    }
    if request.headers.get("hx-request") == "true":
        return templates.TemplateResponse(request, "printers/_table.html", ctx)

    ctx.update(await _filter_bar_context(db))
    return templates.TemplateResponse(request, "printers/list.html", ctx)


@router.post("/assets/{asset_id}/printer-details/update", response_class=HTMLResponse)
async def printer_details_update(
    request: Request,
    asset_id: int,
    ip_address: str = Form(""),
    hostname: str = Form(""),
    consumable_notes: str = Form(""),
    user: CurrentUser = Depends(require("printers.manage")),
    db: AsyncSession = Depends(get_db),
):
    asset = await db.get(Asset, asset_id)
    if asset is None:
        return _toast(request, False, "Asset not found.")

    details = await db.get(PrinterDetails, asset_id)
    is_new = details is None
    if details is None:
        details = PrinterDetails(asset_id=asset_id)
        db.add(details)
    details.ip_address = ip_address.strip() or None
    details.hostname = hostname.strip() or None
    details.consumable_notes = consumable_notes.strip() or None

    db.add(
        AuditLog(
            user_id=user.id, action="create" if is_new else "update", entity_type="printer_details",
            entity_id=str(asset_id), detail=details.ip_address or "",
        )
    )
    await db.commit()
    return _toast(request, True, "Printer details saved.")
