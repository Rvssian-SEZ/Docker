from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session
from datetime import datetime, timedelta

from core.database import get_db
from core.deps import require_user, template_ctx
from models.models import Ticket, User

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory="templates")


@router.get("", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    role = request.state.role
    if role not in ("tech", "admin"):
        raise HTTPException(403)

    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=7)

    stats = {
        "total_open": db.query(func.count(Ticket.id)).filter(Ticket.status == "open").scalar(),
        "total_in_progress": db.query(func.count(Ticket.id)).filter(Ticket.status == "in_progress").scalar(),
        "total_pending": db.query(func.count(Ticket.id)).filter(Ticket.status == "pending").scalar(),
        "closed_today": db.query(func.count(Ticket.id)).filter(
            Ticket.status.in_(["resolved", "closed"]),
            Ticket.closed_at >= today_start,
        ).scalar(),
        "opened_this_week": db.query(func.count(Ticket.id)).filter(
            Ticket.created_at >= week_start
        ).scalar(),
        "overdue": db.query(func.count(Ticket.id)).filter(
            Ticket.sla_due_at < now,
            Ticket.status.notin_(["resolved", "closed"]),
        ).scalar(),
    }

    recent_tickets = (
        db.query(Ticket)
        .order_by(Ticket.updated_at.desc())
        .limit(15)
        .all()
    )

    overdue_tickets = (
        db.query(Ticket)
        .filter(
            Ticket.sla_due_at < now,
            Ticket.status.notin_(["resolved", "closed"]),
        )
        .order_by(Ticket.sla_due_at)
        .limit(10)
        .all()
    )

    # My queue (if tech)
    my_queue = (
        db.query(Ticket)
        .filter(
            Ticket.assigned_to_id == current_user.id,
            Ticket.status.notin_(["resolved", "closed"]),
        )
        .order_by(Ticket.priority.desc(), Ticket.created_at)
        .all()
    )

    ctx = template_ctx(
        request,
        stats=stats,
        recent_tickets=recent_tickets,
        overdue_tickets=overdue_tickets,
        my_queue=my_queue,
    )
    return templates.TemplateResponse("admin/dashboard.html", ctx)
