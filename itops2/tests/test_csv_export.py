"""CSV export: the shared helper (app/core/csv_export.py), the
require_all permission gate, company scoping, and one export route per
list view (Assets/Printers/Contracts/Inventory/Users) proving the CSV
reflects exactly the current filtered view.
"""

from datetime import date, datetime, timezone

from sqlalchemy import select

from app.core.csv_export import csv_response, fmt_date, fmt_datetime
from app.core.models import (
    Asset,
    AssetModel,
    AuthSource,
    Category,
    Company,
    Contract,
    ContractType,
    InventoryItem,
    Manufacturer,
    PrinterDetails,
    Role,
    RoleName,
    RolePermission,
    StatusLabel,
    StatusType,
    User,
)
from app.core.security import hash_password
from app.core.settings_store import save_setting


async def _breakglass_id(db) -> int:
    return (await db.execute(select(User.id).where(User.is_breakglass.is_(True)))).scalar_one()


def test_fmt_date_uses_uk_format():
    assert fmt_date(date(2026, 7, 14)) == "14/07/2026"
    assert fmt_date(None) == ""


def test_fmt_datetime_uses_uk_format():
    assert fmt_datetime(datetime(2026, 7, 14, 9, 5, tzinfo=timezone.utc)) == "14/07/2026 09:05"
    assert fmt_datetime(None) == ""


def test_csv_response_has_utf8_bom_and_header_row():
    resp = csv_response("test.csv", ["a", "b"], [{"a": "1", "b": "2"}])
    assert resp.media_type == "text/csv"
    assert 'filename="test.csv"' in resp.headers["content-disposition"]
    assert resp.body.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM
    text = resp.body.decode("utf-8-sig")
    assert text.splitlines()[0] == "a,b"
    assert text.splitlines()[1] == "1,2"


async def _make_asset(db, tag, *, company=None):
    mfr = Manufacturer(name=f"Mfr-{tag}")
    cat = Category(name=f"Cat-{tag}")
    db.add_all([mfr, cat])
    await db.flush()
    model = AssetModel(name="Latitude 5440", manufacturer_id=mfr.id, category_id=cat.id)
    status = StatusLabel(name=f"Status-{tag}", status_type=StatusType.deployable)
    db.add_all([model, status])
    await db.flush()
    asset = Asset(
        asset_tag=tag, model_id=model.id, status_label_id=status.id,
        company_id=company.id if company else None,
    )
    db.add(asset)
    await db.commit()
    return asset


async def test_assets_export_requires_reports_export_permission(admin_client, db):
    """Revoking reports.export from Admin (while assets.view stays
    granted) must 403 the export route even though the list page itself
    still works -- proves the gate checks BOTH permissions, not just
    the base view permission."""
    admin_role = (await db.execute(select(Role).where(Role.name == RoleName.admin))).scalar_one()
    grant = (
        await db.execute(
            select(RolePermission).where(
                RolePermission.role_id == admin_role.id, RolePermission.permission == "reports.export"
            )
        )
    ).scalar_one()
    await db.delete(grant)
    await db.commit()
    try:
        resp = await admin_client.get("/assets/export")
        assert resp.status_code == 403
        list_resp = await admin_client.get("/assets")
        assert list_resp.status_code == 200
    finally:
        db.add(RolePermission(role_id=admin_role.id, permission="reports.export"))
        await db.commit()


async def test_assets_export_matches_current_filter(admin_client, db):
    await _make_asset(db, "IT-EXPA")
    await _make_asset(db, "IT-EXPB")

    resp = await admin_client.get("/assets?q=EXPA")
    assert resp.status_code == 200

    export = await admin_client.get("/assets/export?q=EXPA")
    assert export.status_code == 200
    assert export.headers["content-type"].startswith("text/csv")
    text = export.content.decode("utf-8-sig")
    assert "IT-EXPA" in text
    assert "IT-EXPB" not in text
    assert text.splitlines()[0] == "asset_tag,serial,manufacturer,model,category,status,company,location,purchase_date,purchase_cost,purchase_currency,warranty_months,checked_out_to"


async def test_assets_export_respects_company_scoping(client, db):
    await save_setting(db, "company.multi_enabled", "true")
    await save_setting(db, "company.scoped_users", "true")
    await db.commit()

    co_a = Company(name="Export Company A")
    co_b = Company(name="Export Company B")
    db.add_all([co_a, co_b])
    await db.commit()
    await _make_asset(db, "IT-SCOPEA", company=co_a)
    await _make_asset(db, "IT-SCOPEB", company=co_b)

    manager_role = (await db.execute(select(Role).where(Role.name == RoleName.manager))).scalar_one()
    db.add(
        User(
            username="export-mgr-a", display_name="Export Manager A", auth_source=AuthSource.local,
            password_hash=hash_password("supersecret123"), role_id=manager_role.id,
            company_id=co_a.id, is_active=True,
        )
    )
    await db.commit()

    login = await client.post("/login", data={"username": "export-mgr-a", "password": "supersecret123"})
    assert login.status_code == 302
    resp = await client.get("/assets/export")
    assert resp.status_code == 200
    text = resp.content.decode("utf-8-sig")
    assert "IT-SCOPEA" in text
    assert "IT-SCOPEB" not in text


async def test_printers_export_includes_hostname_and_ip(admin_client, db):
    asset = await _make_asset(db, "IT-PREXP")
    db.add(PrinterDetails(asset_id=asset.id, hostname="printer-export-host", ip_address="10.1.1.1"))
    # Not actually a Printer-category asset per _make_asset's Category name -- adjust category to "Printer".
    cat = (await db.execute(select(Category).where(Category.name == "Cat-IT-PREXP"))).scalar_one()
    cat.name = "Printer"
    await db.commit()

    resp = await admin_client.get("/printers/export")
    assert resp.status_code == 200
    text = resp.content.decode("utf-8-sig")
    assert "IT-PREXP" in text
    assert "printer-export-host" in text
    assert "10.1.1.1" in text


async def test_contracts_export_matches_current_filter(admin_client, db):
    admin_id = await _breakglass_id(db)
    db.add_all(
        [
            Contract(
                name="Export Match", contract_type=ContractType.license,
                end_date=date(2027, 3, 15), created_by=admin_id,
            ),
            Contract(
                name="Export Other", contract_type=ContractType.subscription,
                end_date=date(2027, 6, 1), created_by=admin_id,
            ),
        ]
    )
    await db.commit()

    resp = await admin_client.get("/contracts/export?contract_type=license")
    assert resp.status_code == 200
    text = resp.content.decode("utf-8-sig")
    assert "Export Match" in text
    assert "Export Other" not in text
    assert "15/03/2027" in text  # UK date format


async def test_inventory_export_matches_current_filter(admin_client, db):
    cat = Category(name="Export Cat")
    db.add(cat)
    await db.commit()
    db.add_all(
        [
            InventoryItem(name="Export Low", category_id=cat.id, quantity=1, min_quantity=5),
            InventoryItem(name="Export Fine", category_id=cat.id, quantity=50, min_quantity=5),
        ]
    )
    await db.commit()

    resp = await admin_client.get("/inventory/export?low_stock=1")
    assert resp.status_code == 200
    text = resp.content.decode("utf-8-sig")
    assert "Export Low" in text
    assert "Export Fine" not in text


async def test_users_export_lists_users(admin_client, db, settings):
    resp = await admin_client.get("/users/export")
    assert resp.status_code == 200
    text = resp.content.decode("utf-8-sig")
    assert settings.breakglass_username in text
    assert text.splitlines()[0] == "username,display_name,email,role,company,auth_source,is_active,last_login_at"
