"""ITOps v2 — application entrypoint."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from starlette.middleware.sessions import SessionMiddleware

from app.core.auth import CurrentUser, RequiresLoginException, get_current_user
from app.core.bootstrap import bootstrap
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.routers import assets as assets_router
from app.routers import auth as auth_router
from app.routers import catalog as catalog_router
from app.routers import contracts as contracts_router
from app.routers import maintenance as maintenance_router
from app.routers import permissions as permissions_router
from app.routers import printers as printers_router
from app.routers import settings as settings_router
from app.routers import users as users_router
from app.templating import templates
from app.version import __version__

logging.basicConfig(level=logging.INFO)
settings = get_settings()

BASE_DIR = Path(__file__).parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with SessionLocal() as db:
        await bootstrap(db)
    yield


app = FastAPI(title=settings.app_name, version=__version__, lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

app.include_router(auth_router.router)
app.include_router(settings_router.router)
app.include_router(permissions_router.router)
app.include_router(users_router.router)
app.include_router(catalog_router.router)
app.include_router(assets_router.router)
app.include_router(maintenance_router.router)
app.include_router(printers_router.router)
app.include_router(contracts_router.router)


@app.exception_handler(RequiresLoginException)
async def requires_login_handler(request: Request, exc: RequiresLoginException):
    return RedirectResponse(url="/login", status_code=302)


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "version": __version__}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, user: CurrentUser = Depends(get_current_user)):
    return templates.TemplateResponse(request, "index.html", {"user": user})
