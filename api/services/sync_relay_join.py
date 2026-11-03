"""Joining a memory over the relay: the new computer's side of pairing (G132 phase 3b).

The person on the new computer scans the home's QR (v2: the code, the relay, a random slot and the home's public keys)
or types the code the home shows. This computer then holds the exchange ``sync_relay_pairing.DevicePairing`` defines:

* **scanned** — the home's keys come from the QR, so the relay can neither read the request nor answer as the home;
  the welcome follows the person's confirmation on the home's screen;
* **typed** — the slot is the code's Argon2id; both screens show six digits, and this computer accepts the welcome
  only after the person confirms here that they match (the home only after the person confirms there). A relay that
  stood between them matches with probability 10⁻⁶.

The welcome carries this device's full token, the membership (with this device's epoch key) and, when the home has
one, its direct address. This computer keeps the token in ``device_token``, the home as ``replica_of`` (its address, or
``sync_transport.RELAY_ONLY_BASE``), the relay in its setting and the endpoint in the relay state — all 0600, outside
every bank — and starts again as a copy. Nothing here is logged but states.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import time
from dataclasses import dataclass, field

from loguru import logger

from api.services.sync_relay_client import PairingSocket
from api.services.sync_relay_crypto import Endpoint, Refused
from api.services.sync_relay_pairing import DevicePairing

JOIN_TTL_S = 600
TEXTS = {
    "connecting": "Reaching the computer that holds your memory…",
    "confirm": "Check that the same six digits show on both screens, then confirm on both.",
    "waiting": "Waiting for you to confirm on the computer that holds your memory.",
    "done": "This computer keeps a copy of your memory now. It starts again in a moment.",
    "void": "Two devices answered this code, so neither was added. Start again with a new code.",
    "failed": "Pairing did not finish. Start again with a new code.",
    "expired": "This code ran out. Start again with a new code.",
}


@dataclass
class Join:
    pairing: DevicePairing
    relay: str
    state: str = "connecting"
    code: str | None = None
    started: float = field(default_factory=time.time)
    confirmed: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None
    socket: PairingSocket | None = None

    def wire(self) -> dict:
        if self.state not in ("done", "void", "failed") and time.time() - self.started > JOIN_TTL_S:
            self.state = "expired"
        return {"state": self.state, "sas": self.pairing.sas, "typed": self.pairing.typed, "code": self.code,
                "text": TEXTS.get(self.state, "")}


JOIN: Join | None = None


def begin(*, qr: dict | None, code: str | None, relay: str | None, name: str, slot_cost: dict | None = None) -> Join:
    """Start joining (``POST /sync/relay/join``): from the scanned QR, or the typed code and the relay address."""
    global JOIN
    if qr is not None:
        pairing = DevicePairing.from_qr(qr, name=name)
        relay = qr.get("relay")
    else:
        pairing = DevicePairing.from_code(code or "", name=name, **(slot_cost or {}))
    if not relay:
        raise Refused("no_relay")
    if JOIN is not None and JOIN.task is not None and not JOIN.task.done():
        JOIN.task.cancel()
    JOIN = Join(pairing=pairing, relay=relay)
    JOIN.task = asyncio.get_running_loop().create_task(_run(JOIN, qr))
    return JOIN


async def _run(join: Join, qr: dict | None) -> None:
    sock = PairingSocket(join.relay, join.pairing.slot)
    join.socket = sock
    try:
        join.pairing.read_offer(await sock.connect())
        await sock.send(join.pairing.request())
        if join.pairing.typed:
            join.pairing.read_reveal(await sock.recv(timeout=JOIN_TTL_S))
            join.state = "confirm"
            await asyncio.wait_for(join.confirmed.wait(), JOIN_TTL_S)
        join.state = "waiting"
        sealed = await sock.recv(timeout=JOIN_TTL_S)
        token, endpoint = join.pairing.accept_welcome(sealed, confirmed=join.confirmed.is_set() or not
                                                      join.pairing.typed)
        welcome = _welcome_extra(join, sealed)
        await asyncio.to_thread(_keep, token, endpoint, join.relay, welcome.get("url"))
        join.state = "done"
        logger.info("relay join: this computer joined; starting again as a copy")
        asyncio.get_running_loop().call_later(0.5, _restart)
    except Refused as exc:
        join.state = "void" if exc.code in ("pairing_void", "pair_closed", "slot_busy") else "failed"
        logger.info(f"relay join: not joined ({exc.code})")
    except (asyncio.TimeoutError, Exception) as exc:  # noqa: BLE001
        join.state = "expired" if isinstance(exc, asyncio.TimeoutError) else "failed"
        logger.info(f"relay join: not joined ({type(exc).__name__})")
    finally:
        with contextlib.suppress(Exception):
            await sock.close()


def _welcome_extra(join: Join, sealed: bytes) -> dict:
    """The welcome's own fields beside the token (the home's direct address, when it has one). Re-read through the
    pairing's own checks (``accept_welcome`` already verified it; this reads ``url`` only)."""
    import json

    from api.services.sync_relay_crypto import b64d
    from api.services.sync_relay_pairing import _unseal, _verify   # noqa: PLC2701

    try:
        got = _unseal(join.pairing.keys, sealed)
        return _verify(b64d(got.get("signed", "")), join.pairing.home_pub["ed"])
    except (Refused, ValueError, json.JSONDecodeError):
        return {}


def _keep(token: str, endpoint: Endpoint, relay: str, url: str | None) -> None:
    from api.services import runtime_layout, sync_transport

    home = runtime_layout.cicada_home()
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    base = sync_transport.RELAY_ONLY_BASE
    if url:
        with contextlib.suppress(ValueError):
            base = runtime_layout._checked_base(url, "url")   # noqa: SLF001
    sync_transport.set_relay_url(relay)
    for name, value in ((runtime_layout.DEVICE_TOKEN_FILE, token), (runtime_layout.REPLICA_FILE, base)):
        tmp = home / f".{name}.tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(value + "\n")
        os.replace(tmp, home / name)
    from api.services import sync_relay_link

    sync_relay_link.join_state(endpoint)


def _restart() -> None:
    from api.services import home_move

    home_move.restart_in_place()


def confirm() -> dict:
    if JOIN is None:
        raise Refused("no_join")
    if JOIN.state != "confirm":
        raise Refused("not_waiting")
    JOIN.confirmed.set()
    return JOIN.wire()


def cancel() -> None:
    global JOIN
    if JOIN is not None and JOIN.task is not None:
        JOIN.task.cancel()
    JOIN = None
