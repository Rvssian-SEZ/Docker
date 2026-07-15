"""app/core/import_mappers/equipment.py -- v1 equipment + its full
lending_records history -> core_assets + core_checkouts."""

from datetime import datetime, timezone

from sqlalchemy import select

from app.core.import_mappers.equipment import import_equipment, import_lending_records
from app.core.models import (
    AssetModel, AuthSource, Category, Checkout, Asset, ImportRowOutcome, Location, Manufacturer,
    Role, RoleName, StatusLabel, User, V1ImportRow,
)
from app.core.settings_store import load_settings
from tests.conftest import FakeV1Source, make_import_batch

EQUIPMENT_ROW = {
    "id": 1, "name": "Conference Room Projector", "category": "projector",
    "serial_number": "PRJ-1", "asset_tag": None, "status": "available",
    "location": "Victoria Office", "notes": None,
}


async def _make_v2_user(db, username="lender"):
    role_id = (await db.execute(select(Role.id).where(Role.name == RoleName.viewer))).scalar_one()
    u = User(username=username, auth_source=AuthSource.oidc, role_id=role_id)
    db.add(u)
    await db.flush()
    return u


async def _tag_user_imported(db, batch, v1_user_id, v2_user_id):
    db.add(
        V1ImportRow(
            batch_id=batch.id, v1_table="users", v1_id=v1_user_id, v2_entity_type="user",
            v2_entity_id=v2_user_id, outcome=ImportRowOutcome.created,
        )
    )
    await db.flush()


async def test_import_equipment_creates_asset_with_placeholders_and_synthesis(db):
    batch = await make_import_batch(db)
    store = await load_settings(db)
    source = FakeV1Source({"FROM equipment": [EQUIPMENT_ROW]})
    await import_equipment(db, source, batch, store)
    await db.commit()

    mfr = (await db.execute(select(Manufacturer).where(Manufacturer.name == "Unknown Manufacturer"))).scalar_one()
    cat = (await db.execute(select(Category).where(Category.name == "Projector"))).scalar_one()
    model = (await db.execute(select(AssetModel).where(AssetModel.name == "Conference Room Projector"))).scalar_one()
    assert model.manufacturer_id == mfr.id
    assert model.category_id == cat.id

    loc = (await db.execute(select(Location).where(Location.name == "Victoria Office"))).scalar_one()
    asset = (await db.execute(select(Asset).where(Asset.serial == "PRJ-1"))).scalar_one()
    assert asset.location_id == loc.id
    assert asset.asset_tag.startswith("IT-")

    import_row = (await db.execute(select(V1ImportRow).where(V1ImportRow.v1_table == "equipment"))).scalar_one()
    assert import_row.outcome == ImportRowOutcome.created
    assert import_row.v2_entity_id == asset.id


async def test_import_equipment_preserves_nonblank_tag(db):
    batch = await make_import_batch(db)
    store = await load_settings(db)
    row = dict(EQUIPMENT_ROW, asset_tag="qwerty-001")
    await import_equipment(db, FakeV1Source({"FROM equipment": [row]}), batch, store)
    await db.commit()

    asset = (await db.execute(select(Asset).where(Asset.serial == "PRJ-1"))).scalar_one()
    assert asset.asset_tag == "qwerty-001"


async def test_import_equipment_dry_run_writes_no_target_rows(db):
    batch = await make_import_batch(db, dry_run=True)
    store = await load_settings(db)
    await import_equipment(db, FakeV1Source({"FROM equipment": [EQUIPMENT_ROW]}), batch, store)
    await db.commit()

    assert (await db.execute(select(Asset).where(Asset.serial == "PRJ-1"))).scalar_one_or_none() is None
    import_row = (await db.execute(select(V1ImportRow).where(V1ImportRow.v1_table == "equipment"))).scalar_one()
    assert import_row.is_dry_run is True
    assert import_row.v2_entity_id is None


async def test_open_lending_record_flips_asset_to_deployed(db):
    batch = await make_import_batch(db)
    store = await load_settings(db)
    await import_equipment(db, FakeV1Source({"FROM equipment": [EQUIPMENT_ROW]}), batch, store)
    await db.flush()
    asset = (await db.execute(select(Asset).where(Asset.serial == "PRJ-1"))).scalar_one()

    borrower = await _make_v2_user(db, "borrower")
    await _tag_user_imported(db, batch, 50, borrower.id)

    lending_row = {
        "id": 1, "equipment_id": 1, "user_id": 50, "lent_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
        "due_at": None, "returned_at": None, "lent_by_id": None, "notes": None,
    }
    await import_lending_records(db, FakeV1Source({"FROM lending_records": [lending_row]}), batch)
    await db.commit()

    await db.refresh(asset)
    assert asset.checked_out_to_user_id == borrower.id
    assert asset.checked_out_at is not None
    status = await db.get(StatusLabel, asset.status_label_id)
    assert status.status_type.value == "deployed"

    checkout = (await db.execute(select(Checkout).where(Checkout.asset_id == asset.id))).scalar_one()
    assert checkout.checked_in_at is None
    assert checkout.target_user_id == borrower.id


async def test_closed_lending_record_creates_closed_checkout(db):
    batch = await make_import_batch(db)
    store = await load_settings(db)
    await import_equipment(db, FakeV1Source({"FROM equipment": [EQUIPMENT_ROW]}), batch, store)
    await db.flush()
    asset = (await db.execute(select(Asset).where(Asset.serial == "PRJ-1"))).scalar_one()

    borrower = await _make_v2_user(db, "borrower2")
    await _tag_user_imported(db, batch, 51, borrower.id)

    lending_row = {
        "id": 2, "equipment_id": 1, "user_id": 51,
        "lent_at": datetime(2025, 1, 1, tzinfo=timezone.utc), "due_at": None,
        "returned_at": datetime(2025, 1, 10, tzinfo=timezone.utc), "lent_by_id": None, "notes": "trade show",
    }
    await import_lending_records(db, FakeV1Source({"FROM lending_records": [lending_row]}), batch)
    await db.commit()

    checkout = (await db.execute(select(Checkout).where(Checkout.target_user_id == borrower.id))).scalar_one()
    assert checkout.checked_in_at is not None
    assert checkout.checkin_status_label_id is not None
    assert "trade show" in checkout.notes

    await db.refresh(asset)
    assert asset.checked_out_at is None  # never touched by a closed historical record


async def test_lending_record_for_unimported_equipment_is_flagged(db):
    batch = await make_import_batch(db)
    lending_row = {
        "id": 3, "equipment_id": 999, "user_id": 1, "lent_at": None, "due_at": None,
        "returned_at": None, "lent_by_id": None, "notes": None,
    }
    await import_lending_records(db, FakeV1Source({"FROM lending_records": [lending_row]}), batch)
    await db.commit()

    import_row = (
        await db.execute(select(V1ImportRow).where(V1ImportRow.v1_table == "lending_records"))
    ).scalar_one()
    assert import_row.outcome == ImportRowOutcome.flagged
    assert "equipment module first" in import_row.detail


async def test_lending_record_for_unimported_user_is_flagged(db):
    batch = await make_import_batch(db)
    store = await load_settings(db)
    await import_equipment(db, FakeV1Source({"FROM equipment": [EQUIPMENT_ROW]}), batch, store)
    await db.flush()
    asset = (await db.execute(select(Asset).where(Asset.serial == "PRJ-1"))).scalar_one()

    lending_row = {
        "id": 4, "equipment_id": 1, "user_id": 777, "lent_at": None, "due_at": None,
        "returned_at": None, "lent_by_id": None, "notes": None,
    }
    await import_lending_records(db, FakeV1Source({"FROM lending_records": [lending_row]}), batch)
    await db.commit()

    import_row = (
        await db.execute(select(V1ImportRow).where(V1ImportRow.v1_table == "lending_records"))
    ).scalar_one()
    assert import_row.outcome == ImportRowOutcome.flagged
    assert "no imported v2 user" in import_row.detail
