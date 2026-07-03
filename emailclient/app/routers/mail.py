from fastapi import APIRouter, Request, Depends, Query, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from core.config import settings
from core.deps import require_user
import core.imap as imap_svc

router = APIRouter()
templates = Jinja2Templates(directory="templates")


def _resolve_mailbox(mailbox: str | None) -> str | None:
    users = settings.mailbox_users
    if not mailbox:
        return users[0] if users else None
    return mailbox if mailbox in users else None


def _all_stats() -> dict[str, dict]:
    stats = {}
    for u in settings.mailbox_users:
        try:
            stats[u] = imap_svc.get_stats(u)
        except Exception:
            stats[u] = {"total": 0, "unread": 0}
    return stats


# ── Inbox ─────────────────────────────────────────────────────────────────────

@router.get("/mail")
async def inbox(
    request: Request,
    user: dict     = Depends(require_user),
    mailbox: str   = Query(default=""),
    q: str         = Query(default=""),
    unread_only: str  = Query(default=""),
    msg_type: str  = Query(default=""),
):
    selected = _resolve_mailbox(mailbox or None)
    if not selected:
        return RedirectResponse(url="/mail")

    try:
        messages   = imap_svc.list_messages(
            selected,
            unread_only=unread_only == "true",
            search_q=q,
            msg_type=msg_type,
        )
        imap_error = None
    except Exception as exc:
        messages   = []
        imap_error = str(exc)

    # HTMX partial — list only
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request, "mail/_list.html", {
            "messages":   messages,
            "selected":   selected,
            "q":          q,
            "unread_only": unread_only,
            "msg_type":   msg_type,
            "imap_error": imap_error,
        })

    return templates.TemplateResponse(request, "mail/inbox.html", {
        "user":          user,
        "mailbox_users": settings.mailbox_users,
        "selected":      selected,
        "messages":      messages,
        "stats":         _all_stats(),
        "q":             q,
        "unread_only":   unread_only,
        "msg_type":      msg_type,
        "imap_error":    imap_error,
    })


# ── Message detail ────────────────────────────────────────────────────────────

@router.get("/mail/{uid}")
async def message_detail(
    uid: int,
    request: Request,
    user: dict   = Depends(require_user),
    mailbox: str = Query(default=""),
):
    selected = _resolve_mailbox(mailbox or None)
    if not selected:
        return RedirectResponse(url="/mail")

    try:
        msg        = imap_svc.get_message(selected, uid)
        imap_error = None
    except Exception as exc:
        msg        = None
        imap_error = str(exc)

    return templates.TemplateResponse(request, "mail/message.html", {
        "user":          user,
        "mailbox_users": settings.mailbox_users,
        "selected":      selected,
        "msg":           msg,
        "stats":         _all_stats(),
        "imap_error":    imap_error,
    })


# ── Actions ───────────────────────────────────────────────────────────────────

@router.post("/mail/{uid}/unseen")
async def mark_unseen(
    uid: int,
    request: Request,
    user: dict   = Depends(require_user),
    mailbox: str = Form(default=""),
):
    selected = _resolve_mailbox(mailbox or None)
    if selected:
        try:
            imap_svc.mark_unseen(selected, uid)
        except Exception:
            pass
    return RedirectResponse(url=f"/mail?mailbox={selected}", status_code=303)


@router.post("/mail/{uid}/delete")
async def delete_message(
    uid: int,
    request: Request,
    user: dict   = Depends(require_user),
    mailbox: str = Form(default=""),
):
    selected = _resolve_mailbox(mailbox or None)
    if selected:
        try:
            imap_svc.delete_message(selected, uid)
        except Exception:
            pass
    return RedirectResponse(url=f"/mail?mailbox={selected}", status_code=303)
