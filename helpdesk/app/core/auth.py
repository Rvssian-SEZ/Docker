import secrets
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode
from typing import Optional

import httpx
from fastapi import Request, HTTPException
from sqlalchemy.orm import Session

from core.config import get_settings
from models.models import User

settings = get_settings()

SESSION_KEY = "hd_session"
STATE_KEY = "hd_oauth_state"


# ─── State signing (HMAC-SHA256) ─────────────────────────────────────────────

def _sign(value: str) -> str:
    mac = hmac.new(settings.secret_key.encode(), value.encode(), hashlib.sha256)
    return f"{value}.{mac.hexdigest()}"


def _unsign(signed: str) -> Optional[str]:
    if "." not in signed:
        return None
    value, sig = signed.rsplit(".", 1)
    expected = hmac.new(settings.secret_key.encode(), value.encode(), hashlib.sha256).hexdigest()
    if hmac.compare_digest(sig, expected):
        return value
    return None


# ─── Session helpers ──────────────────────────────────────────────────────────

def get_session_user(request: Request) -> Optional[dict]:
    raw = request.cookies.get(SESSION_KEY)
    if not raw:
        return None
    value = _unsign(raw)
    if not value:
        return None
    try:
        data = json.loads(value)
        if data.get("expires", 0) < time.time():
            return None
        return data
    except Exception:
        return None


def create_session_cookie(response, user_data: dict, max_age: int = 86400 * 7):
    payload = {**user_data, "expires": time.time() + max_age}
    signed = _sign(json.dumps(payload, separators=(",", ":")))
    response.set_cookie(
        SESSION_KEY,
        signed,
        max_age=max_age,
        httponly=True,
        samesite="lax",
    )


def clear_session_cookie(response):
    response.delete_cookie(SESSION_KEY)


# ─── OIDC flow ────────────────────────────────────────────────────────────────

def build_authorize_url(request: Request) -> tuple[str, str]:
    state = secrets.token_urlsafe(32)
    signed_state = _sign(state)
    params = {
        "client_id": settings.authentik_client_id,
        "response_type": "code",
        "redirect_uri": settings.redirect_uri,
        "scope": "openid profile email groups",
        "state": signed_state,
    }
    return f"{settings.authentik_authorize_url}?{urlencode(params)}", signed_state


async def exchange_code(code: str) -> dict:
    async with httpx.AsyncClient(verify="/app/root_ca.crt") as client:
        r = await client.post(
            settings.authentik_token_url,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.redirect_uri,
                "client_id": settings.authentik_client_id,
                "client_secret": settings.authentik_client_secret,
            },
        )
        r.raise_for_status()
        return r.json()


async def fetch_userinfo(access_token: str) -> dict:
    async with httpx.AsyncClient(verify="/app/root_ca.crt") as client:
        r = await client.get(
            settings.authentik_userinfo_url,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        r.raise_for_status()
        return r.json()


def get_user_role(groups: list[str]) -> str:
    """Derive role from Authentik groups. Returns 'admin', 'tech', or 'user'."""
    if settings.helpdesk_admin_group in groups:
        return "admin"
    if settings.helpdesk_tech_group in groups:
        return "tech"
    return "user"


def upsert_user(db: Session, userinfo: dict) -> User:
    """Create or update the local user record from Authentik userinfo."""
    email = userinfo.get("email", "").lower()
    username = userinfo.get("preferred_username", email.split("@")[0])
    groups = userinfo.get("groups", [])

    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(
            email=email,
            username=username,
            full_name=userinfo.get("name", username),
            is_active=True,
            groups=",".join(groups),
        )
        db.add(user)
    else:
        # Re-sync identity fields; preserve locally edited fields
        user.username = username
        user.full_name = userinfo.get("name", user.full_name)
        user.groups = ",".join(groups)
        user.is_active = True

    db.commit()
    db.refresh(user)
    return user
