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
    search: str = "",
    status: str = "",
    category: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    query = db.query(ITAsset)
    if search:
        like = f"%{search}%"
        query = query.filter(
            ITAsset.name.ilike(like)
            | ITAsset.asset_tag.ilike(like)
            | ITAsset.serial_number.ilike(like)
        )
    if status:
        query = query.filter(ITAsset.status == status)
    if category:
        query = query.filter(ITAsset.category == category)

    assets = query.order_by(ITAsset.asset_tag).all()
    users = db.query(User).filter(User.is_active == True).order_by(User.full_name).all()

    return templates.TemplateResponse(request, "assets/list.html", {
        "assets": assets,
        "users": users,
        "search": search,
        "filter_status": status,
        "filter_category": category,
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
    from datetime import date

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
