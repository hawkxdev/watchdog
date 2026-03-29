"""Monitor state machine."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from watchdog.checkers.base import CheckResult

Status = Literal['UNKNOWN', 'UP', 'DOWN']


@dataclass(frozen=True, slots=True)
class Transition:
    """State change event."""

    monitor_id: str
    from_status: Status
    to_status: Status
    timestamp: datetime


@dataclass
class MonitorState:
    """Per-monitor state tracker."""

    status: Status = 'UNKNOWN'
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    last_check_time: datetime | None = None
    last_status_change: datetime | None = None


def evaluate_check(
    state: MonitorState,
    monitor_id: str,
    result: CheckResult,
    failure_threshold: int,
    success_threshold: int,
) -> Transition | None:
    """Update state and detect transition."""
    now = datetime.now(UTC)
    state.last_check_time = now

    if result.success:
        state.consecutive_failures = 0
        state.consecutive_successes += 1
    else:
        state.consecutive_successes = 0
        state.consecutive_failures += 1

    new_status = _next_status(
        state.status,
        state.consecutive_failures,
        state.consecutive_successes,
        failure_threshold,
        success_threshold,
    )

    if new_status == state.status:
        return None

    from_status = state.status
    state.status = new_status
    state.last_status_change = now
    return Transition(
        monitor_id=monitor_id,
        from_status=from_status,
        to_status=new_status,
        timestamp=now,
    )


def _next_status(
    current: Status,
    failures: int,
    successes: int,
    failure_threshold: int,
    success_threshold: int,
) -> Status:
    """Compute next status."""
    if current in ('UNKNOWN', 'UP') and failures >= failure_threshold:
        return 'DOWN'
    if current == 'UNKNOWN' and successes >= 1:
        return 'UP'
    if current == 'DOWN' and successes >= success_threshold:
        return 'UP'
    return current
