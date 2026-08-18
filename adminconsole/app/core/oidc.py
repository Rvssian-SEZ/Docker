"""OIDC (Authorization Code flow) against Authentik (auth.saa.sc).

Config comes from app_settings (Settings -> Authentication):
- auth.oidc.enabled / issuer / client_id / client_secret
- auth.oidc.group_role_map: JSON {"authentik-group": "role_name", ...}
- auth.oidc.default_role: role for users with no mapped group ("" = deny)

Flow: /auth/oidc/login builds the authorize URL (state in session) ->
Authentik redirects to /auth/oidc/callback -> token exchange -> userinfo ->
provision/update local user row (auth_source=oidc) -> normal session cookie.

Discovery is fetched per login (no caching) so an issuer change in Settings
takes effect immediately — logins are rare enough that this cost is fine.
"""

import json
import logging
import secrets
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.models import AuthSource, Role, RoleName, User
from app.core.settings_store import SettingsStore

logger = logging.getLogger(__name__)

# Highest-privilege mapped group wins if a user belongs to several.
_ROLE_PRIORITY = ["admin", "helpdesk_l2", "helpdesk_l1"]


class OIDCError(Exception):
    """User-presentable OIDC failure."""


def _client() -> httpx.AsyncClient:
    verify = get_settings().ca_cert_path or True
    return httpx.AsyncClient(verify=verify, timeout=10)


async def discover(issuer: str) -> dict:
    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    async with _client() as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


async def build_authorize_url(store: SettingsStore, redirect_uri: str, state: str) -> str:
    conf = await discover(store.get("auth.oidc.issuer"))
    params = httpx.QueryParams(
        response_type="code",
        client_id=store.get("auth.oidc.client_id"),
        redirect_uri=redirect_uri,
        scope="openid profile email",
        state=state,
    )
    return f"{conf['authorization_endpoint']}?{params}"


def new_state() -> str:
    return secrets.token_urlsafe(32)


async def fetch_claims(store: SettingsStore, code: str, redirect_uri: str) -> dict:
    conf = await discover(store.get("auth.oidc.issuer"))
    client_secret = store.get_secret("auth.oidc.client_secret")
    if client_secret is None:
        raise OIDCError("SSO client secret is not configured or could not be decrypted.")
    async with _client() as client:
        token_resp = await client.post(
            conf["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": store.get("auth.oidc.client_id"),
                "client_secret": client_secret,
            },
        )
        if token_resp.status_code != 200:
            logger.warning("OIDC token exchange failed: %s %s", token_resp.status_code, token_resp.text[:500])
            raise OIDCError("SSO token exchange failed.")
        access_token = token_resp.json().get("access_token")
        if not access_token:
            raise OIDCError("SSO provider returned no access token.")
        ui_resp = await client.get(conf["userinfo_endpoint"], headers={"Authorization": f"Bearer {access_token}"})
        if ui_resp.status_code != 200:
            raise OIDCError("SSO userinfo request failed.")
        return ui_resp.json()


def resolve_role(store: SettingsStore, groups: list[str]) -> str | None:
    """Map Authentik groups to a role name; None means access denied."""
    raw = store.get("auth.oidc.group_role_map").strip()
    mapping: dict[str, str] = {}
    if raw:
        try:
            mapping = json.loads(raw)
        except json.JSONDecodeError:
            logger.error("auth.oidc.group_role_map is not valid JSON; ignoring")
    valid = {r.value for r in RoleName}
    matched = [mapping[g] for g in groups if mapping.get(g) in valid]
    if matched:
        return sorted(matched, key=_ROLE_PRIORITY.index)[0]
    default = store.get("auth.oidc.default_role").strip()
    return default if default in valid else None


async def provision_user(db: AsyncSession, claims: dict, role_name: str) -> User:
    """Create or update the local row for an OIDC identity. Never touches
    a local (username-colliding) account — mirrors itops2's own guard."""
    username = (claims.get("preferred_username") or claims.get("email") or "").strip()
    if not username:
        raise OIDCError("SSO provider returned no username.")
    role = (await db.execute(select(Role).where(Role.name == RoleName(role_name)))).scalar_one()
    user = (
        await db.execute(select(User).options(selectinload(User.role)).where(User.username == username))
    ).scalar_one_or_none()
    if user is not None and user.auth_source == AuthSource.local:
        raise OIDCError("This username belongs to a local account. Sign in with a password.")
    if user is None:
        user = User(username=username, auth_source=AuthSource.oidc, role_id=role.id, is_active=True)
        db.add(user)
    user.email = claims.get("email")
    user.display_name = claims.get("name") or username
    user.role_id = role.id
    if not user.is_active:
        raise OIDCError("Your account is disabled. Contact an administrator.")
    user.last_login_at = datetime.now(timezone.utc)
    await db.flush()
    user = (
        await db.execute(select(User).options(selectinload(User.role)).where(User.username == username))
    ).scalar_one()
    return user
