"""Settings -> Notifications: smtp.auth_mode (basic | oauth2) and the
OAuth2-specific fields it gates. Chunk 1 of OAuth2 SMTP -- token
fetching and the actual send path are covered separately
(test_smtp_oauth2_token.py, test_notifications_oauth2.py); this file is
only about the settings scaffold: defaults, save/validate, and which
fields the template shows per mode.
"""

from app.core.settings_store import load_settings, save_setting


async def test_default_auth_mode_is_basic_with_no_migration_needed(db):
    """A fresh install (or any pre-existing one) has no smtp.auth_mode
    row at all -- store.get() must fall back to the DEFAULTS default of
    "basic", which is exactly today's behavior (username/password AUTH,
    or none at all when smtp.username is blank). No bootstrap migration
    is needed for this to be correct."""
    store = await load_settings(db)
    assert store.get("smtp.auth_mode") == "basic"


async def test_notifications_page_shows_auth_mode_select(admin_client):
    resp = await admin_client.get("/settings/notifications")
    assert resp.status_code == 200
    assert 'name="smtp.auth_mode"' in resp.text
    assert "OAuth2 (Microsoft 365)" in resp.text
    assert "Basic (username/password)" in resp.text


def _wrapper_style(html: str, data_auth_mode: str) -> str:
    """Returns the inline style attribute text of the FIRST
    auth-mode-field wrapper <div> for the given mode (e.g. 'basic' or
    'oauth2') -- both fields sharing that mode share the same visibility,
    so checking one is representative."""
    marker = f'data-auth-mode="{data_auth_mode}"'
    idx = html.index(marker)
    tag_end = html.index(">", idx)
    return html[idx:tag_end]


async def test_basic_mode_shows_username_password_hides_oauth2_fields(admin_client):
    resp = await admin_client.get("/settings/notifications")
    assert resp.status_code == 200
    assert "display:none" not in _wrapper_style(resp.text, "basic")
    assert "display:none" in _wrapper_style(resp.text, "oauth2")


async def test_oauth2_mode_shows_oauth2_fields_hides_basic_fields(admin_client, db):
    await save_setting(db, "smtp.auth_mode", "oauth2")
    await db.commit()

    resp = await admin_client.get("/settings/notifications")
    assert resp.status_code == 200
    assert "display:none" not in _wrapper_style(resp.text, "oauth2")
    assert "display:none" in _wrapper_style(resp.text, "basic")


async def test_oauth2_client_secret_field_is_masked(admin_client):
    resp = await admin_client.get("/settings/notifications")
    secret_idx = resp.text.index('name="smtp.oauth2_client_secret"')
    field_end = resp.text.index(">", secret_idx)
    assert 'type="password"' in resp.text[secret_idx:field_end]


async def test_save_oauth2_mode_persists_all_fields(admin_client, db):
    resp = await admin_client.post(
        "/settings/notifications",
        data={
            "smtp.enabled": "true",
            "smtp.host": "smtp.office365.com",
            "smtp.port": "587",
            "smtp.security": "starttls",
            "smtp.auth_mode": "oauth2",
            "smtp.oauth2_tenant_id": "11111111-1111-1111-1111-111111111111",
            "smtp.oauth2_client_id": "22222222-2222-2222-2222-222222222222",
            "smtp.oauth2_client_secret": "super-secret-value",
            "smtp.from_address": "itops2@example.com",
        },
    )
    assert resp.status_code == 200
    assert "text-bg-success" in resp.text

    store = await load_settings(db)
    assert store.get("smtp.auth_mode") == "oauth2"
    assert store.get("smtp.oauth2_tenant_id") == "11111111-1111-1111-1111-111111111111"
    assert store.get("smtp.oauth2_client_id") == "22222222-2222-2222-2222-222222222222"
    assert store.get("smtp.oauth2_client_secret") == "super-secret-value"


async def test_save_rejects_unknown_auth_mode(admin_client, db):
    resp = await admin_client.post(
        "/settings/notifications",
        data={
            "smtp.enabled": "false",
            "smtp.host": "",
            "smtp.port": "25",
            "smtp.security": "none",
            "smtp.auth_mode": "kerberos",
            "smtp.from_address": "",
        },
    )
    assert resp.status_code == 200
    assert "text-bg-danger" in resp.text
    assert "Basic or OAuth2" in resp.text

    store = await load_settings(db)
    assert store.get("smtp.auth_mode") == "basic"  # unchanged, save was rejected
