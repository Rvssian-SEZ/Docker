"""Parses v1's free-text money fields ("1000 SCR", "£200", "Rs
10000.00", "1,500") into (amount, currency) for the Phase 9 import
wizard. Real v1 samples (inspected live before writing this) are the
source of truth for these rules, not guesswork:
"", "500", "1000 SCR", "Rs 10000.00", "90000.00 USD", "$30000",
"250 GBP", "6000".

A bare number with no currency symbol or ISO code is NEVER defaulted
to general.default_currency — flagged for manual review instead, same
"never silently wrong" rule this app already applies to money
everywhere else (e.g. the Printers cost total excluding, not guessing,
a record with no applicable exchange rate).
"""

import json
import logging
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

logger = logging.getLogger(__name__)

_TRAILING_CODE_RE = re.compile(r"^(.*\S)\s+([A-Z]{3})$")


@dataclass
class ParsedMoney:
    amount: Decimal | None
    currency: str | None
    needs_review: bool
    raw: str


def load_symbol_map(raw_json: str) -> dict[str, str]:
    """Same defensive-JSON-parse pattern as oidc.py's
    resolve_role()/auth.oidc.group_role_map: malformed JSON logs and
    falls back to an empty map rather than crashing the import."""
    raw_json = (raw_json or "").strip()
    if not raw_json:
        return {}
    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError:
        logger.error("import.currency_symbol_map is not valid JSON; ignoring")
        return {}
    if not isinstance(parsed, dict):
        logger.error("import.currency_symbol_map is not a JSON object; ignoring")
        return {}
    return {str(k): str(v) for k, v in parsed.items()}


def parse_v1_money(raw: str | None, symbol_map: dict[str, str]) -> ParsedMoney:
    original = raw or ""
    s = original.strip()
    if not s:
        return ParsedMoney(None, None, False, original)

    currency: str | None = None

    # 1. Trailing 3-letter uppercase ISO code ("1000 SCR", "90000.00 USD").
    m = _TRAILING_CODE_RE.match(s)
    if m:
        s, currency = m.group(1), m.group(2)
    else:
        # 2. Leading symbol ("$30000", "£200", "Rs 10000.00") -- longest
        # key first so e.g. a hypothetical "R" entry can't shadow "Rs".
        for symbol in sorted(symbol_map, key=len, reverse=True):
            if s.startswith(symbol):
                currency = symbol_map[symbol]
                s = s[len(symbol):].strip()
                break

    # Thousands separator ("1,500") stripped before numeric parse --
    # this app is UK/English-only (CLAUDE.md), comma-as-thousands is
    # the only convention v1 data actually uses.
    number_str = s.replace(",", "").strip()
    try:
        amount = Decimal(number_str)
    except InvalidOperation:
        return ParsedMoney(None, None, True, original)

    if currency is None:
        # Bare number, no symbol or code anywhere in the string --
        # flagged, never defaulted.
        return ParsedMoney(amount, None, True, original)

    return ParsedMoney(amount, currency, False, original)
