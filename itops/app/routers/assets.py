from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from core.deps import get_db, require_user
from models.asset import AssetCategory, AssetStatus, ITAsset
from models.user import User

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/", response_class=HTMLResponse)
def list_assets(
    request: Request,
    search_tag: str = "",
    search_name: str = "",
    search_serial: str = "",
    search_user: str = "",
    status: str = "",
    category: str = "",
    warranty: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    query = db.query(ITAsset)
    if search_tag:
        query = query.filter(ITAsset.asset_tag.ilike(f"%{search_tag}%"))
    if search_name:
        query = query.filter(ITAsset.name.ilike(f"%{search_name}%"))
    if search_serial:
        query = query.filter(ITAsset.serial_number.ilike(f"%{search_serial}%"))
    if search_user:
        query = query.join(ITAsset.assigned_user).filter(
            User.full_name.ilike(f"%{search_user}%") | User.username.ilike(f"%{search_user}%")
        )
    if status:
        query = query.filter(ITAsset.status == status)
    if category:
        query = query.filter(ITAsset.category == category)
    if warranty == "expired":
        query = query.filter(ITAsset.warranty_expiry < date.today(), ITAsset.warranty_expiry != None)
    elif warranty == "active":
        query = query.filter(ITAsset.warranty_expiry >= date.today())
    elif warranty == "none":
        query = query.filter(ITAsset.warranty_expiry == None)

    assets = query.order_by(ITAsset.asset_tag).all()
    users = db.query(User).filter(User.is_active == True).order_by(User.full_name).all()

    return templates.TemplateResponse(request, "assets/list.html", {
        "assets": assets,
        "users": users,
        "search_tag": search_tag,
        "search_name": search_name,
        "search_serial": search_serial,
        "search_user": search_user,
        "filter_status": status,
        "filter_category": category,
        "filter_warranty": warranty,
        "statuses": AssetStatus,
        "categories": AssetCategory,
        "current_user": current_user,
        "now_date": date.today().isoformat(),
    })


@router.get("/{asset_id}", response_class=HTMLResponse)
def asset_detail(
    asset_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    asset = db.query(ITAsset).filter(ITAsset.id == asset_id).first()
    if not asset:
        return HTMLResponse("Asset not found", status_code=404)
    users = db.query(User).filter(User.is_active == True).order_by(User.full_name).all()
    return templates.TemplateResponse(request, "assets/detail.html", {
        "asset": asset,
        "users": users,
        "statuses": AssetStatus,
        "categories": AssetCategory,
        "current_user": current_user,
    })


@router.post("/new")
def create_asset(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
    name: str = Form(...),
    asset_tag: str = Form(""),
    category: str = Form("other"),
    manufacturer: str = Form(""),
    model: str = Form(""),
    serial_number: str = Form(""),
    purchase_date: str = Form(""),
    warranty_expiry: str = Form(""),
    purchase_price: str = Form(""),
    supplier: str = Form(""),
    notes: str = Form(""),
):
    def parse_date(s):
        return date.fromisoformat(s) if s else None

    asset = ITAsset(
        name=name,
        asset_tag=asset_tag or None,
        category=category,
        manufacturer=manufacturer,
        model=model,
        serial_number=serial_number,
        purchase_date=parse_date(purchase_date),
        warranty_expiry=parse_date(warranty_expiry),
        purchase_price=purchase_price,
        supplier=supplier,
        notes=notes,
        status=AssetStatus.available,
    )
    db.add(asset)
    db.commit()
    return RedirectResponse("/assets", status_code=302)


@router.post("/{asset_id}/edit")
def edit_asset(
    asset_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
    name: str = Form(...),
    asset_tag: str = Form(""),
    category: str = Form("other"),
    manufacturer: str = Form(""),
    model: str = Form(""),
    serial_number: str = Form(""),
    purchase_date: str = Form(""),
    warranty_expiry: str = Form(""),
    purchase_price: str = Form(""),
    supplier: str = Form(""),
    notes: str = Form(""),
):
    def parse_date(s):
        return date.fromisoformat(s) if s else None

    asset = db.query(ITAsset).filter(ITAsset.id == asset_id).first()
    if not asset:
        return HTMLResponse("Asset not found", status_code=404)

    asset.name = name
    asset.asset_tag = asset_tag or None
    asset.category = category
    asset.manufacturer = manufacturer
    asset.model = model
    asset.serial_number = serial_number
    asset.purchase_date = parse_date(purchase_date)
    asset.warranty_expiry = parse_date(warranty_expiry)
    asset.purchase_price = purchase_price
    asset.supplier = supplier
    asset.notes = notes
    db.commit()
    return RedirectResponse("/assets", status_code=302)


@router.post("/{asset_id}/assign")
def assign_asset(
    asset_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
    user_id: str = Form(""),
):
    asset = db.query(ITAsset).filter(ITAsset.id == asset_id).first()
    if not asset:
        return HTMLResponse("Asset not found", status_code=404)
    if user_id:
        asset.assigned_user_id = int(user_id)
        asset.status = AssetStatus.assigned
    else:
        asset.assigned_user_id = None
        asset.status = AssetStatus.available
    db.commit()
    return RedirectResponse("/assets", status_code=302)


@router.post("/{asset_id}/status")
def update_status(
    asset_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
    status: str = Form(...),
):
    asset = db.query(ITAsset).filter(ITAsset.id == asset_id).first()
    if not asset:
        return HTMLResponse("Asset not found", status_code=404)
    asset.status = AssetStatus(status)
    if asset.status != AssetStatus.assigned:
        asset.assigned_user_id = None
    db.commit()
    return RedirectResponse("/assets", status_code=302)


@router.post("/{asset_id}/delete")
def delete_asset(
    asset_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    asset = db.query(ITAsset).filter(ITAsset.id == asset_id).first()
    if asset:
        db.delete(asset)
        db.commit()
    return RedirectResponse("/assets", status_code=302)
