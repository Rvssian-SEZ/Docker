"""Audit trail viewer — filter by actor, action, target type/id, and date
range. Plain GET query-string filtering (not HTMX) so results are
bookmarkable/shareable, same reasoning itops2 used for its list filter bars.
Gated by audit.view, distinct from settings.manage — viewing the trail
doesn't require the ability to change configuration.
"""

import csv
import io
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response

from app.core.audit import distinct_actions, distinct_actors, query_audit
from app.core.auth import CurrentUser, require
from app.templating import templates

router = APIRouter()

# CSV export is deliberately allowed far more rows than the 200 shown on
# the page itself (the whole point of exporting is to get more than one
# screenful for compliance/archival purposes) — this is a safety ceiling
# against an unbounded query on an ever-growing table, not an expected
# real-world result size for this forest.
_EXPORT_LIMIT = 50_000


def _parse_date(value: str | None, *, end_of_day: bool = False) -> datetime | None:
    if not value:
        return None
    try:
        d = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return d + timedelta(days=1, microseconds=-1) if end_of_day else d


@router.get("/audit", response_class=HTMLResponse)
async def audit_list(
    request: Request,
    actor: str | None = None,
    action: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    since: str | None = None,
    until: str | None = None,
    user: CurrentUser = Depends(require("audit.view")),
):
    rows = await query_audit(
        actor_username=actor or None,
        action=action or None,
        target_type=target_type or None,
        target_id=target_id or None,
        since=_parse_date(since),
        until=_parse_date(until, end_of_day=True),
        limit=200,
    )
    return templates.TemplateResponse(
        request,
        "audit_log/list.html",
        {
            "user": user,
            "rows": rows,
            "actors": await distinct_actors(),
            "actions": await distinct_actions(),
            "filters": {
                "actor": actor or "",
                "action": action or "",
                "target_type": target_type or "",
                "target_id": target_id or "",
                "since": since or "",
                "until": until or "",
            },
        },
    )


@router.get("/audit/export.csv")
async def audit_export_csv(
    actor: str | None = None,
    action: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    since: str | None = None,
    until: str | None = None,
    user: CurrentUser = Depends(require("audit.view")),
):
    """Same filters as the /audit list, exported as CSV — gated on
    audit.view (not a separate export permission) since it reveals
    nothing beyond what the filtered list view already shows, just more
    rows and a downloadable format."""
    rows = await query_audit(
        actor_username=actor or None,
        action=action or None,
        target_type=target_type or None,
        target_id=target_id or None,
        since=_parse_date(since),
        until=_parse_date(until, end_of_day=True),
        limit=_EXPORT_LIMIT,
    )
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["When (UTC)", "Actor", "Actor source", "Role", "Action", "Target type", "Target ID", "Reason", "Detail", "Source IP"])
    for r in rows:
        writer.writerow([
            r.at.isoformat(),
            r.actor_username,
            r.actor_source,
            r.actor_role,
            r.action,
            r.target_type,
            r.target_id or "",
            r.reason or "",
            r.detail or "",
            r.source_ip or "",
        ])
    # UTF-8 BOM so Excel on Windows (this app's actual audience) reads the
    # file correctly instead of mis-detecting the encoding — same reasoning
    # graph_client.py documents for the CSVs it reads from Microsoft.
    csv_bytes = ("﻿" + buf.getvalue()).encode("utf-8")
    filename = f"audit_log_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.csv"
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
