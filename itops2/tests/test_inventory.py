"""Inventory: CRUD, the unit-cost-requires-currency validation, and
quantity adjustments -- delta+reason required, negative-result blocked,
each adjustment writes an audit row with the delta and reason.
"""

from sqlalchemy import select

from app.core.models import AuditLog, Category, InventoryItem


async def _make_category(db, name="Toner"):
    cat = Category(name=name)
    db.add(cat)
    await db.commit()
    return cat


async def test_create_inventory_item(admin_client, db):
    cat = await _make_category(db)
    resp = await admin_client.post(
        "/inventory/create",
        data={"name": "HP 26A Toner", "category_id": cat.id, "quantity": "10", "min_quantity": "3"},
    )
    assert resp.status_code == 204

    row = (await db.execute(select(InventoryItem).where(InventoryItem.name == "HP 26A Toner"))).scalar_one()
    assert row.quantity == 10
    assert row.min_quantity == 3


async def test_unit_cost_requires_currency(admin_client, db):
    cat = await _make_category(db)
    resp = await admin_client.post(
        "/inventory/create",
        data={"name": "Toner", "category_id": cat.id, "quantity": "5", "unit_cost": "12.50"},
    )
    assert "text-bg-danger" in resp.text
    assert "currency" in resp.text.lower()
    count = (await db.execute(select(InventoryItem.id))).all()
    assert count == []


async def test_update_does_not_touch_quantity(admin_client, db):
    cat = await _make_category(db)
    await admin_client.post(
        "/inventory/create", data={"name": "Toner", "category_id": cat.id, "quantity": "10"},
    )
    row = (await db.execute(select(InventoryItem))).scalar_one()

    resp = await admin_client.post(
        f"/inventory/{row.id}/update",
        data={"name": "Toner (renamed)", "category_id": cat.id, "min_quantity": "2"},
    )
    assert resp.status_code == 200
    assert "text-bg-success" in resp.text

    await db.refresh(row)
    assert row.name == "Toner (renamed)"
    assert row.min_quantity == 2
    assert row.quantity == 10  # untouched by /update


async def test_adjust_increases_quantity_and_writes_audit_row(admin_client, db):
    cat = await _make_category(db)
    await admin_client.post(
        "/inventory/create", data={"name": "Toner", "category_id": cat.id, "quantity": "10"},
    )
    row = (await db.execute(select(InventoryItem))).scalar_one()

    resp = await admin_client.post(
        f"/inventory/{row.id}/adjust", data={"delta": "5", "reason": "received shipment"},
    )
    assert resp.status_code == 204

    await db.refresh(row)
    assert row.quantity == 15

    audit = (
        await db.execute(
            select(AuditLog).where(AuditLog.entity_type == "inventory_item", AuditLog.action == "adjust")
        )
    ).scalar_one()
    assert "+5" in audit.detail
    assert "received shipment" in audit.detail
    assert "15" in audit.detail


async def test_adjust_decreases_quantity(admin_client, db):
    cat = await _make_category(db)
    await admin_client.post(
        "/inventory/create", data={"name": "Toner", "category_id": cat.id, "quantity": "10"},
    )
    row = (await db.execute(select(InventoryItem))).scalar_one()

    resp = await admin_client.post(
        f"/inventory/{row.id}/adjust", data={"delta": "-4", "reason": "used on IT-0012"},
    )
    assert resp.status_code == 204
    await db.refresh(row)
    assert row.quantity == 6


async def test_adjust_blocked_when_result_would_be_negative(admin_client, db):
    cat = await _make_category(db)
    await admin_client.post(
        "/inventory/create", data={"name": "Toner", "category_id": cat.id, "quantity": "3"},
    )
    row = (await db.execute(select(InventoryItem))).scalar_one()

    resp = await admin_client.post(
        f"/inventory/{row.id}/adjust", data={"delta": "-10", "reason": "oops"},
    )
    assert "text-bg-danger" in resp.text
    assert "negative" in resp.text.lower()
    await db.refresh(row)
    assert row.quantity == 3


async def test_adjust_requires_reason(admin_client, db):
    cat = await _make_category(db)
    await admin_client.post(
        "/inventory/create", data={"name": "Toner", "category_id": cat.id, "quantity": "10"},
    )
    row = (await db.execute(select(InventoryItem))).scalar_one()

    resp = await admin_client.post(f"/inventory/{row.id}/adjust", data={"delta": "5", "reason": ""})
    assert "text-bg-danger" in resp.text
    assert "reason" in resp.text.lower()
    await db.refresh(row)
    assert row.quantity == 10


async def test_adjust_requires_nonzero_delta(admin_client, db):
    cat = await _make_category(db)
    await admin_client.post(
        "/inventory/create", data={"name": "Toner", "category_id": cat.id, "quantity": "10"},
    )
    row = (await db.execute(select(InventoryItem))).scalar_one()

    resp = await admin_client.post(f"/inventory/{row.id}/adjust", data={"delta": "0", "reason": "no-op"})
    assert "text-bg-danger" in resp.text
    assert "non-zero" in resp.text.lower()


async def test_low_stock_flag_shown_on_list(admin_client, db):
    cat = await _make_category(db)
    await admin_client.post(
        "/inventory/create",
        data={"name": "Almost Out Toner", "category_id": cat.id, "quantity": "2", "min_quantity": "5"},
    )
    resp = await admin_client.get("/inventory")
    assert resp.status_code == 200
    assert "table-warning" in resp.text
    assert ">low<" in resp.text


async def test_delete_inventory_item(admin_client, db):
    cat = await _make_category(db)
    await admin_client.post(
        "/inventory/create", data={"name": "Toner", "category_id": cat.id, "quantity": "10"},
    )
    row = (await db.execute(select(InventoryItem))).scalar_one()

    resp = await admin_client.post(f"/inventory/{row.id}/delete")
    assert resp.status_code == 204
    assert (await db.execute(select(InventoryItem).where(InventoryItem.id == row.id))).scalar_one_or_none() is None
