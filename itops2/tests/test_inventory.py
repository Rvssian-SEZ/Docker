"""Inventory: CRUD, the unit-cost-requires-currency validation, and
quantity adjustments -- delta+reason required, negative-result blocked,
each adjustment writes both an audit row (who-did-what) and a
core_inventory_adjustments ledger row (the queryable history), plus the
per-item history view and the delete-blocked-by-history guard.
"""

from sqlalchemy import select

from app.core.models import AuditLog, AuthSource, Category, InventoryAdjustment, InventoryItem, Role, RoleName, User
from app.core.security import hash_password


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


async def test_adjust_writes_ledger_row_not_just_audit_string(admin_client, db):
    """The core_inventory_adjustments ledger (added post-Phase-8) exists
    specifically so the history view never has to parse the audit log's
    formatted detail string -- resulting quantity is a real column, not
    something extracted from '+5 (reason) -> 15'."""
    cat = await _make_category(db)
    await admin_client.post(
        "/inventory/create", data={"name": "Toner", "category_id": cat.id, "quantity": "10"},
    )
    row = (await db.execute(select(InventoryItem))).scalar_one()
    admin_id = (await db.execute(select(User.id).where(User.is_breakglass.is_(True)))).scalar_one()

    resp = await admin_client.post(
        f"/inventory/{row.id}/adjust", data={"delta": "5", "reason": "received shipment"},
    )
    assert resp.status_code == 204

    ledger_row = (
        await db.execute(select(InventoryAdjustment).where(InventoryAdjustment.item_id == row.id))
    ).scalar_one()
    assert ledger_row.delta == 5
    assert ledger_row.quantity_after == 15
    assert ledger_row.reason == "received shipment"
    assert ledger_row.adjusted_by == admin_id

    # The audit row still exists too -- the ledger is additive, not a replacement.
    audit = (
        await db.execute(
            select(AuditLog).where(AuditLog.entity_type == "inventory_item", AuditLog.action == "adjust")
        )
    ).scalar_one()
    assert audit is not None


async def test_history_view_shows_adjustments_newest_first(admin_client, db):
    cat = await _make_category(db)
    await admin_client.post(
        "/inventory/create", data={"name": "Toner", "category_id": cat.id, "quantity": "10"},
    )
    row = (await db.execute(select(InventoryItem))).scalar_one()

    await admin_client.post(f"/inventory/{row.id}/adjust", data={"delta": "5", "reason": "first adjustment"})
    await admin_client.post(f"/inventory/{row.id}/adjust", data={"delta": "-2", "reason": "second adjustment"})

    resp = await admin_client.get(f"/inventory/{row.id}/history")
    assert resp.status_code == 200
    assert "first adjustment" in resp.text
    assert "second adjustment" in resp.text
    # newest (second) adjustment must appear before the first in the HTML
    assert resp.text.index("second adjustment") < resp.text.index("first adjustment")
    assert "13" in resp.text  # resulting quantity after the second adjustment


async def test_history_view_accessible_to_view_only_user(client, db, settings):
    """Viewing history is a read operation (inventory.view), not gated
    behind inventory.manage -- a Technician/Viewer should be able to see
    what happened to an item even if they can't change it."""
    cat = await _make_category(db)
    item = InventoryItem(name="Toner", category_id=cat.id, quantity=10)
    db.add(item)
    await db.flush()
    admin_id = (await db.execute(select(User.id).where(User.is_breakglass.is_(True)))).scalar_one()
    db.add(InventoryAdjustment(item_id=item.id, delta=5, quantity_after=15, reason="restock", adjusted_by=admin_id))
    await db.commit()

    viewer_role = (await db.execute(select(Role).where(Role.name == RoleName.viewer))).scalar_one()
    db.add(
        User(
            username="inv-viewer", display_name="Inv Viewer", auth_source=AuthSource.local,
            password_hash=hash_password("supersecret123"), role_id=viewer_role.id, is_active=True,
        )
    )
    await db.commit()
    login = await client.post("/login", data={"username": "inv-viewer", "password": "supersecret123"})
    assert login.status_code == 302

    resp = await client.get(f"/inventory/{item.id}/history")
    assert resp.status_code == 200
    assert "restock" in resp.text


async def test_delete_blocked_when_adjustment_history_exists(admin_client, db):
    """Once an item has real adjustment history, that's data worth
    keeping -- same reasoning that already blocks hard-deleting an Asset
    with checkout history. Inventory has no archive concept, so this is
    a firm block, not an "archive instead" redirect."""
    cat = await _make_category(db)
    await admin_client.post(
        "/inventory/create", data={"name": "Toner", "category_id": cat.id, "quantity": "10"},
    )
    row = (await db.execute(select(InventoryItem))).scalar_one()
    await admin_client.post(f"/inventory/{row.id}/adjust", data={"delta": "5", "reason": "restock"})

    resp = await admin_client.post(f"/inventory/{row.id}/delete")
    assert "text-bg-danger" in resp.text
    assert "adjustment" in resp.text.lower()
    assert (await db.execute(select(InventoryItem).where(InventoryItem.id == row.id))).scalar_one_or_none() is not None
