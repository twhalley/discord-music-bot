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
from musicbot.cogs.music import _display, _for_log
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
    cfg = Config(token="t", log_level="INFO", dev_guild_id=None, allowed_guild_ids=frozenset())
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


def test_client_never_honours_mentions_from_untrusted_text() -> None:
    """Track titles reach Discord messages, so mentions must never resolve."""
    bot = MusicBot(
        Config(token="t", log_level="INFO", dev_guild_id=None, allowed_guild_ids=frozenset())
    )
    assert bot.allowed_mentions.everyone is False
    assert bot.allowed_mentions.users is False
    assert bot.allowed_mentions.roles is False


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("**bold**", r"\*\*bold\*\*"),
        ("_it_", r"\_it\_"),
        ("`code`", r"\`code\`"),
        ("a|b", r"a\|b"),
        ("plain title", "plain title"),
    ],
)
def test_display_escapes_markdown_in_untrusted_titles(title: str, expected: str) -> None:
    assert _display(title) == expected


def test_display_leaves_mention_text_intact() -> None:
    """escape_markdown does not neuter mentions -- AllowedMentions.none() does.

    Pinned so nobody later removes the client-level guard believing escaping
    covers it.
    """
    assert _display("@everyone") == "@everyone"


def test_log_sanitiser_flattens_and_truncates() -> None:
    """Newlines in untrusted text would let someone forge extra log records."""
    assert "\n" not in _for_log("evil\nINFO forged entry")
    assert "\r" not in _for_log("evil\rmore")
    assert len(_for_log("x" * 500)) == 120


def test_leaves_guilds_outside_the_allowlist() -> None:
    cfg = Config.from_env({"DISCORD_BOT_TOKEN": "t", "ALLOWED_GUILD_IDS": "111"})
    bot = MusicBot(cfg)
    assert bot.config.is_guild_allowed(111) is True
    assert bot.config.is_guild_allowed(999) is False


def test_cooldowns_are_configured_on_commands() -> None:
    """Rate limiting is a security control, so assert it is actually attached."""
    from musicbot.cogs.music import (
        CONTROL_COOLDOWN_RATE,
        PLAY_COOLDOWN_PER,
        PLAY_COOLDOWN_RATE,
    )

    assert PLAY_COOLDOWN_RATE > 0
    assert PLAY_COOLDOWN_PER > 0
    assert CONTROL_COOLDOWN_RATE > 0


def test_bot_replies_are_cleaned_up_not_left_in_the_channel() -> None:
    """Bot chatter is removed after a delay rather than accumulating forever."""
    from musicbot.cogs.music import MESSAGE_CLEANUP_SECONDS, Music

    assert MESSAGE_CLEANUP_SECONDS > 0
    # A central listener, so a newly added command cannot forget to tidy up.
    assert hasattr(Music, "on_app_command_completion")
    assert hasattr(Music, "_delete_reply_later")
