"""Integration test: config -> monitors -> check -> state -> alert."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from watchdog.checkers.base import CheckResult
from watchdog.config import (
    AppConfig,
    DatabaseConfig,
    GeneralConfig,
    MonitorConfig,
    TelegramConfig,
)
from watchdog.notifications import TelegramNotifier
from watchdog.scheduler import run_all
from watchdog.state import MonitorState


def _make_config(*monitors: MonitorConfig) -> AppConfig:
    return AppConfig(
        general=GeneralConfig(
            check_interval=10,
            failure_threshold=1,
            success_threshold=1,
            retention_days=30,
        ),
        database=DatabaseConfig(dsn='postgresql://x:x@localhost/x'),
        telegram=TelegramConfig(
            bot_token='test-token', chat_id='999', enabled=True
        ),
        monitors=list(monitors),
    )


def _http_monitor(**kw: object) -> MonitorConfig:
    defaults = dict(
        id='web-1',
        name='My Web',
        type='http',
        target='https://example.com',
        interval=10,
        enabled=True,
        timeout=5,
    )
    defaults.update(kw)
    return MonitorConfig(**defaults)  # type: ignore[arg-type]


class TestIntegration:
    @pytest.mark.looptime
    async def test_down_alert_sent_on_state_transition(self) -> None:
        """Config -> monitor -> failed check -> DOWN transition -> Telegram alert."""
        config = _make_config(_http_monitor())
        pool = AsyncMock()
        shutdown = asyncio.Event()

        sent_payloads: list[dict] = []

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_http_client = AsyncMock(spec=httpx.AsyncClient)

        async def capture_post(url: str, **kwargs: object) -> MagicMock:
            sent_payloads.append(kwargs.get('json', {}))  # type: ignore[arg-type]
            return mock_response

        mock_http_client.post.side_effect = capture_post

        notifier = TelegramNotifier(
            bot_token='test-token',
            chat_id='999',
            http_client=mock_http_client,
        )

        async def one_shot_check(target: str) -> CheckResult:
            shutdown.set()
            return CheckResult(success=False, error='connection refused')

        checker = MagicMock()
        checker.check = one_shot_check

        with (
            patch('watchdog.scheduler.storage.insert_check', new=AsyncMock()),
            patch(
                'watchdog.scheduler.storage.insert_incident', new=AsyncMock()
            ),
            patch('watchdog.scheduler.create_monitors') as mock_create,
            patch(
                'watchdog.scheduler.retention_cleanup_loop', new=AsyncMock()
            ),
        ):
            mock_create.return_value = [
                (_http_monitor(), checker, MonitorState())
            ]

            await run_all(
                config, pool, mock_http_client, shutdown, notifier=notifier
            )

        assert len(sent_payloads) == 1
        payload = sent_payloads[0]
        assert payload['chat_id'] == '999'
        assert payload['parse_mode'] == 'HTML'
        assert 'My Web' in payload['text']

    @pytest.mark.looptime
    async def test_recovery_alert_sent_after_down(self) -> None:
        """DOWN then UP transition sends recovery alert."""
        config = _make_config(_http_monitor())
        pool = AsyncMock()
        shutdown = asyncio.Event()

        sent_texts: list[str] = []

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_http_client = AsyncMock(spec=httpx.AsyncClient)

        async def capture_post(url: str, **kwargs: object) -> MagicMock:
            payload = kwargs.get('json', {})
            sent_texts.append(payload.get('text', ''))  # type: ignore[union-attr]
            return mock_response

        mock_http_client.post.side_effect = capture_post

        notifier = TelegramNotifier(
            bot_token='test-token',
            chat_id='999',
            http_client=mock_http_client,
        )

        call_count = 0
        check_results = [
            CheckResult(success=False, error='timeout'),
            CheckResult(success=True, response_time_ms=50.0),
        ]

        async def two_shot_check(target: str) -> CheckResult:
            nonlocal call_count
            result = check_results[call_count]
            call_count += 1
            if call_count >= len(check_results):
                shutdown.set()
            return result

        checker = MagicMock()
        checker.check = two_shot_check

        with (
            patch('watchdog.scheduler.storage.insert_check', new=AsyncMock()),
            patch(
                'watchdog.scheduler.storage.insert_incident', new=AsyncMock()
            ),
            patch('watchdog.scheduler.create_monitors') as mock_create,
            patch(
                'watchdog.scheduler.retention_cleanup_loop', new=AsyncMock()
            ),
        ):
            mock_create.return_value = [
                (_http_monitor(), checker, MonitorState())
            ]

            task = asyncio.create_task(
                run_all(
                    config,
                    pool,
                    mock_http_client,
                    shutdown,
                    notifier=notifier,
                )
            )
            await asyncio.sleep(21)
            await task

        assert len(sent_texts) == 2
        assert any('DOWN' in t for t in sent_texts)
        assert any('recovered' in t for t in sent_texts)

    @pytest.mark.looptime
    async def test_no_alert_when_notifier_is_none(self) -> None:
        """No HTTP call when notifier=None."""
        config = _make_config(_http_monitor())
        pool = AsyncMock()
        mock_http_client = AsyncMock(spec=httpx.AsyncClient)
        shutdown = asyncio.Event()

        async def one_shot_check(target: str) -> CheckResult:
            shutdown.set()
            return CheckResult(success=False, error='timeout')

        checker = MagicMock()
        checker.check = one_shot_check

        with (
            patch('watchdog.scheduler.storage.insert_check', new=AsyncMock()),
            patch(
                'watchdog.scheduler.storage.insert_incident', new=AsyncMock()
            ),
            patch('watchdog.scheduler.create_monitors') as mock_create,
            patch(
                'watchdog.scheduler.retention_cleanup_loop', new=AsyncMock()
            ),
        ):
            mock_create.return_value = [
                (_http_monitor(), checker, MonitorState())
            ]

            await run_all(
                config, pool, mock_http_client, shutdown, notifier=None
            )

        mock_http_client.post.assert_not_called()
