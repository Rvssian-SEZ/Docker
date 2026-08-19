"""Runtime-configurable Settings UI (Admin-tier only): Graph app
registration, Authentik SSO, AD service account, break-glass alerting, SMTP.

Gated by BOTH settings.manage (role permission) AND a fresh re-auth
(require_reauth — spec: "Settings page requires re-authentication to
view/edit, not just role-gated, since a stolen session shouldn't be enough
to pull these"). Secret fields are write-only: a GET never returns the
decrypted value, only whether one is currently set; a blank field on save
means "keep the existing value", never "clear it" — clearing a secret is a
separate explicit action per field.
"""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import breakglass
from app.core.audit import write_audit
from app.core.auth import CurrentUser, authenticate_local, require, require_reauth, touch_reauth
from app.core.db import get_db
from app.core.models import AuthSource, User
from app.core.settings_store import DEFAULTS, ENCRYPTED_KEYS, load_settings, save_setting
from app.templating import templates

router = APIRouter()


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("/settings/reauth", response_class=HTMLResponse)
async def reauth_page(
    request: Request,
    next: str = "/settings",
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require("settings.manage")),
):
    is_oidc = False
    if not user.is_breakglass:
        row = await db.get(User, user.id)
        is_oidc = row is not None and row.auth_source == AuthSource.oidc
    return templates.TemplateResponse(
        request,
        "settings/reauth.html",
        {
            "user": user,
            "next": next,
            "error": request.session.pop("reauth_error", None),
            "is_breakglass": user.is_breakglass,
            "is_oidc": is_oidc,
        },
    )


@router.post("/settings/reauth")
async def reauth_submit(
    request: Request,
    next: str = Form("/settings"),
    password: str = Form(""),
    totp_code: str = Form(""),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require("settings.manage")),
):
    ok = False
    if user.is_breakglass:
        ok = await breakglass.authenticate(db, user.username, password, totp_code.strip())
    else:
        ok = (await authenticate_local(db, user.username, password)) is not None
    if not ok:
        request.session["reauth_error"] = "Incorrect password or code."
        return RedirectResponse(f"/settings/reauth?next={next}", status_code=302)
    touch_reauth(request)
    return RedirectResponse(next, status_code=302)


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require("settings.manage")),
    _reauth: CurrentUser = Depends(require_reauth),
):
    store = await load_settings(db)
    return templates.TemplateResponse(
        request,
        "settings/index.html",
        {"user": user, "store": store, "encrypted_keys": ENCRYPTED_KEYS},
    )


@router.post("/settings/{section}")
async def settings_save(
    request: Request,
    section: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require("settings.manage")),
    _reauth: CurrentUser = Depends(require_reauth),
):
    form = await request.form()
    keys = _SECTION_KEYS.get(section)
    if keys is None:
        return RedirectResponse("/settings", status_code=302)
    for key in keys:
        is_bool = DEFAULTS[key][1] == "bool"
        if key not in form:
            if is_bool:
                # HTML checkboxes are absent from form data when unchecked —
                # absence for a bool key means "false", not "leave alone".
                await save_setting(db, key, "false", updated_by=user.username)
            continue
        value = "true" if is_bool else str(form[key]).strip()
        if key in ENCRYPTED_KEYS and not value:
            continue  # blank = keep existing secret, never clear implicitly
        await save_setting(db, key, value, updated_by=user.username)
    await db.commit()
    await write_audit(
        actor_username=user.username,
        actor_role=user.role,
        actor_source="breakglass" if user.is_breakglass else "local",
        action="settings_change",
        target_type="setting",
        target_id=section,
        source_ip=_client_ip(request),
    )
    return RedirectResponse("/settings", status_code=302)


_SECTION_KEYS = {
    "graph": ["graph.tenant_id", "graph.client_id", "graph.client_secret"],
    "authentik": [
        "auth.oidc.enabled",
        "auth.oidc.issuer",
        "auth.oidc.client_id",
        "auth.oidc.client_secret",
        "auth.oidc.button_label",
        "auth.oidc.group_role_map",
        "auth.oidc.default_role",
    ],
    "ad": [
        "ad.ldaps_url",
        "ad.bind_dn",
        "ad.bind_password",
        "ad.base_dn",
        "ad.scoped_ous",
        "ad.excluded_ous",
    ],
    "breakglass": ["breakglass.alert_email", "breakglass.alert_webhook_url", "breakglass.ip_allowlist"],
    "automation": ["semaphore.url", "semaphore.username", "semaphore.password", "semaphore.project_id", "semaphore.laps_template_id", "semaphore.unlock_template_id"],
    "smtp": ["smtp.host", "smtp.port", "smtp.from_address"],
    "sync": ["sync.frequency_minutes"],
}
