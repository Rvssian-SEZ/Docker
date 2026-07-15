"""Manufacturer/Category/Model/StatusLabel synthesis shared by every v1
module that imports onto core_assets (it_assets, equipment, printers).

v1 tracked manufacturer/model as free text with real inconsistency
(blank on several rows, casing drift like "APPLE" vs "ASUS" -- observed
live before writing this). v2 requires Manufacturer -> Category ->
Model as first-class Catalog rows, so each gets synthesized here:
case-insensitive dedup so "APPLE" and "Apple" collapse to one row, and
a placeholder name ("Unknown Manufacturer" / "Unknown Model") when v1
left the field blank -- never a made-up specific value, since that
would be a guess presented as fact.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import AssetModel, Category, Manufacturer, StatusLabel, StatusType

UNKNOWN_MANUFACTURER = "Unknown Manufacturer"
UNKNOWN_MODEL = "Unknown Model"

# v1 it_assets.category is a fixed enum; each value becomes a Category
# row with a nicer display name (also how "printer" -> "Printer" lines
# up with the Printers page's own category-name match).
V1_ASSET_CATEGORY_NAMES = {
    "laptop": "Laptop", "desktop": "Desktop", "monitor": "Monitor", "phone": "Phone",
    "tablet": "Tablet", "printer": "Printer", "networking": "Networking", "server": "Server",
    "peripheral": "Peripheral", "other": "Other",
}


async def resolve_or_plan_manufacturer(db: AsyncSession, cache: dict, name: str | None, dry_run: bool) -> tuple[int | None, bool]:
    clean = (name or "").strip() or UNKNOWN_MANUFACTURER
    key = clean.lower()
    if key in cache:
        return cache[key], False
    existing = (await db.execute(select(Manufacturer).where(func.lower(Manufacturer.name) == key))).scalar_one_or_none()
    if existing is not None:
        cache[key] = existing.id
        return existing.id, False
    if dry_run:
        cache[key] = None
        return None, True
    m = Manufacturer(name=clean)
    db.add(m)
    await db.flush()
    cache[key] = m.id
    return m.id, True


async def resolve_or_plan_category(db: AsyncSession, cache: dict, name: str, dry_run: bool) -> tuple[int | None, bool]:
    clean = name.strip()
    key = clean.lower()
    if key in cache:
        return cache[key], False
    existing = (await db.execute(select(Category).where(func.lower(Category.name) == key))).scalar_one_or_none()
    if existing is not None:
        cache[key] = existing.id
        return existing.id, False
    if dry_run:
        cache[key] = None
        return None, True
    c = Category(name=clean)
    db.add(c)
    await db.flush()
    cache[key] = c.id
    return c.id, True


async def resolve_or_plan_model(
    db: AsyncSession, cache: dict, manufacturer_id: int | None, category_id: int | None, name: str | None, dry_run: bool
) -> tuple[int | None, bool, str | None]:
    """Returns (model_id, was_created, mismatch_note). Model is unique on
    (name, manufacturer_id) only -- category isn't part of that
    uniqueness (a real (manufacturer, model) pair belongs to exactly one
    category in the real world). If a v1 row's synthesized category
    disagrees with an already-matched model's category, the existing
    model wins (never silently re-categorize a Catalog row from an
    import) and a note is returned for the caller to surface."""
    clean = (name or "").strip() or UNKNOWN_MODEL
    key = (clean.lower(), manufacturer_id)
    if key in cache:
        return cache[key][0], False, cache[key][1]
    if dry_run:
        # A dry-run manufacturer never got a real id -- nothing to look up
        # or create a model against, so just plan it as "would create".
        cache[key] = (None, None)
        return None, True, None
    stmt = select(AssetModel).where(
        func.lower(AssetModel.name) == key[0], AssetModel.manufacturer_id == manufacturer_id
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        note = None
        if category_id is not None and existing.category_id != category_id:
            note = f"model '{clean}' already exists under a different category -- kept its existing category"
        cache[key] = (existing.id, note)
        return existing.id, False, note
    if category_id is None:
        cache[key] = (None, None)
        return None, True, None
    model = AssetModel(name=clean, manufacturer_id=manufacturer_id, category_id=category_id)
    db.add(model)
    await db.flush()
    cache[key] = (model.id, None)
    return model.id, True, None


async def resolve_or_plan_status_label(
    db: AsyncSession, cache: dict, name: str, status_type: StatusType, dry_run: bool
) -> tuple[int | None, bool]:
    key = name.strip().lower()
    if key in cache:
        return cache[key], False
    existing = (await db.execute(select(StatusLabel).where(func.lower(StatusLabel.name) == key))).scalar_one_or_none()
    if existing is not None:
        cache[key] = existing.id
        return existing.id, False
    if dry_run:
        cache[key] = None
        return None, True
    label = StatusLabel(name=name.strip(), status_type=status_type)
    db.add(label)
    await db.flush()
    cache[key] = label.id
    return label.id, True
