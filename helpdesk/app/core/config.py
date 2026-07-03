from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # App
    app_name: str = "IT Helpdesk"
    secret_key: str
    app_base_url: str = "http://localhost:8001"
    debug: bool = False

    # Database
    database_url: str

    # Authentik OIDC
    authentik_base_url: str
    authentik_client_id: str
    authentik_client_secret: str

    # SMTP
    smtp_host: str
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "helpdesk@home.internal"
    smtp_tls: bool = True
    smtp_starttls: bool = True

    # Helpdesk
    helpdesk_admin_email: str = ""
    helpdesk_tech_group: str = "helpdesk-tech"
    helpdesk_admin_group: str = "helpdesk-admin"

    # SLA hours per priority
    sla_critical_hours: int = 4
    sla_high_hours: int = 8
    sla_medium_hours: int = 72
    sla_low_hours: int = 120

    @property
    def authentik_authorize_url(self) -> str:
        return f"{self.authentik_base_url}/application/o/authorize/"

    @property
    def authentik_token_url(self) -> str:
        return f"{self.authentik_base_url}/application/o/token/"

    @property
    def authentik_userinfo_url(self) -> str:
        return f"{self.authentik_base_url}/application/o/userinfo/"

    @property
    def authentik_end_session_url(self) -> str:
        return f"{self.authentik_base_url}/application/o/end-session/"

    @property
    def redirect_uri(self) -> str:
        return f"{self.app_base_url}/auth/callback"

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
