"""PostgreSQL storage via asyncpg."""

import logging

import asyncpg

logger = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS checks (
    id               SERIAL PRIMARY KEY,
    monitor_id       VARCHAR(100) NOT NULL,
    success          BOOLEAN      NOT NULL,
    response_time_ms REAL,
    status_code      INTEGER,
    error            TEXT,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_checks_monitor_created
    ON checks (monitor_id, created_at DESC);

CREATE TABLE IF NOT EXISTS incidents (
    id         SERIAL PRIMARY KEY,
    monitor_id VARCHAR(100) NOT NULL,
    status     VARCHAR(20)  NOT NULL,
    message    TEXT,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_incidents_monitor_created
    ON incidents (monitor_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_checks_created_at
    ON checks (created_at);
"""


async def create_pool(
    dsn: str,
    min_size: int = 2,
    max_size: int = 10,
) -> asyncpg.Pool:
    """Create asyncpg connection pool."""
    pool = await asyncpg.create_pool(
        dsn,
        min_size=min_size,
        max_size=max_size,
        command_timeout=60,
    )
    logger.info(
        'asyncpg pool created (min=%d max=%d)',
        min_size,
        max_size,
    )
    return pool


async def close_pool(pool: asyncpg.Pool) -> None:
    """Close connection pool."""
    await pool.close()
    logger.info('asyncpg pool closed')


async def create_schema(pool: asyncpg.Pool) -> None:
    """Create database tables and indexes."""
    async with pool.acquire() as conn:
        await conn.execute(_DDL)
    logger.info('Storage schema verified / created')


async def insert_check(
    pool: asyncpg.Pool,
    monitor_id: str,
    success: bool,
    response_time_ms: float | None,
    status_code: int | None,
    error: str | None,
) -> int:
    """Insert check result. Returns row id."""
    sql = """
        INSERT INTO checks
            (monitor_id, success, response_time_ms,
             status_code, error)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id
    """
    row = await pool.fetchrow(
        sql,
        monitor_id,
        success,
        response_time_ms,
        status_code,
        error,
    )
    return row['id']


async def insert_incident(
    pool: asyncpg.Pool,
    monitor_id: str,
    status: str,
    message: str,
) -> int:
    """Insert state transition incident."""
    sql = """
        INSERT INTO incidents (monitor_id, status, message)
        VALUES ($1, $2, $3)
        RETURNING id
    """
    row = await pool.fetchrow(sql, monitor_id, status, message)
    return row['id']


async def cleanup_old_checks(pool: asyncpg.Pool, retention_days: int) -> int:
    """Delete expired checks. Returns count."""
    sql = """
        DELETE FROM checks
        WHERE created_at < NOW() - make_interval(days => $1)
    """
    result = await pool.execute(sql, retention_days)
    deleted_count = int(result.split()[-1])
    logger.info(
        'Retention cleanup: deleted %d old checks',
        deleted_count,
    )
    return deleted_count
