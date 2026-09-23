"""One rule for "may Cicada fetch this URL?" (G135 R-R10).

Every server-side fetch of a URL someone else chose goes through here:
``media_ingestor._enrich_opengraph`` (a save), and ``link_enrichment``'s two
page fetchers (the Sleep-tail backfill and the live summarizer), which later
fetch whatever a save put in the bank. Before G135 none of them checked where a
URL pointed. With a remote connector, ``cicada_save_url`` would otherwise let
anyone holding a link make this Mac fetch its own LAN, its loopback services
(the ngrok inspector on 4040, the backend on 8000) or a tailnet peer, then read
the fetched title back as a media page.

The rule is ``is_global`` (and not multicast), never ``is_private``: the
carrier-grade range ``100.64.0.0/10`` — where Tailscale hands out addresses —
is neither private nor global in CPython 3.12 (measured), so a private-only
check waves every tailnet peer through. That gap was in G59's logo guard too,
which is why ``logo_service`` now asks this module. An IPv4-mapped IPv6 literal
is judged by the IPv4 it maps. An unresolvable host is refused: a fetcher never
proceeds on a host it cannot place.

A coroutine calls ``is_fetchable_url_async``: ``socket.getaddrinfo`` blocks,
and every fetcher here is ``async`` on the backend's one event loop (the app's
paste reaches ``_enrich_opengraph`` through ``POST /sources/save``), so the
lookup runs in a worker thread — httpx resolves off-loop for the same reason.

Known and accepted (G59's posture): the check resolves a name and the HTTP
client resolves it again to connect, so a DNS answer that changes in between
(rebinding) is not caught here. The fetchers never send cookies or
credentials and read only a page's title and description.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import Callable
from urllib.parse import urlparse

Resolver = Callable[[str], list[str]]


class UnsafeURL(Exception):
    """Raised by ``httpx_request_guard``; each fetcher turns it into its own
    ordinary failure result."""


def _resolve_host(host: str) -> list[str]:
    """Every address ``host`` resolves to; ``[]`` when it does not resolve.
    Module-level so the suite can stand a public address in for DNS
    (``conftest._default_public_net_guard_resolver``)."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return []
    return sorted({info[4][0] for info in infos})


def is_public_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(str(value).split("%", 1)[0])
    except ValueError:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    return bool(ip.is_global) and not ip.is_multicast


def is_fetchable_url(url: str, *, resolver: Resolver | None = None) -> bool:
    try:
        parsed = urlparse(str(url))
        host = parsed.hostname
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https") or not host:
        return False
    try:
        ipaddress.ip_address(host)
    except ValueError:
        addresses = (resolver or _resolve_host)(host)
        return bool(addresses) and all(is_public_ip(a) for a in addresses)
    return is_public_ip(host)


async def is_fetchable_url_async(url: str) -> bool:
    """``is_fetchable_url`` for a coroutine — never a blocking DNS lookup on
    the event loop (see the module docstring)."""
    return await asyncio.to_thread(is_fetchable_url, url)


async def httpx_request_guard(request) -> None:
    """``event_hooks={"request": [httpx_request_guard]}`` — httpx calls it for
    the first request AND for every redirect hop (``_send_handling_redirects``),
    so a public page cannot bounce a fetcher inward."""
    if not await is_fetchable_url_async(str(request.url)):
        raise UnsafeURL("refused a non-public address")
