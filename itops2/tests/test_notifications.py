"""Notifications core module (Phase 8 chunk A): SMTP send + the
event/permission gating query. aiosmtplib.send is always mocked here —
these tests never touch a real mail server (the deployed test-send
button already verified the real Postfix relay by hand).
"""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.core.models import AuthSource, NotificationEvent, NotificationSubscription, Role, RoleName, RolePermission, User
from app.core.notifications import send_email_raising, subscribed_recipients
from app.core.settings_store import save_setting


async def _enable_smtp(db, host="mail.example.test", username="", password="", security="none"):
    await save_setting(db, "smtp.enabled", "true")
    await save_setting(db, "smtp.host", host)
    await save_setting(db, "smtp.port", "25")
    await save_setting(db, "smtp.security", security)
    await save_setting(db, "smtp.username", username)
    await save_setting(db, "smtp.password", password)
    await save_setting(db, "smtp.from_address", "itops2@example.test")
    await db.commit()


async def test_send_raises_when_smtp_disabled(db):
    with pytest.raises(RuntimeError, match="not enabled"):
        await send_email_raising("someone@example.test", "subj", "body")


async def test_send_raises_when_host_missing(db):
    await save_setting(db, "smtp.enabled", "true")
    await db.commit()
    with pytest.raises(RuntimeError, match="host is not configured"):
        await send_email_raising("someone@example.test", "subj", "body")


async def test_send_passes_none_credentials_for_unauthenticated_relay(db):
    """The v1 lesson this whole module exists to encode: aiosmtplib
    attempts AUTH even on port 25 if given empty-string creds instead of
    None. Blank username/password in settings must reach aiosmtplib.send
    as literal None, not "". """
    await _enable_smtp(db, username="", password="")
    with patch("app.core.notifications.aiosmtplib.send", new_callable=AsyncMock) as mock_send:
        await send_email_raising("someone@example.test", "subj", "body")
    assert mock_send.call_args.kwargs["username"] is None
    assert mock_send.call_args.kwargs["password"] is None


async def test_send_passes_through_real_credentials_when_configured(db):
    await _enable_smtp(db, username="relayuser", password="relaypass")
    with patch("app.core.notifications.aiosmtplib.send", new_callable=AsyncMock) as mock_send:
        await send_email_raising("someone@example.test", "subj", "body")
    assert mock_send.call_args.kwargs["username"] == "relayuser"
    assert mock_send.call_args.kwargs["password"] == "relaypass"


@pytest.mark.parametrize(
    "security,expected_use_tls,expected_start_tls",
    [
        ("none", False, False),
        ("starttls", False, True),
        ("tls", True, False),
    ],
)
async def test_send_maps_security_mode_to_explicit_tls_kwargs(db, security, expected_use_tls, expected_start_tls):
    """The bug this fix closes: a single smtp.use_tls bool couldn't tell
    STARTTLS (port 587, plaintext-then-upgrade) from implicit TLS (port
    465, TLS from the first byte) apart, which broke O365:587 with
    WRONG_VERSION_NUMBER -- aiosmtplib spoke plaintext at a socket the
    server expected a TLS ClientHello on. Both kwargs must be explicit,
    nothing left to aiosmtplib's own port-based guessing."""
    await _enable_smtp(db, security=security)
    with patch("app.core.notifications.aiosmtplib.send", new_callable=AsyncMock) as mock_send:
        await send_email_raising("someone@example.test", "subj", "body")
    assert mock_send.call_args.kwargs["use_tls"] is expected_use_tls
    assert mock_send.call_args.kwargs["start_tls"] is expected_start_tls


async def test_test_send_route_reports_failure_as_toast(admin_client, db):
    await _enable_smtp(db)
    with patch("app.core.notifications.aiosmtplib.send", new_callable=AsyncMock) as mock_send:
        mock_send.side_effect = OSError("Connection refused")
        resp = await admin_client.post("/settings/notifications/test-send", data={"to": "x@example.test"})
    assert resp.status_code == 200
    assert "text-bg-danger" in resp.text
    assert "Connection refused" in resp.text


async def test_test_send_route_reports_success_as_toast(admin_client, db):
    await _enable_smtp(db)
    with patch("app.core.notifications.aiosmtplib.send", new_callable=AsyncMock):
        resp = await admin_client.post("/settings/notifications/test-send", data={"to": "x@example.test"})
    assert resp.status_code == 200
    assert "text-bg-success" in resp.text


async def test_subscribed_recipients_respects_permission_grant(db):
    """A subscription alone isn't enough -- the recipient's role must
    also hold the event's required permission (assets.view, for
    checkout_performed). Viewer has assets.view by default, so revoke it
    for this test to prove the join actually filters, then re-grant to
    prove it comes back."""
    viewer_role = (
        await db.execute(select(Role).where(Role.name == RoleName.viewer))
    ).scalar_one()
    user = User(
        username="notif-viewer",
        email="viewer@example.test",
        auth_source=AuthSource.local,
        password_hash="x",
        role_id=viewer_role.id,
    )
    db.add(user)
    await db.flush()
    db.add(NotificationSubscription(user_id=user.id, event_type=NotificationEvent.checkout_performed))
    await db.commit()

    grant = (
        await db.execute(
            select(RolePermission).where(
                RolePermission.role_id == viewer_role.id, RolePermission.permission == "assets.view"
            )
        )
    ).scalar_one()
    await db.delete(grant)
    await db.commit()
    try:
        assert "viewer@example.test" not in await subscribed_recipients("checkout_performed")
    finally:
        # core_role_permissions is seeded once and never truncated between
        # tests -- always restore it, even on assertion failure, so a
        # failure here can't silently break every other test in this run.
        db.add(RolePermission(role_id=viewer_role.id, permission="assets.view"))
        await db.commit()
    assert "viewer@example.test" in await subscribed_recipients("checkout_performed")


# ---- /profile subscription checklist (chunk B) ----

async def test_profile_lists_available_events_and_toggle_persists(admin_client, db):
    resp = await admin_client.get("/profile")
    assert resp.status_code == 200
    assert "Asset checked out" in resp.text
    assert "Contract renewal due" in resp.text  # admin holds contracts.view -> event offered

    toggle = await admin_client.post(
        "/profile/notifications/toggle",
        data={"event_type": "contract_renewal_due", "subscribed": "true"},
    )
    assert toggle.status_code == 200
    assert "text-bg-success" in toggle.text

    admin_id = (await db.execute(select(User.id).where(User.is_breakglass.is_(True)))).scalar_one()
    row = (
        await db.execute(
            select(NotificationSubscription).where(
                NotificationSubscription.user_id == admin_id,
                NotificationSubscription.event_type == NotificationEvent.contract_renewal_due,
            )
        )
    ).scalar_one_or_none()
    assert row is not None

    untoggle = await admin_client.post(
        "/profile/notifications/toggle",
        data={"event_type": "contract_renewal_due", "subscribed": "false"},
    )
    assert untoggle.status_code == 200
    row = (
        await db.execute(
            select(NotificationSubscription).where(
                NotificationSubscription.user_id == admin_id,
                NotificationSubscription.event_type == NotificationEvent.contract_renewal_due,
            )
        )
    ).scalar_one_or_none()
    assert row is None


async def test_profile_toggle_rejects_unknown_event_type(admin_client):
    resp = await admin_client.post(
        "/profile/notifications/toggle", data={"event_type": "not_a_real_event", "subscribed": "true"},
    )
    assert "text-bg-danger" in resp.text
    assert "unknown event type" in resp.text.lower()


async def test_profile_toggle_rejects_event_without_permission(admin_client, db):
    """Same lockout-safety idea as test_subscribed_recipients_respects_permission_grant:
    a user shouldn't even be able to subscribe to an event their role
    can't receive. Temporarily revokes the admin role's contracts.view
    to exercise the reject path, always restoring it afterward."""
    admin_role = (await db.execute(select(Role).where(Role.name == RoleName.admin))).scalar_one()
    grant = (
        await db.execute(
            select(RolePermission).where(
                RolePermission.role_id == admin_role.id, RolePermission.permission == "contracts.view"
            )
        )
    ).scalar_one()
    await db.delete(grant)
    await db.commit()
    try:
        resp = await admin_client.post(
            "/profile/notifications/toggle", data={"event_type": "contract_renewal_due", "subscribed": "true"},
        )
        assert "text-bg-danger" in resp.text
        assert "do not have permission" in resp.text.lower()
    finally:
        db.add(RolePermission(role_id=admin_role.id, permission="contracts.view"))
        await db.commit()
