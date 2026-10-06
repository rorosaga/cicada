#!/usr/bin/env python3
"""Ed25519 signatures for release archives (G182).

The release workflow signs `Cicada-x.y.z.zip` with the private key in the
CICADA_UPDATE_SIGNING_KEY secret (PEM, PKCS#8); the app verifies with the
public key embedded in its Info.plist (`CicadaUpdatePublicKey`, the raw 32
bytes in base64) through CryptoKit's Curve25519.Signing before it installs
anything. The signature covers the archive's exact bytes.

    sign_update.py sign <file>                 # key PEM from $CICADA_UPDATE_SIGNING_KEY; prints base64
    sign_update.py verify <file> <sig-b64>     # public key from scripts/release/update-public-key.txt
    sign_update.py public-key                  # the base64 raw public key of $CICADA_UPDATE_SIGNING_KEY

Needs `cryptography` (CI runs it with `uv run --with cryptography`). Never prints the private key.
"""
from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

PUBLIC_KEY_FILE = Path(__file__).resolve().parent / "update-public-key.txt"


def _private_key() -> Ed25519PrivateKey:
    pem = os.environ.get("CICADA_UPDATE_SIGNING_KEY", "").strip()
    if not pem:
        sys.exit("CICADA_UPDATE_SIGNING_KEY is not set")
    key = serialization.load_pem_private_key(pem.encode(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        sys.exit("CICADA_UPDATE_SIGNING_KEY is not an Ed25519 key")
    return key


def _raw_public(key: Ed25519PublicKey) -> str:
    raw = key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "sign":
        print(base64.b64encode(_private_key().sign(Path(argv[1]).read_bytes())).decode())
        return 0
    if len(argv) >= 3 and argv[0] == "verify":
        raw = base64.b64decode(PUBLIC_KEY_FILE.read_text().strip())
        try:
            Ed25519PublicKey.from_public_bytes(raw).verify(base64.b64decode(argv[2]), Path(argv[1]).read_bytes())
        except Exception:
            print("signature does NOT verify", file=sys.stderr)
            return 1
        print("signature verifies")
        return 0
    if argv[:1] == ["public-key"]:
        print(_raw_public(_private_key().public_key()))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
