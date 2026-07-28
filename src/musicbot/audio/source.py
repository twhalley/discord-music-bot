"""Resolve user queries into streamable tracks via yt-dlp.

Extraction is split into small, injectable pieces so the pure parsing logic
(:func:`build_track`) is unit tested without the network, and the yt-dlp call
(:func:`extract_info`) is mocked in tests.

Audio is *streamed*, never downloaded to disk: yt-dlp hands us a direct media
URL and ffmpeg reads it over the network. This keeps the container filesystem
read-only and avoids buffering whole files.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Protocol, cast

from musicbot.audio.queue import Track
from musicbot.util.urls import host_of, is_allowed_host, is_probable_url, normalize_query

log = logging.getLogger(__name__)

# bestaudio, and we tell yt-dlp not to touch the filesystem.
YTDL_OPTIONS: dict[str, Any] = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",  # noqa: S104 - yt-dlp binds outbound to IPv4
    "skip_download": True,
    "cachedir": False,
    # Extraction runs on a worker thread from a bounded pool. Without a timeout
    # a host that accepts the connection then stalls would hold a thread
    # indefinitely, and enough of those starve the pool.
    "socket_timeout": 15,
    # Never let a redirect chain wander; each hop is re-checked below anyway.
    "extractor_retries": 1,
}

# Base URL of a proof-of-origin token provider, or empty for none.
#
# YouTube refuses some videos from datacenter IPs with "Sign in to confirm
# you're not a bot". Satisfying that needs a PO token, which is produced by
# running YouTube's BotGuard challenge in a JS runtime -- yt-dlp cannot do that
# itself, so it delegates to a provider process.
#
# Read from the environment rather than hard-coded, and *optional by design*:
# unset, the bot behaves exactly as it did before -- some videos refuse to play
# and everything else works. That means a provider outage degrades playback
# instead of taking the bot down with it.
POT_PROVIDER_ENV = "POT_PROVIDER_BASE_URL"


def extractor_args() -> dict[str, dict[str, list[str]]]:
    """Return yt-dlp extractor args for the PO token provider, if configured."""
    base_url = os.environ.get(POT_PROVIDER_ENV, "").strip()
    if not base_url:
        return {}
    return {"youtubepot-bgutilhttp": {"base_url": [base_url]}}


def ytdl_options() -> dict[str, Any]:
    """Return the yt-dlp options for this run, including any provider wiring."""
    options = dict(YTDL_OPTIONS)
    args = extractor_args()
    if args:
        options["extractor_args"] = args
    return options


# Streams whose length we cannot bound are allowed (live radio reports no
# duration), but a single absurdly long VOD would otherwise occupy the player
# for the better part of a day.
MAX_TRACK_SECONDS = 4 * 60 * 60

# ffmpeg options: reconnect on transient network drops, and stream only audio.
FFMPEG_BEFORE_OPTIONS = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin"
FFMPEG_OPTIONS = "-vn"


class SourceError(RuntimeError):
    """Raised when a query cannot be resolved to a playable track."""


class _Extractor(Protocol):
    """Structural type for the subset of yt-dlp we use (keeps tests dependency-free)."""

    def extract_info(self, url: str, download: bool = ...) -> dict[str, Any] | None:
        """Resolve ``url`` to a yt-dlp info dict (or ``None`` if nothing matched)."""


def _build_query(raw: str) -> str:
    """Normalize input and turn plain text into a YouTube search.

    URLs are checked against :data:`musicbot.util.urls.ALLOWED_HOSTS` before
    they can reach yt-dlp. Anything that is not a URL becomes a YouTube search
    term, which is inert — a hostile string like ``file:///etc/passwd`` has no
    ``http(s)://`` prefix, so it is searched for rather than fetched.
    """
    query = normalize_query(raw)
    if not query:
        raise SourceError("Empty query.")
    if is_probable_url(query):
        if not is_allowed_host(query):
            # Log the host, never the whole URL: enough to tell a legitimate
            # share domain we have missed from someone probing the guard, and
            # not enough to record what people are listening to.
            log.info("Refused URL from disallowed host %r", host_of(query) or "<unparsable>")
            raise SourceError(
                "Only YouTube and SoundCloud links are supported. Try searching by name instead."
            )
        return query
    return f"ytsearch1:{query}"


def build_track(info: dict[str, Any], requested_by: int) -> Track:
    """Convert a yt-dlp info dict into a :class:`Track`.

    Pure and fully unit tested. Accepts either a single-video info dict or a
    playlist/search result dict (in which case the first entry is used).
    """
    if "entries" in info:
        entries = [entry for entry in (info["entries"] or []) if entry]
        if not entries:
            raise SourceError("No results found.")
        info = entries[0]

    stream_url = info.get("url")
    if not stream_url:
        raise SourceError("yt-dlp returned no streamable URL for this query.")

    # The stream URL is handed to ffmpeg as a command-line argument. yt-dlp
    # normally returns an https media URL, but the value ultimately derives
    # from a remote response, so it is validated rather than trusted: a value
    # beginning with "-" would be parsed by ffmpeg as an option, and a non-http
    # scheme (file://, concat:, ...) would make it read something local.
    if not is_probable_url(stream_url):
        raise SourceError("yt-dlp returned a stream URL that is not http(s).")

    duration = info.get("duration")
    if isinstance(duration, int | float) and duration > MAX_TRACK_SECONDS:
        raise SourceError(
            f"That track is longer than {MAX_TRACK_SECONDS // 3600} hours. Pick something shorter."
        )

    return Track(
        title=info.get("title") or "Unknown title",
        stream_url=stream_url,
        webpage_url=info.get("webpage_url") or info.get("original_url") or stream_url,
        duration=duration,
        requested_by=requested_by,
    )


# yt-dlp failure text is not shown to users verbatim -- it leaks internals and
# reads like a stack trace. Recognised cases become a short, actionable message
# instead; anything unmatched stays generic.
_ERROR_HINTS: tuple[tuple[str, str], ...] = (
    (
        "sign in to confirm",
        "YouTube is asking this server to sign in before it will serve that "
        "video. Try searching for it by name instead — another upload usually "
        "plays fine.",
    ),
    ("private video", "That video is private."),
    ("video unavailable", "That video is unavailable."),
    ("removed by the uploader", "That video was removed by its uploader."),
    # Match full phrases, never bare words: "age" alone also matches "webpage",
    # "message" and "package", which silently mislabels unrelated failures.
    ("age-restricted", "That video is age-restricted and cannot be played."),
    ("age restricted", "That video is age-restricted and cannot be played."),
    ("confirm your age", "That video is age-restricted and cannot be played."),
    ("copyright", "That video is blocked on copyright grounds."),
    ("not available in your country", "That video is not available from this server's region."),
    ("unable to download webpage", "Could not reach that site. It may be down."),
)


def _friendly_error(exc: Exception) -> str:
    """Map a yt-dlp failure onto a message worth showing a user."""
    text = str(exc).lower()
    for needle, message in _ERROR_HINTS:
        if needle in text:
            return message
    return "Could not resolve that link."


def extract_info(query: str, *, extractor: _Extractor | None = None) -> dict[str, Any]:
    """Run yt-dlp for ``query`` and return its info dict.

    Args:
        query: A URL or ``ytsearch``-style query.
        extractor: Injected in tests. Defaults to a real ``yt_dlp.YoutubeDL``.

    Raises:
        SourceError: if extraction fails. yt-dlp's own exception text is
            translated rather than surfaced, so users get an actionable
            sentence and internals stay out of Discord.
    """
    if extractor is None:
        # Imported lazily so unit tests never need yt-dlp installed.
        from yt_dlp import YoutubeDL

        try:
            with YoutubeDL(ytdl_options()) as ydl:
                info = ydl.extract_info(query, download=False)
        except SourceError:
            raise
        except Exception as exc:
            raise SourceError(_friendly_error(exc)) from exc
    else:
        info = extractor.extract_info(query, download=False)

    if info is None:
        raise SourceError("No results found.")
    # yt-dlp is untyped, so `info` is Any here; we validated it is non-None.
    return cast("dict[str, Any]", info)


def resolve(raw: str, requested_by: int, *, extractor: _Extractor | None = None) -> Track:
    """Resolve raw user input into a playable :class:`Track`."""
    query = _build_query(raw)
    info = extract_info(query, extractor=extractor)
    return build_track(info, requested_by)
