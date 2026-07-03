from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from core import auth as oidc

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/login")
async def login(request: Request):
    cfg = await oidc.get_oidc_config()
    state = oidc.make_state()
    request.session["oidc_state"]  = state
    request.session["oidc_config"] = cfg
    return RedirectResponse(oidc.build_auth_url(cfg["authorization_endpoint"], state))


@router.get("/callback")
async def callback(request: Request, code: str, state: str):
    if state != request.session.get("oidc_state"):
        return RedirectResponse(url="/auth/login")

    cfg      = request.session.get("oidc_config") or await oidc.get_oidc_config()
    tokens   = await oidc.exchange_code(cfg["token_endpoint"], code)
    userinfo = await oidc.fetch_userinfo(cfg["userinfo_endpoint"], tokens["access_token"])

    groups = userinfo.get("groups", [])
    role   = "admin" if "emailclient-admin" in groups else "user"

    request.session["user"] = {
        "sub":      userinfo.get("sub"),
        "name":     userinfo.get("name") or userinfo.get("preferred_username", "User"),
        "email":    userinfo.get("email", ""),
        "username": userinfo.get("preferred_username", ""),
        "role":     role,
    }
    request.session.pop("oidc_state",  None)
    request.session.pop("oidc_config", None)

    return RedirectResponse(url="/mail")


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/auth/login")
