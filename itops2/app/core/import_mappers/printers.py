"""Maps v1 `printers` to core_assets (Printer category) +
core_printer_details, and `printer_repairs` to core_maintenance.

Printers never get a checkout replay -- v1 has no per-printer "assigned
user" concept (no assigned_user_id-equivalent column), so every
printer lands in a plain deployable-type status (Available/Offline/In
Maintenance/Retired), never deployed. v1's `active`/`offline` are kept
as DISTINCT v2 status labels rather than both collapsing to
"Available" -- v1 tracked them as different real states and this
import shouldn't lose that distinction.

v1 printers.department is free text with nowhere to go on core_assets
(Department is scoped to Users only, per the confirmed Phase 9 design
-- see app/core/models.py's Department docstring) -- captured in the
row's own detail rather than silently dropped, same treatment the
Users mapper gives v1 users.location.

contract_id is looked up against the Contracts mapper's own
V1ImportRow trail; if Contracts hasn't been imported yet (or this v1
contract_id fails to resolve for any reason), the printer is still
created -- linking it to a contract is optional M2M coverage, not
load-bearing data, and the live Contracts page already has an
asset-link picker for completing this by hand afterward.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.import_mappers.catalog import (
    resolve_or_plan_category,
    resolve_or_plan_manufacturer,
    resolve_or_plan_model,
    resolve_or_plan_status_label,
)
from app.core.import_mappers.common import (
    next_asset_tag,
    record_row,
    resolve_or_plan_location,
    v2_entity_id_for_v1_row,
)
from app.core.models import (
    Asset,
    ContractAsset,
    ImportRowOutcome,
    Maintenance,
    MaintenanceType,
    PrinterDetails,
    StatusType,
    V1ImportBatch,
)
from app.core.settings_store import SettingsStore
from app.core.v1_currency import load_symbol_map, parse_v1_money

PRINTER_STATUS_PLAN = {
    "active": ("Available", StatusType.deployable),
    "offline": ("Offline", StatusType.pending),
    "maintenance": ("In Maintenance", StatusType.pending),
    "retired": ("Retired", StatusType.archived),
}

PRINTER_CATEGORY = "Printer"


async def import_printers(db: AsyncSession, source, batch: V1ImportBatch, store: SettingsStore) -> None:
    dry_run = batch.dry_run
    mfr_cache: dict = {}
    model_cache: dict = {}
    status_cache: dict = {}
    loc_cache: dict = {}
    prefix = store.get("asset_tag.prefix")
    pad = store.get_int("asset_tag.pad")
    symbol_map = load_symbol_map(store.get("import.currency_symbol_map"))

    category_id, _ = await resolve_or_plan_category(db, {}, PRINTER_CATEGORY, dry_run)

    rows = await source.fetch(
        "SELECT id, make, model, serial_number, asset_tag, ip_address, location, department, status, "
        "purchase_date, warranty_expiry, purchase_price, contract_id, notes FROM printers ORDER BY id"
    )
    for row in rows:
        mfr_id, _ = await resolve_or_plan_manufacturer(db, mfr_cache, row["make"], dry_run)
        model_id, _, model_note = await resolve_or_plan_model(db, model_cache, mfr_id, category_id, row["model"], dry_run)

        location_id = None
        if row["location"]:
            location_id, _ = await resolve_or_plan_location(db, loc_cache, row["location"], dry_run)

        v1_status = (row["status"] or "active").strip().lower()
        label_name, label_type = PRINTER_STATUS_PLAN.get(v1_status, ("Available", StatusType.deployable))
        status_id, _ = await resolve_or_plan_status_label(db, status_cache, label_name, label_type, dry_run)

        tag = (row["asset_tag"] or "").strip()
        if not tag and not dry_run:
            tag = await next_asset_tag(db, prefix, pad)

        money = parse_v1_money(row["purchase_price"], symbol_map)
        cost = money.amount if not money.needs_review else None
        currency = money.currency if not money.needs_review else None

        notes = row["notes"] or None

        detail_notes = []
        if model_note:
            detail_notes.append(model_note)
        if row["department"]:
            detail_notes.append(f"v1 department free text: '{row['department']}' (no v2 field on Assets to store this)")
        if money.needs_review and (row["purchase_price"] or "").strip():
            detail_notes.append(f"NEEDS REVIEW (cost): raw='{row['purchase_price']}'")

        if dry_run:
            detail = f"would create printer asset (tag={tag or 'auto-generated'})"
            if detail_notes:
                detail += "; " + "; ".join(detail_notes)
            await record_row(db, batch, "printers", row["id"], "asset", None, ImportRowOutcome.created, detail)
            continue

        asset = Asset(
            asset_tag=tag,
            serial=row["serial_number"] or None,
            model_id=model_id,
            status_label_id=status_id,
            location_id=location_id,
            purchase_date=row["purchase_date"],
            purchase_cost=cost,
            purchase_currency=currency,
            notes=notes,
        )
        db.add(asset)
        await db.flush()

        if row["ip_address"]:
            db.add(PrinterDetails(asset_id=asset.id, ip_address=row["ip_address"]))

        if row["contract_id"]:
            contract_v2_id = await v2_entity_id_for_v1_row(db, "contracts", row["contract_id"])
            if contract_v2_id is not None:
                db.add(ContractAsset(contract_id=contract_v2_id, asset_id=asset.id))
            else:
                detail_notes.append(
                    f"v1 contract_id={row['contract_id']} not yet imported -- link manually via Contracts"
                )

        detail = f"created printer asset tag={asset.asset_tag}"
        if detail_notes:
            detail += "; " + "; ".join(detail_notes)
        await record_row(db, batch, "printers", row["id"], "asset", asset.id, ImportRowOutcome.created, detail)


async def import_printer_repairs(db: AsyncSession, source, batch: V1ImportBatch, store: SettingsStore) -> None:
    dry_run = batch.dry_run
    symbol_map = load_symbol_map(store.get("import.currency_symbol_map"))

    rows = await source.fetch(
        "SELECT id, printer_id, description, repair_date, cost, document_ref, notes "
        "FROM printer_repairs ORDER BY id"
    )
    for row in rows:
        asset_id = await v2_entity_id_for_v1_row(db, "printers", row["printer_id"])
        if asset_id is None:
            await record_row(
                db, batch, "printer_repairs", row["id"], "maintenance", None, ImportRowOutcome.flagged,
                f"printer {row['printer_id']} has no imported v2 asset -- run the printers module first",
            )
            continue
        if row["repair_date"] is None:
            # core_maintenance.date is required -- v1 shouldn't have a
            # blank one in practice, but never crash the whole import
            # over a single bad row.
            await record_row(
                db, batch, "printer_repairs", row["id"], "maintenance", None, ImportRowOutcome.flagged,
                "blank repair_date -- core_maintenance requires a date",
            )
            continue

        money = parse_v1_money(row["cost"], symbol_map)
        cost = money.amount if not money.needs_review else None
        currency = money.currency if not money.needs_review else None

        description = row["description"] or "(no description in v1 record)"
        if row["document_ref"]:
            description += f"\n\n(document ref: {row['document_ref']})"
        if row["notes"]:
            description += f"\n\n(v1 notes: {row['notes']})"

        detail_notes = []
        if money.needs_review and (row["cost"] or "").strip():
            detail_notes.append(f"NEEDS REVIEW (cost): raw='{row['cost']}'")

        if dry_run:
            detail = "would create maintenance record from printer_repairs"
            if detail_notes:
                detail += "; " + "; ".join(detail_notes)
            await record_row(db, batch, "printer_repairs", row["id"], "maintenance", None, ImportRowOutcome.created, detail)
            continue

        record = Maintenance(
            asset_id=asset_id,
            date=row["repair_date"],
            maintenance_type=MaintenanceType.repair,
            description=description,
            cost=cost,
            currency=currency,
            created_by=batch.started_by,
        )
        db.add(record)
        await db.flush()

        detail = "created maintenance record from printer_repairs"
        if detail_notes:
            detail += "; " + "; ".join(detail_notes)
        await record_row(db, batch, "printer_repairs", row["id"], "maintenance", record.id, ImportRowOutcome.created, detail)
