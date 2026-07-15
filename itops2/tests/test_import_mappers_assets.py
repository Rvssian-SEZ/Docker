"""app/core/import_mappers/assets.py -- it_assets -> core_assets (+
core_checkouts for assigned assets), with Manufacturer/Category/Model
synthesis."""

from datetime import date

from sqlalchemy import select

from app.core.import_mappers.assets import import_assets
from app.core.models import (
    AssetModel, AuthSource, Category, Checkout, Asset, ImportRowOutcome, Manufacturer,
    Role, RoleName, StatusLabel, User, V1ImportRow,
)
from app.core.settings_store import load_settings
from tests.conftest import FakeV1Source, make_import_batch

BASE_ROW = {
    "id": 1, "name": "Test Laptop", "asset_tag": None, "category": "laptop",
    "manufacturer": "Apple", "model": "MacBook Pro", "serial_number": "SN123",
    "status": "available", "assigned_user_id": None, "purchase_date": None,
    "warranty_expiry": None, "purchase_price": None, "supplier": None, "notes": None,
}


def _assets_source(rows):
    return FakeV1Source({"FROM it_assets": rows})


async def test_creates_asset_with_catalog_synthesis_and_auto_tag(db):
    batch = await make_import_batch(db)
    store = await load_settings(db)
    row = dict(BASE_ROW, purchase_price="1000 SCR")
    await import_assets(db, _assets_source([row]), batch, store)
    await db.commit()

    mfr = (await db.execute(select(Manufacturer).where(Manufacturer.name == "Apple"))).scalar_one()
    cat = (await db.execute(select(Category).where(Category.name == "Laptop"))).scalar_one()
    model = (await db.execute(select(AssetModel).where(AssetModel.name == "MacBook Pro"))).scalar_one()
    assert model.manufacturer_id == mfr.id
    assert model.category_id == cat.id

    asset = (await db.execute(select(Asset).where(Asset.serial == "SN123"))).scalar_one()
    assert asset.asset_tag.startswith("IT-")
    assert asset.model_id == model.id
    assert asset.purchase_cost == 1000
    assert asset.purchase_currency == "SCR"

    status = await db.get(StatusLabel, asset.status_label_id)
    assert status.name == "Available"
    assert status.status_type.value == "deployable"

    import_row = (await db.execute(select(V1ImportRow).where(V1ImportRow.v1_table == "it_assets"))).scalar_one()
    assert import_row.outcome == ImportRowOutcome.created
    assert import_row.v2_entity_id == asset.id


async def test_preserves_nonblank_v1_asset_tag(db):
    batch = await make_import_batch(db)
    store = await load_settings(db)
    row = dict(BASE_ROW, asset_tag="qwerty-001")
    await import_assets(db, _assets_source([row]), batch, store)
    await db.commit()

    asset = (await db.execute(select(Asset).where(Asset.serial == "SN123"))).scalar_one()
    assert asset.asset_tag == "qwerty-001"


async def test_unparseable_bare_cost_is_flagged_for_review_but_asset_still_created(db):
    batch = await make_import_batch(db)
    store = await load_settings(db)
    row = dict(BASE_ROW, purchase_price="6000")
    await import_assets(db, _assets_source([row]), batch, store)
    await db.commit()

    asset = (await db.execute(select(Asset).where(Asset.serial == "SN123"))).scalar_one()
    assert asset.purchase_cost is None
    assert asset.purchase_currency is None

    import_row = (await db.execute(select(V1ImportRow).where(V1ImportRow.v1_table == "it_assets"))).scalar_one()
    assert "NEEDS REVIEW (cost)" in import_row.detail
    assert "6000" in import_row.detail


async def test_blank_manufacturer_and_model_use_placeholders(db):
    batch = await make_import_batch(db)
    store = await load_settings(db)
    row = dict(BASE_ROW, manufacturer="", model="")
    await import_assets(db, _assets_source([row]), batch, store)
    await db.commit()

    assert (await db.execute(select(Manufacturer).where(Manufacturer.name == "Unknown Manufacturer"))).scalar_one()
    assert (await db.execute(select(AssetModel).where(AssetModel.name == "Unknown Model"))).scalar_one()


async def test_manufacturer_dedup_is_case_insensitive(db):
    db.add(Manufacturer(name="Apple"))
    await db.flush()

    batch = await make_import_batch(db)
    store = await load_settings(db)
    row = dict(BASE_ROW, manufacturer="APPLE")
    await import_assets(db, _assets_source([row]), batch, store)
    await db.commit()

    all_apple = (await db.execute(select(Manufacturer).where(Manufacturer.name.ilike("apple")))).scalars().all()
    assert len(all_apple) == 1


async def test_assigned_asset_with_known_v2_user_replays_checkout(db):
    role_id = (await db.execute(select(Role.id).where(Role.name == RoleName.viewer))).scalar_one()
    target = User(username="assignee", auth_source=AuthSource.oidc, role_id=role_id)
    db.add(target)
    await db.flush()

    user_batch = await make_import_batch(db)
    db.add(
        V1ImportRow(
            batch_id=user_batch.id, v1_table="users", v1_id=99, v2_entity_type="user",
            v2_entity_id=target.id, outcome=ImportRowOutcome.created,
        )
    )
    await db.flush()

    batch = await make_import_batch(db)
    store = await load_settings(db)
    row = dict(BASE_ROW, status="assigned", assigned_user_id=99)
    await import_assets(db, _assets_source([row]), batch, store)
    await db.commit()

    asset = (await db.execute(select(Asset).where(Asset.serial == "SN123"))).scalar_one()
    assert asset.checked_out_to_user_id == target.id
    assert asset.checked_out_at is not None
    status = await db.get(StatusLabel, asset.status_label_id)
    assert status.status_type.value == "deployed"

    checkout = (await db.execute(select(Checkout).where(Checkout.asset_id == asset.id))).scalar_one()
    assert checkout.target_user_id == target.id
    assert checkout.checked_in_at is None


async def test_assigned_asset_with_unknown_v2_user_created_without_checkout(db):
    batch = await make_import_batch(db)
    store = await load_settings(db)
    row = dict(BASE_ROW, status="assigned", assigned_user_id=12345)
    await import_assets(db, _assets_source([row]), batch, store)
    await db.commit()

    asset = (await db.execute(select(Asset).where(Asset.serial == "SN123"))).scalar_one()
    assert asset.checked_out_to_user_id is None
    assert asset.checked_out_at is None

    import_row = (await db.execute(select(V1ImportRow).where(V1ImportRow.v1_table == "it_assets"))).scalar_one()
    assert "needs manual checkout" in import_row.detail


async def test_dry_run_writes_no_target_rows(db):
    batch = await make_import_batch(db, dry_run=True)
    store = await load_settings(db)
    row = dict(BASE_ROW, manufacturer="DryRunMfr", model="DryRunModel")
    await import_assets(db, _assets_source([row]), batch, store)
    await db.commit()

    assert (await db.execute(select(Manufacturer).where(Manufacturer.name == "DryRunMfr")))\
        .scalar_one_or_none() is None
    assert (await db.execute(select(Asset).where(Asset.serial == "SN123"))).scalar_one_or_none() is None

    import_row = (await db.execute(select(V1ImportRow).where(V1ImportRow.v1_table == "it_assets"))).scalar_one()
    assert import_row.outcome == ImportRowOutcome.created
    assert import_row.is_dry_run is True
    assert import_row.v2_entity_id is None


async def test_warranty_months_computed_from_purchase_and_expiry_dates(db):
    batch = await make_import_batch(db)
    store = await load_settings(db)
    row = dict(BASE_ROW, purchase_date=date(2024, 1, 15), warranty_expiry=date(2025, 1, 15))
    await import_assets(db, _assets_source([row]), batch, store)
    await db.commit()

    asset = (await db.execute(select(Asset).where(Asset.serial == "SN123"))).scalar_one()
    assert asset.warranty_months == 12
