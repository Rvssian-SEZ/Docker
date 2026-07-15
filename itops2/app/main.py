"""ITOps v2 — application entrypoint."""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from starlette.middleware.sessions import SessionMiddleware

from app.core.auth import RequiresLoginException
from app.core.bootstrap import bootstrap
from app.core.config import get_settings
from app.core.daily_checks import run_if_due
from app.core.db import SessionLocal
from app.routers import assets as assets_router
from app.routers import auth as auth_router
from app.routers import catalog as catalog_router
from app.routers import contracts as contracts_router
from app.routers import dashboard as dashboard_router
from app.routers import import_wizard as import_wizard_router
from app.routers import inventory as inventory_router
from app.routers import maintenance as maintenance_router
from app.routers import permissions as permissions_router
from app.routers import printers as printers_router
from app.routers import settings as settings_router
from app.routers import users as users_router
from app.templating import templates
from app.version import __version__

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
settings = get_settings()

BASE_DIR = Path(__file__).parent


async def _daily_tick_loop() -> None:
    """Wakes roughly hourly and runs the scheduled checks (warranty/
    contract-renewal/low-stock digests, app/core/daily_checks.py) once
    per calendar day. Idempotency is a persisted date marker
    (notifications.last_daily_run), not a fixed trigger time -- safe
    across restarts, and if the container is down across an entire day
    that day's check is simply skipped, not backfilled (acceptable for
    advisory notifications).

    Chosen over a /tasks/daily endpoint + host cron (the other option
    presented to Alex before building this) because it needs no
    host-side setup beyond the existing scp+docker-compose deploy
    procedure -- every other phase's scheduled/background work has
    been entirely self-contained in the container, and this keeps that
    pattern intact.
    """
    while True:
        try:
            await run_if_due()
        except Exception:
            logger.exception("Daily scheduled-check tick failed")
        await asyncio.sleep(3600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with SessionLocal() as db:
        await bootstrap(db)
    task = asyncio.create_task(_daily_tick_loop())
    yield
    task.cancel()


app = FastAPI(title=settings.app_name, version=__version__, lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

app.include_router(dashboard_router.router)
app.include_router(auth_router.router)
app.include_router(settings_router.router)
app.include_router(permissions_router.router)
app.include_router(users_router.router)
app.include_router(catalog_router.router)
app.include_router(assets_router.router)
app.include_router(maintenance_router.router)
app.include_router(printers_router.router)
app.include_router(contracts_router.router)
app.include_router(inventory_router.router)
app.include_router(import_wizard_router.router)


@app.exception_handler(RequiresLoginException)
async def requires_login_handler(request: Request, exc: RequiresLoginException):
    return RedirectResponse(url="/login", status_code=302)


@app.exception_handler(RequestValidationError)
async def hx_validation_exception_handler(request: Request, exc: RequestValidationError):
    """Defense in depth for the Form(...) / 422 gap (see CLAUDE.md): every
    route should already validate its own fields and return a toast, but
    if a future route slips and FastAPI's own request validation rejects
    first, an htmx request would otherwise get a raw JSON body that htmx
    can't render into the toast target -- a silent dead end. Only
    htmx requests (HX-Request header) get this treatment; anything else
    (e.g. a malformed non-browser request) keeps FastAPI's default 422.
    """
    if request.headers.get("hx-request") == "true":
        errors = exc.errors()
        if errors:
            field = errors[0].get("loc", ["request"])[-1]
            message = f"{field}: {errors[0].get('msg', 'invalid value')}"
        else:
            message = "Invalid request."
        return templates.TemplateResponse(
            request, "partials/toast.html", {"ok": False, "message": message}
        )
    return await request_validation_exception_handler(request, exc)


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "version": __version__}
