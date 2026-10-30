"""The relay link: phases 1–2's sync carried end to end by the relay the person set (G132 phase 3b, ruling 51c).

Started only when a relay is set (``sync_transport.relay_url``), the bank is shared (a publishing home, or a replica)
and it is not a demo. Unset or off, nothing here is imported (``test_sync_relay_isolation``).

**One task on the backend's own event loop.** It holds one outbound websocket to the relay
(``sync_relay_client.RelayClient``), opens every frame with this device's ``Endpoint`` (membership, signature,
counter, epoch key — the same checks whichever path the bytes took), and runs what the frames ask **in process**,
through the same app and the same routes a direct request reaches: the ASGI scope carries the verified sender
(``auth.RELAY_SENDER_SCOPE`` / ``RELAY_DEVICE_SCOPE``, which no network server can set), and ``auth`` holds that device
to every rule its token would meet. No Cicada token, bank id or name ever crosses the relay.

**What travels** (network.md, "Direct first, the relay as fallback"):

* the home's commits — every new HEAD becomes one ``delta`` to every device (the bundle ``previous..HEAD``, with
  ``seq``, ``head`` and ``base`` inside the ciphertext). A device keeps a delta it receives until its follower asks
  for that base, so a copy catches up from the mailbox while the home is asleep. A device that stays away is
  **coalesced**: once :data:`COALESCE_AFTER` deltas wait for it, the home drops them at the relay (``supersede``) and
  sends one bundle from the commit that device last said it holds;
* a transaction — the outbox's ``Idempotency-Key`` write — as one ``tx`` frame to the home, applied there through
  ``idempotency.run_once`` by the route itself, and answered with a ``control`` frame;
* the status frame — the home's Sleep frame, latest-only at the relay;
* every other request (the registry, the keys, ``/sync/peer``, a pack the follower asks for) as a ``control``
  request, answered by a ``control`` reply — or by a ``delta`` / ``stream`` when the answer is a bundle;
* the group itself — pairing, enrolment, revoke (a new epoch), a hand-off (``Home.hand_off`` and the group record), a
  take-over (a new group, announced with the signed take-over record).

**State** is ``$CICADA_HOME/sync/relay-state.json`` (0600, outside every bank and git): the endpoint's keys, counters
and epoch keys, and the shared memory's id. One per computer — a computer shares one memory at a time, as the home or
as a copy, and keeps the same keys across a move (its bank folder stays, its part changes). The counter is saved
before a frame is sent; what a frame changed is saved after it was handled and before it is acknowledged. Bundles
waiting for the follower sit in ``$CICADA_HOME/sync/relay-spool`` (0700).

Logs carry kinds, sizes, counts and timings only — never a payload, a key or a path inside the bank.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
import secrets
import shutil
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from loguru import logger

from api.services.sync_relay_client import RelayClient, check_url
from api.services.sync_relay_crypto import Endpoint, Home, Keys, Refused, b64d, b64e

STATE_FILE = "relay-state.json"
SPOOL = "relay-spool"
PUSH_POLL_S = 0.5

#: With nothing changed, the status frame is rebuilt (and sent only if it differs) this often.
STATUS_IDLE_S = 300.0
#: A status frame is latest-only and small at the relay (``max_status_bytes``, 16 KiB framed).
STATUS_MAX_FRAMED = 16 * 1024
#: Deltas that may wait for one device before the home replaces them with one coalesced bundle.
COALESCE_AFTER = 4
#: A bundle larger than this is never pushed; a device asks for it (``stream``) instead.
PUSH_MAX_BYTES = 48 * 1024 * 1024
RECONNECT_MAX_S = 30.0
#: A peer that sent nothing for this long is taken to be asleep: a read asked of it waits only ``ASLEEP_WAIT_S``
#: (measured: a copy catching up from the mailbox spent ~40 s of its first minute on the registry, keys and status
#: reads it asks a sleeping home after every catch-up).
ASLEEP_AFTER_S = 90.0
#: A home re-seals its last status frame this often while nothing changed (the heartbeat above is measured against).
ALIVE_EVERY_S = 30.0
ASLEEP_WAIT_S = 1.5
#: How long a request over the relay waits for its answer before the caller hears "no answer" (it is not lost: a
#: bundle that comes later waits for the follower; a transaction's answer waits for the outbox's next try). A
#: first copy (a whole bundle) waits as long as the caller allows.
RELAY_WAIT_S = 20.0
#: The same read asked again while its first ask is unanswered waits for that answer instead of queueing another
#: copy at the relay (a follower polling a home that sleeps).
SAME_ASK_S = 600.0
#: A transaction still unanswered after this long is sent again (the relay keeps a frame at most 7 days).
TX_RESEND_S = 6 * 86_400
#: Answers to transactions kept for a resend after the caller stopped waiting (an outbox retries later).
ANSWERS_KEPT = 1000
#: Headers a request carries over the relay (never ``Authorization``) and an answer brings back.
REQUEST_HEADERS = ("content-type", "idempotency-key", "x-cicada-bank-id", "accept")
ANSWER_HEADERS = ("content-type", "x-cicada-seq", "x-cicada-head", "x-cicada-bank-id", "x-cicada-build-ms")
#: Paths a relay frame may never reach: pairing and the relay's own settings are the person's, on their screen.
DENIED_PREFIXES = ("/sync/relay", "/pair", "/devices/pairing", "/remote")

LINK: "Link | None" = None


# --- state -----------------------------------------------------------------------------------------------------------------

def _sync_folder(create: bool = True) -> Path:
    from api.services import runtime_layout

    folder = runtime_layout.cicada_home() / "sync"
    if create:
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    return folder


def state_path(memory_path=None, *, create: bool = True) -> Path:
    return _sync_folder(create) / STATE_FILE


def load_state(memory_path) -> dict | None:
    try:
        data = json.loads(state_path(memory_path, create=False).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def save_state(memory_path, data: dict) -> None:
    path = state_path(memory_path)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, path)


def spool_dir(memory_path=None) -> Path:
    path = _sync_folder() / SPOOL
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def _endpoint_from(state: dict, memory_path) -> Endpoint:
    ep = state["endpoint"]
    spool = str(spool_dir(memory_path))
    if state.get("kind") == "home" and ep.get("home") == Keys.load(ep["keys"]).ed_b64:
        return Home.from_state(ep, spool_dir=spool)
    return Endpoint.from_state(ep, spool_dir=spool)


# --- the ASGI call, in process ---------------------------------------------------------------------------------------------

async def run_in_process(app, *, sender: str, device_id: str | None, method: str, path: str, query: str,
                         headers: dict, body: bytes, spill_to: Path | None = None) -> tuple[int, dict, bytes, Path | None]:
    """Run one request through the app as the device whose verified frame carried it. ``(status, headers, body,
    file)``: an answer larger than 4 MiB (a bundle) is written to a file under ``spill_to`` instead of memory."""
    from api.services import auth

    if any(path == p or path.startswith(p + "/") for p in DENIED_PREFIXES):
        return 403, {"content-type": "application/json"}, b'{"detail":"not over the relay"}', None
    scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"}, "http_version": "1.1",
             "method": method.upper(), "scheme": "http", "path": path, "raw_path": path.encode("utf-8"),
             "query_string": (query or "").encode("latin-1"), "root_path": "",
             "headers": [(k.lower().encode("latin-1"), str(v).encode("latin-1")) for k, v in headers.items()
                         if k.lower() in REQUEST_HEADERS] + [(b"host", b"relay")],
             "client": None, "server": ("relay", 0), "state": {}, auth.RELAY_SENDER_SCOPE: sender}
    if device_id:
        scope[auth.RELAY_DEVICE_SCOPE] = device_id
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
            if out["fh"] is None and spill_to is not None and out["size"] > 4 * 1024 * 1024:
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
    finally:
        if out["fh"] is not None:
            out["fh"].close()
    keep = {k: v for k, v in out["headers"].items() if k in ANSWER_HEADERS}
    return out["status"], keep, b"".join(out["chunks"]), out["file"]


# --- the link --------------------------------------------------------------------------------------------------------------

class Link:
    def __init__(self, *, app, memory_path: Path, url: str, state: dict, loop: asyncio.AbstractEventLoop):
        self.app = app
        self.memory_path = Path(memory_path)
        self.url = check_url(url)
        self.state = state
        self.ep: Endpoint = _endpoint_from(state, memory_path)
        self.loop = loop
        self.client: RelayClient | None = None
        self.connected = asyncio.Event()
        self.task: asyncio.Task | None = None
        self._send_lock = asyncio.Lock()
        self._waiters: dict[str, asyncio.Future] = {}
        self._answers: dict[str, tuple] = {}
        self._inflight: dict[str, float] = {}
        self._asks: dict[str, tuple[float, str]] = {}
        self._awaiting: dict[str, int] = {}
        #: When a frame last came from each sender: a peer not heard from lately is asleep, so a read asked of it
        #: waits briefly (its frame still waits in the mailbox; a pushed delta or a later ask gets the answer).
        self._seen: dict[str, float] = {}
        self._control_waiters: dict[str, asyncio.Future] = {}
        self._control_lock = asyncio.Lock()
        self.pairings: dict[str, "PairingSession"] = {}
        self._committed_hw: dict[str, int] = dict(self.ep.hw)
        self._open_first: dict[tuple, int] = {}
        self._pushed: dict[str, dict] = dict(state.get("pushed") or {})
        self._recent: list[dict] = list(state.get("recent") or [])
        self._coalesced: dict[str, int] = {}
        self._status_sent: str | None = None
        self._status_raw: bytes | None = None
        self._alive_at = 0.0
        self._stopping = False
        self._counts = {"framesIn": 0, "framesOut": 0, "refused": 0, "deltasPushed": 0, "coalesced": 0,
                        "requestsServed": 0, "reconnects": 0}
        self._last_refused: str | None = None

    # -- surface ------------------------------------------------------------------------------------------------------
    def running(self) -> bool:
        return self.task is not None and not self.task.done()

    @property
    def is_home(self) -> bool:
        return isinstance(self.ep, Home) and self.ep.is_home

    def public_state(self) -> dict:
        return {"connected": self.connected.is_set(), "role": "home" if self.is_home else "device",
                "epoch": self.ep.epoch, "members": len(self.ep.members), "revoked": self.ep.revoked,
                "waiting": len(self._pushed), "pushedHead": self.state.get("pushed_head"), **self._counts,
                "lastRefused": self._last_refused}

    def _save(self) -> None:
        self.state["endpoint"] = self.ep.to_state()
        self.state["kind"] = "home" if self.is_home else "device"
        self.state["pushed"] = self._pushed
        self.state["recent"] = self._recent[-64:]
        save_state(self.memory_path, self.state)

    def start(self) -> None:
        self.task = self.loop.create_task(self._run(), name="cicada-relay-link")

    async def stop(self) -> None:
        self._stopping = True
        if self.task is not None:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self.task
        if self.client is not None:
            with contextlib.suppress(Exception):
                await self.client.close()

    # -- the connection -----------------------------------------------------------------------------------------------
    async def _run(self) -> None:
        delay = 1.0
        while not self._stopping:
            if self.ep.revoked:
                logger.info("relay: this device was removed from the group; the link stops")
                return
            create = None
            if self.is_home and not self.state.get("created"):
                async with self._send_lock:
                    create = self.ep.epoch_frame()
                    self._save()
            client = RelayClient(self.url, self.ep, create=create)
            try:
                await client.connect()
            except Refused as exc:
                code = exc.code
                if code == "unknown_mailbox" and self.is_home:
                    self.state["created"] = False         # the relay forgot this bank (purged): made again
                elif code in ("revoked", "not_member"):
                    self.ep.revoked = True
                    self._save()
                    return
                logger.info(f"relay: not admitted ({code}); trying again in {delay:.0f} s")
                await asyncio.sleep(delay)
                delay = min(delay * 2, RECONNECT_MAX_S)
                continue
            except (OSError, asyncio.TimeoutError, Exception) as exc:  # noqa: BLE001 — offline: try again
                logger.info(f"relay: not reachable ({type(exc).__name__}); trying again in {delay:.0f} s")
                await asyncio.sleep(delay)
                delay = min(delay * 2, RECONNECT_MAX_S)
                continue
            if create is not None:
                self.state["created"] = True
                self.state["posted_epoch"] = self.ep.epoch
                self._save()
            delay = 1.0
            self.client = client
            self.connected.set()
            self._counts["reconnects"] += 1
            tasks = [asyncio.create_task(self._reader(client)), asyncio.create_task(self._controls(client))]
            await self._catch_up_epoch()
            if self.is_home:
                tasks.append(asyncio.create_task(self._pusher(client)))
            try:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for t in done:
                    if t.exception() is not None and not isinstance(t.exception(), Refused):
                        logger.info(f"relay: link task ended ({type(t.exception()).__name__})")
            finally:
                self.connected.clear()
                for t in tasks:
                    t.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await t
                with contextlib.suppress(Exception):
                    await client.close()
                self.client = None
                self._rewind()
                for key, fut in list(self._waiters.items()):
                    if key.startswith("req:") and not fut.done():
                        fut.set_exception(Refused("disconnected"))
            if self._regroup_pending():
                continue
            await asyncio.sleep(0.2)

    def _rewind(self) -> None:
        """A connection dropped mid-message: what was not acknowledged comes again, so every sender's counter goes back
        to the last whole message and its unfinished parts are dropped."""
        for k in list(self.ep._partial):   # noqa: SLF001
            self.ep._drop_partial(k)       # noqa: SLF001
        for sender, hw in self._committed_hw.items():
            self.ep.hw[sender] = hw
        for sender in [s for s in self.ep.hw if s not in self._committed_hw]:
            self.ep.hw.pop(sender, None)
        self._open_first.clear()

    async def _send(self, kind: str, payload: bytes, *, meta: dict | None = None, to="*") -> int | None:
        """Seal and send one message; its counter is saved before the first byte leaves. The relay seq of its last
        part, or None when the relay refused it."""
        client = self.client
        if client is None:
            raise Refused("disconnected")
        async with self._send_lock:
            frames = self.ep.seal(kind, payload, meta=meta, to=to)
            self._save()
            answers = await client.send(frames, timeout=60)
        self._counts["framesOut"] += len(frames)
        last = answers[-1] if answers else {}
        if last.get("t") != "ok":
            self._last_refused = str(last.get("code"))
            logger.info(f"relay: a {kind} frame was refused ({last.get('code')})")
            return None
        return int(last.get("rseq") or 0)

    async def _send_stream(self, path: Path, *, meta: dict, to) -> int | None:
        client = self.client
        if client is None:
            raise Refused("disconnected")
        async with self._send_lock:
            frames = list(self.ep.seal_stream(str(path), meta=meta, to=to))
            self._save()
            answers = await client.send(frames, timeout=120)
        self._counts["framesOut"] += len(frames)
        last = answers[-1] if answers else {}
        return int(last.get("rseq") or 0) if last.get("t") == "ok" else None

    # -- the relay's own messages (one reader, so a pairing request is never swallowed by another wait) ---------------
    async def _controls(self, client: RelayClient) -> None:
        while True:
            msg = await client.control.get()
            t = msg.get("t")
            if t == "pair_req":
                asyncio.create_task(self._on_pair_req(str(msg.get("slot")), b64d(msg.get("body") or "")))
                continue
            fut = self._control_waiters.pop(str(t), None)
            if fut is not None and not fut.done():
                fut.set_result(msg)

    async def _on_pair_req(self, slot: str, body: bytes) -> None:
        await _on_pair_req(self, slot, body)

    async def _control_call(self, obj: dict, answer: str, timeout: float = 10.0) -> dict:
        client = self.client
        if client is None:
            raise Refused("disconnected")
        async with self._control_lock:
            fut = self.loop.create_future()
            self._control_waiters[answer] = fut
            await client.ws.send(json.dumps(obj))
            try:
                return await asyncio.wait_for(fut, timeout)
            finally:
                self._control_waiters.pop(answer, None)

    async def _supersede(self, dev: str, upto: int) -> int:
        got = await self._control_call({"t": "supersede", "dev": dev, "upto": upto}, "superseded")
        return int(got.get("n") or 0)

    # -- reading --------------------------------------------------------------------------------------------------------
    async def _reader(self, client: RelayClient) -> None:
        while True:
            item = await client.inbox.get()
            if item is None:
                return
            rseq, raw = item
            self._counts["framesIn"] += 1
            try:
                msg = self.ep.open(raw)
            except Refused as exc:
                msg = None
                if exc.code != "replay":
                    self._counts["refused"] += 1
                    self._last_refused = exc.code
                if exc.code == "revoked":
                    self._save()
                    logger.info("relay: this device was removed from the group")
                    return
            else:
                if msg is None and rseq and self.ep._partial:   # noqa: SLF001 — a part of a longer message
                    for k in self.ep._partial:                   # noqa: SLF001
                        self._open_first.setdefault(k, rseq)
            if msg is not None:
                # When the sender sent it, not when it arrived: the latest status the relay hands over on connect
                # says how long ago the home was last up.
                self._seen[msg.sender] = time.monotonic() - max(0.0, time.time() - float(msg.at or 0))
                k = (msg.sender, msg.ctr)
                self._open_first.pop(k, None)
                if msg.sender in self.ep.hw:
                    self._committed_hw[msg.sender] = self.ep.hw[msg.sender]
                try:
                    await self._dispatch(msg)
                except Exception as exc:  # noqa: BLE001 — one message never stops the link
                    logger.info(f"relay: a {msg.kind} message was not handled ({type(exc).__name__})")
            if not self._open_first:
                self._committed_hw.update(self.ep.hw)
            self._save()
            if rseq:
                upto = (min(self._open_first.values()) - 1) if self._open_first else rseq
                if upto > 0:
                    with contextlib.suppress(Exception):
                        await client.ack(upto)

    async def _dispatch(self, msg) -> None:
        kind = msg.kind
        if kind == "epoch":
            await self._on_epoch(msg)
        elif kind in ("delta", "stream"):
            await self._on_bundle(msg)
        elif kind == "status":
            self._on_status(msg)
        elif kind == "tx":
            if self.is_home:
                asyncio.create_task(self._serve_tx(msg))
        elif kind == "control":
            try:
                body = json.loads(msg.payload or b"{}")
            except ValueError:
                return
            t = body.get("t")
            if t == "res":
                self._resolve(str(body.get("re")), ("res", body))
            elif t == "req":
                asyncio.create_task(self._serve_req(msg.sender, body))
            elif t == "handoff":
                await self._on_handoff(body)
            elif t == "regroup":
                await self._on_regroup(msg.sender, body)

    def _resolve(self, key: str, value) -> None:
        for k in (f"req:{key}", f"tx:{key}"):
            fut = self._waiters.pop(k, None)
            if fut is not None and not fut.done():
                fut.set_result(value)
        for same, (_at, rid) in list(self._asks.items()):
            if rid == key:
                self._asks.pop(same, None)
        if value[0] == "res" and key in self._inflight:
            self._inflight.pop(key, None)
            self._answers[key] = value
            while len(self._answers) > ANSWERS_KEPT:
                self._answers.pop(next(iter(self._answers)))

    async def _on_epoch(self, msg) -> None:
        st = (msg.meta or {}).get("statement") or {}
        if self.ep.home == self.ep.me and not self.is_home:
            await self._try_take_over()
        logger.info(f"relay: membership epoch {st.get('epoch')} with {len(st.get('devices') or [])} devices")

    async def _on_bundle(self, msg) -> None:
        meta = msg.meta or {}
        folder = spool_dir(self.memory_path)
        if msg.path:
            path = Path(msg.path)
        else:
            path = folder / f"bundle-{secrets.token_hex(8)}.bundle"
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(msg.payload)
        re_ = meta.get("re")
        if re_ and self._awaiting.get(f"req:{re_}"):
            self._resolve(str(re_), ("bundle", str(path), meta))
            return
        if re_:
            self._resolve(str(re_), ("late", None, None))      # nobody waits any more: kept below, as pushed
        base = str(meta.get("base") or "")
        # A pushed delta (or a coalesced one) for the base the follower is asking for right now answers that ask: it
        # never waits behind a request the sleeping home will only answer later.
        asking = self._asks.get(f"home|GET|/sync/pack?have={base}") if base else None
        if asking is not None and self._awaiting.get(f"req:{asking[1]}"):
            self._resolve(asking[1], ("bundle", str(path), meta))
            return
        old = self._pushed.pop(base, None)
        if old:
            with contextlib.suppress(OSError):
                os.unlink(old["file"])
        self._pushed[base] = {"file": str(path), "meta": {k: meta.get(k) for k in ("seq", "head", "base",
                                                                                   "coalesced")}}
        while len(self._pushed) > 64:
            first = next(iter(self._pushed))
            with contextlib.suppress(OSError):
                os.unlink(self._pushed.pop(first)["file"])
        self._wake_follower()

    def _wake_follower(self) -> None:
        from api.services import replica

        replica.wake()

    def _on_status(self, msg) -> None:
        try:
            frame = json.loads(msg.payload)
        except ValueError:
            return
        self.state["status"] = {"at": time.time(), "frame": frame}
        from api.services import replica

        replica._set(home_frame=frame, last_contact=time.time())   # noqa: SLF001

    # -- serving -------------------------------------------------------------------------------------------------------
    def _device_for(self, sender: str) -> str | None:
        from api.services import device_tokens

        try:
            device = device_tokens.store().by_relay_key(sender)
        except Exception:  # noqa: BLE001
            return None
        return device.id if device is not None else None

    async def _serve_tx(self, msg) -> None:
        meta = msg.meta or {}
        idem = str(meta.get("idem") or "")
        try:
            req = json.loads(msg.payload)
        except ValueError:
            return
        headers = dict(req.get("headers") or {})
        headers["Idempotency-Key"] = idem
        reply = await self._execute(msg.sender, req, headers)
        reply["re"] = idem
        await self._reply(msg.sender, reply, req)

    async def _serve_req(self, sender: str, body: dict) -> None:
        reply = await self._execute(sender, body, dict(body.get("headers") or {}))
        reply["re"] = body.get("id")
        await self._reply(sender, reply, body)

    async def _execute(self, sender: str, req: dict, headers: dict) -> dict:
        self._counts["requestsServed"] += 1
        device_id = self._device_for(sender)
        path = str(req.get("path") or "/")
        try:
            payload = base64.b64decode(req.get("body") or "")
        except ValueError:
            payload = b""
        try:
            status, rheaders, body, file = await run_in_process(
                self.app, sender=sender, device_id=device_id, method=str(req.get("method") or "GET"), path=path,
                query=str(req.get("query") or ""), headers=headers, body=payload,
                spill_to=spool_dir(self.memory_path))
        except Exception as exc:  # noqa: BLE001
            logger.info(f"relay: a request was not served ({type(exc).__name__})")
            return {"t": "res", "status": 500, "headers": {}, "body": ""}
        logger.debug(f"relay: served {req.get('method')} {path} {status} for {'a device' if device_id else 'an unknown key'}")
        return {"t": "res", "status": status, "headers": rheaders, "_body": body, "_file": file}

    async def _reply(self, to: str, reply: dict, req: dict) -> None:
        body, file = reply.pop("_body", b""), reply.pop("_file", None)
        path = str(req.get("path") or "")
        try:
            # Only the relay's home may send a bundle as a delta or a stream (every device checks); an old home that is
            # still serving its last history during a hand-off answers in a control frame instead (below).
            if path == "/sync/pack" and reply.get("status") == 200 and self.is_home:
                bundle = file
                if bundle is None:
                    bundle = spool_dir(self.memory_path) / f"answer-{secrets.token_hex(8)}.bin"
                    fd = os.open(bundle, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(fd, "wb") as fh:
                        fh.write(body)
                have = (parse_qs(str(req.get("query") or "")).get("have") or [""])[0]
                h = reply.get("headers") or {}
                meta = {"re": reply.get("re"), "seq": int(h.get("x-cicada-seq") or 0), "head": h.get("x-cicada-head"),
                        "base": have, "bankId": h.get("x-cicada-bank-id"), "buildMs": h.get("x-cicada-build-ms")}
                try:
                    if have and bundle.stat().st_size <= PUSH_MAX_BYTES:
                        await self._send("delta", bundle.read_bytes(), meta=meta, to=[to])
                    else:
                        await self._send_stream(bundle, meta=meta, to=[to])
                finally:
                    with contextlib.suppress(OSError):
                        os.unlink(bundle)
                return
            if file is not None:
                try:
                    big = file.read_bytes() if file.stat().st_size <= PUSH_MAX_BYTES else None
                finally:
                    with contextlib.suppress(OSError):
                        os.unlink(file)
                reply = {**reply, "status": 413, "body": ""} if big is None else {
                    **reply, "body": base64.b64encode(big).decode("ascii")}
            else:
                reply["body"] = base64.b64encode(body or b"").decode("ascii")
            await self._send("control", json.dumps(reply).encode("utf-8"), to=[to])
        except Refused as exc:
            logger.info(f"relay: an answer was not sent ({exc.code})")

    # -- asking (called from the follower's and the outbox's threads) ----------------------------------------------------
    def request(self, method: str, path: str, *, body: bytes | None = None, headers: dict | None = None,
                timeout: float = 30.0, to_file: Path | None = None, to: str = "home"):
        from api.services.sync_transport import NO_ANSWER

        try:
            if asyncio.get_running_loop() is self.loop:
                return None, {NO_ANSWER: "unreachable"}, None   # never block the loop the link runs on
        except RuntimeError:
            pass
        fut = asyncio.run_coroutine_threadsafe(self._ask(method, path, body or b"", dict(headers or {}), timeout,
                                                         to_file, to), self.loop)
        try:
            return fut.result(timeout + 5)
        except Exception:  # noqa: BLE001
            fut.cancel()
            return None, {NO_ANSWER: "timeout"}, None

    async def _ask(self, method: str, path_q: str, body: bytes, headers: dict, timeout: float, to_file, to):
        from api.services.sync_transport import NO_ANSWER

        parts = urlsplit(path_q)
        path, query = parts.path, parts.query
        if to == "home" and method == "GET" and path == "/sync/pack":
            have = (parse_qs(query).get("have") or [""])[0]
            got = self._pushed.pop(have, None) if have else None
            if got is not None and os.path.exists(got["file"]):
                self._save()
                return self._bundle_answer(got["file"], got["meta"], to_file)
        if to == "home" and method == "GET" and path == "/sync/status":
            cached = self.state.get("status") or {}
            if cached.get("frame") and time.time() - float(cached.get("at") or 0) < 3 * STATUS_IDLE_S:
                return 200, {}, cached["frame"]
        if not self.connected.is_set():
            return None, {NO_ANSWER: "unreachable"}, None
        lower = {k.lower(): v for k, v in headers.items()}
        idem = lower.get("idempotency-key")
        req = {"method": method, "path": path, "query": query,
               "headers": {k: v for k, v in lower.items() if k in REQUEST_HEADERS and k != "idempotency-key"},
               "body": base64.b64encode(body).decode("ascii")}
        if idem and method != "GET" and to == "home":
            if idem in self._answers:
                return self._res_answer(self._answers.pop(idem)[1], to_file)
            key = f"tx:{idem}"
            fut = self._waiters.get(key)
            if fut is None or fut.done():
                fut = self.loop.create_future()
                self._waiters[key] = fut
            if idem not in self._inflight or time.time() - self._inflight[idem] > TX_RESEND_S:
                meta = {"idem": idem}
                try:
                    rseq = await self._send("tx", json.dumps(req).encode("utf-8"), meta=meta,
                                            to=self._home_route())
                except Refused as exc:
                    logger.info(f"relay: a write was not sent ({exc.code})")
                    rseq = None
                if rseq is None:
                    self._waiters.pop(key, None)
                    return None, {NO_ANSWER: "unreachable"}, None
                self._inflight[idem] = time.time()
        else:
            same = f"{to}|{method}|{path_q}" if method == "GET" else None
            earlier = self._asks.get(same) if same else None
            if earlier is not None and time.time() - earlier[0] < SAME_ASK_S \
                    and f"req:{earlier[1]}" in self._waiters:
                key = f"req:{earlier[1]}"
                fut = self._waiters[key]
            else:
                rid = secrets.token_hex(12)
                key = f"req:{rid}"
                fut = self.loop.create_future()
                self._waiters[key] = fut
                try:
                    rseq = await self._send("control", json.dumps({"t": "req", "id": rid, **req}).encode("utf-8"),
                                            to=self._home_route() if to == "home" else [to])
                except Refused as exc:
                    logger.info(f"relay: a request was not sent ({exc.code})")
                    rseq = None
                if rseq is None:
                    self._waiters.pop(key, None)
                    return None, {NO_ANSWER: "unreachable"}, None
                if same:
                    self._asks[same] = (time.time(), rid)
        first_copy = path == "/sync/pack" and not (parse_qs(query).get("have") or [""])[0]
        wait = timeout if first_copy else min(timeout, RELAY_WAIT_S)
        peer = self.ep.home if to == "home" else to
        if not key.startswith("tx:") and time.monotonic() - self._seen.get(peer, -1e9) > ASLEEP_AFTER_S:
            wait = min(wait, ASLEEP_WAIT_S)
        self._awaiting[key] = self._awaiting.get(key, 0) + 1
        try:
            got = await asyncio.wait_for(asyncio.shield(fut), wait)
        except (asyncio.TimeoutError, Refused):
            # Not lost: a pack's bundle that comes later waits for the follower, a transaction's answer for the outbox.
            logger.debug(f"relay: no answer yet to {method} {path}")
            return None, {NO_ANSWER: "timeout"}, None
        finally:
            left = self._awaiting.get(key, 1) - 1
            if left > 0:
                self._awaiting[key] = left
            else:
                self._awaiting.pop(key, None)
        if got[0] == "late":
            return None, {NO_ANSWER: "timeout"}, None
        if got[0] == "bundle":
            return self._bundle_answer(got[1], got[2], to_file)
        return self._res_answer(got[1], to_file)

    @staticmethod
    def _bundle_answer(file: str, meta: dict, to_file):
        headers = {"X-Cicada-Seq": str(meta.get("seq") or 0), "X-Cicada-Head": meta.get("head") or "",
                   "X-Cicada-Bank-Id": meta.get("bankId") or ""}
        if to_file is None:
            with contextlib.suppress(OSError):
                os.unlink(file)
            return 200, headers, None
        shutil.move(file, to_file)
        return 200, headers, to_file

    @staticmethod
    def _res_answer(body: dict, to_file):
        status = int(body.get("status") or 500)
        headers = {k.title(): v for k, v in (body.get("headers") or {}).items()}
        raw = base64.b64decode(body.get("body") or "")
        if to_file is not None and 200 <= status < 300 and status != 204:
            Path(to_file).write_bytes(raw)
            return status, headers, to_file
        if not raw:
            return status, headers, None
        try:
            return status, headers, json.loads(raw.decode("utf-8"))
        except ValueError:
            return status, headers, raw

    # -- the home pushes ----------------------------------------------------------------------------------------------
    def _home_route(self):
        """Where "the home" is for this copy's requests: the relay's home — except on a hand-off's target before it
        promotes, which the relay already counts as the home while its history still follows the old one."""
        if self.ep.home == self.ep.me and self.ep.prev_home and self.ep.prev_home in self.ep.members:
            return [self.ep.prev_home]
        return "home"

    async def _pusher(self, client: RelayClient) -> None:
        from api.services import sync_service

        from api.services.sleep_cycle import get_sleep_state

        last_status, seen = 0.0, None
        while self.is_home:
            head = sync_service.git_head(self.memory_path)
            if head and head != self.state.get("pushed_head"):
                await self._push(head)
            # The status frame is computed only when something it says may have changed (the head, Sleep's state) or
            # once a minute — an idle home costs a file read every half second, not a frame build.
            now = (head, getattr(get_sleep_state(), "status", None), getattr(get_sleep_state(), "stage", None))
            if (now != seen and time.monotonic() - last_status >= 2.0) or \
                    time.monotonic() - last_status >= STATUS_IDLE_S:
                last_status, seen = time.monotonic(), now
                await self._push_status()
            elif time.monotonic() - self._alive_at >= ALIVE_EVERY_S and self._status_raw is not None:
                # The same frame sealed again (no rebuild): latest-only at the relay, so it is a heartbeat that
                # costs one seal, never a stored frame — how a device tells a home that is up from one asleep.
                self._alive_at = time.monotonic()
                with contextlib.suppress(Refused, Exception):
                    await self._send("status", self._status_raw, to="*")
            await asyncio.sleep(PUSH_POLL_S)

    async def _push(self, head: str) -> None:
        from api.services import sync_pack, sync_publish

        if not await asyncio.to_thread(sync_publish.publishable, self.memory_path):
            return
        base = self.state.get("pushed_head")
        others = [ed for ed in self.ep.members if ed != self.ep.me]
        if not base or not others:
            self.state["pushed_head"] = head
            self._save()
            return
        try:
            pack = await asyncio.to_thread(sync_pack.build, self.memory_path, base)
        except Exception as exc:  # noqa: BLE001 — a base it cannot bundle from: devices ask for what they lack
            logger.info(f"relay: no delta pushed ({type(exc).__name__})")
            self.state["pushed_head"] = head
            self._save()
            return
        try:
            if pack.path is None:
                self.state["pushed_head"] = pack.sha or head
                self._save()
                return
            meta = {"seq": pack.seq, "head": pack.sha, "base": base}
            rseq = None
            if pack.size <= PUSH_MAX_BYTES:
                rseq = await self._send("delta", pack.path.read_bytes(), meta=meta, to="*")
            self.state["pushed_head"] = pack.sha
            if rseq:
                self._counts["deltasPushed"] += 1
                self._recent.append({"rseq": rseq, "base": base, "head": pack.sha})
            self._save()
        finally:
            pack.cleanup()
        if rseq:
            await self._coalesce(rseq)

    async def _coalesce(self, upto: int) -> None:
        """A device that stays away gets one bundle instead of a growing queue of deltas."""
        from api.services import device_tokens, sync_pack

        heads = [r["head"] for r in self._recent]
        try:
            rows = await asyncio.to_thread(device_tokens.store().list)
        except Exception:  # noqa: BLE001
            return
        for d in rows:
            if not d.active or not d.relay_ed or d.relay_ed not in self.ep.members or not d.copy_head:
                continue
            lag = len(heads) - heads.index(d.copy_head) - 1 if d.copy_head in heads else len(heads)
            since = len(heads) - self._coalesced.get(d.id, 0)
            if lag < COALESCE_AFTER or since < COALESCE_AFTER:
                continue
            client = self.client
            if client is None:
                return
            try:
                dropped = await self._supersede(d.relay_ed, upto)
            except Exception:  # noqa: BLE001
                return
            self._coalesced[d.id] = len(heads)
            if not dropped:
                continue                      # it already took them: online, just not announced yet
            try:
                pack = await asyncio.to_thread(sync_pack.build, self.memory_path, d.copy_head)
            except Exception:  # noqa: BLE001 — it asks for what it lacks when it is back
                continue
            try:
                if pack.path is not None and pack.size <= PUSH_MAX_BYTES:
                    await self._send("delta", pack.path.read_bytes(), to=[d.relay_ed],
                                     meta={"seq": pack.seq, "head": pack.sha, "base": d.copy_head, "coalesced": True})
                    self._counts["coalesced"] += 1
                    logger.info(f"relay: {dropped} deltas waiting for one device coalesced into one")
            finally:
                pack.cleanup()

    async def _push_status(self) -> None:
        from starlette.concurrency import run_in_threadpool

        from api.config import get_settings
        from api.routers import sync as sync_routes
        from api.services import sync_publish, sync_status, sync_ticker
        from api.services.sleep_cycle import get_sleep_state

        if len(self.ep.members) < 2:
            return
        settings = get_settings()
        try:
            if not await asyncio.to_thread(sync_publish.publishable, self.memory_path):
                return
            tick = await sync_ticker.current(self.memory_path, settings, max_age=sync_routes.SHARED_TICK_SECONDS)
            frame = await run_in_threadpool(sync_status.frame, self.memory_path, settings, get_sleep_state(),
                                            tick.debt, bank_id=sync_routes._bank_id(),   # noqa: SLF001
                                            bank=sync_routes._bank_name())               # noqa: SLF001
        except Exception as exc:  # noqa: BLE001
            logger.info(f"relay: no status frame ({type(exc).__name__})")
            return
        raw = json.dumps(frame, sort_keys=True, default=str).encode("utf-8")
        digest = str(hash(raw))
        if digest == self._status_sent or len(raw) > STATUS_MAX_FRAMED - 2048:
            return
        with contextlib.suppress(Refused):
            if await self._send("status", raw, to="*") is not None:
                self._status_sent = digest
                self._status_raw = raw
                self._alive_at = time.monotonic()

    # -- the group --------------------------------------------------------------------------------------------------
    def _sync(self, coro, timeout: float = 30.0):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    def enrol_sync(self, public: dict) -> dict:
        return self._sync(self.enrol(public))

    async def enrol(self, public: dict) -> dict:
        """A device of the group (already paired, its token checked by the route) joins the relay group: a new epoch,
        posted before its answer. Returns what the device needs: the mailbox, the home's keys and that epoch frame."""
        if not self.is_home:
            raise Refused("not_home")
        if public.get("ed") in self.ep.members:
            async with self._send_lock:            # already in the group: the current membership, for it alone
                frame = self.ep.epoch_frame()
                self._save()
        else:
            async with self._send_lock:
                frame = self.ep.add_device(public)
                self._save()
            await self._post_epoch(frame)
        return {"mailbox": self.ep.mailbox, "home": self.ep.keys.public(), "epochFrame": b64e(frame),
                "relay": self.url.removesuffix("/v1")}

    async def _post_epoch(self, frame: bytes) -> None:
        client = self.client
        if client is None:
            return            # posted when this home next connects (``_catch_up_epoch``)
        answers = await client.send([frame], timeout=30)
        if not answers or answers[0].get("t") != "ok":
            raise Refused(str((answers or [{}])[0].get("code") or "epoch_refused"))
        self.state["posted_epoch"] = self.ep.epoch
        self._save()

    async def _catch_up_epoch(self) -> None:
        """A membership changed while this home was not connected: the relay hears it now."""
        if not self.is_home or self.state.get("posted_epoch") == self.ep.epoch:
            return
        async with self._send_lock:
            frame = self.ep.epoch_frame()
            self._save()
        with contextlib.suppress(Refused, Exception):
            await self._post_epoch(frame)

    def revoke_sync(self, ed: str) -> bool:
        return self._sync(self.revoke(ed))

    async def revoke(self, ed: str) -> bool:
        if not self.is_home or ed not in self.ep.members or ed == self.ep.me:
            return False
        async with self._send_lock:
            frame = self.ep.revoke(ed)
            self._save()
        await self._post_epoch(frame)
        logger.info(f"relay: a device was removed; epoch {self.ep.epoch}")
        return True

    def hand_off_sync(self, new_home_ed: str) -> None:
        self._sync(self.hand_off(new_home_ed))

    async def hand_off(self, new_home_ed: str) -> None:
        """The old home's last act at the relay (phase 2's move): the membership names the target, and the group
        record goes to the target alone. From here this endpoint is an ordinary device."""
        if not self.is_home:
            return
        async with self._send_lock:
            frame, record = self.ep.hand_off(new_home_ed)
            self._save()
        await self._post_epoch(frame)
        await self._send("control", json.dumps({"t": "handoff", "record": b64e(record)}).encode("utf-8"),
                         to=[new_home_ed])
        logger.info("relay: the group was handed to the new home")

    async def _on_handoff(self, body: dict) -> None:
        self.state["handoff_record"] = body.get("record")
        self._save()
        if self.ep.home == self.ep.me and not self.is_home:
            await self._try_take_over()

    async def _try_take_over(self) -> None:
        record = self.state.get("handoff_record")
        if not record:
            return
        try:
            self.ep = Home.take_over(self.ep, b64d(record))
        except Refused as exc:
            logger.info(f"relay: the group record was refused ({exc.code})")
            return
        self.state.pop("handoff_record", None)
        self.state["created"] = True
        self._save()
        logger.info("relay: this computer holds the relay group now")
        if self.client is not None and self.task is not None:
            asyncio.create_task(self._pusher(self.client))

    def regroup_sync(self, record_data: dict) -> None:
        self._sync(self.regroup(record_data))

    async def regroup(self, record_data: dict) -> None:
        """A take-over (or a take-back): this computer starts the group again — a new mailbox, its own key as the
        root, the same devices — and tells the old group where it went, with the signed take-over record."""
        old = self.ep
        new = Home.create(keys=old.keys, clock=old.clock)
        new.spool_dir = old.spool_dir
        for ed, x in old.members.items():
            if ed != new.me:
                new.members[ed] = x
                new.joined[ed] = new.epoch
        if self.client is not None:
            with contextlib.suppress(Refused, Exception):
                await self._send("control", json.dumps({"t": "regroup", "mb": new.mailbox, "home": new.keys.public(),
                                                        "record": record_data}).encode("utf-8"), to="*")
        self.ep = new
        self.state["created"] = False
        self.state["regroup"] = True
        self.state.pop("pushed_head", None)
        self._save()
        if self.client is not None:
            with contextlib.suppress(Exception):
                await self.client.close()
        logger.info("relay: the group starts again under this computer")

    def _regroup_pending(self) -> bool:
        if self.state.pop("regroup", False):
            self._save()
            return True
        return False

    async def _on_regroup(self, sender: str, body: dict) -> None:
        """The group started again elsewhere (a take-over). Followed only when the signed take-over record verifies
        against the registry, is newer than the record this copy holds, and names the device whose relay key sent
        this notice and roots the new group."""
        from api.services import home_move, home_record

        data = body.get("record")
        new_home = body.get("home") or {}
        rec = home_record.Record(data) if isinstance(data, dict) else None
        if rec is None or new_home.get("ed") != sender or not isinstance(body.get("mb"), str):
            return
        rows = await asyncio.to_thread(home_move.registry, self.memory_path)
        row = home_move.row(rows, rec.to)
        if row is None or row.get("relay_ed") != sender:
            return
        mine = await asyncio.to_thread(home_move.record, self.memory_path)
        if mine is not None and not home_move.outranks(rec.term, rec.to, mine.term, mine.to):
            return
        peer = {"record": data, "device": rec.to, "term": rec.term}
        if not await asyncio.to_thread(home_move.verified_peer, self.memory_path, peer):
            return
        self.ep.repin(body["mb"], new_home["ed"], new_home.get("x") or "")
        self.ep.revoked = False
        self._committed_hw = {}
        self._pushed.clear()
        self.state["regroup"] = True
        self._save()
        if self.client is not None:
            with contextlib.suppress(Exception):
                await self.client.close()
        logger.info("relay: following the group the new home started")


# --- pairing over the relay, the home's side ---------------------------------------------------------------------------------

PAIR_TTL_S = 600
VOID_TEXT = "Two devices answered this code, so neither was added. Start again with a new code."


class PairingSession:
    """One "add a device" on the home's Settings → Devices: the code ``device_tokens`` issued, its QR slot (random) and
    its typed slot (Argon2id of the code), whichever a device answers first. ``state``: ``waiting`` → ``confirm`` (a
    device answered: its name, and on the typed path the six digits both screens show) → ``done`` | ``void`` (a second
    device answered: "Two devices answered this code; start again") | ``cancelled`` | ``expired``."""

    def __init__(self, link: "Link", pairing_id: str, code: str, *, typed_cost: dict | None = None):
        from api.services.sync_relay_pairing import HomePairing, random_slot, slot_for_code

        self.link = link
        self.id = pairing_id
        self.code = code
        self.started = time.time()
        self.qr = HomePairing(home=link.ep, code=code, slot=random_slot(), typed=False)
        self.typed = HomePairing(home=link.ep, code=code, slot=slot_for_code(code, **(typed_cost or {})), typed=True)
        self.answered: "HomePairing | None" = None
        self.state = "waiting"
        self.device: dict | None = None

    def by_slot(self, slot: str):
        return next((hp for hp in (self.qr, self.typed) if hp.slot == slot), None)

    def wire(self) -> dict:
        if self.state in ("waiting", "confirm") and time.time() - self.started > PAIR_TTL_S:
            self.state = "expired"
        c = self.answered.candidate if self.answered is not None else None
        out = {"id": self.id, "state": self.state, "name": c.name if c else None,
               "sas": c.sas if c else None, "typed": bool(self.answered and self.answered.typed),
               "device": self.device}
        if self.state == "void":
            out["text"] = VOID_TEXT
        return out


async def _open_slots(link: "Link", session: PairingSession) -> None:
    for hp in (session.qr, session.typed):
        got = await link._control_call({"t": "pair_open", "slot": hp.slot, "offer": b64e(hp.offer()),   # noqa: SLF001
                                        "ttl": PAIR_TTL_S}, "pair_opened")
        if got.get("slot") != hp.slot:
            raise Refused("pair_open_failed")


async def _close_slots(link: "Link", session: PairingSession) -> None:
    client = link.client
    if client is None:
        return
    for hp in (session.qr, session.typed):
        with contextlib.suppress(Exception):
            await client.pair_close(hp.slot)


async def _on_pair_req(link: "Link", slot: str, body: bytes) -> None:
    session = next((s for s in link.pairings.values() if s.by_slot(slot) is not None), None)
    if session is None or session.state not in ("waiting", "confirm"):
        return
    hp = session.by_slot(slot)
    if session.answered is not None and session.answered is not hp:
        session.state = "void"            # one device on each path: neither is added
        session.answered.void = True
        await _close_slots(link, session)
        return
    try:
        candidate, reveal = hp.receive(body)
    except Refused as exc:
        if exc.code == "pairing_void":
            session.state = "void"
            await _close_slots(link, session)
        return
    session.answered = hp
    session.state = "confirm"
    if reveal is not None and link.client is not None:
        await link.client.pair_reply(slot, reveal)
    logger.info(f"relay: a device answered a pairing code ({'typed' if hp.typed else 'scanned'})")


async def confirm_pairing(link: "Link", session: PairingSession) -> dict:
    """The person confirmed on the home (the digits match, or the named device is theirs): the code is spent through
    ``device_tokens`` (its expiry, single use), the device gets its full token and its relay keys are recorded, the
    new membership is posted, and only then the sealed welcome goes to the device."""
    from api.services import device_tokens, home_move, sync_transport

    hp = session.answered
    if session.state != "confirm" or hp is None or hp.candidate is None:
        raise Refused("not_waiting")
    device, token = await asyncio.to_thread(device_tokens.store().redeem, session.code, hp.candidate.name or "device",
                                            kind="full")
    await asyncio.to_thread(device_tokens.store().set_relay_key, device.id, hp.candidate.public["ed"],
                            hp.candidate.public["x"])
    url = await asyncio.to_thread(home_move.own_address)
    async with link._send_lock:   # noqa: SLF001
        sealed, frame = hp.welcome(token, confirmed=True, extra={"url": url, "relay": sync_transport.relay_url()})
        link._save()   # noqa: SLF001
    await link._post_epoch(frame)   # noqa: SLF001 — the membership first, then the welcome
    await link.client.pair_reply(hp.slot, sealed)
    session.state = "done"
    session.device = {"id": device.id, "name": device.name}
    await _close_slots(link, session)
    return session.wire()


# --- starting, stopping, joining --------------------------------------------------------------------------------------------

def wanted(memory_path) -> bool:
    """Whether a link should run for this bank: a relay set, the bank shared (a publishing home or a replica), and
    never a demo."""
    from api.services import demo_guard, runtime_layout, sync_publish, sync_transport

    if sync_transport.relay_url() is None:
        return False
    try:
        if demo_guard.is_demo(Path(memory_path)):
            return False
    except Exception:  # noqa: BLE001
        return False
    return runtime_layout.is_replica() or sync_publish.publishable(memory_path)


async def start(app, memory_path) -> "Link | None":
    """The backend's lifespan: start the link when :func:`wanted`. A home makes its group the first time; a replica
    that is not in the group yet enrols over the direct path (its device token, the home's ``/sync/enrol``)."""
    global LINK
    from api.services import runtime_layout, sync_transport

    url = sync_transport.relay_url()
    if url is None or not await asyncio.to_thread(wanted, memory_path):
        return None
    try:
        check_url(url)
    except Refused:
        logger.warning("relay: the relay address is not a wss:// address; the link does not start")
        return None
    state = await asyncio.to_thread(load_state, memory_path)
    if state is not None and not runtime_layout.is_replica():
        bank_id = _bank_id()
        if state.get("bankId") and bank_id and state["bankId"] != bank_id and state.get("kind") == "home":
            logger.info("relay: another memory is shared now; its group starts fresh")
            state = None
    if state is None:
        if runtime_layout.is_replica():
            state = await asyncio.to_thread(enrol_over_direct, memory_path)
            if state is None:
                logger.info("relay: this copy is not in the relay group yet; it follows directly")
                return None
        else:
            home = Home.create()
            state = {"kind": "home", "endpoint": home.to_state(), "created": False, "bankId": _bank_id()}
            await asyncio.to_thread(save_state, memory_path, state)
            await asyncio.to_thread(_register_own_keys, home.keys.public())
    link = Link(app=app, memory_path=Path(memory_path), url=url, state=state, loop=asyncio.get_running_loop())
    if link.ep.home == link.ep.me and not link.is_home:
        await link._try_take_over()      # noqa: SLF001 — promoted after a hand-off whose record arrived first
    link.start()
    LINK = link
    logger.info(f"relay: link started as the {'home' if link.is_home else 'device'}")
    return link


async def stop() -> None:
    global LINK
    link, LINK = LINK, None
    if link is not None:
        await link.stop()


def _bank_id() -> str | None:
    """The shared memory's id: the bank this request is pinned to, else the active one (a background task)."""
    from api.services import bank_registry

    pin = bank_registry.pinned_bank()
    if pin is not None and pin.id:
        return pin.id
    try:
        from api.config import get_settings

        return bank_registry._active_record(Path(get_settings().memory_root))[2] or None   # noqa: SLF001
    except Exception:  # noqa: BLE001
        return None


def _register_own_keys(public: dict) -> None:
    """The home's own relay keys on its own registry row, so the group can still map them after a move."""
    from api.services import device_tokens, home_move

    me = home_move.ensure_own_identity()
    if me:
        with contextlib.suppress(Exception):
            device_tokens.store().set_relay_key(me, public["ed"], public["x"])


def enrol_over_direct(memory_path) -> dict | None:
    """A replica joins its home's relay group over the direct path it already trusts (its device token): its keys are
    made here and only their public halves leave."""
    from api.services import replica

    keys = Keys.generate()
    try:
        status, _h, body = replica.request("POST", "/sync/enrol", body=json.dumps(keys.public()).encode(),
                                           headers={"Content-Type": "application/json"}, timeout=15)
    except replica.NoDeviceToken:
        return None
    if status != 200 or not isinstance(body, dict):
        return None
    try:
        ep = Endpoint(keys=keys, mailbox=body["mailbox"], home=body["home"]["ed"],
                      spool_dir=str(spool_dir(memory_path)))
        msg = ep.open(b64d(body["epochFrame"]))
    except (KeyError, TypeError, Refused):
        return None
    if msg is None or msg.kind != "epoch":
        return None
    state = {"kind": "device", "endpoint": ep.to_state()}
    save_state(memory_path, state)
    return state


def join_state(endpoint: Endpoint) -> None:
    """A device that paired over the relay (``sync_relay_join``) keeps the endpoint the welcome gave it."""
    save_state(None, {"kind": "device", "endpoint": endpoint.to_state()})


_THREAD_GUARD = threading.Lock()
