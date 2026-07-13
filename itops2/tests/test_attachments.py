"""Attachments: upload writes a real file to disk + a DB row, download
serves it back, delete removes both, and archived assets reject
upload/delete.
"""

from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.core.models import Asset, AssetModel, Attachment, Category, Manufacturer, StatusLabel, StatusType


async def _make_catalog(db):
    mfr = Manufacturer(name="Dell")
    cat = Category(name="Laptop")
    db.add_all([mfr, cat])
    await db.flush()
    model = AssetModel(name="Latitude 5440", manufacturer_id=mfr.id, category_id=cat.id)
    deployable = StatusLabel(name="Ready to Deploy", status_type=StatusType.deployable)
    archived = StatusLabel(name="Archived", status_type=StatusType.archived)
    db.add_all([model, deployable, archived])
    await db.commit()
    return model, deployable, archived


async def _make_asset(db, tag="IT-AT01"):
    model, deployable, archived = await _make_catalog(db)
    asset = Asset(asset_tag=tag, model_id=model.id, status_label_id=deployable.id)
    db.add(asset)
    await db.commit()
    return asset, deployable, archived


async def test_upload_writes_file_and_row(admin_client, db):
    asset, *_ = await _make_asset(db)
    resp = await admin_client.post(
        f"/assets/{asset.id}/attachments",
        files={"file": ("manual.txt", b"hello world", "text/plain")},
        data={"description": "user manual"},
    )
    assert resp.status_code == 204

    att = (
        await db.execute(select(Attachment).where(Attachment.entity_id == str(asset.id)))
    ).scalar_one()
    assert att.original_filename == "manual.txt"
    assert att.size_bytes == len(b"hello world")
    assert att.description == "user manual"

    on_disk = Path(get_settings().attachments_dir) / "asset" / str(asset.id) / att.stored_filename
    assert on_disk.exists()
    assert on_disk.read_bytes() == b"hello world"


async def test_download_returns_original_content_and_filename(admin_client, db):
    asset, *_ = await _make_asset(db)
    await admin_client.post(
        f"/assets/{asset.id}/attachments",
        files={"file": ("report.csv", b"a,b,c\n1,2,3", "text/csv")},
    )
    att = (
        await db.execute(select(Attachment).where(Attachment.entity_id == str(asset.id)))
    ).scalar_one()

    resp = await admin_client.get(f"/assets/{asset.id}/attachments/{att.id}/download")
    assert resp.status_code == 200
    assert resp.content == b"a,b,c\n1,2,3"
    assert "report.csv" in resp.headers["content-disposition"]


async def test_delete_removes_row_and_file(admin_client, db):
    asset, *_ = await _make_asset(db)
    await admin_client.post(
        f"/assets/{asset.id}/attachments", files={"file": ("x.txt", b"data", "text/plain")},
    )
    att = (
        await db.execute(select(Attachment).where(Attachment.entity_id == str(asset.id)))
    ).scalar_one()
    on_disk = Path(get_settings().attachments_dir) / "asset" / str(asset.id) / att.stored_filename
    assert on_disk.exists()

    resp = await admin_client.post(f"/assets/{asset.id}/attachments/{att.id}/delete")
    assert resp.status_code == 204
    assert (await db.execute(select(Attachment).where(Attachment.id == att.id))).scalar_one_or_none() is None
    assert not on_disk.exists()


async def test_attachment_blocks_hard_delete_end_to_end(admin_client, db):
    """Full-stack version of the Chunk-3 guard test: upload for real via
    HTTP, then confirm the asset can't be hard-deleted."""
    asset, *_ = await _make_asset(db)
    await admin_client.post(
        f"/assets/{asset.id}/attachments", files={"file": ("x.txt", b"data", "text/plain")},
    )
    resp = await admin_client.post(f"/assets/{asset.id}/delete")
    assert resp.status_code == 200
    assert "text-bg-danger" in resp.text
    assert "attachment" in resp.text.lower()
    assert (await db.execute(select(Asset).where(Asset.id == asset.id))).scalar_one_or_none() is not None


async def test_upload_rejected_on_archived_asset(admin_client, db):
    asset, deployable, archived = await _make_asset(db)
    asset.status_label_id = archived.id
    await db.commit()

    resp = await admin_client.post(
        f"/assets/{asset.id}/attachments", files={"file": ("x.txt", b"data", "text/plain")},
    )
    assert "text-bg-danger" in resp.text
    assert "archived" in resp.text.lower()

    count = (
        await db.execute(select(Attachment).where(Attachment.entity_id == str(asset.id)))
    ).all()
    assert count == []


async def test_download_wrong_asset_id_is_404(admin_client, db):
    model, deployable, _archived = await _make_catalog(db)
    asset = Asset(asset_tag="IT-AT01", model_id=model.id, status_label_id=deployable.id)
    other = Asset(asset_tag="IT-AT02", model_id=model.id, status_label_id=deployable.id)
    db.add_all([asset, other])
    await db.commit()

    await admin_client.post(
        f"/assets/{asset.id}/attachments", files={"file": ("x.txt", b"data", "text/plain")},
    )
    att = (
        await db.execute(select(Attachment).where(Attachment.entity_id == str(asset.id)))
    ).scalar_one()

    resp = await admin_client.get(f"/assets/{other.id}/attachments/{att.id}/download")
    assert resp.status_code == 404
