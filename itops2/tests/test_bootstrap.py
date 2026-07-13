"""Smoke tests proving the throwaway-Postgres test harness itself works,
before any Phase 5 behavior is built on top of it.
"""

from sqlalchemy import select

from app.core.models import Currency, Role


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
