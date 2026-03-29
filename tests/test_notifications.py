"""TelegramNotifier tests."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import httpx

from watchdog.notifications import (
    TelegramNotifier,
    format_down_alert,
    format_recovery_alert,
)
from watchdog.state import Transition


def _transition(
    to_status: str = 'DOWN',
    from_status: str = 'UP',
) -> Transition:
    return Transition(
        monitor_id='web-1',
        from_status=from_status,
        to_status=to_status,
        timestamp=datetime(2026, 3, 29, 12, 0, 0, tzinfo=UTC),
    )


def _notifier() -> tuple[TelegramNotifier, AsyncMock]:
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_client.post.return_value = mock_response
    notifier = TelegramNotifier(
        bot_token='mytoken',
        chat_id='999',
        http_client=mock_client,
    )
    return notifier, mock_client


class TestFormatDownAlert:
    def test_contains_monitor_name(self) -> None:
        msg = format_down_alert(
            'My Server',
            'https://x.com',
            None,
            datetime(2026, 3, 29, 12, 0, 0, tzinfo=UTC),
            3,
        )
        assert 'My Server' in msg

    def test_contains_target(self) -> None:
        msg = format_down_alert(
            'My Server',
            'https://x.com',
            None,
            datetime(2026, 3, 29, 12, 0, 0, tzinfo=UTC),
            3,
        )
        assert 'https://x.com' in msg

    def test_contains_error(self) -> None:
        msg = format_down_alert(
            'My Server',
            'https://x.com',
            'connection refused',
            datetime(2026, 3, 29, 12, 0, 0, tzinfo=UTC),
            3,
        )
        assert 'connection refused' in msg

    def test_contains_failed_checks(self) -> None:
        msg = format_down_alert(
            'My Server',
            'https://x.com',
            None,
            datetime(2026, 3, 29, 12, 0, 0, tzinfo=UTC),
            5,
        )
        assert '5' in msg

    def test_contains_timestamp(self) -> None:
        msg = format_down_alert(
            'My Server',
            'https://x.com',
            None,
            datetime(2026, 3, 29, 12, 0, 0, tzinfo=UTC),
            1,
        )
        assert '2026-03-29' in msg
        assert '12:00 UTC' in msg

    def test_html_bold_name(self) -> None:
        msg = format_down_alert(
            'My Server',
            'https://x.com',
            None,
            datetime(2026, 3, 29, 12, 0, 0, tzinfo=UTC),
            1,
        )
        assert '<b>My Server</b>' in msg

    def test_html_code_target(self) -> None:
        msg = format_down_alert(
            'My Server',
            'https://x.com',
            None,
            datetime(2026, 3, 29, 12, 0, 0, tzinfo=UTC),
            1,
        )
        assert '<code>' in msg

    def test_escapes_html_in_name(self) -> None:
        msg = format_down_alert(
            '<b>bad</b>',
            'https://x.com',
            None,
            datetime(2026, 3, 29, tzinfo=UTC),
            1,
        )
        assert '<b>bad</b>' not in msg
        assert '&lt;b&gt;bad&lt;/b&gt;' in msg

    def test_none_error_shows_unknown(self) -> None:
        msg = format_down_alert(
            'My Server',
            'https://x.com',
            None,
            datetime(2026, 3, 29, tzinfo=UTC),
            1,
        )
        assert 'unknown' in msg


class TestFormatRecoveryAlert:
    def test_contains_monitor_name(self) -> None:
        msg = format_recovery_alert('My Server', 'https://x.com', 120.0)
        assert 'My Server' in msg

    def test_contains_target(self) -> None:
        msg = format_recovery_alert('My Server', 'https://x.com', 120.0)
        assert 'https://x.com' in msg

    def test_contains_downtime_minutes(self) -> None:
        msg = format_recovery_alert('My Server', 'https://x.com', 125.0)
        assert '2m' in msg

    def test_contains_downtime_seconds_only(self) -> None:
        msg = format_recovery_alert('My Server', 'https://x.com', 45.0)
        assert '45s' in msg

    def test_html_bold_name(self) -> None:
        msg = format_recovery_alert('My Server', 'https://x.com', 60.0)
        assert '<b>My Server</b>' in msg

    def test_escapes_html_in_name(self) -> None:
        msg = format_recovery_alert('<script>', 'https://x.com', 60.0)
        assert '<script>' not in msg
        assert '&lt;script&gt;' in msg


class TestTelegramNotifierSendAlert:
    async def test_down_posts_to_correct_url(self) -> None:
        notifier, mock_client = _notifier()
        t = _transition(to_status='DOWN')
        result = await notifier.send_alert(
            t, 'My Server', 'https://x.com', error='timeout', failed_checks=1
        )
        assert result is True
        url = mock_client.post.call_args[0][0]
        assert 'mytoken' in url
        assert 'sendMessage' in url

    async def test_payload_has_html_parse_mode(self) -> None:
        notifier, mock_client = _notifier()
        t = _transition(to_status='DOWN')
        await notifier.send_alert(t, 'My Server', 'https://x.com')
        payload = mock_client.post.call_args[1]['json']
        assert payload['parse_mode'] == 'HTML'
        assert payload['chat_id'] == '999'

    async def test_recovery_posts_message(self) -> None:
        notifier, mock_client = _notifier()
        t = _transition(to_status='UP', from_status='DOWN')
        result = await notifier.send_alert(
            t, 'My Server', 'https://x.com', downtime_seconds=300.0
        )
        assert result is True
        payload = mock_client.post.call_args[1]['json']
        assert 'recovered' in payload['text']

    async def test_unknown_transition_returns_false_no_post(self) -> None:
        notifier, mock_client = _notifier()
        t = _transition(to_status='UNKNOWN')
        result = await notifier.send_alert(t, 'My Server', 'https://x.com')
        assert result is False
        mock_client.post.assert_not_called()

    async def test_request_error_returns_false(self) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.side_effect = httpx.RequestError('network down')
        notifier = TelegramNotifier('tok', '123', mock_client)
        t = _transition(to_status='DOWN')
        result = await notifier.send_alert(t, 'My Server', 'https://x.com')
        assert result is False

    async def test_http_status_error_returns_false(self) -> None:
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            '400', request=MagicMock(), response=MagicMock()
        )
        mock_client.post.return_value = mock_response
        notifier = TelegramNotifier('tok', '123', mock_client)
        t = _transition(to_status='DOWN')
        result = await notifier.send_alert(t, 'My Server', 'https://x.com')
        assert result is False

    async def test_down_alert_includes_target_in_text(self) -> None:
        notifier, mock_client = _notifier()
        t = _transition(to_status='DOWN')
        await notifier.send_alert(
            t,
            'My Server',
            'https://example.com',
            error='timeout',
            failed_checks=2,
        )
        payload = mock_client.post.call_args[1]['json']
        assert 'https://example.com' in payload['text']
        assert '2' in payload['text']
