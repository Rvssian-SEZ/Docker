"""Inventory list filter bar (category, location, low-stock-only
toggle, name search) — SQL-side filtering.
"""

from app.core.models import Category, InventoryItem, Location


async def test_filter_by_category(admin_client, db):
    cat_a = Category(name="Toner")
    cat_b = Category(name="Cables")
    db.add_all([cat_a, cat_b])
    await db.commit()
    db.add_all(
        [
            InventoryItem(name="Toner Item", category_id=cat_a.id, quantity=10),
            InventoryItem(name="Cable Item", category_id=cat_b.id, quantity=10),
        ]
    )
    await db.commit()

    resp = await admin_client.get(f"/inventory?category_id={cat_a.id}")
    assert "Toner Item" in resp.text
    assert "Cable Item" not in resp.text


async def test_filter_by_location(admin_client, db):
    cat = Category(name="Consumables")
    loc_a = Location(name="HQ")
    loc_b = Location(name="Branch")
    db.add_all([cat, loc_a, loc_b])
    await db.commit()
    db.add_all(
        [
            InventoryItem(name="At HQ", category_id=cat.id, location_id=loc_a.id, quantity=10),
            InventoryItem(name="At Branch", category_id=cat.id, location_id=loc_b.id, quantity=10),
        ]
    )
    await db.commit()

    resp = await admin_client.get(f"/inventory?location_id={loc_a.id}")
    assert "At HQ" in resp.text
    assert "At Branch" not in resp.text


async def test_filter_by_low_stock_toggle(admin_client, db):
    cat = Category(name="Consumables2")
    db.add(cat)
    await db.commit()
    db.add_all(
        [
            InventoryItem(name="Low Item", category_id=cat.id, quantity=1, min_quantity=5),
            InventoryItem(name="Fine Item", category_id=cat.id, quantity=50, min_quantity=5),
        ]
    )
    await db.commit()

    resp = await admin_client.get("/inventory?low_stock=1")
    assert "Low Item" in resp.text
    assert "Fine Item" not in resp.text


async def test_filter_by_name_search(admin_client, db):
    cat = Category(name="Consumables3")
    db.add(cat)
    await db.commit()
    db.add_all(
        [
            InventoryItem(name="HDMI Cable", category_id=cat.id, quantity=10),
            InventoryItem(name="USB Cable", category_id=cat.id, quantity=10),
        ]
    )
    await db.commit()

    resp = await admin_client.get("/inventory?q=HDMI")
    assert "HDMI Cable" in resp.text
    assert "USB Cable" not in resp.text


async def test_combined_category_and_low_stock(admin_client, db):
    cat_a = Category(name="CatCombo")
    cat_b = Category(name="OtherCombo")
    db.add_all([cat_a, cat_b])
    await db.commit()
    db.add_all(
        [
            InventoryItem(name="Match Low", category_id=cat_a.id, quantity=1, min_quantity=5),
            InventoryItem(name="Wrong Cat Low", category_id=cat_b.id, quantity=1, min_quantity=5),
            InventoryItem(name="Right Cat Fine", category_id=cat_a.id, quantity=50, min_quantity=5),
        ]
    )
    await db.commit()

    resp = await admin_client.get(f"/inventory?category_id={cat_a.id}&low_stock=1")
    assert "Match Low" in resp.text
    assert "Wrong Cat Low" not in resp.text
    assert "Right Cat Fine" not in resp.text


async def test_inventory_htmx_request_returns_table_partial_only(admin_client, db):
    cat = Category(name="ConsumablesPartial")
    db.add(cat)
    await db.commit()
    db.add(InventoryItem(name="Partial Item", category_id=cat.id, quantity=1))
    await db.commit()

    resp = await admin_client.get("/inventory", headers={"HX-Request": "true"})
    assert resp.status_code == 200
    assert 'id="inventory-table"' in resp.text
    assert "<nav" not in resp.text
    assert "Partial Item" in resp.text


async def test_inventory_no_filters_behaves_like_before(admin_client, db):
    cat = Category(name="ConsumablesPlain")
    db.add(cat)
    await db.commit()
    db.add(InventoryItem(name="Plain Item", category_id=cat.id, quantity=1))
    await db.commit()

    resp = await admin_client.get("/inventory")
    assert resp.status_code == 200
    assert "Plain Item" in resp.text
    assert "bi-funnel" not in resp.text


async def test_dashboard_low_stock_deep_link_still_works(admin_client, db):
    cat = Category(name="ConsumablesDeepLink")
    db.add(cat)
    await db.commit()
    db.add(InventoryItem(name="Deep Link Low", category_id=cat.id, quantity=1, min_quantity=5))
    await db.commit()

    resp = await admin_client.get("/inventory?low_stock=1")
    assert "Deep Link Low" in resp.text
