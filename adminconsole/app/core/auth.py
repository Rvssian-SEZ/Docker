"""Authentication + authorization core for normal (non-break-glass) users.

Session-based: user id in the signed session cookie, break-glass in the
same session under a separate `breakglass` flag (see app/core/breakglass.py
and app/routers/auth.py) so the two identities can never be confused by a
stale/partial session dict.

- get_current_user: dependency; raises RequiresLoginException -> /login redirect
- require(permission): dependency factory enforcing the role permission matrix
- Permissions are loaded per request (no caching) — matrix edits in Settings
  take effect immediately, same as itops2.
- Break-glass always satisfies require(permission) for every permission —
  see CurrentUser.can().

Session timeout: SessionMiddleware itself doesn't do idle timeout: app/main.py
enforces `session.absolute` less usefully than an idle check, so
get_current_user additionally checks last-activity against a 15-minute
window (spec: "shorter than the reporting-only version... e.g. 15 min
idle") and clears+redirects on expiry, refreshing the marker on every
authenticated request.
"""

from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.db import get_db
from app.core.models import AuthSource, RolePermission, User
from app.core.security import verify_password

IDLE_TIMEOUT = timedelta(minutes=15)

# Settings page requires re-authentication to view/edit (spec) — a stolen
# session cookie alone isn't enough. Separate from IDLE_TIMEOUT: this
# clock resets only on an explicit re-auth, not on ordinary activity.
REAUTH_WINDOW = timedelta(minutes=5)


class RequiresLoginException(Exception):
    pass


class ReauthRequiredException(Exception):
    def __init__(self, next_path: str):
        self.next_path = next_path


class CurrentUser:
    """Lightweight request principal — plain values, safe everywhere
    (including passed into audit/alert calls, never an ORM object)."""

    def __init__(self, user: User | None, permissions: set[str], is_breakglass: bool = False, username: str | None = None):
        self.is_breakglass = is_breakglass
        if is_breakglass:
            self.id = None
            self.username = username or "breakglass"
            self.display_name = "Break-glass Admin"
            self.role = "breakglass"
        else:
            assert user is not None
            self.id = user.id
            self.username = user.username
            self.display_name = user.display_name or user.username
            self.role = user.role.name.value
        self.permissions = permissions

    def can(self, permission: str) -> bool:
        return self.is_breakglass or permission in self.permissions


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
    now = datetime.now(timezone.utc)
    last_seen_raw = request.session.get("last_seen")
    if last_seen_raw:
        last_seen = datetime.fromisoformat(last_seen_raw)
        if now - last_seen > IDLE_TIMEOUT:
            request.session.clear()
            raise RequiresLoginException()

    if request.session.get("breakglass"):
        request.session["last_seen"] = now.isoformat()
        return CurrentUser(None, set(), is_breakglass=True, username=request.session.get("breakglass_username"))

    user_id = request.session.get("user_id")
    if user_id is None:
        raise RequiresLoginException()
    user = (
        await db.execute(select(User).options(selectinload(User.role)).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        request.session.clear()
        raise RequiresLoginException()
    perms = {
        p
        for (p,) in (
            await db.execute(select(RolePermission.permission).where(RolePermission.role_id == user.role_id))
        ).all()
    }
    request.session["last_seen"] = now.isoformat()
    return CurrentUser(user, perms)


def require(permission: str):
    async def checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not user.can(permission):
            raise HTTPException(status_code=403, detail=f"Missing permission: {permission}")
        return user

    return checker


def touch_reauth(request: Request) -> None:
    request.session["reauth_at"] = datetime.now(timezone.utc).isoformat()


def require_reauth(request: Request, user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    raw = request.session.get("reauth_at")
    fresh = bool(raw) and datetime.now(timezone.utc) - datetime.fromisoformat(raw) <= REAUTH_WINDOW
    if not fresh:
        raise ReauthRequiredException(next_path=request.url.path)
    return user
