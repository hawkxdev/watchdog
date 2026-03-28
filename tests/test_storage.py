"""Storage layer tests. Requires PostgreSQL (WATCHDOG_DATABASE_URL)."""

import os
from collections.abc import AsyncGenerator

import asyncpg
import pytest
import pytest_asyncio

import watchdog.storage as storage

DATABASE_URL = os.environ.get('WATCHDOG_DATABASE_URL', '')

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason='WATCHDOG_DATABASE_URL not set',
)


@pytest_asyncio.fixture(loop_scope='session', scope='session')
async def pool() -> AsyncGenerator[asyncpg.Pool]:
    """Session scoped pool with schema."""
    p = await storage.create_pool(DATABASE_URL, min_size=1, max_size=3)
    await storage.create_schema(p)
    yield p
    await storage.close_pool(p)


@pytest.fixture(autouse=True)
async def clean_tables(pool: asyncpg.Pool) -> None:
    """Truncate tables before each test."""
    async with pool.acquire() as conn:
        await conn.execute('TRUNCATE checks, incidents RESTART IDENTITY')


class TestPoolLifecycle:
    async def test_create_pool_returns_pool(
        self,
    ) -> None:
        p = await storage.create_pool(DATABASE_URL)
        assert p is not None
        assert not p.is_closing()
        await storage.close_pool(p)

    async def test_close_pool(self) -> None:
        p = await storage.create_pool(DATABASE_URL)
        await storage.close_pool(p)
        assert p.is_closing()


class TestCreateSchema:
    async def test_tables_exist_after_create(self, pool: asyncpg.Pool) -> None:
        await storage.create_schema(pool)
        async with pool.acquire() as conn:
            tables = await conn.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            )
        names = {r['tablename'] for r in tables}
        assert 'checks' in names
        assert 'incidents' in names

    async def test_create_schema_idempotent(self, pool: asyncpg.Pool) -> None:
        await storage.create_schema(pool)
        await storage.create_schema(pool)


class TestInsertCheck:
    async def test_insert_returns_id(self, pool: asyncpg.Pool) -> None:
        row_id = await storage.insert_check(
            pool,
            monitor_id='api',
            success=True,
            response_time_ms=42.5,
            status_code=200,
            error=None,
        )
        assert isinstance(row_id, int)
        assert row_id > 0

    async def test_insert_failed_check(self, pool: asyncpg.Pool) -> None:
        row_id = await storage.insert_check(
            pool,
            monitor_id='vps',
            success=False,
            response_time_ms=None,
            status_code=None,
            error='Connection refused',
        )
        assert row_id > 0

    async def test_insert_preserves_fields(self, pool: asyncpg.Pool) -> None:
        row_id = await storage.insert_check(
            pool,
            monitor_id='my-monitor',
            success=True,
            response_time_ms=100.0,
            status_code=200,
            error=None,
        )
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                'SELECT * FROM checks WHERE id = $1',
                row_id,
            )
        assert row['monitor_id'] == 'my-monitor'
        assert row['success'] is True
        assert float(row['response_time_ms']) == 100.0
        assert row['status_code'] == 200
        assert row['error'] is None

    async def test_created_at_set_automatically(
        self, pool: asyncpg.Pool
    ) -> None:
        row_id = await storage.insert_check(
            pool,
            monitor_id='x',
            success=True,
            response_time_ms=None,
            status_code=None,
            error=None,
        )
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                'SELECT created_at FROM checks WHERE id = $1',
                row_id,
            )
        assert row['created_at'] is not None


class TestInsertIncident:
    async def test_insert_down_incident(self, pool: asyncpg.Pool) -> None:
        row_id = await storage.insert_incident(
            pool,
            monitor_id='api',
            status='down',
            message='3 consecutive failures',
        )
        assert isinstance(row_id, int)
        assert row_id > 0

    async def test_insert_recovery_incident(self, pool: asyncpg.Pool) -> None:
        row_id = await storage.insert_incident(
            pool,
            monitor_id='api',
            status='up',
            message='Recovered after 5 minutes',
        )
        assert row_id > 0

    async def test_insert_preserves_fields(self, pool: asyncpg.Pool) -> None:
        row_id = await storage.insert_incident(
            pool,
            monitor_id='vps',
            status='down',
            message='Ping timeout',
        )
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                'SELECT * FROM incidents WHERE id = $1',
                row_id,
            )
        assert row['monitor_id'] == 'vps'
        assert row['status'] == 'down'
        assert row['message'] == 'Ping timeout'


class TestCleanupOldChecks:
    async def test_cleanup_deletes_old_rows(self, pool: asyncpg.Pool) -> None:
        async with pool.acquire() as conn:
            await conn.execute(
                'INSERT INTO checks'
                ' (monitor_id, success, created_at)'
                ' VALUES ($1, $2, NOW() - INTERVAL'
                " '31 days')",
                'old-monitor',
                True,
            )
        deleted = await storage.cleanup_old_checks(pool, retention_days=30)
        assert deleted >= 1

    async def test_cleanup_keeps_recent_rows(self, pool: asyncpg.Pool) -> None:
        await storage.insert_check(
            pool,
            monitor_id='recent',
            success=True,
            response_time_ms=10.0,
            status_code=200,
            error=None,
        )
        deleted = await storage.cleanup_old_checks(pool, retention_days=30)
        assert deleted == 0
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*) AS n FROM checks WHERE monitor_id = 'recent'"
            )
        assert row['n'] == 1

    async def test_cleanup_returns_count(self, pool: asyncpg.Pool) -> None:
        async with pool.acquire() as conn:
            for i in range(3):
                await conn.execute(
                    'INSERT INTO checks'
                    ' (monitor_id, success, created_at)'
                    ' VALUES ($1, $2, NOW() - INTERVAL'
                    " '40 days')",
                    f'monitor-{i}',
                    True,
                )
        deleted = await storage.cleanup_old_checks(pool, retention_days=30)
        assert deleted == 3
