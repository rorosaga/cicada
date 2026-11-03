"""One request run through the app in process, as a device a carrier already verified (G132 phase 3b).

Two carriers bring a device's request without an HTTP connection to the backend: the relay link (a sealed frame the
relay carried, ``sync_relay_link``) and the home-network door (``sync_door``, ruling 51f D3). Both run the request
here, through the same app and the same routes a direct request reaches. The ASGI scope carries who sent it under keys
no network server can set (``auth.RELAY_SENDER_SCOPE`` — the relay signing key; ``auth.RELAY_DEVICE_SCOPE`` — the
device row, held by ``auth`` to every rule its token would meet; ``auth.DOOR_DEVICE_SCOPE`` — the device the door's
handshake proved). No token ever travels with it.

Stdlib and ``auth`` only: importing this imports nothing relay-side (``test_sync_relay_isolation``).
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import secrets
from pathlib import Path

#: Headers a carried request keeps (never ``Authorization``) and an answer brings back.
REQUEST_HEADERS = ("content-type", "idempotency-key", "x-cicada-bank-id", "accept")
ANSWER_HEADERS = ("content-type", "x-cicada-seq", "x-cicada-head", "x-cicada-bank-id", "x-cicada-build-ms")
#: Paths a carried request may never reach: pairing, the relay's own settings and the remote connector are the
#: person's, on their screen.
DENIED_PREFIXES = ("/sync/relay", "/pair", "/devices/pairing", "/remote")
#: An answer larger than this is written to a file instead of held in memory (a bundle).
SPILL_AFTER = 4 * 1024 * 1024


def denied(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") for p in DENIED_PREFIXES)


async def run_in_process(app, *, sender: str | None, device_id: str | None, method: str, path: str, query: str,
                         headers: dict, body: bytes, spill_to: Path | None = None,
                         door_device: str | None = None) -> tuple[int, dict, bytes, Path | None]:
    """Run one request through the app as the device whose verified frame carried it. ``(status, headers, body,
    file)``: an answer larger than :data:`SPILL_AFTER` is written to a file under ``spill_to`` instead of memory."""
    from api.services import auth

    if denied(path):
        return 403, {"content-type": "application/json"}, b'{"detail":"not over this path"}', None
    scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"}, "http_version": "1.1",
             "method": method.upper(), "scheme": "http", "path": path, "raw_path": path.encode("utf-8"),
             "query_string": (query or "").encode("latin-1"), "root_path": "",
             "headers": [(k.lower().encode("latin-1"), str(v).encode("latin-1")) for k, v in headers.items()
                         if k.lower() in REQUEST_HEADERS] + [(b"host", b"relay")],
             "client": None, "server": ("relay", 0), "state": {}}
    if sender:
        scope[auth.RELAY_SENDER_SCOPE] = sender
    if device_id:
        scope[auth.RELAY_DEVICE_SCOPE] = device_id
    if door_device:
        scope[auth.DOOR_DEVICE_SCOPE] = door_device
    sent = {"body": False}

    async def receive():
        if sent["body"]:
            await asyncio.sleep(3600)
            return {"type": "http.disconnect"}
        sent["body"] = True
        return {"type": "http.request", "body": body or b"", "more_body": False}

    out = {"status": 500, "headers": {}, "chunks": [], "size": 0, "file": None, "fh": None}

    async def send(message):
        if message["type"] == "http.response.start":
            out["status"] = message["status"]
            out["headers"] = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in message.get("headers", [])}
        elif message["type"] == "http.response.body":
            chunk = message.get("body", b"")
            out["size"] += len(chunk)
            if out["fh"] is None and spill_to is not None and out["size"] > SPILL_AFTER:
                path_ = spill_to / f"answer-{secrets.token_hex(8)}.bin"
                out["file"] = path_
                out["fh"] = open(os.open(path_, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb")
                out["fh"].write(b"".join(out["chunks"]))
                out["chunks"] = []
            if out["fh"] is not None:
                out["fh"].write(chunk)
            else:
                out["chunks"].append(chunk)

    try:
        await app(scope, receive, send)
    except BaseException:
        if out["fh"] is not None:
            out["fh"].close()
            out["fh"] = None
        if out["file"] is not None:
            with contextlib.suppress(OSError):
                os.unlink(out["file"])           # a request that failed part way leaves no spill behind
        raise
    finally:
        if out["fh"] is not None:
            out["fh"].close()
    keep = {k: v for k, v in out["headers"].items() if k in ANSWER_HEADERS}
    return out["status"], keep, b"".join(out["chunks"]), out["file"]
