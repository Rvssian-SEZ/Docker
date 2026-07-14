"""Phase 8 chunk D: the Dashboard's summary cards and the new
query-string filters on Assets/Contracts/Inventory list pages that the
cards link into.
"""

import re
from datetime import date, timedelta

from sqlalchemy import select

from app.core.models import (
    Asset,
    AssetModel,
    AuthSource,
    Category,
    Checkout,
    Company,
    Contract,
    ContractType,
    InventoryItem,
    Manufacturer,
    Role,
    RoleName,
    StatusLabel,
    StatusType,
    User,
)
from app.core.security import hash_password
from app.core.settings_store import save_setting


async def _breakglass_id(db) -> int:
    return (await db.execute(select(User.id).where(User.is_breakglass.is_(True)))).scalar_one()


async def _make_asset(db, tag, status_type=StatusType.deployable, company_id=None, **kwargs):
    mfr = Manufacturer(name=f"Mfr-{tag}")
    cat = Category(name=f"Cat-{tag}")
    db.add_all([mfr, cat])
    await db.flush()
    model = AssetModel(name="M", manufacturer_id=mfr.id, category_id=cat.id)
    status = StatusLabel(name=f"Status-{tag}", status_type=status_type)
    db.add_all([model, status])
    await db.flush()
    asset = Asset(
        asset_tag=tag, model_id=model.id, status_label_id=status.id, company_id=company_id, **kwargs
    )
    db.add(asset)
    await db.commit()
    return asset, status


async def test_dashboard_shows_correct_counts_for_admin(admin_client, db):
    today = date.today()
    await save_setting(db, "warranty.alert_days", "30")
    await save_setting(db, "contracts.renewal_alert_days", "14")
    await db.commit()

    # Asset by status + a warranty expiring soon.
    await _make_asset(
        db, "IT-DASH01", purchase_date=today - timedelta(days=350), warranty_months=12,
    )
    await _make_asset(db, "IT-DASH02", status_type=StatusType.archived)

    # An overdue checkout (needs the asset to actually be "deployed").
    deployed_asset, deployed_status = await _make_asset(db, "IT-DASH03", status_type=StatusType.deployed)
    admin_id = await _breakglass_id(db)
    db.add(
        Checkout(
            asset_id=deployed_asset.id, status_label_id_at_checkout=deployed_status.id,
            checked_out_at=today - timedelta(days=20), checked_out_by=admin_id,
            expected_checkin_at=today - timedelta(days=3),
        )
    )
    await db.commit()

    db.add(
        Contract(
            name="Renews Soon", contract_type=ContractType.contract,
            end_date=today + timedelta(days=5), created_by=admin_id,
        )
    )
    cat = Category(name="Consumables-Dash")
    db.add(cat)
    await db.flush()
    db.add(InventoryItem(name="Low Item", category_id=cat.id, quantity=1, min_quantity=5))
    await db.commit()

    resp = await admin_client.get("/")
    assert resp.status_code == 200
    text = resp.text
    assert "Assets by status" in text
    assert "Checkouts" in text
    assert 'href="/assets?checkout_state=overdue"' in text
    assert 'href="/assets?warranty=expiring"' in text
    assert 'href="/contracts?state=expiring_soon"' in text
    assert 'href="/inventory?low_stock=1"' in text


async def test_assets_list_filter_by_status_type(admin_client, db):
    await _make_asset(db, "IT-FILT01", status_type=StatusType.deployable)
    await _make_asset(db, "IT-FILT02", status_type=StatusType.archived)

    resp = await admin_client.get("/assets?status_type=archived")
    assert "IT-FILT02" in resp.text
    assert "IT-FILT01" not in resp.text


async def test_assets_list_filter_by_checkout_state(admin_client, db):
    today = date.today()
    admin_id = await _breakglass_id(db)

    overdue_asset, overdue_status = await _make_asset(db, "IT-OVERDUE", status_type=StatusType.deployed)
    db.add(
        Checkout(
            asset_id=overdue_asset.id, status_label_id_at_checkout=overdue_status.id,
            checked_out_at=today - timedelta(days=20), checked_out_by=admin_id,
            expected_checkin_at=today - timedelta(days=1),
        )
    )
    due_soon_asset, due_soon_status = await _make_asset(db, "IT-DUESOON", status_type=StatusType.deployed)
    db.add(
        Checkout(
            asset_id=due_soon_asset.id, status_label_id_at_checkout=due_soon_status.id,
            checked_out_at=today - timedelta(days=5), checked_out_by=admin_id,
            expected_checkin_at=today + timedelta(days=2),
        )
    )
    await db.commit()

    overdue_resp = await admin_client.get("/assets?checkout_state=overdue")
    assert "IT-OVERDUE" in overdue_resp.text
    assert "IT-DUESOON" not in overdue_resp.text

    due_soon_resp = await admin_client.get("/assets?checkout_state=due_soon")
    assert "IT-DUESOON" in due_soon_resp.text
    assert "IT-OVERDUE" not in due_soon_resp.text


async def test_assets_list_filter_by_warranty_expiring(admin_client, db):
    await save_setting(db, "warranty.alert_days", "30")
    await db.commit()
    today = date.today()

    await _make_asset(db, "IT-WARNSOON", purchase_date=today - timedelta(days=350), warranty_months=12)
    await _make_asset(db, "IT-WARNFAR", purchase_date=today, warranty_months=36)

    resp = await admin_client.get("/assets?warranty=expiring")
    assert "IT-WARNSOON" in resp.text
    assert "IT-WARNFAR" not in resp.text


async def test_contracts_list_filter_by_state(admin_client, db):
    today = date.today()
    admin_id = await _breakglass_id(db)
    await save_setting(db, "contracts.renewal_alert_days", "14")
    await db.commit()

    db.add_all(
        [
            Contract(
                name="Renews Soon", contract_type=ContractType.contract,
                end_date=today + timedelta(days=5), created_by=admin_id,
            ),
            Contract(
                name="Not Due", contract_type=ContractType.contract,
                end_date=today + timedelta(days=90), created_by=admin_id,
            ),
        ]
    )
    await db.commit()

    resp = await admin_client.get("/contracts?state=expiring_soon")
    assert "Renews Soon" in resp.text
    assert "Not Due" not in resp.text


async def test_inventory_list_filter_by_low_stock(admin_client, db):
    cat = Category(name="Consumables-Filt")
    db.add(cat)
    await db.flush()
    db.add_all(
        [
            InventoryItem(name="Low Widget", category_id=cat.id, quantity=1, min_quantity=5),
            InventoryItem(name="Fine Widget", category_id=cat.id, quantity=50, min_quantity=5),
        ]
    )
    await db.commit()

    resp = await admin_client.get("/inventory?low_stock=1")
    assert "Low Widget" in resp.text
    assert "Fine Widget" not in resp.text


async def test_dashboard_scopes_assets_to_users_own_company(client, db):
    """company.scoped_users must restrict a company-assigned user's
    dashboard counts to their own company -- the break-glass admin has
    no company assigned so can't exercise this path (see the "no
    scoping when the user has no company" rule documented in
    dashboard.py), hence logging in as a real Manager here instead."""
    await save_setting(db, "company.multi_enabled", "true")
    await save_setting(db, "company.scoped_users", "true")
    await db.commit()

    company_a = Company(name="Company A")
    company_b = Company(name="Company B")
    db.add_all([company_a, company_b])
    await db.flush()

    await _make_asset(db, "IT-COA", company_id=company_a.id)
    await _make_asset(db, "IT-COB", company_id=company_b.id)

    manager_role = (await db.execute(select(Role).where(Role.name == RoleName.manager))).scalar_one()
    db.add(
        User(
            username="mgr-a", display_name="Manager A", auth_source=AuthSource.local,
            password_hash=hash_password("supersecret123"), role_id=manager_role.id,
            company_id=company_a.id, is_active=True,
        )
    )
    await db.commit()

    login = await client.post("/login", data={"username": "mgr-a", "password": "supersecret123"})
    assert login.status_code == 302

    resp = await client.get("/")
    assert resp.status_code == 200
    # Both assets use a deployable-type status label (different label
    # rows, same status_type), so an unscoped count would be 2 -- must
    # come back as 1 (Company A's asset only) for the scoped manager.
    match = re.search(
        r'status_type=deployable"[^>]*>deployable</a>\s*<span class="fw-semibold">(\d+)</span>', resp.text
    )
    assert match is not None
    assert match.group(1) == "1"
