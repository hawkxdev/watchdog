"""Telegram alert notifications."""

import logging
from datetime import datetime

import httpx

from watchdog.state import Transition

logger = logging.getLogger(__name__)


def _escape(text: str) -> str:
    """Escape HTML special chars."""
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def format_down_alert(
    monitor_name: str,
    target: str,
    error: str | None,
    timestamp: datetime,
    failed_checks: int,
) -> str:
    """HTML template for DOWN alert."""
    ts = timestamp.strftime('%Y-%m-%d %H:%M UTC')
    name = _escape(monitor_name)
    tgt = _escape(target)
    err = _escape(error) if error else 'unknown'
    return (
        f'\U0001f534 <b>{name}</b> is DOWN\n'
        f'Target: <code>{tgt}</code>\n'
        f'Error: {err}\n'
        f'Failed checks: {failed_checks}\n'
        f'Time: {ts}'
    )


def format_recovery_alert(
    monitor_name: str,
    target: str,
    downtime_seconds: float,
) -> str:
    """HTML template for RECOVERY alert."""
    name = _escape(monitor_name)
    tgt = _escape(target)
    minutes = int(downtime_seconds // 60)
    seconds = int(downtime_seconds % 60)
    downtime = f'{minutes}m {seconds}s' if minutes else f'{seconds}s'
    return (
        f'\U0001f7e2 <b>{name}</b> recovered\n'
        f'Target: <code>{tgt}</code>\n'
        f'Downtime: {downtime}'
    )


class TelegramNotifier:
    """Telegram alert sender."""

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        http_client: httpx.AsyncClient,
    ) -> None:
        """Store credentials and shared client."""
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._client = http_client

    async def send_alert(
        self,
        transition: Transition,
        monitor_name: str,
        target: str,
        error: str | None = None,
        failed_checks: int = 0,
        downtime_seconds: float = 0.0,
    ) -> bool:
        """Send DOWN or RECOVERY alert. Returns True on success."""
        if transition.to_status == 'DOWN':
            text = format_down_alert(
                monitor_name,
                target,
                error,
                transition.timestamp,
                failed_checks,
            )
        elif transition.to_status == 'UP':
            text = format_recovery_alert(
                monitor_name,
                target,
                downtime_seconds,
            )
        else:
            return False

        url = f'https://api.telegram.org/bot{self._bot_token}/sendMessage'
        payload = {
            'chat_id': self._chat_id,
            'text': text,
            'parse_mode': 'HTML',
        }
        try:
            response = await self._client.post(url, json=payload)
            _ = response.raise_for_status()
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            logger.warning('Telegram send failed: %s', type(exc).__name__)
            return False
        return True
