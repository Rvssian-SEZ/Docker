from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from core.database import get_db
from core.auth import (
    build_authorize_url, exchange_code, fetch_userinfo,
    upsert_user, get_user_role, create_session_cookie,
    clear_session_cookie, get_session_user, _unsign,
)

router = APIRouter(prefix="/auth", tags=["auth"])
templates = Jinja2Templates(directory="templates")


@router.get("/login")
async def login(request: Request):
    if get_session_user(request):
        return RedirectResponse("/tickets", status_code=302)
    authorize_url, state = build_authorize_url(request)
    response = RedirectResponse(authorize_url, status_code=302)
    response.set_cookie("hd_oauth_state", state, httponly=True, max_age=300, samesite="lax")
    return response


@router.get("/callback")
async def callback(
    request: Request,
    code: str = None,
    state: str = None,
    error: str = None,
    db: Session = Depends(get_db),
):
    if error or not code:
        return templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "error": f"Authentication failed: {error or 'No code received'}"},
        )

    # Validate state
    stored_state = request.cookies.get("hd_oauth_state", "")
    if not stored_state or state != stored_state:
        return templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "error": "Invalid OAuth state. Please try again."},
        )
    if not _unsign(state):
        return templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "error": "State signature invalid."},
        )

    tokens = await exchange_code(code)
    userinfo = await fetch_userinfo(tokens["access_token"])

    user = upsert_user(db, userinfo)
    groups = userinfo.get("groups", [])
    role = get_user_role(groups)

    session_data = {
        "user_id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": role,
    }

    response = RedirectResponse("/tickets", status_code=302)
    response.delete_cookie("hd_oauth_state")
    create_session_cookie(response, session_data)
    return response


@router.get("/logout")
async def logout(request: Request):
    from core.config import get_settings
    settings = get_settings()
    response = RedirectResponse(settings.authentik_end_session_url, status_code=302)
    clear_session_cookie(response)
    return response
