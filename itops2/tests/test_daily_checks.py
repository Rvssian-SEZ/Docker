"""Phase 8 chunk C: the daily scheduled checks (warranty/contract
renewal/low stock) and the idempotency gate around them.
notify_event() is always mocked here — actual SMTP sending is covered
by test_notifications.py.
"""

from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from app.core.daily_checks import _add_months, run_daily_checks, run_if_due
from app.core.models import (
    Asset,
    AssetModel,
    Category,
    Contract,
    ContractType,
    InventoryItem,
    Manufacturer,
    StatusLabel,
    StatusType,
    User,
)
from app.core.settings_store import save_setting


async def _breakglass_id(db) -> int:
    return (await db.execute(select(User.id).where(User.is_breakglass.is_(True)))).scalar_one()


def test_add_months_clamps_to_shorter_target_month():
    assert _add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)  # 2026 not a leap year
    assert _add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)  # 2024 is a leap year


def test_add_months_rolls_over_year():
    assert _add_months(date(2026, 11, 15), 3) == date(2027, 2, 15)


def test_add_months_zero_is_identity():
    assert _add_months(date(2026, 7, 14), 0) == date(2026, 7, 14)


async def _make_asset_with_warranty(db, tag, purchase_date, warranty_months):
    mfr = Manufacturer(name=f"Mfr-{tag}")
    cat = Category(name=f"Cat-{tag}")
    db.add_all([mfr, cat])
    await db.flush()
    model = AssetModel(name="M", manufacturer_id=mfr.id, category_id=cat.id)
    status = StatusLabel(name=f"Status-{tag}", status_type=StatusType.deployable)
    db.add_all([model, status])
    await db.flush()
    asset = Asset(
        asset_tag=tag, model_id=model.id, status_label_id=status.id,
        purchase_date=purchase_date, warranty_months=warranty_months,
    )
    db.add(asset)
    await db.commit()
    return asset


async def test_warranty_check_sends_digest_only_for_assets_in_window(db):
    today = date.today()
    await save_setting(db, "warranty.alert_days", "30")
    await db.commit()

    await _make_asset_with_warranty(db, "IT-WARN-SOON", today - timedelta(days=350), 12)  # expires in 15 days
    await _make_asset_with_warranty(db, "IT-WARN-FAR", today, 24)  # expires in 2 years -- outside window
    await _make_asset_with_warranty(db, "IT-WARN-PAST", today - timedelta(days=400), 12)  # already expired

    with patch("app.core.daily_checks.notify_event", new_callable=AsyncMock) as mock_notify:
        await run_daily_checks()

    warranty_calls = [c for c in mock_notify.call_args_list if c.args[0] == "warranty_expiring"]
    assert len(warranty_calls) == 1
    assert "IT-WARN-SOON" in warranty_calls[0].args[2]
    assert "IT-WARN-FAR" not in warranty_calls[0].args[2]
    assert "IT-WARN-PAST" not in warranty_calls[0].args[2]


async def test_warranty_check_sends_nothing_when_none_qualify(db):
    with patch("app.core.daily_checks.notify_event", new_callable=AsyncMock) as mock_notify:
        await run_daily_checks()
    assert not any(c.args[0] == "warranty_expiring" for c in mock_notify.call_args_list)


async def test_contract_renewal_check_mirrors_expiring_soon_state(db):
    today = date.today()
    await save_setting(db, "contracts.renewal_alert_days", "14")
    await db.commit()
    admin_id = await _breakglass_id(db)

    db.add_all(
        [
            Contract(
                name="Due Soon", contract_type=ContractType.contract,
                end_date=today + timedelta(days=5), created_by=admin_id,
            ),
            Contract(
                name="Not Due Yet", contract_type=ContractType.contract,
                end_date=today + timedelta(days=60), created_by=admin_id,
            ),
            Contract(
                name="Already Expired", contract_type=ContractType.contract,
                end_date=today - timedelta(days=5), created_by=admin_id,
            ),
        ]
    )
    await db.commit()

    with patch("app.core.daily_checks.notify_event", new_callable=AsyncMock) as mock_notify:
        await run_daily_checks()

    calls = [c for c in mock_notify.call_args_list if c.args[0] == "contract_renewal_due"]
    assert len(calls) == 1
    assert "Due Soon" in calls[0].args[2]
    assert "Not Due Yet" not in calls[0].args[2]
    assert "Already Expired" not in calls[0].args[2]


async def test_low_stock_check_matches_list_page_badge_condition(db):
    cat = Category(name="Consumables")
    db.add(cat)
    await db.flush()
    db.add_all(
        [
            InventoryItem(name="Toner Low", category_id=cat.id, quantity=2, min_quantity=5),
            InventoryItem(name="Toner Fine", category_id=cat.id, quantity=50, min_quantity=5),
            InventoryItem(name="No Threshold Set", category_id=cat.id, quantity=0, min_quantity=None),
        ]
    )
    await db.commit()

    with patch("app.core.daily_checks.notify_event", new_callable=AsyncMock) as mock_notify:
        await run_daily_checks()

    calls = [c for c in mock_notify.call_args_list if c.args[0] == "inventory_low_stock"]
    assert len(calls) == 1
    assert "Toner Low" in calls[0].args[2]
    assert "Toner Fine" not in calls[0].args[2]
    assert "No Threshold Set" not in calls[0].args[2]


async def test_run_if_due_is_idempotent_within_the_same_day(db):
    """Simulates two ticks straddling a restart: same calendar day, two
    separate calls to run_if_due() (each opens its own session, exactly
    like two real ticks would) -- only the first should actually run
    the checks."""
    with patch("app.core.daily_checks.run_daily_checks", new_callable=AsyncMock) as mock_run:
        first = await run_if_due()
        second = await run_if_due()

    assert first is True
    assert second is False
    mock_run.assert_called_once()
