import os
import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from core.deps import get_db, require_user
from models.asset import AssetCategory, AssetStatus, ITAsset
from models.user import User

router = APIRouter()
templates = Jinja2Templates(directory="templates")

UPLOAD_DIR = "/app/uploads/assets"
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


def _asset_photo_path(asset_id: int, filename: str) -> str:
    directory = os.path.join(UPLOAD_DIR, str(asset_id))
    os.makedirs(directory, exist_ok=True)
    return os.path.join(directory, filename)


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


@router.get("/{asset_id}/photo")
def serve_photo(
    asset_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    """Serve an asset's photo — own photo first, then model photo fallback."""
    asset = db.query(ITAsset).filter(ITAsset.id == asset_id).first()
    if not asset:
        return HTMLResponse("Not found", status_code=404)

    # Own photo
    if asset.photo_filename:
        path = _asset_photo_path(asset.id, asset.photo_filename)
        if os.path.exists(path):
            return FileResponse(path)

    # Model photo fallback
    if asset.model_key:
        model_asset = db.query(ITAsset).filter(
            ITAsset.photo_is_model_photo == True,  # noqa: E712
            ITAsset.photo_filename != None,  # noqa: E711
            ITAsset.manufacturer.ilike(asset.manufacturer or ""),
            ITAsset.model.ilike(asset.model or ""),
        ).first()
        if model_asset and model_asset.photo_filename:
            path = _asset_photo_path(model_asset.id, model_asset.photo_filename)
            if os.path.exists(path):
                return FileResponse(path)

    return HTMLResponse("No photo", status_code=404)


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

    # Check if a model photo exists from another asset
    model_photo_asset = None
    if not asset.photo_filename and asset.model_key:
        model_photo_asset = db.query(ITAsset).filter(
            ITAsset.photo_is_model_photo == True,  # noqa: E712
            ITAsset.photo_filename != None,  # noqa: E711
            ITAsset.id != asset.id,
            ITAsset.manufacturer.ilike(asset.manufacturer or ""),
            ITAsset.model.ilike(asset.model or ""),
        ).first()

    users = db.query(User).filter(User.is_active == True).order_by(User.full_name).all()
    return templates.TemplateResponse(request, "assets/detail.html", {
        "asset": asset,
        "users": users,
        "statuses": AssetStatus,
        "categories": AssetCategory,
        "model_photo_asset": model_photo_asset,
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
        name=name, asset_tag=asset_tag or None, category=category,
        manufacturer=manufacturer, model=model, serial_number=serial_number,
        purchase_date=parse_date(purchase_date), warranty_expiry=parse_date(warranty_expiry),
        purchase_price=purchase_price, supplier=supplier, notes=notes,
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
    return RedirectResponse(f"/assets/{asset_id}", status_code=302)


@router.post("/{asset_id}/photo/upload")
async def upload_photo(
    asset_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
    file: UploadFile = File(...),
    set_model_photo: str = Form(""),
):
    asset = db.query(ITAsset).filter(ITAsset.id == asset_id).first()
    if not asset:
        return HTMLResponse("Asset not found", status_code=404)

    if file.content_type not in ALLOWED_IMAGE_TYPES:
        return HTMLResponse("Only image files are allowed (JPEG, PNG, WebP, GIF)", status_code=400)

    # Delete old photo if exists
    if asset.photo_filename:
        old_path = _asset_photo_path(asset.id, asset.photo_filename)
        if os.path.exists(old_path):
            os.remove(old_path)

    # Save new photo
    ext = os.path.splitext(file.filename)[1] if file.filename else ".jpg"
    stored_filename = f"{uuid.uuid4().hex}{ext}"
    contents = await file.read()
    with open(_asset_photo_path(asset.id, stored_filename), "wb") as f:
        f.write(contents)

    is_model = set_model_photo == "1"

    # Clear model photo flag from other assets with same make/model
    if is_model and asset.model_key:
        db.query(ITAsset).filter(
            ITAsset.photo_is_model_photo == True,  # noqa: E712
            ITAsset.id != asset.id,
            ITAsset.manufacturer.ilike(asset.manufacturer or ""),
            ITAsset.model.ilike(asset.model or ""),
        ).update({"photo_is_model_photo": False})

    asset.photo_filename = stored_filename
    asset.photo_is_model_photo = is_model
    db.commit()
    return RedirectResponse(f"/assets/{asset_id}", status_code=302)


@router.post("/{asset_id}/photo/delete")
def delete_photo(
    asset_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    asset = db.query(ITAsset).filter(ITAsset.id == asset_id).first()
    if not asset:
        return HTMLResponse("Asset not found", status_code=404)

    if asset.photo_filename:
        path = _asset_photo_path(asset.id, asset.photo_filename)
        if os.path.exists(path):
            os.remove(path)
        asset.photo_filename = None
        asset.photo_is_model_photo = False
        db.commit()

    return RedirectResponse(f"/assets/{asset_id}", status_code=302)


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
    from models.inventory import InventoryDeployment

    asset = db.query(ITAsset).filter(ITAsset.id == asset_id).first()
    if not asset:
        return HTMLResponse("Asset not found", status_code=404)

    new_status = AssetStatus(status)
    asset.status = new_status

    if new_status != AssetStatus.assigned:
        asset.assigned_user_id = None

    if new_status in (AssetStatus.retired, AssetStatus.lost):
        active_deployments = db.query(InventoryDeployment).filter(
            InventoryDeployment.asset_id == asset_id,
            InventoryDeployment.returned_at == None,  # noqa: E711
            InventoryDeployment.is_retired == False,  # noqa: E712
        ).all()
        for d in active_deployments:
            d.is_retired = True
            d.retired_at = datetime.utcnow()
            d.notes = (d.notes + f"\nAuto-retired: asset marked as {new_status.value}").strip()

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
        # Clean up photo
        if asset.photo_filename:
            path = _asset_photo_path(asset.id, asset.photo_filename)
            if os.path.exists(path):
                os.remove(path)
        db.delete(asset)
        db.commit()
    return RedirectResponse("/assets", status_code=302)
