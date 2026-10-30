"""Pairing a device over the relay: the backend half (G132 phase 3a, gate g3). The app's QR and confirmation screens
are phase 3b's.

Today's pairing code (``device_tokens``: 8 symbols of 31, ten minutes, single use) is strong against guessing but it
is not a key, so over an untrusted relay it must be bound to the home's public keys:

**QR (primary).** The QR carries ``{v: 2, code, relay, slot, home: {ed, x}}`` (plus today's ``url`` when the home is
also reachable directly). ``slot`` is random, so the relay never learns the code. The device seals its request
``{code, name, ed, x, nd, binding}`` to the home's X25519 key from the QR; the home checks the code and answers with a
welcome signed by the Ed25519 key the QR pinned and sealed to the device. The relay can neither read nor substitute.

**Typed code (no camera).** The device knows only the code, so the slot is derived from it with Argon2id (a relay that
holds the slot id still cannot afford to search the code space within the code's ten minutes), and the home's keys
arrive through the relay. To catch a relay that substitutes keys, the exchange is a numeric comparison with a
commitment (Bluetooth's numeric-comparison shape): the home's offer commits to a nonce ``nh`` before it sees the
device's nonce ``nd``; after the request it reveals ``nh``; both screens then show the same six digits,
``SAS = H(home keys, device keys, nh, nd, slot)``, only when nobody stood between them. A relay in the middle had to
fix its own commitment before learning ``nd`` and send its own ``nd`` before learning ``nh``, so it matches with
probability 10⁻⁶ per attempt. The home releases the welcome (the token, the membership and the epoch keys) only after
the person confirms the digits match on the home's screen, the device accepts it only after the same confirmation on
its own, and a slot that receives a second request is void ("Two devices answered this code; start again").

Nothing here is logged; the token and the code live only in sealed boxes and in memory.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass, field

from nacl import pwhash
from nacl.exceptions import BadSignatureError, CryptoError
from nacl.public import PublicKey, SealedBox
from nacl.signing import VerifyKey

from .sync_relay_crypto import Endpoint, Home, Keys, Refused, b64d, b64e, canonical

PAIR_DOMAIN = b"cicada-relay-pair-v1\x00"
SAS_DOMAIN = b"cicada-relay-sas-v1\x00"
SLOT_SALT = hashlib.sha256(b"cicada-relay-pair-slot-v1").digest()[: pwhash.argon2id.SALTBYTES]
#: The typed path's slot cost. Production uses the interactive limits (~0.1-0.3 s, 64 MiB, once per pairing); the
#: suite passes the minimums.
SLOT_OPS = pwhash.argon2id.OPSLIMIT_INTERACTIVE
SLOT_MEM = pwhash.argon2id.MEMLIMIT_INTERACTIVE


def normal_code(code: str) -> str:
    return "".join(ch for ch in str(code).upper() if ch.isalnum())


def slot_for_code(code: str, *, ops: int = SLOT_OPS, mem: int = SLOT_MEM) -> str:
    return b64e(pwhash.argon2id.kdf(16, normal_code(code).encode("ascii"), SLOT_SALT, opslimit=ops, memlimit=mem))


def random_slot() -> str:
    return b64e(secrets.token_bytes(16))


def qr_payload(code: str, relay: str, slot: str, home: Keys, url: str | None = None) -> dict:
    """What the home's QR encodes (v2; v1 ``{v, url, code}`` stays for the direct path)."""
    out = {"v": 2, "code": code, "relay": relay, "slot": slot, "home": home.public()}
    if url:
        out["url"] = url
    return out


def _signed(keys: Keys, obj: dict) -> bytes:
    body = canonical(obj)
    return canonical({"body": b64e(body), "sig": b64e(keys.ed.sign(PAIR_DOMAIN + body).signature)})


def _verify(blob: bytes, ed_b64: str) -> dict:
    try:
        outer = json.loads(blob)
        body = b64d(outer["body"])
        VerifyKey(b64d(ed_b64)).verify(PAIR_DOMAIN + body, b64d(outer["sig"]))
        return json.loads(body)
    except (ValueError, KeyError, TypeError, BadSignatureError) as exc:
        raise Refused("bad_pairing_signature") from exc


def _seal(x_b64: str, obj: dict) -> bytes:
    return SealedBox(PublicKey(b64d(x_b64))).encrypt(canonical(obj))


def _unseal(keys: Keys, blob: bytes) -> dict:
    try:
        return json.loads(SealedBox(keys.x).decrypt(blob))
    except (CryptoError, ValueError, TypeError) as exc:
        raise Refused("bad_pairing_message") from exc


def _commit(home_pub: dict, nh: bytes) -> str:
    return b64e(hashlib.sha256(canonical({"ed": home_pub["ed"], "x": home_pub["x"], "nh": b64e(nh)})).digest())


def sas(home_pub: dict, dev_pub: dict, nh: str, nd: str, slot: str) -> str:
    """Six digits both screens show: ``123 456``."""
    digest = hashlib.sha256(SAS_DOMAIN + canonical({"h": home_pub, "d": dev_pub, "nh": nh, "nd": nd,
                                                    "slot": slot})).digest()
    n = int.from_bytes(digest[:8], "big") % 1_000_000
    return f"{n // 1000:03d} {n % 1000:03d}"


@dataclass
class Candidate:
    """A device that answered the code: what the home's screen shows before the person confirms."""

    name: str
    public: dict
    nd: str
    binding: str | None
    sas: str | None


@dataclass
class HomePairing:
    """The home's side of one pairing. ``typed`` is the no-camera path (offer with a commitment, SAS)."""

    home: Home
    code: str
    slot: str
    typed: bool
    _nh: bytes = field(default_factory=lambda: secrets.token_bytes(32))
    candidate: Candidate | None = None
    void: bool = False
    done: bool = False

    def offer(self) -> bytes:
        """Posted to the relay's slot. The QR path needs none (the QR carries the keys) but sends one anyway, so a
        device that scanned a QR can check it is talking to the home it pinned."""
        obj = {"v": 1, "home": self.home.keys.public(), "slot": self.slot}
        if self.typed:
            obj["commit"] = _commit(self.home.keys.public(), self._nh)
        return _signed(self.home.keys, obj)

    def receive(self, sealed: bytes) -> tuple[Candidate, bytes | None]:
        """A device's request. Returns the candidate and, on the typed path, the reveal to send back. A wrong code
        is refused (``bad_code``); a second request voids the slot."""
        if self.void or self.done:
            raise Refused("pairing_void")
        if self.candidate is not None:
            self.void = True
            raise Refused("pairing_void")
        req = _unseal(self.home.keys, sealed)
        if not hmac.compare_digest(normal_code(req.get("code", "")).encode(), normal_code(self.code).encode()):
            raise Refused("bad_code")
        if req.get("slot") != self.slot:
            raise Refused("bad_pairing_message")
        public = {"ed": str(req.get("ed", "")), "x": str(req.get("x", ""))}
        if len(b64d(public["ed"])) != 32 or len(b64d(public["x"])) != 32:
            raise Refused("bad_pairing_message")
        code_sas = sas(self.home.keys.public(), public, b64e(self._nh), req.get("nd", ""), self.slot) \
            if self.typed else None
        self.candidate = Candidate(name=str(req.get("name", ""))[:80], public=public, nd=str(req.get("nd", "")),
                                   binding=req.get("binding"), sas=code_sas)
        reveal = _seal(public["x"], {"nh": b64e(self._nh), "signed": b64e(_signed(self.home.keys, {
            "nh": b64e(self._nh), "slot": self.slot, "for": public["ed"]}))}) if self.typed else None
        return self.candidate, reveal

    def welcome(self, token: str, *, confirmed: bool, extra: dict | None = None) -> tuple[bytes, bytes]:
        """After the person confirmed (always, on the typed path; the QR path's confirmation is the scan itself):
        the device joins a new epoch. Returns the sealed welcome for the device and the epoch frame for the relay."""
        if self.void or self.done or self.candidate is None:
            raise Refused("pairing_void")
        if self.typed and not confirmed:
            raise Refused("not_confirmed")
        frame = self.home.add_device(self.candidate.public)
        self.done = True
        signed = _signed(self.home.keys, {"slot": self.slot, "for": self.candidate.public["ed"],
                                          "mb": self.home.mailbox, "token": token, "epoch_frame": b64e(frame),
                                          **(extra or {})})
        return _seal(self.candidate.public["x"], {"signed": b64e(signed)}), frame


@dataclass
class DevicePairing:
    """The new device's side."""

    keys: Keys
    code: str
    slot: str
    name: str
    home_pub: dict | None = None     # pinned from the QR, or learned from the offer on the typed path
    typed: bool = False
    binding: str | None = None
    _commit: str | None = None
    _nd: str = field(default_factory=lambda: b64e(secrets.token_bytes(32)))
    nh: str | None = None
    sas: str | None = None

    @classmethod
    def from_qr(cls, payload: dict, name: str, keys: Keys | None = None) -> "DevicePairing":
        if payload.get("v") != 2 or not isinstance(payload.get("home"), dict):
            raise Refused("bad_qr")
        return cls(keys=keys or Keys.generate(), code=payload["code"], slot=payload["slot"], name=name,
                   home_pub={"ed": payload["home"]["ed"], "x": payload["home"]["x"]})

    @classmethod
    def from_code(cls, code: str, name: str, keys: Keys | None = None, **slot_cost) -> "DevicePairing":
        return cls(keys=keys or Keys.generate(), code=code, slot=slot_for_code(code, **slot_cost), name=name,
                   typed=True)

    def read_offer(self, offer: bytes) -> None:
        outer = json.loads(offer)
        claimed = json.loads(b64d(outer["body"]))
        home = claimed.get("home") or {}
        if self.home_pub is not None and home != self.home_pub:
            raise Refused("wrong_home")      # the QR pinned another home: a substituted offer
        body = _verify(offer, home.get("ed", ""))
        if body.get("slot") != self.slot:
            raise Refused("bad_pairing_message")
        if self.typed:
            if not body.get("commit"):
                raise Refused("bad_pairing_message")
            self._commit = body["commit"]
            self.home_pub = {"ed": home["ed"], "x": home["x"]}

    def request(self) -> bytes:
        if self.home_pub is None:
            raise Refused("no_offer")
        return _seal(self.home_pub["x"], {"code": self.code, "slot": self.slot, "name": self.name, "nd": self._nd,
                                          "binding": self.binding, **self.keys.public()})

    def read_reveal(self, sealed: bytes) -> str:
        """The typed path: check the home's nonce against its commitment, and return the six digits to show."""
        got = _unseal(self.keys, sealed)
        inner = _verify(b64d(got.get("signed", "")), self.home_pub["ed"])
        if inner.get("nh") != got.get("nh") or inner.get("for") != self.keys.ed_b64 or inner.get("slot") != self.slot:
            raise Refused("bad_pairing_message")
        if _commit(self.home_pub, b64d(got["nh"])) != self._commit:
            raise Refused("bad_commitment")
        self.nh = got["nh"]
        self.sas = sas(self.home_pub, self.keys.public(), self.nh, self._nd, self.slot)
        return self.sas

    def accept_welcome(self, sealed: bytes, *, confirmed: bool) -> tuple[str, Endpoint]:
        """The welcome: the device token and the device's endpoint, already holding the new epoch's key."""
        if self.typed and (not confirmed or self.sas is None):
            raise Refused("not_confirmed")
        got = _unseal(self.keys, sealed)
        inner = _verify(b64d(got.get("signed", "")), self.home_pub["ed"])
        if inner.get("for") != self.keys.ed_b64 or inner.get("slot") != self.slot:
            raise Refused("bad_pairing_message")
        endpoint = Endpoint(keys=self.keys, mailbox=inner["mb"], home=self.home_pub["ed"])
        msg = endpoint.open(b64d(inner["epoch_frame"]))
        if msg is None or msg.kind != "epoch":
            raise Refused("bad_epoch")
        return inner["token"], endpoint
