"""User offboarding: bundles the automatable steps (disable, reset
password, remove every group membership) into one action, tracks the two
Exchange Online/Entra steps this app can't automate yet (mailbox -> shared,
license removal) as admin-ticked checkboxes, and tracks a 6-month
deletion-eligible clock so an overdue account is impossible to miss on
this page — see CLAUDE_CONTEXT.md "Offboarding" for the full process this
implements and why steps 5/8/12 stay manual.

Deliberately reuses ad_accounts.py's connection/scope helpers
(_open_conn/_check_scope/_client_ip/_log_and_alert, AdNotConfigured/
ScopeDenied) rather than duplicating them into a shared module — this is
the only other place they're needed, and _check_scope's OU-scoping logic
in particular must never drift out of sync between the two call sites.
"""

import json

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ldap_client, user_provisioning
from app.core.alerting import alert
from app.core.auth import CurrentUser, require
from app.core.db import get_db
from app.core.models import OffboardingRecord, utcnow
from app.core.ratelimit import check as rate_check
from app.core.settings_store import load_settings
from app.routers.ad_accounts import AdNotConfigured, ScopeDenied, _check_scope, _client_ip, _log_and_alert, _open_conn
from app.templating import templates

router = APIRouter()


@router.get("/offboarding/user-suggest")
async def offboarding_user_suggest(
    q: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require("ad.offboard")),
):
    """Live autocomplete for the Start Offboarding modal's username field
    — same search_accounts()-backed shape as ad_accounts.py's
    member-suggest/name-suggest, filtered to user objects only (a
    computer account isn't something this feature ever applies to)."""
    q = q.strip()
    if not q:
        return JSONResponse({"candidates": []})
    store = await load_settings(db)
    try:
        conn = _open_conn(store)
    except AdNotConfigured:
        return JSONResponse({"candidates": []})
    try:
        results = ldap_client.search_accounts(conn, store.get("ad.base_dn"), q, limit=8)
    finally:
        conn.unbind()
    candidates = [{"sam": r["sam"], "display_name": r["display_name"]} for r in results if r["kind"] == "user"]
    return JSONResponse({"candidates": candidates})


@router.get("/offboarding", response_class=HTMLResponse)
async def offboarding_index(
    request: Request,
    history: bool = False,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require("ad.offboard")),
):
    if history:
        stmt = select(OffboardingRecord).where(OffboardingRecord.completed_at.is_not(None)).order_by(OffboardingRecord.completed_at.desc())
    else:
        stmt = select(OffboardingRecord).where(OffboardingRecord.completed_at.is_(None)).order_by(OffboardingRecord.initiated_at.asc())
    records = list((await db.execute(stmt)).scalars())
    groups_by_id = {r.id: json.loads(r.removed_groups_json) for r in records}
    return templates.TemplateResponse(
        request, "offboarding/index.html",
        {"user": user, "records": records, "groups_by_id": groups_by_id, "history": history},
    )


@router.post("/offboarding/start")
async def offboarding_start(
    request: Request,
    sam: str = Form(...),
    reason: str = Form(...),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require("ad.offboard")),
):
    back = {"back_url": "/offboarding", "back_label": "Back to Offboarding"}
    sam = sam.strip()
    if not reason.strip():
        return templates.TemplateResponse(request, "ad/action_result.html", {"user": user, "ok": False, "message": "A reason/ticket-ref is required.", **back})
    if not sam:
        return templates.TemplateResponse(request, "ad/action_result.html", {"user": user, "ok": False, "message": "A username is required.", **back})
    if not rate_check(f"offboard:{user.username}", max_calls=10, window_seconds=600):
        raise HTTPException(status_code=429, detail="Too many offboarding runs — try again shortly.")

    existing = (
        await db.execute(
            select(OffboardingRecord).where(OffboardingRecord.sam == sam, OffboardingRecord.completed_at.is_(None))
        )
    ).scalar_one_or_none()
    if existing is not None:
        return templates.TemplateResponse(
            request, "ad/action_result.html",
            {"user": user, "ok": False, "message": f"'{sam}' already has an active offboarding record (started {existing.initiated_at:%Y-%m-%d}).", **back},
        )

    store = await load_settings(db)
    try:
        conn = _open_conn(store)
    except AdNotConfigured:
        return templates.TemplateResponse(request, "ad/not_configured.html", {"user": user}, status_code=200)

    try:
        found = ldap_client.find_user(conn, store.get("ad.base_dn"), sam)
        if found is None:
            return templates.TemplateResponse(request, "ad/action_result.html", {"user": user, "ok": False, "message": f"No account found for '{sam}'.", **back})
        dn = found["dn"]
        _check_scope(store, dn, user)

        # Step 1: disable. Tolerant of failure — the bundle keeps going so
        # a problem with one sub-step doesn't block the others, same
        # partial-failure philosophy as Create User's own multi-step
        # sequence. Every outcome is recorded, never silently dropped.
        disable_ok = True
        disable_error = None
        try:
            current_uac = int(found["attributes"].get("userAccountControl", [0])[0])
            ldap_client.set_enabled(conn, dn, current_uac, enabled=False)
        except ldap_client.LdapError as exc:
            disable_ok = False
            disable_error = str(exc)

        # Step 2: reset to a random password nobody is ever shown — the
        # account is disabled, so nothing depends on this value being
        # usable; it exists purely to invalidate whatever the departing
        # user knew. Never logged or displayed, same convention as every
        # other password this app generates.
        reset_ok = True
        reset_error = None
        try:
            random_password = user_provisioning.generate_password()
            ldap_client.reset_password(conn, dn, random_password, force_change_at_logon=False)
        except ldap_client.LdapError as exc:
            reset_ok = False
            reset_error = str(exc)

        # Step 4: remove from every group, recording a permanent snapshot
        # of what the account was in and whether each removal actually
        # succeeded — the account's live memberOf can't answer that later.
        group_dns = found["attributes"].get("memberOf", [])
        group_infos = ldap_client.resolve_groups_by_dn(conn, store.get("ad.base_dn"), group_dns)
        removed_groups = []
        removed_count = 0
        for g in group_infos:
            entry = {"sam": g["sam"], "name": g["name"], "dn": g["dn"], "removed": False, "error": None}
            try:
                ldap_client.remove_group_member(conn, g["dn"], dn)
                entry["removed"] = True
                removed_count += 1
            except ldap_client.LdapError as exc:
                entry["error"] = str(exc)
            removed_groups.append(entry)

        record = OffboardingRecord(
            sam=sam,
            display_name=found["attributes"].get("displayName", [None])[0],
            dn=dn,
            initiated_by=user.username,
            reason=reason,
            disable_ok=disable_ok,
            reset_password_ok=reset_ok,
            removed_groups_json=json.dumps(removed_groups),
        )
        db.add(record)
        await db.commit()
    except ScopeDenied as exc:
        return templates.TemplateResponse(request, "ad/action_result.html", {"user": user, "ok": False, "message": exc.message, **back})
    finally:
        conn.unbind()

    detail_parts = [
        f"disable={'ok' if disable_ok else f'FAILED: {disable_error}'}",
        f"reset_password={'ok' if reset_ok else f'FAILED: {reset_error}'}",
        f"removed from {removed_count}/{len(removed_groups)} groups",
    ]
    await _log_and_alert(request, user, action="offboard_start", target_id=sam, reason=reason, detail="; ".join(detail_parts))
    if user.is_breakglass:
        pending = getattr(request.state, "breakglass_alert_pending", None)
        if pending:
            await alert(db, subject="SAA Admin Console: break-glass offboard_start", body=pending)

    warnings = []
    if not disable_ok:
        warnings.append(f"disable FAILED ({disable_error}) — do this manually")
    if not reset_ok:
        warnings.append(f"password reset FAILED ({reset_error}) — do this manually")
    failed_groups = [g["sam"] for g in removed_groups if not g["removed"]]
    if failed_groups:
        warnings.append(f"could not remove from: {', '.join(failed_groups)}")
    message = f"Offboarding started for '{sam}'."
    if warnings:
        message += " ISSUES: " + "; ".join(warnings)
    return templates.TemplateResponse(request, "ad/action_result.html", {"user": user, "ok": not warnings, "message": message, "back_url": "/offboarding", "back_label": "Back to Offboarding"})


async def _get_record_or_404(db: AsyncSession, record_id: int) -> OffboardingRecord | None:
    return await db.get(OffboardingRecord, record_id)


@router.post("/offboarding/{record_id}/mailbox-converted")
async def offboarding_toggle_mailbox(
    request: Request,
    record_id: int,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require("ad.offboard")),
):
    """One-click toggle, no reason required — this doesn't perform or
    verify any Exchange Online action itself, it just records that an
    admin says they did step 5 manually (see module docstring). Same
    unreasoned-audit-row precedent as settings_change."""
    record = await _get_record_or_404(db, record_id)
    if record is None:
        return templates.TemplateResponse(request, "ad/action_result.html", {"user": user, "ok": False, "message": "Offboarding record not found.", "back_url": "/offboarding", "back_label": "Back to Offboarding"})
    record.mailbox_converted = not record.mailbox_converted
    record.mailbox_converted_by = user.username if record.mailbox_converted else None
    record.mailbox_converted_at = utcnow() if record.mailbox_converted else None
    await db.commit()
    await _log_and_alert(request, user, action="offboarding_mailbox_converted", target_id=record.sam, reason="", detail=str(record.mailbox_converted))
    if user.is_breakglass:
        pending = getattr(request.state, "breakglass_alert_pending", None)
        if pending:
            await alert(db, subject="SAA Admin Console: break-glass offboarding_mailbox_converted", body=pending)
    return templates.TemplateResponse(request, "ad/action_result.html", {"user": user, "ok": True, "message": f"Mailbox-converted marked {'done' if record.mailbox_converted else 'not done'} for {record.sam}.", "back_url": "/offboarding", "back_label": "Back to Offboarding"})


@router.post("/offboarding/{record_id}/licenses-removed")
async def offboarding_toggle_licenses(
    request: Request,
    record_id: int,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require("ad.offboard")),
):
    record = await _get_record_or_404(db, record_id)
    if record is None:
        return templates.TemplateResponse(request, "ad/action_result.html", {"user": user, "ok": False, "message": "Offboarding record not found.", "back_url": "/offboarding", "back_label": "Back to Offboarding"})
    record.licenses_removed = not record.licenses_removed
    record.licenses_removed_by = user.username if record.licenses_removed else None
    record.licenses_removed_at = utcnow() if record.licenses_removed else None
    await db.commit()
    await _log_and_alert(request, user, action="offboarding_licenses_removed", target_id=record.sam, reason="", detail=str(record.licenses_removed))
    if user.is_breakglass:
        pending = getattr(request.state, "breakglass_alert_pending", None)
        if pending:
            await alert(db, subject="SAA Admin Console: break-glass offboarding_licenses_removed", body=pending)
    return templates.TemplateResponse(request, "ad/action_result.html", {"user": user, "ok": True, "message": f"Licenses-removed marked {'done' if record.licenses_removed else 'not done'} for {record.sam}.", "back_url": "/offboarding", "back_label": "Back to Offboarding"})


@router.post("/offboarding/{record_id}/complete")
async def offboarding_complete(
    request: Request,
    record_id: int,
    reason: str = Form(...),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require("ad.offboard")),
):
    """Marks the record complete/archived — used once an admin has
    actually deleted the AD account by hand (step 12; this app doesn't
    perform the deletion itself, per Alex's explicit "manually" wording).
    Allowed at any time, not gated on the 6-month window having actually
    elapsed — the window is a reminder, not a hard lock, consistent with
    this app's general "trust the operator, audit everything" posture
    rather than blocking a legitimate early close-out with no override."""
    back = {"back_url": "/offboarding", "back_label": "Back to Offboarding"}
    if not reason.strip():
        return templates.TemplateResponse(request, "ad/action_result.html", {"user": user, "ok": False, "message": "A reason/ticket-ref is required.", **back})
    record = await _get_record_or_404(db, record_id)
    if record is None:
        return templates.TemplateResponse(request, "ad/action_result.html", {"user": user, "ok": False, "message": "Offboarding record not found.", **back})
    record.completed_at = utcnow()
    record.completed_by = user.username
    record.completed_reason = reason
    await db.commit()
    await _log_and_alert(request, user, action="offboarding_completed", target_id=record.sam, reason=reason)
    if user.is_breakglass:
        pending = getattr(request.state, "breakglass_alert_pending", None)
        if pending:
            await alert(db, subject="SAA Admin Console: break-glass offboarding_completed", body=pending)
    return templates.TemplateResponse(request, "ad/action_result.html", {"user": user, "ok": True, "message": f"Offboarding for '{record.sam}' marked complete.", **back})
