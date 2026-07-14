"""Users management + self-service password change.

Rules:
- Deactivate, never hard-delete (audit log rows reference users).
- Break-glass account: role locked to Admin, cannot be deactivated;
  password CAN be changed (that's the point — retire the .env password).
- OIDC/LDAP users (Phase 3b) have no local password; reset hidden for them.
- Company assignment appears when multi-company is enabled in settings.
"""

from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import CurrentUser, get_current_user, require, require_all
from app.core.csv_export import csv_response, fmt_datetime
from app.core.db import get_db
from app.core.models import AuditLog, AuthSource, Company, NotificationEvent, NotificationSubscription, Role, User
from app.core.notifications import EVENT_PERMISSION, EVENT_TYPES
from app.core.scoping import company_scope
from app.core.security import hash_password, verify_password
from app.core.settings_store import load_settings
from app.templating import templates

router = APIRouter()

MIN_PASSWORD_LEN = 10


async def _form_context(db: AsyncSession) -> dict:
    roles = (await db.execute(select(Role).order_by(Role.id))).scalars().all()
    store = await load_settings(db)
    companies = []
    multi = store.get_bool("company.multi_enabled")
    if multi:
        companies = (
            (await db.execute(select(Company).order_by(Company.name))).scalars().all()
        )
    return {"roles": roles, "companies": companies, "multi_company": multi}


@router.get("/users", response_class=HTMLResponse)
async def users_list(
    request: Request,
    user: CurrentUser = Depends(require("users.view")),
    db: AsyncSession = Depends(get_db),
):
    users = (
        (
            await db.execute(
                select(User)
                .options(selectinload(User.role), selectinload(User.company))
                .order_by(User.username)
            )
        )
        .scalars()
        .all()
    )
    ctx = await _form_context(db)
    ctx.update({"user": user, "users": users})
    return templates.TemplateResponse(request, "users/list.html", ctx)


@router.get("/users/export")
async def users_export(
    user: CurrentUser = Depends(require_all("users.view", "reports.export")),
    db: AsyncSession = Depends(get_db),
):
    """No filter bar exists on /users (never built one), so this exports
    the full list — still scoped to the caller's own company when
    company.scoped_users is on, same as every other export."""
    store = await load_settings(db)
    scope_company_id = company_scope(user, store)
    query = select(User).options(selectinload(User.role), selectinload(User.company)).order_by(User.username)
    if scope_company_id is not None:
        query = query.where(User.company_id == scope_company_id)
    users = (await db.execute(query)).scalars().unique().all()

    fieldnames = ["username", "display_name", "email", "role", "company", "auth_source", "is_active", "last_login_at"]
    rows = [
        {
            "username": u.username,
            "display_name": u.display_name or "",
            "email": u.email or "",
            "role": u.role.name.value,
            "company": u.company.name if u.company else "",
            "auth_source": u.auth_source.value,
            "is_active": "yes" if u.is_active else "no",
            "last_login_at": fmt_datetime(u.last_login_at),
        }
        for u in users
    ]
    return csv_response(f"users-export-{date.today():%Y-%m-%d}.csv", fieldnames, rows)


@router.post("/users/create", response_class=HTMLResponse)
async def users_create(
    request: Request,
    username: str = Form(""),
    display_name: str = Form(""),
    email: str = Form(""),
    password: str = Form(""),
    role_id: int | None = Form(None),
    company_id: str = Form(""),
    user: CurrentUser = Depends(require("users.manage")),
    db: AsyncSession = Depends(get_db),
):
    username = username.strip().lower()
    if not username:
        return _toast(request, False, "Username is required.")
    if len(password) < MIN_PASSWORD_LEN:
        return _toast(request, False, f"Password must be at least {MIN_PASSWORD_LEN} characters.")
    exists = (
        await db.execute(select(User.id).where(User.username == username))
    ).first()
    if exists:
        return _toast(request, False, f"Username '{username}' is already taken.")
    if role_id is None:
        return _toast(request, False, "Role is required.")
    if await db.get(Role, role_id) is None:
        return _toast(request, False, "Unknown role.")

    new_user = User(
        username=username,
        display_name=display_name.strip() or None,
        email=email.strip() or None,
        auth_source=AuthSource.local,
        password_hash=hash_password(password),
        role_id=role_id,
        company_id=int(company_id) if company_id.isdigit() else None,
    )
    db.add(new_user)
    await db.flush()
    db.add(
        AuditLog(
            user_id=user.id, action="create", entity_type="user", entity_id=str(new_user.id),
            detail=username,
        )
    )
    await db.commit()
    # HX-Redirect: full-row list refresh after create keeps the code simple;
    # the create modal is the infrequent path, per-field HTMX isn't worth it here.
    return _refresh(request)


@router.post("/users/{user_id}/update", response_class=HTMLResponse)
async def users_update(
    request: Request,
    user_id: int,
    role_id: int | None = Form(None),
    company_id: str = Form(""),
    is_active: str = Form("false"),
    user: CurrentUser = Depends(require("users.manage")),
    db: AsyncSession = Depends(get_db),
):
    target = await db.get(User, user_id, options=[selectinload(User.role)])
    if target is None:
        return _toast(request, False, "User not found.")

    active = is_active == "true"

    if target.is_breakglass:
        if not active:
            return _toast(request, False, "The break-glass account cannot be deactivated.")
        # role locked — ignore any submitted role change
    else:
        if role_id is None:
            return _toast(request, False, "Role is required.")
        if await db.get(Role, role_id) is None:
            return _toast(request, False, "Unknown role.")
        if target.id == user.id and not active:
            return _toast(request, False, "You cannot deactivate your own account.")
        target.role_id = role_id
        target.is_active = active

    target.company_id = int(company_id) if company_id.isdigit() else None

    db.add(
        AuditLog(
            user_id=user.id, action="update", entity_type="user", entity_id=str(target.id),
            detail=target.username,
        )
    )
    await db.commit()
    return _toast(request, True, f"Updated {target.username}.")


@router.post("/users/{user_id}/reset-password", response_class=HTMLResponse)
async def users_reset_password(
    request: Request,
    user_id: int,
    new_password: str = Form(""),
    user: CurrentUser = Depends(require("users.manage")),
    db: AsyncSession = Depends(get_db),
):
    target = await db.get(User, user_id)
    if target is None:
        return _toast(request, False, "User not found.")
    if target.auth_source != AuthSource.local:
        return _toast(request, False, "This user authenticates externally; no local password.")
    if len(new_password) < MIN_PASSWORD_LEN:
        return _toast(request, False, f"Password must be at least {MIN_PASSWORD_LEN} characters.")
    target.password_hash = hash_password(new_password)
    db.add(
        AuditLog(
            user_id=user.id, action="reset_password", entity_type="user",
            entity_id=str(target.id), detail=target.username,
        )
    )
    await db.commit()
    return _toast(request, True, f"Password reset for {target.username}.")


# ---- self-service ----

@router.get("/profile", response_class=HTMLResponse)
async def profile(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    me = await db.get(User, user.id)
    subscribed = {
        s
        for (s,) in (
            await db.execute(
                select(NotificationSubscription.event_type).where(NotificationSubscription.user_id == user.id)
            )
        ).all()
    }
    # Only offer a checkbox for events this user's role can actually
    # receive (matches the permission gate applied at send time in
    # app/core/notifications.py) -- no point showing a subscription
    # toggle that would silently never fire.
    available_events = [e for e in EVENT_TYPES if user.can(e["permission"])]
    return templates.TemplateResponse(
        request, "users/profile.html",
        {
            "user": user,
            "is_local": me.auth_source == AuthSource.local,
            "available_events": available_events,
            "subscribed": {e.value for e in subscribed},
        },
    )


@router.post("/profile/notifications/toggle", response_class=HTMLResponse)
async def toggle_notification_subscription(
    request: Request,
    event_type: str = Form(""),
    subscribed: str = Form("false"),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if event_type not in NotificationEvent.__members__:
        return _toast(request, False, "Unknown event type.")
    if not user.can(EVENT_PERMISSION[event_type]):
        return _toast(request, False, "You do not have permission to receive this notification.")
    want = subscribed == "true"

    existing = (
        await db.execute(
            select(NotificationSubscription).where(
                NotificationSubscription.user_id == user.id,
                NotificationSubscription.event_type == NotificationEvent[event_type],
            )
        )
    ).scalar_one_or_none()
    if want and existing is None:
        db.add(NotificationSubscription(user_id=user.id, event_type=NotificationEvent[event_type]))
    elif not want and existing is not None:
        await db.delete(existing)
    await db.commit()
    return _toast(request, True, "Saved.")


@router.post("/profile/password", response_class=HTMLResponse)
async def change_own_password(
    request: Request,
    current_password: str = Form(""),
    new_password: str = Form(""),
    confirm_password: str = Form(""),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    me = await db.get(User, user.id)
    if me.auth_source != AuthSource.local:
        return _toast(request, False, "Your account authenticates externally.")
    if not verify_password(current_password, me.password_hash or ""):
        return _toast(request, False, "Current password is incorrect.")
    if len(new_password) < MIN_PASSWORD_LEN:
        return _toast(request, False, f"New password must be at least {MIN_PASSWORD_LEN} characters.")
    if new_password != confirm_password:
        return _toast(request, False, "New passwords do not match.")
    me.password_hash = hash_password(new_password)
    db.add(
        AuditLog(user_id=user.id, action="change_password", entity_type="user",
                 entity_id=str(user.id), detail=me.username)
    )
    await db.commit()
    return _toast(request, True, "Password changed.")


# ---- helpers ----

def _toast(request: Request, ok: bool, message: str):
    return templates.TemplateResponse(
        request, "partials/toast.html", {"ok": ok, "message": message}
    )


def _refresh(request: Request):
    from fastapi.responses import Response

    return Response(status_code=204, headers={"HX-Refresh": "true"})
