"""Shared helpers for every Phase 9 module mapper.

Every mapper writes a V1ImportRow for EVERY v1 source row it looks at,
in both dry-run and real runs -- that history is what the wizard's
batch view shows afterward, per the confirmed design
(core_v1_import_batches.dry_run and V1ImportRow.is_dry_run exist
specifically so a dry run's results are still inspectable after the
fact, not just in the one HTTP response). Only the TARGET tables
(Users, Departments, Assets, ...) are skipped in dry-run mode -- see
resolve_or_plan_department/_location below for the pattern every
mapper's own get-or-create logic follows.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import Asset, Department, ImportRowOutcome, Location, V1ImportBatch, V1ImportRow


async def record_row(
    db: AsyncSession,
    batch: V1ImportBatch,
    v1_table: str,
    v1_id: int,
    v2_entity_type: str,
    v2_entity_id: int | None,
    outcome: ImportRowOutcome,
    detail: str | None = None,
) -> None:
    db.add(
        V1ImportRow(
            batch_id=batch.id,
            is_dry_run=batch.dry_run,
            v1_table=v1_table,
            v1_id=v1_id,
            v2_entity_type=v2_entity_type,
            v2_entity_id=v2_entity_id,
            outcome=outcome,
            detail=detail,
        )
    )


async def resolve_or_plan_department(
    db: AsyncSession, cache: dict, name: str, company_id: int | None, dry_run: bool
) -> tuple[int | None, bool]:
    """Case-insensitive dedup on (name, company_id) -- matches Department's
    own uniqueness scope. Returns (id, was_newly_created_or_would_be).
    In dry-run, a not-found name returns (None, True): "would create",
    nothing actually written, since nothing downstream in dry-run mode
    holds a real FK to point at it anyway (the row that would reference
    it is never written either)."""
    key = (name.strip().lower(), company_id)
    if key in cache:
        return cache[key], False
    stmt = select(Department).where(func.lower(Department.name) == key[0])
    stmt = (
        stmt.where(Department.company_id.is_(None))
        if company_id is None
        else stmt.where(Department.company_id == company_id)
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        cache[key] = existing.id
        return existing.id, False
    if dry_run:
        cache[key] = None
        return None, True
    dept = Department(name=name.strip(), company_id=company_id)
    db.add(dept)
    await db.flush()
    cache[key] = dept.id
    return dept.id, True


async def resolve_or_plan_location(db: AsyncSession, cache: dict, name: str, dry_run: bool) -> tuple[int | None, bool]:
    """Case-insensitive dedup, globally unique (Location has no company axis,
    unlike Department)."""
    key = name.strip().lower()
    if key in cache:
        return cache[key], False
    existing = (await db.execute(select(Location).where(func.lower(Location.name) == key))).scalar_one_or_none()
    if existing is not None:
        cache[key] = existing.id
        return existing.id, False
    if dry_run:
        cache[key] = None
        return None, True
    loc = Location(name=name.strip())
    db.add(loc)
    await db.flush()
    cache[key] = loc.id
    return loc.id, True


async def v2_entity_id_for_v1_row(db: AsyncSession, v1_table: str, v1_id: int) -> int | None:
    """Looks up which v2 entity a v1 (table, id) pair was imported to, via
    the generic V1ImportRow trail -- the traceability mechanism doubling
    as a cross-mapper join, so e.g. equipment's lending_records (needing
    the v2 asset for a v1 equipment_id) or it_assets (needing the v2 user
    for a v1 assigned_user_id) never need their own copy of "have I seen
    this v1 row before"."""
    return (
        await db.execute(
            select(V1ImportRow.v2_entity_id)
            .where(
                V1ImportRow.v1_table == v1_table,
                V1ImportRow.v1_id == v1_id,
                V1ImportRow.is_dry_run.is_(False),
                V1ImportRow.v2_entity_id.is_not(None),
            )
            .order_by(V1ImportRow.created_at.desc())
            .limit(1)
        )
    ).scalars().first()


async def next_asset_tag(db: AsyncSession, prefix: str, pad: int) -> str:
    """Same algorithm as app/routers/assets.py's _next_asset_tag --
    duplicated rather than imported, since routers depend on core
    modules and not the reverse (see CLAUDE.md). Safe to call once per
    row inside a mapper's loop because each created asset is flushed
    before the next row is processed, so the next call's own SELECT
    already sees it."""
    tags = (await db.execute(select(Asset.asset_tag).where(Asset.asset_tag.like(f"{prefix}%")))).scalars().all()
    max_n = 0
    for tag in tags:
        suffix = tag[len(prefix):]
        if suffix.isdigit():
            max_n = max(max_n, int(suffix))
    return f"{prefix}{max_n + 1:0{pad}d}"
