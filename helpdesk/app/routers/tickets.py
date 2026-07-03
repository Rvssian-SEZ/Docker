from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from core.database import get_db
from core.deps import require_user, template_ctx
from core.config import get_settings
from core import email as mail
from models.models import Ticket, TicketUpdate, User, ITAsset, TICKET_CATEGORIES

router = APIRouter(prefix="/tickets", tags=["tickets"])
templates = Jinja2Templates(directory="templates")
settings = get_settings()

# SLA hours map
SLA_HOURS = {
    "critical": settings.sla_critical_hours,
    "high": settings.sla_high_hours,
    "medium": settings.sla_medium_hours,
    "low": settings.sla_low_hours,
}


def _sla_due(priority: str) -> datetime:
    return datetime.utcnow() + timedelta(hours=SLA_HOURS.get(priority, 72))


def _tech_emails(db: Session) -> list[str]:
    """Return emails of all active techs/admins."""
    techs = db.query(User).filter(
        User.is_active == True,
        User.groups.like(f"%{settings.helpdesk_tech_group}%"),
    ).all()
    admins = db.query(User).filter(
        User.is_active == True,
        User.groups.like(f"%{settings.helpdesk_admin_group}%"),
    ).all()
    emails = {u.email for u in techs + admins}
    if settings.helpdesk_admin_email:
        for e in settings.helpdesk_admin_email.split(","):
            emails.add(e.strip())
    return [e for e in emails if e]


# ─── Ticket list ──────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
async def ticket_list(
    request: Request,
    status: str = "",
    priority: str = "",
    category: str = "",
    assigned_to: str = "",
    search: str = "",
    page: int = 1,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    role = request.state.role
    q = db.query(Ticket)

    # Users see only their own tickets
    if role == "user":
        q = q.filter(Ticket.created_by_id == current_user.id)

    if status:
        q = q.filter(Ticket.status == status)
    if priority:
        q = q.filter(Ticket.priority == priority)
    if category:
        q = q.filter(Ticket.category == category)
    if assigned_to == "me":
        q = q.filter(Ticket.assigned_to_id == current_user.id)
    elif assigned_to == "unassigned":
        q = q.filter(Ticket.assigned_to_id == None)
    if search:
        q = q.filter(
            Ticket.title.ilike(f"%{search}%") |
            Ticket.description.ilike(f"%{search}%")
        )

    total = q.count()
    per_page = 25
    tickets = (
        q.order_by(Ticket.updated_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    # Summary stats for top cards
    stats = {
        "open": db.query(func.count(Ticket.id)).filter(Ticket.status == "open").scalar(),
        "in_progress": db.query(func.count(Ticket.id)).filter(Ticket.status == "in_progress").scalar(),
        "pending": db.query(func.count(Ticket.id)).filter(Ticket.status == "pending").scalar(),
        "resolved_today": db.query(func.count(Ticket.id)).filter(
            Ticket.status.in_(["resolved", "closed"]),
            Ticket.closed_at >= datetime.utcnow().replace(hour=0, minute=0, second=0),
        ).scalar(),
    }

    techs = []
    if role in ("tech", "admin"):
        techs = db.query(User).filter(
            User.is_active == True,
            User.groups.op("~*")(f"({settings.helpdesk_tech_group}|{settings.helpdesk_admin_group})"),
        ).all()

    ctx = template_ctx(
        request,
        tickets=tickets,
        stats=stats,
        categories=TICKET_CATEGORIES,
        techs=techs,
        total=total,
        page=page,
        per_page=per_page,
        pages=(total + per_page - 1) // per_page,
        filters=dict(status=status, priority=priority, category=category, assigned_to=assigned_to, search=search),
    )
    return templates.TemplateResponse("tickets/list.html", ctx)


# ─── Ticket create ────────────────────────────────────────────────────────────

@router.get("/new", response_class=HTMLResponse)
async def ticket_new(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    role = request.state.role
    # Users see only their own assets; techs can pick any user
    if role == "user":
        assets = db.query(ITAsset).filter(
            ITAsset.assigned_user_id == current_user.id,
            
        ).all()
        users = [current_user]
    else:
        assets = db.query(ITAsset).filter(ITAsset.assigned_user_id == current_user.id).all()
        users = db.query(User).filter(User.is_active == True).order_by(User.full_name).all()

    ctx = template_ctx(
        request,
        categories=TICKET_CATEGORIES,
        assets=assets,
        users=users,
    )
    return templates.TemplateResponse("tickets/create.html", ctx)


@router.post("", response_class=HTMLResponse)
async def ticket_create(
    request: Request,
    background_tasks: BackgroundTasks,
    title: str = Form(...),
    description: str = Form(...),
    priority: str = Form("medium"),
    category: str = Form(None),
    asset_id: str = Form(default=""),
    on_behalf_of: str = Form(default=""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    role = request.state.role

    # Determine who the ticket is for
    requester_id = current_user.id
    if role in ("tech", "admin") and on_behalf_of:
        requester_id = int(on_behalf_of)

    ticket = Ticket(
        title=title.strip(),
        description=description.strip(),
        priority=priority,
        category=category or None,
        status="open",
        created_by_id=requester_id,
        assigned_to_id=None,
        asset_id=int(asset_id) if asset_id else None,
        sla_due_at=_sla_due(priority),
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)

    requester = db.query(User).get(requester_id)
    background_tasks.add_task(
        mail.notify_ticket_created,
        ticket, requester, None, _tech_emails(db),
    )

    return RedirectResponse(f"/tickets/{ticket.id}", status_code=303)


# ─── HTMX: user devices ───────────────────────────────────────────────────────

@router.get("/htmx/user-assets/{user_id}", response_class=HTMLResponse)
async def htmx_user_assets(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    role = request.state.role
    if role not in ("tech", "admin"):
        raise HTTPException(403)
    assets = db.query(ITAsset).filter(
        ITAsset.assigned_user_id == user_id,
    ).all()
    return templates.TemplateResponse(
        "partials/asset_options.html",
        {"request": request, "assets": assets},
    )


# ─── Ticket detail ────────────────────────────────────────────────────────────

@router.get("/{ticket_id}", response_class=HTMLResponse)
async def ticket_detail(
    ticket_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    role = request.state.role
    if role == "user" and ticket.created_by_id != current_user.id:
        raise HTTPException(403, "Access denied")

    # Requester info
    requester = ticket.created_by
    ticket_count = db.query(func.count(Ticket.id)).filter(
        Ticket.created_by_id == requester.id
    ).scalar()

    # User's devices
    user_assets = db.query(ITAsset).filter(
        ITAsset.assigned_user_id == requester.id
    ).all()

    # Techs for assignment dropdown
    techs = []
    if role in ("tech", "admin"):
        techs = db.query(User).filter(
            User.is_active == True,
            User.groups.op("~*")(f"({settings.helpdesk_tech_group}|{settings.helpdesk_admin_group})"),
        ).all()

    # Filter updates: users see only non-internal
    updates = [
        u for u in ticket.updates
        if role in ("tech", "admin") or not u.is_internal
    ]

    ctx = template_ctx(
        request,
        ticket=ticket,
        updates=updates,
        requester=requester,
        ticket_count=ticket_count,
        user_assets=user_assets,
        techs=techs,
        categories=TICKET_CATEGORIES,
    )
    return templates.TemplateResponse("tickets/detail.html", ctx)


# ─── Add update ───────────────────────────────────────────────────────────────

@router.post("/{ticket_id}/update")
async def ticket_add_update(
    ticket_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    content: str = Form(...),
    is_internal: bool = Form(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(404)

    role = request.state.role
    if role == "user":
        if ticket.created_by_id != current_user.id:
            raise HTTPException(403)
        is_internal = False  # users cannot post internal notes

    update = TicketUpdate(
        ticket_id=ticket.id,
        author_id=current_user.id,
        content=content.strip(),
        is_internal=is_internal,
    )
    db.add(update)
    ticket.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(update)

    background_tasks.add_task(
        mail.notify_ticket_updated,
        ticket, update, current_user,
        ticket.created_by.email,
        ticket.assigned_to,
    )

    return RedirectResponse(f"/tickets/{ticket_id}", status_code=303)


# ─── Status change ────────────────────────────────────────────────────────────

@router.post("/{ticket_id}/status")
async def ticket_change_status(
    ticket_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    new_status: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    role = request.state.role
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(404)

    # Users can only reopen (closed → open)
    if role == "user":
        if not (ticket.status in ("resolved", "closed") and new_status == "open"):
            raise HTTPException(403, "Users can only reopen tickets")

    old_status = ticket.status
    ticket.status = new_status
    ticket.updated_at = datetime.utcnow()

    if new_status in ("resolved", "closed") and not ticket.closed_at:
        ticket.closed_at = datetime.utcnow()
    elif new_status not in ("resolved", "closed"):
        ticket.closed_at = None

    db.commit()

    if new_status in ("resolved", "closed"):
        background_tasks.add_task(
            mail.notify_ticket_closed,
            ticket, current_user, ticket.created_by.email,
        )
    else:
        background_tasks.add_task(
            mail.notify_status_changed,
            ticket, current_user, old_status,
            ticket.assigned_to, ticket.created_by.email,
        )

    return RedirectResponse(f"/tickets/{ticket_id}", status_code=303)


# ─── Assign ticket ────────────────────────────────────────────────────────────

@router.post("/{ticket_id}/assign")
async def ticket_assign(
    ticket_id: int,
    request: Request,
    tech_id: int = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    role = request.state.role
    if role not in ("tech", "admin"):
        raise HTTPException(403)

    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(404)

    ticket.assigned_to_id = tech_id or None
    ticket.updated_at = datetime.utcnow()
    if ticket.status == "open" and tech_id:
        ticket.status = "in_progress"
    db.commit()

    return RedirectResponse(f"/tickets/{ticket_id}", status_code=303)
