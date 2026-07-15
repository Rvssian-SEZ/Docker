"""Email notifications: SMTP send + per-user event subscriptions.

Every send happens from a BackgroundTask or the daily scheduler tick
(app/main.py) — never inline in a request, and always with PRIMITIVE
args only (ids/strings), never ORM objects, since the request's session
is closed by the time a background task runs. Each function here opens
its own short-lived session instead of being handed one.

v1 lesson (see CLAUDE.md): aiosmtplib attempts AUTH even on port 25 if
given empty-string credentials — pass username=None/password=None
explicitly for an unauthenticated relay. `store.get(...) or None`
converts the settings store's "" default into a real None for this.

v2 lesson: smtp.security ("none"/"starttls"/"tls") must map to explicit
use_tls/start_tls kwargs, not be inferred — plaintext-then-upgrade
(STARTTLS, port 587) and implicit-TLS-from-the-start (port 465) are
different wire protocols, and guessing wrong produces a hard-to-read
transport error (WRONG_VERSION_NUMBER against O365:587 was aiosmtplib
speaking plaintext at a socket the server expected a TLS ClientHello on).

smtp.auth_mode ("basic"/"oauth2") is a second, orthogonal axis: "basic"
is everything above (aiosmtplib's own convenience send(), username/
password AUTH or none at all). "oauth2" is Microsoft 365 XOAUTH2
(client-credentials, see app/core/smtp_oauth2.py) and bypasses
aiosmtplib.send() entirely — it needs a raw aiosmtplib.SMTP session so
the SASL exchange can be driven by hand (aiosmtplib has no built-in
XOAUTH2 mechanism). oauth2 mode always does STARTTLS regardless of
smtp.security's value: that setting exists for basic mode's
none/starttls/tls choice, but M365's OAuth2 SMTP submission endpoint
only ever speaks STARTTLS on 587, so there's nothing to choose there.

Two kinds of recipient for an event:
- Direct: the specific user a checkout/checkin was performed against,
  notified regardless of subscription (an operational notice about
  their own asset, not a broadcast).
- Subscribed: any user who both (a) checked the event's box on
  /profile and (b) holds the permission EVENT_TYPES maps it to — a
  subscription alone isn't enough, so a role downgrade can't leave
  someone receiving alerts about data they can no longer see.
"""

import logging

import aiosmtplib
from email.message import EmailMessage

from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.models import NotificationEvent, NotificationSubscription, RolePermission, User
from app.core.settings_store import SettingsStore, load_settings
from app.core.smtp_oauth2 import get_access_token, xoauth2_authenticate

logger = logging.getLogger(__name__)

# smtp.security value -> (use_tls, start_tls) kwargs for aiosmtplib.send.
# Explicit for all three so nothing is left to aiosmtplib's own
# port-based auto-detection.
SMTP_SECURITY_MODES: dict[str, tuple[bool, bool]] = {
    "none": (False, False),
    "starttls": (False, True),
    "tls": (True, False),
}

# event key -> (display label, permission required to receive it)
EVENT_TYPES: list[dict[str, str]] = [
    {"key": NotificationEvent.checkout_performed.value, "label": "Asset checked out", "permission": "assets.view"},
    {"key": NotificationEvent.checkin_performed.value, "label": "Asset checked in", "permission": "assets.view"},
    {"key": NotificationEvent.warranty_expiring.value, "label": "Warranty expiring soon", "permission": "assets.view"},
    {"key": NotificationEvent.contract_renewal_due.value, "label": "Contract renewal due", "permission": "contracts.view"},
    {"key": NotificationEvent.inventory_low_stock.value, "label": "Inventory low stock", "permission": "inventory.view"},
]
EVENT_PERMISSION = {e["key"]: e["permission"] for e in EVENT_TYPES}


async def send_email_raising(to_address: str, subject: str, body: str) -> None:
    """Does the actual SMTP conversation; lets exceptions propagate. Only
    call this directly where the caller wants to know if it failed (the
    Settings test-send button) — everything else goes through
    send_email(), which never raises."""
    if not to_address:
        raise ValueError("No recipient address given.")
    async with SessionLocal() as db:
        store = await load_settings(db)
    if not store.get_bool("smtp.enabled"):
        raise RuntimeError("SMTP is not enabled in Settings → Notifications.")
    if not store.get("smtp.host"):
        raise RuntimeError("SMTP host is not configured.")

    from_address = store.get("smtp.from_address") or "itops2@localhost"
    message = EmailMessage()
    message["From"] = from_address
    message["To"] = to_address
    message["Subject"] = subject
    message.set_content(body)

    if store.get("smtp.auth_mode") == "oauth2":
        await _send_via_oauth2(message, from_address, store)
        return

    use_tls, start_tls = SMTP_SECURITY_MODES.get(store.get("smtp.security"), (False, False))
    await aiosmtplib.send(
        message,
        hostname=store.get("smtp.host"),
        port=store.get_int("smtp.port"),
        username=store.get("smtp.username") or None,
        password=store.get("smtp.password") or None,
        use_tls=use_tls,
        start_tls=start_tls,
    )


async def _send_via_oauth2(message: EmailMessage, from_address: str, store: SettingsStore) -> None:
    """The XOAUTH2 send path: aiosmtplib.send()'s convenience wrapper has
    no way to plug in a custom AUTH mechanism, so this drives a raw
    aiosmtplib.SMTP session by hand instead — connect plaintext, STARTTLS
    (always, regardless of smtp.security — see module docstring),
    re-EHLO to refresh the post-TLS capability list, authenticate via
    the manual SASL exchange in smtp_oauth2.py, then send. The
    connection is always closed via quit() in a finally, even when
    authentication itself fails, so a bad token/secret doesn't leak a
    half-open socket."""
    tenant_id = store.get("smtp.oauth2_tenant_id")
    client_id = store.get("smtp.oauth2_client_id")
    client_secret = store.get("smtp.oauth2_client_secret")
    if not (tenant_id and client_id and client_secret):
        raise RuntimeError("OAuth2 tenant ID, client ID, and client secret must all be configured.")

    token = await get_access_token(tenant_id, client_id, client_secret)

    smtp = aiosmtplib.SMTP(
        hostname=store.get("smtp.host"), port=store.get_int("smtp.port"),
        use_tls=False, start_tls=False,
    )
    await smtp.connect()
    try:
        await smtp.starttls()
        await smtp.ehlo()
        await xoauth2_authenticate(smtp, from_address, token)
        await smtp.send_message(message)
    finally:
        try:
            await smtp.quit()
        except Exception:
            pass


async def send_email(to_address: str, subject: str, body: str) -> None:
    """Fire-and-forget send for BackgroundTasks/the daily scheduler:
    swallows and logs failures rather than raising — a notification
    failing must never surface as a user-facing error in whatever
    request queued it."""
    try:
        await send_email_raising(to_address, subject, body)
    except Exception:
        logger.exception("Failed to send notification email to %s", to_address)


async def subscribed_recipients(event: str) -> list[str]:
    """Emails of active users subscribed to `event` who also hold the
    permission it requires (EVENT_PERMISSION)."""
    permission = EVENT_PERMISSION[event]
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(User.email)
                .join(NotificationSubscription, NotificationSubscription.user_id == User.id)
                .join(RolePermission, RolePermission.role_id == User.role_id)
                .where(
                    NotificationSubscription.event_type == event,
                    RolePermission.permission == permission,
                    User.is_active.is_(True),
                    User.email.isnot(None),
                    User.email != "",
                )
                .distinct()
            )
        ).scalars().all()
    return list(rows)


async def notify_event(event: str, subject: str, body: str, extra_recipients: list[str] | None = None) -> None:
    """Send to every subscribed+permissioned user plus any direct
    recipients (e.g. a checkout's target user), de-duplicated."""
    recipients = set(await subscribed_recipients(event))
    recipients.update(r for r in (extra_recipients or []) if r)
    for address in recipients:
        await send_email(address, subject, body)


async def notify_checkout(asset_tag: str, target_user_email: str | None) -> None:
    await notify_event(
        NotificationEvent.checkout_performed.value,
        f"Asset checked out: {asset_tag}",
        f"Asset {asset_tag} has just been checked out.",
        extra_recipients=[target_user_email] if target_user_email else None,
    )


async def notify_checkin(asset_tag: str, target_user_email: str | None) -> None:
    await notify_event(
        NotificationEvent.checkin_performed.value,
        f"Asset checked in: {asset_tag}",
        f"Asset {asset_tag} has just been checked in.",
        extra_recipients=[target_user_email] if target_user_email else None,
    )
