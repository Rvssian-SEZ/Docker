from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from core.currency import CURRENCIES, DEFAULT_CURRENCY

router = APIRouter()


@router.post("/currency")
def set_currency(
    request: Request,
    currency: str = Form(...),
):
    if currency in CURRENCIES:
        request.session["currency"] = currency
    # Redirect back to where the user came from
    referer = request.headers.get("referer", "/")
    return RedirectResponse(referer, status_code=302)
