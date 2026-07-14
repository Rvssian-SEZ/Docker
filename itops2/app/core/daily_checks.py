"""The three scheduled-check event types (warranty, contract renewal,
low stock) — run once a day by the in-app scheduler in app/main.py.

Each check batches every matching row into ONE digest email per event
type (not one email per asset/contract/item): a daily reminder that
lists everything at once is more useful than a dozen separate emails,
and it means notify_event() -- and therefore SMTP -- is only invoked
when there's actually something to report (nothing matching = no send
at all, not an empty digest).

Idempotency for "no duplicate warnings on restart" is the scheduler
loop's job (app/main.py tracks notifications.last_daily_run), not this
module's -- run_daily_checks() itself is safe to call more than once a
day; it would just re-send the same digest.
"""

from datetime import date, timedelta

from sqlalchemy import select

from app.core.dates import add_months
from app.core.db import SessionLocal
from app.core.models import Asset, Contract, InventoryItem, NotificationEvent
from app.core.notifications import notify_event
from app.core.settings_store import load_settings, save_setting


async def _check_warranty_expiring() -> None:
    async with SessionLocal() as db:
        store = await load_settings(db)
        alert_days = store.get_int("warranty.alert_days")
        assets = (
            (
                await db.execute(
                    select(Asset).where(Asset.purchase_date.isnot(None), Asset.warranty_months.isnot(None))
                )
            )
            .scalars()
            .all()
        )

    today = date.today()
    window_end = today + timedelta(days=alert_days)
    expiring = sorted(
        (
            (a.asset_tag, add_months(a.purchase_date, a.warranty_months))
            for a in assets
        ),
        key=lambda pair: pair[1],
    )
    expiring = [(tag, expiry) for tag, expiry in expiring if today <= expiry <= window_end]
    if not expiring:
        return

    lines = [f"- {tag}: warranty expires {expiry.isoformat()}" for tag, expiry in expiring]
    body = "The following assets have warranties expiring soon:\n\n" + "\n".join(lines)
    await notify_event(
        NotificationEvent.warranty_expiring.value,
        f"{len(expiring)} asset warranty(ies) expiring soon",
        body,
    )


async def _check_contract_renewals() -> None:
    async with SessionLocal() as db:
        store = await load_settings(db)
        alert_days = store.get_int("contracts.renewal_alert_days")
        contracts = (await db.execute(select(Contract))).scalars().all()

    today = date.today()
    window_end = today + timedelta(days=alert_days)
    # Mirrors contracts.py's _renewal_state "expiring_soon" bucket exactly
    # (>= today, i.e. not yet expired; <= today + alert_days).
    due = sorted(
        ((c.name, c.end_date) for c in contracts if today <= c.end_date <= window_end),
        key=lambda pair: pair[1],
    )
    if not due:
        return

    lines = [f"- {name}: renews/expires {end.isoformat()}" for name, end in due]
    body = "The following contracts are due for renewal soon:\n\n" + "\n".join(lines)
    await notify_event(
        NotificationEvent.contract_renewal_due.value,
        f"{len(due)} contract(s) due for renewal soon",
        body,
    )


async def _check_low_stock() -> None:
    async with SessionLocal() as db:
        items = (
            (
                await db.execute(
                    select(InventoryItem).where(InventoryItem.min_quantity.isnot(None))
                )
            )
            .scalars()
            .all()
        )

    # Matches inventory/list.html's low-stock badge condition exactly.
    low = sorted(
        ((i.name, i.quantity, i.min_quantity) for i in items if i.quantity <= i.min_quantity),
        key=lambda row: row[0],
    )
    if not low:
        return

    lines = [f"- {name}: {qty} in stock (minimum {min_qty})" for name, qty, min_qty in low]
    body = "The following inventory items are at or below their minimum quantity:\n\n" + "\n".join(lines)
    await notify_event(
        NotificationEvent.inventory_low_stock.value,
        f"{len(low)} inventory item(s) low on stock",
        body,
    )


async def run_daily_checks() -> None:
    await _check_warranty_expiring()
    await _check_contract_renewals()
    await _check_low_stock()


async def run_if_due() -> bool:
    """Idempotency gate for the "no duplicate warnings on restart"
    requirement: runs the checks and advances the persisted date marker
    only if they haven't already run today, returning whether they ran.
    Pulled out of the scheduler loop (app/main.py) as its own function
    so it's directly testable without needing to drive an infinite
    sleep loop — call it twice in a row to prove idempotency, the same
    as two ticks straddling a container restart would look."""
    async with SessionLocal() as db:
        store = await load_settings(db)
        today = date.today().isoformat()
        if store.get("notifications.last_daily_run") == today:
            return False
        await run_daily_checks()
        await save_setting(db, "notifications.last_daily_run", today)
        await db.commit()
        return True
