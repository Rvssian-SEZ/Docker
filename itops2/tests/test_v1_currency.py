"""app/core/v1_currency.py -- parsed against the REAL v1 sample strings
found by live-inspecting the actual v1 database before this was
written (see the Phase 9 design doc), plus the two examples Alex gave
by hand ("1,500", "£200").
"""

from decimal import Decimal

import pytest

from app.core.v1_currency import load_symbol_map, parse_v1_money

SYMBOL_MAP = {"$": "USD", "£": "GBP", "€": "EUR", "Rs": "SCR"}


def test_load_symbol_map_parses_valid_json():
    assert load_symbol_map('{"$": "USD", "£": "GBP"}') == {"$": "USD", "£": "GBP"}


def test_load_symbol_map_empty_string_returns_empty_dict():
    assert load_symbol_map("") == {}


def test_load_symbol_map_malformed_json_falls_back_to_empty_dict():
    assert load_symbol_map("{not valid json") == {}


def test_load_symbol_map_non_object_json_falls_back_to_empty_dict():
    assert load_symbol_map('["$", "USD"]') == {}


@pytest.mark.parametrize(
    "raw,expected_amount,expected_currency,expected_needs_review",
    [
        ("", None, None, False),
        ("   ", None, None, False),
        ("500", Decimal("500"), None, True),
        ("6000", Decimal("6000"), None, True),
        ("1000 SCR", Decimal("1000"), "SCR", False),
        ("300 SCR", Decimal("300"), "SCR", False),
        ("250 USD", Decimal("250"), "USD", False),
        ("250 GBP", Decimal("250"), "GBP", False),
        ("90000.00 USD", Decimal("90000.00"), "USD", False),
        ("Rs 10000.00", Decimal("10000.00"), "SCR", False),
        ("Rs 70000.00", Decimal("70000.00"), "SCR", False),
        ("$30000", Decimal("30000"), "USD", False),
        ("£200", Decimal("200"), "GBP", False),
        ("1,500", Decimal("1500"), None, True),
        ("£1,500", Decimal("1500"), "GBP", False),
        ("not a number", None, None, True),
    ],
)
def test_parse_v1_money_real_and_example_samples(raw, expected_amount, expected_currency, expected_needs_review):
    result = parse_v1_money(raw, SYMBOL_MAP)
    assert result.amount == expected_amount
    assert result.currency == expected_currency
    assert result.needs_review is expected_needs_review
    assert result.raw == raw


def test_parse_v1_money_preserves_raw_string_even_when_flagged():
    """The original string must survive even for a bare-number flag --
    it's what the manual review queue shows the admin, never silently
    discarded."""
    result = parse_v1_money("6000", SYMBOL_MAP)
    assert result.needs_review is True
    assert result.raw == "6000"


def test_parse_v1_money_with_no_symbol_map_still_handles_iso_codes():
    """The trailing-3-letter-code path doesn't depend on the symbol
    map at all -- only the leading-symbol path does."""
    result = parse_v1_money("1000 SCR", {})
    assert result.amount == Decimal("1000")
    assert result.currency == "SCR"
    assert result.needs_review is False


def test_parse_v1_money_unmapped_symbol_is_flagged_not_guessed():
    result = parse_v1_money("€500", {"$": "USD"})  # € not in this map
    assert result.currency is None
    assert result.needs_review is True
