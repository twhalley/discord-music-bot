"""Unit tests for query resolution, with yt-dlp mocked out."""

from __future__ import annotations

from pathlib import Path
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


@pytest.mark.parametrize(
    "stream_url",
    [
        "-i /etc/passwd",  # would be read by ffmpeg as an option, not a URL
        "file:///etc/passwd",
        "concat:/etc/passwd",
        "",
    ],
)
def test_build_track_rejects_non_http_stream_urls(stream_url: str) -> None:
    """The stream URL becomes an ffmpeg argument, so it is validated not trusted."""
    info = {"title": "x", "url": stream_url}
    with pytest.raises(source.SourceError):
        source.build_track(info, requested_by=1)


def test_build_track_rejects_absurdly_long_tracks() -> None:
    info = {"title": "x", "url": "https://cdn.example/a", "duration": source.MAX_TRACK_SECONDS + 1}
    with pytest.raises(source.SourceError, match="longer than"):
        source.build_track(info, requested_by=1)


def test_build_track_allows_live_streams_with_no_duration() -> None:
    """Live radio reports no duration; that must stay playable."""
    info = {"title": "x", "url": "https://cdn.example/a", "duration": None}
    assert source.build_track(info, requested_by=1).duration is None


def test_ytdl_options_bound_socket_time() -> None:
    """A stalled host must not hold a pool thread indefinitely."""
    assert source.YTDL_OPTIONS["socket_timeout"] > 0


class _RaisingExtractor:
    """Stands in for yt-dlp raising its own exception type."""

    def __init__(self, message: str) -> None:
        self.message = message

    def extract_info(self, url: str, download: bool = False) -> dict[str, Any] | None:
        raise RuntimeError(self.message)


@pytest.mark.parametrize(
    ("raw", "expected_fragment"),
    [
        ("ERROR: [youtube] abc: Sign in to confirm you're not a bot.", "searching for it by name"),
        ("ERROR: Private video. Sign in if you've been granted access", "private"),
        ("ERROR: Video unavailable", "unavailable"),
        ("ERROR: This video has been removed by the uploader", "removed by its uploader"),
        ("ERROR: Unable to download webpage: timed out", "Could not reach"),
        ("ERROR: something nobody has seen before", "Could not resolve"),
    ],
)
def test_yt_dlp_errors_become_actionable_messages(raw: str, expected_fragment: str) -> None:
    """Users get a usable sentence, not a stack trace and not yt-dlp internals."""
    assert expected_fragment.lower() in source._friendly_error(RuntimeError(raw)).lower()


def test_friendly_errors_never_leak_the_original_text() -> None:
    """The raw message can name internal paths and flags; it must not be echoed."""
    raw = "ERROR: /opt/venv/lib/secret/path failed --cookies-from-browser"
    assert "/opt/venv" not in source._friendly_error(RuntimeError(raw))


@pytest.mark.parametrize(
    "raw",
    [
        "ERROR: Unable to download webpage",  # contains "age" inside "webpage"
        "ERROR: unexpected message from server",  # inside "message"
        "ERROR: package resolution failed",  # inside "package"
    ],
)
def test_bare_word_needles_do_not_mislabel(raw: str) -> None:
    """Regression: a bare "age" needle matched webpage/message/package."""
    assert "age-restricted" not in source._friendly_error(RuntimeError(raw))


def test_no_cookies_configured_leaves_options_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cookies are optional: without them the bot behaves exactly as before."""
    monkeypatch.delenv(source.COOKIES_FILE_ENV, raising=False)
    assert source.cookies_file() == ""
    assert "cookiefile" not in source.ytdl_options()


def test_cookies_are_used_when_the_file_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    jar = tmp_path / "youtube.txt"
    jar.write_text("# Netscape HTTP Cookie File\n")
    monkeypatch.setenv(source.COOKIES_FILE_ENV, str(jar))
    assert source.cookies_file() == str(jar)
    assert source.ytdl_options()["cookiefile"] == str(jar)


def test_missing_cookies_file_is_ignored_not_fatal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An expired or not-yet-installed export must degrade, not break the bot."""
    monkeypatch.setenv(source.COOKIES_FILE_ENV, str(tmp_path / "nope.txt"))
    assert source.cookies_file() == ""
    assert "cookiefile" not in source.ytdl_options()


def test_blank_cookies_path_is_treated_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(source.COOKIES_FILE_ENV, "   ")
    assert source.cookies_file() == ""


def test_ytdl_options_does_not_mutate_the_shared_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Each call returns a copy, or cookie config would leak between runs."""
    jar = tmp_path / "c.txt"
    jar.write_text("# Netscape HTTP Cookie File\n")
    monkeypatch.setenv(source.COOKIES_FILE_ENV, str(jar))
    source.ytdl_options()
    assert "cookiefile" not in source.YTDL_OPTIONS
