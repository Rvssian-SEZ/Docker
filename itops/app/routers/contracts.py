from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from core.deps import get_db, require_user
from core.currency import get_currency, all_currencies
from models.contract import BillingCycle, Contract, ContractStatus, ContractType
from models.user import User

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/", response_class=HTMLResponse)
def list_contracts(
    request: Request,
    search: str = "",
    filter_type: str = "",
    filter_status: str = "",
    filter_cycle: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    query = db.query(Contract)
    if search:
        like = f"%{search}%"
        query = query.filter(
            Contract.name.ilike(like) | Contract.vendor_name.ilike(like)
        )
    if filter_type:
        query = query.filter(Contract.contract_type == filter_type)
    if filter_cycle:
        query = query.filter(Contract.billing_cycle == filter_cycle)

    contracts = query.order_by(Contract.renewal_date.asc().nullslast()).all()

    # Apply status filter after fetching (status is computed)
    if filter_status:
        contracts = [c for c in contracts if c.computed_status.value == filter_status]

    # Counts for alert banner
    expiring = [c for c in contracts if c.computed_status == ContractStatus.expiring_soon]
    expired = [c for c in contracts if c.computed_status == ContractStatus.expired]

    users = db.query(User).filter(User.is_active == True).order_by(User.full_name).all()

    return templates.TemplateResponse(request, "contracts/list.html", {
        "contracts": contracts,
        "users": users,
        "search": search,
        "filter_type": filter_type,
        "filter_status": filter_status,
        "filter_cycle": filter_cycle,
        "contract_types": ContractType,
        "billing_cycles": BillingCycle,
        "contract_statuses": ContractStatus,
        "expiring_count": len(expiring),
        "expired_count": len(expired),
        "current_user": current_user,
        "today": date.today().isoformat(),
        "currency": get_currency(request),
        "currencies": all_currencies(),
    })


@router.post("/new")
def create_contract(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
    name: str = Form(...),
    contract_type: str = Form(...),
    vendor_name: str = Form(""),
    vendor_contact_name: str = Form(""),
    vendor_contact_email: str = Form(""),
    vendor_contact_phone: str = Form(""),
    cost: str = Form(""),
    billing_cycle: str = Form(""),
    start_date: str = Form(""),
    renewal_date: str = Form(""),
    owner_id: str = Form(""),
    notes: str = Form(""),
):
    def parse_date(s):
        return date.fromisoformat(s) if s else None

    contract = Contract(
        name=name,
        contract_type=contract_type,
        vendor_name=vendor_name,
        vendor_contact_name=vendor_contact_name,
        vendor_contact_email=vendor_contact_email,
        vendor_contact_phone=vendor_contact_phone,
        cost=cost,
        billing_cycle=billing_cycle or None,
        start_date=parse_date(start_date),
        renewal_date=parse_date(renewal_date),
        owner_id=int(owner_id) if owner_id else None,
        notes=notes,
    )
    db.add(contract)
    db.commit()
    return RedirectResponse("/contracts", status_code=302)


@router.post("/{contract_id}/edit")
def edit_contract(
    contract_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
    name: str = Form(...),
    contract_type: str = Form(...),
    vendor_name: str = Form(""),
    vendor_contact_name: str = Form(""),
    vendor_contact_email: str = Form(""),
    vendor_contact_phone: str = Form(""),
    cost: str = Form(""),
    billing_cycle: str = Form(""),
    start_date: str = Form(""),
    renewal_date: str = Form(""),
    owner_id: str = Form(""),
    status: str = Form(""),
    notes: str = Form(""),
):
    def parse_date(s):
        return date.fromisoformat(s) if s else None

    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if not contract:
        return HTMLResponse("Contract not found", status_code=404)

    contract.name = name
    contract.contract_type = contract_type
    contract.vendor_name = vendor_name
    contract.vendor_contact_name = vendor_contact_name
    contract.vendor_contact_email = vendor_contact_email
    contract.vendor_contact_phone = vendor_contact_phone
    contract.cost = cost
    contract.billing_cycle = billing_cycle or None
    contract.start_date = parse_date(start_date)
    contract.renewal_date = parse_date(renewal_date)
    contract.owner_id = int(owner_id) if owner_id else None
    contract.status = status if status else ContractStatus.active
    contract.notes = notes
    db.commit()
    return RedirectResponse("/contracts", status_code=302)


@router.post("/{contract_id}/delete")
def delete_contract(
    contract_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if contract:
        db.delete(contract)
        db.commit()
    return RedirectResponse("/contracts", status_code=302)
