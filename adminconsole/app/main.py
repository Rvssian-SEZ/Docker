"""SAA Admin Console — application entrypoint."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.core.audit import ensure_schema as ensure_audit_schema
from app.core.auth import ReauthRequiredException, RequiresLoginException
from app.core.bootstrap import bootstrap
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.routers import ad_accounts as ad_router
from app.routers import audit_log as audit_router
from app.routers import auth as auth_router
from app.routers import dashboard as dashboard_router
from app.routers import internal as internal_router
from app.routers import settings as settings_router
from app.version import __version__

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
settings = get_settings()

BASE_DIR = Path(__file__).parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    await ensure_audit_schema()
    async with SessionLocal() as db:
        await bootstrap(db)
    yield


app = FastAPI(title=settings.app_name, version=__version__, lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

app.include_router(dashboard_router.router)
app.include_router(auth_router.router)
app.include_router(settings_router.router)
app.include_router(audit_router.router)
app.include_router(ad_router.router)
app.include_router(internal_router.router)


@app.exception_handler(RequiresLoginException)
async def requires_login_handler(request: Request, exc: RequiresLoginException):
    return RedirectResponse(url="/login", status_code=302)


@app.exception_handler(ReauthRequiredException)
async def reauth_required_handler(request: Request, exc: ReauthRequiredException):
    return RedirectResponse(url=f"/settings/reauth?next={exc.next_path}", status_code=302)
