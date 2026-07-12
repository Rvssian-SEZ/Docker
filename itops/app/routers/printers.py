import os
import uuid
from datetime import date

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from core.deps import get_db, require_user
from core.currency import get_currency, all_currencies
from models.printer import Printer, PrinterRepair, PrinterStatus, PrinterAttachment
from models.contract import Contract
from models.user import User

router = APIRouter()
templates = Jinja2Templates(directory="templates")

UPLOAD_DIR = "/app/uploads/printers"


def _parse_date(s):
    return date.fromisoformat(s) if s else None

def _printer_upload_dir(printer_id: int) -> str:
    path = os.path.join(UPLOAD_DIR, str(printer_id))
    os.makedirs(path, exist_ok=True)
    return path


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
            Printer.make.ilike(like) | Printer.model.ilike(like)
            | Printer.location.ilike(like) | Printer.department.ilike(like)
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
        "currency": get_currency(request),
        "currencies": all_currencies(),
    })



@router.get("/metrics", response_class=HTMLResponse)
def printer_metrics(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    from models.printer import PrinterRepair, _parse_amount, _detect_currency

    CURRENCY_INFO = {
        "SCR": {"symbol": "₨", "name": "Seychelles Rupee"},
        "USD": {"symbol": "$", "name": "US Dollar"},
        "GBP": {"symbol": "£", "name": "Pound Sterling"},
    }

    printers = db.query(Printer).all()
    all_repairs = db.query(PrinterRepair).all()

    # ── Per-currency totals ──────────────────────────────────────────────────
    currency_totals = {}
    for p in printers:
        if p.purchase_price:
            cur = _detect_currency(p.purchase_price)
            amt = _parse_amount(p.purchase_price) or 0
            if cur not in currency_totals:
                currency_totals[cur] = {"purchase": 0, "repairs": 0}
            currency_totals[cur]["purchase"] += amt

    for r in all_repairs:
        if r.cost:
            cur = _detect_currency(r.cost)
            amt = _parse_amount(r.cost) or 0
            if cur not in currency_totals:
                currency_totals[cur] = {"purchase": 0, "repairs": 0}
            currency_totals[cur]["repairs"] += amt

    # Build display list in consistent order
    currency_breakdown = []
    for code in ["SCR", "USD", "GBP"]:
        if code in currency_totals:
            info = CURRENCY_INFO.get(code, {"symbol": code, "name": code})
            totals = currency_totals[code]
            currency_breakdown.append({
                "code": code,
                "symbol": info["symbol"],
                "name": info["name"],
                "purchase": totals["purchase"],
                "repairs": totals["repairs"],
                "total": totals["purchase"] + totals["repairs"],
            })

    # ── Yearly breakdown (all currencies combined numerically) ──────────────
    from sqlalchemy import extract, func
    purchase_rows = db.query(
        extract("year", Printer.purchase_date).label("year"),
        func.count(Printer.id).label("count"),
    ).filter(
        Printer.purchase_date != None,  # noqa: E711
    ).group_by("year").order_by("year").all()

    repair_rows = db.query(
        extract("year", PrinterRepair.repair_date).label("year"),
        func.count(PrinterRepair.id).label("count"),
    ).group_by("year").order_by("year").all()

    all_years = sorted(set(
        [int(r.year) for r in purchase_rows] +
        [int(r.year) for r in repair_rows]
    ))

    # Per-year, per-currency breakdown
    yearly_by_currency = {}  # {year: {currency: {purchase, repairs}}}
    for p in printers:
        if p.purchase_date and p.purchase_price:
            year = p.purchase_date.year
            cur = _detect_currency(p.purchase_price)
            amt = _parse_amount(p.purchase_price) or 0
            yearly_by_currency.setdefault(year, {}).setdefault(cur, {"purchase": 0, "repairs": 0})
            yearly_by_currency[year][cur]["purchase"] += amt

    for r in all_repairs:
        year = r.repair_date.year
        cur = _detect_currency(r.cost) if r.cost else "SCR"
        amt = _parse_amount(r.cost) or 0
        yearly_by_currency.setdefault(year, {}).setdefault(cur, {"purchase": 0, "repairs": 0})
        yearly_by_currency[year][cur]["repairs"] += amt

    # All-time counts
    total_printers = db.query(func.count(Printer.id)).scalar() or 0
    total_repair_records = len(all_repairs)

    return templates.TemplateResponse(request, "printers/metrics.html", {
        "currency_breakdown": currency_breakdown,
        "yearly_by_currency": yearly_by_currency,
        "all_years": all_years,
        "total_printers": total_printers,
        "total_repair_records": total_repair_records,
        "currency_info": CURRENCY_INFO,
        "current_user": current_user,
        "currency": get_currency(request),
        "currencies": all_currencies(),
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
        "today": date.today().isoformat(),
        "current_user": current_user,
        "currency": get_currency(request),
        "currencies": all_currencies(),
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
        make=make, model=model, serial_number=serial_number,
        asset_tag=asset_tag or None, ip_address=ip_address,
        location=location, department=department,
        purchase_date=_parse_date(purchase_date),
        warranty_expiry=_parse_date(warranty_expiry),
        purchase_price=purchase_price,
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
    printer.purchase_price = purchase_price
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
        cost=cost,
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


# ── Attachments ────────────────────────────────────────────────────────────────

@router.post("/{printer_id}/attachments/upload")
async def upload_attachment(
    printer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
    file: UploadFile = File(...),
    notes: str = Form(""),
):
    printer = db.query(Printer).filter(Printer.id == printer_id).first()
    if not printer:
        return HTMLResponse("Printer not found", status_code=404)

    # Generate unique stored filename
    ext = os.path.splitext(file.filename)[1] if file.filename else ""
    stored_filename = f"{uuid.uuid4().hex}{ext}"
    upload_path = os.path.join(_printer_upload_dir(printer_id), stored_filename)

    # Save file
    contents = await file.read()
    with open(upload_path, "wb") as f:
        f.write(contents)

    # Determine mime type
    mime_type = file.content_type or "application/octet-stream"
    if not mime_type or mime_type == "application/octet-stream":
        if ext.lower() == ".pdf":
            mime_type = "application/pdf"

    attachment = PrinterAttachment(
        printer_id=printer_id,
        filename=stored_filename,
        original_filename=file.filename or stored_filename,
        file_size=len(contents),
        mime_type=mime_type,
        notes=notes,
        uploaded_by_id=current_user.id,
    )
    db.add(attachment)
    db.commit()
    return RedirectResponse(f"/printers/{printer_id}", status_code=302)


@router.get("/{printer_id}/attachments/{attachment_id}/view")
def view_attachment(
    printer_id: int,
    attachment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    attachment = db.query(PrinterAttachment).filter(
        PrinterAttachment.id == attachment_id,
        PrinterAttachment.printer_id == printer_id,
    ).first()
    if not attachment:
        return HTMLResponse("File not found", status_code=404)

    file_path = os.path.join(UPLOAD_DIR, str(printer_id), attachment.filename)
    if not os.path.exists(file_path):
        return HTMLResponse("File not found on disk", status_code=404)

    # PDFs and images open inline (new tab), others download
    disposition = "inline" if attachment.is_pdf else "attachment"
    return FileResponse(
        path=file_path,
        media_type=attachment.mime_type,
        filename=attachment.original_filename,
        headers={"Content-Disposition": f'{disposition}; filename="{attachment.original_filename}"'},
    )


@router.post("/{printer_id}/attachments/{attachment_id}/delete")
def delete_attachment(
    printer_id: int,
    attachment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    attachment = db.query(PrinterAttachment).filter(
        PrinterAttachment.id == attachment_id,
        PrinterAttachment.printer_id == printer_id,
    ).first()
    if attachment:
        # Delete file from disk
        file_path = os.path.join(UPLOAD_DIR, str(printer_id), attachment.filename)
        if os.path.exists(file_path):
            os.remove(file_path)
        db.delete(attachment)
        db.commit()
    return RedirectResponse(f"/printers/{printer_id}", status_code=302)

