"""Phase 9 chunk 1: phone/job_title/department_id on core_users --
create/update wiring and display on the Users page + /profile.
"""

from sqlalchemy import select

from app.core.models import Department, Role, RoleName, User


async def test_create_user_with_phone_title_department(admin_client, db):
    dept = Department(name="Profile-Fields-Dept")
    db.add(dept)
    await db.commit()
    role = (await db.execute(select(Role).where(Role.name == RoleName.viewer))).scalar_one()

    resp = await admin_client.post(
        "/users/create",
        data={
            "username": "fields-test-user", "password": "supersecret123", "role_id": role.id,
            "phone": "+248 555 1234", "job_title": "IT Technician", "department_id": dept.id,
        },
    )
    assert resp.status_code == 204

    row = (await db.execute(select(User).where(User.username == "fields-test-user"))).scalar_one()
    assert row.phone == "+248 555 1234"
    assert row.job_title == "IT Technician"
    assert row.department_id == dept.id


async def test_create_user_rejects_unknown_department(admin_client, db):
    role = (await db.execute(select(Role).where(Role.name == RoleName.viewer))).scalar_one()
    resp = await admin_client.post(
        "/users/create",
        data={
            "username": "fields-bad-dept-user", "password": "supersecret123", "role_id": role.id,
            "department_id": "999999",
        },
    )
    assert "text-bg-danger" in resp.text
    assert "department" in resp.text.lower()
    assert (await db.execute(select(User).where(User.username == "fields-bad-dept-user"))).first() is None


async def test_update_user_phone_title_department(admin_client, db):
    dept = Department(name="Profile-Fields-Dept-Update")
    db.add(dept)
    await db.commit()
    role = (await db.execute(select(Role).where(Role.name == RoleName.viewer))).scalar_one()
    await admin_client.post(
        "/users/create", data={"username": "fields-update-user", "password": "supersecret123", "role_id": role.id},
    )
    row = (await db.execute(select(User).where(User.username == "fields-update-user"))).scalar_one()

    resp = await admin_client.post(
        f"/users/{row.id}/update",
        data={
            "role_id": role.id, "is_active": "true",
            "phone": "555-0001", "job_title": "Helpdesk Lead", "department_id": dept.id,
        },
    )
    assert resp.status_code == 200
    assert "text-bg-success" in resp.text
    await db.refresh(row)
    assert row.phone == "555-0001"
    assert row.job_title == "Helpdesk Lead"
    assert row.department_id == dept.id


async def test_users_list_shows_phone_title_department(admin_client, db):
    dept = Department(name="Profile-Fields-Dept-List")
    db.add(dept)
    await db.commit()
    role = (await db.execute(select(Role).where(Role.name == RoleName.viewer))).scalar_one()
    await admin_client.post(
        "/users/create",
        data={
            "username": "fields-list-user", "password": "supersecret123", "role_id": role.id,
            "phone": "555-9999", "job_title": "Network Admin", "department_id": dept.id,
        },
    )

    resp = await admin_client.get("/users")
    assert resp.status_code == 200
    assert "555-9999" in resp.text
    assert "Network Admin" in resp.text
    assert "Profile-Fields-Dept-List" in resp.text


async def test_profile_shows_phone_title_department(admin_client, db):
    """The break-glass admin has none of these set by default -- assign
    them directly and confirm /profile reflects it (profile has no
    self-edit for these fields, admin-managed only, per the design)."""
    dept = Department(name="Profile-Fields-Dept-Self")
    db.add(dept)
    await db.flush()
    admin_id = (await db.execute(select(User.id).where(User.is_breakglass.is_(True)))).scalar_one()
    admin_row = await db.get(User, admin_id)
    admin_row.phone = "555-ADMIN"
    admin_row.job_title = "System Administrator"
    admin_row.department_id = dept.id
    await db.commit()

    resp = await admin_client.get("/profile")
    assert resp.status_code == 200
    assert "555-ADMIN" in resp.text
    assert "System Administrator" in resp.text
    assert "Profile-Fields-Dept-Self" in resp.text
