"""Application configuration via pydantic-settings.

NOTE (carried over from itops2): never put inline comments on value lines
in .env — pydantic-settings will include them in the parsed value.

Env-var settings here are bootstrap-level only (DB paths, secret key,
break-glass initial credential, the Fernet key). Runtime-tunable behaviour
that gets created/rotated independently of code deploys — the Graph app
registration, Authentik SSO, and AD service account — lives in the
app_settings DB table, editable in the Settings UI (encrypted at rest via
FERNET_KEY, see app/core/crypto.py).
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Core / bootstrap ---
    app_name: str = "SAA Admin Console"
    secret_key: str = "change-me"  # session signing (itsdangerous)
    debug: bool = False

    # --- Databases: app state and the append-only audit trail are
    # deliberately separate SQLite files (see app/core/audit_db.py) so a
    # bug in the app-state ORM session can never touch audit rows. ---
    database_url: str = "sqlite+aiosqlite:////data/app.db"
    audit_database_url: str = "sqlite+aiosqlite:////data/audit.db"

    # --- Settings-at-rest encryption (Graph/Authentik/AD secrets in the
    # Settings UI). This is the one secret allowed to live in the
    # environment; the values it protects never do. ---
    fernet_key: str = ""

    # --- Break-glass local admin (ensured at startup; separate from the
    # normal Users/Roles table entirely — see app/core/breakglass.py). ---
    breakglass_username: str = "breakglass"
    breakglass_password: str = "change-me-now"

    # --- TLS trust (Step-CA root for httpx -> Authentik / Graph, ldap3 -> DC) ---
    ca_cert_path: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
