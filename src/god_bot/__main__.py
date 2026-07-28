from __future__ import annotations

import asyncio
import logging
import signal

from .bot import LearningBot
from .config import Config

LOGGER = logging.getLogger(__name__)


async def _run_bot(config: Config) -> None:
    bot = LearningBot(config)
    stop_requested = asyncio.Event()
    loop = asyncio.get_running_loop()

    def request_stop(signal_name: str) -> None:
        LOGGER.info("Received %s; shutting down gracefully", signal_name)
        stop_requested.set()

    for handled_signal in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(
            handled_signal,
            request_stop,
            handled_signal.name,
        )

    bot_task = asyncio.create_task(bot.start(config.token))
    stop_task = asyncio.create_task(stop_requested.wait())
    done, _ = await asyncio.wait(
        {bot_task, stop_task},
        return_when=asyncio.FIRST_COMPLETED,
    )
    if stop_task in done:
        await bot.close()
        await bot_task
    else:
        stop_task.cancel()
        await bot_task


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        config = Config.from_env()
    except ValueError as error:
        raise SystemExit(f"Configuration error: {error}") from error

    try:
        asyncio.run(_run_bot(config))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
