"""The six reporting views' data-fetching logic, on top of app/core/graph_client.py.

DELIBERATE v1 SIMPLIFICATION: the spec describes a standalone cron-
triggered `sync.py` writing to a local cache table. This instead queries
Graph live, with a short in-process TTL cache (_CACHE_TTL) so navigating
between report tabs / a page refresh doesn't re-hit Graph every time, but
there's no persisted history and no cron job. Documented here rather than
silently deviating — revisit if report load times or Graph rate limits
become a real problem, or if trend-over-time (not just point-in-time)
becomes a requirement, which live queries can't provide.

The "Detail" Reports API endpoints (mailbox usage, email activity) are
rendered generically (whatever fields Graph returns) rather than with
hardcoded field extraction — safer than guessing at exact schema field
names from memory and silently showing blank columns if wrong.
"""

import time
from datetime import datetime, timezone

from app.core import graph_client
from app.core.graph_client import GraphPermissionError
from app.core.settings_store import SettingsStore

_CACHE_TTL = 300  # 5 minutes
_cache: dict[str, tuple[float, object]] = {}


async def _cached(key: str, fetch):
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < _CACHE_TTL:
        return hit[1]
    value = await fetch()
    _cache[key] = (time.monotonic(), value)
    return value


async def license_overview(store: SettingsStore) -> list[dict]:
    async def fetch():
        body = await graph_client.get(store, "/subscribedSkus")
        rows = []
        for sku in body.get("value", []):
            prepaid = sku.get("prepaidUnits", {})
            rows.append(
                {
                    "sku": sku.get("skuPartNumber", ""),
                    "enabled": prepaid.get("enabled", 0),
                    "consumed": sku.get("consumedUnits", 0),
                    "available": max(prepaid.get("enabled", 0) - sku.get("consumedUnits", 0), 0),
                    "suspended": prepaid.get("suspended", 0),
                    "warning": prepaid.get("warning", 0),
                }
            )
        return sorted(rows, key=lambda r: r["sku"])

    return await _cached("license_overview", fetch)


async def service_health(store: SettingsStore) -> list[dict]:
    async def fetch():
        body = await graph_client.get(store, "/admin/serviceAnnouncement/healthOverviews")
        return sorted(
            [{"service": r.get("service", ""), "status": r.get("status", "unknown")} for r in body.get("value", [])],
            key=lambda r: r["service"],
        )

    return await _cached("service_health", fetch)


async def mailbox_health(store: SettingsStore) -> dict:
    async def fetch():
        rows = await graph_client.get_report_csv(store, "/reports/getMailboxUsageDetail(period='D7')")
        return {"columns": _columns(rows), "rows": rows}

    return await _cached("mailbox_health", fetch)


async def activity_trends(store: SettingsStore) -> dict:
    async def fetch():
        rows = await graph_client.get_report_csv(store, "/reports/getEmailActivityCounts(period='D7')")
        return {"columns": _columns(rows), "rows": rows}

    return await _cached("activity_trends", fetch)


def _columns(rows: list[dict]) -> list[str]:
    seen: dict[str, None] = {}
    for row in rows[:5]:  # first few rows is enough to establish the column set
        for k in row:
            if not k.startswith("@"):
                seen[k] = None
    return list(seen)


async def risky_users(store: SettingsStore) -> list[dict]:
    async def fetch():
        rows = await graph_client.get_all_pages(store, "/identityProtection/riskyUsers")
        return [
            {
                "user": r.get("userPrincipalName", ""),
                "riskLevel": r.get("riskLevel", ""),
                "riskState": r.get("riskState", ""),
                "riskLastUpdated": r.get("riskLastUpdatedDateTime", ""),
            }
            for r in rows
        ]

    return await _cached("risky_users", fetch)


async def guest_accounts(store: SettingsStore) -> list[dict]:
    async def fetch():
        rows = await graph_client.get_all_pages(
            store,
            "/users",
            params={"$filter": "userType eq 'Guest'", "$select": "displayName,mail,createdDateTime"},
        )
        now = datetime.now(timezone.utc)
        out = []
        for r in rows:
            created = r.get("createdDateTime")
            age_days = None
            if created:
                try:
                    age_days = (now - datetime.fromisoformat(created.replace("Z", "+00:00"))).days
                except ValueError:
                    age_days = None
            out.append({"name": r.get("displayName", ""), "mail": r.get("mail", ""), "age_days": age_days})
        return sorted(out, key=lambda r: r["age_days"] or 0, reverse=True)

    return await _cached("guest_accounts", fetch)


async def mfa_registration(store: SettingsStore) -> dict:
    """Raises GraphPermissionError until UserAuthenticationMethod.Read.All
    (or AuditLog.Read.All, depending on tenant config) is actually
    reflected in issued tokens — see CLAUDE_CONTEXT.md, this can lag
    admin consent by minutes to an hour."""

    async def fetch():
        rows = await graph_client.get_all_pages(store, "/reports/authenticationMethods/userRegistrationDetails")
        total = len(rows)
        registered = sum(1 for r in rows if r.get("isMfaRegistered"))
        return {"total": total, "registered": registered, "pct": round(100 * registered / total, 1) if total else 0.0}

    return await _cached("mfa_registration", fetch)


async def stale_accounts(store: SettingsStore) -> list[dict]:
    """Same permission caveat as mfa_registration — signInActivity needs
    AuditLog.Read.All."""

    async def fetch():
        rows = await graph_client.get_all_pages(
            store, "/users", params={"$select": "displayName,userPrincipalName,signInActivity"}
        )
        now = datetime.now(timezone.utc)
        out = []
        for r in rows:
            activity = r.get("signInActivity") or {}
            last = activity.get("lastSignInDateTime")
            days = None
            if last:
                try:
                    days = (now - datetime.fromisoformat(last.replace("Z", "+00:00"))).days
                except ValueError:
                    days = None
            if days is not None and days >= 30:
                out.append({"user": r.get("userPrincipalName", ""), "days_since_signin": days})
        return sorted(out, key=lambda r: r["days_since_signin"], reverse=True)

    return await _cached("stale_accounts", fetch)
