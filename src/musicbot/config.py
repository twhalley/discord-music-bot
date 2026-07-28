"""Runtime configuration, loaded and validated from the environment.

The bot fails fast on startup if required configuration is missing, so a
misconfigured deployment never reaches Discord with a half-valid state.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class Config:
    """Validated, immutable runtime configuration."""

    token: str
    log_level: str
    # Optional guild id for instant (guild-scoped) slash-command sync during
    # development. Global sync can take up to an hour to propagate.
    dev_guild_id: int | None
    # Guilds the bot is permitted to serve. Empty means "any", which is the
    # historical behaviour. Setting it bounds the damage if an invite link
    # leaks: the bot leaves anywhere it is not wanted instead of quietly
    # streaming for strangers on your infrastructure.
    allowed_guild_ids: frozenset[int]

    def is_guild_allowed(self, guild_id: int) -> bool:
        """True if the bot should serve ``guild_id``."""
        return not self.allowed_guild_ids or guild_id in self.allowed_guild_ids

    @staticmethod
    def from_env(env: dict[str, str] | None = None) -> Config:
        """Build a Config from environment variables.

        Args:
            env: Mapping to read from. Defaults to ``os.environ``. Injected in
                tests so we never depend on the real process environment.
        """
        source = os.environ if env is None else env

        token = source.get("DISCORD_BOT_TOKEN", "").strip()
        if not token:
            raise ConfigError(
                "DISCORD_BOT_TOKEN is not set. Refusing to start without a bot token."
            )

        raw_guild = source.get("DEV_GUILD_ID", "").strip()
        dev_guild_id: int | None = None
        if raw_guild:
            try:
                dev_guild_id = int(raw_guild)
            except ValueError as exc:
                raise ConfigError(f"DEV_GUILD_ID must be an integer, got {raw_guild!r}") from exc

        log_level = source.get("LOG_LEVEL", "INFO").strip().upper()

        raw_allowed = source.get("ALLOWED_GUILD_IDS", "").strip()
        allowed: set[int] = set()
        if raw_allowed:
            for part in raw_allowed.split(","):
                candidate = part.strip()
                if not candidate:
                    continue
                try:
                    allowed.add(int(candidate))
                except ValueError as exc:
                    raise ConfigError(
                        f"ALLOWED_GUILD_IDS must be a comma-separated list of "
                        f"integers, got {candidate!r}"
                    ) from exc

        return Config(
            token=token,
            log_level=log_level,
            dev_guild_id=dev_guild_id,
            allowed_guild_ids=frozenset(allowed),
        )
