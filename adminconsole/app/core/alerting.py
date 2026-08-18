"""Out-of-band alerting for break-glass use and LAPS retrieval — the spec
requires these to trigger "an immediate out-of-band alert (email via your
Postfix relay, and/or webhook) — not just a log entry." This is deliberately
best-effort and never blocks or fails the action it's alerting about: a
down mail relay must not be a way to silently suppress the alert AND the
audit row (the audit row is written unconditionally by the caller,
regardless of whether this send succeeds — see app/core/audit.write_audit).

SMTP/webhook config comes from core Settings (smtp.*, breakglass.alert_*);
if neither is configured, alert() logs a warning and returns — no
exception ever reaches the caller.
"""

import logging

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings_store import load_settings

logger = logging.getLogger(__name__)


async def alert(db: AsyncSession, *, subject: str, body: str) -> None:
    store = await load_settings(db)
    sent = False

    to_addr = store.get("breakglass.alert_email").strip()
    from_addr = store.get("smtp.from_address").strip()
    host = store.get("smtp.host").strip()
    if to_addr and from_addr and host:
        try:
            import aiosmtplib
            from email.message import EmailMessage

            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = from_addr
            msg["To"] = to_addr
            msg.set_content(body)
            await aiosmtplib.send(
                msg,
                hostname=host,
                port=store.get_int("smtp.port"),
                username=None,
                password=None,
            )
            sent = True
        except Exception:
            logger.exception("Break-glass/LAPS alert email failed to send")

    webhook_url = store.get("breakglass.alert_webhook_url").strip()
    if webhook_url:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(webhook_url, json={"subject": subject, "body": body})
            sent = True
        except Exception:
            logger.exception("Break-glass/LAPS alert webhook failed to send")

    if not sent:
        logger.warning("ALERT (no channel configured): %s — %s", subject, body)
