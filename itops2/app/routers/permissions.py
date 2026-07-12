"""Permissions grid — Settings → Permissions.

Design:
- Grid renders from the PERMISSIONS registry (rows) × fixed roles (columns).
- Each checkbox saves individually via HTMX on change — instant, no Save button.
- Lockout guard: 'settings.manage' cannot be removed from the admin role,
  otherwise you could brick the settings UI for everyone.
"""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, require
from app.core.db import get_db
from app.core.models import AuditLog, Role, RoleName, RolePermission
from app.core.permissions import ALL_PERMISSIONS, PERMISSIONS
from app.templating import templates

router = APIRouter(prefix="/settings/permissions")


async def _grid_context(db: AsyncSession) -> dict:
    roles = (
        (await db.execute(select(Role).order_by(Role.id))).scalars().all()
    )
    granted: dict[int, set[str]] = {r.id: set() for r in roles}
    for rp in (await db.execute(select(RolePermission))).scalars():
        granted.setdefault(rp.role_id, set()).add(rp.permission)
    return {"roles": roles, "granted": granted, "groups": PERMISSIONS}


@router.get("", response_class=HTMLResponse)
async def permissions_grid(
    request: Request,
    user: CurrentUser = Depends(require("settings.manage")),
    db: AsyncSession = Depends(get_db),
):
    ctx = await _grid_context(db)
    ctx.update({"user": user, "active_tab": "permissions"})
    return templates.TemplateResponse(request, "settings/permissions.html", ctx)


@router.post("/toggle", response_class=HTMLResponse)
async def toggle_permission(
    request: Request,
    role_id: int = Form(...),
    permission: str = Form(...),
    # v1 lesson: HTMX sends strings; compare explicitly.
    granted: str = Form("false"),
    user: CurrentUser = Depends(require("settings.manage")),
    db: AsyncSession = Depends(get_db),
):
    grant = granted == "true"

    if permission not in ALL_PERMISSIONS:
        return templates.TemplateResponse(
            request, "partials/toast.html", {"ok": False, "message": "Unknown permission."}
        )
    role = await db.get(Role, role_id)
    if role is None:
        return templates.TemplateResponse(
            request, "partials/toast.html", {"ok": False, "message": "Unknown role."}
        )

    # Lockout guard
    if not grant and role.name == RoleName.admin and permission == "settings.manage":
        return templates.TemplateResponse(
            request,
            "partials/toast.html",
            {"ok": False, "message": "settings.manage cannot be removed from Admin."},
        )

    existing = (
        await db.execute(
            select(RolePermission).where(
                RolePermission.role_id == role_id, RolePermission.permission == permission
            )
        )
    ).scalar_one_or_none()

    if grant and existing is None:
        db.add(RolePermission(role_id=role_id, permission=permission))
    elif not grant and existing is not None:
        await db.execute(
            delete(RolePermission).where(RolePermission.id == existing.id)
        )

    db.add(
        AuditLog(
            user_id=user.id,
            action="grant" if grant else "revoke",
            entity_type="permission",
            entity_id=str(role_id),
            detail=f"{role.name.value}:{permission}",
        )
    )
    await db.commit()
    verb = "granted to" if grant else "revoked from"
    return templates.TemplateResponse(
        request,
        "partials/toast.html",
        {"ok": True, "message": f"{permission} {verb} {role.name.value.title()}."},
    )
