from urllib.parse import urlencode

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from core.config import settings
from core.deps import RequiresLoginException
import models  # noqa: F401
from routers import auth, users, assets, equipment

app = FastAPI(
    title="IT Ops Portal",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SECRET_KEY,
    session_cookie="itops_session",
    max_age=86400 * 7,
    https_only=True,
    same_site="lax",
)

@app.exception_handler(RequiresLoginException)
def redirect_to_login(request: Request, exc: RequiresLoginException):
    params = urlencode({"next": exc.next_url})
    return RedirectResponse(f"/auth/login?{params}", status_code=302)

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(users.router, prefix="/users", tags=["users"])
app.include_router(assets.router, prefix="/assets", tags=["assets"])
app.include_router(equipment.router, prefix="/equipment", tags=["equipment"])

@app.get("/")
def root():
    return RedirectResponse("/assets", status_code=302)

@app.get("/health")
def health():
    return {"status": "ok"}
