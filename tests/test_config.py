"""Unit tests for environment configuration parsing."""

from __future__ import annotations

import pytest

from musicbot.config import Config, ConfigError


def test_from_env_reads_token_and_defaults() -> None:
    cfg = Config.from_env({"DISCORD_BOT_TOKEN": "abc"})
    assert cfg.token == "abc"
    assert cfg.log_level == "INFO"
    assert cfg.dev_guild_id is None


def test_from_env_parses_optional_fields() -> None:
    cfg = Config.from_env({"DISCORD_BOT_TOKEN": "abc", "LOG_LEVEL": "debug", "DEV_GUILD_ID": "123"})
    assert cfg.log_level == "DEBUG"
    assert cfg.dev_guild_id == 123


def test_missing_token_fails_fast() -> None:
    with pytest.raises(ConfigError, match="DISCORD_BOT_TOKEN"):
        Config.from_env({})


def test_blank_token_fails_fast() -> None:
    with pytest.raises(ConfigError, match="DISCORD_BOT_TOKEN"):
        Config.from_env({"DISCORD_BOT_TOKEN": "   "})


def test_non_integer_guild_id_is_rejected() -> None:
    with pytest.raises(ConfigError, match="DEV_GUILD_ID"):
        Config.from_env({"DISCORD_BOT_TOKEN": "abc", "DEV_GUILD_ID": "not-a-number"})


def test_config_is_immutable() -> None:
    cfg = Config.from_env({"DISCORD_BOT_TOKEN": "abc"})
    with pytest.raises((AttributeError, TypeError)):
        cfg.token = "changed"  # type: ignore[misc]
