import asyncio
import logging


async def main() -> None:
    """Entry point stub."""
    logger = logging.getLogger('watchdog')
    logger.info('Watchdog starting...')
    logger.info('Watchdog stopped.')


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    )
    asyncio.run(main())
