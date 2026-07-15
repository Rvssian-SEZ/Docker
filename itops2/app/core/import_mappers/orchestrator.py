"""The Phase 9 wizard's run loop: creates one V1ImportBatch, calls the
selected module mapper functions in a fixed dependency order, and
commits.

There is no separate "roll back the target tables" step for a dry run
-- every mapper function already checks batch.dry_run itself and skips
its own target-table writes (Users, Assets, Departments, ...) while
STILL writing a V1ImportRow for every source row it looked at, in both
modes. That's what makes a dry run's results inspectable afterward via
GET /import/batches/{id} rather than only visible in the one HTTP
response: nothing here needs to hold the preview in memory or roll
back a transaction to get it, the row is just already sitting in
core_v1_import_rows once this function returns.

MODULE order matters and is NOT admin-configurable -- it encodes real
dependencies discovered while building the individual mappers: Users
before anything with an assigned_user_id/owner_id/lent_by_id to
resolve; it_assets before its photos or checkouts; equipment before
its lending_records; printers before its repairs/attachments;
inventory_items before its movements. Skipping a module the admin
didn't select just means downstream lookups against it come back
empty and get flagged ("run the X module first") rather than crashing
-- see each mapper's own flagged-row handling.

Failure handling: an exception partway through is caught, the batch is
marked failed, and whatever was already flushed before the failure is
still committed -- a real (non-dry-run) run's partial progress is
real progress, and the partial unique index on V1ImportRow means a
re-run after fixing whatever broke will skip everything already
'created' and pick up where it left off, never duplicate it.
"""

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.import_mappers.attachments import import_asset_photos, import_printer_attachments
from app.core.import_mappers.assets import import_assets
from app.core.import_mappers.contracts import import_contracts
from app.core.import_mappers.equipment import import_equipment, import_lending_records
from app.core.import_mappers.inventory import import_inventory_items, import_inventory_movements
from app.core.import_mappers.printers import import_printer_repairs, import_printers
from app.core.import_mappers.users import import_users
from app.core.models import ImportBatchStatus, V1ImportBatch
from app.core.settings_store import SettingsStore
from app.core.v1_source import V1Source


async def _run_users(db, source, batch, store):
    await import_users(db, source, batch)


async def _run_assets(db, source, batch, store):
    await import_assets(db, source, batch, store)


async def _run_equipment(db, source, batch, store):
    await import_equipment(db, source, batch, store)
    await import_lending_records(db, source, batch)


async def _run_printers(db, source, batch, store):
    await import_printers(db, source, batch, store)
    await import_printer_repairs(db, source, batch, store)


async def _run_attachments(db, source, batch, store):
    await import_asset_photos(db, source, batch, store)
    await import_printer_attachments(db, source, batch, store)


async def _run_contracts(db, source, batch, store):
    await import_contracts(db, source, batch, store)


async def _run_inventory(db, source, batch, store):
    await import_inventory_items(db, source, batch, store)
    await import_inventory_movements(db, source, batch)


# (key, label, fn) -- order is the fixed dependency order described above.
MODULES = [
    ("users", "Users & Departments", _run_users),
    ("assets", "Assets (from v1 IT Assets)", _run_assets),
    ("equipment", "Equipment & Lending History", _run_equipment),
    ("printers", "Printers & Repair History", _run_printers),
    ("attachments", "Attachments (asset photos & printer files)", _run_attachments),
    ("contracts", "Contracts", _run_contracts),
    ("inventory", "Inventory & Stock History", _run_inventory),
]

MODULE_KEYS = [key for key, _label, _fn in MODULES]


async def run_v1_import(
    db: AsyncSession,
    database_url: str,
    store: SettingsStore,
    selected_modules: list[str],
    dry_run: bool,
    started_by: int,
) -> tuple[V1ImportBatch, str | None]:
    """Runs the selected modules against v1 (read-only, see V1Source) and
    returns (batch, error_message). error_message is None on a clean
    completion; a batch always gets a real row and a real status either
    way -- there is no scenario where this raises out to the caller."""
    batch = V1ImportBatch(started_by=started_by, dry_run=dry_run, status=ImportBatchStatus.running)
    db.add(batch)
    await db.flush()

    try:
        source = await V1Source.connect(database_url)
    except Exception as exc:
        batch.status = ImportBatchStatus.failed
        batch.finished_at = datetime.now(timezone.utc)
        await db.commit()
        return batch, f"Could not connect to the v1 database: {exc}"

    error_message = None
    try:
        for key, _label, fn in MODULES:
            if key in selected_modules:
                await fn(db, source, batch, store)
        batch.status = ImportBatchStatus.completed
    except Exception as exc:
        batch.status = ImportBatchStatus.failed
        error_message = str(exc)
    finally:
        batch.finished_at = datetime.now(timezone.utc)
        await source.close()
        await db.commit()

    return batch, error_message
