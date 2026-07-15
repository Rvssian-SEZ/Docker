"""Maps v1 `inventory_items` to core_inventory_items, and replays
`stock_receipts` + `inventory_deployments` as core_inventory_adjustments
-- the FULL movement history, not just a final quantity snapshot.

v1's inventory_items.opening_stock becomes the v2 item's starting
quantity; import_inventory_movements() then replays every stock
receipt (+delta) and deployment (-delta, and +delta again on return)
in true chronological order across BOTH source tables, computing each
step's quantity_after explicitly -- InventoryAdjustment's own
docstring is clear that quantity_after is "stored explicitly rather
than derived", so a lossy per-table replay that ignores interleaving
would produce wrong running totals the moment a receipt and a
deployment for the same item happened out of insertion order. A
deployment that was returned (returned_at IS NOT NULL) becomes TWO
adjustment rows -- the deploy and the return are each real, separate
inventory events; a deployment that was retired instead (is_retired,
never returned) correctly stays a single permanent deduction, since
"retired" means the stock is gone, not "back in inventory".

A returned deployment's deploy-event and return-event both derive from
the SAME v1 inventory_deployments row -- tracked under two distinct
v1_table namespaces ("inventory_deployments" for the deploy,
"inventory_deployments_return" for the return) so their V1ImportRow
tracking rows don't collide on the partial unique index the way a
similar single-source-row/two-target-writes case did in the
attachments mapper (see that module's own note on the same bug).

v1 has no cost field on inventory_items at all, and no min-stock
threshold either -- both stay NULL, no reasonable default to guess.
shelf_life_months has no v2 column (InventoryItem tracks none) --
folded into notes, the same "no target field, so surface it in the
one place a human will still see it" treatment given v1 printers'
department text and v1 contracts' vendor contact details.
"""

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.import_mappers.catalog import resolve_or_plan_category
from app.core.import_mappers.common import record_row, resolve_or_plan_location, v2_entity_id_for_v1_row
from app.core.models import ImportRowOutcome, InventoryAdjustment, InventoryItem, V1ImportBatch
from app.core.settings_store import SettingsStore

V1_INVENTORY_CATEGORY_NAMES = {
    "ram": "RAM", "ssd": "SSD", "nvme": "NVMe", "hdd": "HDD", "access_point": "Access Point",
    "network_switch": "Network Switch", "power_supply": "Power Supply", "server_parts": "Server Parts",
    "misc": "Misc",
}

_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


async def import_inventory_items(db: AsyncSession, source, batch: V1ImportBatch, store: SettingsStore) -> None:
    dry_run = batch.dry_run
    cat_cache: dict = {}
    loc_cache: dict = {}

    rows = await source.fetch(
        "SELECT id, name, category, location, shelf_life_months, notes, opening_stock "
        "FROM inventory_items ORDER BY id"
    )
    for row in rows:
        v1_category = (row["category"] or "misc").strip().lower()
        category_name = V1_INVENTORY_CATEGORY_NAMES.get(v1_category, (row["category"] or "Misc").strip().title())
        category_id, _ = await resolve_or_plan_category(db, cat_cache, category_name, dry_run)

        location_id = None
        if row["location"]:
            location_id, _ = await resolve_or_plan_location(db, loc_cache, row["location"], dry_run)

        notes_parts = [
            p for p in [row["notes"], f"shelf life: {row['shelf_life_months']} months" if row["shelf_life_months"] else None]
            if p
        ]
        notes = "; ".join(notes_parts) or None

        if dry_run:
            await record_row(
                db, batch, "inventory_items", row["id"], "inventory_item", None, ImportRowOutcome.created,
                f"would create inventory item '{row['name']}' (opening stock {row['opening_stock'] or 0})",
            )
            continue

        item = InventoryItem(
            name=row["name"],
            category_id=category_id,
            location_id=location_id,
            quantity=row["opening_stock"] or 0,
            notes=notes,
        )
        db.add(item)
        await db.flush()
        await record_row(
            db, batch, "inventory_items", row["id"], "inventory_item", item.id, ImportRowOutcome.created,
            f"created inventory item '{item.name}' (opening stock {item.quantity})",
        )


async def import_inventory_movements(db: AsyncSession, source, batch: V1ImportBatch) -> None:
    dry_run = batch.dry_run

    receipts = await source.fetch("SELECT id, item_id, quantity, received_at, notes FROM stock_receipts ORDER BY id")
    deployments = await source.fetch(
        "SELECT id, item_id, asset_id, quantity, deployed_at, returned_at, is_retired, notes "
        "FROM inventory_deployments ORDER BY id"
    )

    events_by_item: dict[int, list[dict]] = {}
    for r in receipts:
        reason = "v1 stock receipt" + (f": {r['notes']}" if r["notes"] else "")
        events_by_item.setdefault(r["item_id"], []).append(
            {"ts": r["received_at"], "delta": r["quantity"], "reason": reason, "v1_table": "stock_receipts", "v1_id": r["id"]}
        )
    for d in deployments:
        deploy_reason = f"v1 deployment to asset {d['asset_id']}" + (f": {d['notes']}" if d["notes"] else "")
        events_by_item.setdefault(d["item_id"], []).append(
            {
                "ts": d["deployed_at"], "delta": -d["quantity"], "reason": deploy_reason,
                "v1_table": "inventory_deployments", "v1_id": d["id"],
            }
        )
        if d["returned_at"] is not None:
            events_by_item.setdefault(d["item_id"], []).append(
                {
                    "ts": d["returned_at"], "delta": d["quantity"], "reason": f"v1 return from asset {d['asset_id']}",
                    "v1_table": "inventory_deployments_return", "v1_id": d["id"],
                }
            )

    for v1_item_id, events in events_by_item.items():
        item_id = await v2_entity_id_for_v1_row(db, "inventory_items", v1_item_id)
        if item_id is None:
            for ev in events:
                await record_row(
                    db, batch, ev["v1_table"], ev["v1_id"], "inventory_adjustment", None, ImportRowOutcome.flagged,
                    f"inventory item {v1_item_id} has no imported v2 item -- run the inventory_items module first",
                )
            continue

        events.sort(key=lambda e: e["ts"] or _EPOCH)

        if dry_run:
            for ev in events:
                await record_row(
                    db, batch, ev["v1_table"], ev["v1_id"], "inventory_adjustment", None, ImportRowOutcome.created,
                    f"would replay {ev['delta']:+d} ({ev['reason']})",
                )
            continue

        item = await db.get(InventoryItem, item_id)
        running = item.quantity
        for ev in events:
            running += ev["delta"]
            adjustment = InventoryAdjustment(
                item_id=item_id,
                delta=ev["delta"],
                quantity_after=running,
                reason=ev["reason"],
                adjusted_by=batch.started_by,
                adjusted_at=ev["ts"] or datetime.now(timezone.utc),
            )
            db.add(adjustment)
            await db.flush()
            item.quantity = running
            await record_row(
                db, batch, ev["v1_table"], ev["v1_id"], "inventory_adjustment", adjustment.id, ImportRowOutcome.created,
                f"replayed {ev['delta']:+d}, quantity now {running}",
            )
