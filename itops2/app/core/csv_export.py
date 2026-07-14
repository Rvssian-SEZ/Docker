"""Shared CSV export helper for list-view Export buttons.

UTF-8 with a BOM (utf-8-sig) so Excel — which guesses ANSI/Windows-1252
without a BOM and mangles anything outside ASCII — opens the file
correctly without a manual "Import as UTF-8" step. UK date format
throughout, matching the rest of the app's locale (CLAUDE.md: "UK date
formats, English only").
"""

import csv
import io
from datetime import date, datetime

from fastapi.responses import Response


def fmt_date(value: date | None) -> str:
    return value.strftime("%d/%m/%Y") if value else ""


def fmt_datetime(value: datetime | None) -> str:
    return value.strftime("%d/%m/%Y %H:%M") if value else ""


def csv_response(filename: str, fieldnames: list[str], rows: list[dict]) -> Response:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        content=buf.getvalue().encode("utf-8-sig"),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
