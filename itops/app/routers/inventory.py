from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from core.deps import get_db, require_user
from models.inventory import (
    InventoryItem, InventoryDeployment, StockReceipt, InventoryCategory,
    CATEGORY_LABELS, CATEGORY_SHELF_LIFE,
)
from models.asset import ITAsset, AssetStatus
from models.user import User

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/", response_class=HTMLResponse)
def list_inventory(
    request: Request,
    search: str = "",
    category: str = "",
    show_expired: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    query = db.query(InventoryItem)
    if search:
        query = query.filter(
            InventoryItem.name.ilike(f"%{search}%")
            | InventoryItem.location.ilike(f"%{search}%")
        )
    if category:
        query = query.filter(InventoryItem.category == category)

    items = query.order_by(InventoryItem.category, InventoryItem.name).all()

    if show_expired == "1":
        items = [i for i in items if i.is_expired]

    return templates.TemplateResponse(request, "inventory/list.html", {
        "items": items,
        "search": search,
        "filter_category": category,
        "show_expired": show_expired,
        "categories": InventoryCategory,
        "category_labels": CATEGORY_LABELS,
        "category_shelf_life": CATEGORY_SHELF_LIFE,
        "current_user": current_user,
    })


@router.get("/{item_id}", response_class=HTMLResponse)
def item_detail(
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    item = db.query(InventoryItem).filter(InventoryItem.id == item_id).first()
    if not item:
        return HTMLResponse("Item not found", status_code=404)

    assets = db.query(ITAsset).filter(
        ITAsset.status != AssetStatus.retired
    ).order_by(ITAsset.name).all()

    return templates.TemplateResponse(request, "inventory/detail.html", {
        "item": item,
        "assets": assets,
        "categories": InventoryCategory,
        "category_labels": CATEGORY_LABELS,
        "current_user": current_user,
    })


@router.post("/new")
def create_item(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
    name: str = Form(...),
    category: str = Form(...),
    location: str = Form(""),
    shelf_life_months: str = Form(""),
    notes: str = Form(""),
):
    item = InventoryItem(
        name=name,
        category=InventoryCategory(category),
        opening_stock=0,
        location=location,
        shelf_life_months=int(shelf_life_months) if shelf_life_months else None,
        notes=notes,
    )
    db.add(item)
    db.commit()
    return RedirectResponse(f"/inventory/{item.id}", status_code=302)


@router.post("/{item_id}/edit")
def edit_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
    name: str = Form(...),
    category: str = Form(...),
    location: str = Form(""),
    shelf_life_months: str = Form(""),
    notes: str = Form(""),
):
    item = db.query(InventoryItem).filter(InventoryItem.id == item_id).first()
    if not item:
        return HTMLResponse("Item not found", status_code=404)

    item.name = name
    item.category = InventoryCategory(category)
    item.location = location
    item.shelf_life_months = int(shelf_life_months) if shelf_life_months else None
    item.notes = notes
    db.commit()
    return RedirectResponse(f"/inventory/{item_id}", status_code=302)


@router.post("/{item_id}/receive")
def receive_stock(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
    quantity: int = Form(...),
    notes: str = Form(""),
):
    item = db.query(InventoryItem).filter(InventoryItem.id == item_id).first()
    if not item:
        return HTMLResponse("Item not found", status_code=404)
    if quantity < 1:
        return HTMLResponse("Quantity must be at least 1", status_code=400)

    receipt = StockReceipt(
        item_id=item_id,
        quantity=quantity,
        received_by_id=current_user.id,
        notes=notes,
    )
    db.add(receipt)
    db.commit()
    return RedirectResponse(f"/inventory/{item_id}", status_code=302)


@router.post("/{item_id}/deploy")
def deploy_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
    asset_id: int = Form(...),
    quantity: int = Form(1),
    notes: str = Form(""),
):
    item = db.query(InventoryItem).filter(InventoryItem.id == item_id).first()
    if not item:
        return HTMLResponse("Item not found", status_code=404)
    if quantity > item.quantity_available:
        return HTMLResponse(f"Only {item.quantity_available} available", status_code=400)

    deployment = InventoryDeployment(
        item_id=item_id,
        asset_id=asset_id,
        quantity=quantity,
        deployed_by_id=current_user.id,
        notes=notes,
    )
    db.add(deployment)
    db.commit()
    return RedirectResponse(f"/inventory/{item_id}", status_code=302)


@router.post("/{item_id}/return/{deployment_id}")
def return_item(
    item_id: int,
    deployment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    deployment = db.query(InventoryDeployment).filter(
        InventoryDeployment.id == deployment_id,
        InventoryDeployment.item_id == item_id,
    ).first()
    if not deployment or deployment.returned_at:
        return HTMLResponse("Deployment not found or already returned", status_code=404)

    deployment.returned_at = datetime.utcnow()
    db.commit()
    return RedirectResponse(f"/inventory/{item_id}", status_code=302)


@router.post("/{item_id}/delete")
def delete_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    item = db.query(InventoryItem).filter(InventoryItem.id == item_id).first()
    if item:
        db.delete(item)
        db.commit()
    return RedirectResponse("/inventory", status_code=302)


@router.post("/{item_id}/retire/{deployment_id}")
def retire_deployment(
    item_id: int,
    deployment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user),
):
    """Permanently retire a deployed item — removes it from available stock."""
    deployment = db.query(InventoryDeployment).filter(
        InventoryDeployment.id == deployment_id,
        InventoryDeployment.item_id == item_id,
    ).first()
    if not deployment or deployment.returned_at or deployment.is_retired:
        return HTMLResponse("Deployment not found or already closed", status_code=404)

    deployment.is_retired = True
    deployment.retired_at = datetime.utcnow()
    db.commit()
    return RedirectResponse(f"/inventory/{item_id}", status_code=302)
