"""Pytest fixtures for the Phase 5+ test suite.

Runs against a real, throwaway Postgres container (see
scripts/run_tests.sh) — NOT sqlite. The core_assets/core_checkouts
CHECK constraints (num_nonnulls) and the partial unique index on
core_checkouts are Postgres-only and must be exercised against real
Postgres, not faked or skipped.

DATABASE_URL must already point at the throwaway container, and the
schema must already be migrated (alembic upgrade head), before pytest
starts — scripts/run_tests.sh does both before invoking pytest.
"""

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@itops2-test-db:5432/test")

from app.core.bootstrap import bootstrap  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402

# Truncated before every test. Roles/permissions/breakglass user/currencies
# are seeded once per session by bootstrap() and deliberately left alone —
# tests that need extra users/currencies create their own with unique names.
TRUNCATE_TABLES = (
    "core_assets",
    "core_checkouts",
    "core_attachments",
    "core_audit_log",
    "core_models",
    "core_status_labels",
    "core_categories",
    "core_manufacturers",
    "core_locations",
)


@pytest.fixture(scope="session")
def settings():
    return get_settings()


@pytest_asyncio.fixture(scope="session")
async def _bootstrapped():
    async with SessionLocal() as db:
        await bootstrap(db)
    yield


@pytest_asyncio.fixture(autouse=True)
async def _fresh_engine_per_test(_bootstrapped):
    """pytest-asyncio gives each test function its own event loop; the
    shared engine's connection pool must be disposed before each test runs
    or its pooled asyncpg connections stay bound to a previous (closed)
    loop and blow up with 'attached to a different loop'. Documented
    SQLAlchemy fix for this scenario. Runs after _bootstrapped (which owns
    its own connection, opened and cleanly closed on first use) so there's
    no disposal racing an in-flight close."""
    await engine.dispose()
    yield


@pytest_asyncio.fixture(autouse=True)
async def _clean_tables(_fresh_engine_per_test):
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {', '.join(TRUNCATE_TABLES)} RESTART IDENTITY CASCADE"))
    yield


@pytest_asyncio.fixture
async def db() -> AsyncSession:
    async with SessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def admin_client(client: AsyncClient, settings) -> AsyncClient:
    resp = await client.post(
        "/login",
        data={"username": settings.breakglass_username, "password": settings.breakglass_password},
    )
    assert resp.status_code == 302
    return client
