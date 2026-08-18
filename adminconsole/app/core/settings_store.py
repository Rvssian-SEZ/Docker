"""Typed access to app_settings (runtime-tunable configuration).

Every key must be registered in DEFAULTS — unknown keys are rejected so
typos don't silently create dead settings (same discipline as itops2).

Keys in ENCRYPTED_KEYS are Fernet-encrypted before being written to the DB
(app/core/crypto.py) and are write-only from the UI's perspective: a GET
never returns the decrypted value, only SettingsStore.is_set() (whether a
value currently exists) — same principle as the LAPS reveal-and-hide
pattern, applied to credentials instead of passwords. A field is replaced
by submitting a new value; leaving it blank on save means "keep the
existing value", never "clear it" (see save_setting's blank-means-keep
handling in the settings router).
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt, encrypt
from app.core.models import AppSetting

# key -> (default, type)  — type in {"str", "bool", "int"}
DEFAULTS: dict[str, tuple[str, str]] = {
    "general.site_name": ("SAA Admin Console", "str"),

    # --- Graph app registration (Reporting) ---
    "graph.tenant_id": ("", "str"),
    "graph.client_id": ("", "str"),
    "graph.client_secret": ("", "str"),  # encrypted

    # --- Authentik SSO (auth.saa.sc) ---
    "auth.oidc.enabled": ("false", "bool"),
    "auth.oidc.issuer": ("", "str"),
    "auth.oidc.client_id": ("", "str"),
    "auth.oidc.client_secret": ("", "str"),  # encrypted
    "auth.oidc.button_label": ("Sign in with SSO", "str"),
    # JSON: {"authentik-group": "role_name"}. Highest-privilege mapped
    # group wins (admin > helpdesk_l2 > helpdesk_l1), same resolution order
    # as itops2's oidc.py.
    "auth.oidc.group_role_map": ('{"adminconsole-admins": "admin"}', "str"),
    "auth.oidc.default_role": ("", "str"),  # role when no group matches; empty = deny

    # --- AD service account (LDAPS) ---
    "ad.ldaps_url": ("", "str"),  # ldaps://dc.saa.sc:636
    "ad.bind_dn": ("", "str"),
    "ad.bind_password": ("", "str"),  # encrypted
    "ad.base_dn": ("", "str"),  # search base, e.g. DC=saa,DC=sc
    # Comma-separated OU DNs a Helpdesk L1/L2 role may act against; empty =
    # no restriction beyond the permission matrix itself. Admin/break-glass
    # are never scoped by this.
    "ad.scoped_ous": ("", "str"),
    # OUs/attributes this app must never touch even if asked — checked
    # before ad.scoped_ous, not instead of it (privileged accounts stay a
    # manual/ticketed process regardless of scoping).
    "ad.excluded_ous": ("", "str"),

    # --- Break-glass alerting (out-of-band, every login + every action) ---
    "breakglass.alert_email": ("", "str"),
    "breakglass.alert_webhook_url": ("", "str"),
    "breakglass.ip_allowlist": ("", "str"),  # comma-separated CIDRs; empty = no restriction

    # --- SMTP (Postfix relay, for break-glass/LAPS/audit alerting) ---
    "smtp.host": ("", "str"),
    "smtp.port": ("25", "int"),
    "smtp.from_address": ("", "str"),

    # --- Reporting sync ---
    "sync.frequency_minutes": ("60", "int"),
    "sync.last_run_at": ("", "str"),  # ISO timestamp marker, not user-facing
}

# Settings never returned in plaintext to a template/response.
ENCRYPTED_KEYS: set[str] = {
    "graph.client_secret",
    "auth.oidc.client_secret",
    "ad.bind_password",
}


class SettingsStore:
    """Request-scoped helper; loads all settings once per request."""

    def __init__(self, rows: dict[str, str]):
        self._raw = rows

    def get(self, key: str) -> str:
        if key not in DEFAULTS:
            raise KeyError(f"Unregistered setting: {key}")
        if key in ENCRYPTED_KEYS:
            raise KeyError(f"{key} is encrypted — use is_set(), never get(), for a secret key.")
        return self._raw.get(key, DEFAULTS[key][0])

    def get_secret(self, key: str) -> str | None:
        """Decrypted value for internal use only (e.g. building an LDAPS
        bind or a Graph token request) — never pass this to a template."""
        if key not in ENCRYPTED_KEYS:
            raise KeyError(f"{key} is not an encrypted setting.")
        raw = self._raw.get(key, "")
        if not raw:
            return None
        return decrypt(raw)

    def is_set(self, key: str) -> bool:
        if key not in ENCRYPTED_KEYS:
            raise KeyError(f"{key} is not an encrypted setting.")
        return bool(self._raw.get(key))

    def get_bool(self, key: str) -> bool:
        return self.get(key) == "true"

    def get_int(self, key: str) -> int:
        return int(self.get(key))


async def load_settings(db: AsyncSession) -> SettingsStore:
    rows = (await db.execute(select(AppSetting))).scalars()
    return SettingsStore({r.key: r.value or "" for r in rows})


async def save_setting(db: AsyncSession, key: str, value: str, *, updated_by: str) -> None:
    if key not in DEFAULTS:
        raise KeyError(f"Unregistered setting: {key}")
    stored_value = encrypt(value) if key in ENCRYPTED_KEYS else value
    row = await db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=stored_value, updated_by=updated_by))
    else:
        row.value = stored_value
        row.updated_at = datetime.now(timezone.utc)
        row.updated_by = updated_by
