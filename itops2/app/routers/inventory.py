"""Inventory: quantity-tracked consumables/spares sharing the Catalog
category tree. Quantity only ever changes via the /adjust action (a
+/- delta with a required reason, written to core_audit_log) — never
directly editable through the general edit form, so every change to
stock level has an auditable reason attached. min_quantity (optional)
drives a low-stock visual flag on the list.
"""

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import CurrentUser, require
from app.core.db import get_db
from app.core.models import AuditLog, Category, Currency, InventoryItem, Location
from app.core.settings_store import load_settings
from app.templating import templates

router = APIRouter(prefix="/inventory")


def _toast(request: Request, ok: bool, message: str):
    return templates.TemplateResponse(request, "partials/toast.html", {"ok": ok, "message": message})


def _refresh():
    return Response(status_code=204, headers={"HX-Refresh": "true"})


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
    if not value.lstrip("-").isdigit():
        return None, f"{field} must be a whole number."
    val = int(value)
    if val < 0:
        return None, f"{field} must not be negative."
    return val, None


def _parse_signed_int(value: str):
    value = (value or "").strip()
    if not value:
        return None, "Adjustment amount is required."
    try:
        return int(value), None
    except ValueError:
        return None, "Adjustment must be a whole number."


async def _form_context(db: AsyncSession) -> dict:
    store = await load_settings(db)
    categories = (await db.execute(select(Category).order_by(Category.name))).scalars().all()
    locations = (await db.execute(select(Location).order_by(Location.name))).scalars().all()
    currencies = (
        await db.execute(select(Currency).where(Currency.active.is_(True)).order_by(Currency.code))
    ).scalars().all()
    return {
        "categories": categories,
        "locations": locations,
        "currencies": currencies,
        "default_currency": store.get("general.default_currency"),
    }


async def _validate_unit_cost(db: AsyncSession, unit_cost: str, currency: str):
    """Returns (cost_val, currency_val, error)."""
    cost_val, err = _parse_optional_decimal(unit_cost, "Unit cost")
    if err:
        return None, None, err
    currency_val = currency.strip().upper() or None
    if currency_val is not None and await db.get(Currency, currency_val) is None:
        return None, None, "Unknown currency."
    if cost_val is not None and currency_val is None:
        return None, None, "Pick a currency for the unit cost."
    return cost_val, currency_val, None


# ---- list ----

@router.get("", response_class=HTMLResponse)
async def inventory_list(
    request: Request,
    category_id: str = "",
    location_id: str = "",
    low_stock: str = "",
    q: str = "",
    user: CurrentUser = Depends(require("inventory.view")),
    db: AsyncSession = Depends(get_db),
):
    """Filter bar: category, location, low-stock-only toggle, name
    search — all in SQL. low_stock=1 predates the filter bar (the
    Dashboard's card already linked to it in Phase 8) and keeps the same
    meaning: at or below min_quantity, same condition as the list's own
    low-stock badge."""
    query = select(InventoryItem).options(
        selectinload(InventoryItem.category), selectinload(InventoryItem.location)
    )
    if category_id.isdigit():
        query = query.where(InventoryItem.category_id == int(category_id))
    if location_id.isdigit():
        query = query.where(InventoryItem.location_id == int(location_id))
    if low_stock == "1":
        query = query.where(
            InventoryItem.min_quantity.isnot(None), InventoryItem.quantity <= InventoryItem.min_quantity
        )
    if q.strip():
        query = query.where(InventoryItem.name.ilike(f"%{q.strip()}%"))

    query = query.order_by(InventoryItem.name)
    items = (await db.execute(query)).scalars().unique().all()

    ctx = {
        "user": user,
        "items": items,
        "can_manage": user.can("inventory.manage"),
        "filter_active": bool(category_id or location_id or low_stock == "1" or q.strip()),
        "category_id": category_id,
        "location_id": location_id,
        "low_stock": low_stock,
        "q": q,
    }
    if request.headers.get("hx-request") == "true":
        return templates.TemplateResponse(request, "inventory/_table.html", ctx)

    ctx.update(await _form_context(db))
    return templates.TemplateResponse(request, "inventory/list.html", ctx)


# ---- create ----

@router.post("/create", response_class=HTMLResponse)
async def inventory_create(
    request: Request,
    name: str = Form(""),
    category_id: str = Form(""),
    location_id: str = Form(""),
    quantity: str = Form("0"),
    min_quantity: str = Form(""),
    unit_cost: str = Form(""),
    currency: str = Form(""),
    notes: str = Form(""),
    user: CurrentUser = Depends(require("inventory.manage")),
    db: AsyncSession = Depends(get_db),
):
    if not name.strip():
        return _toast(request, False, "Name is required.")
    if not category_id.isdigit() or await db.get(Category, int(category_id)) is None:
        return _toast(request, False, "Unknown category.")
    location_id_val = int(location_id) if location_id.isdigit() else None
    if location_id_val is not None and await db.get(Location, location_id_val) is None:
        return _toast(request, False, "Unknown location.")
    qty, err = _parse_optional_int(quantity, "Quantity")
    if err:
        return _toast(request, False, err)
    qty = qty or 0
    min_qty, err = _parse_optional_int(min_quantity, "Minimum quantity")
    if err:
        return _toast(request, False, err)
    cost_val, currency_val, err = await _validate_unit_cost(db, unit_cost, currency)
    if err:
        return _toast(request, False, err)

    row = InventoryItem(
        name=name.strip(), category_id=int(category_id), location_id=location_id_val,
        quantity=qty, min_quantity=min_qty, unit_cost=cost_val, currency=currency_val,
        notes=notes.strip() or None,
    )
    db.add(row)
    await db.flush()
    db.add(
        AuditLog(
            user_id=user.id, action="create", entity_type="inventory_item", entity_id=str(row.id), detail=row.name,
        )
    )
    await db.commit()
    return _refresh()


# ---- update ----

@router.post("/{item_id}/update", response_class=HTMLResponse)
async def inventory_update(
    request: Request,
    item_id: int,
    name: str = Form(""),
    category_id: str = Form(""),
    location_id: str = Form(""),
    min_quantity: str = Form(""),
    unit_cost: str = Form(""),
    currency: str = Form(""),
    notes: str = Form(""),
    user: CurrentUser = Depends(require("inventory.manage")),
    db: AsyncSession = Depends(get_db),
):
    item = await db.get(InventoryItem, item_id)
    if item is None:
        return _toast(request, False, "Not found.")
    if not name.strip():
        return _toast(request, False, "Name is required.")
    if not category_id.isdigit() or await db.get(Category, int(category_id)) is None:
        return _toast(request, False, "Unknown category.")
    location_id_val = int(location_id) if location_id.isdigit() else None
    if location_id_val is not None and await db.get(Location, location_id_val) is None:
        return _toast(request, False, "Unknown location.")
    min_qty, err = _parse_optional_int(min_quantity, "Minimum quantity")
    if err:
        return _toast(request, False, err)
    cost_val, currency_val, err = await _validate_unit_cost(db, unit_cost, currency)
    if err:
        return _toast(request, False, err)

    item.name = name.strip()
    item.category_id = int(category_id)
    item.location_id = location_id_val
    item.min_quantity = min_qty
    item.unit_cost = cost_val
    item.currency = currency_val
    item.notes = notes.strip() or None

    db.add(
        AuditLog(user_id=user.id, action="update", entity_type="inventory_item", entity_id=str(item_id), detail=item.name)
    )
    await db.commit()
    return _toast(request, True, "Saved.")


@router.post("/{item_id}/delete", response_class=HTMLResponse)
async def inventory_delete(
    request: Request,
    item_id: int,
    user: CurrentUser = Depends(require("inventory.manage")),
    db: AsyncSession = Depends(get_db),
):
    item = await db.get(InventoryItem, item_id)
    if item is None:
        return _toast(request, False, "Not found.")
    name = item.name
    await db.delete(item)
    db.add(AuditLog(user_id=user.id, action="delete", entity_type="inventory_item", entity_id=str(item_id), detail=name))
    await db.commit()
    return _refresh()


# ---- quantity adjustment ----

@router.post("/{item_id}/adjust", response_class=HTMLResponse)
async def inventory_adjust(
    request: Request,
    item_id: int,
    delta: str = Form(""),
    reason: str = Form(""),
    user: CurrentUser = Depends(require("inventory.manage")),
    db: AsyncSession = Depends(get_db),
):
    item = await db.get(InventoryItem, item_id)
    if item is None:
        return _toast(request, False, "Not found.")
    delta_val, err = _parse_signed_int(delta)
    if err:
        return _toast(request, False, err)
    if delta_val == 0:
        return _toast(request, False, "Adjustment must be non-zero.")
    if not reason.strip():
        return _toast(request, False, "A reason is required.")
    new_qty = item.quantity + delta_val
    if new_qty < 0:
        return _toast(request, False, f"Cannot adjust: would go negative (current {item.quantity}).")

    item.quantity = new_qty
    db.add(
        AuditLog(
            user_id=user.id, action="adjust", entity_type="inventory_item", entity_id=str(item_id),
            detail=f"{delta_val:+d} ({reason.strip()}) -> {new_qty}",
        )
    )
    await db.commit()
    return _refresh()
