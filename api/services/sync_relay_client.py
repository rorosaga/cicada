"""The device side of the relay connection (G132 phase 3a). Phase 3b wires it into the follower and the outbox; until
then nothing imports it, so a normal install starts no process and opens no connection.

The relay URL is the person's own setting (the hosted default or the one they pasted), like ``api_base``: it is not a
URL someone else chose, so ``net_guard`` does not gate it. It must be ``wss://``; plain ``ws://`` is accepted only for a
loopback relay (the suite, a self-hoster's own TLS proxy on the same machine). The client sends no cookie, no Cicada
token and no bank id: the relay sees the mailbox id, this device's public key and its signature over a fresh challenge.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import struct
from urllib.parse import urlparse

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from .sync_relay_crypto import MAX_FRAME, Endpoint, Refused, b64d, b64e

LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def check_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme == "wss" or (parsed.scheme == "ws" and (parsed.hostname or "") in LOOPBACK):
        return url if parsed.path.endswith("/v1") else url.rstrip("/") + "/v1"
    raise Refused("relay_url_not_tls")


class RelayClient:
    """One authenticated connection for one device. ``inbox`` yields ``(relay seq, frame)``; frames are opened by the
    caller's ``Endpoint``, never here."""

    def __init__(self, url: str, endpoint: Endpoint, *, create: bytes | None = None, open_timeout: float = 10):
        self.url = check_url(url)
        self.endpoint = endpoint
        self.create = create
        self.open_timeout = open_timeout
        self.ws = None
        self.welcome: dict | None = None
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.control: asyncio.Queue = asyncio.Queue()
        self.dropped = 0
        self.closed: tuple[int | None, str | None] | None = None
        self._replies: dict[int, asyncio.Future] = {}
        self._reader: asyncio.Task | None = None

    async def connect(self) -> dict:
        self.ws = await connect(self.url, max_size=MAX_FRAME + 64 * 1024, open_timeout=self.open_timeout,
                                user_agent_header=None)
        challenge = json.loads(await self.ws.recv())
        nonce = b64d(challenge["nonce"])
        hello = {"t": "hello", "mb": self.endpoint.mailbox, "dev": self.endpoint.me,
                 "sig": self.endpoint.keys.sign_auth(self.endpoint.mailbox, nonce)}
        if self.create is not None:
            hello["create"] = b64e(self.create)
        await self.ws.send(json.dumps(hello))
        first = json.loads(await self.ws.recv())
        if first.get("t") != "welcome":
            code = first.get("code", "refused")
            with contextlib.suppress(Exception):
                await self.ws.close()
            raise Refused(code)
        self.welcome = first
        self.dropped = first.get("dropped", 0)
        self._reader = asyncio.create_task(self._read())
        return first

    async def _read(self):
        try:
            async for message in self.ws:
                if isinstance(message, bytes):
                    (rseq,) = struct.unpack(">Q", message[:8])
                    await self.inbox.put((rseq, message[8:]))
                    continue
                msg = json.loads(message)
                t = msg.get("t")
                if t in ("ok", "refused") and self._replies:
                    # A frame the relay could not even parse is answered without its counter: it is the oldest one
                    # still waiting, since frames are answered in the order they were sent.
                    ctr = msg.get("ctr") if msg.get("ctr") in self._replies else min(self._replies)
                    fut = self._replies.pop(ctr)
                    if not fut.done():
                        fut.set_result(msg)
                elif t == "dropped":
                    self.dropped += int(msg.get("n", 0))
                else:
                    await self.control.put(msg)
        except ConnectionClosed:
            pass
        finally:
            rcvd = getattr(self.ws, "close_rcvd", None)
            self.closed = (getattr(rcvd, "code", None), getattr(rcvd, "reason", None))
            for fut in self._replies.values():
                if not fut.done():
                    fut.set_exception(Refused("disconnected"))
            await self.inbox.put(None)

    async def send(self, frames: list[bytes], timeout: float = 30) -> list[dict]:
        """Send frames in order; returns the relay's answer to each (``ok`` with its relay seq, or ``refused``)."""
        out = []
        for raw in frames:
            (hlen,) = struct.unpack(">H", raw[3:5])
            ctr = json.loads(raw[5 : 5 + hlen])["ctr"]
            fut = asyncio.get_running_loop().create_future()
            self._replies[ctr] = fut
            await self.ws.send(raw)
            out.append(await asyncio.wait_for(fut, timeout))
        return out

    async def send_raw(self, raw: bytes) -> None:
        await self.ws.send(raw)

    async def recv(self, timeout: float = 10):
        item = await asyncio.wait_for(self.inbox.get(), timeout)
        if item is None:
            raise Refused("disconnected")
        return item

    async def ack(self, upto: int) -> None:
        await self.ws.send(json.dumps({"t": "ack", "upto": upto}))

    async def counts(self, timeout: float = 10) -> dict:
        await self.ws.send(json.dumps({"t": "counts"}))
        return (await self.next_control("counts", timeout))["pending"]

    async def supersede(self, dev: str, upto: int, timeout: float = 10) -> int:
        """The home only: drop the deltas still waiting for ``dev`` up to relay seq ``upto``, before sending it one
        coalesced ``cursor..HEAD`` delta instead."""
        await self.ws.send(json.dumps({"t": "supersede", "dev": dev, "upto": upto}))
        return (await self.next_control("superseded", timeout))["n"]

    async def next_control(self, t: str, timeout: float = 10) -> dict:
        while True:
            msg = await asyncio.wait_for(self.control.get(), timeout)
            if msg.get("t") == t:
                return msg

    # -- pairing, the home's side ---------------------------------------------------------------------------------
    async def pair_open(self, slot: str, offer: bytes, ttl: int = 600) -> None:
        await self.ws.send(json.dumps({"t": "pair_open", "slot": slot, "offer": b64e(offer), "ttl": ttl}))
        msg = await self.next_control("pair_opened")
        if msg.get("slot") != slot:
            raise Refused("pair_open_failed")

    async def pair_request(self, timeout: float = 10) -> tuple[str, bytes]:
        msg = await self.next_control("pair_req", timeout)
        return msg["slot"], b64d(msg["body"])

    async def pair_reply(self, slot: str, body: bytes) -> None:
        await self.ws.send(json.dumps({"t": "pair_reply", "slot": slot, "body": b64e(body)}))

    async def pair_close(self, slot: str) -> None:
        await self.ws.send(json.dumps({"t": "pair_close", "slot": slot}))

    async def close(self) -> None:
        if self.ws is not None:
            await self.ws.close()
        if self._reader is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader


class PairingSocket:
    """A not-yet-paired device's connection to one slot: it reads the home's offer and exchanges sealed messages."""

    def __init__(self, url: str, slot: str, open_timeout: float = 10):
        self.url = check_url(url)
        self.slot = slot
        self.open_timeout = open_timeout
        self.ws = None
        self.offer: bytes | None = None

    async def connect(self) -> bytes:
        self.ws = await connect(self.url, max_size=64 * 1024, open_timeout=self.open_timeout, user_agent_header=None)
        await self.ws.recv()   # the challenge: a pairing device has no key to answer it with yet
        await self.ws.send(json.dumps({"t": "pair", "slot": self.slot}))
        msg = json.loads(await self.ws.recv())
        if msg.get("t") != "pair_offer":
            raise Refused(msg.get("code", "refused"))
        self.offer = b64d(msg["offer"])
        return self.offer

    async def send(self, body: bytes) -> None:
        await self.ws.send(json.dumps({"t": "pair_send", "body": b64e(body)}))

    async def recv(self, timeout: float = 10) -> bytes:
        msg = json.loads(await asyncio.wait_for(self.ws.recv(), timeout))
        if msg.get("t") != "pair_reply":
            raise Refused(msg.get("code", "refused"))
        return b64d(msg["body"])

    async def close(self) -> None:
        if self.ws is not None:
            await self.ws.close()
