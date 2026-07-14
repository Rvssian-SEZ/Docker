"""Smoke tests proving the throwaway-Postgres test harness itself works,
before any Phase 5 behavior is built on top of it.
"""

from sqlalchemy import select

from app.core.bootstrap import bootstrap
from app.core.models import AppSetting, Currency, Role
from app.core.settings_store import load_settings


async def test_bootstrap_seeds_four_roles(db):
    roles = (await db.execute(select(Role))).scalars().all()
    assert {r.name.value for r in roles} == {"admin", "manager", "technician", "viewer"}


async def test_bootstrap_seeds_default_currencies(db):
    codes = (await db.execute(select(Currency.code))).scalars().all()
    assert set(codes) >= {"SCR", "USD", "GBP", "EUR"}


async def test_breakglass_login_succeeds(client, settings):
    resp = await client.post(
        "/login",
        data={"username": settings.breakglass_username, "password": settings.breakglass_password},
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == "/"


async def test_login_wrong_password_fails(client, settings):
    resp = await client.post(
        "/login",
        data={"username": settings.breakglass_username, "password": "definitely-wrong"},
    )
    assert resp.status_code == 401


async def test_clean_tables_actually_clean(db, admin_client):
    """Guards the harness's own isolation: create a manufacturer, and the
    next test must not see it."""
    resp = await admin_client.post("/catalog/manufacturers/create", data={"name": "LeakCheck"})
    assert resp.status_code == 204


async def test_previous_test_leak_check(db):
    from app.core.models import Manufacturer

    rows = (await db.execute(select(Manufacturer))).scalars().all()
    assert rows == [], "manufacturer from the previous test leaked across _clean_tables"


async def test_bootstrap_migrates_smtp_use_tls_true_to_security_tls_with_no_port_set(db):
    db.add(AppSetting(key="smtp.use_tls", value="true"))
    await db.commit()

    await bootstrap(db)

    store = await load_settings(db)
    assert store.get("smtp.security") == "tls"
    assert await db.get(AppSetting, "smtp.use_tls") is None


async def test_bootstrap_migrates_smtp_use_tls_false_to_security_none(db):
    db.add(AppSetting(key="smtp.use_tls", value="false"))
    await db.commit()

    await bootstrap(db)

    store = await load_settings(db)
    assert store.get("smtp.security") == "none"
    assert await db.get(AppSetting, "smtp.use_tls") is None


async def test_bootstrap_migration_prefers_port_587_to_starttls_over_the_old_bool(db):
    """The actual production bug this migration exists to avoid
    repeating: a real deployment had use_tls=true on port 587
    (smtp.office365.com), which the old boolean model could only turn
    into "tls" (implicit TLS) -- wrong for 587, which needs STARTTLS.
    Port 587 must win over whatever the old bool said."""
    db.add(AppSetting(key="smtp.use_tls", value="true"))
    db.add(AppSetting(key="smtp.port", value="587"))
    await db.commit()

    await bootstrap(db)

    store = await load_settings(db)
    assert store.get("smtp.security") == "starttls"


async def test_bootstrap_migration_prefers_port_465_to_tls_over_the_old_bool(db):
    db.add(AppSetting(key="smtp.use_tls", value="false"))
    db.add(AppSetting(key="smtp.port", value="465"))
    await db.commit()

    await bootstrap(db)

    store = await load_settings(db)
    assert store.get("smtp.security") == "tls"


async def test_bootstrap_migration_is_idempotent_and_does_not_clobber_a_set_value(db):
    """If smtp.security was already explicitly set (e.g. an admin picked
    STARTTLS after upgrading) before some stray smtp.use_tls row got
    re-created, the migration must not silently overwrite it."""
    db.add(AppSetting(key="smtp.use_tls", value="true"))
    db.add(AppSetting(key="smtp.security", value="starttls"))
    await db.commit()

    await bootstrap(db)

    store = await load_settings(db)
    assert store.get("smtp.security") == "starttls"
    assert await db.get(AppSetting, "smtp.use_tls") is None

    # Second bootstrap run (simulates a second startup) must be a no-op.
    await bootstrap(db)
    store = await load_settings(db)
    assert store.get("smtp.security") == "starttls"
