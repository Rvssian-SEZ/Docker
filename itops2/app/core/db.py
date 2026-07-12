"""Async SQLAlchemy engine/session.

Performance requirements baked in from day one (v1 was sluggish on save):
- async engine with connection pooling
- sessions are request-scoped via dependency
- background tasks NEVER receive ORM objects (DetachedInstanceError) —
  extract primitive values before the session closes.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    echo=settings.debug,
)

SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    """All ITOps v2 core tables use the core_ prefix.

    Helpdesk v2 / CRM v2 will share this database later with their own
    prefixes and their own alembic version tables — same isolation
    discipline as the v1 shared DB.
    """


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
