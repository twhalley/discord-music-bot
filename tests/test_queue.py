"""Unit tests for the pure per-guild queue logic."""

from __future__ import annotations

import pytest

from musicbot.audio.queue import GuildQueue, Track


def make_track(title: str = "song", duration: int | None = 200) -> Track:
    return Track(
        title=title,
        stream_url=f"https://cdn.example/{title}.opus",
        webpage_url=f"https://youtube.com/watch?v={title}",
        duration=duration,
        requested_by=42,
    )


def test_new_queue_is_empty() -> None:
    q = GuildQueue()
    assert q.is_empty()
    assert len(q) == 0
    assert q.current is None
    assert q.pop_next() is None


def test_add_returns_position_and_orders_fifo() -> None:
    q = GuildQueue()
    assert q.add(make_track("a")) == 1
    assert q.add(make_track("b")) == 2
    assert len(q) == 2

    first = q.pop_next()
    second = q.pop_next()
    assert first is not None and first.title == "a"
    assert second is not None and second.title == "b"


def test_pop_next_sets_current_then_clears_when_drained() -> None:
    q = GuildQueue()
    q.add(make_track("only"))
    played = q.pop_next()
    assert played is not None and q.current is played
    # Queue is now empty; the next pop clears current.
    assert q.pop_next() is None
    assert q.current is None


def test_upcoming_is_non_destructive_and_limited() -> None:
    q = GuildQueue()
    for i in range(5):
        q.add(make_track(f"t{i}"))
    peek = q.upcoming(limit=3)
    assert [t.title for t in peek] == ["t0", "t1", "t2"]
    assert len(q) == 5  # peeking did not consume


def test_upcoming_rejects_negative_limit() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        GuildQueue().upcoming(limit=-1)


def test_clear_keeps_current_but_reset_wipes_it() -> None:
    q = GuildQueue()
    q.add(make_track("a"))
    q.add(make_track("b"))
    q.pop_next()  # current = a, b pending

    q.clear()
    assert q.is_empty()
    assert q.current is not None and q.current.title == "a"

    q.reset()
    assert q.current is None


@pytest.mark.parametrize(
    ("duration", "expected"),
    [
        (None, "LIVE"),
        (0, "LIVE"),
        (5, "0:05"),
        (65, "1:05"),
        (3661, "1:01:01"),
    ],
)
def test_duration_label(duration: int | None, expected: str) -> None:
    assert make_track(duration=duration).duration_label == expected
