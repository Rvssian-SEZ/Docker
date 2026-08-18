"""Short-lived, single-use handoff slots for LAPS password delivery.

The password never travels through Semaphore's persistent task output
(see SAA/playbooks/admin_read_laps_password.yml in the Semaphore repo for
why) - instead the Ansible task running on the DC POSTs it directly to
/internal/laps-callback/{token}, and the request that triggered the
Semaphore run is awaiting exactly that token here. In-memory only (no
DB row, nothing to ever accidentally retain): a token is consumed and
deleted the instant it's read, and unclaimed tokens expire and are swept
so a crashed/timed-out request can never be replayed later.
"""

import asyncio
import secrets
import time

_TTL_SECONDS = 30
_pending: dict[str, dict] = {}


def create() -> tuple[str, asyncio.Event]:
    token = secrets.token_urlsafe(32)
    event = asyncio.Event()
    _pending[token] = {"event": event, "result": None, "created_at": time.monotonic()}
    return token, event


def deliver(token: str, *, password: str, expiration: str) -> bool:
    """Called by the callback route. Returns False if the token is unknown
    or already expired/consumed (e.g. a retried/duplicate delivery, or an
    attacker guessing at the endpoint with no matching pending request)."""
    slot = _pending.get(token)
    if slot is None:
        return False
    if time.monotonic() - slot["created_at"] > _TTL_SECONDS:
        _pending.pop(token, None)
        return False
    slot["result"] = {"password": password, "expiration": expiration}
    slot["event"].set()
    return True


async def wait_and_consume(token: str, event: asyncio.Event, *, timeout: float) -> dict | None:
    """Waits for delivery (or timeout), then ALWAYS removes the slot -
    a token is usable exactly once, whether it succeeds, times out, or the
    caller gives up."""
    try:
        await asyncio.wait_for(event.wait(), timeout=timeout)
        slot = _pending.get(token)
        return slot["result"] if slot else None
    except asyncio.TimeoutError:
        return None
    finally:
        _pending.pop(token, None)
