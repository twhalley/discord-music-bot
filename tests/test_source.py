"""Unit tests for query resolution, with yt-dlp mocked out."""

from __future__ import annotations

from typing import Any

import pytest

from musicbot.audio import source
from musicbot.audio.queue import Track


class FakeExtractor:
    """Stands in for yt_dlp.YoutubeDL; records the query it was asked to resolve."""

    def __init__(self, result: dict[str, Any] | None) -> None:
        self.result = result
        self.seen_query: str | None = None

    def extract_info(self, url: str, download: bool = False) -> dict[str, Any] | None:
        self.seen_query = url
        return self.result


VIDEO_INFO: dict[str, Any] = {
    "title": "Test Song",
    "url": "https://cdn.example/audio.webm",
    "webpage_url": "https://youtube.com/watch?v=abc",
    "duration": 213,
}


def test_build_track_from_single_video() -> None:
    track = source.build_track(VIDEO_INFO, requested_by=7)
    assert isinstance(track, Track)
    assert track.title == "Test Song"
    assert track.stream_url == "https://cdn.example/audio.webm"
    assert track.duration == 213
    assert track.requested_by == 7


def test_build_track_uses_first_entry_of_search_result() -> None:
    info = {"entries": [None, VIDEO_INFO]}  # yt-dlp can emit leading None entries
    track = source.build_track(info, requested_by=1)
    assert track.title == "Test Song"


def test_build_track_raises_on_empty_entries() -> None:
    with pytest.raises(source.SourceError, match="No results"):
        source.build_track({"entries": []}, requested_by=1)


def test_build_track_raises_without_stream_url() -> None:
    with pytest.raises(source.SourceError, match="no streamable URL"):
        source.build_track({"title": "x"}, requested_by=1)


def test_resolve_passes_url_through_verbatim() -> None:
    fake = FakeExtractor(VIDEO_INFO)
    track = source.resolve("https://soundcloud.com/a/b", requested_by=9, extractor=fake)
    assert fake.seen_query == "https://soundcloud.com/a/b"
    assert track.requested_by == 9


def test_resolve_wraps_plain_text_as_search() -> None:
    fake = FakeExtractor(VIDEO_INFO)
    source.resolve("never gonna give you up", requested_by=1, extractor=fake)
    assert fake.seen_query == "ytsearch1:never gonna give you up"


def test_resolve_strips_angle_brackets_before_search_detection() -> None:
    fake = FakeExtractor(VIDEO_INFO)
    source.resolve("<https://youtube.com/watch?v=a>", requested_by=1, extractor=fake)
    assert fake.seen_query == "https://youtube.com/watch?v=a"


def test_resolve_raises_on_empty_query() -> None:
    with pytest.raises(source.SourceError, match="Empty"):
        source.resolve("   ", requested_by=1, extractor=FakeExtractor(VIDEO_INFO))


def test_extract_info_raises_when_extractor_returns_none() -> None:
    with pytest.raises(source.SourceError, match="No results"):
        source.extract_info("ytsearch1:nothing", extractor=FakeExtractor(None))


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/opc/v2/instance/",
        "https://youtube.com@169.254.169.254/",
        "http://127.0.0.1/admin",
        "https://youtube.com.evil.test/",
    ],
)
def test_resolve_refuses_disallowed_urls_without_calling_extractor(url: str) -> None:
    """The SSRF guard must reject before yt-dlp is ever invoked."""
    fake = FakeExtractor(VIDEO_INFO)
    with pytest.raises(source.SourceError, match="Only YouTube and SoundCloud"):
        source.resolve(url, requested_by=1, extractor=fake)
    assert fake.seen_query is None


def test_resolve_accepts_allowed_url_hosts() -> None:
    fake = FakeExtractor(VIDEO_INFO)
    source.resolve("https://m.youtube.com/watch?v=abc", requested_by=1, extractor=fake)
    assert fake.seen_query == "https://m.youtube.com/watch?v=abc"


def test_hostile_non_url_text_is_searched_not_fetched() -> None:
    """Without an http(s) prefix the input is inert search text."""
    fake = FakeExtractor(VIDEO_INFO)
    source.resolve("file:///etc/passwd", requested_by=1, extractor=fake)
    assert fake.seen_query == "ytsearch1:file:///etc/passwd"
