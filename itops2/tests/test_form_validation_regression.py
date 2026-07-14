"""Regression tests for the Form(...) / 422 gap (see CLAUDE.md): posting
a missing required field to any htmx-driven route must come back as a
friendly toast, never FastAPI's raw JSON 422 body -- htmx can't render
JSON into the toast area, so that used to be a silent dead end.

One test per router named in the audit (assets, checkout, maintenance,
attachments, users, catalog, settings), plus one that specifically
exercises the global RequestValidationError handler (defense in depth)
via a field that's present but malformed -- the per-route Form("")
fixes only cover "missing", not "wrong type", so this is the only way
to prove the handler itself works, not just the per-route validation.
"""

from sqlalchemy import select

from app.core.models import Asset, AssetModel, Category, Manufacturer, StatusLabel, StatusType


def _not_raw_json(resp) -> bool:
    return not resp.text.lstrip().startswith('{"detail"')


async def _make_asset(db, tag="IT-RV01"):
    mfr = Manufacturer(name=f"Dell-{tag}")
    cat = Category(name=f"Laptop-{tag}")
    db.add_all([mfr, cat])
    await db.flush()
    model = AssetModel(name="Latitude 5440", manufacturer_id=mfr.id, category_id=cat.id)
    deployable = (
        await db.execute(select(StatusLabel).where(StatusLabel.name == "Ready to Deploy"))
    ).scalar_one_or_none()
    if deployable is None:
        deployable = StatusLabel(name="Ready to Deploy", status_type=StatusType.deployable)
        db.add(deployable)
        await db.flush()
    db.add(model)
    await db.flush()
    asset = Asset(asset_tag=tag, model_id=model.id, status_label_id=deployable.id)
    db.add(asset)
    await db.commit()
    return asset


async def test_assets_missing_model_id_returns_toast(admin_client, db):
    # model_id and status_label_id both omitted entirely (not sent as
    # empty strings) -- unambiguously exercises the Form(None) default,
    # not Pydantic's empty-string-to-int coercion behavior.
    resp = await admin_client.post("/assets/create", data={"serial": "SN-1"})
    assert resp.status_code == 200
    assert "text-bg-danger" in resp.text
    assert _not_raw_json(resp)


async def test_checkout_missing_status_label_id_returns_toast(admin_client, db):
    asset = await _make_asset(db)
    resp = await admin_client.post(f"/assets/{asset.id}/checkout", data={"target_location_id": ""})
    assert resp.status_code == 200
    assert "text-bg-danger" in resp.text
    assert _not_raw_json(resp)


async def test_maintenance_missing_description_returns_toast(admin_client, db):
    asset = await _make_asset(db)
    resp = await admin_client.post(
        f"/assets/{asset.id}/maintenance/create",
        data={"date": "2026-01-15", "maintenance_type": "repair"},
    )
    assert resp.status_code == 200
    assert "text-bg-danger" in resp.text
    assert _not_raw_json(resp)


async def test_attachment_upload_missing_file_returns_toast(admin_client, db):
    asset = await _make_asset(db)
    resp = await admin_client.post(f"/assets/{asset.id}/attachments", data={"description": "no file attached"})
    assert resp.status_code == 200
    assert "text-bg-danger" in resp.text
    assert "no file selected" in resp.text.lower()
    assert _not_raw_json(resp)


async def test_users_missing_role_id_returns_toast(admin_client, db):
    resp = await admin_client.post(
        "/users/create", data={"username": "regressiontest", "password": "supersecret123"},
    )
    assert resp.status_code == 200
    assert "text-bg-danger" in resp.text
    assert _not_raw_json(resp)


async def test_catalog_missing_name_returns_toast(admin_client, db):
    resp = await admin_client.post("/catalog/manufacturers/create", data={})
    assert resp.status_code == 200
    assert "text-bg-danger" in resp.text
    assert _not_raw_json(resp)


async def test_settings_currency_missing_symbol_returns_toast(admin_client, db):
    resp = await admin_client.post("/settings/currency/create", data={"code": "ZZZ"})
    assert resp.status_code == 200
    assert "text-bg-danger" in resp.text
    assert _not_raw_json(resp)


async def test_global_handler_catches_malformed_int_field(admin_client, db):
    """The per-route Form("") fixes only cover a field being absent --
    a present-but-wrong-type value (e.g. model_id=notanumber) still fails
    FastAPI's own request validation before the route body runs. This is
    the one case only the global RequestValidationError handler catches.

    The handler only special-cases requests carrying the HX-Request
    header (what htmx.js actually sends) -- admin_client is a plain
    httpx client, so the header must be set explicitly to simulate a
    real htmx-driven request."""
    resp = await admin_client.post(
        "/assets/create",
        data={"model_id": "not-a-number", "status_label_id": "1"},
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 200
    assert "text-bg-danger" in resp.text
    assert _not_raw_json(resp)


async def test_non_htmx_request_keeps_default_422(admin_client, db):
    """Without the HX-Request header (e.g. a non-browser API client), the
    handler must fall through to FastAPI's normal 422 -- the graceful
    toast is a courtesy for the app's own htmx-driven UI, not a blanket
    behavior change for every client."""
    resp = await admin_client.post(
        "/assets/create", data={"model_id": "not-a-number", "status_label_id": "1"},
    )
    assert resp.status_code == 422
    assert resp.text.lstrip().startswith('{"detail"')
