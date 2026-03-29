"""Retention cleanup loop tests."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from watchdog.scheduler import retention_cleanup_loop


def _patches() -> tuple:
    """Create check and incident cleanup mocks."""
    mock_checks = AsyncMock(return_value=0)
    mock_incidents = AsyncMock(return_value=0)
    return (
        mock_checks,
        mock_incidents,
        patch(
            'watchdog.scheduler.storage.cleanup_old_checks',
            new=mock_checks,
        ),
        patch(
            'watchdog.scheduler.storage.cleanup_old_incidents',
            new=mock_incidents,
        ),
    )


class TestRetentionCleanupLoop:
    @pytest.mark.looptime
    async def test_shutdown_runs_startup_cleanup_only(self) -> None:
        pool = AsyncMock()
        shutdown = asyncio.Event()
        shutdown.set()

        mock_checks, mock_incidents, p1, p2 = _patches()
        with p1, p2:
            await retention_cleanup_loop(pool, 30, shutdown, interval_hours=24)

        mock_checks.assert_awaited_once_with(pool, 30)
        mock_incidents.assert_awaited_once_with(pool, 30)

    @pytest.mark.looptime
    async def test_cleanup_called_after_interval(self) -> None:
        pool = AsyncMock()
        shutdown = asyncio.Event()

        mock_checks, mock_incidents, p1, p2 = _patches()
        with p1, p2:
            task = asyncio.create_task(
                retention_cleanup_loop(pool, 30, shutdown, interval_hours=1)
            )
            await asyncio.sleep(3600)
            shutdown.set()
            await asyncio.sleep(1)
            await task

        assert mock_checks.await_count == 2
        assert mock_incidents.await_count == 2

    @pytest.mark.looptime
    async def test_cleanup_called_with_correct_retention_days(
        self,
    ) -> None:
        pool = AsyncMock()
        shutdown = asyncio.Event()

        mock_checks, mock_incidents, p1, p2 = _patches()
        with p1, p2:
            task = asyncio.create_task(
                retention_cleanup_loop(pool, 7, shutdown, interval_hours=1)
            )
            await asyncio.sleep(3600)
            shutdown.set()
            await asyncio.sleep(1)
            await task

        mock_checks.assert_any_await(pool, 7)
        mock_incidents.assert_any_await(pool, 7)

    @pytest.mark.looptime
    async def test_cleanup_runs_multiple_times(self) -> None:
        pool = AsyncMock()
        shutdown = asyncio.Event()

        mock_checks, mock_incidents, p1, p2 = _patches()
        with p1, p2:
            task = asyncio.create_task(
                retention_cleanup_loop(pool, 30, shutdown, interval_hours=1)
            )
            await asyncio.sleep(7300)
            shutdown.set()
            await asyncio.sleep(1)
            await task

        assert mock_checks.await_count == 3
        assert mock_incidents.await_count == 3
