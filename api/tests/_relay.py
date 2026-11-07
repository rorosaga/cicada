"""Shared helpers for the relay tests (G132 phase 3a): the standalone relay package is put on the path here, for the
tests only — nothing in the backend imports it (``test_sync_relay_isolation``)."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RELAY_DIR = REPO / "relay"
if str(RELAY_DIR) not in sys.path:
    sys.path.insert(0, str(RELAY_DIR))

from cicada_relay import wire  # noqa: E402
from cicada_relay.config import MiB, Config  # noqa: E402
from cicada_relay.server import Relay  # noqa: E402
from cicada_relay.store import Refused as StoreRefused, Store  # noqa: E402


class Clock:
    def __init__(self, t: float = 1_800_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


__all__ = ["Clock", "Config", "MiB", "Relay", "Store", "StoreRefused", "wire"]
