"""Contracts list filter bar (type, expiring state, vendor free-text) —
SQL-side filtering.
"""

from datetime import date, timedelta

from sqlalchemy import select

from app.core.models import Contract, ContractType, User
from app.core.settings_store import save_setting


async def _breakglass_id(db) -> int:
    return (await db.execute(select(User.id).where(User.is_breakglass.is_(True)))).scalar_one()


async def _make_contract(db, name, *, contract_type=ContractType.contract, end_date=None, vendor=None):
    admin_id = await _breakglass_id(db)
    c = Contract(
        name=name, contract_type=contract_type, vendor=vendor,
        end_date=end_date or (date.today() + timedelta(days=365)), created_by=admin_id,
    )
    db.add(c)
    await db.commit()
    return c


async def test_filter_by_contract_type(admin_client, db):
    await _make_contract(db, "Contract A", contract_type=ContractType.license)
    await _make_contract(db, "Contract B", contract_type=ContractType.subscription)

    resp = await admin_client.get("/contracts?contract_type=license")
    assert "Contract A" in resp.text
    assert "Contract B" not in resp.text


async def test_filter_by_state_expired_expiring_soon_active(admin_client, db):
    await save_setting(db, "contracts.renewal_alert_days", "14")
    await db.commit()
    today = date.today()

    await _make_contract(db, "Contract Expired", end_date=today - timedelta(days=1))
    await _make_contract(db, "Contract Soon", end_date=today + timedelta(days=5))
    await _make_contract(db, "Contract Active", end_date=today + timedelta(days=90))

    expired_resp = await admin_client.get("/contracts?state=expired")
    assert "Contract Expired" in expired_resp.text
    assert "Contract Soon" not in expired_resp.text
    assert "Contract Active" not in expired_resp.text

    soon_resp = await admin_client.get("/contracts?state=expiring_soon")
    assert "Contract Soon" in soon_resp.text
    assert "Contract Expired" not in soon_resp.text
    assert "Contract Active" not in soon_resp.text

    active_resp = await admin_client.get("/contracts?state=active")
    assert "Contract Active" in active_resp.text
    assert "Contract Expired" not in active_resp.text
    assert "Contract Soon" not in active_resp.text


async def test_filter_by_vendor_free_text(admin_client, db):
    await _make_contract(db, "Contract V1", vendor="Acme Corp")
    await _make_contract(db, "Contract V2", vendor="Globex Inc")

    resp = await admin_client.get("/contracts?vendor=Acme")
    assert "Contract V1" in resp.text
    assert "Contract V2" not in resp.text


async def test_combined_type_and_state_filters(admin_client, db):
    await save_setting(db, "contracts.renewal_alert_days", "14")
    await db.commit()
    today = date.today()

    await _make_contract(
        db, "Match", contract_type=ContractType.license, end_date=today + timedelta(days=5),
    )
    await _make_contract(
        db, "Wrong Type", contract_type=ContractType.subscription, end_date=today + timedelta(days=5),
    )
    await _make_contract(
        db, "Wrong State", contract_type=ContractType.license, end_date=today + timedelta(days=90),
    )

    resp = await admin_client.get("/contracts?contract_type=license&state=expiring_soon")
    assert "Match" in resp.text
    assert "Wrong Type" not in resp.text
    assert "Wrong State" not in resp.text


async def test_contracts_htmx_request_returns_table_partial_only(admin_client, db):
    await _make_contract(db, "Partial Contract")
    resp = await admin_client.get("/contracts", headers={"HX-Request": "true"})
    assert resp.status_code == 200
    assert 'id="contracts-table"' in resp.text
    assert "<nav" not in resp.text
    assert "Partial Contract" in resp.text


async def test_contracts_no_filters_behaves_like_before(admin_client, db):
    await _make_contract(db, "Plain Contract")
    resp = await admin_client.get("/contracts")
    assert resp.status_code == 200
    assert "Plain Contract" in resp.text
    assert "bi-funnel" not in resp.text


async def test_dashboard_state_deep_link_still_works(admin_client, db):
    await save_setting(db, "contracts.renewal_alert_days", "14")
    await db.commit()
    await _make_contract(db, "Deep Link Soon", end_date=date.today() + timedelta(days=5))

    resp = await admin_client.get("/contracts?state=expiring_soon")
    assert "Deep Link Soon" in resp.text
