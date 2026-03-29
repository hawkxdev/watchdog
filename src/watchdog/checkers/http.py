"""HTTP checker implementation."""

import time

import httpx

from watchdog.checkers.base import Checker, CheckResult


class HttpChecker(Checker):
    """HTTP endpoint checker."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        timeout: int = 10,
        expected_status: int = 200,
        follow_redirects: bool = True,
    ) -> None:
        """Configure HTTP checker."""
        self._client = client
        self._timeout = timeout
        self._expected_status = expected_status
        self._follow_redirects = follow_redirects

    async def check(self, target: str) -> CheckResult:
        """Check HTTP target."""
        start = time.monotonic()
        try:
            async with self._client.stream(
                'GET',
                target,
                timeout=self._timeout,
                follow_redirects=self._follow_redirects,
            ) as response:
                elapsed = (time.monotonic() - start) * 1000
                success = response.status_code == self._expected_status
                error = (
                    f'expected {self._expected_status},'
                    f' got {response.status_code}'
                    if not success
                    else None
                )
                return CheckResult(
                    success=success,
                    response_time_ms=elapsed,
                    status_code=response.status_code,
                    error=error,
                )
        except (
            httpx.TimeoutException,
            httpx.ConnectError,
            httpx.NetworkError,
            httpx.TooManyRedirects,
            httpx.InvalidURL,
        ) as exc:
            return CheckResult(
                success=False,
                error=str(exc),
            )
