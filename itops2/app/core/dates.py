"""Small date-arithmetic helpers with no external dependency
(no python-dateutil in requirements.txt)."""

from datetime import date


def add_months(d: date, months: int) -> date:
    """Calendar month arithmetic: rolls the year forward as needed and
    clamps the day into the target month (e.g. 31 Jan + 1 month ->
    28/29 Feb, not an invalid date)."""
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(
        d.day,
        [
            31,
            29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
            31, 30, 31, 30, 31, 31, 30, 31, 30, 31,
        ][month - 1],
    )
    return date(year, month, day)
