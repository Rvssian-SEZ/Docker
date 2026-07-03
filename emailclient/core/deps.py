from fastapi import Request


class RequiresLoginException(Exception):
    pass


def require_user(request: Request) -> dict:
    user = request.session.get("user")
    if not user:
        raise RequiresLoginException()
    return user
