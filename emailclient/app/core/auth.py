import secrets
import httpx
from core.config import settings

CA_CERT = "/app/root_ca.crt"


async def get_oidc_config() -> dict:
    async with httpx.AsyncClient(verify=CA_CERT) as client:
        r = await client.get(
            settings.OIDC_DISCOVERY_URL.rstrip("/") + "/.well-known/openid-configuration"
        )
        r.raise_for_status()
        return r.json()


def make_state() -> str:
    return secrets.token_urlsafe(24)


def build_auth_url(auth_endpoint: str, state: str) -> str:
    redirect_uri = settings.APP_BASE_URL.rstrip("/") + "/auth/callback"
    params = {
        "response_type": "code",
        "client_id":     settings.OIDC_CLIENT_ID,
        "redirect_uri":  redirect_uri,
        "scope":         "openid profile email",
        "state":         state,
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{auth_endpoint}?{query}"


async def exchange_code(token_endpoint: str, code: str) -> dict:
    redirect_uri = settings.APP_BASE_URL.rstrip("/") + "/auth/callback"
    async with httpx.AsyncClient(verify=CA_CERT) as client:
        r = await client.post(
            token_endpoint,
            data={
                "grant_type":    "authorization_code",
                "code":          code,
                "redirect_uri":  redirect_uri,
                "client_id":     settings.OIDC_CLIENT_ID,
                "client_secret": settings.OIDC_CLIENT_SECRET,
            },
        )
        r.raise_for_status()
        return r.json()


async def fetch_userinfo(userinfo_endpoint: str, access_token: str) -> dict:
    async with httpx.AsyncClient(verify=CA_CERT) as client:
        r = await client.get(
            userinfo_endpoint,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        r.raise_for_status()
        return r.json()
