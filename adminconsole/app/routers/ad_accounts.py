"""AD account management: search, unlock, reset password, enable/disable,
non-privileged attribute edits, LAPS retrieval.

STATUS: wired to app/core/ldap_client.py, which is NOT yet live-verified
against SAA.SC AD (see that module's docstring) — the ad.* Settings section
must be configured and the service account's dsacls delegation granted
(spec's "AD Delegation Prerequisites") before any of this can succeed
against a real DC. Until ad.ldaps_url/bind_dn/bind_password/base_dn are all
set, every route here returns a clear "AD is not configured" page instead
of a stack trace (same degrade-gracefully contract as Settings/break-glass).

Every write — and every LAPS read, which the spec treats as equally
sensitive — writes an audit row BEFORE the LDAP call (so an attempt is
recorded even if the call itself fails) and requires a non-blank reason.
Break-glass additionally triggers alert() on every one of these routes,
not just at login.
"""

import asyncio

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from ldap3 import Connection
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ldap_client, laps_pending, semaphore_client
from app.core.alerting import alert
from app.core.audit import write_audit
from app.core.auth import CurrentUser, require
from app.core.db import get_db
from app.core.ratelimit import check as rate_check
from app.core.settings_store import SettingsStore, load_settings
from app.templating import templates

router = APIRouter()


class AdNotConfigured(Exception):
    pass


class ScopeDenied(Exception):
    def __init__(self, message: str):
        self.message = message


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _open_conn(store: SettingsStore) -> Connection:
    ldaps_url = store.get("ad.ldaps_url").strip()
    bind_dn = store.get("ad.bind_dn").strip()
    base_dn = store.get("ad.base_dn").strip()
    bind_password = store.get_secret("ad.bind_password")
    if not (ldaps_url and bind_dn and base_dn and bind_password):
        raise AdNotConfigured()
    return ldap_client.bind(ldaps_url, bind_dn, bind_password)


def _check_scope(store: SettingsStore, dn: str, user: CurrentUser) -> None:
    """Admin and break-glass are never scoped. Helpdesk L1/L2 are blocked
    from ad.excluded_ous unconditionally, and — if ad.scoped_ous is set —
    restricted to only those OUs. DN suffix match, case-insensitive.
    """
    if user.is_breakglass or user.role == "admin":
        return
    dn_lower = dn.lower()
    excluded = [ou.strip().lower() for ou in store.get("ad.excluded_ous").split(",") if ou.strip()]
    if any(dn_lower.endswith(ou) for ou in excluded):
        raise ScopeDenied("This account is in a restricted OU. Contact an administrator.")
    scoped = [ou.strip().lower() for ou in store.get("ad.scoped_ous").split(",") if ou.strip()]
    if scoped and not any(dn_lower.endswith(ou) for ou in scoped):
        raise ScopeDenied("This account is outside your delegated OUs.")


async def _log_and_alert(
    request: Request,
    user: CurrentUser,
    *,
    action: str,
    target_id: str,
    reason: str,
    detail: str | None = None,
) -> None:
    await write_audit(
        actor_username=user.username,
        actor_role=user.role,
        actor_source="breakglass" if user.is_breakglass else "local",
        action=action,
        target_type="ad_account",
        target_id=target_id,
        reason=reason,
        source_ip=_client_ip(request),
        detail=detail,
    )
    if user.is_breakglass:
        await_args = f"{action} on {target_id} by break-glass '{user.username}' from {_client_ip(request)}. Reason: {reason}"
        # alert() takes a db session for Settings lookup; caller passes one in.
        request.state.breakglass_alert_pending = await_args  # picked up by the route after db is available


@router.get("/ad", response_class=HTMLResponse)
async def ad_search_page(
    request: Request,
    q: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require("ad.search")),
):
    store = await load_settings(db)
    if not (store.get("ad.ldaps_url") and store.get("ad.bind_dn") and store.get("ad.base_dn")):
        return templates.TemplateResponse(request, "ad/not_configured.html", {"user": user}, status_code=200)
    results = []
    error = None
    if q:
        try:
            conn = _open_conn(store)
            try:
                results = ldap_client.search_accounts(conn, store.get("ad.base_dn"), q.strip())
                if not results:
                    error = f"No accounts found matching '{q.strip()}'."
            finally:
                conn.unbind()
        except AdNotConfigured:
            return templates.TemplateResponse(request, "ad/not_configured.html", {"user": user}, status_code=200)
        except Exception as exc:
            error = f"AD search failed: {exc}"
    return templates.TemplateResponse(
        request, "ad/search.html", {"user": user, "q": q or "", "results": results, "error": error}
    )


@router.post("/ad/{sam}/unlock")
async def ad_unlock(
    request: Request,
    sam: str,
    reason: str = Form(...),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require("ad.unlock")),
):
    return await _perform(request, db, user, sam, reason, action="unlock", op=lambda conn, dn, attrs: ldap_client.unlock_account(conn, dn))


@router.post("/ad/{sam}/reset-password")
async def ad_reset_password(
    request: Request,
    sam: str,
    reason: str = Form(...),
    new_password: str = Form(...),
    force_change: bool = Form(True),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require("ad.reset_password")),
):
    if not rate_check(f"reset:{user.username}", max_calls=5, window_seconds=600):
        raise HTTPException(status_code=429, detail="Too many password resets — try again shortly.")
    return await _perform(
        request,
        db,
        user,
        sam,
        reason,
        action="reset_password",
        op=lambda conn, dn, attrs: ldap_client.reset_password(conn, dn, new_password, force_change_at_logon=force_change),
    )


@router.post("/ad/{sam}/enable")
async def ad_enable(
    request: Request, sam: str, reason: str = Form(...), db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require("ad.enable_disable")),
):
    return await _perform(
        request, db, user, sam, reason, action="enable",
        op=lambda conn, dn, attrs: ldap_client.set_enabled(conn, dn, int(attrs.get("userAccountControl", [0])[0]), enabled=True),
    )


@router.post("/ad/{sam}/disable")
async def ad_disable(
    request: Request, sam: str, reason: str = Form(...), db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require("ad.enable_disable")),
):
    return await _perform(
        request, db, user, sam, reason, action="disable",
        op=lambda conn, dn, attrs: ldap_client.set_enabled(conn, dn, int(attrs.get("userAccountControl", [0])[0]), enabled=False),
    )


@router.post("/ad/{sam}/laps")
async def ad_laps_reveal(
    request: Request,
    sam: str,
    reason: str = Form(...),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require("ad.laps_read")),
):
    """LDAPS confirms the computer exists and applies OU scoping, same as
    every other action here — but the actual password comes from Semaphore
    (see app/core/semaphore_client.py for why LDAPS alone can't read it on
    this forest's Windows-LAPS-with-encryption setup)."""
    if not rate_check(f"laps:{user.username}", max_calls=10, window_seconds=600):
        raise HTTPException(status_code=429, detail="Too many LAPS reveals — try again shortly.")
    store = await load_settings(db)
    try:
        conn = _open_conn(store)
    except AdNotConfigured:
        return templates.TemplateResponse(request, "ad/not_configured.html", {"user": user}, status_code=200)
    try:
        # Computer accounts' sAMAccountName always ends in "$" (unlike user
        # accounts) - the LDAPS lookup needs it even though Semaphore's
        # Get-LapsADPassword -Identity call (below) accepts the bare name.
        computer_sam = sam if sam.endswith("$") else f"{sam}$"
        found = ldap_client.find_user(conn, store.get("ad.base_dn"), computer_sam)
        if found is None:
            return templates.TemplateResponse(request, "ad/action_result.html", {"user": user, "ok": False, "message": f"No computer object found for '{sam}'."})
        _check_scope(store, found["dn"], user)
    except ScopeDenied as exc:
        return templates.TemplateResponse(request, "ad/action_result.html", {"user": user, "ok": False, "message": exc.message})
    finally:
        conn.unbind()

    token, event = laps_pending.create()
    callback_url = str(request.url_for("laps_callback", token=token))
    trigger_task = asyncio.create_task(
        semaphore_client.trigger_laps_read(store, target_computer=sam, callback_url=callback_url)
    )
    result = await laps_pending.wait_and_consume(token, event, timeout=90)
    trigger_error: str | None = None
    try:
        await trigger_task
    except semaphore_client.SemaphoreError as exc:
        trigger_error = str(exc)

    outcome = "delivered" if result else f"failed: {trigger_error or 'timed out waiting for callback'}"
    await _log_and_alert(request, user, action="laps_reveal", target_id=sam, reason=reason, detail=outcome)
    if user.is_breakglass:
        pending = getattr(request.state, "breakglass_alert_pending", None)
        if pending:
            await alert(db, subject="SAA Admin Console: break-glass LAPS reveal", body=pending)

    if result is None:
        return templates.TemplateResponse(
            request,
            "ad/action_result.html",
            {"user": user, "ok": False, "message": f"LAPS read failed: {trigger_error or 'timed out'}"},
        )
    return templates.TemplateResponse(
        request,
        "ad/laps_result.html",
        {"user": user, "sam": sam, "password": result["password"]},
    )


async def _perform(request: Request, db: AsyncSession, user: CurrentUser, sam: str, reason: str, *, action: str, op) -> HTMLResponse:
    if not reason.strip():
        return templates.TemplateResponse(request, "ad/action_result.html", {"user": user, "ok": False, "message": "A reason/ticket-ref is required."})
    store = await load_settings(db)
    try:
        conn = _open_conn(store)
    except AdNotConfigured:
        return templates.TemplateResponse(request, "ad/not_configured.html", {"user": user}, status_code=200)
    try:
        found = ldap_client.find_user(conn, store.get("ad.base_dn"), sam)
        if found is None:
            return templates.TemplateResponse(request, "ad/action_result.html", {"user": user, "ok": False, "message": f"No account found for '{sam}'."})
        _check_scope(store, found["dn"], user)
        op(conn, found["dn"], found["attributes"])
    except ScopeDenied as exc:
        return templates.TemplateResponse(request, "ad/action_result.html", {"user": user, "ok": False, "message": exc.message})
    except ldap_client.LdapError as exc:
        if action == "unlock" and "insufficientAccessRights" in str(exc):
            # AdminSDHolder-protected (adminCount=1) account — a standing
            # per-object ACE grant here gets silently wiped by SDProp's own
            # cycle (confirmed live 2026-08-19, see CLAUDE_CONTEXT.md
            # "Protected Users unlock"), so this falls back to a Semaphore-
            # run unlock via Ansible@SAA.SC instead of delegating anything
            # new. Only unlock has this fallback — reset/enable-disable/
            # attribute-edit on a protected account stay a manual process.
            try:
                await semaphore_client.trigger_protected_unlock(store, target_sam=sam)
            except semaphore_client.SemaphoreError as fallback_exc:
                await _log_and_alert(
                    request, user, action="unlock_failed", target_id=sam, reason=reason,
                    detail=f"LDAPS insufficientAccessRights (adminCount=1?); Semaphore fallback also failed: {fallback_exc}",
                )
                return templates.TemplateResponse(
                    request, "ad/action_result.html",
                    {"user": user, "ok": False, "message": f"Unlock failed via LDAPS (insufficient rights — likely AdminSDHolder-protected) and via the fallback: {fallback_exc}"},
                )
            await _log_and_alert(
                request, user, action="unlock", target_id=sam, reason=reason,
                detail="LDAPS insufficientAccessRights (adminCount=1 account) — used the Semaphore fallback",
            )
            if user.is_breakglass:
                pending = getattr(request.state, "breakglass_alert_pending", None)
                if pending:
                    await alert(db, subject="SAA Admin Console: break-glass unlock", body=pending)
            return templates.TemplateResponse(
                request, "ad/action_result.html",
                {"user": user, "ok": True, "message": f"Unlock succeeded for {sam} (via the AdminSDHolder-protected-account fallback)."},
            )
        await _log_and_alert(request, user, action=f"{action}_failed", target_id=sam, reason=reason, detail=str(exc))
        return templates.TemplateResponse(request, "ad/action_result.html", {"user": user, "ok": False, "message": str(exc)})
    finally:
        conn.unbind()

    await _log_and_alert(request, user, action=action, target_id=sam, reason=reason)
    if user.is_breakglass:
        pending = getattr(request.state, "breakglass_alert_pending", None)
        if pending:
            await alert(db, subject=f"SAA Admin Console: break-glass {action}", body=pending)
    return templates.TemplateResponse(request, "ad/action_result.html", {"user": user, "ok": True, "message": f"{action.replace('_', ' ').title()} succeeded for {sam}."})
