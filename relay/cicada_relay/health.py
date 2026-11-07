"""``python -m cicada_relay.health``: the container's healthcheck. Asks this relay's own ``/healthz`` on loopback (over
TLS when the relay terminates its own name; the certificate is for that name, not for loopback, so it is not
verified here) and exits 0 only on ``ok``."""
from __future__ import annotations

import ssl
import sys
import urllib.request

from .config import Config


def main() -> int:
    cfg = Config.from_env()
    tls = bool(cfg.tls_cert and cfg.tls_key)
    ctx = None
    if tls:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    url = f"{'https' if tls else 'http'}://127.0.0.1:{cfg.port}/healthz"
    try:
        with urllib.request.urlopen(url, timeout=4, context=ctx) as resp:
            return 0 if resp.read().strip() == b"ok" else 1
    except OSError:
        return 1


if __name__ == "__main__":
    sys.exit(main())
