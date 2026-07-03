from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from core import auth as oidc
from core.database import get_db

router = APIRouter()


@router.get("/login")
async def login(request: Request, next: str = "/"):
    """Redirect the browser to Authentik's authorization endpoint."""
    state = oidc.make_state(next_url=next)
    # Stash state in session so we can verify it in /callback
    request.session["oauth_state"] = state
    return RedirectResponse(oidc.get_authorization_url(state))


@router.get("/callback")
async def callback(
    request: Request,
    code: str,
    state: str,
    db: Session = Depends(get_db),
):
    """Handle the OIDC redirect from Authentik."""
    # 1. Verify state
    stored_state = request.session.pop("oauth_state", None)
    if stored_state != state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state — possible CSRF")

    try:
        payload = oidc.verify_state(state)
    except Exception:
        raise HTTPException(status_code=400, detail="State token invalid or expired")

    # 2. Exchange code for tokens
    try:
        tokens = await oidc.exchange_code_for_tokens(code)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Token exchange failed: {e}")

    access_token = tokens.get("access_token")
    if not access_token:
        raise HTTPException(status_code=502, detail="No access_token in Authentik response")

    # 3. Fetch userinfo
    try:
        userinfo = await oidc.get_userinfo(access_token)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Userinfo fetch failed: {e}")

    # 4. Upsert user in local DB
    user = oidc.upsert_user(db, userinfo)

    # 5. Write session
    oidc.set_session_user(request, user)

    # 6. Redirect to original destination
    next_url = payload.get("next", "/")
    return RedirectResponse(next_url, status_code=302)


@router.get("/logout")
async def logout(request: Request):
    """Clear local session and redirect to Authentik's end-session endpoint."""
    from core.config import settings
    oidc.clear_session(request)
    return RedirectResponse(settings.authentik_logout_url, status_code=302)
