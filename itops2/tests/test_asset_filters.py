"""The Assets list filter bar (SQL-side filtering, not load-then-filter
in Python) — status label, category, model, location, company,
checked-out state, and free-text search, individually and combined.
"""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.core.models import (
    Asset,
    AssetModel,
    Category,
    Checkout,
    Company,
    Location,
    Manufacturer,
    StatusLabel,
    StatusType,
    User,
)
from app.core.settings_store import save_setting


def _row(tag: str) -> str:
    """A table row's asset-tag link text, e.g. '>IT-SA</a>' — unlike a
    bare tag substring, this can't collide with the filter bar's own
    dropdown options (every status label/category/model/location/
    company is always listed there, and this test module's status
    label names deliberately embed the tag, e.g. "Status-IT-SA")."""
    return f">{tag}</a>"


async def _breakglass_id(db) -> int:
    return (await db.execute(select(User.id).where(User.is_breakglass.is_(True)))).scalar_one()


async def _make_asset(db, tag, *, mfr_name=None, category_name=None, model_name="Latitude 5440",
                       status_type=StatusType.deployable, location=None, company=None, serial=None,
                       category=None, model=None):
    if category is None:
        category = Category(name=category_name or f"Cat-{tag}")
        db.add(category)
        await db.flush()
    cat = category
    if model is None:
        mfr = Manufacturer(name=mfr_name or f"Mfr-{tag}")
        db.add(mfr)
        await db.flush()
        model = AssetModel(name=model_name, manufacturer_id=mfr.id, category_id=cat.id)
        db.add(model)
        await db.flush()
    status = StatusLabel(name=f"Status-{tag}", status_type=status_type)
    db.add(status)
    await db.flush()
    asset = Asset(
        asset_tag=tag, serial=serial, model_id=model.id, status_label_id=status.id,
        location_id=location.id if location else None,
        company_id=company.id if company else None,
    )
    db.add(asset)
    await db.commit()
    return asset, model, status, cat


async def test_filter_by_status_label_id(admin_client, db):
    asset_a, _, status_a, _ = await _make_asset(db, "IT-SA")
    asset_b, _, status_b, _ = await _make_asset(db, "IT-SB")

    resp = await admin_client.get(f"/assets?status_label_id={status_a.id}")
    assert _row("IT-SA") in resp.text
    assert _row("IT-SB") not in resp.text


async def test_filter_by_category_id(admin_client, db):
    asset_a, _, _, cat_a = await _make_asset(db, "IT-CATA", category_name="Laptops")
    asset_b, _, _, cat_b = await _make_asset(db, "IT-CATB", category_name="Monitors")

    resp = await admin_client.get(f"/assets?category_id={cat_a.id}")
    assert _row("IT-CATA") in resp.text
    assert _row("IT-CATB") not in resp.text


async def test_filter_by_model_id(admin_client, db):
    asset_a, model_a, _, _ = await _make_asset(db, "IT-MODA", model_name="Latitude")
    asset_b, model_b, _, _ = await _make_asset(db, "IT-MODB", model_name="ThinkPad")

    resp = await admin_client.get(f"/assets?model_id={model_a.id}")
    assert _row("IT-MODA") in resp.text
    assert _row("IT-MODB") not in resp.text


async def test_filter_by_location_id(admin_client, db):
    loc_a = Location(name="HQ")
    loc_b = Location(name="Branch")
    db.add_all([loc_a, loc_b])
    await db.commit()
    await _make_asset(db, "IT-LOCA", location=loc_a)
    await _make_asset(db, "IT-LOCB", location=loc_b)

    resp = await admin_client.get(f"/assets?location_id={loc_a.id}")
    assert _row("IT-LOCA") in resp.text
    assert _row("IT-LOCB") not in resp.text


async def test_filter_by_company_id(admin_client, db):
    co_a = Company(name="Acme")
    co_b = Company(name="Globex")
    db.add_all([co_a, co_b])
    await db.commit()
    await _make_asset(db, "IT-COA", company=co_a)
    await _make_asset(db, "IT-COB", company=co_b)

    resp = await admin_client.get(f"/assets?company_id={co_a.id}")
    assert _row("IT-COA") in resp.text
    assert _row("IT-COB") not in resp.text


async def test_filter_checkout_state_out_and_available(admin_client, db):
    admin_id = await _breakglass_id(db)
    loc = Location(name="Checkout Target Loc")
    db.add(loc)
    await db.commit()
    now = datetime.now(timezone.utc)
    out_asset, _, out_status, _ = await _make_asset(db, "IT-OUT", status_type=StatusType.deployed)
    db.add(
        Checkout(
            asset_id=out_asset.id, status_label_id_at_checkout=out_status.id,
            target_location_id=loc.id, checked_out_at=now, checked_out_by=admin_id,
        )
    )
    out_asset.checked_out_at = now
    out_asset.checked_out_to_location_id = loc.id
    await db.commit()
    await _make_asset(db, "IT-AVAIL")

    out_resp = await admin_client.get("/assets?checkout_state=out")
    assert _row("IT-OUT") in out_resp.text
    assert _row("IT-AVAIL") not in out_resp.text

    available_resp = await admin_client.get("/assets?checkout_state=available")
    assert _row("IT-AVAIL") in available_resp.text
    assert _row("IT-OUT") not in available_resp.text


async def test_free_text_search_matches_tag_serial_and_model_name(admin_client, db):
    await _make_asset(db, "IT-SEARCH01", serial="SN-UNIQUE-1", model_name="Latitude 5440")
    await _make_asset(db, "IT-SEARCH02", serial="SN-UNIQUE-2", model_name="Latitude 5440")
    await _make_asset(db, "IT-OTHER", serial="SN-OTHER", model_name="ThinkPad T14")

    by_tag = await admin_client.get("/assets?q=SEARCH01")
    assert _row("IT-SEARCH01") in by_tag.text
    assert _row("IT-SEARCH02") not in by_tag.text
    assert _row("IT-OTHER") not in by_tag.text

    by_serial = await admin_client.get("/assets?q=SN-UNIQUE-2")
    assert _row("IT-SEARCH02") in by_serial.text
    assert _row("IT-SEARCH01") not in by_serial.text

    by_model = await admin_client.get("/assets?q=ThinkPad")
    assert _row("IT-OTHER") in by_model.text
    assert _row("IT-SEARCH01") not in by_model.text
    assert _row("IT-SEARCH02") not in by_model.text


async def test_combined_filters_apply_together(admin_client, db):
    _, model, _, cat = await _make_asset(db, "IT-COMBO-MATCH", category_name="Combo Cat", model_name="Combo Model")
    # Shares category+model with the match on purpose -- category_id alone
    # wouldn't distinguish them, only category_id AND q together should.
    await _make_asset(db, "IT-COMBO-WRONG-NAME", category=cat, model=model)
    await _make_asset(db, "IT-COMBO-WRONG-CAT", category_name="Other Cat", model_name="Combo Model 2")

    resp = await admin_client.get(f"/assets?category_id={cat.id}&q=IT-COMBO-MATCH")
    assert _row("IT-COMBO-MATCH") in resp.text
    assert _row("IT-COMBO-WRONG-CAT") not in resp.text
    assert _row("IT-COMBO-WRONG-NAME") not in resp.text


async def test_htmx_request_returns_table_partial_only(admin_client, db):
    await _make_asset(db, "IT-PARTIAL")
    resp = await admin_client.get("/assets", headers={"HX-Request": "true"})
    assert resp.status_code == 200
    assert 'id="assets-table"' in resp.text
    assert "<nav" not in resp.text  # no sidebar/base layout
    assert _row("IT-PARTIAL") in resp.text


async def test_no_filters_behaves_like_before(admin_client, db):
    await _make_asset(db, "IT-PLAIN")
    resp = await admin_client.get("/assets")
    assert resp.status_code == 200
    assert _row("IT-PLAIN") in resp.text
    assert "bi-funnel" not in resp.text  # no "N result(s), clear filters" banner


async def test_dashboard_deep_links_still_work_alongside_new_filters(admin_client, db):
    """The pre-existing Dashboard-only params (status_type, warranty=
    expiring, checkout_state=overdue/due_soon) must keep working now
    that checkout_state also carries the new out/available values."""
    await save_setting(db, "warranty.alert_days", "30")
    await db.commit()
    today = date.today()
    await _make_asset(db, "IT-DEEPLINK-ARCHIVED", status_type=StatusType.archived)
    warranty_asset, _, _, _ = await _make_asset(db, "IT-DEEPLINK-WARN")
    warranty_asset.purchase_date = today - timedelta(days=350)
    warranty_asset.warranty_months = 12
    await db.commit()

    status_resp = await admin_client.get("/assets?status_type=archived")
    assert _row("IT-DEEPLINK-ARCHIVED") in status_resp.text

    warranty_resp = await admin_client.get("/assets?warranty=expiring")
    assert _row("IT-DEEPLINK-WARN") in warranty_resp.text
