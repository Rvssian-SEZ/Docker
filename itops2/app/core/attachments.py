"""Shared attachment storage helpers, used by assets, maintenance
records, contracts, and (Phase 8 refinement) model/asset photos —
entity_type='asset' / 'maintenance' / 'contract' / 'model', all against
the same core_attachments polymorphic table. See CLAUDE.md for why
attachments use this generic entity_type/entity_id style rather than
per-entity FK columns (unlike checkout targets).

Disk layout: {attachments_dir}/{entity_type}/{entity_id}/{stored_filename}
— entity_type used raw, no pluralization. Image uploads additionally get
a thumbnail generated once, at upload time (not resized on every list
render — a 50-row list each serving a multi-MB phone photo on the fly
would be exactly the kind of v1 sluggishness this app's performance
requirement exists to avoid), stored alongside the original under
.../thumbs/{stem}.jpg.
"""

import uuid
from pathlib import Path

from fastapi import UploadFile
from PIL import Image

from app.core.config import get_settings

MAX_ATTACHMENT_SIZE = 25 * 1024 * 1024  # 25 MB
THUMBNAIL_MAX_SIZE = (200, 200)


def attachment_dir(entity_type: str, entity_id: str) -> Path:
    return Path(get_settings().attachments_dir) / entity_type / entity_id


def thumbnail_path(entity_type: str, entity_id: str, stored_filename: str) -> Path:
    stem = Path(stored_filename).stem
    return attachment_dir(entity_type, entity_id) / "thumbs" / f"{stem}.jpg"


def _make_thumbnail(source: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as img:
        img.thumbnail(THUMBNAIL_MAX_SIZE)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")  # JPEG has no alpha channel
        img.save(dest, format="JPEG", quality=85)


async def save_upload(upload: UploadFile, entity_type: str, entity_id: str) -> tuple[str, int, str | None]:
    """Streams the upload to disk under a UUID-based name (never trust the
    original filename for the on-disk path — traversal/collision safety).
    If the content type is an image, also generates a thumbnail. A file
    that claims to be an image but isn't (or is corrupt) still saves fine
    as a regular attachment — thumbnail generation is best-effort and
    silently skipped on failure, never a reason to reject the upload.
    Returns (stored_filename, size_bytes, error)."""
    ext = Path(upload.filename or "").suffix
    stored_name = f"{uuid.uuid4()}{ext}"
    directory = attachment_dir(entity_type, entity_id)
    directory.mkdir(parents=True, exist_ok=True)
    dest = directory / stored_name
    size = 0
    with dest.open("wb") as f:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_ATTACHMENT_SIZE:
                f.close()
                dest.unlink(missing_ok=True)
                return "", 0, f"File too large (max {MAX_ATTACHMENT_SIZE // (1024 * 1024)} MB)."
            f.write(chunk)

    if (upload.content_type or "").startswith("image/"):
        try:
            _make_thumbnail(dest, thumbnail_path(entity_type, entity_id, stored_name))
        except Exception:
            # Deliberately broad: a corrupt/truncated image (real users do
            # upload these) raises whatever PIL feels like for that failure
            # mode -- UnidentifiedImageError for an unrecognized format, a
            # plain OSError for a truncated file, or even a bare SyntaxError
            # from a PNG chunk parser choking mid-file (caught the hard way:
            # a malformed test upload 500'd the whole request because
            # SyntaxError isn't a subclass of either of the two originally
            # caught here). None of PIL's failure modes should ever turn
            # into a failed attachment upload -- thumbnailing is strictly
            # best-effort.
            pass

    return stored_name, size, None
