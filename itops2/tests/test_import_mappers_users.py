"""app/core/import_mappers/users.py -- Users + Department/Location
synthesis, the first Phase 9 module mapper."""

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.import_mappers.users import import_users
from app.core.models import Department, ImportRowOutcome, Location, User, V1ImportRow
from tests.conftest import FakeV1Source, make_import_batch


def _users_source(rows):
    return FakeV1Source({"FROM users": rows})


async def test_creates_new_user_with_department_and_location_synthesis(db):
    batch = await make_import_batch(db)
    source = _users_source(
        [
            {
                "id": 1, "username": "jdoe", "email": "jdoe@example.com", "full_name": "Jane Doe",
                "phone": "555-1234", "department": "IT Support", "title": "Sysadmin",
                "location": "Victoria Office", "is_active": True,
            }
        ]
    )
    await import_users(db, source, batch)
    await db.commit()

    user = (
        await db.execute(select(User).options(selectinload(User.role)).where(User.username == "jdoe"))
    ).scalar_one()
    assert user.email == "jdoe@example.com"
    assert user.display_name == "Jane Doe"
    assert user.phone == "555-1234"
    assert user.job_title == "Sysadmin"
    assert user.auth_source.value == "oidc"
    assert user.role.name.value == "viewer"
    assert user.is_active is True

    dept = (await db.execute(select(Department).where(Department.name == "IT Support"))).scalar_one()
    assert user.department_id == dept.id

    loc = (await db.execute(select(Location).where(Location.name == "Victoria Office"))).scalar_one_or_none()
    assert loc is not None  # seeded for later mappers even though User has no location_id

    import_row = (await db.execute(select(V1ImportRow).where(V1ImportRow.v1_table == "users"))).scalar_one()
    assert import_row.outcome == ImportRowOutcome.created
    assert import_row.v2_entity_id == user.id
    assert import_row.is_dry_run is False


async def test_matches_existing_user_by_username_and_backfills_only_nulls(db):
    from app.core.models import AuthSource, Role, RoleName

    role_id = (await db.execute(select(Role.id).where(Role.name == RoleName.technician))).scalar_one()
    existing = User(
        username="already.there", auth_source=AuthSource.oidc, role_id=role_id,
        phone="ORIGINAL-PHONE", job_title=None, is_active=True,
    )
    db.add(existing)
    await db.flush()
    existing_id = existing.id

    batch = await make_import_batch(db)
    source = _users_source(
        [
            {
                "id": 2, "username": "already.there", "email": "x@example.com", "full_name": "X",
                "phone": "V1-PHONE-SHOULD-NOT-OVERWRITE", "department": None, "title": "V1 Title",
                "location": None, "is_active": True,
            }
        ]
    )
    await import_users(db, source, batch)
    await db.commit()

    await db.refresh(existing, attribute_names=["phone", "job_title", "role_id"])
    assert existing.phone == "ORIGINAL-PHONE"  # never overwritten
    assert existing.job_title == "V1 Title"  # backfilled, was NULL
    assert existing.role_id == role_id  # untouched -- import doesn't touch roles on match

    import_row = (
        await db.execute(select(V1ImportRow).where(V1ImportRow.v1_table == "users", V1ImportRow.v1_id == 2))
    ).scalar_one()
    assert import_row.outcome == ImportRowOutcome.skipped
    assert import_row.v2_entity_id == existing_id
    assert import_row.detail == "matched existing user 'already.there'; backfilled job_title"


async def test_blank_username_is_flagged_not_imported(db):
    batch = await make_import_batch(db)
    source = _users_source([{"id": 3, "username": "  ", "email": None, "full_name": None, "phone": None,
                              "department": None, "title": None, "location": None, "is_active": True}])
    await import_users(db, source, batch)
    await db.commit()

    import_row = (
        await db.execute(select(V1ImportRow).where(V1ImportRow.v1_table == "users", V1ImportRow.v1_id == 3))
    ).scalar_one()
    assert import_row.outcome == ImportRowOutcome.flagged
    assert import_row.v2_entity_id is None


async def test_dry_run_writes_no_target_rows_but_writes_import_rows(db):
    batch = await make_import_batch(db, dry_run=True)
    source = _users_source(
        [
            {
                "id": 4, "username": "preview.only", "email": None, "full_name": None, "phone": None,
                "department": "Ops", "title": None, "location": None, "is_active": True,
            }
        ]
    )
    await import_users(db, source, batch)
    await db.commit()

    assert (await db.execute(select(User).where(User.username == "preview.only"))).scalar_one_or_none() is None
    assert (await db.execute(select(Department).where(Department.name == "Ops"))).scalar_one_or_none() is None

    import_row = (
        await db.execute(select(V1ImportRow).where(V1ImportRow.v1_table == "users", V1ImportRow.v1_id == 4))
    ).scalar_one()
    assert import_row.outcome == ImportRowOutcome.created
    assert import_row.is_dry_run is True
    assert import_row.v2_entity_id is None
    assert "would create" in import_row.detail


async def test_department_synthesis_is_case_insensitive(db):
    dept = Department(name="Finance", company_id=None)
    db.add(dept)
    await db.flush()

    batch = await make_import_batch(db)
    source = _users_source(
        [
            {
                "id": 5, "username": "finance.user", "email": None, "full_name": None, "phone": None,
                "department": "FINANCE", "title": None, "location": None, "is_active": True,
            }
        ]
    )
    await import_users(db, source, batch)
    await db.commit()

    all_finance = (await db.execute(select(Department).where(Department.name.ilike("finance")))).scalars().all()
    assert len(all_finance) == 1

    user = (await db.execute(select(User).where(User.username == "finance.user"))).scalar_one()
    assert user.department_id == dept.id
