"""The Discord client: least-privilege intents, cog loading, and command sync."""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

from musicbot.config import Config

log = logging.getLogger(__name__)

# Extensions (cogs) to load on startup. Add "musicbot.cogs.embedfix" here when
# the embed-fixer cog lands (it will additionally require the message_content
# intent below).
INITIAL_EXTENSIONS: tuple[str, ...] = ("musicbot.cogs.music",)


def build_intents() -> discord.Intents:
    """Return the minimal gateway intents the bot needs.

    Music playback needs only voice-state and guild info — NOT the privileged
    message-content intent. When the embed-fixer cog is added, enable
    ``intents.message_content = True`` here and toggle it in the Developer Portal.
    """
    intents = discord.Intents.none()
    intents.guilds = True
    intents.voice_states = True
    return intents


class MusicBot(commands.Bot):
    """Bot subclass that loads cogs and syncs application commands on startup."""

    def __init__(self, config: Config) -> None:
        self.config = config
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=build_intents(),
            # Track titles come from yt-dlp and are attacker-controlled: anyone
            # can upload a video called "@everyone" and get it queued. Since the
            # bot echoes titles back into messages, mentions must never be
            # honoured no matter what ends up in the text.
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def setup_hook(self) -> None:
        for extension in INITIAL_EXTENSIONS:
            await self.load_extension(extension)
            log.info("Loaded extension %s", extension)

        if self.config.dev_guild_id is not None:
            # Guild-scoped sync is instant — ideal for development.
            guild = discord.Object(id=self.config.dev_guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info("Synced commands to dev guild %s", self.config.dev_guild_id)
        else:
            await self.tree.sync()
            log.info("Synced global commands")

    async def on_ready(self) -> None:
        if self.user is not None:
            log.info("Logged in as %s (id=%s)", self.user, self.user.id)
