from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from core.deps import get_db, require_user
from models.equipment import Equipment, EquipmentStatus, LendingRecord
from models.user import User

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/", response_class=HTMLResponse)
def list_equipment(
    request: Request,
    search: str = "",
    status: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    query = db.query(Equipment)
    if search:
        like = f"%{search}%"
        query = query.filter(
            Equipment.name.ilike(like) | Equipment.category.ilike(like)
        )
    if status:
        query = query.filter(Equipment.status == status)

    equipment_list = query.order_by(Equipment.name).all()
    users = db.query(User).filter(User.is_active == True).order_by(User.full_name).all()

    return templates.TemplateResponse(request, "equipment/list.html", {
        "equipment_list": equipment_list,
        "users": users,
        "search": search,
        "filter_status": status,
        "statuses": EquipmentStatus,
        "current_user": current_user,
    })


@router.post("/new")
def create_equipment(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
    name: str = Form(...),
    category: str = Form(""),
    serial_number: str = Form(""),
    asset_tag: str = Form(""),
    location: str = Form(""),
    notes: str = Form(""),
):
    eq = Equipment(
        name=name,
        category=category,
        serial_number=serial_number,
        asset_tag=asset_tag or None,
        location=location,
        notes=notes,
    )
    db.add(eq)
    db.commit()
    return RedirectResponse("/equipment", status_code=302)


@router.get("/lending", response_class=HTMLResponse)
def lending_list(
    request: Request,
    show: str = "active",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    query = db.query(LendingRecord)
    if show == "active":
        query = query.filter(LendingRecord.returned_at == None)  # noqa: E711

    records = query.order_by(LendingRecord.lent_at.desc()).all()
    users = db.query(User).filter(User.is_active == True).order_by(User.full_name).all()
    equipment_list = (
        db.query(Equipment)
        .filter(Equipment.status == EquipmentStatus.available)
        .order_by(Equipment.name)
        .all()
    )

    return templates.TemplateResponse(request, "equipment/lending.html", {
        "records": records,
        "users": users,
        "equipment_list": equipment_list,
        "show": show,
        "current_user": current_user,
    })


@router.post("/lend")
def lend_equipment(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
    equipment_id: int = Form(...),
    user_id: int = Form(...),
    due_at: str = Form(""),
    notes: str = Form(""),
):
    equipment = db.query(Equipment).filter(Equipment.id == equipment_id).first()
    if not equipment or equipment.status != EquipmentStatus.available:
        return HTMLResponse("Equipment not available", status_code=400)

    due = datetime.fromisoformat(due_at) if due_at else None
    record = LendingRecord(
        equipment_id=equipment_id,
        user_id=user_id,
        lent_by_id=current_user.id,
        due_at=due,
        notes=notes,
    )
    equipment.status = EquipmentStatus.on_loan
    db.add(record)
    db.commit()
    return RedirectResponse("/equipment/lending", status_code=302)


@router.post("/return/{record_id}")
def return_equipment(
    record_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
    notes: str = Form(""),
):
    record = db.query(LendingRecord).filter(LendingRecord.id == record_id).first()
    if not record or record.returned_at:
        return HTMLResponse("Lending record not found or already returned", status_code=404)

    record.returned_at = datetime.utcnow()
    if notes:
        record.notes = (record.notes + "\n" + notes).strip()

    equipment = db.query(Equipment).filter(Equipment.id == record.equipment_id).first()
    if equipment:
        equipment.status = EquipmentStatus.available

    db.commit()
    return RedirectResponse("/equipment/lending", status_code=302)


@router.post("/{equipment_id}/delete")
def delete_equipment(
    equipment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    eq = db.query(Equipment).filter(Equipment.id == equipment_id).first()
    if eq:
        db.delete(eq)
        db.commit()
    return RedirectResponse("/equipment", status_code=302)
