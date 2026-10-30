"""The route table, applied (G132 phase 1 B, ruling 51a): one ASGI middleware, inert unless it is needed.

* **On a replica** (``replica_guard.active()``) every request that changes something is classified by
  ``replica_routes`` before any handler runs: ``local`` runs here; ``refuse`` answers 409 ``replica_read_only``;
  ``forward`` is sent to the same route at the home (this computer's server token checked first, the app's bank name
  checked against this copy, the home's bank id named, an ``Idempotency-Key`` sent) and the home's answer comes back
  — or 503 ``home_away`` when the home is not reachable, nothing changed; ``capture`` goes through the outbox and
  answers 202 ``queued`` while the home is away. A route the table does not name is refused (fail closed). After a
  write the home took, the reply waits up to about 2 s for this copy to reach the home's head (read-your-writes).
  ``GET /sleep/status`` is the home's (§3a), with this device's outbox beside it.
* **On a home that publishes** (``sync_publish.enabled()``) a write's answer carries ``X-Cicada-Seq``, the home's head
  once it committed, so a replica knows which seq to wait for.
* **Otherwise** nothing: one environment read and one ``stat`` per request, and the request passes untouched.
"""
from __future__ import annotations

import asyncio
import json
import secrets
from urllib.parse import unquote

from starlette.routing import Match

MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
HOME_AWAY_TEXT = ("The computer that holds your memory is not reachable, so this was not changed. Reading works from "
                  "this copy; try again when that computer is back.")
HOME_UNSURE_TEXT = ("The computer that holds your memory did not answer in time, so this may or may not have been "
                    "saved there. Check before trying again.")
HOME_UNSURE_KEYED_TEXT = ("The computer that holds your memory did not answer in time, so this may or may not have "
                          "been saved there. Trying again is safe: it is sent with the same key, so it is applied "
                          "only once.")
#: A forwarded write that timed out, by what it was: its key, reused when the same write is sent again (review of #566).
_UNSURE: dict[str, tuple[str, float]] = {}
UNSURE_KEEP_S = 3600.0
QUEUED_TEXT ="Kept on this computer: it is sent to the computer that holds your memory as soon as it is reachable."
MAX_FORWARD_BYTES = 64 * 1024 * 1024


def _template(scope) -> str | None:
    app = scope.get("app")
    router = getattr(app, "router", None)
    for route in getattr(router, "routes", []) or []:
        try:
            match, _child = route.matches(scope)
        except Exception:  # noqa: BLE001
            continue
        if match == Match.FULL:
            return getattr(route, "path", None)
    return None


async def _json(send, status: int, body: dict, headers: dict | None = None) -> None:
    raw = json.dumps(body).encode("utf-8")
    hdrs = [(b"content-type", b"application/json"), (b"content-length", str(len(raw)).encode())]
    hdrs += [(k.lower().encode(), str(v).encode()) for k, v in (headers or {}).items()]
    await send({"type": "http.response.start", "status": status, "headers": hdrs})
    await send({"type": "http.response.body", "body": raw})


async def _read_body(receive, limit: int) -> bytes | None:
    chunks, size = [], 0
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            return None
        chunk = message.get("body", b"")
        size += len(chunk)
        if size > limit:
            return None
        chunks.append(chunk)
        if not message.get("more_body"):
            return b"".join(chunks)


def _header(scope, name: bytes) -> str | None:
    for k, v in scope.get("headers") or []:
        if k.lower() == name:
            return v.decode("latin-1")
    return None


def _authorized(scope) -> bool:
    from api.services import auth

    if not auth.auth_enabled():
        return True
    supplied = auth.credential(_header(scope, b"authorization"))
    return bool(supplied) and secrets.compare_digest(supplied.encode(), auth.get_token().encode())


class ReplicaRouting:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)
        from api.services import replica_guard

        if replica_guard.active():
            if await self._replica(scope, receive, send):
                return
            return await self.app(scope, receive, send)
        if scope.get("method") in MUTATING:
            from api.services import sync_publish

            if sync_publish.enabled():
                from api.services import home_move

                if home_move.writes_closed() and not _open_while_closed(scope.get("path") or ""):
                    # G132 phase 2: the home is moving (or moved): nothing is admitted here. A device's outbox and the
                    # hooks' spool keep a 503 and send it again — to the new home, once they follow it.
                    if _authorized(scope) or _device_authorized(scope):
                        await _json(send, 503, {"code": "home_moving", "detail": home_move.closed_text()})
                        return
                return await _admitted(self.app, scope, receive, send)
        return await self.app(scope, receive, send)

    async def _replica(self, scope, receive, send) -> bool:
        """True when the request was answered here (refused, forwarded, queued)."""
        from api.services import replica_routes

        method = scope.get("method", "GET")
        if method not in MUTATING:
            # A read never pays for route matching: the few the home answers are fixed paths.
            if f"{method} {scope.get('path')}" in replica_routes.GET_FROM_HOME:
                if not _authorized(scope):
                    return False   # the route's own auth answers it
                await _sleep_status(scope, send)
                return True
            return False
        template = _template(scope)
        if template is None:
            return False           # no such route: FastAPI's own 404/405
        cls = replica_routes.classify(method, template)
        if cls == replica_routes.LOCAL:
            return False
        if not _authorized(scope):
            await _json(send, 401, {"detail": "missing or invalid bearer token"})
            return True
        if cls in (None, replica_routes.REFUSE):
            from api.services import replica_guard

            await _json(send, 409, {"code": "replica_read_only", "detail": replica_guard.TEXT})
            return True
        await _forward(scope, receive, send, queue=cls == replica_routes.CAPTURE)
        return True


#: What a home that is handing off still answers: the hand-off's own routes, the device registry, cancelling Sleep, and
#: the tool door (which refuses a write itself and still answers a read).
def _open_while_closed(path: str) -> bool:
    return (path.startswith("/sync/") or path in ("/tools/call", "/sleep/cancel", "/devices")
            or path.startswith("/devices/"))


def _device_authorized(scope) -> bool:
    from api.services import auth, device_tokens

    supplied = auth.credential(_header(scope, b"authorization"))
    if not device_tokens.looks_like(supplied):
        return False
    try:
        return device_tokens.store().verify(supplied) is not None
    except Exception:  # noqa: BLE001
        return False


_NOT_JOURNALED = ("/sync/", "/sleep/", "/devices", "/banks")


async def _admitted(app, scope, receive, send) -> None:
    """A publishing home runs the write, adds ``X-Cicada-Seq``, and — for one of the app's writes the route table
    sends to the home (``forward``) — keeps it in ``admitted_log`` once it landed (G132 phase 2: what is offered back
    if this home is ever taken over while it was away)."""
    from api.services import replica_routes

    path = scope.get("path") or ""
    # Changes to the memory only: never the tool door (it keeps its own), a hand-off, Sleep's controls or devices.
    template = None if path == "/tools/call" or path.startswith(_NOT_JOURNALED) else _template(scope)
    journal = template is not None and replica_routes.classify(scope["method"], template) == replica_routes.FORWARD
    if not journal:
        return await app(scope, receive, _with_seq(scope, send))
    from api.config import get_settings
    from api.services import admitted_log, sync_log

    memory_path = get_settings().memory_path
    try:
        before = await asyncio.to_thread(sync_log.head_seq, memory_path)
    except Exception:  # noqa: BLE001
        before = None
    chunks: list[bytes] = []
    size = [0]
    status: list[int | None] = [None]

    async def tee():
        message = await receive()
        if message.get("type") == "http.request":
            chunk = message.get("body", b"")
            size[0] += len(chunk)
            if size[0] <= admitted_log.MAX_BODY:
                chunks.append(chunk)
        return message

    async def seen(message):
        if message.get("type") == "http.response.start":
            status[0] = message.get("status")
        await send(message)

    with admitted_log.tracking(memory_path) as track:
        await app(scope, tee, _with_seq(scope, seen))
    if status[0] is not None and 200 <= status[0] < 300 and size[0] <= admitted_log.MAX_BODY:
        own = (scope.get("state") or {}).get("device") is None and not scope.get("cicada.relay_device")
        await asyncio.to_thread(admitted_log.record_rest, memory_path, method=scope["method"], path=scope["path"],
                                query=scope.get("query_string", b"").decode("latin-1"), body=b"".join(chunks),
                                content_type=_header(scope, b"content-type"), seq_before=before, track=track,
                                key=(_header(scope, b"idempotency-key") or None) if own else None)


def _with_seq(scope, send):
    """Add ``X-Cicada-Seq`` (the published head once the write committed) to a home's write answer."""
    async def wrapped(message):
        if message.get("type") == "http.response.start":
            try:
                from api.config import get_settings
                from api.services import sync_log

                seq = await asyncio.to_thread(sync_log.head_seq, get_settings().memory_path)
            except Exception:  # noqa: BLE001 — a header never fails the write it describes
                seq = None
            if isinstance(seq, int):
                message = {**message, "headers": [*message.get("headers", []), (b"x-cicada-seq", str(seq).encode())]}
        await send(message)

    return wrapped


async def _forward(scope, receive, send, *, queue: bool) -> None:
    from api.services import bank_registry, replica, tx_outbox
    from api.config import get_settings

    root = get_settings().memory_root
    name, _path, bank_id = await asyncio.to_thread(bank_registry._active_record, root)  # noqa: SLF001
    asked = _header(scope, b"x-cicada-bank")
    if asked is not None and unquote(asked) != name:
        from api.services import bank_binding

        await _json(send, 409, {"code": bank_binding.CODE, "detail": bank_binding.DETAIL})
        return
    body = await _read_body(receive, MAX_FORWARD_BYTES)
    if body is None:
        await _json(send, 413, {"detail": "too large to send on"})
        return
    query = scope.get("query_string", b"").decode("latin-1")
    import hashlib
    import time

    # Review of #566: the same write sent again after a timeout reuses the key it was first sent with, so the home
    # applies it once whether or not the first one landed.
    fingerprint = hashlib.sha256(b"\0".join([scope["method"].encode(), scope["path"].encode(), query.encode(),
                                             body])).hexdigest()
    now = time.monotonic()
    for fp in [fp for fp, (_k, at) in _UNSURE.items() if now - at > UNSURE_KEEP_S]:
        _UNSURE.pop(fp, None)
    key = _header(scope, b"idempotency-key") or (_UNSURE.get(fingerprint) or (None, 0))[0]
    try:
        entry = tx_outbox.rest_entry(scope["method"], scope["path"], query, body, _header(scope, b"content-type"),
                                     bank_id=bank_id, base_seq=replica.seq(), key=key)
    except ValueError:
        await _json(send, 413, {"detail": "too large to keep for later"})
        return
    if queue:
        verdict, status, answer = await asyncio.to_thread(tx_outbox.submit, entry, replica.send)
    else:
        status, answer = await asyncio.to_thread(replica.send, entry)
        verdict = tx_outbox.verdict(entry, status, answer)
    if status is None or (queue and verdict not in ("landed", "rejected", "drop")):
        if queue:
            await _json(send, 202, {"status": "queued", "code": "queued", "detail": QUEUED_TEXT, "id": entry["id"]})
        elif (answer or {}).get("_noAnswer") == "timeout":
            from api.services import idempotency

            _UNSURE[fingerprint] = (entry["id"], time.monotonic())
            keyed = scope["path"] in idempotency.LONG_ROUTES
            await _json(send, 503, {"code": "home_unsure", "detail": HOME_UNSURE_KEYED_TEXT if keyed
                                    else HOME_UNSURE_TEXT, "idempotencyKey": entry["id"]},
                        headers={"Idempotency-Key": entry["id"]})
        else:
            await _json(send, 503, {"code": "home_away", "detail": HOME_AWAY_TEXT})
        return
    _UNSURE.pop(fingerprint, None)
    answer = dict(answer or {})
    home_seq = answer.pop("_cicadaSeq", None)
    if verdict == "landed":
        await asyncio.to_thread(replica.wait_for_seq, home_seq)
    answer.pop("raw", None)
    await _json(send, status, answer)


async def _sleep_status(scope, send) -> None:
    from api.services import replica, sync_status

    try:
        status, _h, body = await asyncio.to_thread(replica.request, "GET", "/sleep/status", timeout=5)
    except replica.NoDeviceToken:
        status, body = None, None   # fail closed: nothing sent without this copy's own device token
    outbox = await asyncio.to_thread(sync_status.outbox_counts)
    if status == 200 and isinstance(body, dict):
        await _json(send, 200, {**body, "outbox": outbox, "replica": replica.state()})
        return
    await _json(send, 503, {"code": "home_away", "detail": HOME_AWAY_TEXT, "sleep": replica.home_sleep(),
                            "outbox": outbox, "replica": replica.state()})
