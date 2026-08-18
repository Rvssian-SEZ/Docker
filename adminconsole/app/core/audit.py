"""The append-only audit trail — a physically separate SQLite database
(AUDIT_DATABASE_URL, default /data/audit.db) from app state, per the spec's
"Audit everything, immutably" requirement.

Immutability is enforced at the DB level, not just by app discipline: on
startup (see ensure_schema, called from app/main.py's lifespan) this module
creates the table if missing and installs BEFORE UPDATE / BEFORE DELETE
triggers that RAISE(ABORT) — so even a bug that calls session.execute(update(...))
or a raw UPDATE against this file fails at the SQLite engine, not just at
the ORM layer. This is the practical ceiling of "insert-only" achievable in
SQLite (it has no per-connection user/grant system like Postgres); the
compose-level mitigation is that this file lives on its own volume path,
never bind-mounted writable into anything else.

Every write here is its own commit, independent of whatever app-DB
transaction triggered it — the two databases can't share one transaction,
and an audit row must still land even if the caller's app-DB commit hasn't
happened yet (write audit-then-app-state, not the other way around, so a
crash between the two never loses the audit record — see write_audit's
docstring for the ordering contract callers must follow).
"""

from collections.abc import AsyncGenerator
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text, event, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import get_settings

settings = get_settings()

audit_engine = create_async_engine(settings.audit_database_url, echo=settings.debug)


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


AuditSessionLocal = async_sessionmaker(audit_engine, class_=AsyncSession, expire_on_commit=False)


class AuditBase(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AuditLog(AuditBase):
    """One row per write action or LAPS read. No FKs to the app DB (it's a
    different file) — actor identity is denormalized (username + role +
    auth source, not a user_id) so a row stays fully readable even if the
    actor's account is later deleted, renamed, or its role changes.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor_username: Mapped[str] = mapped_column(String(150), index=True)
    actor_role: Mapped[str] = mapped_column(String(50), index=True)
    # "local" / "oidc" / "breakglass" — breakglass rows are also flagged
    # for the alerting path (app/core/alerting.py), never silently blended
    # into normal local-auth actions.
    actor_source: Mapped[str] = mapped_column(String(20), index=True)
    action: Mapped[str] = mapped_column(String(50), index=True)  # unlock/reset_password/enable/disable/edit_attributes/laps_reveal/login/settings_change/...
    target_type: Mapped[str] = mapped_column(String(50), index=True)  # ad_account/setting/session/...
    target_id: Mapped[str | None] = mapped_column(String(200), index=True)  # e.g. the AD sAMAccountName or DN
    reason: Mapped[str | None] = mapped_column(Text)  # ticket-ref / justification, required for sensitive actions
    source_ip: Mapped[str | None] = mapped_column(String(45))
    detail: Mapped[str | None] = mapped_column(Text)


_TRIGGER_SQL = (
    """
    CREATE TRIGGER IF NOT EXISTS audit_log_no_update
    BEFORE UPDATE ON audit_log
    BEGIN
        SELECT RAISE(ABORT, 'audit_log is append-only: UPDATE is not permitted');
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS audit_log_no_delete
    BEFORE DELETE ON audit_log
    BEGIN
        SELECT RAISE(ABORT, 'audit_log is append-only: DELETE is not permitted');
    END;
    """,
)


async def ensure_schema() -> None:
    """Idempotent — safe on every startup. Creates the table (if missing)
    and (re-)installs the append-only triggers; CREATE TRIGGER IF NOT
    EXISTS means an already-current install is a no-op."""
    async with audit_engine.begin() as conn:
        await conn.run_sync(AuditBase.metadata.create_all)
        for stmt in _TRIGGER_SQL:
            await conn.execute(text(stmt))


async def get_audit_db() -> AsyncGenerator[AsyncSession, None]:
    async with AuditSessionLocal() as session:
        yield session


async def write_audit(
    *,
    actor_username: str,
    actor_role: str,
    actor_source: str,
    action: str,
    target_type: str,
    target_id: str | None = None,
    reason: str | None = None,
    source_ip: str | None = None,
    detail: str | None = None,
) -> None:
    """Opens its own session/commit — call this BEFORE the corresponding
    app-DB write (or AD/Graph call) commits, so a crash or a failed
    downstream call still leaves a record that the action was attempted.
    A LAPS reveal or a failed unlock attempt is exactly as worth logging as
    a successful one; callers should log outcome (success/failure) in
    `detail`, never skip the call on failure.
    """
    async with AuditSessionLocal() as session:
        session.add(
            AuditLog(
                actor_username=actor_username,
                actor_role=actor_role,
                actor_source=actor_source,
                action=action,
                target_type=target_type,
                target_id=target_id,
                reason=reason,
                source_ip=source_ip,
                detail=detail,
            )
        )
        await session.commit()


async def query_audit(
    *,
    actor_username: str | None = None,
    action: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[AuditLog]:
    """Backs the /audit filter UI — every param is optional and AND-ed."""
    stmt = select(AuditLog).order_by(AuditLog.at.desc())
    if actor_username:
        stmt = stmt.where(AuditLog.actor_username == actor_username)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if target_type:
        stmt = stmt.where(AuditLog.target_type == target_type)
    if target_id:
        stmt = stmt.where(AuditLog.target_id.contains(target_id))
    if since:
        stmt = stmt.where(AuditLog.at >= since)
    if until:
        stmt = stmt.where(AuditLog.at <= until)
    stmt = stmt.limit(limit).offset(offset)
    async with AuditSessionLocal() as session:
        return list((await session.execute(stmt)).scalars())


async def distinct_actors() -> list[str]:
    async with AuditSessionLocal() as session:
        rows = await session.execute(select(AuditLog.actor_username).distinct().order_by(AuditLog.actor_username))
        return [r for (r,) in rows]


async def distinct_actions() -> list[str]:
    async with AuditSessionLocal() as session:
        rows = await session.execute(select(AuditLog.action).distinct().order_by(AuditLog.action))
        return [r for (r,) in rows]
