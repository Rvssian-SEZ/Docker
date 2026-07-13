"""Contracts: CRUD, the cost-requires-currency validation, the renewal
state (expired/expiring_soon/normal) computation, asset linking/
unlinking (CASCADE on delete), and attachment cleanup on delete.
"""

from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.core.models import (
    Asset,
    AssetModel,
    Attachment,
    Category,
    Contract,
    ContractAsset,
    Manufacturer,
    StatusLabel,
    StatusType,
)


async def _make_contract_data(end_date="2026-12-31"):
    return {
        "name": "Office 365 Subscription",
        "contract_type": "subscription",
        "vendor": "Microsoft",
        "start_date": "2026-01-01",
        "end_date": end_date,
        "cost": "100.00",
        "currency": "SCR",
    }


async def _make_asset(db, tag="IT-CT01"):
    mfr = Manufacturer(name=f"Dell-{tag}")
    cat = Category(name=f"Laptop-{tag}")
    db.add_all([mfr, cat])
    await db.flush()
    model = AssetModel(name="Latitude 5440", manufacturer_id=mfr.id, category_id=cat.id)
    deployable = (
        await db.execute(select(StatusLabel).where(StatusLabel.name == "Ready to Deploy"))
    ).scalar_one_or_none()
    if deployable is None:
        deployable = StatusLabel(name="Ready to Deploy", status_type=StatusType.deployable)
        db.add(deployable)
        await db.flush()
    db.add(model)
    await db.flush()
    asset = Asset(asset_tag=tag, model_id=model.id, status_label_id=deployable.id)
    db.add(asset)
    await db.commit()
    return asset


async def test_create_contract(admin_client, db):
    resp = await admin_client.post("/contracts/create", data=await _make_contract_data())
    assert resp.status_code == 204
    assert resp.headers["hx-redirect"].startswith("/contracts/")

    row = (await db.execute(select(Contract).where(Contract.name == "Office 365 Subscription"))).scalar_one()
    assert row.contract_type.value == "subscription"
    assert row.vendor == "Microsoft"
    assert str(row.cost) == "100.00"


async def test_cost_requires_currency(admin_client, db):
    data = await _make_contract_data()
    data.pop("currency")
    resp = await admin_client.post("/contracts/create", data=data)
    assert "text-bg-danger" in resp.text
    assert "currency" in resp.text.lower()
    count = (await db.execute(select(Contract.id))).all()
    assert count == []


async def test_end_date_required(admin_client, db):
    """A real <input type=date> always submits the field, even empty --
    unlike dict.pop(), which would trigger FastAPI's own 422 instead of
    the app's friendly-toast validation path."""
    data = await _make_contract_data()
    data["end_date"] = ""
    resp = await admin_client.post("/contracts/create", data=data)
    assert "text-bg-danger" in resp.text


async def test_update_contract(admin_client, db):
    await admin_client.post("/contracts/create", data=await _make_contract_data())
    row = (await db.execute(select(Contract))).scalar_one()

    data = await _make_contract_data()
    data["name"] = "Office 365 (renamed)"
    data["auto_renews"] = "true"
    resp = await admin_client.post(f"/contracts/{row.id}/update", data=data)
    assert resp.status_code == 200
    assert "text-bg-success" in resp.text

    await db.refresh(row)
    assert row.name == "Office 365 (renamed)"
    assert row.auto_renews is True


async def test_renewal_states_shown_on_list(admin_client, db):
    today = date.today()
    expired = await _make_contract_data(end_date=str(today - timedelta(days=5)))
    expired["name"] = "Expired Contract"
    soon = await _make_contract_data(end_date=str(today + timedelta(days=5)))
    soon["name"] = "Soon Contract"
    normal = await _make_contract_data(end_date=str(today + timedelta(days=365)))
    normal["name"] = "Normal Contract"

    for data in (expired, soon, normal):
        await admin_client.post("/contracts/create", data=data)

    resp = await admin_client.get("/contracts")
    assert resp.status_code == 200
    assert "expired" in resp.text
    # default contracts.renewal_alert_days is 30, so +5 days is "soon"
    assert ">soon<" in resp.text
    # find rows via table-warning/table-danger classes
    assert "table-danger" in resp.text
    assert "table-warning" in resp.text


async def test_link_and_unlink_asset(admin_client, db):
    await admin_client.post("/contracts/create", data=await _make_contract_data())
    contract = (await db.execute(select(Contract))).scalar_one()
    asset = await _make_asset(db)

    resp = await admin_client.post(f"/contracts/{contract.id}/assets/link", data={"asset_id": asset.id})
    assert resp.status_code == 204

    link = (
        await db.execute(
            select(ContractAsset).where(ContractAsset.contract_id == contract.id, ContractAsset.asset_id == asset.id)
        )
    ).scalar_one_or_none()
    assert link is not None

    # duplicate link rejected
    dup = await admin_client.post(f"/contracts/{contract.id}/assets/link", data={"asset_id": asset.id})
    assert "already linked" in dup.text.lower()

    unlink = await admin_client.post(f"/contracts/{contract.id}/assets/{asset.id}/unlink")
    assert unlink.status_code == 204
    link_after = (
        await db.execute(
            select(ContractAsset).where(ContractAsset.contract_id == contract.id, ContractAsset.asset_id == asset.id)
        )
    ).scalar_one_or_none()
    assert link_after is None


async def test_deleting_asset_cascades_contract_link(admin_client, db):
    """The one deliberate CASCADE in this schema: deleting an asset must
    not be blocked by (nor leave orphaned) a contract coverage link."""
    await admin_client.post("/contracts/create", data=await _make_contract_data())
    contract = (await db.execute(select(Contract))).scalar_one()
    asset = await _make_asset(db)
    await admin_client.post(f"/contracts/{contract.id}/assets/link", data={"asset_id": asset.id})

    resp = await admin_client.post(f"/assets/{asset.id}/delete")
    assert resp.status_code == 204

    link_after = (
        await db.execute(select(ContractAsset).where(ContractAsset.asset_id == asset.id))
    ).scalar_one_or_none()
    assert link_after is None


async def test_delete_contract_removes_attachments(admin_client, db):
    await admin_client.post("/contracts/create", data=await _make_contract_data())
    contract = (await db.execute(select(Contract))).scalar_one()

    await admin_client.post(
        f"/contracts/{contract.id}/attachments", files={"file": ("agreement.pdf", b"pdf bytes", "application/pdf")},
    )
    att = (await db.execute(select(Attachment).where(Attachment.entity_id == str(contract.id)))).scalar_one()
    on_disk = Path(get_settings().attachments_dir) / "contract" / str(contract.id) / att.stored_filename
    assert on_disk.exists()

    resp = await admin_client.post(f"/contracts/{contract.id}/delete")
    assert resp.status_code == 204

    assert (await db.execute(select(Contract).where(Contract.id == contract.id))).scalar_one_or_none() is None
    assert (await db.execute(select(Attachment).where(Attachment.id == att.id))).scalar_one_or_none() is None
    assert not on_disk.exists()


async def test_contract_attachment_download_roundtrip(admin_client, db):
    await admin_client.post("/contracts/create", data=await _make_contract_data())
    contract = (await db.execute(select(Contract))).scalar_one()

    await admin_client.post(
        f"/contracts/{contract.id}/attachments", files={"file": ("terms.txt", b"terms and conditions", "text/plain")},
    )
    att = (await db.execute(select(Attachment).where(Attachment.entity_id == str(contract.id)))).scalar_one()

    resp = await admin_client.get(f"/contracts/{contract.id}/attachments/{att.id}/download")
    assert resp.status_code == 200
    assert resp.content == b"terms and conditions"
