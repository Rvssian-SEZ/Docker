"""Assets CRUD: creation, the required duplicate-asset-tag IntegrityError
path, and the hard-delete guard (blocked by checkout history / attachments,
allowed otherwise).
"""

from datetime import datetime, timezone

from sqlalchemy import select

from app.core.models import (
    Asset,
    AssetModel,
    Attachment,
    Category,
    Checkout,
    Manufacturer,
    StatusLabel,
    StatusType,
    User,
)


async def _breakglass_id(db) -> int:
    return (await db.execute(select(User.id).where(User.is_breakglass.is_(True)))).scalar_one()


async def _make_catalog(db):
    """Manufacturer + Category + Model + a deployable status label — the
    minimum a valid asset needs. Returns (model, status_label)."""
    mfr = Manufacturer(name="Dell")
    cat = Category(name="Laptop")
    db.add_all([mfr, cat])
    await db.flush()
    model = AssetModel(name="Latitude 5440", manufacturer_id=mfr.id, category_id=cat.id)
    status = StatusLabel(name="Ready to Deploy", status_type=StatusType.deployable)
    db.add_all([model, status])
    await db.flush()
    await db.commit()
    return model, status


async def test_create_asset_via_http(admin_client, db):
    model, status = await _make_catalog(db)
    resp = await admin_client.post(
        "/assets/create",
        data={
            "asset_tag": "IT-0001",
            "model_id": model.id,
            "status_label_id": status.id,
        },
    )
    assert resp.status_code == 204
    assert resp.headers["hx-redirect"].startswith("/assets/")

    asset = (await db.execute(select(Asset).where(Asset.asset_tag == "IT-0001"))).scalar_one()
    assert asset.model_id == model.id
    assert asset.status_label_id == status.id


async def test_create_without_tag_auto_generates(admin_client, db):
    model, status = await _make_catalog(db)
    resp = await admin_client.post(
        "/assets/create", data={"model_id": model.id, "status_label_id": status.id},
    )
    assert resp.status_code == 204
    asset = (await db.execute(select(Asset))).scalar_one()
    assert asset.asset_tag.startswith("IT-")


async def test_duplicate_asset_tag_returns_friendly_toast_not_500(admin_client, db):
    """The one test explicitly required: posting a second asset with an
    already-used tag must hit the IntegrityError->toast path, not crash."""
    model, status = await _make_catalog(db)
    first = await admin_client.post(
        "/assets/create",
        data={"asset_tag": "IT-0042", "model_id": model.id, "status_label_id": status.id},
    )
    assert first.status_code == 204

    second = await admin_client.post(
        "/assets/create",
        data={"asset_tag": "IT-0042", "model_id": model.id, "status_label_id": status.id},
    )
    assert second.status_code == 200
    assert "text-bg-danger" in second.text
    assert "already exists" in second.text

    count = (
        await db.execute(select(Asset.id).where(Asset.asset_tag == "IT-0042"))
    ).all()
    assert len(count) == 1, "the failed duplicate must not have been inserted"


async def test_delete_asset_with_no_history_succeeds(admin_client, db):
    model, status = await _make_catalog(db)
    asset = Asset(asset_tag="IT-DEL1", model_id=model.id, status_label_id=status.id)
    db.add(asset)
    await db.commit()

    resp = await admin_client.post(f"/assets/{asset.id}/delete")
    assert resp.status_code == 204
    assert resp.headers["hx-redirect"] == "/assets"
    assert (await db.execute(select(Asset).where(Asset.id == asset.id))).scalar_one_or_none() is None


async def test_delete_asset_with_checkout_history_is_blocked(admin_client, db):
    model, status = await _make_catalog(db)
    asset = Asset(asset_tag="IT-DEL2", model_id=model.id, status_label_id=status.id)
    db.add(asset)
    await db.flush()
    admin_id = await _breakglass_id(db)
    checkout = Checkout(
        asset_id=asset.id,
        status_label_id_at_checkout=status.id,
        checked_out_at=datetime.now(timezone.utc),
        checked_out_by=admin_id,
        checked_in_at=datetime.now(timezone.utc),
        checked_in_by=admin_id,
        checkin_status_label_id=status.id,
    )
    db.add(checkout)
    await db.commit()

    resp = await admin_client.post(f"/assets/{asset.id}/delete")
    assert resp.status_code == 200
    assert "text-bg-danger" in resp.text
    assert "checkout history" in resp.text
    assert (await db.execute(select(Asset).where(Asset.id == asset.id))).scalar_one_or_none() is not None


async def test_delete_asset_with_attachments_is_blocked(admin_client, db):
    model, status = await _make_catalog(db)
    asset = Asset(asset_tag="IT-DEL3", model_id=model.id, status_label_id=status.id)
    db.add(asset)
    await db.flush()
    db.add(
        Attachment(
            entity_type="asset",
            entity_id=str(asset.id),
            original_filename="manual.pdf",
            stored_filename="deadbeef.pdf",
            size_bytes=10,
            uploaded_by=await _breakglass_id(db),
        )
    )
    await db.commit()

    resp = await admin_client.post(f"/assets/{asset.id}/delete")
    assert resp.status_code == 200
    assert "text-bg-danger" in resp.text
    assert "attachment" in resp.text
    assert (await db.execute(select(Asset).where(Asset.id == asset.id))).scalar_one_or_none() is not None


async def test_cannot_set_status_to_deployed_directly(admin_client, db):
    model, status = await _make_catalog(db)
    deployed = StatusLabel(name="Deployed", status_type=StatusType.deployed)
    db.add(deployed)
    await db.commit()

    resp = await admin_client.post(
        "/assets/create",
        data={"model_id": model.id, "status_label_id": deployed.id},
    )
    assert resp.status_code == 200
    assert "text-bg-danger" in resp.text
    assert "checkout" in resp.text.lower()
