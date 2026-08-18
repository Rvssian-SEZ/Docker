"""The six reporting views (spec's original scope): license overview,
security posture (MFA %, risky sign-ins, legacy auth, guest age), mailbox
health, activity trends, service health, stale accounts. Each section
fails independently — a Graph permission gap or transient error in one
report never takes down the rest of the page (see app/core/reports.py's
GraphPermissionError handling).
"""

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import reports as reports_core
from app.core.auth import CurrentUser, require, require_all
from app.core.csv_export import csv_response
from app.core.db import get_db
from app.core.graph_client import GraphError, GraphPermissionError
from app.core.settings_store import load_settings
from app.templating import templates

logger = logging.getLogger(__name__)
router = APIRouter()


async def _section(coro):
    """Runs one report's fetch; turns a Graph failure into a status the
    template can render inline instead of raising and breaking the page."""
    try:
        return {"ok": True, "data": await coro}
    except GraphPermissionError as exc:
        return {"ok": False, "missing_permission": True, "error": str(exc)}
    except GraphError as exc:
        return {"ok": False, "missing_permission": False, "error": str(exc)}


@router.get("/reports", response_class=HTMLResponse)
async def reports_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require("reports.view")),
):
    store = await load_settings(db)
    if not (store.get("graph.tenant_id") and store.get("graph.client_id")):
        return templates.TemplateResponse(request, "reports/not_configured.html", {"user": user})

    sections = {
        "licenses": await _section(reports_core.license_overview(store)),
        "service_health": await _section(reports_core.service_health(store)),
        "mailbox_health": await _section(reports_core.mailbox_health(store)),
        "activity_trends": await _section(reports_core.activity_trends(store)),
        "risky_users": await _section(reports_core.risky_users(store)),
        "guest_accounts": await _section(reports_core.guest_accounts(store)),
        "mfa_registration": await _section(reports_core.mfa_registration(store)),
        "stale_accounts": await _section(reports_core.stale_accounts(store)),
    }
    return templates.TemplateResponse(request, "reports/index.html", {"user": user, "s": sections})


async def _mailbox_rows(store):
    return (await reports_core.mailbox_health(store))["rows"]


async def _activity_rows(store):
    return (await reports_core.activity_trends(store))["rows"]


_EXPORTERS = {
    "licenses": (reports_core.license_overview, "licenses.csv"),
    "risky_users": (reports_core.risky_users, "risky_users.csv"),
    "guest_accounts": (reports_core.guest_accounts, "guest_accounts.csv"),
    "stale_accounts": (reports_core.stale_accounts, "stale_accounts.csv"),
    "mailbox_health": (_mailbox_rows, "mailbox_health.csv"),
    "activity_trends": (_activity_rows, "activity_trends.csv"),
}


@router.get("/reports/export/{key}")
async def export_report(
    key: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_all("reports.view", "reports.export")),
):
    """Exports exactly what the report shows — never LAPS/secret data (none
    of these reports carry any), matching the spec's "export is a
    reporting feature, not an admin-action feature" rule."""
    entry = _EXPORTERS.get(key)
    if entry is None:
        return HTMLResponse("Unknown report.", status_code=404)
    fetch, filename = entry
    store = await load_settings(db)
    try:
        rows = await fetch(store)
    except GraphError as exc:
        return HTMLResponse(f"Export failed: {exc}", status_code=502)
    return csv_response(rows, filename=filename)
