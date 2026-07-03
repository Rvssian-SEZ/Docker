from fastapi import Depends, Request
from sqlalchemy.orm import Session

from core.database import get_db
from core.auth import get_session_user
from models.user import User


class RequiresLoginException(Exception):
    def __init__(self, next_url: str = "/"):
        self.next_url = next_url


def require_user(request: Request, db: Session = Depends(get_db)) -> User:
    session_user = get_session_user(request)
    if not session_user:
        raise RequiresLoginException(next_url=str(request.url))

    user = db.query(User).filter(User.id == session_user["id"]).first()
    if not user or not user.is_active:
        raise RequiresLoginException()

    return user


__all__ = ["require_user", "get_db", "RequiresLoginException"]
