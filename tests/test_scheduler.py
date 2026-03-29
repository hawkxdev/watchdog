"""Scheduler tests."""

import asyncio
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import httpx
import pytest

from watchdog.checkers.base import CheckResult
from watchdog.checkers.heartbeat import HeartbeatChecker
from watchdog.checkers.http import HttpChecker
from watchdog.checkers.ping import PingChecker
from watchdog.config import (
    AppConfig,
    DatabaseConfig,
    GeneralConfig,
    MonitorConfig,
    TelegramConfig,
)
from watchdog.scheduler import create_monitors, monitor_loop, run_all
from watchdog.state import MonitorState


def _make_config(*monitors: MonitorConfig) -> AppConfig:
    return AppConfig(
        general=GeneralConfig(check_interval=60),
        database=DatabaseConfig(dsn='postgresql://x:x@localhost/x'),
        telegram=TelegramConfig(bot_token='tok', chat_id='123', enabled=False),
        monitors=list(monitors),
    )


def _http_monitor(**kw: object) -> MonitorConfig:
    defaults = dict(
        id='http-1',
        name='HTTP',
        type='http',
        target='https://example.com',
        interval=30,
        enabled=True,
        expected_status=200,
        timeout=5,
    )
    defaults.update(kw)
    return MonitorConfig(**defaults)  # type: ignore[arg-type]


def _ping_monitor(**kw: object) -> MonitorConfig:
    defaults = dict(
        id='ping-1',
        name='Ping',
        type='ping',
        target='8.8.8.8',
        interval=30,
        enabled=True,
        timeout=5,
    )
    defaults.update(kw)
    return MonitorConfig(**defaults)  # type: ignore[arg-type]


def _hb_monitor(**kw: object) -> MonitorConfig:
    defaults = dict(
        id='hb-1',
        name='Heartbeat',
        type='heartbeat',
        target='hb-1',
        interval=60,
        enabled=True,
        timeout=10,
    )
    defaults.update(kw)
    return MonitorConfig(**defaults)  # type: ignore[arg-type]


class TestCreateMonitors:
    def test_http_monitor_creates_http_checker(self) -> None:
        config = _make_config(_http_monitor())
        pool = MagicMock()
        client = MagicMock(spec=httpx.AsyncClient)
        result = create_monitors(config, pool, client)
        assert len(result) == 1
        mc, checker, state = result[0]
        assert isinstance(checker, HttpChecker)
        assert isinstance(state, MonitorState)
        assert mc.id == 'http-1'

    def test_ping_monitor_creates_ping_checker(self) -> None:
        config = _make_config(_ping_monitor())
        pool = MagicMock()
        client = MagicMock(spec=httpx.AsyncClient)
        result = create_monitors(config, pool, client)
        assert len(result) == 1
        _, checker, _ = result[0]
        assert isinstance(checker, PingChecker)

    def test_heartbeat_monitor_creates_heartbeat_checker(self) -> None:
        config = _make_config(_hb_monitor())
        pool = MagicMock()
        client = MagicMock(spec=httpx.AsyncClient)
        result = create_monitors(config, pool, client)
        assert len(result) == 1
        _, checker, _ = result[0]
        assert isinstance(checker, HeartbeatChecker)

    def test_disabled_monitor_skipped(self) -> None:
        config = _make_config(
            _http_monitor(id='enabled-1'),
            _http_monitor(id='disabled-1', enabled=False),
        )
        pool = MagicMock()
        client = MagicMock(spec=httpx.AsyncClient)
        result = create_monitors(config, pool, client)
        assert len(result) == 1
        assert result[0][0].id == 'enabled-1'

    def test_multiple_monitors_all_enabled(self) -> None:
        config = _make_config(
            _http_monitor(id='http-1'),
            _ping_monitor(id='ping-1'),
            _hb_monitor(id='hb-1'),
        )
        pool = MagicMock()
        client = MagicMock(spec=httpx.AsyncClient)
        result = create_monitors(config, pool, client)
        assert len(result) == 3

    def test_heartbeat_uses_interval_from_config(self) -> None:
        config = _make_config(_hb_monitor(interval=120))
        pool = MagicMock()
        client = MagicMock(spec=httpx.AsyncClient)
        result = create_monitors(config, pool, client)
        _, checker, _ = result[0]
        assert isinstance(checker, HeartbeatChecker)
        assert checker._interval == 120

    def test_heartbeat_falls_back_to_general_interval(self) -> None:
        config = _make_config(_hb_monitor(interval=None))
        pool = MagicMock()
        client = MagicMock(spec=httpx.AsyncClient)
        result = create_monitors(config, pool, client)
        _, checker, _ = result[0]
        assert isinstance(checker, HeartbeatChecker)
        assert checker._interval == config.general.check_interval

    def test_empty_monitors_list(self) -> None:
        config = _make_config()
        pool = MagicMock()
        client = MagicMock(spec=httpx.AsyncClient)
        result = create_monitors(config, pool, client)
        assert result == []


class TestMonitorLoop:
    @pytest.mark.looptime
    async def test_loop_runs_check_once_then_sleeps(self) -> None:
        checker = AsyncMock()
        checker.check.return_value = CheckResult(
            success=True, response_time_ms=10.0
        )
        mc = _http_monitor(interval=30)
        state = MonitorState()
        pool = AsyncMock()
        shutdown = asyncio.Event()

        with (
            patch('watchdog.scheduler.storage.insert_check', new=AsyncMock()),
            patch(
                'watchdog.scheduler.storage.insert_incident',
                new=AsyncMock(),
            ),
        ):
            task = asyncio.create_task(
                monitor_loop(mc.id, checker, mc, state, pool, 3, 2, shutdown)
            )
            await asyncio.sleep(0)
            shutdown.set()
            await asyncio.sleep(31)
            await task

        checker.check.assert_awaited_once_with(mc.target)

    @pytest.mark.looptime
    async def test_loop_calls_insert_check(self) -> None:
        checker = AsyncMock()
        checker.check.return_value = CheckResult(
            success=True, response_time_ms=5.0
        )
        mc = _http_monitor(interval=10)
        state = MonitorState()
        pool = AsyncMock()
        shutdown = asyncio.Event()

        mock_insert = AsyncMock()
        with (
            patch('watchdog.scheduler.storage.insert_check', new=mock_insert),
            patch(
                'watchdog.scheduler.storage.insert_incident',
                new=AsyncMock(),
            ),
        ):
            task = asyncio.create_task(
                monitor_loop(mc.id, checker, mc, state, pool, 3, 2, shutdown)
            )
            await asyncio.sleep(0)
            shutdown.set()
            await asyncio.sleep(11)
            await task

        mock_insert.assert_awaited_once_with(
            pool, mc.id, True, 5.0, None, None
        )

    @pytest.mark.looptime
    async def test_loop_inserts_incident_on_transition(self) -> None:
        checker = AsyncMock()
        checker.check.return_value = CheckResult(
            success=False, error='timeout'
        )
        mc = _http_monitor(interval=10)
        state = MonitorState(status='UP')
        pool = AsyncMock()
        shutdown = asyncio.Event()

        mock_incident = AsyncMock()
        with (
            patch('watchdog.scheduler.storage.insert_check', new=AsyncMock()),
            patch(
                'watchdog.scheduler.storage.insert_incident',
                new=mock_incident,
            ),
        ):
            task = asyncio.create_task(
                monitor_loop(mc.id, checker, mc, state, pool, 1, 2, shutdown)
            )
            await asyncio.sleep(0)
            shutdown.set()
            await asyncio.sleep(11)
            await task

        mock_incident.assert_awaited_once_with(pool, mc.id, 'DOWN', ANY)

    @pytest.mark.looptime
    async def test_loop_exits_immediately_on_shutdown(self) -> None:
        checker = AsyncMock()
        checker.check.return_value = CheckResult(success=True)
        mc = _http_monitor(interval=300)
        state = MonitorState()
        pool = AsyncMock()
        shutdown = asyncio.Event()
        shutdown.set()

        with (
            patch('watchdog.scheduler.storage.insert_check', new=AsyncMock()),
            patch(
                'watchdog.scheduler.storage.insert_incident',
                new=AsyncMock(),
            ),
        ):
            await monitor_loop(mc.id, checker, mc, state, pool, 3, 2, shutdown)

        checker.check.assert_not_awaited()

    @pytest.mark.looptime
    async def test_loop_runs_multiple_iterations(self) -> None:
        checker = AsyncMock()
        checker.check.return_value = CheckResult(success=True)
        mc = _http_monitor(interval=10)
        state = MonitorState()
        pool = AsyncMock()
        shutdown = asyncio.Event()

        mock_insert = AsyncMock()
        with (
            patch('watchdog.scheduler.storage.insert_check', new=mock_insert),
            patch(
                'watchdog.scheduler.storage.insert_incident',
                new=AsyncMock(),
            ),
        ):
            task = asyncio.create_task(
                monitor_loop(mc.id, checker, mc, state, pool, 3, 2, shutdown)
            )
            await asyncio.sleep(25)
            shutdown.set()
            await asyncio.sleep(11)
            await task

        assert checker.check.await_count == 3

    @pytest.mark.looptime
    async def test_loop_uses_general_interval_when_monitor_interval_none(
        self,
    ) -> None:
        checker = AsyncMock()
        checker.check.return_value = CheckResult(success=True)
        mc = _http_monitor(interval=None)
        state = MonitorState()
        pool = AsyncMock()
        shutdown = asyncio.Event()

        mock_insert = AsyncMock()
        with (
            patch('watchdog.scheduler.storage.insert_check', new=mock_insert),
            patch(
                'watchdog.scheduler.storage.insert_incident',
                new=AsyncMock(),
            ),
        ):
            task = asyncio.create_task(
                monitor_loop(
                    mc.id,
                    checker,
                    mc,
                    state,
                    pool,
                    3,
                    2,
                    shutdown,
                    default_interval=60,
                )
            )
            await asyncio.sleep(0)
            shutdown.set()
            await asyncio.sleep(61)
            await task

        checker.check.assert_awaited_once()


class TestRunAll:
    @pytest.mark.looptime
    async def test_run_all_starts_all_enabled_monitors(self) -> None:
        config = _make_config(
            _http_monitor(id='http-1', interval=10),
            _ping_monitor(id='ping-1', interval=10),
        )
        pool = AsyncMock()
        client = MagicMock(spec=httpx.AsyncClient)
        shutdown = asyncio.Event()

        invoked_ids: list[str] = []

        async def fake_monitor_loop(
            monitor_id: str, *args: object, **kwargs: object
        ) -> None:
            invoked_ids.append(monitor_id)

        with patch('watchdog.scheduler.monitor_loop', new=fake_monitor_loop):
            await run_all(config, pool, client, shutdown)

        assert sorted(invoked_ids) == ['http-1', 'ping-1']
