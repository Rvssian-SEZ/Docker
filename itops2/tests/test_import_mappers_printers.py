"""app/core/import_mappers/printers.py -- v1 printers -> core_assets
(Printer category) + core_printer_details, and printer_repairs ->
core_maintenance."""

from datetime import date

from sqlalchemy import select

from app.core.import_mappers.printers import import_printer_repairs, import_printers
from app.core.models import (
    AssetModel, Asset, Category, Contract, ContractAsset, ContractType, ImportRowOutcome, Maintenance,
    Manufacturer, PrinterDetails, StatusLabel, V1ImportRow,
)
from app.core.settings_store import load_settings
from tests.conftest import FakeV1Source, make_import_batch

PRINTER_ROW = {
    "id": 1, "make": "HP", "model": "LaserJet Pro", "serial_number": "PR-SN-1", "asset_tag": None,
    "ip_address": "10.0.0.5", "location": "Victoria Office", "department": "Finance",
    "status": "active", "purchase_date": None, "warranty_expiry": None, "purchase_price": None,
    "contract_id": None, "notes": "shared printer",
}


def _printers_source(rows):
    return FakeV1Source({"FROM printers": rows})


async def test_creates_printer_asset_with_synthesis_and_details(db):
    batch = await make_import_batch(db)
    store = await load_settings(db)
    await import_printers(db, _printers_source([PRINTER_ROW]), batch, store)
    await db.commit()

    cat = (await db.execute(select(Category).where(Category.name == "Printer"))).scalar_one()
    mfr = (await db.execute(select(Manufacturer).where(Manufacturer.name == "HP"))).scalar_one()
    model = (await db.execute(select(AssetModel).where(AssetModel.name == "LaserJet Pro"))).scalar_one()
    assert model.category_id == cat.id
    assert model.manufacturer_id == mfr.id

    asset = (await db.execute(select(Asset).where(Asset.serial == "PR-SN-1"))).scalar_one()
    assert asset.notes == "shared printer"
    status = await db.get(StatusLabel, asset.status_label_id)
    assert status.name == "Available"
    assert status.status_type.value == "deployable"

    details = await db.get(PrinterDetails, asset.id)
    assert details.ip_address == "10.0.0.5"

    import_row = (await db.execute(select(V1ImportRow).where(V1ImportRow.v1_table == "printers"))).scalar_one()
    assert "Finance" in import_row.detail  # department captured, no v2 field to store it in


async def test_offline_and_active_map_to_distinct_status_labels(db):
    batch = await make_import_batch(db)
    store = await load_settings(db)
    row1 = dict(PRINTER_ROW, id=1, serial_number="A")
    row2 = dict(PRINTER_ROW, id=2, serial_number="B", status="offline")
    await import_printers(db, _printers_source([row1, row2]), batch, store)
    await db.commit()

    active_asset = (await db.execute(select(Asset).where(Asset.serial == "A"))).scalar_one()
    offline_asset = (await db.execute(select(Asset).where(Asset.serial == "B"))).scalar_one()
    active_status = await db.get(StatusLabel, active_asset.status_label_id)
    offline_status = await db.get(StatusLabel, offline_asset.status_label_id)
    assert active_status.name == "Available"
    assert offline_status.name == "Offline"
    assert active_status.id != offline_status.id


async def test_contract_link_created_when_contract_already_imported(db):
    batch = await make_import_batch(db)
    contract = Contract(
        name="Support Contract", contract_type=ContractType.contract, end_date=date(2026, 1, 1),
        created_by=batch.started_by,
    )
    db.add(contract)
    await db.flush()

    db.add(
        V1ImportRow(
            batch_id=batch.id, v1_table="contracts", v1_id=7, v2_entity_type="contract",
            v2_entity_id=contract.id, outcome=ImportRowOutcome.created,
        )
    )
    await db.flush()

    store = await load_settings(db)
    row = dict(PRINTER_ROW, contract_id=7)
    await import_printers(db, _printers_source([row]), batch, store)
    await db.commit()

    asset = (await db.execute(select(Asset).where(Asset.serial == "PR-SN-1"))).scalar_one()
    link = (
        await db.execute(select(ContractAsset).where(ContractAsset.contract_id == contract.id))
    ).scalar_one()
    assert link.asset_id == asset.id


async def test_contract_not_yet_imported_notes_instead_of_blocking(db):
    batch = await make_import_batch(db)
    store = await load_settings(db)
    row = dict(PRINTER_ROW, contract_id=999)
    await import_printers(db, _printers_source([row]), batch, store)
    await db.commit()

    import_row = (await db.execute(select(V1ImportRow).where(V1ImportRow.v1_table == "printers"))).scalar_one()
    assert import_row.outcome == ImportRowOutcome.created  # asset still created
    assert "not yet imported" in import_row.detail


async def test_printers_dry_run_writes_no_target_rows(db):
    batch = await make_import_batch(db, dry_run=True)
    store = await load_settings(db)
    await import_printers(db, _printers_source([PRINTER_ROW]), batch, store)
    await db.commit()

    assert (await db.execute(select(Asset).where(Asset.serial == "PR-SN-1"))).scalar_one_or_none() is None
    import_row = (await db.execute(select(V1ImportRow).where(V1ImportRow.v1_table == "printers"))).scalar_one()
    assert import_row.is_dry_run is True


async def test_printer_repair_creates_maintenance_record(db):
    batch = await make_import_batch(db)
    store = await load_settings(db)
    await import_printers(db, _printers_source([PRINTER_ROW]), batch, store)
    await db.flush()
    asset = (await db.execute(select(Asset).where(Asset.serial == "PR-SN-1"))).scalar_one()

    repair_row = {
        "id": 1, "printer_id": 1, "description": "Replaced fuser", "repair_date": date(2025, 3, 1),
        "cost": "300 SCR", "document_ref": "INV-001", "notes": None,
    }
    await import_printer_repairs(db, FakeV1Source({"FROM printer_repairs": [repair_row]}), batch, store)
    await db.commit()

    record = (await db.execute(select(Maintenance).where(Maintenance.asset_id == asset.id))).scalar_one()
    assert record.maintenance_type.value == "repair"
    assert record.cost == 300
    assert record.currency == "SCR"
    assert "INV-001" in record.description


async def test_printer_repair_for_unimported_printer_is_flagged(db):
    batch = await make_import_batch(db)
    store = await load_settings(db)
    repair_row = {
        "id": 2, "printer_id": 999, "description": "x", "repair_date": date(2025, 1, 1),
        "cost": None, "document_ref": None, "notes": None,
    }
    await import_printer_repairs(db, FakeV1Source({"FROM printer_repairs": [repair_row]}), batch, store)
    await db.commit()

    import_row = (
        await db.execute(select(V1ImportRow).where(V1ImportRow.v1_table == "printer_repairs"))
    ).scalar_one()
    assert import_row.outcome == ImportRowOutcome.flagged
    assert "printers module first" in import_row.detail


async def test_printer_repair_with_blank_date_is_flagged(db):
    batch = await make_import_batch(db)
    store = await load_settings(db)
    await import_printers(db, _printers_source([PRINTER_ROW]), batch, store)
    await db.flush()

    repair_row = {
        "id": 3, "printer_id": 1, "description": "x", "repair_date": None,
        "cost": None, "document_ref": None, "notes": None,
    }
    await import_printer_repairs(db, FakeV1Source({"FROM printer_repairs": [repair_row]}), batch, store)
    await db.commit()

    import_row = (
        await db.execute(
            select(V1ImportRow).where(V1ImportRow.v1_table == "printer_repairs", V1ImportRow.v1_id == 3)
        )
    ).scalar_one()
    assert import_row.outcome == ImportRowOutcome.flagged
    assert "blank repair_date" in import_row.detail
