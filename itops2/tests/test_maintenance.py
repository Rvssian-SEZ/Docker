"""Maintenance records: CRUD, the cost-requires-currency validation, and
that deleting a record cleans up its attachments (DB rows + files), not
just the record itself.
"""

from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.core.models import (
    Asset,
    AssetModel,
    Attachment,
    Category,
    Maintenance,
    Manufacturer,
    StatusLabel,
    StatusType,
)


async def _make_asset(db):
    mfr = Manufacturer(name="Dell")
    cat = Category(name="Laptop")
    db.add_all([mfr, cat])
    await db.flush()
    model = AssetModel(name="Latitude 5440", manufacturer_id=mfr.id, category_id=cat.id)
    deployable = StatusLabel(name="Ready to Deploy", status_type=StatusType.deployable)
    db.add_all([model, deployable])
    await db.flush()
    asset = Asset(asset_tag="IT-MT01", model_id=model.id, status_label_id=deployable.id)
    db.add(asset)
    await db.commit()
    return asset


async def test_create_maintenance_record(admin_client, db):
    asset = await _make_asset(db)
    resp = await admin_client.post(
        f"/assets/{asset.id}/maintenance/create",
        data={
            "date": "2026-01-15",
            "maintenance_type": "repair",
            "description": "Replaced fan",
            "cost": "45.00",
            "currency": "SCR",
            "performed_by": "Acme IT Services",
        },
    )
    assert resp.status_code == 204

    row = (await db.execute(select(Maintenance).where(Maintenance.asset_id == asset.id))).scalar_one()
    assert row.description == "Replaced fan"
    assert str(row.cost) == "45.00"
    assert row.currency == "SCR"
    assert row.performed_by == "Acme IT Services"
    assert row.maintenance_type.value == "repair"


async def test_cost_requires_currency(admin_client, db):
    asset = await _make_asset(db)
    resp = await admin_client.post(
        f"/assets/{asset.id}/maintenance/create",
        data={"date": "2026-01-15", "maintenance_type": "repair", "description": "x", "cost": "45.00"},
    )
    assert "text-bg-danger" in resp.text
    assert "currency" in resp.text.lower()
    count = (await db.execute(select(Maintenance.id).where(Maintenance.asset_id == asset.id))).all()
    assert count == []


async def test_update_maintenance_record(admin_client, db):
    asset = await _make_asset(db)
    await admin_client.post(
        f"/assets/{asset.id}/maintenance/create",
        data={"date": "2026-01-15", "maintenance_type": "repair", "description": "Replaced fan"},
    )
    row = (await db.execute(select(Maintenance).where(Maintenance.asset_id == asset.id))).scalar_one()

    resp = await admin_client.post(
        f"/assets/{asset.id}/maintenance/{row.id}/update",
        data={"date": "2026-01-16", "maintenance_type": "upgrade", "description": "Upgraded RAM"},
    )
    assert resp.status_code == 204

    await db.refresh(row)
    assert row.description == "Upgraded RAM"
    assert row.maintenance_type.value == "upgrade"
    assert str(row.date) == "2026-01-16"


async def test_delete_maintenance_record_removes_attachments(admin_client, db):
    asset = await _make_asset(db)
    await admin_client.post(
        f"/assets/{asset.id}/maintenance/create",
        data={"date": "2026-01-15", "maintenance_type": "repair", "description": "Replaced fan"},
    )
    row = (await db.execute(select(Maintenance).where(Maintenance.asset_id == asset.id))).scalar_one()

    await admin_client.post(
        f"/assets/{asset.id}/maintenance/{row.id}/attachments",
        files={"file": ("receipt.pdf", b"pdf bytes", "application/pdf")},
    )
    att = (
        await db.execute(select(Attachment).where(Attachment.entity_id == str(row.id)))
    ).scalar_one()
    on_disk = Path(get_settings().attachments_dir) / "maintenance" / str(row.id) / att.stored_filename
    assert on_disk.exists()

    resp = await admin_client.post(f"/assets/{asset.id}/maintenance/{row.id}/delete")
    assert resp.status_code == 204

    assert (await db.execute(select(Maintenance).where(Maintenance.id == row.id))).scalar_one_or_none() is None
    assert (await db.execute(select(Attachment).where(Attachment.id == att.id))).scalar_one_or_none() is None
    assert not on_disk.exists()


async def test_maintenance_attachment_download_roundtrip(admin_client, db):
    asset = await _make_asset(db)
    await admin_client.post(
        f"/assets/{asset.id}/maintenance/create",
        data={"date": "2026-01-15", "maintenance_type": "maintenance", "description": "Cleaned rollers"},
    )
    row = (await db.execute(select(Maintenance).where(Maintenance.asset_id == asset.id))).scalar_one()

    await admin_client.post(
        f"/assets/{asset.id}/maintenance/{row.id}/attachments",
        files={"file": ("notes.txt", b"cleaned and tested", "text/plain")},
    )
    att = (
        await db.execute(select(Attachment).where(Attachment.entity_id == str(row.id)))
    ).scalar_one()

    resp = await admin_client.get(f"/assets/{asset.id}/maintenance/{row.id}/attachments/{att.id}/download")
    assert resp.status_code == 200
    assert resp.content == b"cleaned and tested"


async def test_unknown_maintenance_type_rejected(admin_client, db):
    asset = await _make_asset(db)
    resp = await admin_client.post(
        f"/assets/{asset.id}/maintenance/create",
        data={"date": "2026-01-15", "maintenance_type": "sabotage", "description": "x"},
    )
    assert "text-bg-danger" in resp.text
    assert "unknown maintenance type" in resp.text.lower()


async def test_asset_with_maintenance_records_blocks_hard_delete_with_accurate_message(admin_client, db):
    """Regression test: an asset with maintenance records but NO checkout
    history must not be told it has checkout history (a real bug found
    during Phase 6 testing -- the generic IntegrityError catch-all
    assumed checkout history was the only remaining FK blocker)."""
    asset = await _make_asset(db)
    await admin_client.post(
        f"/assets/{asset.id}/maintenance/create",
        data={"date": "2026-01-15", "maintenance_type": "repair", "description": "Replaced fan"},
    )

    resp = await admin_client.post(f"/assets/{asset.id}/delete")
    assert resp.status_code == 200
    assert "text-bg-danger" in resp.text
    assert "maintenance record" in resp.text.lower()
    assert "checkout history" not in resp.text.lower()
    assert (await db.execute(select(Asset).where(Asset.id == asset.id))).scalar_one_or_none() is not None
