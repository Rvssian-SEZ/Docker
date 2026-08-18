"""Break-glass admin: bypasses Authentik entirely, local credential (bcrypt)
+ mandatory TOTP, usable when Authentik itself is down. Not a Role, not a
User row — see app/core/models.BreakGlassCredential and CLAUDE_CONTEXT.md.

Every login and every action taken while authenticated as break-glass
triggers alert() (app/core/alerting.py) in addition to the normal audit
row — callers in the AD/settings routers check
`request.session.get("breakglass")` and alert on every one of those routes,
not just at login.
"""

import ipaddress
import logging

import pyotp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt
from app.core.models import BreakGlassCredential
from app.core.security import verify_password
from app.core.settings_store import load_settings

logger = logging.getLogger(__name__)

BREAKGLASS_ROW_ID = 1


async def get_credential(db: AsyncSession) -> BreakGlassCredential | None:
    return await db.get(BreakGlassCredential, BREAKGLASS_ROW_ID)


async def ip_allowed(db: AsyncSession, client_ip: str | None) -> bool:
    """breakglass.ip_allowlist is a comma-separated CIDR list; empty means
    no restriction. An unparseable client_ip (e.g. behind a proxy without
    --forwarded-allow-ips configured right) fails closed, not open."""
    store = await load_settings(db)
    raw = store.get("breakglass.ip_allowlist").strip()
    if not raw:
        return True
    if not client_ip:
        return False
    try:
        addr = ipaddress.ip_address(client_ip)
    except ValueError:
        return False
    for cidr in (c.strip() for c in raw.split(",") if c.strip()):
        try:
            if addr in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            logger.warning("Invalid CIDR in breakglass.ip_allowlist: %s", cidr)
    return False


async def authenticate(db: AsyncSession, username: str, password: str, totp_code: str) -> bool:
    cred = await get_credential(db)
    if cred is None or cred.username != username:
        return False
    if not verify_password(password, cred.password_hash):
        return False
    secret = decrypt(cred.totp_secret_encrypted)
    if secret is None:
        logger.error("Break-glass TOTP secret could not be decrypted — FERNET_KEY missing/rotated?")
        return False
    return pyotp.TOTP(secret).verify(totp_code, valid_window=1)
