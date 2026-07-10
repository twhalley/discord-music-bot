"""Resolve user queries into streamable tracks via yt-dlp.

Extraction is split into small, injectable pieces so the pure parsing logic
(:func:`build_track`) is unit tested without the network, and the yt-dlp call
(:func:`extract_info`) is mocked in tests.

Audio is *streamed*, never downloaded to disk: yt-dlp hands us a direct media
URL and ffmpeg reads it over the network. This keeps the container filesystem
read-only and avoids buffering whole files.
"""

from __future__ import annotations

from typing import Any, Protocol, cast

from musicbot.audio.queue import Track
from musicbot.util.urls import is_probable_url, normalize_query

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
}

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
    """Normalize input and turn plain text into a YouTube search."""
    query = normalize_query(raw)
    if not query:
        raise SourceError("Empty query.")
    if is_probable_url(query):
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

    return Track(
        title=info.get("title") or "Unknown title",
        stream_url=stream_url,
        webpage_url=info.get("webpage_url") or info.get("original_url") or stream_url,
        duration=info.get("duration"),
        requested_by=requested_by,
    )


def extract_info(query: str, *, extractor: _Extractor | None = None) -> dict[str, Any]:
    """Run yt-dlp for ``query`` and return its info dict.

    Args:
        query: A URL or ``ytsearch``-style query.
        extractor: Injected in tests. Defaults to a real ``yt_dlp.YoutubeDL``.
    """
    if extractor is None:
        # Imported lazily so unit tests never need yt-dlp installed.
        from yt_dlp import YoutubeDL

        with YoutubeDL(YTDL_OPTIONS) as ydl:
            info = ydl.extract_info(query, download=False)
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
