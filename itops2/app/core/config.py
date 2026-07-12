"""Application configuration via pydantic-settings.

NOTE (v1 lesson): never put inline comments on value lines in .env —
pydantic-settings will include them in the parsed value.

Env-var settings here are bootstrap-level only (DB, secret key, bind).
Runtime-tunable behaviour (SMTP, auth providers, currency, company mode,
notifications) lives in the core_settings DB table, editable in the
Settings UI — so client installs are configured in-app, not by editing
env files.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Core / bootstrap ---
    app_name: str = "ITOps v2"
    secret_key: str = "change-me"  # session signing (itsdangerous)
    debug: bool = False

    # --- Database ---
    database_url: str = "postgresql+asyncpg://itops2:itops2@db:5432/itops2"

    # --- Break-glass local admin (created/ensured at startup) ---
    # Always active regardless of OIDC/LDAP configuration.
    breakglass_username: str = "admin"
    breakglass_password: str = "change-me-now"

    # --- TLS trust (Step-CA root for httpx calls to Authentik etc.) ---
    ca_cert_path: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
