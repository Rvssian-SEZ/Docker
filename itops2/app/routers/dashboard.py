"""Dashboard: the landing page. Read-only summary cards, each linking
into an already-existing list view's new query-string filter (assets/
contracts/inventory, all added in this same Phase 8 chunk). Cards are
gated by the same permission their linked page requires — a Viewer with
only contracts.view sees just the contracts card, not a wall of zeros
for pages they can't open.

Company scoping (company.scoped_users): the Asset/Contract counts here
are restricted to the CURRENT user's own company when the setting is on
AND the user has a company assigned — a company-less user (e.g. the
break-glass admin) sees everything regardless, since there's nothing to
scope to. This is dashboard-only for now: the Assets/Contracts list
pages themselves don't yet enforce company.scoped_users (a pre-existing
gap from Phase 4/5 that this phase wasn't asked to close — see
CLAUDE.md). Inventory has no company_id column at all, so it's never
scoped.
"""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, get_current_user
from app.core.dates import add_months
from app.core.db import get_db
from app.core.models import Asset, Checkout, Contract, InventoryItem, StatusLabel, StatusType
from app.core.scoping import company_scope as _company_scope
from app.core.settings_store import load_settings
from app.templating import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    store = await load_settings(db)
    scope_company_id = _company_scope(user, store)
    today = date.today()
    cards: dict = {}

    if user.can("assets.view"):
        status_q = (
            select(StatusLabel.status_type, func.count(Asset.id))
            .join(Asset, Asset.status_label_id == StatusLabel.id)
            .group_by(StatusLabel.status_type)
        )
        if scope_company_id is not None:
            status_q = status_q.where(Asset.company_id == scope_company_id)
        by_status = {st.value: 0 for st in StatusType}
        for status_type, count in (await db.execute(status_q)).all():
            by_status[status_type.value] = count
        cards["assets_by_status"] = by_status

        open_checkouts_q = select(Checkout.asset_id, Checkout.expected_checkin_at).where(
            Checkout.checked_in_at.is_(None), Checkout.expected_checkin_at.isnot(None)
        )
        if scope_company_id is not None:
            open_checkouts_q = open_checkouts_q.join(Asset, Asset.id == Checkout.asset_id).where(
                Asset.company_id == scope_company_id
            )
        expected_dates = [row[1] for row in (await db.execute(open_checkouts_q)).all()]
        window_end = today + timedelta(days=7)
        cards["checkouts_overdue"] = sum(1 for d in expected_dates if d < today)
        cards["checkouts_due_soon"] = sum(1 for d in expected_dates if today <= d <= window_end)

        warranty_q = select(Asset.purchase_date, Asset.warranty_months).where(
            Asset.purchase_date.isnot(None), Asset.warranty_months.isnot(None)
        )
        if scope_company_id is not None:
            warranty_q = warranty_q.where(Asset.company_id == scope_company_id)
        alert_days = store.get_int("warranty.alert_days")
        warranty_window_end = today + timedelta(days=alert_days)
        cards["warranty_expiring"] = sum(
            1
            for purchase_date, months in (await db.execute(warranty_q)).all()
            if today <= add_months(purchase_date, months) <= warranty_window_end
        )

    if user.can("contracts.view"):
        contracts_q = select(Contract.end_date)
        if scope_company_id is not None:
            contracts_q = contracts_q.where(Contract.company_id == scope_company_id)
        alert_days = store.get_int("contracts.renewal_alert_days")
        window_end = today + timedelta(days=alert_days)
        end_dates = (await db.execute(contracts_q)).scalars().all()
        cards["contracts_renewing"] = sum(1 for d in end_dates if today <= d <= window_end)

    if user.can("inventory.view"):
        rows = (
            await db.execute(
                select(InventoryItem.quantity, InventoryItem.min_quantity).where(
                    InventoryItem.min_quantity.isnot(None)
                )
            )
        ).all()
        cards["low_stock"] = sum(1 for qty, min_qty in rows if qty <= min_qty)

    return templates.TemplateResponse(request, "index.html", {"user": user, "cards": cards})
