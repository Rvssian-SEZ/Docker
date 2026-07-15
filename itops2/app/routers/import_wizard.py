"""The Phase 9 v1-import wizard: GET /import (module picker + batch
history), POST /import (kicks off a dry-run or real run), GET
/import/batches/{id} (results -- summary counts + the full row list,
filterable to just flagged rows for the manual-review queue).

Admin-only (import.run permission, locked admin-only in the permission
registry's DEFAULTS -- see app/core/permissions.py). The v1 connection
string is read from the import.v1_database_url setting (Settings ->
Import), never entered ad hoc per run -- one place to audit, one place
the read-only enforcement (V1Source.connect) has to be trusted.

Module order/labels come straight from the orchestrator's own MODULES
list -- there is no second copy of "what modules exist" to keep in
sync.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import CurrentUser, require
from app.core.db import get_db
from app.core.import_mappers.orchestrator import MODULES, run_v1_import
from app.core.models import ImportRowOutcome, V1ImportBatch, V1ImportRow
from app.core.settings_store import load_settings
from app.templating import templates

router = APIRouter(prefix="/import")


def _toast(request: Request, ok: bool, message: str):
    return templates.TemplateResponse(request, "partials/toast.html", {"ok": ok, "message": message})


def _redirect(path: str):
    return Response(status_code=204, headers={"HX-Redirect": path})


@router.get("", response_class=HTMLResponse)
async def import_index(
    request: Request,
    user: CurrentUser = Depends(require("import.run")),
    db: AsyncSession = Depends(get_db),
):
    store = await load_settings(db)
    batches = (
        (
            await db.execute(
                select(V1ImportBatch)
                .options(selectinload(V1ImportBatch.starter))
                .order_by(V1ImportBatch.started_at.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    counts_by_batch: dict[int, dict[str, int]] = {}
    if batches:
        rows = (
            await db.execute(
                select(V1ImportRow.batch_id, V1ImportRow.outcome, func.count())
                .where(V1ImportRow.batch_id.in_([b.id for b in batches]))
                .group_by(V1ImportRow.batch_id, V1ImportRow.outcome)
            )
        ).all()
        for batch_id, outcome, count in rows:
            counts_by_batch.setdefault(batch_id, {})[outcome.value] = count

    return templates.TemplateResponse(
        request,
        "import/index.html",
        {
            "user": user,
            "modules": MODULES,
            "batches": batches,
            "counts_by_batch": counts_by_batch,
            "v1_database_configured": bool(store.get("import.v1_database_url").strip()),
        },
    )


@router.post("", response_class=HTMLResponse)
async def import_run(
    request: Request,
    user: CurrentUser = Depends(require("import.run")),
    db: AsyncSession = Depends(get_db),
):
    form = await request.form()
    selected = [key for key, _label, _fn in MODULES if form.get(f"module_{key}") == "true"]
    dry_run = form.get("dry_run", "true") == "true"

    store = await load_settings(db)
    database_url = store.get("import.v1_database_url").strip()
    if not database_url:
        return _toast(request, False, "Configure the v1 database connection string in Settings → Import first.")
    if not selected:
        return _toast(request, False, "Pick at least one module to import.")

    batch, error = await run_v1_import(
        db, database_url, store, selected_modules=selected, dry_run=dry_run, started_by=user.id
    )
    if error:
        return _toast(request, False, f"Import batch #{batch.id} failed: {error} (see the batch for partial results)")
    return _redirect(f"/import/batches/{batch.id}")


@router.get("/batches/{batch_id}", response_class=HTMLResponse)
async def import_batch_detail(
    request: Request,
    batch_id: int,
    outcome: str = "",
    user: CurrentUser = Depends(require("import.run")),
    db: AsyncSession = Depends(get_db),
):
    batch = await db.get(V1ImportBatch, batch_id, options=[selectinload(V1ImportBatch.starter)])
    if batch is None:
        return _toast(request, False, "Batch not found.")

    stmt = select(V1ImportRow).where(V1ImportRow.batch_id == batch_id)
    if outcome:
        try:
            stmt = stmt.where(V1ImportRow.outcome == ImportRowOutcome(outcome))
        except ValueError:
            outcome = ""
    stmt = stmt.order_by(V1ImportRow.v1_table, V1ImportRow.v1_id)
    rows = (await db.execute(stmt)).scalars().all()

    counts_raw = (
        await db.execute(
            select(V1ImportRow.outcome, func.count())
            .where(V1ImportRow.batch_id == batch_id)
            .group_by(V1ImportRow.outcome)
        )
    ).all()
    counts = {o.value: c for o, c in counts_raw}

    return templates.TemplateResponse(
        request,
        "import/batch_detail.html",
        {"user": user, "batch": batch, "rows": rows, "counts": counts, "outcome_filter": outcome},
    )
