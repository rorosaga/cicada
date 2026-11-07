"""Third-party code Cicada carries as source, each with its licence and the reason it is here (README in each folder).

* ``pyaes`` 1.6.1 (MIT, Richard Moore) — Telethon imports it unconditionally, but PyPI has only its sdist, and the
  release backend installs wheels only, hash-checked (``scripts/release/build-backend.sh``; #504 review B5). Copied
  byte for byte from ``pyaes-1.6.1.tar.gz`` (sha256 ``02c1b1405c38d3c370b085fb952dd8bea3fadcee6411ad99f312cc129c536d8f``,
  PyPI's own digest) and loaded under its own name only when Telegram is connected (`telegram_port.load_telethon`).
  It is the fallback: ``cryptg`` (a hashed wheel) does the AES when present, as it is in a release.
"""
