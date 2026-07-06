from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from core.deps import get_db, require_user
from models.printer import Printer, PrinterRepair, PrinterStatus
from models.contract import Contract
from models.user import User

router = APIRouter()
templates = Jinja2Templates(directory="templates")


def _parse_date(s):
    return date.fromisoformat(s) if s else None

def _parse_decimal(s):
    try:
        return Decimal(s) if s else None
    except Exception:
        return None


@router.get("/", response_class=HTMLResponse)
def list_printers(
    request: Request,
    search: str = "",
    status: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    query = db.query(Printer)
    if search:
        like = f"%{search}%"
        query = query.filter(
            Printer.make.ilike(like)
            | Printer.model.ilike(like)
            | Printer.location.ilike(like)
            | Printer.department.ilike(like)
            | Printer.asset_tag.ilike(like)
        )
    if status:
        query = query.filter(Printer.status == status)

    printers = query.order_by(Printer.make, Printer.model).all()
    contracts = db.query(Contract).order_by(Contract.name).all()

    return templates.TemplateResponse(request, "printers/list.html", {
        "printers": printers,
        "contracts": contracts,
        "search": search,
        "filter_status": status,
        "statuses": PrinterStatus,
        "current_user": current_user,
    })


@router.get("/{printer_id}", response_class=HTMLResponse)
def printer_detail(
    printer_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    printer = db.query(Printer).filter(Printer.id == printer_id).first()
    if not printer:
        return HTMLResponse("Printer not found", status_code=404)
    contracts = db.query(Contract).order_by(Contract.name).all()
    return templates.TemplateResponse(request, "printers/detail.html", {
        "printer": printer,
        "contracts": contracts,
        "statuses": PrinterStatus,
        "current_user": current_user,
    })


@router.post("/new")
def create_printer(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
    make: str = Form(...),
    model: str = Form(...),
    serial_number: str = Form(""),
    asset_tag: str = Form(""),
    ip_address: str = Form(""),
    location: str = Form(""),
    department: str = Form(""),
    purchase_date: str = Form(""),
    warranty_expiry: str = Form(""),
    purchase_price: str = Form(""),
    contract_id: str = Form(""),
    notes: str = Form(""),
):
    printer = Printer(
        make=make,
        model=model,
        serial_number=serial_number,
        asset_tag=asset_tag or None,
        ip_address=ip_address,
        location=location,
        department=department,
        purchase_date=_parse_date(purchase_date),
        warranty_expiry=_parse_date(warranty_expiry),
        purchase_price=_parse_decimal(purchase_price),
        contract_id=int(contract_id) if contract_id else None,
        notes=notes,
    )
    db.add(printer)
    db.commit()
    return RedirectResponse(f"/printers/{printer.id}", status_code=302)


@router.post("/{printer_id}/edit")
def edit_printer(
    printer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
    make: str = Form(...),
    model: str = Form(...),
    serial_number: str = Form(""),
    asset_tag: str = Form(""),
    ip_address: str = Form(""),
    location: str = Form(""),
    department: str = Form(""),
    status: str = Form(""),
    purchase_date: str = Form(""),
    warranty_expiry: str = Form(""),
    purchase_price: str = Form(""),
    contract_id: str = Form(""),
    notes: str = Form(""),
):
    printer = db.query(Printer).filter(Printer.id == printer_id).first()
    if not printer:
        return HTMLResponse("Printer not found", status_code=404)

    printer.make = make
    printer.model = model
    printer.serial_number = serial_number
    printer.asset_tag = asset_tag or None
    printer.ip_address = ip_address
    printer.location = location
    printer.department = department
    printer.status = PrinterStatus(status) if status else printer.status
    printer.purchase_date = _parse_date(purchase_date)
    printer.warranty_expiry = _parse_date(warranty_expiry)
    printer.purchase_price = _parse_decimal(purchase_price)
    printer.contract_id = int(contract_id) if contract_id else None
    printer.notes = notes
    db.commit()
    return RedirectResponse(f"/printers/{printer_id}", status_code=302)


@router.post("/{printer_id}/delete")
def delete_printer(
    printer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    printer = db.query(Printer).filter(Printer.id == printer_id).first()
    if printer:
        db.delete(printer)
        db.commit()
    return RedirectResponse("/printers", status_code=302)


@router.post("/{printer_id}/repairs/add")
def add_repair(
    printer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
    description: str = Form(...),
    repair_date: str = Form(""),
    cost: str = Form(""),
    document_ref: str = Form(""),
    notes: str = Form(""),
):
    printer = db.query(Printer).filter(Printer.id == printer_id).first()
    if not printer:
        return HTMLResponse("Printer not found", status_code=404)

    repair = PrinterRepair(
        printer_id=printer_id,
        description=description,
        repair_date=_parse_date(repair_date) or date.today(),
        cost=_parse_decimal(cost),
        document_ref=document_ref,
        notes=notes,
    )
    db.add(repair)
    db.commit()
    return RedirectResponse(f"/printers/{printer_id}", status_code=302)


@router.post("/{printer_id}/repairs/{repair_id}/delete")
def delete_repair(
    printer_id: int,
    repair_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    repair = db.query(PrinterRepair).filter(
        PrinterRepair.id == repair_id,
        PrinterRepair.printer_id == printer_id,
    ).first()
    if repair:
        db.delete(repair)
        db.commit()
    return RedirectResponse(f"/printers/{printer_id}", status_code=302)
