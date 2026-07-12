"""Settings pages.

Phase 2 ships: General tab (site name, currency, asset tag format, company
toggles, depreciation/warranty policy) + About (versions).
Phase 3 adds: Authentication, Permissions grid. Phase 8: Notifications/SMTP.

HTMX pattern (the 'saves feel instant' requirement):
- the form posts via hx-post and swaps only a small toast target,
  never the whole page.
"""

from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, require
from app.core.db import get_db
from app.core.models import AuditLog
from app.core.settings_store import DEFAULTS, load_settings, save_setting
from app.templating import templates
from app.version import __version__

router = APIRouter(prefix="/settings")

# Keys editable on the General tab, in display order.
GENERAL_KEYS = [
    "general.site_name",
    "general.default_currency",
    "asset_tag.prefix",
    "asset_tag.pad",
    "company.multi_enabled",
    "company.scoped_users",
    "depreciation.default_months",
    "warranty.alert_days",
]

LABELS = {
    "general.site_name": ("Site name", "Shown in the sidebar and page titles"),
    "general.default_currency": ("Default currency", "ISO code, e.g. SCR, USD, GBP"),
    "asset_tag.prefix": ("Asset tag prefix", "e.g. IT- produces IT-0001"),
    "asset_tag.pad": ("Asset tag number padding", "Digits in the numeric part"),
    "company.multi_enabled": ("Enable multi-company", "Adds a Companies section and company fields"),
    "company.scoped_users": ("Scope users to their company", "Users only see their own company's data"),
    "depreciation.default_months": ("Default depreciation period (months)", "Used when a model has no override"),
    "warranty.alert_days": ("Warranty alert lead time (days)", "Notify this many days before expiry"),
}


def schema_version() -> str:
    try:
        cfg = AlembicConfig("alembic.ini")
        return ScriptDirectory.from_config(cfg).get_current_head() or "unknown"
    except Exception:
        return "unknown"


@router.get("", response_class=HTMLResponse)
async def settings_general(
    request: Request,
    user: CurrentUser = Depends(require("settings.manage")),
    db: AsyncSession = Depends(get_db),
):
    store = await load_settings(db)
    fields = [
        {
            "key": k,
            "label": LABELS[k][0],
            "help": LABELS[k][1],
            "type": DEFAULTS[k][1],
            "value": store.get(k),
        }
        for k in GENERAL_KEYS
    ]
    return templates.TemplateResponse(
        request,
        "settings/general.html",
        {"user": user, "fields": fields, "active_tab": "general"},
    )


@router.post("/general", response_class=HTMLResponse)
async def settings_general_save(
    request: Request,
    user: CurrentUser = Depends(require("settings.manage")),
    db: AsyncSession = Depends(get_db),
):
    form = await request.form()
    for key in GENERAL_KEYS:
        kind = DEFAULTS[key][1]
        if kind == "bool":
            # checkboxes: absent when unchecked
            value = "true" if form.get(key) == "true" else "false"
        else:
            value = str(form.get(key, "")).strip()
            if kind == "int" and not value.isdigit():
                return templates.TemplateResponse(
                    request,
                    "partials/toast.html",
                    {"ok": False, "message": f"{LABELS[key][0]} must be a number."},
                )
        await save_setting(db, key, value)
    db.add(AuditLog(user_id=user.id, action="update", entity_type="settings", detail="general"))
    await db.commit()
    return templates.TemplateResponse(
        request, "partials/toast.html", {"ok": True, "message": "Settings saved."}
    )


@router.get("/about", response_class=HTMLResponse)
async def settings_about(
    request: Request,
    user: CurrentUser = Depends(require("settings.manage")),
):
    return templates.TemplateResponse(
        request,
        "settings/about.html",
        {
            "user": user,
            "active_tab": "about",
            "app_ver": __version__,
            "schema_ver": schema_version(),
        },
    )
