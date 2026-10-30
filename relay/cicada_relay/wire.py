"""The frame the relay stores and forwards (G132 phase 3a).

A frame is ``MAGIC || u16 header length || header || body || Ed25519 signature``. The header is canonical JSON the
sender signs together with the body; the body is ciphertext the relay never opens (an ``epoch`` frame's body is the
home-signed membership statement and per-device sealed key wraps, public by design). The relay reads the header for
routing and bounds only: mailbox, epoch, sender, counter, kind, the sender's own creation time, the message and part
numbers, and the recipients.

The backend's ``api/services/sync_relay_crypto.py`` builds and opens the same frames; the two never import each other
(the relay ships alone in its container), and ``api/tests/test_sync_relay_e2e.py`` checks they agree byte for byte.
"""
from __future__ import annotations

import base64
import json
import re
import struct
from dataclasses import dataclass

from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey

MAGIC = b"CR1"
SIG_DOMAIN = b"cicada-relay-frame-v1\x00"
AUTH_DOMAIN = b"cicada-relay-auth-v1\x00"
SIG_LEN = 64
#: Every kind the relay accepts. ``tx`` and ``control`` live in the transactions reserve, ``delta`` is evictable,
#: ``status`` is latest-only per sender, ``stream`` is the one bootstrap at a time, ``epoch`` is the membership.
KINDS = frozenset({"tx", "control", "delta", "status", "stream", "epoch"})
#: Kinds only the bank's home may send: the replica's deltas, the bootstrap, and the membership itself.
HOME_ONLY = frozenset({"delta", "stream", "epoch"})
MAILBOX_RE = re.compile(r"^[A-Za-z0-9_-]{22}$")
KEY_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
HEADER_KEYS = frozenset({"v", "mb", "ep", "from", "ctr", "kind", "at", "msg", "part", "parts", "to"})


class WireError(ValueError):
    """A frame that is malformed, not canonical, or not signed by its sender. ``code`` is what the relay answers."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def b64d(text: str) -> bytes:
    if not isinstance(text, str):
        raise WireError("bad_encoding")
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (ValueError, TypeError) as exc:
        raise WireError("bad_encoding") from exc


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


@dataclass(frozen=True)
class Frame:
    raw: bytes
    header: dict
    header_bytes: bytes
    body: bytes
    sig: bytes

    @property
    def signed(self) -> bytes:
        return SIG_DOMAIN + self.raw[: len(self.raw) - SIG_LEN]

    @property
    def aad(self) -> bytes:
        """What the body's AEAD authenticates: everything before the body."""
        return self.raw[: len(MAGIC) + 2 + len(self.header_bytes)]

    @property
    def sender(self) -> str:
        return self.header["from"]

    @property
    def kind(self) -> str:
        return self.header["kind"]


def parse(raw: bytes) -> Frame:
    """Split and shape-check a frame. Never verifies the signature (``verify`` does, once the sender's key is known)."""
    if not isinstance(raw, (bytes, bytearray)) or len(raw) < len(MAGIC) + 2 + SIG_LEN or raw[:3] != MAGIC:
        raise WireError("bad_frame")
    raw = bytes(raw)
    (hlen,) = struct.unpack(">H", raw[3:5])
    if 5 + hlen + SIG_LEN > len(raw):
        raise WireError("bad_frame")
    header_bytes = raw[5 : 5 + hlen]
    try:
        header = json.loads(header_bytes)
    except ValueError as exc:
        raise WireError("bad_header") from exc
    if not isinstance(header, dict) or set(header) != HEADER_KEYS or canonical(header) != header_bytes:
        raise WireError("bad_header")
    ints = ("v", "ep", "ctr", "at", "msg", "part", "parts")
    if any(not isinstance(header[k], int) or isinstance(header[k], bool) or header[k] < 0 for k in ints):
        raise WireError("bad_header")
    if header["v"] != 1 or header["kind"] not in KINDS or not MAILBOX_RE.match(str(header["mb"])):
        raise WireError("bad_header")
    if not KEY_RE.match(str(header["from"])) or not (0 <= header["part"] < header["parts"] <= 4096):
        raise WireError("bad_header")
    if header["msg"] > header["ctr"] or header["ctr"] - header["msg"] != header["part"]:
        raise WireError("bad_header")
    to = header["to"]
    if not (to in ("*", "home") or (isinstance(to, list) and 0 < len(to) <= 64
                                    and all(isinstance(k, str) and KEY_RE.match(k) for k in to))):
        raise WireError("bad_header")
    return Frame(raw=raw, header=header, header_bytes=header_bytes, body=raw[5 + hlen : -SIG_LEN], sig=raw[-SIG_LEN:])


def verify(frame: Frame, sender_key_b64: str | None = None) -> None:
    """The sender's Ed25519 signature over the domain, the header and the body. Raises ``WireError('bad_signature')``."""
    key = sender_key_b64 or frame.sender
    try:
        VerifyKey(b64d(key)).verify(frame.signed, frame.sig)
    except (BadSignatureError, ValueError, TypeError) as exc:
        raise WireError("bad_signature") from exc


def auth_message(mailbox: str, nonce: bytes) -> bytes:
    return AUTH_DOMAIN + mailbox.encode("ascii") + b"\x00" + nonce


def verify_auth(device_b64: str, mailbox: str, nonce: bytes, sig_b64: str) -> bool:
    try:
        VerifyKey(b64d(device_b64)).verify(auth_message(mailbox, nonce), b64d(sig_b64))
        return True
    except (BadSignatureError, ValueError, TypeError, WireError):
        return False


def epoch_statement(frame: Frame) -> dict:
    """The membership statement an ``epoch`` frame carries, shape-checked. The frame's own signature (by the bank's
    current home) is what makes it binding; ``statement.home`` names the home from this epoch on (a hand-off when it
    differs from the signer)."""
    try:
        body = json.loads(frame.body)
        st = body["statement"]
    except (ValueError, KeyError, TypeError) as exc:
        raise WireError("bad_epoch") from exc
    if not isinstance(st, dict) or st.get("v") != 1 or st.get("mb") != frame.header["mb"]:
        raise WireError("bad_epoch")
    if st.get("epoch") != frame.header["ep"] or not KEY_RE.match(str(st.get("home", ""))):
        raise WireError("bad_epoch")
    devices = st.get("devices")
    if not isinstance(devices, list) or not 0 < len(devices) <= 64:
        raise WireError("bad_epoch")
    eds = []
    for d in devices:
        if not isinstance(d, dict) or not KEY_RE.match(str(d.get("ed", ""))) or not KEY_RE.match(str(d.get("x", ""))):
            raise WireError("bad_epoch")
        eds.append(d["ed"])
    if len(set(eds)) != len(eds) or st["home"] not in eds:
        raise WireError("bad_epoch")
    return st
