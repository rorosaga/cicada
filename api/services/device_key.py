"""This computer's signing key for the home's hand-off record (G132 phase 2, ruling 51a).

A hand-off record (``home_record``) is signed by the device that writes it — the old home on a move, the replica that
takes over on a take-over — and every device checks the signature against the public key that device registered in
the device registry beforehand (``device_tokens``' ``sign_jwk``, shared with every full device). The key is a P-256
key (ES256, the one curve ``device_proof`` already speaks), kept as ``$CICADA_HOME/sync/device_key.pem`` (0600),
made the first time this computer needs it.

**Why a file, not the Keychain or the Secure Enclave.** The backend writes the record, and the backend runs headless
too (a Linux server, the launchd agent with no app open): a hand-off must not wait for the app, and a Keychain item a
background process creates or reads raises the person's Keychain prompt, which nothing may do unasked. The master
token, which already lets its holder do anything on this computer, lives as a 0600 file in the same folder, so a key
beside it adds no weaker point. The app may later wrap this key in its own Keychain item (a computer's phase-4 work,
with the device-group key); the record's format does not change when it does.

Nothing about the key is ever logged, sent or put in a bank, except the public JWK the registry carries.
"""
from __future__ import annotations

import base64
import os
import threading
from pathlib import Path

FILE = "device_key.pem"
_LOCK = threading.Lock()


def _path() -> Path:
    from api.services import runtime_layout

    return runtime_layout.cicada_home() / "sync" / FILE


def _private(create: bool = True):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    path = _path()
    with _LOCK:
        try:
            return serialization.load_pem_private_key(path.read_bytes(), password=None)
        except FileNotFoundError:
            if not create:
                return None
        key = ec.generate_private_key(ec.SECP256R1())
        pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = path.with_name(f".{FILE}.{os.getpid()}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(pem)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.link(tmp, path)            # never replace a key another process made a moment ago
        except FileExistsError:
            tmp.unlink(missing_ok=True)
            return serialization.load_pem_private_key(path.read_bytes(), password=None)
        tmp.unlink(missing_ok=True)
        return key


def exists() -> bool:
    return _path().exists()


def public_jwk(create: bool = True) -> dict | None:
    """This computer's public key as a JWK (``kty``, ``crv``, ``x``, ``y``), or None when it has none and
    ``create`` is False."""
    from api.services import device_proof

    key = _private(create)
    return device_proof.public_jwk(key) if key is not None else None


def thumbprint(jwk: dict | None) -> str | None:
    from api.services import device_proof

    try:
        return device_proof.thumbprint(jwk) if jwk else None
    except Exception:  # noqa: BLE001 — a malformed key has no thumbprint
        return None


def sign(data: bytes) -> str:
    """An ES256 signature (raw r||s, base64url) over ``data`` with this computer's key."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    der = _private(True).sign(data, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    return base64.urlsafe_b64encode(r.to_bytes(32, "big") + s.to_bytes(32, "big")).rstrip(b"=").decode("ascii")


def verify(jwk: dict, data: bytes, signature: str) -> bool:
    """Is ``signature`` an ES256 signature over ``data`` by the public key ``jwk``?"""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

    try:
        if not isinstance(jwk, dict) or jwk.get("kty") != "EC" or jwk.get("crv") != "P-256":
            return False

        def num(field: str) -> int:
            raw = str(jwk[field])
            return int.from_bytes(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)), "big")

        public = ec.EllipticCurvePublicNumbers(num("x"), num("y"), ec.SECP256R1()).public_key()
        raw = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
        if len(raw) != 64:
            return False
        der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
        public.verify(der, data, ec.ECDSA(hashes.SHA256()))
        return True
    except (InvalidSignature, ValueError, KeyError, TypeError):
        return False
