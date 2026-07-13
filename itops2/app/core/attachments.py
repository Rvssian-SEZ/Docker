"""Shared attachment storage helpers, used by both assets and
maintenance records (entity_type='asset' / 'maintenance'), both against
the same core_attachments polymorphic table. See CLAUDE.md for why
attachments use this generic entity_type/entity_id style rather than
per-entity FK columns (unlike checkout targets).

Disk layout: {attachments_dir}/{entity_type}/{entity_id}/{stored_filename}
— entity_type used raw, no pluralization.
"""

import uuid
from pathlib import Path

from fastapi import UploadFile

from app.core.config import get_settings

MAX_ATTACHMENT_SIZE = 25 * 1024 * 1024  # 25 MB


def attachment_dir(entity_type: str, entity_id: str) -> Path:
    return Path(get_settings().attachments_dir) / entity_type / entity_id


async def save_upload(upload: UploadFile, entity_type: str, entity_id: str) -> tuple[str, int, str | None]:
    """Streams the upload to disk under a UUID-based name (never trust the
    original filename for the on-disk path — traversal/collision safety).
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
    return stored_name, size, None
