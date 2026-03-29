"""ICMP ping checker."""

from icmplib import SocketPermissionError, async_ping

from watchdog.checkers.base import Checker, CheckResult


class PingChecker(Checker):
    """ICMP ping checker."""

    def __init__(self, count: int = 3, timeout: int = 5) -> None:
        """Configure ping checker."""
        self._count = count
        self._timeout = timeout

    async def check(self, target: str) -> CheckResult:
        """Ping target host."""
        try:
            result = await async_ping(
                target,
                count=self._count,
                timeout=self._timeout,
                privileged=False,
            )
            if result.is_alive:
                return CheckResult(
                    success=True,
                    response_time_ms=result.avg_rtt,
                )
            return CheckResult(
                success=False,
                error=f'host unreachable: {target}',
            )
        except SocketPermissionError:
            return CheckResult(
                success=False,
                error='ICMP requires elevated privileges',
            )
        except OSError as exc:
            return CheckResult(
                success=False,
                error=str(exc),
            )
        except Exception as exc:
            return CheckResult(
                success=False,
                error=f'{type(exc).__name__}: {exc}',
            )
