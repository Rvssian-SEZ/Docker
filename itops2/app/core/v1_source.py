"""Read-only connection to the v1 database for the import wizard
(Phase 9). Structural, not disciplined: the connection itself is opened
with default_transaction_read_only=on (Postgres rejects any write at
the database level, not because app code chooses not to send one), and
every fetch() additionally runs inside its own `BEGIN TRANSACTION READ
ONLY` block. On top of that, V1Source's public interface is only
fetch() — there is no execute()/commit() method on this type for
application code to call in the first place, so a write isn't just
forbidden at runtime, it's a method that doesn't exist to reach for.

raw_connection is exposed for TESTS ONLY, to prove the DB-level
guarantee directly (attempt a real write against the underlying
connection and confirm Postgres itself refuses it) — application code
must never touch it.
"""

import asyncpg


class V1Source:
    def __init__(self, conn: asyncpg.Connection):
        self._conn = conn

    @classmethod
    async def connect(cls, database_url: str) -> "V1Source":
        # asyncpg wants a plain postgresql:// DSN, not the
        # dialect-qualified postgresql+asyncpg:// SQLAlchemy uses
        # elsewhere in this app.
        dsn = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        conn = await asyncpg.connect(dsn, server_settings={"default_transaction_read_only": "on"})
        return cls(conn)

    async def fetch(self, sql: str, *params) -> list[asyncpg.Record]:
        async with self._conn.transaction(readonly=True):
            return await self._conn.fetch(sql, *params)

    async def close(self) -> None:
        await self._conn.close()

    @property
    def raw_connection(self) -> asyncpg.Connection:
        """TEST-ONLY escape hatch — see module docstring. Never call
        .execute()/anything mutating on this from application code."""
        return self._conn
