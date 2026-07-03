from fastapi import Request, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from core.database import get_db
from core.auth import get_session_user
from models.models import User


def require_session(request: Request) -> dict:
    user = get_session_user(request)
    if not user:
        raise HTTPException(status_code=307, headers={"Location": "/auth/login"})
    return user


def require_user(
    request: Request,
    db: Session = Depends(get_db),
    session: dict = Depends(require_session),
) -> User:
    user = db.query(User).filter(User.id == session["user_id"]).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=403, detail="Account inactive or not found")
    # Attach role to request state for template use
    request.state.current_user = user
    request.state.role = session.get("role", "user")
    return user


def require_tech(
    user: User = Depends(require_user),
    request: Request = None,
) -> User:
    if request is None:
        raise HTTPException(status_code=403, detail="Forbidden")
    role = request.state.role
    if role not in ("tech", "admin"):
        raise HTTPException(status_code=403, detail="Tech or Admin access required")
    return user


def require_admin(
    user: User = Depends(require_user),
    request: Request = None,
) -> User:
    if request is None:
        raise HTTPException(status_code=403, detail="Forbidden")
    if request.state.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


# ─── Template context helper ──────────────────────────────────────────────────

def template_ctx(request: Request, **extra) -> dict:
    """Base context dict injected into every template."""
    session = get_session_user(request)
    return {
        "request": request,
        "current_user": getattr(request.state, "current_user", None),
        "role": getattr(request.state, "role", "user"),
        "session": session,
        **extra,
    }
