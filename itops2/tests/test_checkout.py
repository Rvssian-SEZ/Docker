"""Checkout/checkin: status-transition rules, the polymorphic-target
validation, and the partial unique index that guarantees at most one
open checkout per asset at the DB level.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.models import (
    Asset,
    AssetModel,
    AuthSource,
    Category,
    Checkout,
    Location,
    Manufacturer,
    StatusLabel,
    StatusType,
    User,
)


async def _setup(db):
    mfr = Manufacturer(name="Dell")
    cat = Category(name="Laptop")
    db.add_all([mfr, cat])
    await db.flush()
    model = AssetModel(name="Latitude 5440", manufacturer_id=mfr.id, category_id=cat.id)
    deployable = StatusLabel(name="Ready to Deploy", status_type=StatusType.deployable)
    deployed = StatusLabel(name="Deployed", status_type=StatusType.deployed)
    pending = StatusLabel(name="In Repair", status_type=StatusType.pending)
    db.add_all([model, deployable, deployed, pending])
    await db.flush()
    asset = Asset(asset_tag="IT-CK01", model_id=model.id, status_label_id=deployable.id)
    db.add(asset)
    await db.commit()
    return asset, deployable, deployed, pending


async def _breakglass_id(db) -> int:
    return (await db.execute(select(User.id).where(User.is_breakglass.is_(True)))).scalar_one()


async def test_checkout_to_location_succeeds(admin_client, db):
    asset, deployable, deployed, pending = await _setup(db)
    location = Location(name="HQ")
    db.add(location)
    await db.commit()

    resp = await admin_client.post(
        f"/assets/{asset.id}/checkout",
        data={"target_location_id": location.id, "status_label_id": deployed.id},
    )
    assert resp.status_code == 204

    await db.refresh(asset)
    assert asset.checked_out_to_location_id == location.id
    assert asset.checked_out_at is not None
    assert asset.status_label_id == deployed.id

    history = (await db.execute(select(Checkout).where(Checkout.asset_id == asset.id))).scalar_one()
    assert history.target_location_id == location.id
    assert history.checked_in_at is None


async def test_checkout_requires_deployable_status(admin_client, db):
    asset, deployable, deployed, pending = await _setup(db)
    asset.status_label_id = pending.id
    await db.commit()

    location = Location(name="HQ")
    db.add(location)
    await db.commit()

    resp = await admin_client.post(
        f"/assets/{asset.id}/checkout",
        data={"target_location_id": location.id, "status_label_id": deployed.id},
    )
    assert "text-bg-danger" in resp.text
    assert "deployable" in resp.text.lower()


async def test_checkout_requires_exactly_one_target(admin_client, db):
    asset, deployable, deployed, pending = await _setup(db)
    resp = await admin_client.post(
        f"/assets/{asset.id}/checkout", data={"status_label_id": deployed.id},
    )
    assert "text-bg-danger" in resp.text
    assert "exactly one target" in resp.text.lower()


async def test_checkout_to_self_asset_rejected(admin_client, db):
    asset, deployable, deployed, pending = await _setup(db)
    resp = await admin_client.post(
        f"/assets/{asset.id}/checkout",
        data={"target_asset_id": asset.id, "status_label_id": deployed.id},
    )
    assert "text-bg-danger" in resp.text
    assert "itself" in resp.text.lower()


async def test_double_checkout_rejected_at_app_layer(admin_client, db):
    """After the first checkout the asset's status is now deployed (not
    deployable), so a second attempt is rejected by the deployable-status
    guard before it can even reach the checked_out_at guard -- both are
    valid, independent rejections of the same double-checkout attempt."""
    asset, deployable, deployed, pending = await _setup(db)
    location = Location(name="HQ")
    db.add(location)
    await db.commit()

    first = await admin_client.post(
        f"/assets/{asset.id}/checkout",
        data={"target_location_id": location.id, "status_label_id": deployed.id},
    )
    assert first.status_code == 204

    second = await admin_client.post(
        f"/assets/{asset.id}/checkout",
        data={"target_location_id": location.id, "status_label_id": deployed.id},
    )
    assert "text-bg-danger" in second.text
    assert "deployable" in second.text.lower() or "already checked out" in second.text.lower()


async def test_double_checkout_rejected_via_checked_out_at_guard(admin_client, db):
    """Directly exercises the checked_out_at guard itself (defense in
    depth): an asset whose status is still deployable but whose
    checked_out_at is already set (an inconsistent state reachable only
    by bypassing the app, e.g. a bug elsewhere) must still be rejected,
    not silently double-checked-out."""
    asset, deployable, deployed, pending = await _setup(db)
    location = Location(name="HQ")
    db.add(location)
    await db.flush()
    asset.checked_out_at = datetime.now(timezone.utc)
    asset.checked_out_to_location_id = location.id
    await db.commit()

    resp = await admin_client.post(
        f"/assets/{asset.id}/checkout",
        data={"target_location_id": location.id, "status_label_id": deployed.id},
    )
    assert "text-bg-danger" in resp.text
    assert "already checked out" in resp.text.lower()


async def test_partial_unique_index_blocks_two_open_checkouts_at_db_level(db):
    """Bypasses the app layer entirely to prove the DB constraint itself
    (not just application logic) enforces at most one open checkout."""
    asset, deployable, deployed, pending = await _setup(db)
    admin_id = await _breakglass_id(db)
    db.add(
        Checkout(
            asset_id=asset.id, status_label_id_at_checkout=deployed.id,
            checked_out_at=datetime.now(timezone.utc), checked_out_by=admin_id,
        )
    )
    await db.commit()

    db.add(
        Checkout(
            asset_id=asset.id, status_label_id_at_checkout=deployed.id,
            checked_out_at=datetime.now(timezone.utc), checked_out_by=admin_id,
        )
    )
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


async def test_checkin_closes_history_and_restores_asset(admin_client, db):
    asset, deployable, deployed, pending = await _setup(db)
    location = Location(name="HQ")
    db.add(location)
    await db.commit()

    await admin_client.post(
        f"/assets/{asset.id}/checkout",
        data={"target_location_id": location.id, "status_label_id": deployed.id},
    )

    resp = await admin_client.post(
        f"/assets/{asset.id}/checkin", data={"status_label_id": deployable.id, "notes": "all good"},
    )
    assert resp.status_code == 204

    await db.refresh(asset)
    assert asset.checked_out_at is None
    assert asset.checked_out_to_location_id is None
    assert asset.status_label_id == deployable.id

    history = (await db.execute(select(Checkout).where(Checkout.asset_id == asset.id))).scalar_one()
    assert history.checked_in_at is not None
    assert history.checkin_status_label_id == deployable.id


async def test_checkin_rejects_deployed_destination(admin_client, db):
    asset, deployable, deployed, pending = await _setup(db)
    location = Location(name="HQ")
    db.add(location)
    await db.commit()
    await admin_client.post(
        f"/assets/{asset.id}/checkout",
        data={"target_location_id": location.id, "status_label_id": deployed.id},
    )

    resp = await admin_client.post(
        f"/assets/{asset.id}/checkin", data={"status_label_id": deployed.id},
    )
    assert "text-bg-danger" in resp.text
    assert "non-deployed" in resp.text.lower()


async def test_checkin_without_open_checkout_rejected(admin_client, db):
    asset, deployable, deployed, pending = await _setup(db)
    resp = await admin_client.post(
        f"/assets/{asset.id}/checkin", data={"status_label_id": deployable.id},
    )
    assert "text-bg-danger" in resp.text
    assert "not currently checked out" in resp.text.lower()


async def _make_target_user(db, username="checkout-target", email="target@example.test"):
    role_id = await _admin_role_id(db)
    user = User(username=username, email=email, auth_source=AuthSource.local, password_hash="x", role_id=role_id)
    db.add(user)
    await db.commit()
    return user


async def _admin_role_id(db) -> int:
    return (await db.execute(select(User.role_id).where(User.is_breakglass.is_(True)))).scalar_one()


async def test_checkout_to_user_notifies_target_by_email(admin_client, db):
    """Wiring test (Phase 8 chunk B): checking an asset out to a user
    with an email queues notify_checkout with that email as the direct
    recipient -- the actual send is covered by test_notifications.py,
    this only proves the router calls it with the right arguments."""
    asset, deployable, deployed, pending = await _setup(db)
    target = await _make_target_user(db, username="checkout-target-1", email="target1@example.test")

    with patch("app.routers.assets.notify_checkout", new_callable=AsyncMock) as mock_notify:
        resp = await admin_client.post(
            f"/assets/{asset.id}/checkout",
            data={"target_user_id": target.id, "status_label_id": deployed.id},
        )
    assert resp.status_code == 204
    mock_notify.assert_called_once_with(asset.asset_tag, target.email)


async def test_checkout_to_location_notifies_with_no_direct_recipient(admin_client, db):
    asset, deployable, deployed, pending = await _setup(db)
    location = Location(name="HQ")
    db.add(location)
    await db.commit()

    with patch("app.routers.assets.notify_checkout", new_callable=AsyncMock) as mock_notify:
        resp = await admin_client.post(
            f"/assets/{asset.id}/checkout",
            data={"target_location_id": location.id, "status_label_id": deployed.id},
        )
    assert resp.status_code == 204
    mock_notify.assert_called_once_with(asset.asset_tag, None)


async def test_checkin_notifies_the_original_target_user(admin_client, db):
    asset, deployable, deployed, pending = await _setup(db)
    target = await _make_target_user(db, username="checkout-target-2", email="target2@example.test")
    await admin_client.post(
        f"/assets/{asset.id}/checkout",
        data={"target_user_id": target.id, "status_label_id": deployed.id},
    )

    with patch("app.routers.assets.notify_checkin", new_callable=AsyncMock) as mock_notify:
        resp = await admin_client.post(
            f"/assets/{asset.id}/checkin", data={"status_label_id": deployable.id},
        )
    assert resp.status_code == 204
    mock_notify.assert_called_once_with(asset.asset_tag, target.email)
