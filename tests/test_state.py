"""State machine tests."""

import pytest

from watchdog.checkers.base import CheckResult
from watchdog.state import MonitorState, evaluate_check


def _success() -> CheckResult:
    return CheckResult(success=True, response_time_ms=10.0)


def _failure() -> CheckResult:
    return CheckResult(
        success=False,
        response_time_ms=None,
        error='timeout',
    )


class TestMonitorStateDefaults:
    def test_initial_status_unknown(self) -> None:
        s = MonitorState()
        assert s.status == 'UNKNOWN'
        assert s.consecutive_failures == 0
        assert s.consecutive_successes == 0
        assert s.last_check_time is None
        assert s.last_status_change is None


class TestEvaluateCheck:
    def test_unknown_to_up_on_first_success(self) -> None:
        s = MonitorState()
        t = evaluate_check(
            s,
            'mon1',
            _success(),
            failure_threshold=3,
            success_threshold=2,
        )
        assert s.status == 'UP'
        assert t is not None
        assert t.monitor_id == 'mon1'
        assert t.from_status == 'UNKNOWN'
        assert t.to_status == 'UP'

    def test_unknown_to_down_after_n_failures(self) -> None:
        s = MonitorState()
        evaluate_check(
            s,
            'mon1',
            _failure(),
            failure_threshold=3,
            success_threshold=2,
        )
        evaluate_check(
            s,
            'mon1',
            _failure(),
            failure_threshold=3,
            success_threshold=2,
        )
        t = evaluate_check(
            s,
            'mon1',
            _failure(),
            failure_threshold=3,
            success_threshold=2,
        )
        assert s.status == 'DOWN'
        assert t is not None
        assert t.from_status == 'UNKNOWN'
        assert t.to_status == 'DOWN'

    def test_up_stays_up_on_success(self) -> None:
        s = MonitorState(status='UP')
        t = evaluate_check(
            s,
            'mon1',
            _success(),
            failure_threshold=3,
            success_threshold=2,
        )
        assert s.status == 'UP'
        assert t is None

    def test_up_stays_up_on_single_failure(self) -> None:
        s = MonitorState(status='UP')
        t = evaluate_check(
            s,
            'mon1',
            _failure(),
            failure_threshold=3,
            success_threshold=2,
        )
        assert s.status == 'UP'
        assert t is None
        assert s.consecutive_failures == 1

    def test_up_to_down_after_n_failures(self) -> None:
        s = MonitorState(status='UP')
        evaluate_check(
            s,
            'mon1',
            _failure(),
            failure_threshold=3,
            success_threshold=2,
        )
        evaluate_check(
            s,
            'mon1',
            _failure(),
            failure_threshold=3,
            success_threshold=2,
        )
        t = evaluate_check(
            s,
            'mon1',
            _failure(),
            failure_threshold=3,
            success_threshold=2,
        )
        assert s.status == 'DOWN'
        assert t is not None
        assert t.from_status == 'UP'
        assert t.to_status == 'DOWN'

    def test_down_to_up_after_m_successes(self) -> None:
        s = MonitorState(status='DOWN')
        evaluate_check(
            s,
            'mon1',
            _success(),
            failure_threshold=3,
            success_threshold=2,
        )
        t = evaluate_check(
            s,
            'mon1',
            _success(),
            failure_threshold=3,
            success_threshold=2,
        )
        assert s.status == 'UP'
        assert t is not None
        assert t.from_status == 'DOWN'
        assert t.to_status == 'UP'

    def test_down_stays_down_on_single_success(self) -> None:
        s = MonitorState(status='DOWN')
        t = evaluate_check(
            s,
            'mon1',
            _success(),
            failure_threshold=3,
            success_threshold=2,
        )
        assert s.status == 'DOWN'
        assert t is None
        assert s.consecutive_successes == 1

    def test_no_transition_repeated_failures_in_down(self) -> None:
        s = MonitorState(status='DOWN')
        evaluate_check(
            s,
            'mon1',
            _failure(),
            failure_threshold=2,
            success_threshold=2,
        )
        t = evaluate_check(
            s,
            'mon1',
            _failure(),
            failure_threshold=2,
            success_threshold=2,
        )
        assert s.status == 'DOWN'
        assert t is None

    def test_failure_resets_success_counter(self) -> None:
        s = MonitorState(status='DOWN')
        evaluate_check(
            s,
            'mon1',
            _success(),
            failure_threshold=3,
            success_threshold=3,
        )
        evaluate_check(
            s,
            'mon1',
            _success(),
            failure_threshold=3,
            success_threshold=3,
        )
        evaluate_check(
            s,
            'mon1',
            _failure(),
            failure_threshold=3,
            success_threshold=3,
        )
        assert s.consecutive_successes == 0

    def test_success_resets_failure_counter(self) -> None:
        s = MonitorState(status='UP')
        evaluate_check(
            s,
            'mon1',
            _failure(),
            failure_threshold=3,
            success_threshold=2,
        )
        evaluate_check(
            s,
            'mon1',
            _failure(),
            failure_threshold=3,
            success_threshold=2,
        )
        evaluate_check(
            s,
            'mon1',
            _success(),
            failure_threshold=3,
            success_threshold=2,
        )
        assert s.consecutive_failures == 0

    def test_last_check_time_updated(self) -> None:
        s = MonitorState()
        assert s.last_check_time is None
        evaluate_check(
            s,
            'mon1',
            _success(),
            failure_threshold=3,
            success_threshold=2,
        )
        assert s.last_check_time is not None

    def test_last_status_change_set_on_transition(self) -> None:
        s = MonitorState()
        assert s.last_status_change is None
        evaluate_check(
            s,
            'mon1',
            _success(),
            failure_threshold=3,
            success_threshold=2,
        )
        assert s.last_status_change is not None

    def test_transition_has_timestamp(self) -> None:
        s = MonitorState()
        t = evaluate_check(
            s,
            'mon1',
            _success(),
            failure_threshold=3,
            success_threshold=2,
        )
        assert t is not None
        assert t.timestamp is not None

    @pytest.mark.parametrize('n', [1, 2, 5])
    def test_transitions_at_exact_threshold(self, n: int) -> None:
        s = MonitorState(status='UP')
        for i in range(n):
            t = evaluate_check(
                s,
                'mon1',
                _failure(),
                failure_threshold=n,
                success_threshold=n,
            )
            if i < n - 1:
                assert t is None
            else:
                assert t is not None
                assert t.to_status == 'DOWN'
        for i in range(n):
            t = evaluate_check(
                s,
                'mon1',
                _success(),
                failure_threshold=n,
                success_threshold=n,
            )
            if i < n - 1:
                assert t is None
            else:
                assert t is not None
                assert t.to_status == 'UP'
