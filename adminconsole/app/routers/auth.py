"""Login / logout: local auth, break-glass (local + TOTP, separate path),
and OIDC (Authentik). Every successful login writes an audit row; a
break-glass login additionally fires an out-of-band alert (spec: "Every
login and every action taken while authenticated as break-glass triggers
an immediate out-of-band alert").
"""

import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import breakglass, oidc
from app.core.alerting import alert
from app.core.audit import write_audit
from app.core.auth import authenticate_local, touch_reauth
from app.core.crypto import is_configured as fernet_configured
from app.core.db import get_db
from app.core.settings_store import load_settings
from app.templating import templates

logger = logging.getLogger(__name__)
router = APIRouter()


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, db: AsyncSession = Depends(get_db)):
    if request.session.get("user_id") or request.session.get("breakglass"):
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
    await write_audit(
        actor_username=user.username,
        actor_role=user.role.name.value,
        actor_source="local",
        action="login",
        target_type="session",
        source_ip=_client_ip(request),
    )
    return RedirectResponse("/", status_code=302)


@router.get("/login/breakglass", response_class=HTMLResponse)
async def breakglass_login_page(request: Request):
    return templates.TemplateResponse(
        request, "login_breakglass.html", {"error": request.session.pop("login_error", None)}
    )


@router.post("/login/breakglass", response_class=HTMLResponse)
async def breakglass_login_submit(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    totp_code: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    client_ip = _client_ip(request)
    if not fernet_configured():
        return templates.TemplateResponse(
            request,
            "login_breakglass.html",
            {"error": "Break-glass is not configured on this deployment (FERNET_KEY unset)."},
            status_code=503,
        )
    if not await breakglass.ip_allowed(db, client_ip):
        logger.warning("Break-glass login blocked by IP allowlist from %s", client_ip)
        return templates.TemplateResponse(
            request, "login_breakglass.html", {"error": "Access denied from this network."}, status_code=403
        )
    ok = await breakglass.authenticate(db, username.strip(), password, totp_code.strip())
    if not ok:
        await write_audit(
            actor_username=username.strip() or "(unknown)",
            actor_role="breakglass",
            actor_source="breakglass",
            action="login_failed",
            target_type="session",
            source_ip=client_ip,
        )
        return templates.TemplateResponse(
            request, "login_breakglass.html", {"error": "Invalid credentials or TOTP code."}, status_code=401
        )
    request.session["breakglass"] = True
    request.session["breakglass_username"] = username.strip()
    await write_audit(
        actor_username=username.strip(),
        actor_role="breakglass",
        actor_source="breakglass",
        action="login",
        target_type="session",
        source_ip=client_ip,
    )
    await alert(
        db,
        subject="SAA Admin Console: break-glass login",
        body=f"Break-glass login for '{username.strip()}' from {client_ip or 'unknown IP'} at request time.",
    )
    return RedirectResponse("/", status_code=302)


@router.get("/auth/oidc/login")
async def oidc_login(request: Request, reauth_next: str | None = None, db: AsyncSession = Depends(get_db)):
    store = await load_settings(db)
    if not store.get_bool("auth.oidc.enabled"):
        return RedirectResponse("/login", status_code=302)
    state = oidc.new_state()
    request.session["oidc_state"] = state
    if reauth_next:
        request.session["reauth_next"] = reauth_next
    try:
        url = await oidc.build_authorize_url(store, str(request.url_for("oidc_callback")), state)
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
        claims = await oidc.fetch_claims(store, code, str(request.url_for("oidc_callback")))
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
    await db.commit()
    await write_audit(
        actor_username=user.username,
        actor_role=role_name,
        actor_source="oidc",
        action="login",
        target_type="session",
        source_ip=_client_ip(request),
    )
    # If this OIDC round-trip was triggered as a Settings re-auth (see
    # require_reauth/touch_reauth), mark it fresh and return to the page
    # that requested it instead of the normal post-login redirect to "/".
    reauth_next = request.session.pop("reauth_next", None)
    if reauth_next:
        touch_reauth(request)
        return RedirectResponse(reauth_next, status_code=302)
    return RedirectResponse("/", status_code=302)


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)
