"""Whether this machine has a network, and whether it slept — read locally, nothing sent.

Sleep runs at night on laptops. A lid closed mid-read leaves engine calls that fail on wake, before the network is
back (2026-11-03: four ``Request timed out`` envelopes and ``Errno 51 Network is unreachable`` beside them). These two
signals let a run tell that apart from an engine that needs a fix:

- ``has_route``: a UDP socket ``connect`` to a documentation address (RFC 5737 / RFC 3849) asks the kernel for a
  route and sends no packet; with no network it fails with ``ENETUNREACH``. No fetch, no DNS, no byte on the wire.
- ``slept_s``: two monotonic clocks, one that counts while the machine sleeps and one that stops; their difference
  since a ``mark`` is the time asleep. Neither moves with the wall clock, so a time-zone change or an NTP step on
  wake is never read as a sleep.
"""
from __future__ import annotations

import socket
import time
from dataclasses import dataclass

#: Documentation-only addresses: never routed to anyone, so even a misbehaving stack has nobody to reach.
_PROBES = ((socket.AF_INET, ("192.0.2.1", 9)), (socket.AF_INET6, ("2001:db8::1", 9)))


def has_route() -> bool:
    """True when the kernel has a route off this machine (IPv4 or IPv6). Sends nothing."""
    for family, addr in _PROBES:
        try:
            sock = socket.socket(family, socket.SOCK_DGRAM)
        except OSError:
            continue
        try:
            sock.connect(addr)     # UDP connect: a route lookup only, no packet
            return True
        except OSError:
            continue
        finally:
            sock.close()
    return False


def _elapsed() -> float:
    """A monotonic clock that keeps counting while the machine sleeps."""
    if hasattr(time, "CLOCK_UPTIME_RAW"):          # macOS: CLOCK_MONOTONIC counts sleep, UPTIME_RAW does not
        return time.clock_gettime(time.CLOCK_MONOTONIC)
    if hasattr(time, "CLOCK_BOOTTIME"):            # Linux: BOOTTIME counts suspend, MONOTONIC does not
        return time.clock_gettime(time.CLOCK_BOOTTIME)
    return time.monotonic()                        # elsewhere: no sleep is ever measured


def _awake() -> float:
    """A monotonic clock that stops while the machine sleeps."""
    if hasattr(time, "CLOCK_UPTIME_RAW"):
        return time.clock_gettime(time.CLOCK_UPTIME_RAW)
    if hasattr(time, "CLOCK_BOOTTIME"):
        return time.clock_gettime(time.CLOCK_MONOTONIC)
    return time.monotonic()


@dataclass(frozen=True)
class Mark:
    elapsed: float
    awake: float


def mark() -> Mark:
    return Mark(_elapsed(), _awake())


def slept_s(since: Mark | None) -> float:
    """Seconds the machine slept since ``since`` (0 for ``None``)."""
    if since is None:
        return 0.0
    return max(0.0, (_elapsed() - since.elapsed) - (_awake() - since.awake))


def awake_s(since: Mark) -> float:
    """Seconds the machine was awake since ``since`` — a bound that time asleep never uses up."""
    return max(0.0, _awake() - since.awake)
