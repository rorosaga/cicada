"""Device-bound tokens: a proof of the device's own key on every request (G212, owner 2026-10-29; RFC 9449's shape).

A paired device's ``cic_dev_`` token is a bearer: whoever holds a copy can use it. A **key-bound** device also holds a
P-256 private key that never leaves it (the Secure Enclave on an iPhone) and signs each request with it. The server
keeps only that key's RFC 7638 thumbprint beside the token's hash (``device_tokens``), so a copied token is useless
anywhere the key is not: every request a bound token signs must carry a ``DPoP`` header whose proof

* is a compact JWS, ``typ: dpop+jwt``, ``alg: ES256`` (the one curve a Secure Enclave holds), with the public key as a
  ``jwk`` in its header and no private member;
* is signed by that key, whose thumbprint is the one the device was bound with;
* names this request: ``htm`` its method, ``htu`` its path. **Only the path is compared**, not the scheme or host —
  the person's overlay (``tailscale serve``) terminates TLS and the backend sees ``127.0.0.1``, so the authority the
  phone signed is the overlay's, never this socket's. A token is one server's, so a proof can name no other server;
* is fresh: ``iat`` within :data:`MAX_SKEW_S` of this server's clock, and its ``jti`` never seen before in that window
  (one process, one cache — the backend runs one worker);
* carries ``ath``, the token's own sha256, so a proof made for one token is no proof for another.

A bound token never falls back to bearer: no proof, or any check failing, is a 401 with ``WWW-Authenticate: DPoP
error="invalid_dpop_proof", error_description="<reason>"`` (one enum from :data:`REASONS`, never a value). An unbound
device (paired before key binding, or a computer whose clients cannot sign yet) works exactly as before.

Verifying costs one ECDSA verify; the public key object is cached by thumbprint so a device's steady stream parses its
key once. ``cryptography`` is already the backend's (``trace_seal``); a client that cannot import it never binds.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import secrets
import threading
import time
from collections import OrderedDict
from urllib.parse import urlsplit

HEADER = "DPoP"
TYP = "dpop+jwt"
ALG = "ES256"
#: How far a proof's ``iat`` may sit from this server's clock, either way. RFC 9449 leaves it to the server; five
#: minutes covers a phone whose clock drifts without accepting a proof captured long ago.
MAX_SKEW_S = 300
#: A ``jti`` is remembered for the whole window a proof could still pass in (both sides of the skew).
JTI_TTL_S = 2 * MAX_SKEW_S
#: The cache's ceiling; past it the oldest entries go first (they are the first to leave the window anyway).
JTI_MAX = 50_000
#: A proof is a few hundred bytes; anything far longer is not one.
MAX_PROOF_BYTES = 4096
REASONS = ("missing", "malformed", "unsupported", "bad_signature", "wrong_request", "stale", "replayed",
           "wrong_token", "wrong_key")


class ProofError(ValueError):
    """Why a proof failed: one of :data:`REASONS`, safe to say to the caller (an enum, never a value)."""

    def __init__(self, reason: str) -> None:
        assert reason in REASONS, reason
        self.reason = reason
        super().__init__(reason)


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    if not isinstance(text, str) or not text or any(ch in text for ch in "=+/ \n"):
        raise ProofError("malformed")
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError):
        raise ProofError("malformed") from None


def thumbprint(jwk: dict) -> str:
    """RFC 7638: sha256 over the required members in lexicographic order, no spaces — the same string on every side."""
    canonical = json.dumps({"crv": jwk["crv"], "kty": jwk["kty"], "x": jwk["x"], "y": jwk["y"]},
                           separators=(",", ":"), sort_keys=True)
    return b64url(hashlib.sha256(canonical.encode("ascii")).digest())


def token_hash(token: str) -> str:
    """``ath``: the access token's sha256, base64url."""
    return b64url(hashlib.sha256(token.encode("ascii")).digest())


_KEYS: OrderedDict[str, object] = OrderedDict()
_KEYS_MAX = 256
_keys_lock = threading.Lock()


def _public_key(jwk) -> tuple[object, str]:
    """The verified P-256 public key a proof's ``jwk`` names, and its thumbprint. A private member, another curve or a
    point off the curve is refused."""
    if not isinstance(jwk, dict) or jwk.get("kty") != "EC" or jwk.get("crv") != "P-256":
        raise ProofError("unsupported")
    if "d" in jwk or not isinstance(jwk.get("x"), str) or not isinstance(jwk.get("y"), str):
        raise ProofError("malformed")
    x, y = _b64url_decode(jwk["x"]), _b64url_decode(jwk["y"])
    if len(x) != 32 or len(y) != 32:
        raise ProofError("malformed")
    jkt = thumbprint(jwk)
    with _keys_lock:
        key = _KEYS.get(jkt)
        if key is not None:
            _KEYS.move_to_end(jkt)
            return key, jkt
    from cryptography.hazmat.primitives.asymmetric import ec

    try:
        key = ec.EllipticCurvePublicNumbers(int.from_bytes(x, "big"), int.from_bytes(y, "big"),
                                            ec.SECP256R1()).public_key()
    except ValueError:
        raise ProofError("malformed") from None
    with _keys_lock:
        _KEYS[jkt] = key
        while len(_KEYS) > _KEYS_MAX:
            _KEYS.popitem(last=False)
    return key, jkt


_SEEN: OrderedDict[tuple[str, str], float] = OrderedDict()
_seen_lock = threading.Lock()


def _first_use(jkt: str, jti: str, now: float) -> bool:
    """Record ``(jkt, jti)``; False when it was already used inside the window."""
    key = (jkt, jti)
    with _seen_lock:
        while _SEEN:
            _, expires = next(iter(_SEEN.items()))
            if expires > now and len(_SEEN) < JTI_MAX:
                break
            _SEEN.popitem(last=False)
        if key in _SEEN:
            return False
        _SEEN[key] = now + JTI_TTL_S
        return True


def _no_constant(name: str):
    raise ValueError(f"non-finite number {name}")


def _strict_json(raw: bytes):
    """A proof part's JSON with no NaN, Infinity or -Infinity (Python's ``json`` accepts all three by default; JSON
    itself has none) — refused as malformed before any claim is read (review B1)."""
    return json.loads(raw, parse_constant=_no_constant)


def _same_path(htu: str, path: str) -> bool:
    try:
        parts = urlsplit(htu)
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return False
    return (parts.path.rstrip("/") or "/") == ((path or "/").rstrip("/") or "/")


def verify(proof: str | None, *, method: str, path: str, token: str | None = None, now: float | None = None) -> str:
    """The thumbprint of the key that signed ``proof`` for this request, else :class:`ProofError`. ``token`` given:
    the proof must carry its ``ath``. The replay cache is written last, so a proof that fails any other check never
    spends its ``jti``."""
    if not proof:
        raise ProofError("missing")
    if len(proof) > MAX_PROOF_BYTES or proof.count(".") != 2:
        raise ProofError("malformed")
    head_b64, body_b64, sig_b64 = proof.split(".")
    try:
        header = _strict_json(_b64url_decode(head_b64))
        claims = _strict_json(_b64url_decode(body_b64))
    except (ValueError, UnicodeDecodeError):
        raise ProofError("malformed") from None
    if not isinstance(header, dict) or not isinstance(claims, dict) or header.get("typ") != TYP:
        raise ProofError("malformed")
    if header.get("alg") != ALG:
        raise ProofError("unsupported")
    key, jkt = _public_key(header.get("jwk"))
    signature = _b64url_decode(sig_b64)
    if len(signature) != 64:
        raise ProofError("bad_signature")
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

    der = encode_dss_signature(int.from_bytes(signature[:32], "big"), int.from_bytes(signature[32:], "big"))
    try:
        key.verify(der, f"{head_b64}.{body_b64}".encode("ascii"), ec.ECDSA(hashes.SHA256()))
    except InvalidSignature:
        raise ProofError("bad_signature") from None
    htm, htu = claims.get("htm"), claims.get("htu")
    if not isinstance(htm, str) or not isinstance(htu, str) or htm != method.upper() or not _same_path(htu, path):
        raise ProofError("wrong_request")
    # Review B1 (2026-10-29): `iat` is a whole number of seconds and nothing else. A float, a bool, a string — and
    # above all NaN, which every comparison passes — is no time at all. NaN and ±Infinity are already refused by
    # `_strict_json`; an int is finite by construction.
    iat = claims.get("iat")
    # Bounded too: an int past 2^53 cannot meet a float clock (Python would raise OverflowError on the subtraction).
    if isinstance(iat, bool) or not isinstance(iat, int) or not 0 <= iat <= 2**53:
        raise ProofError("malformed")
    moment = time.time() if now is None else now
    if abs(moment - iat) > MAX_SKEW_S:
        raise ProofError("stale")
    jti = claims.get("jti")
    if not isinstance(jti, str) or not 8 <= len(jti) <= 128:
        raise ProofError("malformed")
    ath = claims.get("ath")
    if token is not None and (not isinstance(ath, str) or not secrets.compare_digest(ath, token_hash(token))):
        raise ProofError("wrong_token")
    if not _first_use(jkt, jti, moment):
        raise ProofError("replayed")
    return jkt


def reset() -> None:
    """Forget every cached key and seen ``jti`` (tests)."""
    with _keys_lock:
        _KEYS.clear()
    with _seen_lock:
        _SEEN.clear()


# ── The client half: what a device sends (tests, the scratch checks, and any Python client that holds a key) ────────

def public_jwk(private_key) -> dict:
    numbers = private_key.public_key().public_numbers()
    return {"kty": "EC", "crv": "P-256", "x": b64url(numbers.x.to_bytes(32, "big")),
            "y": b64url(numbers.y.to_bytes(32, "big"))}


def make_proof(private_key, method: str, url: str, *, token: str | None = None, now: float | None = None,
               jti: str | None = None) -> str:
    """A DPoP proof for one request, signed with ``private_key`` (a ``cryptography`` P-256 key)."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    header = {"typ": TYP, "alg": ALG, "jwk": public_jwk(private_key)}
    claims = {"htm": method.upper(), "htu": url, "iat": int(time.time() if now is None else now),
              "jti": jti or secrets.token_urlsafe(16)}
    if token is not None:
        claims["ath"] = token_hash(token)
    signing = (b64url(json.dumps(header, separators=(",", ":")).encode()) + "."
               + b64url(json.dumps(claims, separators=(",", ":")).encode()))
    r, s = decode_dss_signature(private_key.sign(signing.encode("ascii"), ec.ECDSA(hashes.SHA256())))
    return f"{signing}.{b64url(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"
