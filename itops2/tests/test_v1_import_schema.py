"""Phase 9 chunk 1: the import-tracking schema itself (batches/rows) --
just the DB-level guarantees, before any real parsing/mapping logic
exists (that's chunks 2-3). The partial unique index is the key thing
to prove here: at most one 'created' row per (v1_table, v1_id) among
real (non-dry-run) rows, enforced by Postgres, not just app discipline.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.models import ImportRowOutcome, User, V1ImportBatch, V1ImportRow


async def _breakglass_id(db) -> int:
    return (await db.execute(select(User.id).where(User.is_breakglass.is_(True)))).scalar_one()


async def _make_batch(db, dry_run=False):
    admin_id = await _breakglass_id(db)
    batch = V1ImportBatch(started_by=admin_id, dry_run=dry_run)
    db.add(batch)
    await db.flush()
    return batch


async def test_second_created_row_for_same_v1_source_is_rejected(db):
    batch = await _make_batch(db)
    db.add(
        V1ImportRow(
            batch_id=batch.id, v1_table="it_assets", v1_id=1, v2_entity_type="asset", v2_entity_id=100,
            outcome=ImportRowOutcome.created,
        )
    )
    await db.commit()

    db.add(
        V1ImportRow(
            batch_id=batch.id, v1_table="it_assets", v1_id=1, v2_entity_type="asset", v2_entity_id=101,
            outcome=ImportRowOutcome.created,
        )
    )
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


async def test_flagged_and_skipped_outcomes_do_not_collide_with_created(db):
    """The partial index only guards 'created' rows -- a v1 row can be
    flagged in one batch and successfully created in a later one (the
    re-run-after-fixing-a-flag flow) without the index getting in the way."""
    batch1 = await _make_batch(db)
    db.add(
        V1ImportRow(
            batch_id=batch1.id, v1_table="contracts", v1_id=5, v2_entity_type="contract",
            outcome=ImportRowOutcome.flagged, detail="missing renewal_date",
        )
    )
    await db.commit()

    batch2 = await _make_batch(db)
    db.add(
        V1ImportRow(
            batch_id=batch2.id, v1_table="contracts", v1_id=5, v2_entity_type="contract", v2_entity_id=42,
            outcome=ImportRowOutcome.created,
        )
    )
    await db.commit()  # must not raise

    rows = (
        await db.execute(select(V1ImportRow).where(V1ImportRow.v1_table == "contracts", V1ImportRow.v1_id == 5))
    ).scalars().all()
    assert len(rows) == 2
    assert {r.outcome for r in rows} == {ImportRowOutcome.flagged, ImportRowOutcome.created}


async def test_dry_run_rows_excluded_from_the_created_once_guarantee(db):
    """Two dry-run batches both claiming to have 'created' the same v1
    row must not collide -- a dry run never actually creates anything
    and can be re-previewed as many times as the admin likes before
    committing to a real run."""
    dry1 = await _make_batch(db, dry_run=True)
    db.add(
        V1ImportRow(
            batch_id=dry1.id, is_dry_run=True, v1_table="printers", v1_id=9, v2_entity_type="asset",
            outcome=ImportRowOutcome.created,
        )
    )
    await db.commit()

    dry2 = await _make_batch(db, dry_run=True)
    db.add(
        V1ImportRow(
            batch_id=dry2.id, is_dry_run=True, v1_table="printers", v1_id=9, v2_entity_type="asset",
            outcome=ImportRowOutcome.created,
        )
    )
    await db.commit()  # must not raise -- dry-run rows aren't covered by the partial index

    rows = (
        await db.execute(select(V1ImportRow).where(V1ImportRow.v1_table == "printers", V1ImportRow.v1_id == 9))
    ).scalars().all()
    assert len(rows) == 2


async def test_batch_status_defaults_to_running(db):
    batch = await _make_batch(db)
    await db.commit()
    await db.refresh(batch)
    assert batch.status.value == "running"
    assert batch.dry_run is False
