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
    "smtp.use_tls": ("false", "bool"),
    "smtp.username": ("", "str"),        # empty = unauthenticated relay
    "smtp.password": ("", "str"),
    "smtp.from_address": ("", "str"),
    # Depreciation / warranty policy
    "depreciation.default_months": ("36", "int"),
    "warranty.alert_days": ("30", "int"),
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
