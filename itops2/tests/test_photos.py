"""Two-level asset photos (post-Phase-8 refinement): thumbnail
generation at upload time (not on every list render), the model-level
photo (dedicated upload/remove routes, replace-not-accumulate), the
per-asset override (reuses the existing attachment upload -- no new
route), and the effective-photo fallback (asset's own > model's).
"""

import io
from pathlib import Path

from PIL import Image
from sqlalchemy import select

from app.core.attachments import thumbnail_path
from app.core.config import get_settings
from app.core.models import Asset, AssetModel, Attachment, Category, Manufacturer, StatusLabel, StatusType


def _png_bytes(color=(255, 0, 0)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (400, 400), color).save(buf, format="PNG")
    return buf.getvalue()


async def _make_model(db, name="Latitude 5440"):
    mfr = Manufacturer(name=f"Mfr-{name}")
    cat = Category(name=f"Cat-{name}")
    db.add_all([mfr, cat])
    await db.flush()
    model = AssetModel(name=name, manufacturer_id=mfr.id, category_id=cat.id)
    db.add(model)
    await db.commit()
    return model


async def _make_asset(db, model, tag="IT-PH01"):
    status = StatusLabel(name=f"Status-{tag}", status_type=StatusType.deployable)
    db.add(status)
    await db.flush()
    asset = Asset(asset_tag=tag, model_id=model.id, status_label_id=status.id)
    db.add(asset)
    await db.commit()
    return asset


# ---- thumbnail generation on upload ----

async def test_image_upload_generates_thumbnail(admin_client, db):
    model = await _make_model(db)
    resp = await admin_client.post(
        f"/catalog/models/{model.id}/photo",
        files={"file": ("photo.png", _png_bytes(), "image/png")},
    )
    assert resp.status_code == 204

    att = (await db.execute(select(Attachment).where(Attachment.entity_type == "model"))).scalar_one()
    thumb = thumbnail_path("model", str(model.id), att.stored_filename)
    assert thumb.exists()
    with Image.open(thumb) as img:
        assert img.format == "JPEG"
        assert max(img.size) <= 200  # resized, not the 400x400 original


async def test_non_image_attachment_gets_no_thumbnail(admin_client, db):
    model = await _make_model(db)
    asset = await _make_asset(db, model)
    resp = await admin_client.post(
        f"/assets/{asset.id}/attachments",
        files={"file": ("manual.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert resp.status_code == 204

    att = (await db.execute(select(Attachment).where(Attachment.entity_id == str(asset.id)))).scalar_one()
    thumb = thumbnail_path("asset", str(asset.id), att.stored_filename)
    assert not thumb.exists()


async def test_corrupt_image_upload_does_not_500(admin_client, db):
    """Regression: a real upload of a byte-truncated PNG raised a bare
    SyntaxError from PIL's PNG chunk parser, which isn't a subclass of
    either UnidentifiedImageError or OSError -- the original except
    clause let it propagate and 500 the whole request. Thumbnailing must
    be strictly best-effort: the attachment itself still has to save
    even when PIL can't make sense of the "image"."""
    model = await _make_model(db)
    good_png = _png_bytes()
    truncated = good_png[: len(good_png) // 2]  # valid header, corrupt body

    resp = await admin_client.post(
        f"/catalog/models/{model.id}/photo",
        files={"file": ("corrupt.png", truncated, "image/png")},
    )
    assert resp.status_code == 204

    att = (await db.execute(select(Attachment).where(Attachment.entity_type == "model"))).scalar_one()
    thumb = thumbnail_path("model", str(model.id), att.stored_filename)
    assert not thumb.exists()  # best-effort: no thumbnail, but no crash either


# ---- model photo: upload, replace, delete ----

async def test_model_photo_upload_rejects_non_image(admin_client, db):
    model = await _make_model(db)
    resp = await admin_client.post(
        f"/catalog/models/{model.id}/photo",
        files={"file": ("doc.pdf", b"not an image", "application/pdf")},
    )
    assert "text-bg-danger" in resp.text
    assert "image" in resp.text.lower()


async def test_model_photo_replace_keeps_only_one(admin_client, db):
    model = await _make_model(db)
    first = await admin_client.post(
        f"/catalog/models/{model.id}/photo",
        files={"file": ("one.png", _png_bytes((255, 0, 0)), "image/png")},
    )
    assert first.status_code == 204
    first_att = (await db.execute(select(Attachment).where(Attachment.entity_type == "model"))).scalar_one()
    first_path = Path(get_settings().attachments_dir) / "model" / str(model.id) / first_att.stored_filename
    first_thumb = thumbnail_path("model", str(model.id), first_att.stored_filename)
    assert first_path.exists() and first_thumb.exists()

    second = await admin_client.post(
        f"/catalog/models/{model.id}/photo",
        files={"file": ("two.png", _png_bytes((0, 255, 0)), "image/png")},
    )
    assert second.status_code == 204

    rows = (await db.execute(select(Attachment).where(Attachment.entity_type == "model"))).scalars().all()
    assert len(rows) == 1
    assert rows[0].original_filename == "two.png"
    # the superseded file (original + thumbnail) is actually removed from disk
    assert not first_path.exists()
    assert not first_thumb.exists()


async def test_model_photo_delete_removes_row_and_files(admin_client, db):
    model = await _make_model(db)
    await admin_client.post(
        f"/catalog/models/{model.id}/photo", files={"file": ("photo.png", _png_bytes(), "image/png")},
    )
    att = (await db.execute(select(Attachment).where(Attachment.entity_type == "model"))).scalar_one()
    path = Path(get_settings().attachments_dir) / "model" / str(model.id) / att.stored_filename
    thumb = thumbnail_path("model", str(model.id), att.stored_filename)
    assert path.exists() and thumb.exists()

    resp = await admin_client.post(f"/catalog/models/{model.id}/photo/delete")
    assert resp.status_code == 204
    assert (await db.execute(select(Attachment).where(Attachment.entity_type == "model"))).first() is None
    assert not path.exists()
    assert not thumb.exists()


async def test_model_photo_delete_with_no_photo_is_a_friendly_noop(admin_client, db):
    model = await _make_model(db)
    resp = await admin_client.post(f"/catalog/models/{model.id}/photo/delete")
    assert "text-bg-danger" in resp.text
    assert "no photo" in resp.text.lower()


# ---- serving routes ----

async def test_model_photo_thumbnail_and_full_serve_after_upload(admin_client, db):
    model = await _make_model(db)
    await admin_client.post(
        f"/catalog/models/{model.id}/photo", files={"file": ("photo.png", _png_bytes(), "image/png")},
    )
    thumb_resp = await admin_client.get(f"/catalog/models/{model.id}/photo/thumbnail")
    assert thumb_resp.status_code == 200
    assert thumb_resp.headers["content-type"] == "image/jpeg"

    full_resp = await admin_client.get(f"/catalog/models/{model.id}/photo/full")
    assert full_resp.status_code == 200
    assert full_resp.headers["content-type"] == "image/png"


async def test_model_photo_routes_404_with_no_photo(admin_client, db):
    model = await _make_model(db)
    assert (await admin_client.get(f"/catalog/models/{model.id}/photo/thumbnail")).status_code == 404
    assert (await admin_client.get(f"/catalog/models/{model.id}/photo/full")).status_code == 404


# ---- effective asset photo: asset overrides model ----

async def test_asset_photo_falls_back_to_model_photo(admin_client, db):
    model = await _make_model(db)
    asset = await _make_asset(db, model)
    await admin_client.post(
        f"/catalog/models/{model.id}/photo", files={"file": ("model.png", _png_bytes((10, 20, 30)), "image/png")},
    )

    resp = await admin_client.get(f"/assets/{asset.id}/photo/thumbnail")
    assert resp.status_code == 200


async def test_assets_own_image_attachment_overrides_model_photo(admin_client, db):
    model = await _make_model(db)
    asset = await _make_asset(db, model)
    await admin_client.post(
        f"/catalog/models/{model.id}/photo", files={"file": ("model.png", _png_bytes((10, 20, 30)), "image/png")},
    )
    await admin_client.post(
        f"/assets/{asset.id}/attachments",
        files={"file": ("asset-own.png", _png_bytes((200, 100, 50)), "image/png")},
    )

    resp = await admin_client.get(f"/assets/{asset.id}/photo/full")
    assert resp.status_code == 200
    with Image.open(io.BytesIO(resp.content)) as img:
        assert img.getpixel((0, 0)) == (200, 100, 50)  # the asset's own photo, not the model's


async def test_assets_non_image_attachment_does_not_count_as_photo(admin_client, db):
    """A PDF manual attached to an asset must not shadow the model's
    photo -- only image-type attachments are eligible."""
    model = await _make_model(db)
    asset = await _make_asset(db, model)
    await admin_client.post(
        f"/catalog/models/{model.id}/photo", files={"file": ("model.png", _png_bytes(), "image/png")},
    )
    await admin_client.post(
        f"/assets/{asset.id}/attachments", files={"file": ("manual.pdf", b"fake pdf", "application/pdf")},
    )

    resp = await admin_client.get(f"/assets/{asset.id}/photo/thumbnail")
    assert resp.status_code == 200  # still resolves -- falls through to the model's photo


async def test_asset_photo_routes_404_with_no_photo_anywhere(admin_client, db):
    model = await _make_model(db)
    asset = await _make_asset(db, model)
    assert (await admin_client.get(f"/assets/{asset.id}/photo/thumbnail")).status_code == 404
    assert (await admin_client.get(f"/assets/{asset.id}/photo/full")).status_code == 404
