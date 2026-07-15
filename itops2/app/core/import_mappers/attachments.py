"""Copies v1 files onto core_attachments: it_assets' single
photo_filename/photo_is_model_photo pair, and printer_attachments.

v1's photo_is_model_photo flag maps directly onto v2's own two-level
photo design (a model-level default photo + an optional per-asset
override, both just image-type core_attachments rows -- see
app/core/photos.py) -- photo_is_model_photo=true becomes
entity_type='model' against the asset's model_id, false becomes
entity_type='asset' against the asset itself. No new logic was needed
for this, v1's flag and v2's mechanism already agree.

Files are copied out of v1's READ-ONLY bind-mounted upload volumes
(import.v1_asset_uploads_path / import.v1_printer_uploads_path --
see the setup guide's import section for the temporary mount
procedure) via app/core/attachments.py's copy_from_disk(), the same
storage convention (UUID stored name, thumbnail-on-image) the live
upload routes already use. A dry run never touches the filesystem at
all -- it only checks the source file exists and reports what it
would copy, exactly mirroring how every other mapper in this package
skips its target-table writes in dry-run mode.

A missing source file (deleted from disk in v1 but still referenced
in its DB row, or simply not present under the mounted path) is
flagged, never a reason to fail the whole batch.
"""

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.attachments import copy_from_disk
from app.core.import_mappers.common import record_row, v2_entity_id_for_v1_row
from app.core.models import Asset, Attachment, ImportRowOutcome, V1ImportBatch
from app.core.settings_store import SettingsStore


async def import_asset_photos(db: AsyncSession, source, batch: V1ImportBatch, store: SettingsStore) -> None:
    dry_run = batch.dry_run
    uploads_dir = store.get("import.v1_asset_uploads_path")

    rows = await source.fetch("SELECT id, photo_filename, photo_is_model_photo FROM it_assets ORDER BY id")
    for row in rows:
        if not row["photo_filename"]:
            continue

        # A distinct v1_table namespace ("it_assets_photo", not "it_assets")
        # for THIS row's own tracking -- the it_assets mapper already owns
        # one (v1_table="it_assets", v1_id=row["id"]) slot in the partial
        # unique index for the asset itself; reusing it here for the photo
        # would collide on the very same key the moment both are 'created'.
        asset_id = await v2_entity_id_for_v1_row(db, "it_assets", row["id"])
        if asset_id is None:
            await record_row(
                db, batch, "it_assets_photo", row["id"], "attachment", None, ImportRowOutcome.flagged,
                "asset has no imported v2 asset -- run the it_assets module first",
            )
            continue

        asset = await db.get(Asset, asset_id)
        is_model_photo = bool(row["photo_is_model_photo"])
        entity_type = "model" if is_model_photo else "asset"
        entity_id = str(asset.model_id) if is_model_photo else str(asset.id)

        source_path = Path(uploads_dir) / row["photo_filename"]
        if not source_path.is_file():
            await record_row(
                db, batch, "it_assets_photo", row["id"], "attachment", None, ImportRowOutcome.flagged,
                f"photo file not found under import.v1_asset_uploads_path: {row['photo_filename']}",
            )
            continue

        if dry_run:
            await record_row(
                db, batch, "it_assets_photo", row["id"], "attachment", None, ImportRowOutcome.created,
                f"would copy photo '{row['photo_filename']}' to {entity_type}/{entity_id}",
            )
            continue

        stored_name, size, error = copy_from_disk(source_path, entity_type, entity_id)
        if error:
            await record_row(db, batch, "it_assets_photo", row["id"], "attachment", None, ImportRowOutcome.flagged, error)
            continue

        attachment = Attachment(
            entity_type=entity_type,
            entity_id=entity_id,
            original_filename=row["photo_filename"],
            stored_filename=stored_name,
            size_bytes=size,
            uploaded_by=batch.started_by,
        )
        db.add(attachment)
        await db.flush()
        await record_row(
            db, batch, "it_assets_photo", row["id"], "attachment", attachment.id, ImportRowOutcome.created,
            f"copied photo to {entity_type}/{entity_id}",
        )


async def import_printer_attachments(db: AsyncSession, source, batch: V1ImportBatch, store: SettingsStore) -> None:
    dry_run = batch.dry_run
    uploads_dir = store.get("import.v1_printer_uploads_path")

    rows = await source.fetch(
        "SELECT id, printer_id, filename, original_filename, mime_type, uploaded_at, uploaded_by_id "
        "FROM printer_attachments ORDER BY id"
    )
    for row in rows:
        asset_id = await v2_entity_id_for_v1_row(db, "printers", row["printer_id"])
        if asset_id is None:
            await record_row(
                db, batch, "printer_attachments", row["id"], "attachment", None, ImportRowOutcome.flagged,
                f"printer {row['printer_id']} has no imported v2 asset -- run the printers module first",
            )
            continue

        source_path = Path(uploads_dir) / row["filename"]
        if not source_path.is_file():
            await record_row(
                db, batch, "printer_attachments", row["id"], "attachment", None, ImportRowOutcome.flagged,
                f"file not found under import.v1_printer_uploads_path: {row['filename']}",
            )
            continue

        if dry_run:
            await record_row(
                db, batch, "printer_attachments", row["id"], "attachment", None, ImportRowOutcome.created,
                f"would copy '{row['filename']}' to asset/{asset_id}",
            )
            continue

        stored_name, size, error = copy_from_disk(source_path, "asset", str(asset_id), row["mime_type"])
        if error:
            await record_row(
                db, batch, "printer_attachments", row["id"], "attachment", None, ImportRowOutcome.flagged, error
            )
            continue

        uploaded_by = None
        if row["uploaded_by_id"]:
            uploaded_by = await v2_entity_id_for_v1_row(db, "users", row["uploaded_by_id"])

        attachment = Attachment(
            entity_type="asset",
            entity_id=str(asset_id),
            original_filename=row["original_filename"] or row["filename"],
            stored_filename=stored_name,
            content_type=row["mime_type"] or None,
            size_bytes=size,
            uploaded_by=uploaded_by or batch.started_by,
            uploaded_at=row["uploaded_at"] or datetime.now(timezone.utc),
        )
        db.add(attachment)
        await db.flush()
        await record_row(
            db, batch, "printer_attachments", row["id"], "attachment", attachment.id, ImportRowOutcome.created,
            f"copied attachment to asset/{asset_id}",
        )
