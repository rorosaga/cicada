"""Per-network limits on what needs no credential: creating a bank, and holding an unauthenticated socket.

- **Keyed by network, not address:** an IPv4 address is its own /32, an IPv6 address counts as its /64 (one host or
  one customer's whole prefix), an IPv4-mapped IPv6 address as its IPv4. A host that rotates through its /64 is one key.
- **O(1) at the cap:** the create table is an ``OrderedDict`` in last-touched order with a hard cap. A new key first pops
  expired windows off the front (each pop O(1), each entry popped once); if the table is still full, the create is
  refused (``busy``) rather than scanned or another network's count forgotten.
- **Only success counts:** ``allow`` reads, ``record`` writes, and the server records only after the bank was created.
- **Behind a proxy:** the peer address is the proxy's, so every client would share one key. ``RELAY_TRUSTED_PROXIES``
  (comma-separated networks, empty by default) names the proxies whose ``X-Forwarded-For`` is believed; the right-most
  entry is the one that proxy appended. From any other peer the header is ignored. With no trusted proxy, TLS should
  terminate in the relay itself (``RELAY_TLS_CERT``/``RELAY_TLS_KEY``), as the Dockerfile documents.

Addresses live here in memory only, for the counts; they are never logged or stored.
"""
from __future__ import annotations

import ipaddress
from collections import OrderedDict

WINDOW_S = 3600


def net_key(ip: str) -> str:
    try:
        addr = ipaddress.ip_address(str(ip).split("%", 1)[0])
    except ValueError:
        return "?"
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    if isinstance(addr, ipaddress.IPv6Address):
        return str(ipaddress.IPv6Network((addr, 64), strict=False))
    return str(addr)


def parse_networks(spec: str) -> list:
    out = []
    for part in (spec or "").split(","):
        part = part.strip()
        if part:
            out.append(ipaddress.ip_network(part, strict=False))
    return out


def client_ip(peer: str, headers, trusted: list) -> str:
    """The client's address: the peer's, unless the peer is a trusted proxy that appended ``X-Forwarded-For``."""
    if not trusted:
        return peer
    try:
        addr = ipaddress.ip_address(str(peer).split("%", 1)[0])
    except ValueError:
        return peer
    if not any(addr in net for net in trusted):
        return peer
    forwarded = (headers.get("X-Forwarded-For") or "") if headers is not None else ""
    last = forwarded.split(",")[-1].strip()
    try:
        ipaddress.ip_address(last)
    except ValueError:
        return peer
    return last


class CreateLimiter:
    def __init__(self, per_window: int, max_keys: int, clock):
        self.per_window = per_window
        self.max_keys = max_keys
        self.clock = clock
        self.table: OrderedDict[str, list] = OrderedDict()   # key -> [window start, count]

    def _expire_front(self, now: float) -> None:
        while self.table:
            key, (start, _count) = next(iter(self.table.items()))
            if now - start < WINDOW_S:
                return
            self.table.popitem(last=False)

    def allow(self, key: str) -> bool:
        now = self.clock()
        entry = self.table.get(key)
        if entry is not None and now - entry[0] < WINDOW_S:
            return entry[1] < self.per_window
        if entry is None and len(self.table) >= self.max_keys:
            self._expire_front(now)
            return len(self.table) < self.max_keys
        return True

    def record(self, key: str) -> None:
        now = self.clock()
        entry = self.table.get(key)
        if entry is None or now - entry[0] >= WINDOW_S:
            entry = [now, 0]
        entry[1] += 1
        self.table[key] = entry
        self.table.move_to_end(key)
        if len(self.table) > self.max_keys:
            self._expire_front(now)
            while len(self.table) > self.max_keys:     # only reachable if allow() was skipped: never grow past the cap
                self.table.popitem(last=False)
