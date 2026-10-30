"""Where this backend listens, and where the person's other devices reach it directly (G132 phase 3b): shown, never
widened.

**The bind.** The backend binds ``127.0.0.1`` only — unchanged by this phase. Nothing here opens a socket. Another
device reaches it directly at the address the person already configured: their tailnet (``tailscale serve``, TLS
ending on this computer and forwarding to loopback — Settings → Devices' one-click step) or ``CICADA_DEVICE_URL`` (a
TLS proxy of their own). Every such address is ``https`` (``runtime_layout``'s rule: plain ``http`` only to
loopback), so a device token never crosses a network in the clear.

**Why no LAN listener in this build.** A listener on the LAN address itself would serve the API over plain HTTP (no
certificate a peer could check), and a token sent to it would cross the LAN in the clear — what the ``https`` rule
exists to stop. The way to have one is a self-signed certificate whose fingerprint the device's registered key signs
(the discovery hello already carries that signature) and that the peer pins; that is a new listening surface, so it
is listed for the owner (report, "Needs the owner") rather than built.

**What discovery advertises.** Only an address the person configured that is ``https`` on a private literal IP of
this network (RFC 1918, the tailnet's shared range, IPv6 unique-local) — never a public address, a wildcard, loopback
or a name resolved here. With none, the app only browses.
"""
from __future__ import annotations

import ipaddress
import os
from urllib.parse import urlsplit

DEVICE_URL_ENV = "CICADA_DEVICE_URL"
TAILNET_V4 = ipaddress.ip_network("100.64.0.0/10")
#: RFC 1918, the tailnet's shared range, and IPv6 unique-local (which holds the tailnet's IPv6 range) — named here,
#: never ``is_private`` (Python counts documentation and benchmarking ranges as private too).
PRIVATE_NETS = tuple(ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")) + (
    TAILNET_V4, ipaddress.ip_network("fc00::/7"))


def plan(environ=os.environ, *, backend_port: int) -> tuple[str, int] | None:
    """``(host, port)`` discovery may advertise: the person's ``CICADA_DEVICE_URL`` when it is ``https`` on a private
    literal address with a port other than the backend's loopback one; else None."""
    raw = (environ.get(DEVICE_URL_ENV) or "").strip()
    if not raw:
        return None
    try:
        parts = urlsplit(raw)
        host, port = parts.hostname, parts.port or (443 if parts.scheme == "https" else None)
    except ValueError:
        return None
    if parts.scheme != "https" or not host or not port or port == backend_port:
        return None
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return None          # a name: whatever serves it is the person's; never resolved here
    if addr.is_unspecified or addr.is_loopback or addr.is_link_local or addr.is_multicast:
        return None
    if not any(addr in net for net in PRIVATE_NETS if net.version == addr.version):
        return None
    return str(addr), int(port)


def bound() -> tuple[str, int] | None:
    from api.config import get_settings

    return plan(backend_port=get_settings().port)


def wire() -> dict:
    from api.config import get_settings
    from api.services import home_move

    port = get_settings().port
    try:
        reached = home_move.own_address()
    except Exception:  # noqa: BLE001
        reached = None
    host = urlsplit(reached).hostname if reached else None
    return {"listening": f"127.0.0.1:{port}", "loopbackOnly": True, "reachedAt": host,
            "text": (f"Cicada listens on this computer only (127.0.0.1:{port}). Your other devices reach it at "
                     f"{host}, the address you set up." if host else
                     f"Cicada listens on this computer only (127.0.0.1:{port}). Your other devices reach it through "
                     f"the relay, or once you share it on your private network.")}
