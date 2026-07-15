"""Maps v1 it_assets rows to core_assets (+ core_checkouts for
currently-assigned assets), synthesizing Manufacturer/Category/Model
via app/core/import_mappers/catalog.py.

Status mapping is deliberate, not 1:1 -- v2's asset workflow rule
(status_type == deployed reachable ONLY via a real checkout, never a
direct field write -- see core_assets' CHECK constraints and
app/routers/assets.py's checkout route) means an "assigned" v1 asset
can't just get its status_label_id set directly. It's created in a
deployable status first, then a synthesized core_checkouts row is
opened against it -- replaying the checkout, not faking the
destination state.

purchase_price is v1 free text ("1000 SCR", "$30000", "6000") parsed
via app/core/v1_currency.parse_v1_money(). An unparseable bare number
still creates the asset (asset_tag/model/status carry the record, cost
is one field among many) but cost/currency are left NULL and the row's
detail is prefixed "NEEDS REVIEW (cost): ..." -- the marker chunk 4's
wizard review queue filters on.

asset_tag: v1's is blank on essentially every real row (confirmed live
before writing this). A blank tag is auto-generated using the exact
same prefix+pad+next-number convention as the live Assets page's own
auto-suggest (app/routers/assets.py:_next_asset_tag), duplicated here
rather than imported -- routers depend on core, not the reverse (see
CLAUDE.md). A non-blank v1 tag is preserved as-is, per the confirmed
design ("preserves asset tags"). Dry-run can't predict the exact
generated tag without writing, so it's shown as "auto-generated".
"""

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.import_mappers.catalog import (
    V1_ASSET_CATEGORY_NAMES,
    resolve_or_plan_category,
    resolve_or_plan_manufacturer,
    resolve_or_plan_model,
    resolve_or_plan_status_label,
)
from app.core.import_mappers.common import record_row
from app.core.models import Asset, Checkout, ImportRowOutcome, StatusType, V1ImportBatch, V1ImportRow
from app.core.settings_store import SettingsStore
from app.core.v1_currency import load_symbol_map, parse_v1_money

V1_STATUS_PLAN = {
    "available": ("Available", StatusType.deployable),
    "assigned": ("In Use", StatusType.deployed),
    "maintenance": ("In Maintenance", StatusType.pending),
    "retired": ("Retired", StatusType.archived),
    "lost": ("Lost", StatusType.archived),
}


async def v2_user_id_for_v1_user(db: AsyncSession, v1_user_id: int) -> int | None:
    """Looks up which v2 user a v1 users.id was imported to, via the
    Users mapper's own V1ImportRow trail -- the generic traceability
    mechanism doubling as a cross-mapper join, so this module never
    needs its own copy of "have I seen this v1 user before"."""
    return (
        await db.execute(
            select(V1ImportRow.v2_entity_id)
            .where(
                V1ImportRow.v1_table == "users",
                V1ImportRow.v1_id == v1_user_id,
                V1ImportRow.is_dry_run.is_(False),
                V1ImportRow.v2_entity_id.is_not(None),
            )
            .order_by(V1ImportRow.created_at.desc())
            .limit(1)
        )
    ).scalars().first()


async def next_asset_tag(db: AsyncSession, prefix: str, pad: int) -> str:
    """Same algorithm as app/routers/assets.py's _next_asset_tag. Safe to
    call once per row inside this mapper's loop because each created
    asset is flushed before the next row is processed, so the next
    call's own SELECT already sees it."""
    tags = (await db.execute(select(Asset.asset_tag).where(Asset.asset_tag.like(f"{prefix}%")))).scalars().all()
    max_n = 0
    for tag in tags:
        suffix = tag[len(prefix):]
        if suffix.isdigit():
            max_n = max(max_n, int(suffix))
    return f"{prefix}{max_n + 1:0{pad}d}"


def months_between(start: date, end: date) -> int:
    """Approximate reverse of app/core/dates.add_months -- an exact
    inversion is ill-defined once day-of-month clamping is involved;
    close enough for a one-time import's warranty_months estimate."""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day > start.day:
        months += 1
    return max(months, 0)


async def import_assets(db: AsyncSession, source, batch: V1ImportBatch, store: SettingsStore) -> None:
    dry_run = batch.dry_run
    symbol_map = load_symbol_map(store.get("import.currency_symbol_map"))
    prefix = store.get("asset_tag.prefix")
    pad = store.get_int("asset_tag.pad")

    mfr_cache: dict = {}
    cat_cache: dict = {}
    model_cache: dict = {}
    status_cache: dict = {}

    rows = await source.fetch(
        "SELECT id, name, asset_tag, category, manufacturer, model, serial_number, status, "
        "assigned_user_id, purchase_date, warranty_expiry, purchase_price, supplier, notes "
        "FROM it_assets ORDER BY id"
    )
    for row in rows:
        v1_category = (row["category"] or "other").strip().lower()
        category_name = V1_ASSET_CATEGORY_NAMES.get(v1_category, v1_category.title() or "Other")
        category_id, _ = await resolve_or_plan_category(db, cat_cache, category_name, dry_run)
        mfr_id, _ = await resolve_or_plan_manufacturer(db, mfr_cache, row["manufacturer"], dry_run)
        model_id, _, model_note = await resolve_or_plan_model(db, model_cache, mfr_id, category_id, row["model"], dry_run)

        v1_status = (row["status"] or "available").strip().lower()
        label_name, label_type = V1_STATUS_PLAN.get(v1_status, ("Available", StatusType.deployable))
        # Never create the asset directly in a deployed-type label -- see
        # module docstring. Assigned assets start Available and get
        # checked out below, once the row itself exists.
        initial_name, initial_type = ("Available", StatusType.deployable) if label_type == StatusType.deployed else (label_name, label_type)
        initial_status_id, _ = await resolve_or_plan_status_label(db, status_cache, initial_name, initial_type, dry_run)

        tag = (row["asset_tag"] or "").strip()
        if not tag and not dry_run:
            tag = await next_asset_tag(db, prefix, pad)

        money = parse_v1_money(row["purchase_price"], symbol_map)
        cost = money.amount if not money.needs_review else None
        currency = money.currency if not money.needs_review else None

        notes = "; ".join(p for p in [row["notes"], f"supplier: {row['supplier']}" if row["supplier"] else None] if p) or None

        detail_notes = []
        if model_note:
            detail_notes.append(model_note)
        if money.needs_review and (row["purchase_price"] or "").strip():
            detail_notes.append(f"NEEDS REVIEW (cost): raw='{row['purchase_price']}'")

        if dry_run:
            detail = f"would create asset (tag={tag or 'auto-generated'}, status={v1_status})"
            if detail_notes:
                detail += "; " + "; ".join(detail_notes)
            await record_row(db, batch, "it_assets", row["id"], "asset", None, ImportRowOutcome.created, detail)
            continue

        warranty_months = None
        if row["purchase_date"] and row["warranty_expiry"]:
            warranty_months = months_between(row["purchase_date"], row["warranty_expiry"])

        asset = Asset(
            asset_tag=tag,
            serial=row["serial_number"] or None,
            model_id=model_id,
            status_label_id=initial_status_id,
            purchase_date=row["purchase_date"],
            purchase_cost=cost,
            purchase_currency=currency,
            warranty_months=warranty_months,
            notes=notes,
        )
        db.add(asset)
        await db.flush()

        if label_type == StatusType.deployed:
            v2_user_id = await v2_user_id_for_v1_user(db, row["assigned_user_id"]) if row["assigned_user_id"] else None
            if v2_user_id is None:
                detail_notes.append(
                    "v1 status=assigned but assigned_user_id has no imported v2 user -- "
                    "created without checkout, needs manual checkout"
                )
            else:
                deployed_status_id, _ = await resolve_or_plan_status_label(db, status_cache, label_name, label_type, dry_run)
                now = datetime.now(timezone.utc)
                asset.checked_out_to_user_id = v2_user_id
                asset.checked_out_at = now
                asset.status_label_id = deployed_status_id
                db.add(
                    Checkout(
                        asset_id=asset.id,
                        target_user_id=v2_user_id,
                        status_label_id_at_checkout=deployed_status_id,
                        checked_out_at=now,
                        checked_out_by=batch.started_by,
                        notes="checkout replayed from v1 import",
                    )
                )

        detail = f"created asset tag={asset.asset_tag}"
        if detail_notes:
            detail += "; " + "; ".join(detail_notes)
        await record_row(db, batch, "it_assets", row["id"], "asset", asset.id, ImportRowOutcome.created, detail)
