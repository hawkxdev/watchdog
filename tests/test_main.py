"""Main entry point tests."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from watchdog.config import GeneralConfig, MonitorConfig


class TestGeneralConfigHeartbeatPort:
    def test_default_heartbeat_port(self) -> None:
        cfg = GeneralConfig()
        assert cfg.heartbeat_port == 8080

    def test_custom_heartbeat_port(self) -> None:
        cfg = GeneralConfig(heartbeat_port=9090)
        assert cfg.heartbeat_port == 9090

    def test_heartbeat_port_positive_validation(self) -> None:
        with pytest.raises(Exception):
            GeneralConfig(heartbeat_port=0)


class TestMainLifecycle:
    async def test_main_loads_config_and_exits_on_shutdown(self) -> None:
        import watchdog.__main__ as m

        mock_pool = AsyncMock()
        mock_pool.__aenter__ = AsyncMock(return_value=mock_pool)
        mock_pool.__aexit__ = AsyncMock(return_value=None)

        async def fake_run_all(
            config: object,
            pool: object,
            client: object,
            shutdown: asyncio.Event,
            **kwargs: object,
        ) -> None:
            shutdown.set()

        with (
            patch(
                'watchdog.__main__.load_config',
                return_value=MagicMock(
                    database=MagicMock(
                        dsn='postgresql://x:x@localhost/x',
                        min_pool_size=2,
                        max_pool_size=10,
                    ),
                    general=MagicMock(heartbeat_port=8080),
                    monitors=[],
                    telegram=MagicMock(enabled=False),
                ),
            ),
            patch(
                'watchdog.__main__.storage.create_pool',
                new=AsyncMock(return_value=mock_pool),
            ),
            patch('watchdog.__main__.storage.close_pool', new=AsyncMock()),
            patch('watchdog.__main__.storage.create_schema', new=AsyncMock()),
            patch('watchdog.__main__.run_all', new=fake_run_all),
        ):
            await m.main()

    async def test_main_starts_heartbeat_server_when_hb_monitors_present(
        self,
    ) -> None:
        import watchdog.__main__ as m

        mock_pool = AsyncMock()

        async def fake_run_all(
            config: object,
            pool: object,
            client: object,
            shutdown: asyncio.Event,
            **kwargs: object,
        ) -> None:
            shutdown.set()

        @asynccontextmanager
        async def fake_hb_server(
            app: object, host: str, port: int
        ) -> AsyncGenerator[None, None]:
            yield

        hb_monitor = MagicMock(spec=MonitorConfig)
        hb_monitor.type = 'heartbeat'
        hb_monitor.enabled = True
        hb_monitor.id = 'hb-1'

        mock_app = MagicMock()

        with (
            patch(
                'watchdog.__main__.load_config',
                return_value=MagicMock(
                    database=MagicMock(
                        dsn='postgresql://x:x@localhost/x',
                        min_pool_size=2,
                        max_pool_size=10,
                    ),
                    general=MagicMock(heartbeat_port=8080),
                    monitors=[hb_monitor],
                    telegram=MagicMock(enabled=False),
                ),
            ),
            patch(
                'watchdog.__main__.storage.create_pool',
                new=AsyncMock(return_value=mock_pool),
            ),
            patch('watchdog.__main__.storage.close_pool', new=AsyncMock()),
            patch('watchdog.__main__.storage.create_schema', new=AsyncMock()),
            patch(
                'watchdog.__main__.create_heartbeat_app',
                new=AsyncMock(return_value=mock_app),
            ),
            patch(
                'watchdog.__main__._heartbeat_server',
                new=fake_hb_server,
            ),
            patch('watchdog.__main__.run_all', new=fake_run_all),
        ):
            await m.main()
