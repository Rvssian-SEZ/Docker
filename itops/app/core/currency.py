"""Currency preferences — stored in session, defaulting to SCR."""

from fastapi import Request

CURRENCIES = {
    "SCR": {"symbol": "₨", "name": "Seychelles Rupee", "code": "SCR"},
    "USD": {"symbol": "$", "name": "US Dollar", "code": "USD"},
    "GBP": {"symbol": "£", "name": "Pound Sterling", "code": "GBP"},
}

DEFAULT_CURRENCY = "SCR"


def get_currency(request: Request) -> dict:
    """Return the current currency dict from session."""
    code = request.session.get("currency", DEFAULT_CURRENCY)
    return CURRENCIES.get(code, CURRENCIES[DEFAULT_CURRENCY])


def all_currencies() -> dict:
    return CURRENCIES
