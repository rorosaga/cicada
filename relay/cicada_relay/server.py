"""The relay: devices dial out, authenticate per device, and meet at their bank's mailbox (G132 phase 3a).

The relay knows a bank only by an opaque mailbox id and its members' public keys, from the latest membership statement
the bank's home signed. It verifies signatures and mints nothing: no Cicada token ever reaches it. It stores and
forwards whole frames it cannot open, fans them out to the bank's online devices, keeps the latest status frame per
sender, tells a device what is still on its way per sending device (ruling 51d), and routes the pairing slots.

Protocol (one websocket at ``/v1``; text messages are JSON control, binary messages are frames):

    relay  -> {"t":"challenge","nonce":b64}
    device -> {"t":"hello","mb":id,"dev":ed,"sig":b64[,"create":b64 epoch frame]}   | {"t":"pair","slot":id}
    relay  -> {"t":"welcome","epoch":n,"home":ed,"pending":{ed:n},"dropped":n}
              then binary deliveries: u64 relay seq || frame (0 for the membership and status frames)
    device -> binary frame                      relay -> {"t":"ok","ctr":n,"rseq":n} | {"t":"refused","ctr":n,"code":c}
    device -> {"t":"ack","upto":rseq}         | {"t":"counts"} -> {"t":"counts","pending":{ed:n}}
    home   -> {"t":"supersede","dev":ed,"upto":rseq} -> {"t":"superseded","dev":ed,"n":n}   (coalescing deltas)
    home   -> {"t":"pair_open","slot":id,"offer":b64,"ttl":s} | {"t":"pair_reply","slot":id,"body":b64}
              | {"t":"pair_close","slot":id}                  relay -> {"t":"pair_req","slot":id,"body":b64}
    pairing device -> {"t":"pair_send","body":b64}           relay -> {"t":"pair_offer"|"pair_reply",...}

Logs carry hashed ids, sizes, counts and timings only: never a body, a key, an address or a slot.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import http
import json
import logging
import secrets
import ssl
import struct
import time

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from . import wire
from .config import Config
from .store import Refused, Store

log = logging.getLogger("cicada_relay")


def tag(value: str) -> str:
    """A short, stable, non-reversible label for a log line."""
    return hashlib.sha256(str(value).encode()).hexdigest()[:8]


class Conn:
    def __init__(self, ws, mb: str, dev: str):
        self.ws = ws
        self.mb = mb
        self.dev = dev
        self.sent_upto = 0
        self.lock = asyncio.Lock()


class Relay:
    def __init__(self, config: Config | None = None, clock=time.time):
        self.config = config or Config.from_env()
        self.clock = clock
        self.store = Store(self.config.db_path, self.config, clock)
        self.online: dict[str, dict[str, Conn]] = {}
        self.pair_waiters: dict[str, object] = {}
        self.unauthenticated = 0
        self._unauth_by_ip: dict[str, int] = {}
        self._creates: dict[str, list[float]] = {}
        self._server = None
        self._purger: asyncio.Task | None = None

    # -- lifecycle ----------------------------------------------------------------------------------------------
    def _ssl(self):
        if not (self.config.tls_cert and self.config.tls_key):
            return None
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(self.config.tls_cert, self.config.tls_key)
        return ctx

    @staticmethod
    def _http(connection, request):
        if request.path == "/healthz":
            return connection.respond(http.HTTPStatus.OK, "ok\n")
        if request.path != "/v1":
            return connection.respond(http.HTTPStatus.NOT_FOUND, "not found\n")
        return None

    async def start(self):
        cfg = self.config
        self._server = await serve(self._handle, cfg.host, cfg.port, process_request=self._http,
                                   max_size=cfg.max_frame_bytes + 64 * 1024, ssl=self._ssl(),
                                   ping_interval=20, ping_timeout=20, server_header=None)
        self._purger = asyncio.create_task(self._purge_loop())
        return self

    @property
    def port(self) -> int:
        return self._server.sockets[0].getsockname()[1]

    async def stop(self):
        if self._purger:
            self._purger.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._purger
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        self.store.close()

    async def _purge_loop(self):
        while True:
            await asyncio.sleep(self.config.purge_interval_s)
            self.purge()

    def purge(self) -> dict:
        out = self.store.purge(online=set(self.online))
        if any(out.values()):
            log.info("purge frames=%d status=%d slots=%d banks=%d", out["frames"], out["status"], out["slots"],
                     out["banks"])
        return out

    # -- connections --------------------------------------------------------------------------------------------
    @staticmethod
    def _ip(ws) -> str:
        addr = getattr(ws, "remote_address", None)
        return str(addr[0]) if addr else "?"

    def _may_create(self, ip: str) -> bool:
        now = self.clock()
        recent = [t for t in self._creates.get(ip, []) if now - t < 3600]
        if len(recent) >= self.config.creates_per_ip_per_hour:
            self._creates[ip] = recent
            return False
        self._creates[ip] = recent + [now]
        if len(self._creates) > 100_000:      # bounded: forget the quietest addresses
            for k in [k for k, v in self._creates.items() if not v or now - v[-1] >= 3600]:
                del self._creates[k]
        return True

    async def _handle(self, ws):
        ip = self._ip(ws)
        if (self.unauthenticated >= self.config.max_unauthenticated
                or self._unauth_by_ip.get(ip, 0) >= self.config.max_unauthenticated_per_ip):
            await ws.close(1013, "busy")
            return
        self.unauthenticated += 1
        self._unauth_by_ip[ip] = self._unauth_by_ip.get(ip, 0) + 1
        authed = False

        def release():
            self.unauthenticated -= 1
            left = self._unauth_by_ip.get(ip, 1) - 1
            if left > 0:
                self._unauth_by_ip[ip] = left
            else:
                self._unauth_by_ip.pop(ip, None)
        try:
            nonce = secrets.token_bytes(32)
            await ws.send(json.dumps({"t": "challenge", "nonce": wire.b64e(nonce)}))
            try:
                first = json.loads(await asyncio.wait_for(ws.recv(), self.config.handshake_timeout_s))
            except (asyncio.TimeoutError, ValueError, TypeError):
                await ws.close(4400, "handshake")
                return
            if not isinstance(first, dict):
                await ws.close(4400, "handshake")
                return
            if first.get("t") == "pair":
                await self._pair_device(ws, first)
                return
            conn = await self._hello(ws, first, nonce, ip)
            if conn is None:
                return
            release()
            authed = True
            await self._serve(conn)
        except ConnectionClosed:
            pass
        finally:
            if not authed:
                release()

    async def _error(self, ws, code: str, close_code: int = 4400):
        with contextlib.suppress(ConnectionClosed):
            await ws.send(json.dumps({"t": "error", "code": code}))
            await ws.close(close_code, code)

    async def _hello(self, ws, msg: dict, nonce: bytes, ip: str = "?") -> Conn | None:
        mb, dev, sig = msg.get("mb"), msg.get("dev"), msg.get("sig")
        if (msg.get("t") != "hello" or not isinstance(mb, str) or not wire.MAILBOX_RE.match(mb)
                or not isinstance(dev, str) or not wire.KEY_RE.match(dev) or not isinstance(sig, str)):
            await self._error(ws, "bad_hello")
            return None
        if not wire.verify_auth(dev, mb, nonce, sig):
            await self._error(ws, "bad_auth", 4401)
            return None
        bank = self.store.bank(mb)
        if bank is None:
            if not msg.get("create"):
                await self._error(ws, "unknown_mailbox", 4404)
                return None
            if not self._may_create(ip):
                log.info("create refused: rate")
                await self._error(ws, "rate_limited", 1013)
                return None
            try:
                frame = wire.parse(wire.b64d(msg["create"]))
                st = wire.epoch_statement(frame)
                if frame.kind != "epoch" or frame.sender != st["home"] or dev != st["home"]:
                    raise wire.WireError("bad_epoch")
                wire.verify(frame)
                self.store.create_bank(mb, st, frame.raw, frame.header["ctr"])
            except (wire.WireError, Refused) as exc:
                await self._error(ws, exc.code)
                return None
            log.info("bank created mb=%s devices=%d", tag(mb), len(st["devices"]))
            bank = self.store.bank(mb)
        elif not self.store.is_member(mb, dev):
            await self._error(ws, "not_member", 4403)
            return None
        peers = self.online.setdefault(mb, {})
        if dev not in peers and len(peers) >= self.config.max_connections_per_bank:
            await self._error(ws, "too_many_connections", 1013)
            return None
        old = peers.get(dev)
        conn = Conn(ws, mb, dev)
        peers[dev] = conn
        if old is not None:
            with contextlib.suppress(ConnectionClosed):
                await old.ws.close(4409, "replaced")
        self.store.touch(mb)
        await ws.send(json.dumps({"t": "welcome", "epoch": bank["epoch"], "home": bank["home"],
                                  "pending": self.store.counts(mb), "dropped": self.store.take_dropped(mb, dev)}))
        await ws.send(struct.pack(">Q", 0) + bank["epoch_frame"])
        for raw in self.store.statuses(mb, exclude=dev):
            await ws.send(struct.pack(">Q", 0) + raw)
        if dev == bank["home"]:
            for slot in self.store.slots_of(mb):
                for body in self.store.take_slot_msgs(slot, "to_home"):
                    await ws.send(json.dumps({"t": "pair_req", "slot": slot, "body": wire.b64e(body)}))
        log.info("connect mb=%s dev=%s", tag(mb), tag(dev))
        return conn

    async def _serve(self, conn: Conn):
        try:
            await self._flush(conn)
            async for message in conn.ws:
                if isinstance(message, bytes):
                    await self._on_frame(conn, message)
                else:
                    await self._on_control(conn, message)
        finally:
            peers = self.online.get(conn.mb, {})
            if peers.get(conn.dev) is conn:
                del peers[conn.dev]
                if not peers:
                    self.online.pop(conn.mb, None)
            self.store.touch(conn.mb)
            log.info("disconnect mb=%s dev=%s", tag(conn.mb), tag(conn.dev))

    async def _flush(self, conn: Conn):
        async with conn.lock:
            while True:
                # Sizes first, a bounded batch; each frame's bytes are read only as it is sent, so a flush holds about
                # one frame however full the bank is.
                rows = self.store.pending(conn.mb, conn.dev, after=conn.sent_upto)
                if not rows:
                    return
                for rseq, _size in rows:
                    raw = self.store.frame(rseq)
                    if raw is not None:
                        await conn.ws.send(struct.pack(">Q", rseq) + raw)
                    conn.sent_upto = rseq

    def _kick(self, mb: str, devs) -> None:
        peers = self.online.get(mb, {})
        for dev in devs:
            conn = peers.get(dev)
            if conn is not None:
                asyncio.create_task(self._flush_quiet(conn))

    async def _flush_quiet(self, conn: Conn):
        with contextlib.suppress(ConnectionClosed):
            await self._flush(conn)

    # -- frames -------------------------------------------------------------------------------------------------
    async def _reply(self, conn: Conn, obj: dict):
        with contextlib.suppress(ConnectionClosed):
            await conn.ws.send(json.dumps(obj))

    async def _on_frame(self, conn: Conn, raw: bytes):
        started = time.perf_counter()
        ctr = None
        try:
            frame = wire.parse(raw)
            ctr = frame.header["ctr"]
            if len(raw) > self.config.max_frame_bytes:
                raise Refused("too_large")
            if frame.header["mb"] != conn.mb or frame.sender != conn.dev:
                raise Refused("not_yours")
            wire.verify(frame)
            bank = self.store.bank(conn.mb)
            if bank is None or not self.store.is_member(conn.mb, conn.dev):
                raise Refused("not_member")
            kind = frame.kind
            if kind in wire.HOME_ONLY and conn.dev != bank["home"]:
                raise Refused("home_only")
            if kind == "epoch":
                rseq = await self._on_epoch(conn, frame)
            else:
                self.store.bump_ctr(conn.mb, conn.dev, ctr)
                if kind == "status":
                    self.store.put_status(conn.mb, conn.dev, raw, frame.header["at"])
                    rseq = 0
                    for dev, peer in list(self.online.get(conn.mb, {}).items()):
                        if dev != conn.dev:
                            with contextlib.suppress(ConnectionClosed):
                                await peer.ws.send(struct.pack(">Q", 0) + raw)
                else:
                    rseq = self._store_frame(conn, frame, bank)
        except (Refused, wire.WireError) as exc:
            log.info("refused mb=%s from=%s size=%d code=%s", tag(conn.mb), tag(conn.dev), len(raw), exc.code)
            await self._reply(conn, {"t": "refused", "ctr": ctr, "code": exc.code})
            return
        log.info("frame mb=%s from=%s kind=%s size=%d rseq=%d ms=%.2f", tag(conn.mb), tag(conn.dev), frame.kind,
                 len(raw), rseq, (time.perf_counter() - started) * 1000)
        await self._reply(conn, {"t": "ok", "ctr": ctr, "rseq": rseq})

    def _store_frame(self, conn: Conn, frame: wire.Frame, bank: dict) -> int:
        to = frame.header["to"]
        members = set(self.store.members(conn.mb))
        if to == "*":
            recipients = sorted(members - {conn.dev})
        elif to == "home":
            if conn.dev == bank["home"]:
                raise Refused("bad_route")
            recipients = [bank["home"]]
        else:
            if not set(to) <= members or conn.dev in to:
                raise Refused("bad_route")
            recipients = sorted(set(to))
        stream = f"{frame.sender}:{frame.header['msg']}" if frame.kind == "stream" else None
        rseq, evicted = self.store.put(conn.mb, sender=conn.dev, kind=frame.kind, raw=frame.raw,
                                       created_at=frame.header["at"], recipients=recipients, to_home=to == "home",
                                       stream=stream)
        peers = self.online.get(conn.mb, {})
        for dev, n in evicted.items():
            peer = peers.get(dev)
            if peer is not None:
                asyncio.create_task(self._reply(peer, {"t": "dropped", "n": self.store.take_dropped(conn.mb, dev)}))
        if evicted:
            log.info("evicted mb=%s frames=%d", tag(conn.mb), sum(evicted.values()))
        self._kick(conn.mb, recipients)
        return rseq

    async def _on_epoch(self, conn: Conn, frame: wire.Frame) -> int:
        st = wire.epoch_statement(frame)
        removed = self.store.apply_epoch(conn.mb, st, frame.raw)
        peers = self.online.get(conn.mb, {})
        for dev in removed:
            peer = peers.pop(dev, None)
            if peer is not None:
                await self._error(peer.ws, "revoked", 4403)
        for dev, peer in list(peers.items()):
            if dev != conn.dev:
                with contextlib.suppress(ConnectionClosed):
                    await peer.ws.send(struct.pack(">Q", 0) + frame.raw)
        log.info("epoch mb=%s epoch=%d devices=%d removed=%d", tag(conn.mb), st["epoch"], len(st["devices"]),
                 len(removed))
        return 0

    # -- control ------------------------------------------------------------------------------------------------
    async def _on_control(self, conn: Conn, text: str):
        try:
            msg = json.loads(text)
            t = msg.get("t")
        except (ValueError, AttributeError):
            await self._reply(conn, {"t": "error", "code": "bad_control"})
            return
        if t == "ack" and isinstance(msg.get("upto"), int):
            self.store.ack(conn.mb, conn.dev, msg["upto"])
        elif t == "counts":
            await self._reply(conn, {"t": "counts", "pending": self.store.counts(conn.mb)})
        elif t == "supersede" and isinstance(msg.get("upto"), int) and isinstance(msg.get("dev"), str):
            bank = self.store.bank(conn.mb)
            if bank is None or conn.dev != bank["home"]:
                await self._reply(conn, {"t": "refused", "code": "home_only"})
                return
            n = self.store.supersede(conn.mb, conn.dev, msg["dev"], msg["upto"])
            log.info("supersede mb=%s dev=%s frames=%d", tag(conn.mb), tag(msg["dev"]), n)
            await self._reply(conn, {"t": "superseded", "dev": msg["dev"], "n": n})
        elif t in ("pair_open", "pair_reply", "pair_close"):
            await self._pair_home(conn, msg)
        else:
            await self._reply(conn, {"t": "error", "code": "bad_control"})

    # -- pairing ------------------------------------------------------------------------------------------------
    async def _pair_home(self, conn: Conn, msg: dict):
        bank = self.store.bank(conn.mb)
        slot = msg.get("slot")
        try:
            if bank is None or conn.dev != bank["home"]:
                raise Refused("home_only")
            if not isinstance(slot, str) or not wire.MAILBOX_RE.match(slot):
                raise Refused("bad_slot")
            if msg["t"] == "pair_open":
                self.store.open_slot(slot, conn.mb, wire.b64d(msg.get("offer", "")),
                                     float(msg.get("ttl") or self.config.pair_ttl_s))
                await self._reply(conn, {"t": "pair_opened", "slot": slot})
                log.info("pair open mb=%s", tag(conn.mb))
                return
            row = self.store.slot(slot)
            if row is None or row["mb"] != conn.mb:
                raise Refused("unknown_slot")
            if msg["t"] == "pair_close":
                self.store.close_slot(slot)
                waiter = self.pair_waiters.pop(slot, None)
                if waiter is not None:
                    await self._error(waiter, "pair_closed", 1000)
                return
            body = wire.b64d(msg.get("body", ""))
            self.store.count_slot_msg(slot, body)
            waiter = self.pair_waiters.get(slot)
            if waiter is not None:
                with contextlib.suppress(ConnectionClosed):
                    await waiter.send(json.dumps({"t": "pair_reply", "body": wire.b64e(body)}))
                    return
            self.store.queue_slot_msg(slot, "to_device", body)
        except (Refused, wire.WireError) as exc:
            await self._reply(conn, {"t": "refused", "code": exc.code, "slot": slot})

    async def _pair_device(self, ws, msg: dict):
        slot = msg.get("slot")
        row = self.store.slot(slot) if isinstance(slot, str) and wire.MAILBOX_RE.match(slot) else None
        if row is None:
            await self._error(ws, "unknown_slot", 4404)
            return
        if slot in self.pair_waiters:
            await self._error(ws, "slot_busy", 4409)
            return
        self.pair_waiters[slot] = ws
        try:
            await ws.send(json.dumps({"t": "pair_offer", "offer": wire.b64e(row["offer"])}))
            for body in self.store.take_slot_msgs(slot, "to_device"):
                await ws.send(json.dumps({"t": "pair_reply", "body": wire.b64e(body)}))
            deadline = row["expires"]
            while True:
                left = deadline - self.clock()
                if left <= 0:
                    await self._error(ws, "slot_expired", 1000)
                    return
                try:
                    text = await asyncio.wait_for(ws.recv(), min(left, 60))
                except asyncio.TimeoutError:
                    continue
                try:
                    m = json.loads(text)
                    body = wire.b64d(m["body"]) if m.get("t") == "pair_send" else None
                except (ValueError, KeyError, TypeError, AttributeError, wire.WireError):
                    body = None
                if body is None:
                    await self._error(ws, "bad_control")
                    return
                try:
                    self.store.count_slot_msg(slot, body)
                except Refused as exc:
                    await self._error(ws, exc.code)
                    return
                home = self.online.get(row["mb"], {}).get(self.store.bank(row["mb"])["home"])
                if home is not None:
                    await self._reply(home, {"t": "pair_req", "slot": slot, "body": wire.b64e(body)})
                else:
                    self.store.queue_slot_msg(slot, "to_home", body)
                log.info("pair message mb=%s size=%d", tag(row["mb"]), len(body))
        finally:
            if self.pair_waiters.get(slot) is ws:
                del self.pair_waiters[slot]
