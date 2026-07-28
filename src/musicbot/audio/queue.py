"""Per-guild play queue.

Deliberately pure and dependency-free (no Discord objects) so the queueing
logic is fully unit tested. The cog layer owns the voice client and feeds
:class:`Track` values through here.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

# Any guild member can call /play, so an unbounded queue is a memory-growth
# lever for anyone in the server. The cap is generous for real use and turns
# spam into a polite refusal instead of a slow leak.
MAX_QUEUE_SIZE = 100


class QueueFullError(RuntimeError):
    """Raised when a track is added to a queue that has reached its cap."""


@dataclass(frozen=True, slots=True)
class Track:
    """An immutable, resolved audio track ready to be streamed."""

    title: str
    stream_url: str
    webpage_url: str
    duration: int | None
    requested_by: int  # Discord user id, for "requested by" display.

    @property
    def duration_label(self) -> str:
        """Human-readable ``M:SS`` (or ``H:MM:SS``) label, or ``LIVE`` if unknown."""
        if self.duration is None or self.duration <= 0:
            return "LIVE"
        hours, remainder = divmod(self.duration, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"


class GuildQueue:
    """A FIFO queue of tracks plus the currently-playing track for one guild."""

    def __init__(self, max_size: int = MAX_QUEUE_SIZE) -> None:
        if max_size < 1:
            raise ValueError("max_size must be at least 1")
        self._items: deque[Track] = deque()
        self._current: Track | None = None
        self._max_size = max_size

    @property
    def max_size(self) -> int:
        """The most tracks this queue will hold, excluding the current one."""
        return self._max_size

    def is_full(self) -> bool:
        """True when no further tracks can be added."""
        return len(self._items) >= self._max_size

    @property
    def current(self) -> Track | None:
        """The track currently playing, if any."""
        return self._current

    def __len__(self) -> int:
        return len(self._items)

    def is_empty(self) -> bool:
        """True when nothing is queued (ignores the currently-playing track)."""
        return not self._items

    def add(self, track: Track) -> int:
        """Append a track; return its 1-based position in the pending queue.

        Raises:
            QueueFullError: if the queue already holds ``max_size`` tracks.
        """
        if self.is_full():
            raise QueueFullError(f"Queue is full ({self._max_size} tracks).")
        self._items.append(track)
        return len(self._items)

    def pop_next(self) -> Track | None:
        """Advance to the next track, set it as current, and return it.

        Returns ``None`` and clears the current track when the queue is empty.
        """
        self._current = self._items.popleft() if self._items else None
        return self._current

    def upcoming(self, limit: int = 10) -> list[Track]:
        """Return up to ``limit`` pending tracks without consuming them."""
        if limit < 0:
            raise ValueError("limit must be non-negative")
        return list(self._items)[:limit]

    def clear(self) -> None:
        """Drop all pending tracks (does not stop the current one)."""
        self._items.clear()

    def reset(self) -> None:
        """Clear pending tracks and forget the current one."""
        self._items.clear()
        self._current = None
