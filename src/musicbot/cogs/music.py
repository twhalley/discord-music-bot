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
from musicbot.audio.queue import GuildQueue, QueueFullError, Track

log = logging.getLogger(__name__)

# yt-dlp extraction is blocking network I/O run on a worker thread. Without a
# bound, every concurrent /play across every guild spawns another thread, so a
# handful of users can exhaust the thread pool. Resolutions beyond this many
# simply wait their turn.
MAX_CONCURRENT_RESOLUTIONS = 4

# Per-user command budget. The semaphore above bounds work in flight; this
# bounds how fast one member can ask for it, so a single user cannot monopolise
# the queue or the extraction pool by holding down a macro.
PLAY_COOLDOWN_RATE = 5
PLAY_COOLDOWN_PER = 60.0
CONTROL_COOLDOWN_RATE = 10
CONTROL_COOLDOWN_PER = 60.0

# How long to wait after the queue drains before leaving the channel. Not zero:
# a /play issued just as the last track ends spends a few seconds in yt-dlp, and
# disconnecting underneath it would drop the track the user just asked for. The
# state is re-checked after the wait, so queueing anything cancels the departure.
IDLE_DISCONNECT_SECONDS = 20.0


def _display(title: str) -> str:
    """Escape a track title for safe inclusion in a Discord message.

    Titles come from yt-dlp and are chosen by whoever uploaded the media, so
    they are untrusted text. `AllowedMentions.none()` on the client already
    stops mentions resolving; this additionally stops markdown in a title from
    forging formatting or fake links in the bot's own output.
    """
    return discord.utils.escape_markdown(title)


def _for_log(value: str, limit: int = 120) -> str:
    """Flatten untrusted text for a single log line.

    Titles and queries are attacker-influenced. Newlines in a log record let
    someone forge additional entries, so they are stripped and the result is
    truncated.
    """
    return value.replace("\n", " ").replace("\r", " ")[:limit]


class Music(commands.Cog):
    """Voice playback commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._queues: dict[int, GuildQueue] = {}
        self._resolve_limit = asyncio.Semaphore(MAX_CONCURRENT_RESOLUTIONS)

    def _queue_for(self, guild_id: int) -> GuildQueue:
        return self._queues.setdefault(guild_id, GuildQueue())

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        """Answer the interaction instead of leaving it to time out.

        An unhandled error shows the user "the application did not respond",
        which is indistinguishable from the bot being down. Rate limiting is
        expected control flow, so it gets a plain reply; anything else is
        logged and answered generically so internals are not disclosed.
        """
        if isinstance(error, app_commands.CommandOnCooldown):
            message = f"Slow down — try that again in {error.retry_after:.0f}s."
        else:
            log.exception("Unhandled application command error", exc_info=error)
            message = "Something went wrong running that command."

        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        """Disconnect once no humans remain in the channel.

        Otherwise the bot holds a voice connection, an ffmpeg process and a
        queue indefinitely after the last listener leaves — a resource leak,
        and a way to keep it pinned in a channel nobody is using.
        """
        if member.bot:
            return

        client = member.guild.voice_client
        if not isinstance(client, discord.VoiceClient) or not client.is_connected():
            return

        channel = client.channel
        if channel is None or any(not m.bot for m in channel.members):
            return

        log.info("Last listener left guild %s; disconnecting", member.guild.id)
        self._queue_for(member.guild.id).reset()
        client.stop()
        await client.disconnect()

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
        # The client can go away between a track finishing and this running --
        # /stop, a kick from the channel, or a gateway drop. Calling play() on a
        # disconnected client raises inside the event loop, so check first.
        if not client.is_connected():
            log.info("Voice client gone in guild %s; stopping playback loop", guild_id)
            self._queue_for(guild_id).reset()
            return

        queue = self._queue_for(guild_id)
        track = queue.pop_next()
        if track is None:
            # Nothing left to play: leave rather than sit idle in the channel.
            self.bot.loop.create_task(self._leave_when_idle(guild_id, client))
            return

        try:
            audio = discord.FFmpegOpusAudio(
                track.stream_url,
                before_options=source.FFMPEG_BEFORE_OPTIONS,
                options=source.FFMPEG_OPTIONS,
            )
        except Exception:
            # A spawn failure must not kill the loop -- skip to the next track.
            log.exception("Could not start ffmpeg in guild %s", guild_id)
            self.bot.loop.call_soon_threadsafe(self._play_next, guild_id, client)
            return

        def _after(error: Exception | None) -> None:
            if error is not None:
                log.error("Playback error in guild %s: %s", guild_id, error)
            # The after-callback runs off the event loop; hop back onto it.
            self.bot.loop.call_soon_threadsafe(self._play_next, guild_id, client)

        client.play(audio, after=_after)
        log.info("Now playing in guild %s: %s", guild_id, _for_log(track.title))

    async def _leave_when_idle(self, guild_id: int, client: discord.VoiceClient) -> None:
        """Disconnect once the queue has drained and stayed drained.

        Called when playback finds nothing left to play. The wait exists so a
        `/play` issued as the previous track ends -- which spends a few seconds
        in yt-dlp before anything is queued -- is not cut off mid-resolution;
        the state is re-checked afterwards, so queueing anything cancels this.
        """
        await asyncio.sleep(IDLE_DISCONNECT_SECONDS)

        if not client.is_connected():
            return
        if client.is_playing() or client.is_paused():
            return
        if not self._queue_for(guild_id).is_empty():
            return

        log.info("Queue empty in guild %s; leaving the channel", guild_id)
        self._queue_for(guild_id).reset()
        await client.disconnect()

    # --- commands ----------------------------------------------------------

    @app_commands.command(description="Play a YouTube/SoundCloud link or search term.")
    @app_commands.describe(query="A URL or search text")
    @app_commands.checks.cooldown(PLAY_COOLDOWN_RATE, PLAY_COOLDOWN_PER)
    async def play(self, interaction: discord.Interaction, query: str) -> None:
        client = await self._ensure_voice(interaction)
        if client is None:
            return

        guild = interaction.guild
        if guild is None:  # unreachable once _ensure_voice succeeds, but narrows the type
            return

        queue = self._queue_for(guild.id)
        # Check before doing the expensive extraction, so a full queue costs a
        # rejected message rather than a wasted network round-trip.
        if queue.is_full():
            await interaction.response.send_message(
                f"The queue is full ({queue.max_size} tracks). Try again once it drains.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True)
        try:
            # yt-dlp extraction is blocking network I/O; keep the event loop
            # free, and cap how many can be in flight at once.
            async with self._resolve_limit:
                track = await asyncio.to_thread(source.resolve, query, interaction.user.id)
        except source.SourceError as exc:
            await interaction.followup.send(f"Couldn't play that: {exc}")
            return
        except Exception:
            log.exception("Unexpected error resolving query %r", query)
            await interaction.followup.send("Something went wrong resolving that link.")
            return

        try:
            position = queue.add(track)
        except QueueFullError:
            # The queue can fill while we were resolving.
            await interaction.followup.send(
                f"The queue filled up while loading that ({queue.max_size} tracks)."
            )
            return

        if client.is_playing() or client.is_paused():
            await interaction.followup.send(
                f"Queued **{_display(track.title)}** (`{track.duration_label}`)"
                f" — position {position}."
            )
        else:
            self._play_next(guild.id, client)
            await interaction.followup.send(
                f"Now playing **{_display(track.title)}** (`{track.duration_label}`)."
            )

    @app_commands.command(description="Skip the current track.")
    @app_commands.checks.cooldown(CONTROL_COOLDOWN_RATE, CONTROL_COOLDOWN_PER)
    async def skip(self, interaction: discord.Interaction) -> None:
        client = self._voice_client(interaction)
        if client is None or not (client.is_playing() or client.is_paused()):
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)
            return
        client.stop()  # triggers the after-callback, which plays the next track
        await interaction.response.send_message("Skipped.")

    @app_commands.command(description="Pause playback.")
    @app_commands.checks.cooldown(CONTROL_COOLDOWN_RATE, CONTROL_COOLDOWN_PER)
    async def pause(self, interaction: discord.Interaction) -> None:
        client = self._voice_client(interaction)
        if client is None or not client.is_playing():
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)
            return
        client.pause()
        await interaction.response.send_message("Paused.")

    @app_commands.command(description="Resume playback.")
    @app_commands.checks.cooldown(CONTROL_COOLDOWN_RATE, CONTROL_COOLDOWN_PER)
    async def resume(self, interaction: discord.Interaction) -> None:
        client = self._voice_client(interaction)
        if client is None or not client.is_paused():
            await interaction.response.send_message("Nothing is paused.", ephemeral=True)
            return
        client.resume()
        await interaction.response.send_message("Resumed.")

    @app_commands.command(description="Stop, clear the queue, and leave the channel.")
    @app_commands.checks.cooldown(CONTROL_COOLDOWN_RATE, CONTROL_COOLDOWN_PER)
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
    @app_commands.checks.cooldown(CONTROL_COOLDOWN_RATE, CONTROL_COOLDOWN_PER)
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
            f"Now playing **{_display(current.title)}** (`{current.duration_label}`)\n"
            f"<{current.webpage_url}>"
        )

    @app_commands.command(description="Show the upcoming queue.")
    @app_commands.checks.cooldown(CONTROL_COOLDOWN_RATE, CONTROL_COOLDOWN_PER)
    async def queue(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Guild only.", ephemeral=True)
            return
        upcoming = self._queue_for(interaction.guild.id).upcoming(limit=10)
        if not upcoming:
            await interaction.response.send_message("The queue is empty.", ephemeral=True)
            return
        lines = [
            f"{i}. **{_display(t.title)}** (`{t.duration_label}`)"
            for i, t in enumerate(upcoming, start=1)
        ]
        await interaction.response.send_message("\n".join(lines))


async def setup(bot: commands.Bot) -> None:
    """discord.py extension entrypoint."""
    await bot.add_cog(Music(bot))
