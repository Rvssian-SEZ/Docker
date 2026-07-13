"""Catalog: core lookup data feeding Assets (Phase 5) — companies, locations,
manufacturers, categories, models, status labels.

Simple named entities (companies/locations/manufacturers/categories) share
one CRUD implementation registered per entity below. Models and status
labels have extra fields so they get dedicated routes.

Deletes are never cascaded: the DB FK blocks them while referenced, and we
turn that IntegrityError into a friendly toast instead of a 500.
HTMX pattern matches Users: create/delete are infrequent -> HX-Refresh the
list; rename/update -> toast only, per-field save.
"""

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import CurrentUser, get_current_user, require
from app.core.db import get_db
from app.core.models import (
    AssetModel,
    AuditLog,
    Category,
    Company,
    Location,
    Manufacturer,
    StatusLabel,
    StatusType,
)
from app.templating import templates

router = APIRouter(prefix="/catalog")


@router.get("", response_class=HTMLResponse)
async def catalog_root(user: CurrentUser = Depends(get_current_user)):
    if user.can("catalog.view"):
        return RedirectResponse("/catalog/manufacturers", status_code=302)
    if user.can("companies.manage"):
        return RedirectResponse("/catalog/companies", status_code=302)
    raise HTTPException(status_code=403, detail="Missing permission: catalog.view")


# ---- shared helpers (named entities: id, name) ----

async def _create_named(db: AsyncSession, model_cls, name: str, user: CurrentUser, entity_type: str):
    name = name.strip()
    if not name:
        return None, "Name is required."
    exists = (await db.execute(select(model_cls.id).where(model_cls.name == name))).first()
    if exists:
        return None, f"'{name}' already exists."
    row = model_cls(name=name)
    db.add(row)
    await db.flush()
    db.add(AuditLog(user_id=user.id, action="create", entity_type=entity_type, entity_id=str(row.id), detail=name))
    await db.commit()
    return row, None


async def _rename_named(db: AsyncSession, model_cls, item_id: int, name: str, user: CurrentUser, entity_type: str):
    name = name.strip()
    if not name:
        return False, "Name is required."
    row = await db.get(model_cls, item_id)
    if row is None:
        return False, "Not found."
    dup = (
        await db.execute(select(model_cls.id).where(model_cls.name == name, model_cls.id != item_id))
    ).first()
    if dup:
        return False, f"'{name}' already exists."
    old = row.name
    row.name = name
    db.add(
        AuditLog(
            user_id=user.id, action="update", entity_type=entity_type, entity_id=str(item_id),
            detail=f"{old} -> {name}",
        )
    )
    await db.commit()
    return True, f"Renamed to '{name}'."


async def _delete_named(db: AsyncSession, model_cls, item_id: int, user: CurrentUser, entity_type: str):
    row = await db.get(model_cls, item_id)
    if row is None:
        return False, "Not found."
    name = row.name
    await db.delete(row)
    db.add(AuditLog(user_id=user.id, action="delete", entity_type=entity_type, entity_id=str(item_id), detail=name))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return False, f"Cannot delete '{name}': still in use."
    return True, None


def _toast(request: Request, ok: bool, message: str):
    return templates.TemplateResponse(request, "partials/toast.html", {"ok": ok, "message": message})


def _refresh():
    return Response(status_code=204, headers={"HX-Refresh": "true"})


def _register_simple_entity(
    path: str,
    model_cls,
    entity_type: str,
    label_plural: str,
    label_singular: str,
    view_perm: str,
    manage_perm: str,
    active_tab: str,
):
    view_dep = require(view_perm)
    manage_dep = require(manage_perm)

    async def list_view(
        request: Request, user: CurrentUser = Depends(view_dep), db: AsyncSession = Depends(get_db)
    ):
        rows = (await db.execute(select(model_cls).order_by(model_cls.name))).scalars().all()
        return templates.TemplateResponse(
            request,
            "catalog/simple_list.html",
            {
                "user": user,
                "rows": rows,
                "active_tab": active_tab,
                "label_plural": label_plural,
                "label_singular": label_singular,
                "base_url": f"/catalog/{path}",
                "can_manage": user.can(manage_perm),
            },
        )

    async def create(
        request: Request,
        name: str = Form(...),
        user: CurrentUser = Depends(manage_dep),
        db: AsyncSession = Depends(get_db),
    ):
        _, err = await _create_named(db, model_cls, name, user, entity_type)
        if err:
            return _toast(request, False, err)
        return _refresh()

    async def update(
        request: Request,
        item_id: int,
        name: str = Form(...),
        user: CurrentUser = Depends(manage_dep),
        db: AsyncSession = Depends(get_db),
    ):
        ok, message = await _rename_named(db, model_cls, item_id, name, user, entity_type)
        return _toast(request, ok, message)

    async def delete(
        request: Request,
        item_id: int,
        user: CurrentUser = Depends(manage_dep),
        db: AsyncSession = Depends(get_db),
    ):
        ok, err = await _delete_named(db, model_cls, item_id, user, entity_type)
        if not ok:
            return _toast(request, False, err)
        return _refresh()

    router.add_api_route(f"/{path}", list_view, methods=["GET"], response_class=HTMLResponse)
    router.add_api_route(f"/{path}/create", create, methods=["POST"], response_class=HTMLResponse)
    router.add_api_route(f"/{path}/{{item_id}}/update", update, methods=["POST"], response_class=HTMLResponse)
    router.add_api_route(f"/{path}/{{item_id}}/delete", delete, methods=["POST"], response_class=HTMLResponse)


_register_simple_entity(
    "companies", Company, "company", "Companies", "company",
    "companies.manage", "companies.manage", "companies",
)
_register_simple_entity(
    "locations", Location, "location", "Locations", "location",
    "catalog.view", "catalog.manage", "locations",
)
_register_simple_entity(
    "manufacturers", Manufacturer, "manufacturer", "Manufacturers", "manufacturer",
    "catalog.view", "catalog.manage", "manufacturers",
)
_register_simple_entity(
    "categories", Category, "category", "Categories", "category",
    "catalog.view", "catalog.manage", "categories",
)


# ---- status labels (name + status_type) ----

@router.get("/status-labels", response_class=HTMLResponse)
async def status_labels_list(
    request: Request,
    user: CurrentUser = Depends(require("catalog.view")),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(select(StatusLabel).order_by(StatusLabel.name))).scalars().all()
    return templates.TemplateResponse(
        request,
        "catalog/status_labels.html",
        {
            "user": user,
            "rows": rows,
            "status_types": list(StatusType),
            "active_tab": "status-labels",
            "can_manage": user.can("catalog.manage"),
        },
    )


@router.post("/status-labels/create", response_class=HTMLResponse)
async def status_labels_create(
    request: Request,
    name: str = Form(...),
    status_type: str = Form(...),
    user: CurrentUser = Depends(require("catalog.manage")),
    db: AsyncSession = Depends(get_db),
):
    name = name.strip()
    if not name:
        return _toast(request, False, "Name is required.")
    if status_type not in StatusType.__members__:
        return _toast(request, False, "Unknown status type.")
    exists = (await db.execute(select(StatusLabel.id).where(StatusLabel.name == name))).first()
    if exists:
        return _toast(request, False, f"'{name}' already exists.")
    row = StatusLabel(name=name, status_type=StatusType(status_type))
    db.add(row)
    await db.flush()
    db.add(
        AuditLog(
            user_id=user.id, action="create", entity_type="status_label", entity_id=str(row.id), detail=name,
        )
    )
    await db.commit()
    return _refresh()


@router.post("/status-labels/{item_id}/update", response_class=HTMLResponse)
async def status_labels_update(
    request: Request,
    item_id: int,
    name: str = Form(...),
    status_type: str = Form(...),
    user: CurrentUser = Depends(require("catalog.manage")),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(StatusLabel, item_id)
    if row is None:
        return _toast(request, False, "Not found.")
    name = name.strip()
    if not name:
        return _toast(request, False, "Name is required.")
    if status_type not in StatusType.__members__:
        return _toast(request, False, "Unknown status type.")
    dup = (
        await db.execute(select(StatusLabel.id).where(StatusLabel.name == name, StatusLabel.id != item_id))
    ).first()
    if dup:
        return _toast(request, False, f"'{name}' already exists.")
    row.name = name
    row.status_type = StatusType(status_type)
    db.add(
        AuditLog(user_id=user.id, action="update", entity_type="status_label", entity_id=str(item_id), detail=name)
    )
    await db.commit()
    return _toast(request, True, f"Updated {name}.")


@router.post("/status-labels/{item_id}/delete", response_class=HTMLResponse)
async def status_labels_delete(
    request: Request,
    item_id: int,
    user: CurrentUser = Depends(require("catalog.manage")),
    db: AsyncSession = Depends(get_db),
):
    ok, err = await _delete_named(db, StatusLabel, item_id, user, "status_label")
    if not ok:
        return _toast(request, False, err)
    return _refresh()


# ---- models (name + manufacturer + category + optional overrides) ----

def _parse_optional_int(value: str, field: str):
    value = (value or "").strip()
    if not value:
        return None, None
    if not value.lstrip("-").isdigit() or int(value) < 0:
        return None, f"{field} must be a whole number of months."
    return int(value), None


async def _models_form_context(db: AsyncSession) -> dict:
    manufacturers = (await db.execute(select(Manufacturer).order_by(Manufacturer.name))).scalars().all()
    categories = (await db.execute(select(Category).order_by(Category.name))).scalars().all()
    return {"manufacturers": manufacturers, "categories": categories}


@router.get("/models", response_class=HTMLResponse)
async def models_list(
    request: Request,
    user: CurrentUser = Depends(require("catalog.view")),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        (
            await db.execute(
                select(AssetModel)
                .options(selectinload(AssetModel.manufacturer), selectinload(AssetModel.category))
                .order_by(AssetModel.name)
            )
        )
        .scalars()
        .all()
    )
    ctx = await _models_form_context(db)
    ctx.update(
        {
            "user": user,
            "rows": rows,
            "active_tab": "models",
            "can_manage": user.can("catalog.manage"),
        }
    )
    return templates.TemplateResponse(request, "catalog/models.html", ctx)


@router.post("/models/create", response_class=HTMLResponse)
async def models_create(
    request: Request,
    name: str = Form(...),
    manufacturer_id: int = Form(...),
    category_id: int = Form(...),
    depreciation_months: str = Form(""),
    eol_months: str = Form(""),
    user: CurrentUser = Depends(require("catalog.manage")),
    db: AsyncSession = Depends(get_db),
):
    name = name.strip()
    if not name:
        return _toast(request, False, "Name is required.")
    if await db.get(Manufacturer, manufacturer_id) is None:
        return _toast(request, False, "Unknown manufacturer.")
    if await db.get(Category, category_id) is None:
        return _toast(request, False, "Unknown category.")
    dep, err = _parse_optional_int(depreciation_months, "Depreciation")
    if err:
        return _toast(request, False, err)
    eol, err = _parse_optional_int(eol_months, "EOL")
    if err:
        return _toast(request, False, err)
    dup = (
        await db.execute(
            select(AssetModel.id).where(
                AssetModel.name == name, AssetModel.manufacturer_id == manufacturer_id
            )
        )
    ).first()
    if dup:
        return _toast(request, False, f"'{name}' already exists for this manufacturer.")

    row = AssetModel(
        name=name,
        manufacturer_id=manufacturer_id,
        category_id=category_id,
        depreciation_months=dep,
        eol_months=eol,
    )
    db.add(row)
    await db.flush()
    db.add(AuditLog(user_id=user.id, action="create", entity_type="model", entity_id=str(row.id), detail=name))
    await db.commit()
    return _refresh()


@router.post("/models/{item_id}/update", response_class=HTMLResponse)
async def models_update(
    request: Request,
    item_id: int,
    name: str = Form(...),
    manufacturer_id: int = Form(...),
    category_id: int = Form(...),
    depreciation_months: str = Form(""),
    eol_months: str = Form(""),
    user: CurrentUser = Depends(require("catalog.manage")),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(AssetModel, item_id)
    if row is None:
        return _toast(request, False, "Not found.")
    name = name.strip()
    if not name:
        return _toast(request, False, "Name is required.")
    if await db.get(Manufacturer, manufacturer_id) is None:
        return _toast(request, False, "Unknown manufacturer.")
    if await db.get(Category, category_id) is None:
        return _toast(request, False, "Unknown category.")
    dep, err = _parse_optional_int(depreciation_months, "Depreciation")
    if err:
        return _toast(request, False, err)
    eol, err = _parse_optional_int(eol_months, "EOL")
    if err:
        return _toast(request, False, err)
    dup = (
        await db.execute(
            select(AssetModel.id).where(
                AssetModel.name == name,
                AssetModel.manufacturer_id == manufacturer_id,
                AssetModel.id != item_id,
            )
        )
    ).first()
    if dup:
        return _toast(request, False, f"'{name}' already exists for this manufacturer.")

    row.name = name
    row.manufacturer_id = manufacturer_id
    row.category_id = category_id
    row.depreciation_months = dep
    row.eol_months = eol
    db.add(AuditLog(user_id=user.id, action="update", entity_type="model", entity_id=str(item_id), detail=name))
    await db.commit()
    return _toast(request, True, f"Updated {name}.")


@router.post("/models/{item_id}/delete", response_class=HTMLResponse)
async def models_delete(
    request: Request,
    item_id: int,
    user: CurrentUser = Depends(require("catalog.manage")),
    db: AsyncSession = Depends(get_db),
):
    ok, err = await _delete_named(db, AssetModel, item_id, user, "model")
    if not ok:
        return _toast(request, False, err)
    return _refresh()
