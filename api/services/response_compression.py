"""Compress API responses only for a client on another machine (2026-10-16 perf, owner decision 3).

The app's cold hydration is ~92 % ``/graph`` (10.5 MB at owner scale; gzip level 1 makes it ~0.9 MB in ~20 ms). On one
Mac the bytes cross loopback, where compressing them costs CPU and saves nothing, so a local client is answered exactly
as before. A client of a headless server (G181) crosses a network, so its responses are gzipped at level 1 — the fast
level; Starlette's default 9 costs several times the CPU for a few percent more.

**Who is another machine** — decided from the request alone, before the route runs:

- the peer address is not loopback (a server reached directly on an overlay address);
- a proxy forwarded it (``X-Forwarded-For``, ``Forwarded``, ``X-Real-IP`` or a ``Tailscale-User-Login`` header) — how
  ``tailscale serve`` in front of ``127.0.0.1`` delivers a tailnet client's request;
- it is signed with a per-device token (``device_tokens``, ruling 28): a device is by definition another machine,
  which also covers an SSH tunnel, whose requests arrive from loopback with no header.

A wrong guess costs only CPU or bytes, never correctness: the client asked for gzip in ``Accept-Encoding`` or it gets
none. ETags are untouched (the body's digest is computed by the route before compression), and a 304 has no body. The
SSE stream (``text/event-stream``) is never buffered or compressed, nor is a body that is already compressed (images,
video, audio, PDF, archives) or one under ``MINIMUM_SIZE``.
"""
from __future__ import annotations

import ipaddress

from starlette.datastructures import Headers
from starlette.middleware.gzip import GZipResponder
from starlette.types import ASGIApp, Message, Receive, Scope, Send

#: zlib level 1: ~11x on the owner-scale `/graph` in ~20 ms.
COMPRESS_LEVEL = 1
#: Below this a response is sent as it is (a header costs more than it saves).
MINIMUM_SIZE = 1024
#: Bodies that are compressed already: gzip would spend CPU to make them bigger.
_ALREADY_COMPRESSED = ("image/", "video/", "audio/", "application/pdf", "application/zip", "application/gzip",
                       "application/x-gzip", "font/woff")
_FORWARDING_HEADERS = ("x-forwarded-for", "forwarded", "x-real-ip", "tailscale-user-login")


def _is_loopback(host: str | None) -> bool:
    if not host:
        return True   # no peer (an in-process test client, a unix socket): this machine
    if host in ("localhost", "testclient"):
        return True
    try:
        addr = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return addr.is_loopback


def is_remote(scope: Scope) -> bool:
    """True when this request came from another machine (see the module docstring)."""
    client = scope.get("client")
    if not _is_loopback(client[0] if client else None):
        return True
    headers = Headers(scope=scope)
    if any(name in headers for name in _FORWARDING_HEADERS):
        return True
    authorization = headers.get("authorization", "")
    if authorization[:7].lower() == "bearer ":
        from api.services import device_tokens

        return device_tokens.looks_like(authorization[7:].strip())
    return False


class _Responder(GZipResponder):
    """Starlette's responder, also passing through a body that is compressed already."""

    async def send_with_compression(self, message: Message) -> None:
        if message["type"] == "http.response.start":
            await super().send_with_compression(message)
            if Headers(raw=message["headers"]).get("content-type", "").startswith(_ALREADY_COMPRESSED):
                self.content_type_is_excluded = True
            return
        await super().send_with_compression(message)


class RemoteGZipMiddleware:
    """gzip (level :data:`COMPRESS_LEVEL`) for a client on another machine that accepts it; everything else untouched."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (scope["type"] == "http" and "gzip" in Headers(scope=scope).get("accept-encoding", "")
                and is_remote(scope)):
            await _Responder(self.app, MINIMUM_SIZE, compresslevel=COMPRESS_LEVEL)(scope, receive, send)
            return
        await self.app(scope, receive, send)
