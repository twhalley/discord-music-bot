"""Slash-command music cog: join voice, stream YouTube/SoundCloud, manage a queue.

The heavy lifting (queueing, extraction) lives in ``musicbot.audio`` where it is
unit tested. This cog is the thin Discord-facing glue: it owns the voice client,
drives the per-guild player loop, and turns interactions into queue operations.
"""

from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from musicbot.audio import source
from musicbot.audio.queue import GuildQueue, Track

log = logging.getLogger(__name__)


class Music(commands.Cog):
    """Voice playback commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._queues: dict[int, GuildQueue] = {}

    def _queue_for(self, guild_id: int) -> GuildQueue:
        return self._queues.setdefault(guild_id, GuildQueue())

    # --- voice helpers -----------------------------------------------------

    @staticmethod
    def _voice_client(interaction: discord.Interaction) -> discord.VoiceClient | None:
        guild = interaction.guild
        if guild is None:
            return None
        client = guild.voice_client
        return client if isinstance(client, discord.VoiceClient) else None

    async def _ensure_voice(self, interaction: discord.Interaction) -> discord.VoiceClient | None:
        """Connect to (or move to) the caller's voice channel, returning the client."""
        user = interaction.user
        if not isinstance(user, discord.Member) or user.voice is None or user.voice.channel is None:
            await interaction.response.send_message(
                "You need to be in a voice channel first.", ephemeral=True
            )
            return None

        channel = user.voice.channel
        client = self._voice_client(interaction)
        if client is None:
            return await channel.connect(self_deaf=True)
        if client.channel != channel:
            await client.move_to(channel)
        return client

    # --- player loop -------------------------------------------------------

    def _play_next(self, guild_id: int, client: discord.VoiceClient) -> None:
        """Pop the next track and start streaming it; schedules itself on finish."""
        queue = self._queue_for(guild_id)
        track = queue.pop_next()
        if track is None:
            return

        audio = discord.FFmpegOpusAudio(
            track.stream_url,
            before_options=source.FFMPEG_BEFORE_OPTIONS,
            options=source.FFMPEG_OPTIONS,
        )

        def _after(error: Exception | None) -> None:
            if error is not None:
                log.error("Playback error in guild %s: %s", guild_id, error)
            # The after-callback runs off the event loop; hop back onto it.
            self.bot.loop.call_soon_threadsafe(self._play_next, guild_id, client)

        client.play(audio, after=_after)
        log.info("Now playing in guild %s: %s", guild_id, track.title)

    # --- commands ----------------------------------------------------------

    @app_commands.command(description="Play a YouTube/SoundCloud link or search term.")
    @app_commands.describe(query="A URL or search text")
    async def play(self, interaction: discord.Interaction, query: str) -> None:
        client = await self._ensure_voice(interaction)
        if client is None:
            return

        guild = interaction.guild
        if guild is None:  # unreachable once _ensure_voice succeeds, but narrows the type
            return

        await interaction.response.defer(thinking=True)
        try:
            # yt-dlp extraction is blocking network I/O; keep the event loop free.
            track = await asyncio.to_thread(source.resolve, query, interaction.user.id)
        except source.SourceError as exc:
            await interaction.followup.send(f"Couldn't play that: {exc}")
            return
        except Exception:
            log.exception("Unexpected error resolving query %r", query)
            await interaction.followup.send("Something went wrong resolving that link.")
            return

        queue = self._queue_for(guild.id)

        if client.is_playing() or client.is_paused():
            position = queue.add(track)
            await interaction.followup.send(
                f"Queued **{track.title}** (`{track.duration_label}`) — position {position}."
            )
        else:
            queue.add(track)
            self._play_next(guild.id, client)
            await interaction.followup.send(
                f"Now playing **{track.title}** (`{track.duration_label}`)."
            )

    @app_commands.command(description="Skip the current track.")
    async def skip(self, interaction: discord.Interaction) -> None:
        client = self._voice_client(interaction)
        if client is None or not (client.is_playing() or client.is_paused()):
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)
            return
        client.stop()  # triggers the after-callback, which plays the next track
        await interaction.response.send_message("Skipped.")

    @app_commands.command(description="Pause playback.")
    async def pause(self, interaction: discord.Interaction) -> None:
        client = self._voice_client(interaction)
        if client is None or not client.is_playing():
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)
            return
        client.pause()
        await interaction.response.send_message("Paused.")

    @app_commands.command(description="Resume playback.")
    async def resume(self, interaction: discord.Interaction) -> None:
        client = self._voice_client(interaction)
        if client is None or not client.is_paused():
            await interaction.response.send_message("Nothing is paused.", ephemeral=True)
            return
        client.resume()
        await interaction.response.send_message("Resumed.")

    @app_commands.command(description="Stop, clear the queue, and leave the channel.")
    async def stop(self, interaction: discord.Interaction) -> None:
        client = self._voice_client(interaction)
        if client is None:
            await interaction.response.send_message("I'm not in a voice channel.", ephemeral=True)
            return
        if interaction.guild is not None:
            self._queue_for(interaction.guild.id).reset()
        client.stop()
        await client.disconnect()
        await interaction.response.send_message("Stopped and left the channel.")

    @app_commands.command(name="nowplaying", description="Show the current track.")
    async def now_playing(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Guild only.", ephemeral=True)
            return
        current: Track | None = self._queue_for(interaction.guild.id).current
        client = self._voice_client(interaction)
        if current is None or client is None or not (client.is_playing() or client.is_paused()):
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"Now playing **{current.title}** (`{current.duration_label}`)\n{current.webpage_url}"
        )

    @app_commands.command(description="Show the upcoming queue.")
    async def queue(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Guild only.", ephemeral=True)
            return
        upcoming = self._queue_for(interaction.guild.id).upcoming(limit=10)
        if not upcoming:
            await interaction.response.send_message("The queue is empty.", ephemeral=True)
            return
        lines = [
            f"{i}. **{t.title}** (`{t.duration_label}`)" for i, t in enumerate(upcoming, start=1)
        ]
        await interaction.response.send_message("\n".join(lines))


async def setup(bot: commands.Bot) -> None:
    """discord.py extension entrypoint."""
    await bot.add_cog(Music(bot))
