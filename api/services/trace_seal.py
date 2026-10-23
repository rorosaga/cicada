"""Sealing for activity traces (G218): AES-256-GCM, one nonce per record, bound to where the record belongs.

Every record — a timeline line, an OCR line, a screenshot file, the settings file — is sealed on its own with a fresh
96-bit random nonce, and its *associated data* names the record's place (``kind`` and day). A byte flipped anywhere
fails the tag; a line moved to another day's file, or a screenshot renamed to another id, fails it too. Opening never
returns a guess: it returns the plaintext or raises :class:`Tampered`.

Wire format of a sealed blob: ``b"v1" + nonce(12) + ciphertext+tag``. A text line is that blob in URL-safe base64.
"""
from __future__ import annotations

import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

VERSION = b"v1"
NONCE_BYTES = 12


class Tampered(ValueError):
    """A sealed record that does not open with this key and this place: changed, moved, or sealed by another key."""


def _aad(place: str) -> bytes:
    return b"cicada-traces/" + VERSION + b"/" + place.encode("utf-8")


def seal(key: bytes, plaintext: bytes, place: str) -> bytes:
    nonce = os.urandom(NONCE_BYTES)
    return VERSION + nonce + AESGCM(key).encrypt(nonce, plaintext, _aad(place))


def open_sealed(key: bytes, blob: bytes, place: str) -> bytes:
    if len(blob) < len(VERSION) + NONCE_BYTES + 16 or not blob.startswith(VERSION):
        raise Tampered("not a sealed trace record")
    nonce = blob[len(VERSION):len(VERSION) + NONCE_BYTES]
    try:
        return AESGCM(key).decrypt(nonce, blob[len(VERSION) + NONCE_BYTES:], _aad(place))
    except InvalidTag:
        raise Tampered("a sealed trace record failed its check") from None


def seal_line(key: bytes, plaintext: bytes, place: str) -> str:
    return base64.urlsafe_b64encode(seal(key, plaintext, place)).decode("ascii")


def open_line(key: bytes, line: str, place: str) -> bytes:
    try:
        blob = base64.urlsafe_b64decode(line.strip().encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        raise Tampered("a sealed trace line is not base64") from None
    return open_sealed(key, blob, place)
