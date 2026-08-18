"""Shared CSV export helper — UTF-8 BOM so Excel opens it without a
mangled-encoding prompt, same convention as itops2's own csv_export.py."""

import csv
import io

from fastapi.responses import StreamingResponse


def csv_response(rows: list[dict], *, filename: str) -> StreamingResponse:
    buf = io.StringIO()
    buf.write("﻿")
    if rows:
        writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
