"""app/core/import_mappers/contracts.py -- v1 contracts -> core_contracts."""

from datetime import date

from sqlalchemy import select

from app.core.import_mappers.contracts import import_contracts
from app.core.models import AuthSource, Contract, ImportRowOutcome, Role, RoleName, User, V1ImportRow
from app.core.settings_store import load_settings
from tests.conftest import FakeV1Source, make_import_batch

BASE_ROW = {
    "id": 1, "name": "Annual Support", "contract_type": "support", "status": "active",
    "vendor_name": "Acme IT", "vendor_contact_name": None, "vendor_contact_email": None,
    "vendor_contact_phone": None, "cost": "250 GBP", "billing_cycle": "annual",
    "start_date": date(2025, 1, 1), "renewal_date": date(2026, 1, 1), "owner_id": None, "notes": None,
}


def _contracts_source(rows):
    return FakeV1Source({"FROM contracts": rows})


async def test_creates_contract_with_cost_and_billing_cycle(db):
    batch = await make_import_batch(db)
    store = await load_settings(db)
    await import_contracts(db, _contracts_source([BASE_ROW]), batch, store)
    await db.commit()

    contract = (await db.execute(select(Contract).where(Contract.name == "Annual Support"))).scalar_one()
    assert contract.contract_type.value == "contract"  # support -> contract
    assert contract.vendor == "Acme IT"
    assert contract.cost == 250
    assert contract.currency == "GBP"
    assert contract.renewal_period_months == 12
    assert contract.auto_renews is True
    assert contract.end_date == date(2026, 1, 1)


async def test_saas_maps_to_subscription(db):
    batch = await make_import_batch(db)
    store = await load_settings(db)
    row = dict(BASE_ROW, contract_type="saas", name="SaaS Deal")
    await import_contracts(db, _contracts_source([row]), batch, store)
    await db.commit()

    contract = (await db.execute(select(Contract).where(Contract.name == "SaaS Deal"))).scalar_one()
    assert contract.contract_type.value == "subscription"


async def test_vendor_maps_to_contract(db):
    batch = await make_import_batch(db)
    store = await load_settings(db)
    row = dict(BASE_ROW, contract_type="vendor", name="Vendor Deal")
    await import_contracts(db, _contracts_source([row]), batch, store)
    await db.commit()

    contract = (await db.execute(select(Contract).where(Contract.name == "Vendor Deal"))).scalar_one()
    assert contract.contract_type.value == "contract"


async def test_one_time_billing_cycle_does_not_auto_renew(db):
    batch = await make_import_batch(db)
    store = await load_settings(db)
    row = dict(BASE_ROW, billing_cycle="one_time", name="One Time Purchase")
    await import_contracts(db, _contracts_source([row]), batch, store)
    await db.commit()

    contract = (await db.execute(select(Contract).where(Contract.name == "One Time Purchase"))).scalar_one()
    assert contract.renewal_period_months is None
    assert contract.auto_renews is False


async def test_cancelled_status_is_flagged_not_created(db):
    batch = await make_import_batch(db)
    store = await load_settings(db)
    row = dict(BASE_ROW, status="cancelled")
    await import_contracts(db, _contracts_source([row]), batch, store)
    await db.commit()

    assert (await db.execute(select(Contract))).scalar_one_or_none() is None
    import_row = (await db.execute(select(V1ImportRow).where(V1ImportRow.v1_table == "contracts"))).scalar_one()
    assert import_row.outcome == ImportRowOutcome.flagged
    assert "cancelled" in import_row.detail


async def test_blank_renewal_date_is_flagged(db):
    batch = await make_import_batch(db)
    store = await load_settings(db)
    row = dict(BASE_ROW, renewal_date=None)
    await import_contracts(db, _contracts_source([row]), batch, store)
    await db.commit()

    assert (await db.execute(select(Contract))).scalar_one_or_none() is None
    import_row = (await db.execute(select(V1ImportRow).where(V1ImportRow.v1_table == "contracts"))).scalar_one()
    assert import_row.outcome == ImportRowOutcome.flagged
    assert "renewal_date" in import_row.detail


async def test_vendor_contact_folded_into_notes(db):
    batch = await make_import_batch(db)
    store = await load_settings(db)
    row = dict(
        BASE_ROW, vendor_contact_name="Jane Vendor", vendor_contact_email="jane@acme.test",
        notes="Renews automatically",
    )
    await import_contracts(db, _contracts_source([row]), batch, store)
    await db.commit()

    contract = (await db.execute(select(Contract).where(Contract.name == "Annual Support"))).scalar_one()
    assert "Renews automatically" in contract.notes
    assert "Jane Vendor" in contract.notes
    assert "jane@acme.test" in contract.notes


async def test_unparseable_cost_flagged_but_contract_still_created(db):
    batch = await make_import_batch(db)
    store = await load_settings(db)
    row = dict(BASE_ROW, cost="6000")
    await import_contracts(db, _contracts_source([row]), batch, store)
    await db.commit()

    contract = (await db.execute(select(Contract).where(Contract.name == "Annual Support"))).scalar_one()
    assert contract.cost is None
    import_row = (await db.execute(select(V1ImportRow).where(V1ImportRow.v1_table == "contracts"))).scalar_one()
    assert "NEEDS REVIEW (cost)" in import_row.detail


async def test_owner_resolved_to_created_by_when_imported(db):
    role_id = (await db.execute(select(Role.id).where(Role.name == RoleName.viewer))).scalar_one()
    owner = User(username="contract-owner", auth_source=AuthSource.oidc, role_id=role_id)
    db.add(owner)
    await db.flush()

    batch = await make_import_batch(db)
    db.add(
        V1ImportRow(
            batch_id=batch.id, v1_table="users", v1_id=42, v2_entity_type="user",
            v2_entity_id=owner.id, outcome=ImportRowOutcome.created,
        )
    )
    await db.flush()

    store = await load_settings(db)
    row = dict(BASE_ROW, owner_id=42)
    await import_contracts(db, _contracts_source([row]), batch, store)
    await db.commit()

    contract = (await db.execute(select(Contract).where(Contract.name == "Annual Support"))).scalar_one()
    assert contract.created_by == owner.id


async def test_owner_falls_back_to_importing_admin_when_unmapped(db):
    batch = await make_import_batch(db)
    store = await load_settings(db)
    row = dict(BASE_ROW, owner_id=999)
    await import_contracts(db, _contracts_source([row]), batch, store)
    await db.commit()

    contract = (await db.execute(select(Contract).where(Contract.name == "Annual Support"))).scalar_one()
    assert contract.created_by == batch.started_by


async def test_dry_run_writes_no_target_rows(db):
    batch = await make_import_batch(db, dry_run=True)
    store = await load_settings(db)
    await import_contracts(db, _contracts_source([BASE_ROW]), batch, store)
    await db.commit()

    assert (await db.execute(select(Contract))).scalar_one_or_none() is None
    import_row = (await db.execute(select(V1ImportRow).where(V1ImportRow.v1_table == "contracts"))).scalar_one()
    assert import_row.is_dry_run is True
    assert import_row.outcome == ImportRowOutcome.created
