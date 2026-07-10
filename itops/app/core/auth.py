import os
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import Request
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from sqlalchemy.orm import Session

from core.config import settings
from models.user import User


_signer = URLSafeTimedSerializer(settings.SECRET_KEY, salt="oidc-state")

# Use internal CA cert if provided
_CA_CERT = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE") or True


def make_state(next_url: str = "/") -> str:
    return _signer.dumps({"next": next_url, "nonce": secrets.token_hex(8)})


def verify_state(token: str, max_age: int = 600) -> dict:
    return _signer.loads(token, max_age=max_age)


def get_authorization_url(state: str) -> str:
    params = {
        "client_id": settings.AUTHENTIK_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": settings.oidc_redirect_uri,
        "scope": "openid profile email",
        "state": state,
    }
    return f"{settings.authentik_authorize_url}?{urlencode(params)}"


async def exchange_code_for_tokens(code: str) -> dict:
    async with httpx.AsyncClient(timeout=15, verify=_CA_CERT) as client:
        response = await client.post(
            settings.authentik_token_url,
            data={
                "client_id": settings.AUTHENTIK_CLIENT_ID,
                "client_secret": settings.AUTHENTIK_CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.oidc_redirect_uri,
            },
        )
        response.raise_for_status()
        return response.json()


async def get_userinfo(access_token: str) -> dict:
    async with httpx.AsyncClient(timeout=15, verify=_CA_CERT) as client:
        response = await client.get(
            settings.authentik_userinfo_url,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response.raise_for_status()
        return response.json()


def upsert_user(db: Session, userinfo: dict) -> User:
    sub = userinfo["sub"]
    user = db.query(User).filter(User.sub == sub).first()

    if user is None:
        user = User(sub=sub)
        db.add(user)

    user.username = userinfo.get("preferred_username", sub)
    user.email = userinfo.get("email", "")
    user.full_name = userinfo.get("name", "")
    groups = userinfo.get("groups", [])
    user.groups = ",".join(groups) if groups else ""

    db.commit()
    db.refresh(user)
    return user


def set_session_user(request: Request, user: User) -> None:
    request.session["user"] = {
        "id": user.id,
        "sub": user.sub,
        "username": user.username,
        "email": user.email,
        "full_name": user.full_name,
        "groups": user.groups,
    }


def get_session_user(request: Request) -> dict | None:
    return request.session.get("user")


def clear_session(request: Request) -> None:
    request.session.clear()
