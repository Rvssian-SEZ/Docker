"""Audit trail viewer — filter by actor, action, target type/id, and date
range. Plain GET query-string filtering (not HTMX) so results are
bookmarkable/shareable, same reasoning itops2 used for its list filter bars.
Gated by audit.view, distinct from settings.manage — viewing the trail
doesn't require the ability to change configuration.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.core.audit import distinct_actions, distinct_actors, query_audit
from app.core.auth import CurrentUser, require
from app.templating import templates

router = APIRouter()


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
