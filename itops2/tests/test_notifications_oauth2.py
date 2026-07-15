"""app/core/notifications.py's OAuth2 (XOAUTH2) send path -- the piece
that wires app/core/smtp_oauth2.py into send_email_raising() and, via
that, the Settings test-send button. aiosmtplib.SMTP and the token/auth
functions are all mocked; no real Microsoft tenant is reachable from
this environment (see CLAUDE.md: built and unit-tested, awaiting live
tenant verification).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.notifications import send_email_raising
from app.core.settings_store import save_setting
from app.core.smtp_oauth2 import XOAuth2Error


async def _enable_oauth2_smtp(
    db, host="smtp.office365.com", port="587", security="starttls",
    tenant="tenant-1", client="client-1", secret="secret-1",
):
    await save_setting(db, "smtp.enabled", "true")
    await save_setting(db, "smtp.host", host)
    await save_setting(db, "smtp.port", port)
    await save_setting(db, "smtp.security", security)
    await save_setting(db, "smtp.auth_mode", "oauth2")
    await save_setting(db, "smtp.oauth2_tenant_id", tenant)
    await save_setting(db, "smtp.oauth2_client_id", client)
    await save_setting(db, "smtp.oauth2_client_secret", secret)
    await save_setting(db, "smtp.from_address", "itops2@example.test")
    await db.commit()


def _mock_smtp_instance():
    instance = MagicMock()
    instance.connect = AsyncMock()
    instance.starttls = AsyncMock()
    instance.ehlo = AsyncMock()
    instance.send_message = AsyncMock()
    instance.quit = AsyncMock()
    return instance


async def test_oauth2_send_does_the_full_dance_in_order(db):
    await _enable_oauth2_smtp(db)
    instance = _mock_smtp_instance()
    with (
        patch("app.core.notifications.get_access_token", new=AsyncMock(return_value="tok-abc")) as mock_token,
        patch("app.core.notifications.aiosmtplib.SMTP", new=MagicMock(return_value=instance)) as mock_smtp_cls,
        patch("app.core.notifications.xoauth2_authenticate", new=AsyncMock()) as mock_auth,
        patch("app.core.notifications.aiosmtplib.send", new=AsyncMock()) as mock_send,
    ):
        await send_email_raising("someone@example.test", "subj", "body")

    mock_token.assert_awaited_once_with("tenant-1", "client-1", "secret-1")
    mock_smtp_cls.assert_called_once()
    assert mock_smtp_cls.call_args.kwargs["hostname"] == "smtp.office365.com"
    assert mock_smtp_cls.call_args.kwargs["port"] == 587
    instance.connect.assert_awaited_once()
    instance.starttls.assert_awaited_once()
    instance.ehlo.assert_awaited_once()
    mock_auth.assert_awaited_once_with(instance, "itops2@example.test", "tok-abc")
    instance.send_message.assert_awaited_once()
    instance.quit.assert_awaited_once()
    mock_send.assert_not_called()  # basic-mode convenience function must not be used


async def test_oauth2_uses_starttls_regardless_of_smtp_security(db):
    """oauth2 mode always STARTTLS -- smtp.security is a basic-mode-only
    choice and must not affect how the SMTP instance is constructed."""
    await _enable_oauth2_smtp(db, security="tls")  # deliberately "wrong" for oauth2
    instance = _mock_smtp_instance()
    with (
        patch("app.core.notifications.get_access_token", new=AsyncMock(return_value="tok")),
        patch("app.core.notifications.aiosmtplib.SMTP", new=MagicMock(return_value=instance)) as mock_smtp_cls,
        patch("app.core.notifications.xoauth2_authenticate", new=AsyncMock()),
    ):
        await send_email_raising("someone@example.test", "subj", "body")

    assert mock_smtp_cls.call_args.kwargs["use_tls"] is False
    assert mock_smtp_cls.call_args.kwargs["start_tls"] is False
    instance.starttls.assert_awaited_once()


async def test_oauth2_missing_credentials_raises_before_connecting(db):
    await _enable_oauth2_smtp(db, tenant="", client="client-1", secret="secret-1")
    with (
        patch("app.core.notifications.get_access_token", new=AsyncMock()) as mock_token,
        patch("app.core.notifications.aiosmtplib.SMTP", new=MagicMock()) as mock_smtp_cls,
    ):
        with pytest.raises(RuntimeError, match="tenant ID, client ID, and client secret"):
            await send_email_raising("someone@example.test", "subj", "body")
    mock_token.assert_not_awaited()
    mock_smtp_cls.assert_not_called()


async def test_oauth2_quit_called_even_when_auth_fails(db):
    await _enable_oauth2_smtp(db)
    instance = _mock_smtp_instance()
    with (
        patch("app.core.notifications.get_access_token", new=AsyncMock(return_value="tok")),
        patch("app.core.notifications.aiosmtplib.SMTP", new=MagicMock(return_value=instance)),
        patch(
            "app.core.notifications.xoauth2_authenticate",
            new=AsyncMock(side_effect=XOAuth2Error("XOAUTH2 authentication failed: status=535")),
        ),
    ):
        with pytest.raises(XOAuth2Error, match="status=535"):
            await send_email_raising("someone@example.test", "subj", "body")
    instance.quit.assert_awaited_once()
    instance.send_message.assert_not_awaited()  # never reached -- auth failed first


async def test_basic_mode_never_touches_oauth2_code_path(db):
    """Regression: the default (basic) mode must still go through
    aiosmtplib.send() exactly as before -- oauth2 machinery must not be
    invoked just because it exists."""
    await save_setting(db, "smtp.enabled", "true")
    await save_setting(db, "smtp.host", "mail.example.test")
    await save_setting(db, "smtp.port", "25")
    await save_setting(db, "smtp.security", "none")
    await save_setting(db, "smtp.from_address", "itops2@example.test")
    await db.commit()  # smtp.auth_mode left unset -> defaults to "basic"

    with (
        patch("app.core.notifications.aiosmtplib.send", new=AsyncMock()) as mock_send,
        patch("app.core.notifications.get_access_token", new=AsyncMock()) as mock_token,
        patch("app.core.notifications.aiosmtplib.SMTP", new=MagicMock()) as mock_smtp_cls,
    ):
        await send_email_raising("someone@example.test", "subj", "body")

    mock_send.assert_awaited_once()
    mock_token.assert_not_awaited()
    mock_smtp_cls.assert_not_called()


# ---- test-send button (Settings -> Notifications) ----

async def test_test_send_route_surfaces_xoauth2_error_message(admin_client, db):
    await _enable_oauth2_smtp(db)
    instance = _mock_smtp_instance()
    with (
        patch("app.core.notifications.get_access_token", new=AsyncMock(return_value="tok")),
        patch("app.core.notifications.aiosmtplib.SMTP", new=MagicMock(return_value=instance)),
        patch(
            "app.core.notifications.xoauth2_authenticate",
            new=AsyncMock(side_effect=XOAuth2Error("XOAUTH2 authentication failed: status=535; schemes=bearer")),
        ),
    ):
        resp = await admin_client.post("/settings/notifications/test-send", data={"to": "x@example.test"})
    assert resp.status_code == 200
    assert "text-bg-danger" in resp.text
    assert "status=535" in resp.text


async def test_test_send_route_succeeds_in_oauth2_mode(admin_client, db):
    await _enable_oauth2_smtp(db)
    instance = _mock_smtp_instance()
    with (
        patch("app.core.notifications.get_access_token", new=AsyncMock(return_value="tok")),
        patch("app.core.notifications.aiosmtplib.SMTP", new=MagicMock(return_value=instance)),
        patch("app.core.notifications.xoauth2_authenticate", new=AsyncMock()),
    ):
        resp = await admin_client.post("/settings/notifications/test-send", data={"to": "x@example.test"})
    assert resp.status_code == 200
    assert "text-bg-success" in resp.text
    instance.send_message.assert_awaited_once()


async def test_test_send_route_surfaces_token_error_message(admin_client, db):
    from app.core.smtp_oauth2 import OAuth2TokenError

    await _enable_oauth2_smtp(db)
    with patch(
        "app.core.notifications.get_access_token",
        new=AsyncMock(side_effect=OAuth2TokenError("Token request failed (401): AADSTS7000215: Invalid client secret.")),
    ):
        resp = await admin_client.post("/settings/notifications/test-send", data={"to": "x@example.test"})
    assert resp.status_code == 200
    assert "text-bg-danger" in resp.text
    assert "Invalid client secret" in resp.text
