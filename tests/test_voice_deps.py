"""Guards on the voice dependency set.

These exist because a missing voice dependency is invisible until someone runs
a command: the bot starts, authenticates and syncs its commands normally, and
only fails inside ``channel.connect()``. That shipped to production once. Unit
tests are the cheapest place to catch it.
"""

from __future__ import annotations

import nacl.utils
from nacl.secret import Aead, SecretBox


def test_voice_backends_are_both_present() -> None:
    """discord.py 2.7 needs davey (DAVE protocol) as well as PyNaCl.

    ``has_dave`` being False is exactly the production failure:
    "RuntimeError: davey library needed in order to use voice".
    """
    import discord.voice_client as voice_client

    assert voice_client.has_dave is True, "davey missing — /play will fail at connect()"
    assert voice_client.has_nacl is True, "PyNaCl missing — voice cannot be encrypted"


def test_pynacl_exposes_the_api_discord_uses() -> None:
    """PyNaCl is pinned past the ``<1.6`` bound discord.py's voice extra declares.

    That bound cannot be honoured while ``pip-audit`` is clean: 1.5.0 carries
    PYSEC-2026-3002, fixed in 1.6.2. The bound is stale rather than real for
    the slice of the API discord.py touches — ``SecretBox``, ``Aead`` and
    ``utils.random`` — so that slice is asserted here. If a future discord.py
    reaches further into PyNaCl, this is where it should fail.
    """
    assert SecretBox.NONCE_SIZE == 24
    assert Aead.NONCE_SIZE == 24
    assert len(nacl.utils.random(8)) == 8


def test_aead_roundtrip_works() -> None:
    """Exercise the primitive the voice path actually encrypts audio with."""
    box = Aead(nacl.utils.random(32))
    nonce = nacl.utils.random(Aead.NONCE_SIZE)
    ciphertext = box.encrypt(b"audio frame", b"aad", nonce)
    assert box.decrypt(ciphertext, b"aad") == b"audio frame"
