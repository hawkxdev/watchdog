"""Heartbeat checker and receiver."""

import logging
import re
from datetime import UTC, datetime, timedelta

import aiohttp.web
import asyncpg
import asyncpg.exceptions

from watchdog import storage
from watchdog.checkers.base import Checker, CheckResult

logger = logging.getLogger(__name__)

_POOL_KEY: aiohttp.web.AppKey[asyncpg.Pool] = aiohttp.web.AppKey('pool')
_KNOWN_IDS_KEY: aiohttp.web.AppKey[set[str]] = aiohttp.web.AppKey('known_ids')


class HeartbeatChecker(Checker):
    """Deadline-based heartbeat checker."""

    def __init__(
        self,
        pool: asyncpg.Pool,
        interval: int,
        grace: int = 0,
    ) -> None:
        """Configure heartbeat checker."""
        self._pool = pool
        self._interval = interval
        self._grace = grace

    async def check(self, target: str) -> CheckResult:
        """Evaluate heartbeat deadline."""
        last_ping = await storage.get_last_heartbeat_ping(self._pool, target)
        if last_ping is None:
            return CheckResult(
                success=False,
                error='no heartbeat received',
            )
        now = datetime.now(UTC)
        deadline = last_ping + timedelta(seconds=self._interval + self._grace)
        if now > deadline:
            overdue_s = (now - deadline).total_seconds()
            return CheckResult(
                success=False,
                error=f'heartbeat overdue by {overdue_s:.1f}s',
            )
        elapsed_ms = (now - last_ping).total_seconds() * 1000
        return CheckResult(
            success=True,
            response_time_ms=elapsed_ms,
        )


_MONITOR_ID_RE = re.compile(r'^[a-z0-9_-]{1,100}$')


async def _handle_ping(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """Handle incoming heartbeat ping."""
    monitor_id = request.match_info['monitor_id']
    if not _MONITOR_ID_RE.match(monitor_id):
        return aiohttp.web.json_response(
            {'error': 'invalid monitor_id'}, status=400
        )
    known_ids = request.app[_KNOWN_IDS_KEY]
    if known_ids and monitor_id not in known_ids:
        return aiohttp.web.json_response(
            {'error': 'unknown monitor'}, status=404
        )
    pool = request.app[_POOL_KEY]
    try:
        await storage.upsert_heartbeat_ping(pool, monitor_id)
    except (asyncpg.PostgresError, OSError):
        logger.exception('Heartbeat upsert failed for %s', monitor_id)
        return aiohttp.web.json_response(
            {'error': 'internal error'}, status=500
        )
    return aiohttp.web.json_response(
        {'status': 'ok', 'monitor_id': monitor_id}
    )


async def create_heartbeat_app(
    pool: asyncpg.Pool,
    known_ids: set[str] | None = None,
) -> aiohttp.web.Application:
    """Create aiohttp app for heartbeat receiver."""
    app = aiohttp.web.Application()
    app[_POOL_KEY] = pool
    app[_KNOWN_IDS_KEY] = known_ids or set()
    app.router.add_post('/{monitor_id}', _handle_ping)
    return app
