"""Maps v1 `users` rows to core_users, synthesizing Departments from
v1's free-text `department` column (and seeding the Location catalog
from `location` -- see the note below on why that one has no target
field on the user itself).

Identity match is on username ALONE, matching app/core/oidc.py's own
provision_user() -- v2's OIDC login already keys on username with no
subject-ID column, so importing under the same key means a user who
later logs in via SSO lands on exactly the row this mapper created or
matched, picking up its phone/job_title/department for free instead of
starting blank.

A username that already exists in v2 (e.g. someone already logged in
via SSO before the import ran) is matched, not duplicated -- only
currently-NULL phone/job_title/department_id fields are backfilled,
never overwritten, so the import can never silently clobber something
an admin (or a real OIDC login) already set. Same "never overwrite a
value that's already set" rule as the smtp.security migration.

A username with no v2 match is created fresh with auth_source=oidc
(v1 was pure Authentik SSO -- its users table has no password column
at all) and role=Viewer, the least-privileged role: it's a placeholder
only, since provision_user() re-syncs role_id from the user's actual
Authentik groups on their very first v2 login regardless of what this
import assigns.

v1's `location` free text has nowhere to attach on core_users (Users
got department_id only, not location_id, per the confirmed schema) --
but it still seeds the shared Location catalog (case-insensitive
dedup) so Printers/Inventory import later in the same run resolve the
same location string to the same row instead of creating a near-dupe.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.import_mappers.common import record_row, resolve_or_plan_department, resolve_or_plan_location
from app.core.models import AuthSource, ImportRowOutcome, Role, RoleName, User, V1ImportBatch


async def import_users(db: AsyncSession, source, batch: V1ImportBatch) -> None:
    dry_run = batch.dry_run
    dept_cache: dict = {}
    loc_cache: dict = {}
    viewer_role_id = (await db.execute(select(Role.id).where(Role.name == RoleName.viewer))).scalar_one()

    rows = await source.fetch(
        "SELECT id, username, email, full_name, phone, department, title, location, is_active "
        "FROM users ORDER BY id"
    )
    for row in rows:
        username = (row["username"] or "").strip()
        if not username:
            await record_row(
                db, batch, "users", row["id"], "user", None, ImportRowOutcome.flagged,
                "blank username -- cannot import (v2 identity is keyed on username)",
            )
            continue

        dept_id = None
        if row["department"]:
            dept_id, _ = await resolve_or_plan_department(db, dept_cache, row["department"], None, dry_run)
        if row["location"]:
            await resolve_or_plan_location(db, loc_cache, row["location"], dry_run)

        existing = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
        if existing is not None:
            backfilled = []
            if not dry_run:
                if existing.phone is None and row["phone"]:
                    existing.phone = row["phone"]
                    backfilled.append("phone")
                if existing.job_title is None and row["title"]:
                    existing.job_title = row["title"]
                    backfilled.append("job_title")
                if existing.department_id is None and dept_id is not None:
                    existing.department_id = dept_id
                    backfilled.append("department")
            detail = f"matched existing user '{username}'" + (
                f"; backfilled {', '.join(backfilled)}" if backfilled else "; no fields needed backfilling"
            )
            await record_row(db, batch, "users", row["id"], "user", existing.id, ImportRowOutcome.skipped, detail)
            continue

        if dry_run:
            await record_row(
                db, batch, "users", row["id"], "user", None, ImportRowOutcome.created,
                f"would create user '{username}' (auth_source=oidc, role=viewer)",
            )
            continue

        new_user = User(
            username=username,
            email=row["email"] or None,
            display_name=row["full_name"] or username,
            auth_source=AuthSource.oidc,
            role_id=viewer_role_id,
            phone=row["phone"] or None,
            job_title=row["title"] or None,
            department_id=dept_id,
            is_active=bool(row["is_active"]),
        )
        db.add(new_user)
        await db.flush()
        await record_row(
            db, batch, "users", row["id"], "user", new_user.id, ImportRowOutcome.created,
            f"created user '{username}'",
        )
