"""app/core/import_mappers/orchestrator.py -- run_v1_import()'s own
wiring (module selection, batch/status lifecycle, failure handling),
using a real V1Source against a minimal v1-shaped `users` table
created directly in the same throwaway Postgres the rest of the suite
runs against. The individual mapper functions have their own dedicated
test files (test_import_mappers_*.py) with FakeV1Source -- this file
is only about the orchestrator's own behavior, not mapper correctness.
"""

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from app.core.import_mappers.orchestrator import run_v1_import
from app.core.models import ImportBatchStatus, User
from app.core.settings_store import load_settings


@pytest_asyncio.fixture
async def v1_users_table(db):
    """Creates an empty v1-shaped `users` table -- each test inserts its
    OWN row with a unique username, since core_users is never truncated
    between tests (see conftest.py's TRUNCATE_TABLES comment) and a
    shared literal username would leak across tests in this file."""
    await db.execute(text("DROP TABLE IF EXISTS users CASCADE"))
    await db.execute(
        text(
            "CREATE TABLE users (id int, username varchar, email varchar, full_name varchar, "
            "phone varchar, department varchar, title varchar, location varchar, is_active boolean)"
        )
    )
    await db.commit()
    yield
    await db.execute(text("DROP TABLE IF EXISTS users CASCADE"))
    await db.commit()


async def _seed_v1_user(db, username: str, v1_id: int = 1):
    await db.execute(
        text(
            "INSERT INTO users (id, username, email, full_name, phone, department, title, location, is_active) "
            "VALUES (:id, :username, :email, 'V1 User', NULL, NULL, NULL, NULL, true)"
        ),
        {"id": v1_id, "username": username, "email": f"{username}@example.com"},
    )
    await db.commit()


async def test_only_selected_modules_run(db, settings, v1_users_table):
    await _seed_v1_user(db, "orch-only-selected")
    store = await load_settings(db)
    batch, error = await run_v1_import(
        db, settings.database_url, store, selected_modules=["users"], dry_run=False, started_by=1
    )
    await db.commit()

    assert error is None
    assert batch.status == ImportBatchStatus.completed
    user = (await db.execute(select(User).where(User.username == "orch-only-selected"))).scalar_one()
    assert user.email == "orch-only-selected@example.com"


async def test_unselected_modules_are_skipped(db, settings, v1_users_table):
    await _seed_v1_user(db, "orch-unselected-skip")
    store = await load_settings(db)
    batch, error = await run_v1_import(
        db, settings.database_url, store, selected_modules=[], dry_run=False, started_by=1
    )
    await db.commit()

    assert error is None
    assert batch.status == ImportBatchStatus.completed
    assert (await db.execute(select(User).where(User.username == "orch-unselected-skip"))).scalar_one_or_none() is None


async def test_dry_run_completes_without_creating_target_rows(db, settings, v1_users_table):
    await _seed_v1_user(db, "orch-dry-run")
    store = await load_settings(db)
    batch, error = await run_v1_import(
        db, settings.database_url, store, selected_modules=["users"], dry_run=True, started_by=1
    )
    await db.commit()

    assert error is None
    assert batch.dry_run is True
    assert batch.status == ImportBatchStatus.completed
    assert (await db.execute(select(User).where(User.username == "orch-dry-run"))).scalar_one_or_none() is None


async def test_connection_failure_sets_failed_status_without_raising(db, settings):
    store = await load_settings(db)
    bad_url = "postgresql+asyncpg://nouser:nopass@127.0.0.1:1/nonexistent"
    batch, error = await run_v1_import(
        db, bad_url, store, selected_modules=["users"], dry_run=False, started_by=1
    )
    await db.commit()

    assert error is not None
    assert batch.status == ImportBatchStatus.failed
    assert batch.finished_at is not None


async def test_module_failure_marks_batch_failed_but_keeps_earlier_progress(db, settings, v1_users_table):
    """"assets" comes after "users" in MODULES' fixed order, and no
    it_assets table exists in this test's minimal v1 schema -- the
    users module's work should still be committed even though the run
    as a whole fails on the next module."""
    await _seed_v1_user(db, "orch-partial-progress")
    store = await load_settings(db)
    batch, error = await run_v1_import(
        db, settings.database_url, store, selected_modules=["users", "assets"], dry_run=False, started_by=1
    )
    await db.commit()

    assert error is not None
    assert batch.status == ImportBatchStatus.failed
    user = (await db.execute(select(User).where(User.username == "orch-partial-progress"))).scalar_one_or_none()
    assert user is not None  # users module's work survives the later failure
