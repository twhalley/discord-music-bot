"""Console entrypoint: load config, configure logging, and run the bot."""

from __future__ import annotations

import logging
import sys

from musicbot.bot import MusicBot
from musicbot.config import Config, ConfigError


def main() -> int:
    """Start the bot. Returns a process exit code."""
    try:
        config = Config.from_env()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    logging.basicConfig(
        level=getattr(logging, config.log_level, logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    bot = MusicBot(config)
    # discord.py installs its own logging handlers; let it manage its loggers.
    bot.run(config.token, log_handler=None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
