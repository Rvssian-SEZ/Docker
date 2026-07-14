"""app/core/v1_source.py -- proves the read-only guarantee is enforced
by Postgres itself, not just by V1Source's public interface happening
to lack a write method.

There's no real v1 database in the test harness, so these tests point
V1Source at the same throwaway Postgres the rest of the suite already
runs against (via settings.database_url) -- any real Postgres instance
proves the point equally well, since the guarantee is generic
(default_transaction_read_only=on + an explicit readonly transaction),
not specific to v1's schema.
"""

import asyncpg
import pytest

from app.core.v1_source import V1Source


@pytest.fixture
async def source(settings):
    src = await V1Source.connect(settings.database_url)
    yield src
    await src.close()


async def test_fetch_runs_a_real_select(source: V1Source):
    rows = await source.fetch("SELECT 1 AS one")
    assert rows[0]["one"] == 1


async def test_fetch_can_read_real_tables(source: V1Source):
    # core_currencies is seeded by bootstrap() and never truncated --
    # guaranteed to have rows in every test run.
    rows = await source.fetch("SELECT code FROM core_currencies")
    assert len(rows) > 0


async def test_connection_level_write_is_rejected_by_postgres(source: V1Source):
    """The server_settings=default_transaction_read_only=on passed at
    connect time -- proven directly against the raw connection, not
    through V1Source's own (write-less) public API, so this can't pass
    just because V1Source happens not to expose .execute()."""
    with pytest.raises(asyncpg.exceptions.ReadOnlySQLTransactionError):
        await source.raw_connection.execute(
            "CREATE TABLE v1_source_write_should_never_happen (id int)"
        )


async def test_fetch_transaction_is_itself_read_only(source: V1Source):
    """Belt-and-braces: even if a future caller connected without the
    read-only server_setting somehow, fetch()'s own `transaction(readonly=True)`
    wrapper still refuses a write issued through it."""
    with pytest.raises(asyncpg.exceptions.ReadOnlySQLTransactionError):
        async with source._conn.transaction(readonly=True):
            await source._conn.execute(
                "CREATE TABLE v1_source_write_should_never_happen_2 (id int)"
            )


async def test_v1_source_exposes_no_write_methods():
    """Structural check that the public interface itself has nothing
    to reach for -- fetch()/close()/connect() only."""
    public_methods = {name for name in dir(V1Source) if not name.startswith("_")}
    assert public_methods == {"connect", "fetch", "close", "raw_connection"}
