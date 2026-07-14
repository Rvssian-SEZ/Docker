"""Printers: category-based filtering (not a separate entity), the
printer_details 1:1 upsert, and currency-converted maintenance cost
totals -- including the case where no exchange rate is available (must
be surfaced as excluded, never silently wrong).
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.core.models import (
    Asset,
    AssetModel,
    Category,
    ExchangeRate,
    Maintenance,
    MaintenanceType,
    Manufacturer,
    PrinterDetails,
    StatusLabel,
    StatusType,
    User,
)


async def _breakglass_id(db) -> int:
    return (await db.execute(select(User.id).where(User.is_breakglass.is_(True)))).scalar_one()


async def _make_asset(db, category_name="Printer", tag="IT-PR01"):
    mfr = Manufacturer(name=f"Brother-{category_name}-{tag}")
    cat = Category(name=category_name)
    db.add_all([mfr, cat])
    await db.flush()
    model = AssetModel(name="HL-L2350DW", manufacturer_id=mfr.id, category_id=cat.id)
    db.add(model)
    await db.flush()

    deployable = (
        await db.execute(select(StatusLabel).where(StatusLabel.name == "Ready to Deploy"))
    ).scalar_one_or_none()
    if deployable is None:
        deployable = StatusLabel(name="Ready to Deploy", status_type=StatusType.deployable)
        db.add(deployable)
        await db.flush()

    asset = Asset(asset_tag=tag, model_id=model.id, status_label_id=deployable.id)
    db.add(asset)
    await db.commit()
    return asset


async def test_printers_list_only_shows_printer_category(admin_client, db):
    await _make_asset(db, category_name="Printer", tag="IT-PR01")
    await _make_asset(db, category_name="Laptop", tag="IT-LT01")

    resp = await admin_client.get("/printers")
    assert resp.status_code == 200
    assert "IT-PR01" in resp.text
    assert "IT-LT01" not in resp.text


async def test_printers_list_category_match_case_insensitive(admin_client, db):
    await _make_asset(db, category_name="printer")  # lowercase
    resp = await admin_client.get("/printers")
    assert "IT-PR01" in resp.text


async def test_printers_list_shows_hostname_column(admin_client, db):
    """Hostname already existed on core_printer_details (Phase 6) and was
    already editable/displayed on the asset detail page and already
    searchable via the list's free-text filter -- the only real gap was
    the list table itself never rendering it as a column."""
    asset = await _make_asset(db)
    db.add(PrinterDetails(asset_id=asset.id, hostname="printer-3rdfloor", ip_address="10.0.5.20"))
    await db.commit()

    resp = await admin_client.get("/printers")
    assert resp.status_code == 200
    assert "Hostname" in resp.text  # column header
    assert "printer-3rdfloor" in resp.text
    assert "10.0.5.20" in resp.text


async def test_printer_details_upsert_create_then_update(admin_client, db):
    asset = await _make_asset(db)

    resp = await admin_client.post(
        f"/assets/{asset.id}/printer-details/update",
        data={"ip_address": "10.0.0.5", "hostname": "printer1", "consumable_notes": "toner low"},
    )
    assert resp.status_code == 200
    assert "text-bg-success" in resp.text

    row = (await db.execute(select(PrinterDetails).where(PrinterDetails.asset_id == asset.id))).scalar_one()
    assert row.ip_address == "10.0.0.5"
    assert row.hostname == "printer1"

    resp2 = await admin_client.post(
        f"/assets/{asset.id}/printer-details/update",
        data={"ip_address": "10.0.0.6", "hostname": "printer1", "consumable_notes": ""},
    )
    assert resp2.status_code == 200

    await db.refresh(row)
    assert row.ip_address == "10.0.0.6"
    assert row.consumable_notes is None

    # Still exactly one row -- an upsert, not a second insert (asset_id is PK).
    count = (await db.execute(select(PrinterDetails).where(PrinterDetails.asset_id == asset.id))).all()
    assert len(count) == 1


async def test_maintenance_total_same_currency_no_conversion_needed(admin_client, db):
    asset = await _make_asset(db)
    db.add(
        Maintenance(
            asset_id=asset.id, date=date(2026, 1, 10), maintenance_type=MaintenanceType.repair,
            description="toner replaced", cost=Decimal("25.00"), currency="SCR",
            created_by=await _breakglass_id(db),
        )
    )
    await db.commit()

    resp = await admin_client.get("/printers")
    assert "25.00" in resp.text


async def test_maintenance_total_converted_via_exchange_rate(admin_client, db):
    asset = await _make_asset(db)
    db.add(
        ExchangeRate(from_currency="USD", to_currency="SCR", rate=Decimal("13.500000"), effective_date=date(2026, 1, 1))
    )
    db.add(
        Maintenance(
            asset_id=asset.id, date=date(2026, 1, 10), maintenance_type=MaintenanceType.repair,
            description="drum replaced", cost=Decimal("10.00"), currency="USD",
            created_by=await _breakglass_id(db),
        )
    )
    await db.commit()

    resp = await admin_client.get("/printers")
    assert resp.status_code == 200
    # 10.00 USD * 13.5 = 135.00 SCR
    assert "135.00" in resp.text


async def test_maintenance_total_excluded_when_no_rate_available(admin_client, db):
    asset = await _make_asset(db)
    # EUR exists as a currency but no EUR->SCR rate is seeded anywhere.
    db.add(
        Maintenance(
            asset_id=asset.id, date=date(2026, 1, 10), maintenance_type=MaintenanceType.repair,
            description="fuser replaced", cost=Decimal("50.00"), currency="EUR",
            created_by=await _breakglass_id(db),
        )
    )
    await db.commit()

    resp = await admin_client.get("/printers")
    assert resp.status_code == 200
    # Must not silently show a wrong total (e.g. treating EUR as SCR 1:1).
    assert "50.00" not in resp.text
    assert "excluded" in resp.text.lower()


async def test_printer_details_update_requires_printers_manage(client, db, settings):
    """A user with printers.view but not printers.manage (default
    Technician grant) must not be able to edit printer details."""
    from app.core.models import AuthSource, Role, RoleName
    from app.core.security import hash_password

    tech_role = (await db.execute(select(Role).where(Role.name == RoleName.technician))).scalar_one()
    db.add(
        User(
            username="tech1", display_name="Tech One", auth_source=AuthSource.local,
            password_hash=hash_password("supersecret123"), role_id=tech_role.id, is_active=True,
        )
    )
    await db.commit()

    login = await client.post("/login", data={"username": "tech1", "password": "supersecret123"})
    assert login.status_code == 302

    asset = await _make_asset(db)
    resp = await client.post(
        f"/assets/{asset.id}/printer-details/update",
        data={"ip_address": "10.0.0.5", "hostname": "", "consumable_notes": ""},
    )
    assert resp.status_code == 403
