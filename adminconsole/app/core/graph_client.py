"""Microsoft Graph client: client-credentials token acquisition (cached
per-process until near expiry), `@odata.nextLink` pagination, and
429/Retry-After backoff — the spec's explicit Graph handling requirements.

Permissions actually granted to this tenant's app registration were
confirmed live (2026-08-18) via its own appRoleAssignments, not assumed:
Directory.Read.All, User.Read.All, IdentityRiskyUser.Read.All,
ServiceHealth.Read.All, Reports.Read.All. AuditLog.Read.All and
UserAuthenticationMethod.Read.All are NOT granted — calls needing those
(stale-accounts sign-in data, MFA registration %) get a
GraphPermissionError, which callers turn into a "missing permission"
state in the UI rather than a crash, same convention as every other
not-yet-configured feature in this app.
"""

import asyncio
import logging
import time

import httpx

from app.core.settings_store import SettingsStore

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

# Cached across requests within this process — a client-credentials token
# is tenant/app-wide, not per-user, so there's nothing request-scoped to
# key it on. Refreshed with a safety margin before actual expiry.
_token_cache: dict[str, tuple[str, float]] = {}


class GraphError(Exception):
    """User-presentable Graph API failure."""


class GraphPermissionError(GraphError):
    """The app registration lacks a permission this call needs — a known,
    named gap (see module docstring), not an unexpected failure. Callers
    render this as a distinct "missing permission" state."""


class GraphLicenseError(GraphError):
    """The tenant itself lacks the M365/Entra license tier a call needs
    (e.g. Azure AD Premium for signInActivity/userRegistrationDetails,
    Premium P2 for Identity Protection/riskyUsers) — confirmed live via
    Authentication_RequestFromNonPremiumTenantOrB2CTenant and a similar
    "not licensed for this feature" 403. No permission grant fixes this;
    it's a distinct state from GraphPermissionError so the UI doesn't
    imply "go consent a scope" for something consent can't solve."""


async def _get_token(store: SettingsStore) -> str:
    tenant_id = store.get("graph.tenant_id")
    client_id = store.get("graph.client_id")
    client_secret = store.get_secret("graph.client_secret")
    if not (tenant_id and client_id and client_secret):
        raise GraphError("Graph is not configured (Settings -> Graph App Registration).")

    cached = _token_cache.get(client_id)
    if cached and cached[1] - 60 > time.monotonic():
        return cached[0]

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": "https://graph.microsoft.com/.default",
                "grant_type": "client_credentials",
            },
        )
    if resp.status_code != 200:
        logger.warning("Graph token request failed: %s %s", resp.status_code, resp.text[:300])
        raise GraphError("Graph token request failed — check the tenant/client ID and secret.")
    body = resp.json()
    token = body["access_token"]
    _token_cache[client_id] = (token, time.monotonic() + body.get("expires_in", 3600))
    return token


async def get(store: SettingsStore, path_or_url: str, *, params: dict | None = None) -> dict:
    """Single-request GET. `path_or_url` may be a path under GRAPH_BASE
    (e.g. "/subscribedSkus") or a full URL (a `@odata.nextLink`, or one of
    the Reports API endpoints that redirects to a signed CSV/JSON blob
    URL — httpx follows that redirect automatically)."""
    token = await _get_token(store)
    url = path_or_url if path_or_url.startswith("http") else f"{GRAPH_BASE}{path_or_url}"
    return await _request(token, url, params)


async def get_all_pages(store: SettingsStore, path: str, *, params: dict | None = None, max_pages: int = 50) -> list[dict]:
    """Follows `@odata.nextLink` until exhausted or max_pages is hit (a
    hard ceiling so a misbehaving query can't loop forever — 50 pages at
    Graph's typical 100-999/page default is 5k-50k objects, comfortably
    more than this tenant needs for any of the six report views)."""
    token = await _get_token(store)
    url = f"{GRAPH_BASE}{path}"
    items: list[dict] = []
    for _ in range(max_pages):
        body = await _request(token, url, params)
        items.extend(body.get("value", []))
        next_link = body.get("@odata.nextLink")
        if not next_link:
            break
        url, params = next_link, None  # nextLink already carries the full query string
    return items


async def get_report_csv(store: SettingsStore, path: str) -> list[dict]:
    """The classic Reports API "Detail"/"Counts" endpoints only return
    CSV — confirmed live that `$format=application/json` on these
    specific endpoints 400s with "JSON format is not supported" (unlike
    some other Graph report endpoints where that param does work, so this
    is deliberately a separate function rather than a flag on get()).
    Follows the endpoint's 302 to the signed blob URL same as get()."""
    token = await _get_token(store)
    url = f"{GRAPH_BASE}{path}"
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(url, headers=headers)
    if resp.status_code == 403:
        try:
            body = resp.json().get("error", {})
        except Exception:
            body = {}
        code, message = body.get("code", ""), body.get("message", "")
        if code == "Authentication_MSGraphPermissionMissing":
            raise GraphPermissionError(f"Missing Graph permission for {path.split('(')[0]}.")
        if code == "Authentication_RequestFromNonPremiumTenantOrB2CTenant" or "not licensed for this feature" in message:
            raise GraphLicenseError(f"Requires an Azure AD Premium license this tenant doesn't have ({message or code}).")
        raise GraphError(f"Graph report request forbidden: {resp.text[:200]}")
    if resp.status_code >= 400:
        raise GraphError(f"Graph report request failed ({resp.status_code}): {resp.text[:200]}")
    import csv
    import io

    # Confirmed live: these CSVs are UTF-8-BOM'd, which otherwise ends up
    # glued onto the first column's name (e.g. "﻿Report Refresh Date").
    reader = csv.DictReader(io.StringIO(resp.text.lstrip("﻿")))
    return list(reader)


async def _request(token: str, url: str, params: dict | None) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    # follow_redirects: the classic Reports API endpoints (getMailboxUsageDetail,
    # getEmailActivityCounts, etc.) respond 302 to a signed blob URL for the
    # actual data — confirmed live (a raw httpx.get without this returned the
    # 302 itself, not the report). Report callers also append
    # $format=application/json to those URLs so the blob is JSON, not CSV.
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for attempt in range(5):
            resp = await client.get(url, headers=headers, params=params)
            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", 2 * (attempt + 1)))
                logger.info("Graph 429 — backing off %.1fs (attempt %d)", retry_after, attempt + 1)
                await asyncio.sleep(retry_after)
                continue
            if resp.status_code == 403:
                try:
                    body = resp.json().get("error", {})
                except Exception:
                    body = {}
                code = body.get("code", "")
                message = body.get("message", "")
                if code == "Authentication_MSGraphPermissionMissing":
                    raise GraphPermissionError(f"Missing Graph permission for {url.split('?')[0]}.")
                if code == "Authentication_RequestFromNonPremiumTenantOrB2CTenant" or "not licensed for this feature" in message:
                    raise GraphLicenseError(f"Requires an Azure AD Premium license this tenant doesn't have ({message or code}).")
                raise GraphError(f"Graph request forbidden: {resp.text[:200]}")
            if resp.status_code >= 400:
                raise GraphError(f"Graph request failed ({resp.status_code}): {resp.text[:200]}")
            return resp.json()
    raise GraphError("Graph request failed after repeated 429 rate-limiting.")
