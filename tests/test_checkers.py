"""Checker tests."""

from dataclasses import FrozenInstanceError
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx
from icmplib import SocketPermissionError

from watchdog.checkers.base import CheckResult
from watchdog.checkers.http import HttpChecker
from watchdog.checkers.ping import PingChecker


class TestCheckResult:
    def test_success_result(self) -> None:
        r = CheckResult(success=True, response_time_ms=42.5)
        assert r.success is True
        assert r.response_time_ms == 42.5
        assert r.status_code is None
        assert r.error is None

    def test_failure_result(self) -> None:
        r = CheckResult(
            success=False,
            response_time_ms=None,
            error='timeout',
        )
        assert r.success is False
        assert r.response_time_ms is None
        assert r.error == 'timeout'

    def test_http_result_with_status(self) -> None:
        r = CheckResult(
            success=True,
            response_time_ms=100.0,
            status_code=200,
        )
        assert r.status_code == 200

    def test_frozen(self) -> None:
        r = CheckResult(success=True, response_time_ms=1.0)
        with pytest.raises(FrozenInstanceError):
            r.success = False  # type: ignore[misc]

    def test_defaults(self) -> None:
        r = CheckResult(success=True)
        assert r.response_time_ms is None
        assert r.status_code is None
        assert r.error is None


class TestHttpChecker:
    async def test_success_200(self, respx_mock: respx.MockRouter) -> None:
        respx_mock.get('https://example.com/health').mock(
            return_value=httpx.Response(200)
        )
        async with httpx.AsyncClient() as client:
            checker = HttpChecker(
                client=client,
                timeout=5,
                expected_status=200,
            )
            result = await checker.check('https://example.com/health')
        assert result.success is True
        assert result.status_code == 200
        assert result.response_time_ms is not None
        assert result.response_time_ms >= 0
        assert result.error is None

    async def test_unexpected_status(
        self, respx_mock: respx.MockRouter
    ) -> None:
        respx_mock.get('https://example.com/health').mock(
            return_value=httpx.Response(503)
        )
        async with httpx.AsyncClient() as client:
            checker = HttpChecker(
                client=client,
                timeout=5,
                expected_status=200,
            )
            result = await checker.check('https://example.com/health')
        assert result.success is False
        assert result.status_code == 503
        assert result.error is not None

    async def test_connection_error(
        self, respx_mock: respx.MockRouter
    ) -> None:
        respx_mock.get('https://example.com/health').mock(
            side_effect=httpx.ConnectError('refused')
        )
        async with httpx.AsyncClient() as client:
            checker = HttpChecker(
                client=client,
                timeout=5,
                expected_status=200,
            )
            result = await checker.check('https://example.com/health')
        assert result.success is False
        assert result.response_time_ms is None
        assert result.error is not None

    async def test_timeout_error(self, respx_mock: respx.MockRouter) -> None:
        respx_mock.get('https://example.com/health').mock(
            side_effect=httpx.TimeoutException('timed out')
        )
        async with httpx.AsyncClient() as client:
            checker = HttpChecker(
                client=client,
                timeout=5,
                expected_status=200,
            )
            result = await checker.check('https://example.com/health')
        assert result.success is False
        assert result.error is not None

    async def test_custom_expected_status(
        self, respx_mock: respx.MockRouter
    ) -> None:
        respx_mock.get('https://example.com/redirect').mock(
            return_value=httpx.Response(301)
        )
        async with httpx.AsyncClient() as client:
            checker = HttpChecker(
                client=client,
                timeout=5,
                expected_status=301,
            )
            result = await checker.check('https://example.com/redirect')
        assert result.success is True
        assert result.status_code == 301

    async def test_shared_client_reused(
        self, respx_mock: respx.MockRouter
    ) -> None:
        respx_mock.get('https://example.com/').mock(
            return_value=httpx.Response(200)
        )
        async with httpx.AsyncClient() as client:
            checker = HttpChecker(
                client=client,
                timeout=5,
                expected_status=200,
            )
            r1 = await checker.check('https://example.com/')
            r2 = await checker.check('https://example.com/')
        assert r1.success is True
        assert r2.success is True


class TestPingChecker:
    async def test_success_ping(self) -> None:
        mock_result = AsyncMock()
        mock_result.is_alive = True
        mock_result.avg_rtt = 12.5

        with patch(
            'watchdog.checkers.ping.async_ping',
            new=AsyncMock(return_value=mock_result),
        ):
            checker = PingChecker(count=3, timeout=5)
            result = await checker.check('8.8.8.8')

        assert result.success is True
        assert result.response_time_ms == 12.5
        assert result.error is None

    async def test_host_unreachable(self) -> None:
        mock_result = AsyncMock()
        mock_result.is_alive = False
        mock_result.avg_rtt = 0.0

        with patch(
            'watchdog.checkers.ping.async_ping',
            new=AsyncMock(return_value=mock_result),
        ):
            checker = PingChecker(count=3, timeout=5)
            result = await checker.check('192.0.2.1')

        assert result.success is False
        assert result.error is not None

    async def test_permission_error(self) -> None:
        with patch(
            'watchdog.checkers.ping.async_ping',
            new=AsyncMock(side_effect=SocketPermissionError(False)),
        ):
            checker = PingChecker(count=3, timeout=5)
            result = await checker.check('8.8.8.8')

        assert result.success is False
        assert result.error is not None
        assert 'ICMP' in result.error

    async def test_os_error(self) -> None:
        with patch(
            'watchdog.checkers.ping.async_ping',
            new=AsyncMock(side_effect=OSError('network unreachable')),
        ):
            checker = PingChecker(count=3, timeout=5)
            result = await checker.check('10.0.0.1')

        assert result.success is False
        assert result.error is not None
