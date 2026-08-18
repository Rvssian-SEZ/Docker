"""Internal, unauthenticated-by-design callback for LAPS password delivery.

Not user-facing — called by the Ansible task running on a DC (see
SAA/playbooks/admin_read_laps_password.yml in the Semaphore repo), which
has no session cookie to present. Security comes from the token itself:
generated per-request (32 bytes, unguessable), single-use, ~30s TTL, and
rejected outright if it doesn't match a pending request app/core/ad_accounts.py
is actively waiting on (see app/core/laps_pending.py). This is the same
trust model as any webhook-style callback — the token IS the credential.
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core import laps_pending

router = APIRouter()


@router.post("/internal/laps-callback/{token}")
async def laps_callback(token: str, request: Request):
    body = await request.json()
    password = body.get("password", "")
    expiration = body.get("expiration", "")
    ok = laps_pending.deliver(token, password=password, expiration=expiration)
    if not ok:
        # Unknown/expired/already-consumed token — never reveals which,
        # so this endpoint can't be used to probe for valid tokens.
        return JSONResponse({"status": "rejected"}, status_code=404)
    return JSONResponse({"status": "accepted"})
