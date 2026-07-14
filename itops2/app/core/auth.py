"""Authentication + authorization core.

Session-based: user id in the signed session cookie.
- get_current_user: dependency; raises RequiresLoginException -> /login redirect
- require(permission): dependency factory enforcing the role permission matrix
- Permissions are loaded per request (no local caching of role grants —
  matrix edits take effect immediately).

OIDC and LDAP providers plug in at Phase 3; local auth ships now.
The break-glass admin always authenticates locally regardless of provider config.
"""

from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from app.core.security import hash_password, verify_password
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.db import get_db
from app.core.models import AuthSource, RolePermission, User



class RequiresLoginException(Exception):
    pass


class CurrentUser:
    """Lightweight request principal — plain values, safe everywhere."""

    def __init__(self, user: User, permissions: set[str]):
        self.id = user.id
        self.username = user.username
        self.display_name = user.display_name or user.username
        self.role = user.role.name.value
        self.company_id = user.company_id
        self.permissions = permissions

    def can(self, permission: str) -> bool:
        return permission in self.permissions


async def authenticate_local(db: AsyncSession, username: str, password: str) -> User | None:
    user = (
        await db.execute(
            select(User)
            .options(selectinload(User.role))
            .where(User.username == username, User.auth_source == AuthSource.local)
        )
    ).scalar_one_or_none()
    if user is None or not user.is_active or not user.password_hash:
        return None
    if not verify_password(password, user.password_hash):
        return None
    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()
    return user


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> CurrentUser:
    user_id = request.session.get("user_id")
    if user_id is None:
        raise RequiresLoginException()
    user = (
        await db.execute(
            select(User).options(selectinload(User.role)).where(User.id == user_id)
        )
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        request.session.clear()
        raise RequiresLoginException()
    perms = {
        p
        for (p,) in (
            await db.execute(
                select(RolePermission.permission).where(RolePermission.role_id == user.role_id)
            )
        ).all()
    }
    return CurrentUser(user, perms)


def require(permission: str):
    async def checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not user.can(permission):
            raise HTTPException(status_code=403, detail=f"Missing permission: {permission}")
        return user

    return checker


def require_all(*permissions: str):
    """Like require(), but for routes that need more than one grant at
    once — e.g. CSV export needs both the list's own view permission
    (so export can't see data the UI wouldn't show) AND reports.export
    (the export feature itself)."""

    async def checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        missing = [p for p in permissions if not user.can(p)]
        if missing:
            raise HTTPException(status_code=403, detail=f"Missing permission(s): {', '.join(missing)}")
        return user

    return checker
