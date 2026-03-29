"""Application entry point."""

import asyncio
import logging
import os
import signal
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager

import aiohttp.web
import httpx

from watchdog import storage
from watchdog.checkers.heartbeat import create_heartbeat_app
from watchdog.config import load_config
from watchdog.notifications import TelegramNotifier
from watchdog.scheduler import run_all

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _heartbeat_server(
    app: aiohttp.web.Application,
    host: str,
    port: int,
) -> AsyncGenerator[None, None]:
    """Manage aiohttp AppRunner lifecycle."""
    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, host, port)
    await site.start()
    logger.info('Heartbeat server listening on %s:%d', host, port)
    try:
        yield
    finally:
        await runner.cleanup()
        logger.info('Heartbeat server stopped')


async def main() -> None:
    """Application entry point."""
    config = load_config(os.environ.get('CONFIG_PATH', 'config.toml'))

    shutdown = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, shutdown.set)

    async with AsyncExitStack() as stack:
        pool = await storage.create_pool(
            config.database.dsn,
            min_size=config.database.min_pool_size,
            max_size=config.database.max_pool_size,
        )
        stack.push_async_callback(storage.close_pool, pool)
        await storage.create_schema(pool)

        http_client = await stack.enter_async_context(
            httpx.AsyncClient(max_redirects=5)
        )

        hb_ids = {
            m.id
            for m in config.monitors
            if m.type == 'heartbeat' and m.enabled
        }
        if hb_ids:
            app = await create_heartbeat_app(pool, known_ids=hb_ids)
            await stack.enter_async_context(
                _heartbeat_server(
                    app, '0.0.0.0', config.general.heartbeat_port
                )
            )

        notifier = (
            TelegramNotifier(
                bot_token=config.telegram.bot_token,
                chat_id=config.telegram.chat_id,
                http_client=http_client,
            )
            if config.telegram.enabled
            else None
        )

        await run_all(config, pool, http_client, shutdown, notifier=notifier)


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    )
    asyncio.run(main())
