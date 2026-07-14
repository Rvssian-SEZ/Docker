"""Two-level asset photos (post-Phase-8 refinement): a photo on the
MODEL shown as the default for every asset of that model, plus an
optional per-asset photo that overrides it for that one asset.

Both levels reuse the existing core_attachments polymorphic table
rather than a dedicated column on core_models/core_assets — one
mechanism, not two. "The photo" for a given entity is simply its most
recently uploaded image-type attachment (content_type starting with
"image/"); uploading a new one supersedes the old one for display
purposes without deleting it, the same non-destructive-by-default
pattern every other attachment in this app already follows. Chosen
over a dedicated `photo_filename` column because it needed zero schema
changes (core_attachments already accepts any entity_type string) and
keeps versioning/history "free" — reuploading a photo is just another
upload, recoverable from the entity's own attachment list.

Per-asset photos need no new upload UI at all: any image uploaded
through an asset's EXISTING attachment upload form automatically
becomes eligible. Model photos get a small dedicated upload/remove
widget (models.html has no attachments list UI to piggyback on, unlike
Assets — see catalog.py), which for simplicity keeps at most one image
attachment per model (uploading a new one deletes the previous).
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import Asset, Attachment


async def _latest_image_attachment(db: AsyncSession, entity_type: str, entity_id: str) -> Attachment | None:
    return (
        await db.execute(
            select(Attachment)
            .where(
                Attachment.entity_type == entity_type,
                Attachment.entity_id == entity_id,
                Attachment.content_type.ilike("image/%"),
            )
            .order_by(Attachment.uploaded_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def model_photo_attachment(db: AsyncSession, model_id: int) -> Attachment | None:
    return await _latest_image_attachment(db, "model", str(model_id))


async def asset_photo_attachment(db: AsyncSession, asset_id: int) -> Attachment | None:
    return await _latest_image_attachment(db, "asset", str(asset_id))


async def effective_asset_photo(db: AsyncSession, asset: Asset) -> Attachment | None:
    """The asset's own photo if it has one, else its model's photo."""
    own = await asset_photo_attachment(db, asset.id)
    if own is not None:
        return own
    return await model_photo_attachment(db, asset.model_id)
