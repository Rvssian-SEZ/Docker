"""Maps v1 `equipment` (+ its full `lending_records` history) to
core_assets + core_checkouts.

Unlike it_assets, v1 equipment has no manufacturer field at all --
every row gets the "Unknown Manufacturer" placeholder (see
catalog.py). category is synthesized directly from equipment.category
free text (no fixed enum to translate here, unlike it_assets), and the
Catalog Model itself is synthesized from equipment.name (e.g.
"Conference Room Projector") since v1 has no separate model field to
distinguish name from model for this table.

Checkout state is derived ENTIRELY from lending_records, not
equipment.status -- v1 has two overlapping signals for "is this on
loan" (the status enum AND an open lending_records row) and trusting
lending_records alone avoids a dual-source-of-truth bug if they ever
disagree in the real data. import_equipment() always creates the asset
in a non-deployed status (available/maintenance/retired); a later call
to import_lending_records() replays every lend/return cycle as its own
core_checkouts row and flips the asset to deployed if the last one is
still open -- matching this app's own checkout ledger being append-
only HISTORY, not a current-state snapshot. v1 has no record of what
status equipment returned TO on a historical checkin (its status enum
has no "returned to X" concept), so every historical return is
recorded against "Available", the only status v1 equipment reasonably
returns to -- noted in that checkout's own row's detail.
"""

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.import_mappers.catalog import (
    UNKNOWN_MANUFACTURER,
    resolve_or_plan_category,
    resolve_or_plan_model,
    resolve_or_plan_status_label,
)
from app.core.import_mappers.common import (
    next_asset_tag,
    record_row,
    resolve_or_plan_location,
    v2_entity_id_for_v1_row,
)
from app.core.models import Asset, Checkout, ImportRowOutcome, Manufacturer, StatusType, V1ImportBatch
from app.core.settings_store import SettingsStore

EQUIPMENT_STATUS_PLAN = {
    "available": ("Available", StatusType.deployable),
    "on_loan": ("Available", StatusType.deployable),  # corrected by import_lending_records if still open
    "maintenance": ("In Maintenance", StatusType.pending),
    "retired": ("Retired", StatusType.archived),
}


async def _unknown_manufacturer_id(db: AsyncSession, cache: dict, dry_run: bool) -> int | None:
    key = UNKNOWN_MANUFACTURER.lower()
    if key in cache:
        return cache[key]
    existing = (await db.execute(select(Manufacturer).where(func.lower(Manufacturer.name) == key))).scalar_one_or_none()
    if existing is not None:
        cache[key] = existing.id
        return existing.id
    if dry_run:
        cache[key] = None
        return None
    m = Manufacturer(name=UNKNOWN_MANUFACTURER)
    db.add(m)
    await db.flush()
    cache[key] = m.id
    return m.id


async def import_equipment(db: AsyncSession, source, batch: V1ImportBatch, store: SettingsStore) -> None:
    dry_run = batch.dry_run
    mfr_cache: dict = {}
    cat_cache: dict = {}
    model_cache: dict = {}
    status_cache: dict = {}
    loc_cache: dict = {}
    prefix = store.get("asset_tag.prefix")
    pad = store.get_int("asset_tag.pad")

    rows = await source.fetch(
        "SELECT id, name, category, serial_number, asset_tag, status, location, notes FROM equipment ORDER BY id"
    )
    for row in rows:
        mfr_id = await _unknown_manufacturer_id(db, mfr_cache, dry_run)
        category_name = (row["category"] or "Other").strip().title() or "Other"
        category_id, _ = await resolve_or_plan_category(db, cat_cache, category_name, dry_run)
        model_id, _, model_note = await resolve_or_plan_model(db, model_cache, mfr_id, category_id, row["name"], dry_run)

        location_id = None
        if row["location"]:
            location_id, _ = await resolve_or_plan_location(db, loc_cache, row["location"], dry_run)

        v1_status = (row["status"] or "available").strip().lower()
        label_name, label_type = EQUIPMENT_STATUS_PLAN.get(v1_status, ("Available", StatusType.deployable))
        status_id, _ = await resolve_or_plan_status_label(db, status_cache, label_name, label_type, dry_run)

        tag = (row["asset_tag"] or "").strip()
        if not tag and not dry_run:
            tag = await next_asset_tag(db, prefix, pad)

        if dry_run:
            detail = f"would create asset from equipment (tag={tag or 'auto-generated'})"
            if model_note:
                detail += "; " + model_note
            await record_row(db, batch, "equipment", row["id"], "asset", None, ImportRowOutcome.created, detail)
            continue

        asset = Asset(
            asset_tag=tag,
            serial=row["serial_number"] or None,
            model_id=model_id,
            status_label_id=status_id,
            location_id=location_id,
            notes=row["notes"] or None,
        )
        db.add(asset)
        await db.flush()

        detail = f"created asset tag={asset.asset_tag} from v1 equipment"
        if model_note:
            detail += "; " + model_note
        await record_row(db, batch, "equipment", row["id"], "asset", asset.id, ImportRowOutcome.created, detail)


async def import_lending_records(db: AsyncSession, source, batch: V1ImportBatch) -> None:
    dry_run = batch.dry_run
    status_cache: dict = {}
    # Resolved once, outside the loop -- both label names are fixed
    # regardless of which row is being replayed.
    in_use_status_id, _ = await resolve_or_plan_status_label(db, status_cache, "In Use", StatusType.deployed, dry_run)
    available_status_id, _ = await resolve_or_plan_status_label(
        db, status_cache, "Available", StatusType.deployable, dry_run
    )

    rows = await source.fetch(
        "SELECT id, equipment_id, user_id, lent_at, due_at, returned_at, lent_by_id, notes "
        "FROM lending_records ORDER BY id"
    )
    for row in rows:
        asset_id = await v2_entity_id_for_v1_row(db, "equipment", row["equipment_id"])
        if asset_id is None:
            await record_row(
                db, batch, "lending_records", row["id"], "checkout", None, ImportRowOutcome.flagged,
                f"equipment {row['equipment_id']} has no imported v2 asset -- run the equipment module first",
            )
            continue
        target_user_id = await v2_entity_id_for_v1_row(db, "users", row["user_id"]) if row["user_id"] else None
        checked_out_by = (
            await v2_entity_id_for_v1_row(db, "users", row["lent_by_id"]) if row["lent_by_id"] else None
        ) or batch.started_by
        if target_user_id is None:
            await record_row(
                db, batch, "lending_records", row["id"], "checkout", None, ImportRowOutcome.flagged,
                f"user {row['user_id']} has no imported v2 user -- cannot replay this lending record",
            )
            continue

        if dry_run:
            state = "open" if row["returned_at"] is None else "closed"
            await record_row(
                db, batch, "lending_records", row["id"], "checkout", None, ImportRowOutcome.created,
                f"would replay a {state} checkout against asset (v1 equipment {row['equipment_id']})",
            )
            continue

        checked_out_at = row["lent_at"] or datetime.now(timezone.utc)
        replay_note = "(replayed from v1 lending_records)"
        checkout = Checkout(
            asset_id=asset_id,
            target_user_id=target_user_id,
            status_label_id_at_checkout=in_use_status_id,
            checked_out_at=checked_out_at,
            checked_out_by=checked_out_by,
            expected_checkin_at=row["due_at"],
            notes=f"{row['notes']} {replay_note}" if row["notes"] else replay_note,
        )

        if row["returned_at"] is not None:
            checkout.checked_in_at = row["returned_at"]
            checkout.checked_in_by = checked_out_by
            checkout.checkin_status_label_id = available_status_id
            db.add(checkout)
            detail = "replayed closed checkout (returned to Available -- v1 has no record of the actual return-to status)"
        else:
            db.add(checkout)
            asset = await db.get(Asset, asset_id)
            asset.checked_out_to_user_id = target_user_id
            asset.checked_out_at = checked_out_at
            asset.status_label_id = in_use_status_id
            detail = "replayed open checkout (equipment still on loan)"

        await db.flush()
        await record_row(
            db, batch, "lending_records", row["id"], "checkout", checkout.id, ImportRowOutcome.created, detail
        )
