from datetime import datetime, timedelta, date
from typing import Optional
import json

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, extract, case, and_
from sqlalchemy.orm import Session

from core.database import get_db
from core.deps import require_user, template_ctx
from core.config import get_settings
from models.models import Ticket, TicketUpdate, User

router = APIRouter(prefix="/reports", tags=["reports"])
templates = Jinja2Templates(directory="templates")
settings = get_settings()


def _require_tech(request: Request):
    if request.state.role not in ("tech", "admin"):
        raise HTTPException(403, "Tech or Admin access required")


# ─── KPI page ─────────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
async def reports_index(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    _require_tech(request)
    ctx = template_ctx(request)
    return templates.TemplateResponse("reports/kpi.html", ctx)


# ─── KPI data API ─────────────────────────────────────────────────────────────

@router.get("/data")
async def reports_data(
    request: Request,
    period: str = "monthly",    # monthly | quarterly | yearly
    year: int = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    _require_tech(request)
    now = datetime.utcnow()
    year = year or now.year

    if period == "monthly":
        return _monthly_data(db, year)
    elif period == "quarterly":
        return _quarterly_data(db, year)
    elif period == "yearly":
        return _yearly_data(db)
    else:
        raise HTTPException(400, "period must be monthly, quarterly, or yearly")


def _monthly_data(db: Session, year: int) -> dict:
    months = list(range(1, 13))
    labels = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

    # Opened per month
    opened_rows = db.query(
        extract("month", Ticket.created_at).label("m"),
        func.count(Ticket.id),
    ).filter(extract("year", Ticket.created_at) == year).group_by("m").all()
    opened_map = {int(m): c for m, c in opened_rows}

    # Closed per month
    closed_rows = db.query(
        extract("month", Ticket.closed_at).label("m"),
        func.count(Ticket.id),
    ).filter(
        Ticket.closed_at != None,
        extract("year", Ticket.closed_at) == year,
    ).group_by("m").all()
    closed_map = {int(m): c for m, c in closed_rows}

    # Avg resolution hours per month (closed tickets only)
    res_rows = db.query(
        extract("month", Ticket.closed_at).label("m"),
        func.avg(
            func.extract("epoch", Ticket.closed_at - Ticket.created_at) / 3600
        ),
    ).filter(
        Ticket.closed_at != None,
        extract("year", Ticket.closed_at) == year,
    ).group_by("m").all()
    res_map = {int(m): round(float(v), 1) if v else 0 for m, v in res_rows}

    # SLA compliance per month
    sla_rows = db.query(
        extract("month", Ticket.closed_at).label("m"),
        func.count(Ticket.id),
        func.sum(case((Ticket.closed_at <= Ticket.sla_due_at, 1), else_=0)),
    ).filter(
        Ticket.closed_at != None,
        Ticket.sla_due_at != None,
        extract("year", Ticket.closed_at) == year,
    ).group_by("m").all()
    sla_map = {}
    for m, total, within in sla_rows:
        sla_map[int(m)] = round((within / total * 100) if total else 0, 1)

    # By category (for the year)
    cat_rows = db.query(
        Ticket.category,
        func.count(Ticket.id),
    ).filter(
        extract("year", Ticket.created_at) == year
    ).group_by(Ticket.category).all()

    # By priority (for the year)
    pri_rows = db.query(
        Ticket.priority,
        func.count(Ticket.id),
    ).filter(
        extract("year", Ticket.created_at) == year
    ).group_by(Ticket.priority).all()

    # Per tech (for the year)
    tech_rows = db.query(
        User.full_name,
        func.count(Ticket.id),
        func.avg(
            case(
                (Ticket.closed_at != None,
                 func.extract("epoch", Ticket.closed_at - Ticket.created_at) / 3600),
                else_=None
            )
        ),
    ).join(Ticket, Ticket.assigned_to_id == User.id).filter(
        extract("year", Ticket.created_at) == year
    ).group_by(User.full_name).order_by(func.count(Ticket.id).desc()).all()

    return {
        "period": "monthly",
        "year": year,
        "labels": labels,
        "opened": [opened_map.get(m, 0) for m in months],
        "closed": [closed_map.get(m, 0) for m in months],
        "avg_resolution_hours": [res_map.get(m, 0) for m in months],
        "sla_compliance_pct": [sla_map.get(m, 0) for m in months],
        "by_category": {cat or "Uncategorised": cnt for cat, cnt in cat_rows},
        "by_priority": {pri: cnt for pri, cnt in pri_rows},
        "by_tech": [
            {"name": name, "count": cnt, "avg_hours": round(float(avg), 1) if avg else None}
            for name, cnt, avg in tech_rows
        ],
    }


def _quarterly_data(db: Session, year: int) -> dict:
    labels = ["Q1 (Jan–Mar)", "Q2 (Apr–Jun)", "Q3 (Jul–Sep)", "Q4 (Oct–Dec)"]
    quarter_map = {1: 1, 2: 1, 3: 1, 4: 2, 5: 2, 6: 2, 7: 3, 8: 3, 9: 3, 10: 4, 11: 4, 12: 4}

    opened_rows = db.query(
        extract("month", Ticket.created_at).label("m"),
        func.count(Ticket.id),
    ).filter(extract("year", Ticket.created_at) == year).group_by("m").all()

    closed_rows = db.query(
        extract("month", Ticket.closed_at).label("m"),
        func.count(Ticket.id),
    ).filter(
        Ticket.closed_at != None,
        extract("year", Ticket.closed_at) == year,
    ).group_by("m").all()

    def _to_quarters(rows):
        q = {1: 0, 2: 0, 3: 0, 4: 0}
        for m, c in rows:
            q[quarter_map[int(m)]] += c
        return [q[i] for i in [1, 2, 3, 4]]

    res_rows = db.query(
        extract("month", Ticket.closed_at).label("m"),
        func.avg(func.extract("epoch", Ticket.closed_at - Ticket.created_at) / 3600),
    ).filter(
        Ticket.closed_at != None,
        extract("year", Ticket.closed_at) == year,
    ).group_by("m").all()
    q_res = {1: [], 2: [], 3: [], 4: []}
    for m, v in res_rows:
        if v:
            q_res[quarter_map[int(m)]].append(float(v))
    avg_res = [round(sum(v) / len(v), 1) if v else 0 for v in [q_res[i] for i in [1,2,3,4]]]

    # SLA per quarter
    sla_rows = db.query(
        extract("month", Ticket.closed_at).label("m"),
        func.count(Ticket.id),
        func.sum(case((Ticket.closed_at <= Ticket.sla_due_at, 1), else_=0)),
    ).filter(
        Ticket.closed_at != None,
        Ticket.sla_due_at != None,
        extract("year", Ticket.closed_at) == year,
    ).group_by("m").all()
    q_sla_total = {1: 0, 2: 0, 3: 0, 4: 0}
    q_sla_within = {1: 0, 2: 0, 3: 0, 4: 0}
    for m, total, within in sla_rows:
        q = quarter_map[int(m)]
        q_sla_total[q] += total
        q_sla_within[q] += (within or 0)
    sla_pct = [
        round(q_sla_within[i] / q_sla_total[i] * 100, 1) if q_sla_total[i] else 0
        for i in [1, 2, 3, 4]
    ]

    cat_rows = db.query(Ticket.category, func.count(Ticket.id)).filter(
        extract("year", Ticket.created_at) == year
    ).group_by(Ticket.category).all()

    return {
        "period": "quarterly",
        "year": year,
        "labels": labels,
        "opened": _to_quarters(opened_rows),
        "closed": _to_quarters(closed_rows),
        "avg_resolution_hours": avg_res,
        "sla_compliance_pct": sla_pct,
        "by_category": {cat or "Uncategorised": cnt for cat, cnt in cat_rows},
        "by_tech": _tech_summary(db, year),
    }


def _yearly_data(db: Session) -> dict:
    # Get min year from data
    min_year = db.query(func.min(extract("year", Ticket.created_at))).scalar()
    if not min_year:
        min_year = datetime.utcnow().year
    min_year = int(min_year)
    max_year = datetime.utcnow().year
    years = list(range(min_year, max_year + 1))

    opened = []
    closed = []
    avg_res = []
    sla_pct = []
    for y in years:
        o = db.query(func.count(Ticket.id)).filter(extract("year", Ticket.created_at) == y).scalar() or 0
        c = db.query(func.count(Ticket.id)).filter(
            Ticket.closed_at != None, extract("year", Ticket.closed_at) == y
        ).scalar() or 0
        r = db.query(func.avg(func.extract("epoch", Ticket.closed_at - Ticket.created_at) / 3600)).filter(
            Ticket.closed_at != None, extract("year", Ticket.closed_at) == y
        ).scalar()
        st, sw = db.query(
            func.count(Ticket.id),
            func.sum(case((Ticket.closed_at <= Ticket.sla_due_at, 1), else_=0))
        ).filter(
            Ticket.closed_at != None, Ticket.sla_due_at != None,
            extract("year", Ticket.closed_at) == y
        ).first()
        opened.append(o)
        closed.append(c)
        avg_res.append(round(float(r), 1) if r else 0)
        sla_pct.append(round(sw / st * 100, 1) if st else 0)

    cat_rows = db.query(Ticket.category, func.count(Ticket.id)).group_by(Ticket.category).all()

    return {
        "period": "yearly",
        "labels": [str(y) for y in years],
        "opened": opened,
        "closed": closed,
        "avg_resolution_hours": avg_res,
        "sla_compliance_pct": sla_pct,
        "by_category": {cat or "Uncategorised": cnt for cat, cnt in cat_rows},
        "by_tech": _tech_summary(db, None),
    }


def _tech_summary(db, year):
    q = db.query(
        User.full_name,
        func.count(Ticket.id),
        func.avg(case(
            (Ticket.closed_at != None, func.extract("epoch", Ticket.closed_at - Ticket.created_at) / 3600),
            else_=None
        )),
    ).join(Ticket, Ticket.assigned_to_id == User.id)
    if year:
        q = q.filter(extract("year", Ticket.created_at) == year)
    rows = q.group_by(User.full_name).order_by(func.count(Ticket.id).desc()).all()
    return [
        {"name": n, "count": c, "avg_hours": round(float(a), 1) if a else None}
        for n, c, a in rows
    ]


# ─── CSV export ───────────────────────────────────────────────────────────────

@router.get("/export/csv")
async def export_csv(
    request: Request,
    year: int = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    _require_tech(request)
    import csv, io
    year = year or datetime.utcnow().year

    tickets = db.query(Ticket).filter(
        extract("year", Ticket.created_at) == year
    ).order_by(Ticket.created_at).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID", "Title", "Status", "Priority", "Category",
        "Created By", "Assigned To", "Asset",
        "Created At", "Closed At", "Resolution Hours", "SLA Met",
    ])
    for t in tickets:
        writer.writerow([
            t.id, t.title, t.status, t.priority, t.category or "",
            t.created_by.full_name if t.created_by else "",
            t.assigned_to.full_name if t.assigned_to else "",
            f"{t.asset.manufacturer} {t.asset.model}" if t.asset else "",
            t.created_at.strftime("%Y-%m-%d %H:%M") if t.created_at else "",
            t.closed_at.strftime("%Y-%m-%d %H:%M") if t.closed_at else "",
            t.resolution_hours or "",
            "Yes" if (t.closed_at and t.sla_due_at and t.closed_at <= t.sla_due_at) else
            ("No" if t.closed_at else ""),
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=helpdesk-kpi-{year}.csv"},
    )
