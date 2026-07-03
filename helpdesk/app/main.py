from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.exceptions import HTTPException

from core.config import get_settings
from core.database import engine, Base
from models import models  # ensure all models are imported before create_all
from routers import auth, tickets, reports, admin

settings = get_settings()

# Create helpdesk tables (shared tables already exist, checkfirst=True handles that)
# Alembic handles migrations; this is a safety net
Base.metadata.create_all(bind=engine, checkfirst=True)

app = FastAPI(
    title=settings.app_name,
    docs_url="/api/docs" if settings.debug else None,
    redoc_url=None,
)

templates = Jinja2Templates(directory="templates")

# Register routers
app.include_router(auth.router)
app.include_router(tickets.router)
app.include_router(reports.router)
app.include_router(admin.router)


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse("/tickets", status_code=302)


@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "ok"}


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code == 307 and "Location" in exc.headers:
        return RedirectResponse(exc.headers["Location"], status_code=302)
    return templates.TemplateResponse(
        "error.html",
        {"request": request, "status_code": exc.status_code, "detail": exc.detail},
        status_code=exc.status_code,
    )
