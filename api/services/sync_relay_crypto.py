"""The relay's end-to-end layer, shared by the home and every device (G132 phase 3a, ruling 51c, gate g3).

Nothing in a normal install imports this: it is reached only by the relay client and the pairing module, which phase
3b wires into the follower and the outbox. Unset or off, nothing changes.

**Construction** (``reports/g132-relay-research.md`` §2, "sender keys, simplified"):

- Every device holds an Ed25519 key (signs its frames, authenticates to the relay) and an X25519 key (receives key
  wraps). The phone keeps both in the Keychain and binds them to its Secure-Enclave key at pairing (3b).
- The home holds the bank's **epoch key** ``K_e`` (32 random bytes) and the membership. Every membership change (a
  device paired, a device revoked, the home handed off) starts a new epoch: the home draws ``K_{e+1}`` and posts one
  ``epoch`` frame carrying the statement ``{v, mb, epoch, home, devices:[{ed, x}], at}`` and, per device, a
  ``crypto_box_seal`` of the epoch keys that device may hold (from the epoch it joined, within the retention window).
  A device accepts an epoch frame only when it is signed by the home it pinned at pairing; a statement whose ``home``
  differs is the hand-off, and the new home's key is pinned from then on.
- Every other frame's body is ``nonce(24) || XChaCha20-Poly1305(K_e, pad(part), aad = magic || header)``, and the
  whole frame is signed by its sender's Ed25519 key. The group key alone would let any member forge as another; the
  signature stops that, and stops the relay outright.
- Plaintext is padded to size buckets (4 KiB, doubling to 512 KiB, then the largest part) so the relay learns a
  bucket, not a length. A payload larger than one part is split into consecutive parts of one message.

**Anti-replay and anti-reorder.** Every frame carries its sender's counter ``ctr``, which only grows (3b persists it
before a frame is sent). A receiver keeps the highest counter accepted per sender and refuses anything at or below
it, so a replayed frame and a reordered one are both refused; parts of one message must arrive consecutively. The
inner metadata, encrypted, ties a frame to what already de-duplicates it: a transaction carries its
``Idempotency-Key`` (``idem``) and ``base_seq``, a delta its ``seq`` and ``base_seq`` (the follower still checks
ancestry before applying). A transaction whose signed creation time is older than ``TX_MAX_AGE_S`` (7 days, a day
inside the home's 8-day key) is refused, so a frame replayed after the key expired cannot run twice.

**What the relay can and cannot do** is the PR's threat model (network.md, "The relay: built on localhost").
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import struct
import time
import contextlib
from dataclasses import dataclass, field

from nacl import bindings
from nacl.exceptions import BadSignatureError, CryptoError
from nacl.public import PrivateKey, PublicKey, SealedBox
from nacl.signing import SigningKey, VerifyKey

MAGIC = b"CR1"
SIG_DOMAIN = b"cicada-relay-frame-v1\x00"
AUTH_DOMAIN = b"cicada-relay-auth-v1\x00"
SIG_LEN = 64
NONCE_LEN = bindings.crypto_aead_xchacha20poly1305_ietf_NPUBBYTES
TAG_LEN = bindings.crypto_aead_xchacha20poly1305_ietf_ABYTES
KINDS = frozenset({"tx", "control", "delta", "status", "stream", "epoch"})
HOME_ONLY = frozenset({"delta", "stream", "epoch"})

MiB = 1024 * 1024
MAX_FRAME = 1 * MiB
#: Room left in a frame for the header (a recipient list of 64 keys is ~3 KB), nonce, tag and signature.
MAX_PART_PLAIN = MAX_FRAME - 8 * 1024
BUCKETS = tuple(4096 << i for i in range(8)) + (MAX_PART_PLAIN,)   # 4 KiB … 512 KiB, then the largest part
TX_MAX_AGE_S = 7 * 86_400
MAX_CLOCK_SKEW_S = 300
#: Epoch keys a newly wrapped device receives: those started within this window (frames under them may still be in
#: the mailbox, whose longest TTL is 7 days).
KEY_RETAIN_S = 8 * 86_400
#: A message other than the bootstrap is assembled in memory, up to this. A Sleep drain's decay delta measured ~10 MB.
MAX_MESSAGE_BYTES = 64 * MiB
#: The bootstrap (``stream``) is never held in memory: its parts are spooled to a 0600 file outside every bank, up to
#: the relay's own ``max_stream_bytes`` (``relay/cicada_relay/config.py``; ``test_sync_relay_crypto`` holds the two equal).
MAX_STREAM_BYTES = 256 * MiB
HANDOFF_DOMAIN = b"cicada-relay-handoff-v1\x00"


class Refused(Exception):
    """A frame this endpoint will not accept; ``code`` says why (never the frame's content)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def b64d(text: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(str(text) + "=" * (-len(str(text)) % 4))
    except (ValueError, TypeError) as exc:
        raise Refused("bad_encoding") from exc


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def new_mailbox_id() -> str:
    """Random, never derived from the bank id or a name: the relay knows a bank only by this."""
    return b64e(secrets.token_bytes(16))


# -- padding ---------------------------------------------------------------------------------------------------------
def bucket(n: int) -> int:
    for size in BUCKETS:
        if n + 1 <= size:
            return size
    raise ValueError("part too large")


def pad(data: bytes) -> bytes:
    """ISO/IEC 7816-4 padding (libsodium's ``sodium_pad``): ``0x80`` then zeros, up to the bucket."""
    return data + b"\x80" + b"\x00" * (bucket(len(data)) - len(data) - 1)


def unpad(data: bytes) -> bytes:
    end = len(data.rstrip(b"\x00"))
    if end == 0 or data[end - 1] != 0x80:
        raise Refused("bad_padding")
    return data[: end - 1]


def framed_size(payload_len: int, meta_len: int = 64, header_len: int = 300) -> int:
    """Bytes the relay stores for one message of ``payload_len`` (the measured bundle sizes' wire cost)."""
    inner = 4 + meta_len + payload_len
    total, left = 0, inner
    while True:
        chunk = min(left, MAX_PART_PLAIN - 1)
        total += len(MAGIC) + 2 + header_len + NONCE_LEN + bucket(chunk) + TAG_LEN + SIG_LEN
        left -= chunk
        if left <= 0:
            return total


# -- keys ------------------------------------------------------------------------------------------------------------
@dataclass
class Keys:
    """A device's two key pairs. ``export`` is secret: 3b keeps it outside every bank (0600, or the Keychain)."""

    ed: SigningKey
    x: PrivateKey

    @classmethod
    def generate(cls) -> "Keys":
        return cls(SigningKey.generate(), PrivateKey.generate())

    @property
    def ed_b64(self) -> str:
        return b64e(bytes(self.ed.verify_key))

    @property
    def x_b64(self) -> str:
        return b64e(bytes(self.x.public_key))

    def public(self) -> dict:
        return {"ed": self.ed_b64, "x": self.x_b64}

    def export(self) -> dict:
        return {"ed": b64e(bytes(self.ed)), "x": b64e(bytes(self.x))}

    @classmethod
    def load(cls, data: dict) -> "Keys":
        return cls(SigningKey(b64d(data["ed"])), PrivateKey(b64d(data["x"])))

    def sign_auth(self, mailbox: str, nonce: bytes) -> str:
        """The relay's challenge, signed: proves this device holds a key on the bank's membership."""
        return b64e(self.ed.sign(AUTH_DOMAIN + mailbox.encode("ascii") + b"\x00" + nonce).signature)


# -- frames ----------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Parsed:
    raw: bytes
    header: dict
    aad: bytes
    body: bytes
    sig: bytes


def build_frame(keys: Keys, header: dict, body: bytes) -> bytes:
    hb = canonical(header)
    head = MAGIC + struct.pack(">H", len(hb)) + hb
    sig = keys.ed.sign(SIG_DOMAIN + head + body).signature
    return head + body + sig


def parse_frame(raw: bytes) -> Parsed:
    if not isinstance(raw, (bytes, bytearray)) or len(raw) < 5 + SIG_LEN or raw[:3] != MAGIC:
        raise Refused("bad_frame")
    raw = bytes(raw)
    (hlen,) = struct.unpack(">H", raw[3:5])
    if 5 + hlen + SIG_LEN > len(raw):
        raise Refused("bad_frame")
    hb = raw[5 : 5 + hlen]
    try:
        header = json.loads(hb)
    except ValueError as exc:
        raise Refused("bad_header") from exc
    if not isinstance(header, dict) or canonical(header) != hb or header.get("v") != 1:
        raise Refused("bad_header")
    if header.get("kind") not in KINDS:
        raise Refused("bad_header")
    for k in ("ep", "ctr", "at", "msg", "part", "parts"):
        if not isinstance(header.get(k), int) or isinstance(header.get(k), bool) or header[k] < 0:
            raise Refused("bad_header")
    if not (0 <= header["part"] < header["parts"]) or header["ctr"] - header["msg"] != header["part"]:
        raise Refused("bad_header")
    return Parsed(raw=raw, header=header, aad=raw[: 5 + hlen], body=raw[5 + hlen : -SIG_LEN], sig=raw[-SIG_LEN:])


def verify_frame(p: Parsed, sender_ed_b64: str) -> None:
    try:
        VerifyKey(b64d(sender_ed_b64)).verify(SIG_DOMAIN + p.raw[:-SIG_LEN], p.sig)
    except (BadSignatureError, ValueError, TypeError) as exc:
        raise Refused("bad_signature") from exc


@dataclass
class Message:
    kind: str
    sender: str
    payload: bytes
    meta: dict
    at: int
    ctr: int
    #: A bootstrap's payload is not in memory: it is this spooled file (0600), the caller's to apply and delete.
    path: str | None = None


def _check_meta(kind: str, meta: dict) -> None:
    if kind == "tx":
        idem = meta.get("idem")
        if not isinstance(idem, str) or not 8 <= len(idem) <= 200:
            raise Refused("bad_meta")
    if kind == "delta" and not isinstance(meta.get("seq"), int):
        raise Refused("bad_meta")


@dataclass
class Endpoint:
    """One device's half: its keys and counter, the pinned home key, the epoch keys it holds, the membership it last
    accepted, and the highest counter accepted per sender. ``to_state``/``from_state`` carry it across restarts
    (secret: outside every bank)."""

    keys: Keys
    mailbox: str
    home: str                                   # the home's Ed25519 key, pinned at pairing
    ctr: int = 0
    epoch: int = 0
    epoch_keys: dict[int, bytes] = field(default_factory=dict)
    members: dict[str, str] = field(default_factory=dict)   # ed -> x
    hw: dict[str, int] = field(default_factory=dict)
    revoked: bool = False
    clock: object = time.time
    #: Where a bootstrap's parts are spooled (0700, outside every bank; 3b passes ``$CICADA_HOME/sync/<bank>/spool``).
    #: Unset, a stream is refused.
    spool_dir: str | None = None
    #: The home before the last hand-off this device accepted: the only key a hand-off's group record may be signed by.
    prev_home: str | None = None
    _partial: dict = field(default_factory=dict)

    @property
    def me(self) -> str:
        return self.keys.ed_b64

    @property
    def is_home(self) -> bool:
        return self.me == self.home

    # -- sending ----------------------------------------------------------------------------------------------------
    def _next_ctr(self, n: int) -> int:
        first = self.ctr + 1
        self.ctr += n
        return first

    def seal(self, kind: str, payload: bytes, *, meta: dict | None = None, to="*") -> list[bytes]:
        """Encrypt and sign one message as one or more frames, in the order they must be sent."""
        if kind not in KINDS or kind == "epoch":
            raise Refused("bad_kind")
        if kind in HOME_ONLY and not self.is_home:
            raise Refused("home_only")
        if self.revoked or self.epoch not in self.epoch_keys:
            raise Refused("no_epoch")
        meta = dict(meta or {})
        _check_meta(kind, meta)
        mb = canonical(meta)
        inner = struct.pack(">I", len(mb)) + mb + bytes(payload)
        step = MAX_PART_PLAIN - 1
        chunks = [inner[i : i + step] for i in range(0, len(inner), step)] or [b""]
        if kind == "stream" and len(inner) > MAX_STREAM_BYTES:
            raise Refused("too_large")
        msg = self._next_ctr(len(chunks))
        at = int(self.clock())
        return [self._part(kind, to, msg, i, len(chunks), at, chunk) for i, chunk in enumerate(chunks)]

    def seal_stream(self, path: str, *, meta: dict | None = None, to="*"):
        """The bootstrap from a file, one frame at a time: neither side ever holds the whole bundle in memory."""
        if not self.is_home:
            raise Refused("home_only")
        if self.revoked or self.epoch not in self.epoch_keys:
            raise Refused("no_epoch")
        mb = canonical(dict(meta or {}))
        size = os.path.getsize(path)
        inner_len = 4 + len(mb) + size
        if inner_len > MAX_STREAM_BYTES:
            raise Refused("too_large")
        step = MAX_PART_PLAIN - 1
        parts = max(1, -(-inner_len // step))
        msg = self._next_ctr(parts)
        at = int(self.clock())
        with open(path, "rb") as fh:
            head = struct.pack(">I", len(mb)) + mb
            for i in range(parts):
                chunk = head + fh.read(step - len(head))
                head = b""
                yield self._part("stream", to, msg, i, parts, at, chunk)

    def _part(self, kind: str, to, msg: int, i: int, parts: int, at: int, chunk: bytes) -> bytes:
        header = {"v": 1, "mb": self.mailbox, "ep": self.epoch, "from": self.me, "ctr": msg + i, "kind": kind,
                  "at": at, "msg": msg, "part": i, "parts": parts, "to": to}
        hb = canonical(header)
        aad = MAGIC + struct.pack(">H", len(hb)) + hb
        nonce = secrets.token_bytes(NONCE_LEN)
        ct = bindings.crypto_aead_xchacha20poly1305_ietf_encrypt(pad(chunk), aad, nonce, self.epoch_keys[self.epoch])
        return build_frame(self.keys, header, nonce + ct)

    # -- receiving --------------------------------------------------------------------------------------------------
    def open(self, raw: bytes) -> Message | None:
        """Verify, decrypt and order one frame. Returns the whole message on its last part, ``None`` for an earlier
        part or an epoch frame already known; raises ``Refused`` for anything that must not be accepted."""
        p = parse_frame(raw)
        h = p.header
        if h["mb"] != self.mailbox:
            raise Refused("wrong_mailbox")
        if h["kind"] == "epoch":
            return self._open_epoch(p)
        sender = h["from"]
        if sender not in self.members:
            raise Refused("not_member")
        verify_frame(p, sender)
        if h["kind"] in HOME_ONLY and sender != self.home:
            raise Refused("home_only")
        to = h["to"]
        if (to == "home" and not self.is_home) or (isinstance(to, list) and self.me not in to):
            raise Refused("not_for_me")
        if h["ctr"] <= self.hw.get(sender, 0):
            raise Refused("replay")
        key = self.epoch_keys.get(h["ep"])
        if key is None:
            raise Refused("unknown_epoch")
        now = self.clock()
        if h["at"] > now + MAX_CLOCK_SKEW_S:
            raise Refused("clock")
        if h["kind"] == "tx" and now - h["at"] > TX_MAX_AGE_S:
            raise Refused("expired")
        if len(p.body) < NONCE_LEN + TAG_LEN:
            raise Refused("bad_ciphertext")
        try:
            plain = bindings.crypto_aead_xchacha20poly1305_ietf_decrypt(
                p.body[NONCE_LEN:], p.aad, p.body[:NONCE_LEN], key)
        except CryptoError as exc:
            raise Refused("bad_ciphertext") from exc
        chunk = unpad(plain)
        self.hw[sender] = h["ctr"]
        return self._assemble(h, sender, chunk)

    def _drop_partial(self, k) -> None:
        got = self._partial.pop(k, None)
        if isinstance(got, dict):
            got["fh"].close()
            with contextlib.suppress(OSError):
                os.unlink(got["path"])

    @staticmethod
    def _meta(inner: bytes, kind: str) -> tuple[dict, int]:
        if len(inner) < 4:
            raise Refused("bad_meta")
        (mlen,) = struct.unpack(">I", inner[:4])
        if 4 + mlen > len(inner):
            raise Refused("bad_meta")
        try:
            meta = json.loads(inner[4 : 4 + mlen])
        except ValueError as exc:
            raise Refused("bad_meta") from exc
        if not isinstance(meta, dict):
            raise Refused("bad_meta")
        _check_meta(kind, meta)
        return meta, 4 + mlen

    def _spool(self, h: dict, sender: str, chunk: bytes) -> Message | None:
        """A bootstrap part, appended to its 0600 spool file; the message on the last part names the file."""
        k = (sender, h["msg"])
        if h["part"] == 0:
            for other in [kk for kk in self._partial if kk[0] == sender]:
                self._drop_partial(other)
            if not self.spool_dir:
                raise Refused("no_spool")
            meta, start = self._meta(chunk, h["kind"])
            os.makedirs(self.spool_dir, mode=0o700, exist_ok=True)
            path = os.path.join(self.spool_dir, f"stream-{secrets.token_hex(8)}.part")
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            got = {"fh": os.fdopen(fd, "wb"), "path": path, "parts": 0, "bytes": 0, "meta": meta}
            self._partial[k] = got
            chunk = chunk[start:]
        else:
            got = self._partial.get(k)
            if not isinstance(got, dict) or got["parts"] != h["part"]:
                self._drop_partial(k)
                raise Refused("gap")
        got["bytes"] += len(chunk)
        if got["bytes"] > MAX_STREAM_BYTES:
            self._drop_partial(k)
            raise Refused("too_large")
        got["fh"].write(chunk)
        got["parts"] += 1
        if h["part"] < h["parts"] - 1:
            return None
        self._partial.pop(k)
        got["fh"].close()
        return Message(kind="stream", sender=sender, payload=b"", meta=got["meta"], at=h["at"], ctr=h["msg"],
                       path=got["path"])

    def _assemble(self, h: dict, sender: str, chunk: bytes) -> Message | None:
        if h["kind"] == "stream":
            return self._spool(h, sender, chunk)
        k = (sender, h["msg"])
        if h["parts"] == 1:
            inner = chunk
        else:
            if h["part"] == 0:
                for other in [kk for kk in self._partial if kk[0] == sender]:
                    self._drop_partial(other)
                self._partial[k] = [chunk]
            else:
                got = self._partial.get(k)
                if not isinstance(got, list) or len(got) != h["part"]:
                    self._drop_partial(k)
                    raise Refused("gap")
                got.append(chunk)
                if sum(len(c) for c in got) > MAX_MESSAGE_BYTES:
                    self._drop_partial(k)
                    raise Refused("too_large")
            if h["part"] < h["parts"] - 1:
                return None
            inner = b"".join(self._partial.pop(k))
        meta, start = self._meta(inner, h["kind"])
        return Message(kind=h["kind"], sender=sender, payload=inner[start:], meta=meta, at=h["at"], ctr=h["msg"])

    def _open_epoch(self, p: Parsed) -> Message | None:
        verify_frame(p, self.home)   # only the pinned home may change the membership
        if p.header["from"] != self.home:
            raise Refused("home_only")
        try:
            body = json.loads(p.body)
            st = body["statement"]
            wraps = body["keys"]
        except (ValueError, KeyError, TypeError) as exc:
            raise Refused("bad_epoch") from exc
        if st.get("mb") != self.mailbox or st.get("epoch") != p.header["ep"] or st.get("v") != 1:
            raise Refused("bad_epoch")
        if st["epoch"] <= self.epoch:
            return None   # already known: the relay re-sends the latest membership on every connect
        devices = {d["ed"]: d["x"] for d in st.get("devices", [])}
        if self.me not in devices:
            self.revoked = True
            raise Refused("revoked")
        wrap = wraps.get(self.me)
        if not wrap:
            raise Refused("bad_epoch")
        try:
            got = json.loads(SealedBox(self.keys.x).decrypt(b64d(wrap)))
        except (CryptoError, ValueError) as exc:
            raise Refused("bad_epoch") from exc
        if got.get("mb") != self.mailbox or str(st["epoch"]) not in got.get("keys", {}):
            raise Refused("bad_epoch")
        for e, k in got["keys"].items():
            self.epoch_keys[int(e)] = b64d(k)
        self.members = devices
        self.epoch = st["epoch"]
        if st["home"] != self.home:
            self.prev_home = self.home
        self.home = st["home"]
        return Message(kind="epoch", sender=p.header["from"], payload=b"", meta={"statement": st},
                       at=p.header["at"], ctr=p.header["ctr"])

    # -- persistence ------------------------------------------------------------------------------------------------
    def to_state(self) -> dict:
        return {"keys": self.keys.export(), "mailbox": self.mailbox, "home": self.home, "ctr": self.ctr,
                "epoch": self.epoch, "epoch_keys": {str(e): b64e(k) for e, k in self.epoch_keys.items()},
                "members": self.members, "hw": self.hw, "revoked": self.revoked, "prev_home": self.prev_home}

    def clear_spool(self) -> int:
        """Delete unfinished bootstrap parts left by an earlier run (a crash or a restart mid-stream). ``from_state``
        calls it when given a ``spool_dir``: a restored endpoint holds no partial stream, so nothing there is live."""
        if not self.spool_dir or not os.path.isdir(self.spool_dir):
            return 0
        n = 0
        for name in os.listdir(self.spool_dir):
            if name.startswith("stream-") and name.endswith(".part"):
                with contextlib.suppress(OSError):
                    os.unlink(os.path.join(self.spool_dir, name))
                    n += 1
        return n

    @classmethod
    def from_state(cls, state: dict, **kw) -> "Endpoint":
        endpoint = cls._restore(state, **kw)
        endpoint.clear_spool()
        return endpoint

    @classmethod
    def _restore(cls, state: dict, **kw) -> "Endpoint":
        return cls(keys=Keys.load(state["keys"]), mailbox=state["mailbox"], home=state["home"], ctr=state["ctr"],
                   epoch=state["epoch"], epoch_keys={int(e): b64d(k) for e, k in state["epoch_keys"].items()},
                   members=dict(state["members"]), hw=dict(state["hw"]), revoked=state["revoked"],
                   prev_home=state.get("prev_home"), **kw)


@dataclass
class Home(Endpoint):
    """The home's half: it also owns the group — who is in it, and every epoch key with when it started."""

    joined: dict[str, int] = field(default_factory=dict)          # ed -> the epoch it joined
    started: dict[int, float] = field(default_factory=dict)       # epoch -> when it started

    @classmethod
    def create(cls, keys: Keys | None = None, mailbox: str | None = None, clock=time.time) -> "Home":
        keys = keys or Keys.generate()
        home = cls(keys=keys, mailbox=mailbox or new_mailbox_id(), home=keys.ed_b64, clock=clock)
        home.members = {keys.ed_b64: keys.x_b64}
        home.joined = {keys.ed_b64: 1}
        home._new_epoch()
        return home

    def _new_epoch(self) -> None:
        self.epoch += 1
        self.epoch_keys[self.epoch] = secrets.token_bytes(32)
        self.started[self.epoch] = self.clock()

    def epoch_frame(self, *, home: str | None = None) -> bytes:
        """The current membership, signed, with each device's key wrap. ``home`` names a hand-off target."""
        now = self.clock()
        devices = [{"ed": ed, "x": x} for ed, x in sorted(self.members.items())]
        st = {"v": 1, "mb": self.mailbox, "epoch": self.epoch, "home": home or self.me, "devices": devices,
              "at": int(now)}
        wraps = {}
        for ed, x in sorted(self.members.items()):
            if ed == self.me:
                continue
            keep = {str(e): b64e(k) for e, k in self.epoch_keys.items()
                    if e >= self.joined.get(ed, self.epoch) and (e == self.epoch or now - self.started.get(e, now)
                                                                 <= KEY_RETAIN_S)}
            wraps[ed] = b64e(SealedBox(PublicKey(b64d(x))).encrypt(canonical({"mb": self.mailbox, "keys": keep})))
        ctr = self._next_ctr(1)
        header = {"v": 1, "mb": self.mailbox, "ep": self.epoch, "from": self.me, "ctr": ctr, "kind": "epoch",
                  "at": int(now), "msg": ctr, "part": 0, "parts": 1, "to": "*"}
        return build_frame(self.keys, header, canonical({"statement": st, "keys": wraps}))

    def add_device(self, public: dict) -> bytes:
        """A paired device joins: a new epoch it holds the key to, and nothing from before it joined."""
        if not public.get("ed") or not public.get("x"):
            raise Refused("bad_device")
        self._new_epoch()
        self.members[public["ed"]] = public["x"]
        self.joined[public["ed"]] = self.epoch
        return self.epoch_frame()

    def revoke(self, ed: str) -> bytes:
        """Remove a device and rotate: nothing sent after this frame opens with a key the device holds, and the relay
        drops it the moment it reads the new membership."""
        if ed == self.me or ed not in self.members:
            raise Refused("bad_device")
        del self.members[ed]
        self.joined.pop(ed, None)
        self.hw.pop(ed, None)
        self._new_epoch()
        return self.epoch_frame()

    def hand_off(self, new_home_ed: str) -> tuple[bytes, bytes]:
        """The old home's last membership frame names the new home (phase 2's signed hand-off, at the relay), and the
        group record — who joined when, and when each epoch started — goes to the new home alone, signed by this home
        and sealed to the new home's key, so the new home never wraps a key to a device that joined after it, nor
        restarts a key's retention. After it, this endpoint is an ordinary device. Returns ``(epoch frame, record)``."""
        if new_home_ed not in self.members or new_home_ed == self.me:
            raise Refused("bad_device")
        self._new_epoch()
        frame = self.epoch_frame(home=new_home_ed)
        body = canonical({"mb": self.mailbox, "epoch": self.epoch, "to": new_home_ed, "joined": self.joined,
                          "started": {str(e): t for e, t in self.started.items()}})
        signed = canonical({"body": b64e(body), "sig": b64e(self.keys.ed.sign(HANDOFF_DOMAIN + body).signature)})
        record = SealedBox(PublicKey(b64d(self.members[new_home_ed]))).encrypt(signed)
        self.prev_home, self.home = self.me, new_home_ed
        return frame, record

    @classmethod
    def take_over(cls, device: Endpoint, record: bytes) -> "Home":
        """A device that accepted a hand-off naming it becomes the home, from the state it holds and the old home's
        group record (required: without it the new home cannot know who joined when)."""
        if device.home != device.me or not device.prev_home:
            raise Refused("not_home")
        try:
            outer = json.loads(SealedBox(device.keys.x).decrypt(record))
            body = b64d(outer["body"])
            VerifyKey(b64d(device.prev_home)).verify(HANDOFF_DOMAIN + body, b64d(outer["sig"]))
            got = json.loads(body)
        except (CryptoError, BadSignatureError, ValueError, KeyError, TypeError) as exc:
            raise Refused("bad_handoff") from exc
        if got.get("mb") != device.mailbox or got.get("epoch") != device.epoch or got.get("to") != device.me:
            raise Refused("bad_handoff")
        joined = {ed: int(e) for ed, e in got["joined"].items() if ed in device.members}
        if set(joined) != set(device.members):
            raise Refused("bad_handoff")
        home = cls(keys=device.keys, mailbox=device.mailbox, home=device.me, ctr=device.ctr, epoch=device.epoch,
                   epoch_keys=dict(device.epoch_keys), members=dict(device.members), hw=dict(device.hw),
                   clock=device.clock, prev_home=device.prev_home)
        home.joined = joined
        home.started = {int(e): float(t) for e, t in got["started"].items() if int(e) in device.epoch_keys}
        return home

    def to_state(self) -> dict:
        state = super().to_state()
        state["joined"] = self.joined
        state["started"] = {str(e): t for e, t in self.started.items()}
        return state

    @classmethod
    def from_state(cls, state: dict, **kw) -> "Home":
        home = super().from_state(state, **kw)   # clears the spool too
        home.joined = dict(state.get("joined", {}))
        home.started = {int(e): t for e, t in state.get("started", {}).items()}
        return home
