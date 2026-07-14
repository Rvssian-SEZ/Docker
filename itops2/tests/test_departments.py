"""Departments (Phase 9 chunk 1): a Catalog lookup tightly scoped to
Users -- name + optional company_id, unique per (name, company_id) not
globally. core_departments is NOT in conftest's TRUNCATE_TABLES (see
that file's comment) since core_users.department_id FKs to it and users
are never truncated -- every test here uses a unique department name.
"""

from sqlalchemy import select

from app.core.models import Company, Department


async def test_create_department_without_company(admin_client, db):
    resp = await admin_client.post("/catalog/departments/create", data={"name": "Dept-NoCoA"})
    assert resp.status_code == 204
    row = (await db.execute(select(Department).where(Department.name == "Dept-NoCoA"))).scalar_one()
    assert row.company_id is None


async def test_create_department_requires_name(admin_client, db):
    resp = await admin_client.post("/catalog/departments/create", data={"name": ""})
    assert "text-bg-danger" in resp.text
    assert "name" in resp.text.lower()


async def test_same_name_allowed_across_different_companies(admin_client, db):
    co_a = Company(name="Dept-Test-Co-A")
    co_b = Company(name="Dept-Test-Co-B")
    db.add_all([co_a, co_b])
    await db.commit()

    first = await admin_client.post(
        "/catalog/departments/create", data={"name": "Dept-IT-Shared", "company_id": co_a.id},
    )
    assert first.status_code == 204
    second = await admin_client.post(
        "/catalog/departments/create", data={"name": "Dept-IT-Shared", "company_id": co_b.id},
    )
    assert second.status_code == 204

    rows = (await db.execute(select(Department).where(Department.name == "Dept-IT-Shared"))).scalars().all()
    assert len(rows) == 2
    assert {r.company_id for r in rows} == {co_a.id, co_b.id}


async def test_duplicate_name_within_same_company_rejected(admin_client, db):
    co = Company(name="Dept-Test-Co-Dup")
    db.add(co)
    await db.commit()

    await admin_client.post("/catalog/departments/create", data={"name": "Dept-Finance", "company_id": co.id})
    dup = await admin_client.post("/catalog/departments/create", data={"name": "Dept-Finance", "company_id": co.id})
    assert "text-bg-danger" in dup.text
    assert "already exists" in dup.text.lower()


async def test_duplicate_name_with_no_company_rejected(admin_client, db):
    await admin_client.post("/catalog/departments/create", data={"name": "Dept-NoCoDup"})
    dup = await admin_client.post("/catalog/departments/create", data={"name": "Dept-NoCoDup"})
    assert "text-bg-danger" in dup.text
    assert "already exists" in dup.text.lower()


async def test_update_department_name_and_company(admin_client, db):
    co = Company(name="Dept-Test-Co-Update")
    db.add(co)
    await db.commit()
    await admin_client.post("/catalog/departments/create", data={"name": "Dept-Original"})
    row = (await db.execute(select(Department).where(Department.name == "Dept-Original"))).scalar_one()

    resp = await admin_client.post(
        f"/catalog/departments/{row.id}/update", data={"name": "Dept-Renamed", "company_id": co.id},
    )
    assert resp.status_code == 200
    assert "text-bg-success" in resp.text
    await db.refresh(row)
    assert row.name == "Dept-Renamed"
    assert row.company_id == co.id


async def test_delete_department_blocked_while_referenced_by_a_user(admin_client, db):
    """Same FK-guard-with-friendly-toast pattern as every other Catalog
    entity -- a department can't vanish out from under a user still
    pointing at it."""
    from app.core.models import AuthSource, Role, RoleName, User
    from app.core.security import hash_password

    await admin_client.post("/catalog/departments/create", data={"name": "Dept-Referenced"})
    row = (await db.execute(select(Department).where(Department.name == "Dept-Referenced"))).scalar_one()

    viewer_role = (await db.execute(select(Role).where(Role.name == RoleName.viewer))).scalar_one()
    db.add(
        User(
            username="dept-ref-user", auth_source=AuthSource.local, password_hash=hash_password("supersecret123"),
            role_id=viewer_role.id, department_id=row.id,
        )
    )
    await db.commit()

    resp = await admin_client.post(f"/catalog/departments/{row.id}/delete")
    assert "text-bg-danger" in resp.text
    assert "still in use" in resp.text.lower()
    assert (await db.execute(select(Department).where(Department.id == row.id))).scalar_one_or_none() is not None


async def test_delete_unreferenced_department_succeeds(admin_client, db):
    await admin_client.post("/catalog/departments/create", data={"name": "Dept-Deletable"})
    row = (await db.execute(select(Department).where(Department.name == "Dept-Deletable"))).scalar_one()

    resp = await admin_client.post(f"/catalog/departments/{row.id}/delete")
    assert resp.status_code == 204
    assert (await db.execute(select(Department).where(Department.id == row.id))).scalar_one_or_none() is None
