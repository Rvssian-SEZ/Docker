"""Login / logout routes: local auth + OIDC (Authentik). LDAP joins later."""

import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import oidc
from app.core.auth import authenticate_local
from app.core.db import get_db
from app.core.models import AuditLog
from app.core.settings_store import load_settings
from app.templating import templates

logger = logging.getLogger(__name__)
router = APIRouter()


def _redirect_uri(request: Request) -> str:
    # Correct scheme relies on uvicorn --proxy-headers behind the reverse proxy.
    return str(request.url_for("oidc_callback"))


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, db: AsyncSession = Depends(get_db)):
    if request.session.get("user_id"):
        return RedirectResponse("/", status_code=302)
    store = await load_settings(db)
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "error": request.session.pop("login_error", None),
            "oidc_enabled": store.get_bool("auth.oidc.enabled"),
            "oidc_label": store.get("auth.oidc.button_label"),
        },
    )


@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    user = await authenticate_local(db, username.strip(), password)
    if user is None:
        store = await load_settings(db)
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "error": "Invalid username or password.",
                "oidc_enabled": store.get_bool("auth.oidc.enabled"),
                "oidc_label": store.get("auth.oidc.button_label"),
            },
            status_code=401,
        )
    request.session["user_id"] = user.id
    db.add(AuditLog(user_id=user.id, action="login", entity_type="session"))
    await db.commit()
    return RedirectResponse("/", status_code=302)


@router.get("/auth/oidc/login")
async def oidc_login(request: Request, db: AsyncSession = Depends(get_db)):
    store = await load_settings(db)
    if not store.get_bool("auth.oidc.enabled"):
        return RedirectResponse("/login", status_code=302)
    state = oidc.new_state()
    request.session["oidc_state"] = state
    try:
        url = await oidc.build_authorize_url(store, _redirect_uri(request), state)
    except Exception:
        logger.exception("OIDC discovery failed")
        request.session["login_error"] = "SSO is unavailable (provider discovery failed)."
        return RedirectResponse("/login", status_code=302)
    return RedirectResponse(url, status_code=302)


@router.get("/auth/oidc/callback")
async def oidc_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    def fail(message: str) -> RedirectResponse:
        request.session["login_error"] = message
        return RedirectResponse("/login", status_code=302)

    expected_state = request.session.pop("oidc_state", None)
    if error:
        return fail(f"SSO error: {error}")
    if not code or not state or state != expected_state:
        return fail("SSO state mismatch. Please try again.")
    store = await load_settings(db)
    if not store.get_bool("auth.oidc.enabled"):
        return fail("SSO is disabled.")
    try:
        claims = await oidc.fetch_claims(store, code, _redirect_uri(request))
        role_name = oidc.resolve_role(store, claims.get("groups") or [])
        if role_name is None:
            return fail("Your account has no access to this application.")
        user = await oidc.provision_user(db, claims, role_name)
    except oidc.OIDCError as exc:
        await db.rollback()
        return fail(str(exc))
    except Exception:
        logger.exception("OIDC callback failed")
        await db.rollback()
        return fail("SSO sign-in failed. Contact an administrator.")
    request.session["user_id"] = user.id
    db.add(AuditLog(user_id=user.id, action="login", entity_type="session", detail="oidc"))
    await db.commit()
    return RedirectResponse("/", status_code=302)


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)
