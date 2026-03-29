"""Monitor scheduler."""

import asyncio
import logging

import asyncpg
import httpx

from watchdog import storage
from watchdog.checkers.base import Checker, CheckResult
from watchdog.checkers.heartbeat import HeartbeatChecker
from watchdog.checkers.http import HttpChecker
from watchdog.checkers.ping import PingChecker
from watchdog.config import AppConfig, MonitorConfig
from watchdog.state import MonitorState, evaluate_check

logger = logging.getLogger(__name__)


async def monitor_loop(
    monitor_id: str,
    checker: Checker,
    config: MonitorConfig,
    state: MonitorState,
    pool: asyncpg.Pool,
    failure_threshold: int,
    success_threshold: int,
    shutdown: asyncio.Event,
    default_interval: int = 60,
) -> None:
    """Run single monitor check loop."""
    interval = config.interval or default_interval
    check_timeout = config.timeout or default_interval
    while not shutdown.is_set():
        try:
            async with asyncio.timeout(check_timeout):
                result = await checker.check(config.target)
        except TimeoutError:
            result = CheckResult(success=False, error='check timed out')
        await storage.insert_check(
            pool,
            monitor_id,
            result.success,
            result.response_time_ms,
            result.status_code,
            result.error,
        )
        transition = evaluate_check(
            state,
            monitor_id,
            result,
            failure_threshold,
            success_threshold,
        )
        if transition:
            await storage.insert_incident(
                pool,
                monitor_id,
                transition.to_status,
                f'{transition.from_status} -> {transition.to_status}',
            )
            logger.info(
                'Monitor %s: %s -> %s',
                monitor_id,
                transition.from_status,
                transition.to_status,
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


async def run_all(
    config: AppConfig,
    pool: asyncpg.Pool,
    http_client: httpx.AsyncClient,
    shutdown: asyncio.Event,
) -> None:
    """Run all monitors in TaskGroup."""
    monitors = create_monitors(config, pool, http_client)
    async with asyncio.TaskGroup() as tg:
        for mc, checker, state in monitors:
            tg.create_task(
                monitor_loop(
                    mc.id,
                    checker,
                    mc,
                    state,
                    pool,
                    config.general.failure_threshold,
                    config.general.success_threshold,
                    shutdown,
                    default_interval=config.general.check_interval,
                ),
                name=f'monitor-{mc.id}',
            )
