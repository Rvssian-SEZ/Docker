"""Landing page. Reporting (license overview, security posture, mailbox
health, activity trends, service health, stale accounts) is Phase 2 — see
CLAUDE_CONTEXT.md build order. Until Graph is configured, this degrades to
a "not configured" state rather than erroring, matching the spec's
first-run requirement.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, get_current_user, require
from app.core.db import get_db
from app.core.settings_store import load_settings
from app.templating import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    store = await load_settings(db)
    graph_configured = bool(store.get("graph.tenant_id") and store.get("graph.client_id"))
    ad_configured = bool(store.get("ad.ldaps_url") and store.get("ad.bind_dn") and store.get("ad.base_dn"))
    return templates.TemplateResponse(
        request,
        "index.html",
        {"user": user, "graph_configured": graph_configured, "ad_configured": ad_configured},
    )


@router.get("/reports", response_class=HTMLResponse)
async def reports_placeholder(
    request: Request,
    user: CurrentUser = Depends(require("reports.view")),
):
    """Real reporting views (license overview, security posture, mailbox
    health, activity trends, service health, stale accounts) are Phase 3 —
    not built yet. This exists so the sidebar link (gated on reports.view,
    same as the real page will be) doesn't 404."""
    return templates.TemplateResponse(request, "reports_not_built.html", {"user": user})


@router.get("/healthz")
async def healthz():
    return {"status": "ok"}
