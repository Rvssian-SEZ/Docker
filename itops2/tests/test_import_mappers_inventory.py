"""app/core/import_mappers/inventory.py -- v1 inventory_items ->
core_inventory_items, and stock_receipts + inventory_deployments
replayed as core_inventory_adjustments in true chronological order."""

from datetime import datetime, timezone

from sqlalchemy import select

from app.core.import_mappers.inventory import import_inventory_items, import_inventory_movements
from app.core.models import Category, ImportRowOutcome, InventoryAdjustment, InventoryItem, Location, V1ImportRow
from app.core.settings_store import load_settings
from tests.conftest import FakeV1Source, make_import_batch

ITEM_ROW = {
    "id": 1, "name": "Kingston 16GB DDR4", "category": "ram", "location": "Server Room",
    "shelf_life_months": 24, "notes": "static-sensitive", "opening_stock": 10,
}


async def test_creates_item_with_category_synthesis_and_opening_stock(db):
    batch = await make_import_batch(db)
    store = await load_settings(db)
    await import_inventory_items(db, FakeV1Source({"FROM inventory_items": [ITEM_ROW]}), batch, store)
    await db.commit()

    cat = (await db.execute(select(Category).where(Category.name == "RAM"))).scalar_one()
    loc = (await db.execute(select(Location).where(Location.name == "Server Room"))).scalar_one()
    item = (await db.execute(select(InventoryItem).where(InventoryItem.name == "Kingston 16GB DDR4"))).scalar_one()
    assert item.category_id == cat.id
    assert item.location_id == loc.id
    assert item.quantity == 10
    assert "static-sensitive" in item.notes
    assert "24 months" in item.notes


async def test_items_dry_run_writes_no_target_rows(db):
    batch = await make_import_batch(db, dry_run=True)
    store = await load_settings(db)
    await import_inventory_items(db, FakeV1Source({"FROM inventory_items": [ITEM_ROW]}), batch, store)
    await db.commit()

    assert (await db.execute(select(InventoryItem))).scalar_one_or_none() is None


async def test_movements_replay_in_chronological_order_not_insertion_order(db):
    batch = await make_import_batch(db)
    store = await load_settings(db)
    await import_inventory_items(db, FakeV1Source({"FROM inventory_items": [ITEM_ROW]}), batch, store)
    await db.flush()
    item = (await db.execute(select(InventoryItem).where(InventoryItem.name == "Kingston 16GB DDR4"))).scalar_one()

    # Inserted out of chronological order on purpose: the later-dated
    # receipt appears FIRST in the source rows, the earlier-dated
    # deployment SECOND -- the mapper must still replay by timestamp.
    receipts = [{"id": 1, "item_id": 1, "quantity": 5, "received_at": datetime(2025, 2, 1, tzinfo=timezone.utc), "notes": None}]
    deployments = [
        {
            "id": 1, "item_id": 1, "asset_id": 42, "quantity": 3,
            "deployed_at": datetime(2025, 1, 1, tzinfo=timezone.utc), "returned_at": None,
            "is_retired": False, "notes": None,
        }
    ]
    source = FakeV1Source({"FROM stock_receipts": receipts, "FROM inventory_deployments": deployments})
    await import_inventory_movements(db, source, batch)
    await db.commit()

    adjustments = (
        await db.execute(select(InventoryAdjustment).where(InventoryAdjustment.item_id == item.id).order_by(InventoryAdjustment.adjusted_at))
    ).scalars().all()
    assert len(adjustments) == 2
    # opening stock 10 -> deploy -3 (Jan) -> 7 -> receipt +5 (Feb) -> 12
    assert adjustments[0].delta == -3
    assert adjustments[0].quantity_after == 7
    assert adjustments[1].delta == 5
    assert adjustments[1].quantity_after == 12

    await db.refresh(item)
    assert item.quantity == 12


async def test_returned_deployment_creates_two_adjustments_with_distinct_tracking(db):
    batch = await make_import_batch(db)
    store = await load_settings(db)
    await import_inventory_items(db, FakeV1Source({"FROM inventory_items": [ITEM_ROW]}), batch, store)
    await db.flush()
    item = (await db.execute(select(InventoryItem).where(InventoryItem.name == "Kingston 16GB DDR4"))).scalar_one()

    deployments = [
        {
            "id": 2, "item_id": 1, "asset_id": 7, "quantity": 2,
            "deployed_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
            "returned_at": datetime(2025, 1, 15, tzinfo=timezone.utc), "is_retired": False, "notes": None,
        }
    ]
    source = FakeV1Source({"FROM stock_receipts": [], "FROM inventory_deployments": deployments})
    await import_inventory_movements(db, source, batch)
    await db.commit()

    adjustments = (
        await db.execute(select(InventoryAdjustment).where(InventoryAdjustment.item_id == item.id).order_by(InventoryAdjustment.adjusted_at))
    ).scalars().all()
    assert len(adjustments) == 2
    assert adjustments[0].delta == -2  # deploy
    assert adjustments[1].delta == 2   # return
    await db.refresh(item)
    assert item.quantity == 10  # net zero after full return

    rows = (
        await db.execute(select(V1ImportRow).where(V1ImportRow.v1_id == 2, V1ImportRow.v2_entity_type == "inventory_adjustment"))
    ).scalars().all()
    assert {r.v1_table for r in rows} == {"inventory_deployments", "inventory_deployments_return"}


async def test_retired_deployment_never_returns_stock(db):
    batch = await make_import_batch(db)
    store = await load_settings(db)
    await import_inventory_items(db, FakeV1Source({"FROM inventory_items": [ITEM_ROW]}), batch, store)
    await db.flush()
    item = (await db.execute(select(InventoryItem).where(InventoryItem.name == "Kingston 16GB DDR4"))).scalar_one()

    deployments = [
        {
            "id": 3, "item_id": 1, "asset_id": 8, "quantity": 4,
            "deployed_at": datetime(2025, 1, 1, tzinfo=timezone.utc), "returned_at": None,
            "is_retired": True, "notes": None,
        }
    ]
    source = FakeV1Source({"FROM stock_receipts": [], "FROM inventory_deployments": deployments})
    await import_inventory_movements(db, source, batch)
    await db.commit()

    adjustments = (
        await db.execute(select(InventoryAdjustment).where(InventoryAdjustment.item_id == item.id))
    ).scalars().all()
    assert len(adjustments) == 1
    assert adjustments[0].delta == -4
    await db.refresh(item)
    assert item.quantity == 6


async def test_movements_for_unimported_item_are_flagged(db):
    batch = await make_import_batch(db)
    receipts = [{"id": 5, "item_id": 999, "quantity": 1, "received_at": None, "notes": None}]
    source = FakeV1Source({"FROM stock_receipts": receipts, "FROM inventory_deployments": []})
    await import_inventory_movements(db, source, batch)
    await db.commit()

    import_row = (
        await db.execute(select(V1ImportRow).where(V1ImportRow.v1_table == "stock_receipts", V1ImportRow.v1_id == 5))
    ).scalar_one()
    assert import_row.outcome == ImportRowOutcome.flagged
    assert "inventory_items module first" in import_row.detail


async def test_movements_dry_run_writes_no_adjustments(db):
    batch = await make_import_batch(db)
    store = await load_settings(db)
    await import_inventory_items(db, FakeV1Source({"FROM inventory_items": [ITEM_ROW]}), batch, store)
    await db.flush()
    item = (await db.execute(select(InventoryItem).where(InventoryItem.name == "Kingston 16GB DDR4"))).scalar_one()

    dry_batch = await make_import_batch(db, dry_run=True)
    receipts = [{"id": 6, "item_id": 1, "quantity": 5, "received_at": datetime(2025, 1, 1, tzinfo=timezone.utc), "notes": None}]
    source = FakeV1Source({"FROM stock_receipts": receipts, "FROM inventory_deployments": []})
    await import_inventory_movements(db, source, dry_batch)
    await db.commit()

    assert (await db.execute(select(InventoryAdjustment))).scalar_one_or_none() is None
    await db.refresh(item)
    assert item.quantity == 10  # unchanged
