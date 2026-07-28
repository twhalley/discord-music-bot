"""Unit tests for URL helpers and the embed-fixer rewrite table."""

from __future__ import annotations

import pytest

from musicbot.util.urls import (
    is_allowed_host,
    is_probable_url,
    normalize_query,
    rewrite_embeds,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("https://youtube.com/watch?v=x", True),
        ("http://soundcloud.com/artist/track", True),
        ("  https://x.com/a ", True),
        ("never gonna give you up", False),
        ("ftp://example.com/file", False),
    ],
)
def test_is_probable_url(text: str, expected: bool) -> None:
    assert is_probable_url(text) is expected


def test_normalize_query_strips_angle_brackets_and_whitespace() -> None:
    assert normalize_query("  <https://x.com/a>  ") == "https://x.com/a"
    assert normalize_query("plain text") == "plain text"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("look https://twitter.com/u/status/1", "look https://vxtwitter.com/u/status/1"),
        ("https://x.com/u/status/2", "https://fixupx.com/u/status/2"),
        ("https://www.reddit.com/r/x/comments/1", "https://www.rxddit.com/r/x/comments/1"),
    ],
)
def test_rewrite_embeds_replaces_known_domains(text: str, expected: str) -> None:
    assert rewrite_embeds(text) == expected


def test_rewrite_embeds_returns_none_when_nothing_matches() -> None:
    assert rewrite_embeds("just a https://example.com link") is None
    assert rewrite_embeds("no links at all") is None


def test_rewrite_embeds_skips_already_fixed_links() -> None:
    # An already-mirrored link must not be double-rewritten.
    assert rewrite_embeds("https://vxtwitter.com/u/status/1") is None


def test_rewrite_embeds_handles_multiple_links() -> None:
    result = rewrite_embeds("https://x.com/a and https://tiktok.com/@u/video/1")
    assert result == "https://fixupx.com/a and https://vxtiktok.com/@u/video/1"


@pytest.mark.parametrize(
    "url",
    [
        "https://youtube.com/watch?v=x",
        "https://www.youtube.com/watch?v=x",
        "https://m.youtube.com/watch?v=x",
        "https://music.youtube.com/watch?v=x",
        "https://youtu.be/x",
        "http://soundcloud.com/artist/track",
        "https://on.soundcloud.com/abc",
        "https://YouTube.COM/watch?v=x",  # host comparison is case-insensitive
        "https://youtube.com./watch?v=x",  # trailing DNS root dot
    ],
)
def test_is_allowed_host_accepts_supported_services(url: str) -> None:
    assert is_allowed_host(url) is True


@pytest.mark.parametrize(
    "url",
    [
        # Cloud instance metadata — the SSRF target this guard exists for.
        "http://169.254.169.254/opc/v2/instance/",
        "http://127.0.0.1:8080/admin",
        "http://localhost/",
        "http://[::1]/",
        "http://10.0.0.5/internal",
        # Userinfo trick: the real host is the metadata service, not YouTube.
        "https://youtube.com@169.254.169.254/",
        "https://youtube.com:pass@169.254.169.254/",
        # Suffix confusion: an attacker-controlled parent domain.
        "https://youtube.com.evil.test/",
        "https://notyoutube.com/",
        "https://evil.test/?x=youtube.com",
        # Non-http schemes never reach yt-dlp as URLs.
        "file:///etc/passwd",
        "ftp://youtube.com/x",
        "gopher://youtube.com/",
        # Malformed authority.
        "https://[not-an-ipv6/",
        "https:///nohost",
        "",
    ],
)
def test_is_allowed_host_rejects_everything_else(url: str) -> None:
    assert is_allowed_host(url) is False
