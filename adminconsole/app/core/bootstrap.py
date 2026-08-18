"""First-boot / startup seeding. Idempotent — safe on every startup:
- ensures the three fixed roles exist
- seeds default permission matrix for roles that have no rows yet (never
  overwrites an admin-tuned matrix)
- ensures the break-glass credential exists, IF FERNET_KEY is configured
  (its TOTP secret must be encrypted at rest — with no key, bootstrap
  logs a critical warning and leaves break-glass unusable rather than
  storing a TOTP seed in plaintext or refusing to start at all; this is
  the same "degrade to not-configured" contract Settings uses).
"""

import logging
import secrets

import pyotp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crypto
from app.core.breakglass import BREAKGLASS_ROW_ID
from app.core.config import get_settings
from app.core.models import BreakGlassCredential, Role, RoleName, RolePermission
from app.core.permissions import DEFAULTS
from app.core.security import hash_password

log = logging.getLogger(__name__)


async def bootstrap(db: AsyncSession) -> None:
    settings = get_settings()

    # --- Roles ---
    existing = {r.name: r for r in (await db.execute(select(Role))).scalars()}
    for role_name in RoleName:
        if role_name not in existing:
            role = Role(name=role_name, description=role_name.value.replace("_", " ").title())
            db.add(role)
            existing[role_name] = role
    await db.flush()

    # --- Default permission matrix (only for roles with zero rows) ---
    for role_name, role in existing.items():
        has_rows = (
            await db.execute(select(RolePermission.id).where(RolePermission.role_id == role.id).limit(1))
        ).first()
        if not has_rows:
            for perm in DEFAULTS[role_name]:
                db.add(RolePermission(role_id=role.id, permission=perm))
            log.info("Seeded default permissions for role %s", role_name.value)

    # --- Break-glass credential ---
    if crypto.is_configured():
        bg = await db.get(BreakGlassCredential, BREAKGLASS_ROW_ID)
        if bg is None:
            totp_secret = pyotp.random_base32()
            db.add(
                BreakGlassCredential(
                    id=BREAKGLASS_ROW_ID,
                    username=settings.breakglass_username,
                    password_hash=hash_password(settings.breakglass_password),
                    totp_secret_encrypted=crypto.encrypt(totp_secret),
                )
            )
            # Logged once, at creation only — this is a bootstrap
            # convenience, not how the credential should stay long-term.
            log.warning(
                "Created break-glass admin '%s'. Password is the BREAKGLASS_PASSWORD "
                "env value; TOTP secret is %s (add to an authenticator app now — "
                "this is the only time it is printed). Rotate both immediately.",
                settings.breakglass_username,
                totp_secret,
            )
    else:
        log.critical(
            "FERNET_KEY is not set — break-glass admin cannot be created/used until it "
            "is. Set FERNET_KEY and restart before relying on the break-glass path."
        )

    await db.commit()
