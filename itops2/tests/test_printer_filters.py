"""Printers list filter bar (location, status, free-text over
hostname/IP) — SQL-side filtering, same pattern as the Assets list.
"""

from sqlalchemy import select

from app.core.models import Asset, AssetModel, Category, Location, Manufacturer, PrinterDetails, StatusLabel, StatusType


async def _make_printer(db, tag, *, location=None, status_type=StatusType.deployable):
    mfr = Manufacturer(name=f"Brother-{tag}")
    cat = (await db.execute(select(Category).where(Category.name == "Printer"))).scalar_one_or_none()
    if cat is None:
        cat = Category(name="Printer")
        db.add(cat)
        await db.flush()
    db.add(mfr)
    await db.flush()
    model = AssetModel(name="HL-L2350DW", manufacturer_id=mfr.id, category_id=cat.id)
    status = StatusLabel(name=f"PrinterStatus-{tag}", status_type=status_type)
    db.add_all([model, status])
    await db.flush()
    asset = Asset(
        asset_tag=tag, model_id=model.id, status_label_id=status.id,
        location_id=location.id if location else None,
    )
    db.add(asset)
    await db.commit()
    return asset, status


def _row(tag: str) -> str:
    return f">{tag}</a>"


async def test_filter_printers_by_location(admin_client, db):
    loc_a = Location(name="HQ")
    loc_b = Location(name="Branch")
    db.add_all([loc_a, loc_b])
    await db.commit()
    await _make_printer(db, "IT-PRLOCA", location=loc_a)
    await _make_printer(db, "IT-PRLOCB", location=loc_b)

    resp = await admin_client.get(f"/printers?location_id={loc_a.id}")
    assert _row("IT-PRLOCA") in resp.text
    assert _row("IT-PRLOCB") not in resp.text


async def test_filter_printers_by_status_label(admin_client, db):
    asset_a, status_a = await _make_printer(db, "IT-PRSTA")
    asset_b, status_b = await _make_printer(db, "IT-PRSTB")

    resp = await admin_client.get(f"/printers?status_label_id={status_a.id}")
    assert _row("IT-PRSTA") in resp.text
    assert _row("IT-PRSTB") not in resp.text


async def test_filter_printers_by_hostname_or_ip(admin_client, db):
    asset_a, _ = await _make_printer(db, "IT-PRHOST")
    asset_b, _ = await _make_printer(db, "IT-PRNOMATCH")
    db.add_all(
        [
            PrinterDetails(asset_id=asset_a.id, hostname="printer-3rdfloor", ip_address="10.0.5.20"),
            PrinterDetails(asset_id=asset_b.id, hostname="printer-basement", ip_address="10.0.5.99"),
        ]
    )
    await db.commit()

    by_hostname = await admin_client.get("/printers?q=3rdfloor")
    assert _row("IT-PRHOST") in by_hostname.text
    assert _row("IT-PRNOMATCH") not in by_hostname.text

    by_ip = await admin_client.get("/printers?q=10.0.5.20")
    assert _row("IT-PRHOST") in by_ip.text
    assert _row("IT-PRNOMATCH") not in by_ip.text


async def test_filter_printers_excludes_printers_with_no_details_row_when_searching(admin_client, db):
    """A printer with no core_printer_details row yet (lazily created on
    first save) must not blow up the outer-join search, just not match."""
    await _make_printer(db, "IT-PRNODETAILS")
    resp = await admin_client.get("/printers?q=anything")
    assert resp.status_code == 200
    assert _row("IT-PRNODETAILS") not in resp.text


async def test_printers_htmx_request_returns_table_partial_only(admin_client, db):
    await _make_printer(db, "IT-PRPARTIAL")
    resp = await admin_client.get("/printers", headers={"HX-Request": "true"})
    assert resp.status_code == 200
    assert 'id="printers-table"' in resp.text
    assert "<nav" not in resp.text
    assert _row("IT-PRPARTIAL") in resp.text


async def test_printers_no_filters_behaves_like_before(admin_client, db):
    await _make_printer(db, "IT-PRPLAIN")
    resp = await admin_client.get("/printers")
    assert resp.status_code == 200
    assert _row("IT-PRPLAIN") in resp.text
    assert "bi-funnel" not in resp.text
