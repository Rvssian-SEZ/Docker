"""Typed access to core_settings (runtime-tunable configuration).

All runtime behaviour settings live here, edited in the Settings UI.
Every key must be registered in DEFAULTS — unknown keys are rejected so
typos don't silently create dead settings.

Values are stored as text; booleans as "true"/"false".
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import AppSetting

# key -> (default, type)  — type in {"str", "bool", "int"}
DEFAULTS: dict[str, tuple[str, str]] = {
    # General
    "general.site_name": ("ITOps v2", "str"),
    "general.default_currency": ("SCR", "str"),
    # Asset tags
    "asset_tag.prefix": ("IT-", "str"),
    "asset_tag.pad": ("4", "int"),
    # Companies
    "company.multi_enabled": ("false", "bool"),
    "company.scoped_users": ("false", "bool"),
    # Auth (runtime part; secrets too — this is an internal tool, DB is the boundary)
    "auth.oidc.enabled": ("false", "bool"),
    "auth.oidc.issuer": ("", "str"),
    "auth.oidc.client_id": ("", "str"),
    "auth.oidc.client_secret": ("", "str"),
    "auth.oidc.button_label": ("Sign in with SSO", "str"),
    "auth.oidc.group_role_map": ('{"itops-admins": "admin"}', "str"),  # JSON: {"group": "role"}
    "auth.oidc.default_role": ("", "str"),  # role when no group matches; empty = deny
    "auth.ldap.enabled": ("false", "bool"),
    "auth.ldap.url": ("", "str"),          # ldaps://host:636 or ldap://host:389
    "auth.ldap.bind_dn": ("", "str"),
    "auth.ldap.bind_password": ("", "str"),
    "auth.ldap.user_base": ("", "str"),
    "auth.ldap.user_filter": ("(uid={username})", "str"),
    "auth.ldap.group_role_map": ("", "str"),  # JSON: {"cn=it-admins,...": "admin"}
    # SMTP
    "smtp.enabled": ("false", "bool"),
    "smtp.host": ("", "str"),
    "smtp.port": ("25", "int"),
    # "none" (plaintext, e.g. an internal relay on 25), "starttls" (plaintext
    # connect then upgrade, e.g. port 587), "tls" (implicit TLS from the
    # start, e.g. port 465) -- a single use_tls bool couldn't tell "starttls"
    # and "tls" apart, which is what broke O365:587 (WRONG_VERSION_NUMBER:
    # we spoke plaintext SMTP at a socket O365 expected a TLS ClientHello
    # on). Migrated from the old smtp.use_tls bool in bootstrap.py.
    "smtp.security": ("none", "str"),
    "smtp.username": ("", "str"),        # empty = unauthenticated relay
    "smtp.password": ("", "str"),
    "smtp.from_address": ("", "str"),
    # Notifications: last date (ISO, YYYY-MM-DD) the daily scheduled-check
    # tick ran -- not a user-facing setting, just a persisted marker so the
    # in-app scheduler (app/main.py) is idempotent across restarts within
    # the same day. Empty string = never run.
    "notifications.last_daily_run": ("", "str"),
    # Depreciation / warranty policy
    "depreciation.default_months": ("36", "int"),
    "warranty.alert_days": ("30", "int"),
    # Contracts: separate key from warranty.alert_days (same pattern, own
    # value) -- a shared key would silently couple two unrelated concerns.
    "contracts.renewal_alert_days": ("30", "int"),
    # Phase 9: one-time v1 import wizard config. Kept in core_settings like
    # every other secret this app already stores in plaintext (smtp.password,
    # auth.oidc.client_secret) -- same "internal tool, DB is the boundary"
    # model, no new precedent.
    "import.v1_database_url": ("", "str"),  # postgresql://user:pass@host:port/db, read-only enforced at connect time
    # Symbol -> ISO code map, NOT hardcoded: "Rs" only means SCR for THIS
    # deployment. A client in another region edits this setting, not code.
    "import.currency_symbol_map": ('{"$": "USD", "£": "GBP", "€": "EUR", "Rs": "SCR"}', "str"),
    # Paths where v1's upload volumes are (temporarily, read-only) mounted
    # inside this container for the file-copy step -- see the setup guide's
    # import section for the docker-compose override procedure. Empty =
    # metadata-only import (attachment rows created, files not copied).
    "import.v1_asset_uploads_path": ("", "str"),
    "import.v1_printer_uploads_path": ("", "str"),
}


class SettingsStore:
    """Request-scoped helper; loads all settings once per request."""

    def __init__(self, values: dict[str, str]):
        self._values = values

    def get(self, key: str) -> str:
        if key not in DEFAULTS:
            raise KeyError(f"Unregistered setting: {key}")
        return self._values.get(key, DEFAULTS[key][0])

    def get_bool(self, key: str) -> bool:
        # v1 lesson: HTMX/forms send strings — compare explicitly.
        return self.get(key) == "true"

    def get_int(self, key: str) -> int:
        return int(self.get(key))


async def load_settings(db: AsyncSession) -> SettingsStore:
    rows = (await db.execute(select(AppSetting))).scalars()
    return SettingsStore({r.key: r.value or "" for r in rows})


async def save_setting(db: AsyncSession, key: str, value: str) -> None:
    if key not in DEFAULTS:
        raise KeyError(f"Unregistered setting: {key}")
    row = await db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=value))
    else:
        row.value = value
        row.updated_at = datetime.now(timezone.utc)
