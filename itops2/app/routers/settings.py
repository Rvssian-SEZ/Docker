"""Settings pages.

Phase 2 ships: General tab (site name, currency, asset tag format, company
toggles, depreciation/warranty policy) + About (versions).
Phase 3 adds: Authentication, Permissions grid. Phase 8: Notifications/SMTP.

HTMX pattern (the 'saves feel instant' requirement):
- the form posts via hx-post and swaps only a small toast target,
  never the whole page.
"""

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser, require
from app.core.db import get_db
from app.core.models import AuditLog, Currency, ExchangeRate
from app.core.notifications import SMTP_SECURITY_MODES, send_email_raising
from app.core.settings_store import DEFAULTS, load_settings, save_setting
from app.templating import templates
from app.version import __version__

router = APIRouter(prefix="/settings")

CURRENCY_CODE_RE = re.compile(r"^[A-Z]{3}$")

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
    "contracts.renewal_alert_days",
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
    "contracts.renewal_alert_days": (
        "Contract renewal alert lead time (days)", "Flag contracts as 'expiring soon' this many days before renewal",
    ),
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


# Keys editable on the Authentication tab (OIDC; LDAP joins later).
AUTH_KEYS = [
    "auth.oidc.enabled",
    "auth.oidc.issuer",
    "auth.oidc.client_id",
    "auth.oidc.client_secret",
    "auth.oidc.button_label",
    "auth.oidc.group_role_map",
    "auth.oidc.default_role",
]

AUTH_LABELS = {
    "auth.oidc.enabled": ("Enable OIDC sign-in", "Shows an SSO button on the login page"),
    "auth.oidc.issuer": ("Issuer URL", "e.g. https://auth.home.internal/application/o/itops2/"),
    "auth.oidc.client_id": ("Client ID", "From the provider's application config"),
    "auth.oidc.client_secret": ("Client secret", "Stored in the database"),
    "auth.oidc.button_label": ("Button label", "Text on the login page SSO button"),
    "auth.oidc.group_role_map": (
        "Group → role map (JSON)",
        'e.g. {"itops-admins": "admin", "it-staff": "technician"}',
    ),
    "auth.oidc.default_role": (
        "Default role",
        "Role when no group matches: admin/manager/technician/viewer, empty = deny",
    ),
}


@router.get("/auth", response_class=HTMLResponse)
async def settings_auth(
    request: Request,
    user: CurrentUser = Depends(require("settings.manage")),
    db: AsyncSession = Depends(get_db),
):
    store = await load_settings(db)
    fields = [
        {
            "key": k,
            "label": AUTH_LABELS[k][0],
            "help": AUTH_LABELS[k][1],
            "type": DEFAULTS[k][1],
            "value": store.get(k),
        }
        for k in AUTH_KEYS
    ]
    redirect_uri = str(request.url_for("oidc_callback"))
    return templates.TemplateResponse(
        request,
        "settings/auth.html",
        {"user": user, "fields": fields, "active_tab": "auth", "redirect_uri": redirect_uri},
    )


@router.post("/auth", response_class=HTMLResponse)
async def settings_auth_save(
    request: Request,
    user: CurrentUser = Depends(require("settings.manage")),
    db: AsyncSession = Depends(get_db),
):
    form = await request.form()
    for key in AUTH_KEYS:
        kind = DEFAULTS[key][1]
        if kind == "bool":
            value = "true" if form.get(key) == "true" else "false"
        else:
            value = str(form.get(key, "")).strip()
        await save_setting(db, key, value)
    db.add(AuditLog(user_id=user.id, action="update", entity_type="settings", detail="auth"))
    await db.commit()
    return templates.TemplateResponse(
        request, "partials/toast.html", {"ok": True, "message": "Authentication settings saved."}
    )


NOTIFICATIONS_KEYS = [
    "smtp.enabled",
    "smtp.host",
    "smtp.port",
    "smtp.security",
    "smtp.auth_mode",
    "smtp.username",
    "smtp.password",
    "smtp.oauth2_tenant_id",
    "smtp.oauth2_client_id",
    "smtp.oauth2_client_secret",
    "smtp.from_address",
]

NOTIFICATIONS_LABELS = {
    "smtp.enabled": ("Enable email notifications", "Master switch — off means nothing is ever sent"),
    "smtp.host": ("SMTP host", "e.g. mail.example.com, or smtp.office365.com for OAuth2"),
    "smtp.port": ("SMTP port", "25 -> None, 587 -> STARTTLS (also OAuth2), 465 -> TLS"),
    "smtp.security": ("Security", "None (port 25), STARTTLS (port 587), or TLS (port 465) — must match the port"),
    "smtp.auth_mode": ("Authentication", "Basic (username/password, or none) or OAuth2 (Microsoft 365)"),
    "smtp.username": ("Username", "Leave blank for an unauthenticated relay"),
    "smtp.password": ("Password", "Leave blank for an unauthenticated relay"),
    "smtp.oauth2_tenant_id": ("Tenant ID", "Entra (Azure AD) directory (tenant) ID"),
    "smtp.oauth2_client_id": ("Client ID", "Application (client) ID of the registered Entra app"),
    "smtp.oauth2_client_secret": ("Client secret", "From the Entra app's Certificates & secrets"),
    "smtp.from_address": ("From address", "e.g. itops2@example.com — for OAuth2 must be the mailbox the app was granted SendAs rights to"),
}

# Rendered as a <select> in settings/notifications.html — value, display label.
SMTP_SECURITY_OPTIONS = [
    ("none", "None (plaintext)"),
    ("starttls", "STARTTLS"),
    ("tls", "TLS"),
]

SMTP_AUTH_MODE_OPTIONS = [
    ("basic", "Basic (username/password)"),
    ("oauth2", "OAuth2 (Microsoft 365)"),
]

# Which of NOTIFICATIONS_KEYS the settings/notifications.html template
# shows for each smtp.auth_mode -- kept here (not duplicated in the
# template) so the "what belongs to which mode" list has one source of
# truth. smtp.enabled/host/port/security/auth_mode/from_address are
# mode-independent and always shown.
SMTP_AUTH_MODE_FIELDS = {
    "basic": ["smtp.username", "smtp.password"],
    "oauth2": ["smtp.oauth2_tenant_id", "smtp.oauth2_client_id", "smtp.oauth2_client_secret"],
}


@router.get("/notifications", response_class=HTMLResponse)
async def settings_notifications(
    request: Request,
    user: CurrentUser = Depends(require("settings.manage")),
    db: AsyncSession = Depends(get_db),
):
    store = await load_settings(db)
    fields = [
        {
            "key": k,
            "label": NOTIFICATIONS_LABELS[k][0],
            "help": NOTIFICATIONS_LABELS[k][1],
            "type": DEFAULTS[k][1],
            "value": store.get(k),
        }
        for k in NOTIFICATIONS_KEYS
    ]
    return templates.TemplateResponse(
        request,
        "settings/notifications.html",
        {
            "user": user,
            "fields": fields,
            "active_tab": "notifications",
            "smtp_security_options": SMTP_SECURITY_OPTIONS,
            "smtp_auth_mode_options": SMTP_AUTH_MODE_OPTIONS,
            "smtp_auth_mode_fields": SMTP_AUTH_MODE_FIELDS,
            "current_auth_mode": store.get("smtp.auth_mode"),
        },
    )


@router.post("/notifications", response_class=HTMLResponse)
async def settings_notifications_save(
    request: Request,
    user: CurrentUser = Depends(require("settings.manage")),
    db: AsyncSession = Depends(get_db),
):
    form = await request.form()
    for key in NOTIFICATIONS_KEYS:
        kind = DEFAULTS[key][1]
        if kind == "bool":
            value = "true" if form.get(key) == "true" else "false"
        else:
            value = str(form.get(key, "")).strip()
            if kind == "int" and not value.isdigit():
                return templates.TemplateResponse(
                    request,
                    "partials/toast.html",
                    {"ok": False, "message": f"{NOTIFICATIONS_LABELS[key][0]} must be a number."},
                )
            if key == "smtp.security" and value not in SMTP_SECURITY_MODES:
                return _toast(request, False, "Security must be None, STARTTLS, or TLS.")
            if key == "smtp.auth_mode" and value not in dict(SMTP_AUTH_MODE_OPTIONS):
                return _toast(request, False, "Authentication must be Basic or OAuth2.")
        await save_setting(db, key, value)
    db.add(AuditLog(user_id=user.id, action="update", entity_type="settings", detail="notifications"))
    await db.commit()
    return templates.TemplateResponse(
        request, "partials/toast.html", {"ok": True, "message": "Notification settings saved."}
    )


@router.post("/notifications/test-send", response_class=HTMLResponse)
async def settings_notifications_test_send(
    request: Request,
    to: str = Form(""),
    user: CurrentUser = Depends(require("settings.manage")),
    db: AsyncSession = Depends(get_db),
):
    to = to.strip()
    if not to:
        return _toast(request, False, "Enter an address to send the test to.")
    try:
        await send_email_raising(to, "ITOps v2 test email", "This is a test email from ITOps v2 — SMTP is working.")
    except Exception as exc:
        return _toast(request, False, f"Send failed: {exc}")
    return _toast(request, True, f"Test email sent to {to}.")


# Keys editable on the Import tab (Phase 9 v1 import wizard config).
IMPORT_KEYS = [
    "import.v1_database_url",
    "import.currency_symbol_map",
    "import.v1_asset_uploads_path",
    "import.v1_printer_uploads_path",
]

IMPORT_LABELS = {
    "import.v1_database_url": (
        "v1 database connection string",
        "postgresql://user:pass@host:port/db — connects strictly read-only",
    ),
    "import.currency_symbol_map": (
        "Currency symbol map (JSON)",
        'e.g. {"$": "USD", "£": "GBP", "€": "EUR", "Rs": "SCR"} — "Rs" only means SCR for THIS deployment',
    ),
    "import.v1_asset_uploads_path": (
        "v1 asset uploads path (in-container)",
        "Path where v1's asset-photo upload volume is read-only bind-mounted — see the setup guide's import section",
    ),
    "import.v1_printer_uploads_path": (
        "v1 printer uploads path (in-container)",
        "Path where v1's printer-attachment upload volume is read-only bind-mounted",
    ),
}


@router.get("/import", response_class=HTMLResponse)
async def settings_import(
    request: Request,
    user: CurrentUser = Depends(require("settings.manage")),
    db: AsyncSession = Depends(get_db),
):
    store = await load_settings(db)
    fields = [
        {
            "key": k,
            "label": IMPORT_LABELS[k][0],
            "help": IMPORT_LABELS[k][1],
            "type": DEFAULTS[k][1],
            "value": store.get(k),
        }
        for k in IMPORT_KEYS
    ]
    return templates.TemplateResponse(
        request,
        "settings/import.html",
        {"user": user, "fields": fields, "active_tab": "import"},
    )


@router.post("/import", response_class=HTMLResponse)
async def settings_import_save(
    request: Request,
    user: CurrentUser = Depends(require("settings.manage")),
    db: AsyncSession = Depends(get_db),
):
    form = await request.form()
    for key in IMPORT_KEYS:
        value = str(form.get(key, "")).strip()
        await save_setting(db, key, value)
    db.add(AuditLog(user_id=user.id, action="update", entity_type="settings", detail="import"))
    await db.commit()
    return templates.TemplateResponse(
        request, "partials/toast.html", {"ok": True, "message": "Import settings saved."}
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


# ---- Currency: currencies + dated exchange rates ----

def _toast(request: Request, ok: bool, message: str):
    return templates.TemplateResponse(request, "partials/toast.html", {"ok": ok, "message": message})


def _refresh():
    return Response(status_code=204, headers={"HX-Refresh": "true"})


@router.get("/currency", response_class=HTMLResponse)
async def settings_currency(
    request: Request,
    user: CurrentUser = Depends(require("settings.manage")),
    db: AsyncSession = Depends(get_db),
):
    currencies = (await db.execute(select(Currency).order_by(Currency.code))).scalars().all()
    rates = (
        (
            await db.execute(
                select(ExchangeRate).order_by(ExchangeRate.effective_date.desc(), ExchangeRate.id.desc())
            )
        )
        .scalars()
        .all()
    )
    store = await load_settings(db)
    return templates.TemplateResponse(
        request,
        "settings/currency.html",
        {
            "user": user,
            "currencies": currencies,
            "rates": rates,
            "default_currency": store.get("general.default_currency"),
            "active_tab": "currency",
        },
    )


@router.post("/currency/create", response_class=HTMLResponse)
async def currency_create(
    request: Request,
    code: str = Form(""),
    symbol: str = Form(""),
    user: CurrentUser = Depends(require("settings.manage")),
    db: AsyncSession = Depends(get_db),
):
    code = code.strip().upper()
    symbol = symbol.strip()
    if not CURRENCY_CODE_RE.match(code):
        return _toast(request, False, "Currency code must be 3 letters (ISO 4217), e.g. SCR.")
    if not symbol:
        return _toast(request, False, "Symbol is required.")
    if await db.get(Currency, code) is not None:
        return _toast(request, False, f"{code} already exists.")
    db.add(Currency(code=code, symbol=symbol, active=True))
    db.add(AuditLog(user_id=user.id, action="create", entity_type="currency", entity_id=code, detail=symbol))
    await db.commit()
    return _refresh()


@router.post("/currency/{code}/toggle", response_class=HTMLResponse)
async def currency_toggle(
    request: Request,
    code: str,
    active: str = Form("false"),
    user: CurrentUser = Depends(require("settings.manage")),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(Currency, code)
    if row is None:
        return _toast(request, False, "Not found.")
    row.active = active == "true"
    db.add(
        AuditLog(
            user_id=user.id, action="update", entity_type="currency", entity_id=code,
            detail=f"active={row.active}",
        )
    )
    await db.commit()
    return _toast(request, True, f"{code} {'enabled' if row.active else 'disabled'}.")


@router.post("/currency/{code}/delete", response_class=HTMLResponse)
async def currency_delete(
    request: Request,
    code: str,
    user: CurrentUser = Depends(require("settings.manage")),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(Currency, code)
    if row is None:
        return _toast(request, False, "Not found.")
    store = await load_settings(db)
    if code == store.get("general.default_currency"):
        return _toast(request, False, "Cannot delete the default currency — change it in General settings first.")
    await db.delete(row)
    db.add(AuditLog(user_id=user.id, action="delete", entity_type="currency", entity_id=code, detail=code))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return _toast(request, False, f"Cannot delete {code}: still in use.")
    return _refresh()


@router.post("/currency/rates/create", response_class=HTMLResponse)
async def exchange_rate_create(
    request: Request,
    from_currency: str = Form(""),
    to_currency: str = Form(""),
    rate: str = Form(""),
    effective_date: str = Form(""),
    user: CurrentUser = Depends(require("settings.manage")),
    db: AsyncSession = Depends(get_db),
):
    from_currency = from_currency.strip().upper()
    to_currency = to_currency.strip().upper()
    if from_currency == to_currency:
        return _toast(request, False, "From and to currency must differ.")
    if await db.get(Currency, from_currency) is None or await db.get(Currency, to_currency) is None:
        return _toast(request, False, "Unknown currency.")
    try:
        rate_val = Decimal(rate.strip())
        if rate_val <= 0:
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        return _toast(request, False, "Rate must be a positive number.")
    try:
        eff_date = date.fromisoformat(effective_date.strip())
    except ValueError:
        return _toast(request, False, "Invalid date.")
    dup = (
        await db.execute(
            select(ExchangeRate.id).where(
                ExchangeRate.from_currency == from_currency,
                ExchangeRate.to_currency == to_currency,
                ExchangeRate.effective_date == eff_date,
            )
        )
    ).first()
    if dup:
        return _toast(request, False, "A rate for this pair and date already exists.")

    row = ExchangeRate(
        from_currency=from_currency, to_currency=to_currency, rate=rate_val, effective_date=eff_date,
    )
    db.add(row)
    await db.flush()
    db.add(
        AuditLog(
            user_id=user.id, action="create", entity_type="exchange_rate", entity_id=str(row.id),
            detail=f"{from_currency}->{to_currency} {rate_val} @ {eff_date}",
        )
    )
    await db.commit()
    return _refresh()


@router.post("/currency/rates/{item_id}/delete", response_class=HTMLResponse)
async def exchange_rate_delete(
    request: Request,
    item_id: int,
    user: CurrentUser = Depends(require("settings.manage")),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(ExchangeRate, item_id)
    if row is None:
        return _toast(request, False, "Not found.")
    detail = f"{row.from_currency}->{row.to_currency} @ {row.effective_date}"
    await db.delete(row)
    db.add(
        AuditLog(
            user_id=user.id, action="delete", entity_type="exchange_rate", entity_id=str(item_id), detail=detail,
        )
    )
    await db.commit()
    return _refresh()
