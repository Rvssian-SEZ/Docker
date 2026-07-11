from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str

    # App
    SECRET_KEY: str
    APP_BASE_URL: str = "http://localhost:8000"

    # Authentik OIDC
    AUTHENTIK_BASE_URL: str
    AUTHENTIK_SLUG: str = "itops"
    AUTHENTIK_CLIENT_ID: str
    AUTHENTIK_CLIENT_SECRET: str

    # Authentik API (for user sync)
    # Create under Admin > Directory > Tokens & App passwords
    AUTHENTIK_API_TOKEN: str = ""

    @property
    def authentik_authorize_url(self) -> str:
        return f"{self.AUTHENTIK_BASE_URL}/application/o/authorize/"

    @property
    def authentik_token_url(self) -> str:
        return f"{self.AUTHENTIK_BASE_URL}/application/o/token/"

    @property
    def authentik_userinfo_url(self) -> str:
        return f"{self.AUTHENTIK_BASE_URL}/application/o/userinfo/"

    @property
    def authentik_logout_url(self) -> str:
        return f"{self.AUTHENTIK_BASE_URL}/application/o/{self.AUTHENTIK_SLUG}/end-session/"

    @property
    def oidc_redirect_uri(self) -> str:
        return f"{self.APP_BASE_URL}/auth/callback"

    class Config:
        env_file = ".env"


settings = Settings()
