"""Unit tests for client construction and the process entrypoint.

Neither module needs a live gateway to exercise: intent selection and the
config-to-run wiring are ordinary functions, and ``bot.run`` is substituted so
``main`` can be driven end to end without touching the network.
"""

from __future__ import annotations

from typing import Any

import pytest

from musicbot import __main__ as entrypoint
from musicbot.bot import INITIAL_EXTENSIONS, MusicBot, build_intents
from musicbot.config import Config


def test_build_intents_is_least_privilege() -> None:
    intents = build_intents()
    assert intents.guilds is True
    assert intents.voice_states is True
    # Privileged intents stay off until a cog genuinely needs them; enabling
    # one also requires a toggle in the Developer Portal.
    assert intents.message_content is False
    assert intents.members is False
    assert intents.presences is False


def test_music_is_the_only_extension_loaded() -> None:
    assert INITIAL_EXTENSIONS == ("musicbot.cogs.music",)


def test_bot_exposes_the_config_it_was_built_with() -> None:
    cfg = Config(token="t", log_level="INFO", dev_guild_id=None)
    bot = MusicBot(cfg)
    assert bot.config is cfg
    assert bot.intents.voice_states is True


def test_main_reports_config_errors_and_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    assert entrypoint.main() == 2
    assert "Configuration error" in capsys.readouterr().err


def test_main_starts_the_bot_with_the_configured_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "fake-token")
    monkeypatch.delenv("DEV_GUILD_ID", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    started: dict[str, Any] = {}

    def fake_run(self: MusicBot, token: str, **kwargs: Any) -> None:
        started["token"] = token
        started["log_handler"] = kwargs.get("log_handler", "unset")

    monkeypatch.setattr(MusicBot, "run", fake_run)

    assert entrypoint.main() == 0
    assert started["token"] == "fake-token"
    # discord.py installs its own handlers; main must not fight it.
    assert started["log_handler"] is None
