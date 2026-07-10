"""URL helpers shared across the bot.

This module holds pure, side-effect-free functions so they can be unit tested
without touching Discord or the network. It also hosts the embed-fixer
replacement table, which the future ``embedfix`` cog will consume (see
docstring on :func:`rewrite_embeds`).
"""

from __future__ import annotations

import re

# Maps a source domain to its embed-friendly mirror. Kept here (rather than in a
# cog) so the music bot and the future embed-fixer cog share one source of truth.
EMBED_REPLACEMENTS: dict[str, str] = {
    "twitter.com": "vxtwitter.com",
    "x.com": "fixupx.com",
    "reddit.com": "rxddit.com",
    "instagram.com": "ddinstagram.com",
    "tiktok.com": "vxtiktok.com",
}

# Domains that are already fixed; used to avoid rewriting an already-mirrored link.
_ALREADY_FIXED = set(EMBED_REPLACEMENTS.values())

_URL_RE = re.compile(
    r"https?://(?:www\.)?(?P<domain>[a-z0-9.-]+\.[a-z]{2,})",
    re.IGNORECASE,
)


def is_probable_url(text: str) -> bool:
    """Return True if ``text`` looks like an http(s) URL rather than a search term."""
    return bool(re.match(r"^\s*https?://", text, re.IGNORECASE))


def normalize_query(raw: str) -> str:
    """Trim a user-supplied /play argument and strip Discord's angle-bracket escaping.

    Users often paste ``<https://...>`` to suppress an embed; yt-dlp needs the
    bare URL.
    """
    query = raw.strip()
    if query.startswith("<") and query.endswith(">"):
        query = query[1:-1].strip()
    return query


def rewrite_embeds(text: str) -> str | None:
    """Rewrite social links to their embed-friendly mirrors.

    Pure function backing the future embed-fixer cog. Returns the rewritten
    string, or ``None`` if nothing changed (so a caller can cheaply decide
    whether to repost).
    """

    def _replace(match: re.Match[str]) -> str:
        domain = match.group("domain").lower()
        if domain in _ALREADY_FIXED:
            return match.group(0)
        replacement = EMBED_REPLACEMENTS.get(domain)
        if replacement is None:
            return match.group(0)
        return match.group(0).replace(match.group("domain"), replacement)

    rewritten = _URL_RE.sub(_replace, text)
    return rewritten if rewritten != text else None
