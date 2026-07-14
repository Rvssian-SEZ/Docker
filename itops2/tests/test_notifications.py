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


async def _enable_smtp(db, host="mail.example.test", username="", password=""):
    await save_setting(db, "smtp.enabled", "true")
    await save_setting(db, "smtp.host", host)
    await save_setting(db, "smtp.port", "25")
    await save_setting(db, "smtp.use_tls", "false")
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
