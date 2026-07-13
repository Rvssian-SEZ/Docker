"""First-boot / startup seeding.

Idempotent — safe to run on every startup:
- ensures the four fixed roles exist
- seeds default permission matrix for roles that have no rows yet
  (never overwrites an admin-tuned matrix)
- ensures the break-glass local admin exists and is active
- seeds SCR/USD/GBP/EUR currencies if missing (never touches existing rows)
"""

import logging

from app.core.security import hash_password
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.models import AuthSource, Currency, Role, RoleName, RolePermission, User
from app.core.permissions import DEFAULTS

DEFAULT_CURRENCIES = (("SCR", "SR"), ("USD", "$"), ("GBP", "£"), ("EUR", "€"))

log = logging.getLogger(__name__)


async def bootstrap(db: AsyncSession) -> None:
    settings = get_settings()

    # --- Roles ---
    existing = {r.name: r for r in (await db.execute(select(Role))).scalars()}
    for role_name in RoleName:
        if role_name not in existing:
            role = Role(name=role_name, description=role_name.value.title())
            db.add(role)
            existing[role_name] = role
    await db.flush()

    # --- Default permission matrix (only for roles with zero rows) ---
    for role_name, role in existing.items():
        has_rows = (
            await db.execute(
                select(RolePermission.id).where(RolePermission.role_id == role.id).limit(1)
            )
        ).first()
        if not has_rows:
            for perm in DEFAULTS[role_name]:
                db.add(RolePermission(role_id=role.id, permission=perm))
            log.info("Seeded default permissions for role %s", role_name.value)

    # --- Break-glass admin ---
    bg = (
        await db.execute(select(User).where(User.is_breakglass.is_(True)))
    ).scalar_one_or_none()
    if bg is None:
        db.add(
            User(
                username=settings.breakglass_username,
                display_name="Break-glass Admin",
                auth_source=AuthSource.local,
                password_hash=hash_password(settings.breakglass_password),
                role_id=existing[RoleName.admin].id,
                is_active=True,
                is_breakglass=True,
            )
        )
        log.warning(
            "Created break-glass admin '%s' — change the password immediately.",
            settings.breakglass_username,
        )
    else:
        bg.is_active = True  # break-glass can never be locked out

    # --- Default currencies (never overwrite an admin's active/symbol edits) ---
    existing_codes = {c for (c,) in (await db.execute(select(Currency.code))).all()}
    for code, symbol in DEFAULT_CURRENCIES:
        if code not in existing_codes:
            db.add(Currency(code=code, symbol=symbol, active=True))

    await db.commit()
