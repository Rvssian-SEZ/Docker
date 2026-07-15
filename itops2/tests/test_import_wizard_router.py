"""app/routers/import_wizard.py -- the wizard's HTTP surface: module
picker + history (GET /import), kicking off a run (POST /import), and
the batch results / flagged-row review queue (GET /import/batches/{id}).
"""

import pytest_asyncio
from sqlalchemy import select, text

from app.core.models import ImportRowOutcome, User, V1ImportRow
from app.core.settings_store import save_setting
from tests.conftest import make_import_batch


@pytest_asyncio.fixture
async def v1_users_table(db):
    await db.execute(text("DROP TABLE IF EXISTS users CASCADE"))
    await db.execute(
        text(
            "CREATE TABLE users (id int, username varchar, email varchar, full_name varchar, "
            "phone varchar, department varchar, title varchar, location varchar, is_active boolean)"
        )
    )
    await db.execute(
        text(
            "INSERT INTO users (id, username, email, full_name, phone, department, title, location, is_active) "
            "VALUES (1, 'wizard-v1-user', 'wizard@example.com', 'Wizard User', NULL, NULL, NULL, NULL, true)"
        )
    )
    await db.commit()
    yield
    await db.execute(text("DROP TABLE IF EXISTS users CASCADE"))
    await db.commit()


async def test_index_shows_warning_when_no_database_configured(admin_client):
    resp = await admin_client.get("/import")
    assert resp.status_code == 200
    assert "Set it up in Settings" in resp.text


async def test_index_lists_modules(admin_client):
    resp = await admin_client.get("/import")
    assert "Users &amp; Departments" in resp.text or "Users & Departments" in resp.text
    assert "Contracts" in resp.text


async def test_run_without_database_url_shows_toast_error(admin_client, db):
    resp = await admin_client.post("/import", data={"module_users": "true", "dry_run": "true"})
    assert resp.status_code == 200
    assert "Configure the v1 database connection" in resp.text


async def test_run_without_selected_modules_shows_toast_error(admin_client, db, settings):
    await save_setting(db, "import.v1_database_url", settings.database_url)
    await db.commit()
    resp = await admin_client.post("/import", data={"dry_run": "true"})
    assert resp.status_code == 200
    assert "Pick at least one module" in resp.text


async def test_successful_dry_run_redirects_to_batch_detail(admin_client, db, settings, v1_users_table):
    await save_setting(db, "import.v1_database_url", settings.database_url)
    await db.commit()

    resp = await admin_client.post("/import", data={"module_users": "true", "dry_run": "true"})
    assert resp.status_code == 204
    assert resp.headers["hx-redirect"].startswith("/import/batches/")

    # the run must not have created a real v2 user (dry run)
    assert (
        await db.execute(select(User).where(User.username == "wizard-v1-user"))
    ).scalar_one_or_none() is None


async def test_successful_real_run_creates_user_and_batch_detail_shows_it(admin_client, db, settings, v1_users_table):
    await save_setting(db, "import.v1_database_url", settings.database_url)
    await db.commit()

    resp = await admin_client.post("/import", data={"module_users": "true", "dry_run": "false"})
    assert resp.status_code == 204
    batch_url = resp.headers["hx-redirect"]

    user = (await db.execute(select(User).where(User.username == "wizard-v1-user"))).scalar_one()
    assert user.email == "wizard@example.com"

    detail = await admin_client.get(batch_url)
    assert detail.status_code == 200
    assert "wizard-v1-user" in detail.text
    assert "users" in detail.text
    assert "created" in detail.text.lower()


async def test_batch_detail_filters_by_outcome(admin_client, db):
    batch = await make_import_batch(db)
    db.add(
        V1ImportRow(
            batch_id=batch.id, v1_table="contracts", v1_id=1, v2_entity_type="contract",
            outcome=ImportRowOutcome.flagged, detail="v1 status=cancelled",
        )
    )
    db.add(
        V1ImportRow(
            batch_id=batch.id, v1_table="contracts", v1_id=2, v2_entity_type="contract",
            v2_entity_id=99, outcome=ImportRowOutcome.created, detail="created contract",
        )
    )
    await db.commit()

    resp = await admin_client.get(f"/import/batches/{batch.id}?outcome=flagged")
    assert resp.status_code == 200
    assert "v1 status=cancelled" in resp.text
    assert "created contract" not in resp.text


async def test_batch_detail_not_found(admin_client):
    resp = await admin_client.get("/import/batches/999999")
    assert resp.status_code == 200
    assert "not found" in resp.text.lower()
