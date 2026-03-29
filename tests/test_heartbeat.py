"""Heartbeat checker and receiver tests."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import asyncpg
from aiohttp.test_utils import TestClient, TestServer

from watchdog.checkers.heartbeat import HeartbeatChecker, create_heartbeat_app


class TestHeartbeatChecker:
    async def test_recent_ping_returns_success(self) -> None:
        recent = datetime.now(UTC) - timedelta(seconds=30)
        pool = AsyncMock()
        with patch(
            'watchdog.checkers.heartbeat.storage.get_last_heartbeat_ping',
            new=AsyncMock(return_value=recent),
        ):
            checker = HeartbeatChecker(pool=pool, interval=60, grace=0)
            result = await checker.check('mon-hb')
        assert result.success is True
        assert result.response_time_ms is not None
        assert result.response_time_ms >= 0
        assert result.error is None

    async def test_stale_ping_returns_failure(self) -> None:
        stale = datetime.now(UTC) - timedelta(seconds=200)
        pool = AsyncMock()
        with patch(
            'watchdog.checkers.heartbeat.storage.get_last_heartbeat_ping',
            new=AsyncMock(return_value=stale),
        ):
            checker = HeartbeatChecker(pool=pool, interval=60, grace=0)
            result = await checker.check('mon-hb')
        assert result.success is False
        assert result.error is not None
        assert 'overdue' in result.error

    async def test_no_ping_returns_failure(self) -> None:
        pool = AsyncMock()
        with patch(
            'watchdog.checkers.heartbeat.storage.get_last_heartbeat_ping',
            new=AsyncMock(return_value=None),
        ):
            checker = HeartbeatChecker(pool=pool, interval=60, grace=0)
            result = await checker.check('mon-hb')
        assert result.success is False
        assert result.error == 'no heartbeat received'

    async def test_grace_extends_deadline(self) -> None:
        slightly_stale = datetime.now(UTC) - timedelta(seconds=70)
        pool = AsyncMock()
        with patch(
            'watchdog.checkers.heartbeat.storage.get_last_heartbeat_ping',
            new=AsyncMock(return_value=slightly_stale),
        ):
            checker = HeartbeatChecker(pool=pool, interval=60, grace=30)
            result = await checker.check('mon-hb')
        assert result.success is True

    async def test_grace_boundary_exact_deadline(self) -> None:
        at_deadline = datetime.now(UTC) - timedelta(seconds=91)
        pool = AsyncMock()
        with patch(
            'watchdog.checkers.heartbeat.storage.get_last_heartbeat_ping',
            new=AsyncMock(return_value=at_deadline),
        ):
            checker = HeartbeatChecker(pool=pool, interval=60, grace=30)
            result = await checker.check('mon-hb')
        assert result.success is False

    async def test_response_time_is_elapsed_since_ping(self) -> None:
        ping_time = datetime.now(UTC) - timedelta(seconds=10)
        pool = AsyncMock()
        with patch(
            'watchdog.checkers.heartbeat.storage.get_last_heartbeat_ping',
            new=AsyncMock(return_value=ping_time),
        ):
            checker = HeartbeatChecker(pool=pool, interval=60, grace=0)
            result = await checker.check('mon-hb')
        assert result.success is True
        assert result.response_time_ms is not None
        assert 9000 <= result.response_time_ms <= 11000


class TestHeartbeatStorageFunctions:
    async def test_upsert_heartbeat_ping_called(self) -> None:
        pool = AsyncMock()
        pool.fetchrow = AsyncMock(return_value=None)
        pool.execute = AsyncMock(return_value=None)
        with patch(
            'watchdog.checkers.heartbeat.storage.upsert_heartbeat_ping',
            new=AsyncMock(),
        ) as mock_upsert:
            app = await create_heartbeat_app(pool)
            async with TestClient(TestServer(app)) as client:
                resp = await client.post('/my-monitor')
            mock_upsert.assert_awaited_once_with(pool, 'my-monitor')
            assert resp.status == 200

    async def test_post_returns_ok_json(self) -> None:
        pool = AsyncMock()
        with patch(
            'watchdog.checkers.heartbeat.storage.upsert_heartbeat_ping',
            new=AsyncMock(),
        ):
            app = await create_heartbeat_app(pool)
            async with TestClient(TestServer(app)) as client:
                resp = await client.post('/my-monitor')
                data = await resp.json()
            assert data['status'] == 'ok'
            assert data['monitor_id'] == 'my-monitor'

    async def test_post_returns_500_on_db_error(self) -> None:
        pool = AsyncMock()
        with patch(
            'watchdog.checkers.heartbeat.storage.upsert_heartbeat_ping',
            new=AsyncMock(side_effect=asyncpg.PostgresError('db error')),
        ):
            app = await create_heartbeat_app(pool)
            async with TestClient(TestServer(app)) as client:
                resp = await client.post('/my-monitor')
                data = await resp.json()
            assert resp.status == 500
            assert 'error' in data

    async def test_post_different_monitor_ids(self) -> None:
        pool = AsyncMock()
        captured: list[str] = []

        async def capture_upsert(p: object, mid: str) -> None:
            captured.append(mid)

        with patch(
            'watchdog.checkers.heartbeat.storage.upsert_heartbeat_ping',
            new=capture_upsert,
        ):
            app = await create_heartbeat_app(pool)
            async with TestClient(TestServer(app)) as client:
                await client.post('/server-a')
                await client.post('/server-b')
        assert captured == ['server-a', 'server-b']
