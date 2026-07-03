from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_BASE_URL: str = "http://192.168.110.50:8003"
    SECRET_KEY: str

    # Authentik OIDC
    OIDC_CLIENT_ID: str
    OIDC_CLIENT_SECRET: str
    OIDC_DISCOVERY_URL: str

    # IMAP — Mail LXC
    IMAP_HOST: str = "192.168.110.35"
    IMAP_PORT: int = 993
    IMAP_MASTER_USER: str = "mailadmin"
    IMAP_MASTER_PASS: str = ""

    # Comma-separated list of mailbox users
    MAIL_USERS: str = "nutwatch,alex,admin"

    @property
    def mailbox_users(self) -> list[str]:
        return [u.strip() for u in self.MAIL_USERS.split(",") if u.strip()]

    model_config = {"env_file": ".env"}


settings = Settings()
