from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from core.deps import get_db, require_user
from core.currency import get_currency, all_currencies
from core.sync import sync_users_from_authentik, get_sync_state
from models.user import User

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/", response_class=HTMLResponse)
def list_users(
    request: Request,
    search: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    query = db.query(User)
    if search:
        like = f"%{search}%"
        query = query.filter(
            User.full_name.ilike(like)
            | User.username.ilike(like)
            | User.email.ilike(like)
            | User.department.ilike(like)
            | User.title.ilike(like)
        )
    users = query.order_by(User.full_name).all()
    sync_state = get_sync_state()

    return templates.TemplateResponse(request, "users/list.html", {
        "users": users,
        "search": search,
        "current_user": current_user,
        "sync_state": sync_state,
    })


@router.post("/sync")
async def trigger_sync(
    request: Request,
    current_user: User = Depends(require_user),
):
    """Manually trigger a user sync from Authentik."""
    from core.config import settings
    if not settings.AUTHENTIK_API_TOKEN:
        return JSONResponse(
            {"error": "AUTHENTIK_API_TOKEN is not configured"},
            status_code=400,
        )
    try:
        result = await sync_users_from_authentik()
        return RedirectResponse("/users", status_code=302)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/{user_id}", response_class=HTMLResponse)
def user_detail(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return HTMLResponse("User not found", status_code=404)
    return templates.TemplateResponse(request, "users/detail.html", {
        "user": user,
        "current_user": current_user,
        "currencies": all_currencies(),
    })


@router.post("/{user_id}/edit")
def edit_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
    phone: str = Form(""),
    department: str = Form(""),
    title: str = Form(""),
    location: str = Form(""),
    notes: str = Form(""),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return HTMLResponse("User not found", status_code=404)
    user.phone = phone
    user.department = department
    user.title = title
    user.location = location
    user.notes = notes
    db.commit()
    return RedirectResponse(f"/users/{user_id}", status_code=302)
