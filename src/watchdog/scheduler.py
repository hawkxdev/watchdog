"""Monitor scheduler."""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import asyncpg
import httpx

from watchdog import storage
from watchdog.checkers.base import Checker, CheckResult
from watchdog.checkers.heartbeat import HeartbeatChecker
from watchdog.checkers.http import HttpChecker
from watchdog.checkers.ping import PingChecker
from watchdog.config import AppConfig, GeneralConfig, MonitorConfig
from watchdog.state import MonitorState, evaluate_check

if TYPE_CHECKING:
    from watchdog.notifications import TelegramNotifier

logger = logging.getLogger(__name__)


def _calc_downtime(state: MonitorState) -> float:
    """Compute downtime seconds for recovery transition."""
    if state.last_status_change is None:
        return 0.0
    return (datetime.now(UTC) - state.last_status_change).total_seconds()


async def monitor_loop(
    checker: Checker,
    config: MonitorConfig,
    state: MonitorState,
    pool: asyncpg.Pool,
    general: GeneralConfig,
    shutdown: asyncio.Event,
    notifier: 'TelegramNotifier | None' = None,
) -> None:
    """Run single monitor check loop."""
    interval = config.interval or general.check_interval
    check_timeout = config.timeout or 10
    while not shutdown.is_set():
        try:
            async with asyncio.timeout(check_timeout):
                result = await checker.check(config.target)
        except TimeoutError:
            result = CheckResult(success=False, error='check timed out')
        await storage.insert_check(
            pool,
            config.id,
            result.success,
            result.response_time_ms,
            result.status_code,
            result.error,
        )
        transition = evaluate_check(
            state,
            config.id,
            result,
            general.failure_threshold,
            general.success_threshold,
        )
        if transition:
            await storage.insert_incident(
                pool,
                config.id,
                transition.to_status,
                f'{transition.from_status} -> {transition.to_status}',
            )
            logger.info(
                'Monitor %s: %s -> %s',
                config.id,
                transition.from_status,
                transition.to_status,
            )
            if notifier:
                await notifier.send_alert(
                    transition=transition,
                    monitor_name=config.name,
                    target=config.target,
                    error=result.error,
                    failed_checks=state.consecutive_failures,
                    downtime_seconds=_calc_downtime(state),
                )
        try:
            async with asyncio.timeout(interval):
                await shutdown.wait()
                return
        except TimeoutError:
            continue


def create_monitors(
    config: AppConfig,
    pool: asyncpg.Pool,
    http_client: httpx.AsyncClient,
) -> list[tuple[MonitorConfig, Checker, MonitorState]]:
    """Instantiate checkers from config."""
    result: list[tuple[MonitorConfig, Checker, MonitorState]] = []
    for mc in config.monitors:
        if not mc.enabled:
            continue
        checker: Checker
        if mc.type == 'http':
            checker = HttpChecker(
                client=http_client,
                timeout=mc.timeout or 10,
                expected_status=mc.expected_status or 200,
            )
        elif mc.type == 'ping':
            checker = PingChecker(count=3, timeout=mc.timeout or 5)
        elif mc.type == 'heartbeat':
            checker = HeartbeatChecker(
                pool=pool,
                interval=mc.interval or config.general.check_interval,
                grace=mc.timeout or 0,
            )
        else:
            logger.warning('Unknown monitor type %r, skipping', mc.type)
            continue
        result.append((mc, checker, MonitorState()))
    return result


async def retention_cleanup_loop(
    pool: asyncpg.Pool,
    retention_days: int,
    shutdown: asyncio.Event,
    interval_hours: int = 24,
) -> None:
    """Periodic retention cleanup."""
    await storage.cleanup_old_checks(pool, retention_days)
    await storage.cleanup_old_incidents(pool, retention_days)
    interval = interval_hours * 3600
    while not shutdown.is_set():
        try:
            async with asyncio.timeout(interval):
                await shutdown.wait()
                return
        except TimeoutError:
            pass
        await storage.cleanup_old_checks(pool, retention_days)
        await storage.cleanup_old_incidents(pool, retention_days)


async def _tick_loop(
    callback: Callable[[], None],
    shutdown: asyncio.Event,
    interval: int = 30,
) -> None:
    """Periodically call callback until shutdown."""
    while not shutdown.is_set():
        try:
            callback()
        except Exception:
            logger.warning('on_tick callback failed', exc_info=True)
        try:
            async with asyncio.timeout(interval):
                await shutdown.wait()
                return
        except TimeoutError:
            continue


async def run_all(
    config: AppConfig,
    pool: asyncpg.Pool,
    http_client: httpx.AsyncClient,
    shutdown: asyncio.Event,
    notifier: 'TelegramNotifier | None' = None,
    on_tick: Callable[[], None] | None = None,
) -> None:
    """Run all monitors in TaskGroup."""
    monitors = create_monitors(config, pool, http_client)
    async with asyncio.TaskGroup() as tg:
        for mc, checker, state in monitors:
            tg.create_task(
                monitor_loop(
                    checker,
                    mc,
                    state,
                    pool,
                    config.general,
                    shutdown,
                    notifier=notifier,
                ),
                name=f'monitor-{mc.id}',
            )
        tg.create_task(
            retention_cleanup_loop(
                pool,
                config.general.retention_days,
                shutdown,
            ),
            name='retention',
        )
        if on_tick:
            tg.create_task(
                _tick_loop(on_tick, shutdown),
                name='sd-notify',
            )
