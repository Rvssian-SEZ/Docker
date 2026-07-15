"""app/core/import_mappers/attachments.py -- copying v1 asset photos
and printer_attachments onto core_attachments, out of a (test-local
stand-in for the) read-only bind-mounted v1 upload volume."""

import tempfile
from pathlib import Path

from sqlalchemy import select

from app.core.import_mappers.attachments import import_asset_photos, import_printer_attachments
from app.core.models import (
    AssetModel, Asset, Attachment, Category, ImportRowOutcome, Manufacturer, StatusLabel, StatusType,
    V1ImportRow,
)
from app.core.settings_store import SettingsStore
from tests.conftest import FakeV1Source, make_import_batch


async def _make_asset(db, tag="IT-0001"):
    mfr = Manufacturer(name=f"Mfr-{tag}")
    cat = Category(name=f"Cat-{tag}")
    db.add_all([mfr, cat])
    await db.flush()
    model = AssetModel(name=f"Model-{tag}", manufacturer_id=mfr.id, category_id=cat.id)
    status = StatusLabel(name=f"Status-{tag}", status_type=StatusType.deployable)
    db.add_all([model, status])
    await db.flush()
    asset = Asset(asset_tag=tag, model_id=model.id, status_label_id=status.id)
    db.add(asset)
    await db.flush()
    return asset


async def _tag_it_asset_imported(db, batch, v1_id, v2_asset_id):
    db.add(
        V1ImportRow(
            batch_id=batch.id, v1_table="it_assets", v1_id=v1_id, v2_entity_type="asset",
            v2_entity_id=v2_asset_id, outcome=ImportRowOutcome.created,
        )
    )
    await db.flush()


async def _tag_printer_imported(db, batch, v1_id, v2_asset_id):
    db.add(
        V1ImportRow(
            batch_id=batch.id, v1_table="printers", v1_id=v1_id, v2_entity_type="asset",
            v2_entity_id=v2_asset_id, outcome=ImportRowOutcome.created,
        )
    )
    await db.flush()


async def test_asset_photo_copied_as_model_photo_when_flagged(db):
    upload_dir = tempfile.mkdtemp()
    (Path(upload_dir) / "photo1.jpg").write_bytes(b"fake-jpeg-bytes")

    asset = await _make_asset(db, "IT-P1")
    batch = await make_import_batch(db)
    await _tag_it_asset_imported(db, batch, 1, asset.id)

    store = SettingsStore({"import.v1_asset_uploads_path": upload_dir})
    row = {"id": 1, "photo_filename": "photo1.jpg", "photo_is_model_photo": True}
    await import_asset_photos(db, FakeV1Source({"FROM it_assets": [row]}), batch, store)
    await db.commit()

    att = (await db.execute(select(Attachment).where(Attachment.entity_type == "model"))).scalar_one()
    assert att.entity_id == str(asset.model_id)
    assert att.original_filename == "photo1.jpg"

    import_row = (
        await db.execute(select(V1ImportRow).where(V1ImportRow.v1_table == "it_assets_photo", V1ImportRow.v1_id == 1))
    ).scalars().all()
    assert any(r.outcome == ImportRowOutcome.created and r.v2_entity_id == att.id for r in import_row)


async def test_asset_photo_copied_as_asset_photo_when_not_flagged(db):
    upload_dir = tempfile.mkdtemp()
    (Path(upload_dir) / "photo2.jpg").write_bytes(b"fake-jpeg-bytes")

    asset = await _make_asset(db, "IT-P2")
    batch = await make_import_batch(db)
    await _tag_it_asset_imported(db, batch, 2, asset.id)

    store = SettingsStore({"import.v1_asset_uploads_path": upload_dir})
    row = {"id": 2, "photo_filename": "photo2.jpg", "photo_is_model_photo": False}
    await import_asset_photos(db, FakeV1Source({"FROM it_assets": [row]}), batch, store)
    await db.commit()

    att = (await db.execute(select(Attachment).where(Attachment.entity_type == "asset"))).scalar_one()
    assert att.entity_id == str(asset.id)


async def test_asset_photo_missing_file_is_flagged(db):
    upload_dir = tempfile.mkdtemp()
    asset = await _make_asset(db, "IT-P3")
    batch = await make_import_batch(db)
    await _tag_it_asset_imported(db, batch, 3, asset.id)

    store = SettingsStore({"import.v1_asset_uploads_path": upload_dir})
    row = {"id": 3, "photo_filename": "does-not-exist.jpg", "photo_is_model_photo": False}
    await import_asset_photos(db, FakeV1Source({"FROM it_assets": [row]}), batch, store)
    await db.commit()

    import_row = (
        await db.execute(select(V1ImportRow).where(V1ImportRow.v1_table == "it_assets_photo", V1ImportRow.v1_id == 3))
    ).scalar_one()
    assert import_row.outcome == ImportRowOutcome.flagged
    assert "not found" in import_row.detail


async def test_asset_photo_dry_run_copies_nothing(db):
    upload_dir = tempfile.mkdtemp()
    (Path(upload_dir) / "photo4.jpg").write_bytes(b"fake-jpeg-bytes")

    asset = await _make_asset(db, "IT-P4")
    batch = await make_import_batch(db, dry_run=True)
    await _tag_it_asset_imported(db, batch, 4, asset.id)

    store = SettingsStore({"import.v1_asset_uploads_path": upload_dir})
    row = {"id": 4, "photo_filename": "photo4.jpg", "photo_is_model_photo": False}
    await import_asset_photos(db, FakeV1Source({"FROM it_assets": [row]}), batch, store)
    await db.commit()

    assert (await db.execute(select(Attachment))).scalar_one_or_none() is None
    import_row = (
        await db.execute(select(V1ImportRow).where(V1ImportRow.v1_table == "it_assets_photo", V1ImportRow.v1_id == 4))
    ).scalar_one()
    assert import_row.is_dry_run is True
    assert import_row.outcome == ImportRowOutcome.created


async def test_asset_photo_with_no_v2_asset_match_is_flagged(db):
    upload_dir = tempfile.mkdtemp()
    (Path(upload_dir) / "photo5.jpg").write_bytes(b"x")
    batch = await make_import_batch(db)
    store = SettingsStore({"import.v1_asset_uploads_path": upload_dir})
    row = {"id": 5, "photo_filename": "photo5.jpg", "photo_is_model_photo": False}
    await import_asset_photos(db, FakeV1Source({"FROM it_assets": [row]}), batch, store)
    await db.commit()

    import_row = (
        await db.execute(select(V1ImportRow).where(V1ImportRow.v1_table == "it_assets_photo", V1ImportRow.v1_id == 5))
    ).scalar_one()
    assert import_row.outcome == ImportRowOutcome.flagged
    assert "it_assets module first" in import_row.detail


async def test_printer_attachment_copied(db):
    upload_dir = tempfile.mkdtemp()
    (Path(upload_dir) / "manual.pdf").write_bytes(b"%PDF-fake")

    asset = await _make_asset(db, "IT-PR1")
    batch = await make_import_batch(db)
    await _tag_printer_imported(db, batch, 10, asset.id)

    store = SettingsStore({"import.v1_printer_uploads_path": upload_dir})
    row = {
        "id": 1, "printer_id": 10, "filename": "manual.pdf", "original_filename": "Printer Manual.pdf",
        "mime_type": "application/pdf", "uploaded_at": None, "uploaded_by_id": None,
    }
    await import_printer_attachments(db, FakeV1Source({"FROM printer_attachments": [row]}), batch, store)
    await db.commit()

    att = (await db.execute(select(Attachment).where(Attachment.entity_id == str(asset.id)))).scalar_one()
    assert att.original_filename == "Printer Manual.pdf"
    assert att.content_type == "application/pdf"
    assert att.uploaded_by == batch.started_by  # no v1 uploader match -> falls back to the importing admin


async def test_printer_attachment_for_unimported_printer_is_flagged(db):
    upload_dir = tempfile.mkdtemp()
    batch = await make_import_batch(db)
    store = SettingsStore({"import.v1_printer_uploads_path": upload_dir})
    row = {
        "id": 2, "printer_id": 999, "filename": "x.pdf", "original_filename": "x.pdf",
        "mime_type": None, "uploaded_at": None, "uploaded_by_id": None,
    }
    await import_printer_attachments(db, FakeV1Source({"FROM printer_attachments": [row]}), batch, store)
    await db.commit()

    import_row = (
        await db.execute(select(V1ImportRow).where(V1ImportRow.v1_table == "printer_attachments"))
    ).scalar_one()
    assert import_row.outcome == ImportRowOutcome.flagged
    assert "printers module first" in import_row.detail
