"""Each device's ordered list of routes to its home, T3 Code's connection model (G132, ruling 51f; owner 2026-11-03:
"yes i think we should copy t3 code or any other better way done by any other software").

**The list.** In this order, every route carrying the same requests:

1. ``lan`` — the home's door (``sync_door``) at a private address of the network both are on;
2. ``tailnet`` — the home's door at its tailnet address, when Tailscale already runs on both (never required);
3. ``configured`` — the address the person set (``replica_of``, a device's registry address: their ``tailscale serve``
   or their own TLS proxy), phases 1–2's HTTP request with this device's token;
4. ``mapped`` / ``ipv6`` — slice 2, behind "Reach my memory away from home" (off; never listed in this build);
5. ``relay`` — the relay the person set under Advanced (off by default);
6. none of them: **queue** — the write waits in the outbox (never expiring until it was sent, ``tx_outbox``), reads
   come from this device's own copy.

**First that answers wins**, and that route is used from then on. A route that does not answer is skipped for
:data:`DOWN_S` and then tried first again — so an earlier route is re-checked every minute, and at once when the
network changes (this computer's own addresses, read every :data:`FINGERPRINT_S`; or the app's word, ``POST
/sync/network``, when it sees a new network or comes back to the front) — and the device moves back as soon as it
answers. A LAN address that does not answer away from home costs one :data:`LAN_CONNECT_S` connect, then nothing for a
minute.

**Learned routes.** A door tells every device that reaches it where it is now (its ``R`` frame), and each device of
the group says where its own door is in the registry (``door``), so a device keeps the routes it learned — including
those of a device that becomes the home later. Identity is the pairing keys, never an address: a device that changed
networks reaches the same home by another route with nothing re-paired, and fetches only what it missed.

**Which route was used** is recorded in the telemetry ledger as enums only (``sync_route``: the side, the route kind,
the event) — never an address, a host or a port. Addresses live only in ``$CICADA_HOME/sync/routes.json`` (0600) and
the registry mirror, outside every bank.

The route logic (:class:`Book`, :func:`drive`) knows nothing of the follower, so a client that only sends captures —
the phone — runs the same list (``api/tests/_phone_like.py`` is that shape).
"""
from __future__ import annotations

import json
import os
import secrets
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

KINDS = ("lan", "tailnet", "configured", "mapped", "ipv6", "relay")
TELEMETRY_KIND = "sync_route"
#: A route that did not answer is tried again (first, if it comes first) after this long.
DOWN_S = 60.0
#: This computer's own addresses are read at most this often to notice a new network.
FINGERPRINT_S = 5.0
LAN_CONNECT_S = 1.0
OTHER_CONNECT_S = 2.0
ROUTES_FILE = "routes.json"
LAN_DIAL_ENV = "CICADA_SYNC_LAN_DIAL"
LEARNED_TTL_S = 30 * 86_400


class NoAnswer(Exception):
    """No route answered. ``kind``: ``unreachable`` (nothing was sent anywhere) or ``timeout`` (a request was sent and
    its answer did not come: it may have landed)."""

    def __init__(self, kind: str = "unreachable"):
        super().__init__(kind)
        self.kind = kind


@dataclass(frozen=True)
class Route:
    kind: str            # one of KINDS
    carrier: str         # door | http | relay
    host: str = ""
    port: int = 0
    base: str = ""

    @property
    def key(self) -> str:
        return f"{self.kind}|{self.carrier}|{self.host}|{self.port}|{self.base}"

    @property
    def connect_s(self) -> float:
        return LAN_CONNECT_S if self.kind == "lan" else OTHER_CONNECT_S


def order(routes: list[Route]) -> list[Route]:
    seen, out = set(), []
    for r in sorted(routes, key=lambda r: KINDS.index(r.kind)):
        if r.key not in seen:
            seen.add(r.key)
            out.append(r)
    return out


class Book:
    """One device's routes to one target: which answered last, which are down until when, and the network it was on
    when it learned that."""

    def __init__(self, side: str = "device", *, fingerprint=None, clock=time.monotonic):
        self.side = side
        self.lock = threading.Lock()
        self.active: str | None = None
        self.active_kind: str | None = None
        self.down: dict[str, float] = {}
        self.clock = clock
        self.fingerprint = fingerprint
        self.fp: str | None = None
        self.fp_at = -1e9
        self.moves = 0
        self.last_move_at: float | None = None
        self.queued = False
        self.on_change = None

    def note_network_change(self) -> None:
        """Every route is worth trying again now (a new network, the app back in front)."""
        with self.lock:
            self.down.clear()
        if self.on_change is not None:
            self.on_change()

    def _check_network(self) -> None:
        if self.fingerprint is None:
            return
        now = self.clock()
        if now - self.fp_at < FINGERPRINT_S:
            return
        self.fp_at = now
        try:
            fp = self.fingerprint()
        except Exception:  # noqa: BLE001
            return
        if self.fp is not None and fp != self.fp:
            self.note_network_change()
        self.fp = fp

    def candidates(self, routes: list[Route]) -> list[Route]:
        """The routes to try now, in order: those not down; when every one is down, all of them (the caller backs
        off, so an unreachable home costs one round of short connects per try)."""
        self._check_network()
        now = self.clock()
        with self.lock:
            up = [r for r in routes if self.down.get(r.key, 0.0) <= now]
        return up or list(routes)

    def ok(self, route: Route) -> None:
        with self.lock:
            self.down.pop(route.key, None)
            moved = route.key != self.active
            before = self.active_kind
            self.active, self.active_kind, self.queued = route.key, route.kind, False
            if moved:
                self.moves += 1
                self.last_move_at = time.time()
        if moved:
            record(self.side, route=route.kind, event="moved", before=before)

    def failed(self, route: Route) -> None:
        with self.lock:
            self.down[route.key] = self.clock() + DOWN_S
            if self.active == route.key:
                self.active = None

    def none(self) -> None:
        with self.lock:
            first = not self.queued
            before = self.active_kind
            self.active, self.active_kind, self.queued = None, None, True
        if first:
            record(self.side, route="none", event="queued", before=before)

    def wire(self, routes: list[Route] | None = None) -> dict:
        now = self.clock()
        with self.lock:
            listed = [{"kind": r.kind, "carrier": r.carrier,
                       "state": "active" if r.key == self.active else
                       ("down" if self.down.get(r.key, 0.0) > now else "untried")}
                      for r in (routes or [])]
            return {"active": self.active_kind, "queued": self.queued, "moves": self.moves,
                    "lastMoveAt": self.last_move_at, "routes": listed}

    def reset(self) -> None:
        with self.lock:
            self.active = self.active_kind = None
            self.down.clear()
            self.queued = False
            self.moves = 0
            self.last_move_at = None
            self.fp, self.fp_at = None, -1e9


def drive(book: Book, routes: list[Route], attempt):
    """Try ``routes`` in order through ``attempt(route)`` (which returns the answer or raises :class:`NoAnswer`); the
    first that answers wins. :class:`NoAnswer` when none did — ``timeout`` if any request may have landed."""
    worst = "unreachable"
    for route in book.candidates(routes):
        try:
            got = attempt(route)
        except NoAnswer as exc:
            book.failed(route)
            if exc.kind == "timeout":
                worst = "timeout"
            continue
        book.ok(route)
        return got
    book.none()
    raise NoAnswer(worst)


# --- telemetry: enums only ------------------------------------------------------------------------------------------------

def record(side: str, *, route: str, event: str, before: str | None = None) -> None:
    """One ``sync_route`` row: ``side`` (device | door), ``route`` (a :data:`KINDS` value, ``loopback`` folded into
    ``lan``, or ``none``), ``event`` (moved | queued | served), ``before`` (the kind it moved from). Never an address."""
    try:
        from api.services import telemetry

        refs = {"side": side, "route": route, "event": event}
        if before:
            refs["before"] = before
        telemetry.record(telemetry.UsageEvent(kind=TELEMETRY_KIND, stage="sync", invocations=0, billing="free",
                                              refs=refs))
    except Exception:  # noqa: BLE001 — telemetry never breaks a request
        pass


# --- what this computer learned (outside every bank) ---------------------------------------------------------------------

_FILE_LOCK = threading.Lock()


def _path() -> Path:
    from api.services import runtime_layout

    return runtime_layout.cicada_home() / "sync" / ROUTES_FILE


def _load() -> dict:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict) -> None:
    path = _path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, path)


def _clean_door(info) -> dict | None:
    if not isinstance(info, dict):
        return None
    try:
        port = int(info.get("port") or 0)
    except (TypeError, ValueError):
        return None
    if not 0 < port < 65536:
        return None
    from api.services import sync_door

    def hosts(kind):
        return [h for h in (info.get(kind) or [])[:8]
                if isinstance(h, str) and sync_door.address_class(h) in ("lan", "tailnet", "loopback")]

    key = info.get("key") if isinstance(info.get("key"), str) and len(info.get("key")) <= 64 else None
    return {"port": port, "key": key, "lan": hosts("lan"), "tailnet": hosts("tailnet")}


def learn(device_id: str, info: dict) -> None:
    """A door told us where it is now (its ``R`` frame): kept for ``device_id``."""
    clean = _clean_door(info)
    if not device_id or clean is None:
        return
    with _FILE_LOCK:
        data = _load()
        learned = data.setdefault("learned", {})
        old = learned.get(device_id) or {}
        if {k: old.get(k) for k in clean} == clean and time.time() - float(old.get("at") or 0) < 3600:
            return
        learned[device_id] = {**clean, "at": time.time()}
        _save(data)


def found(device_id: str, host: str, port: int) -> None:
    """The app found the door at ``host:port`` on this network (Bonjour) and the handshake proved it is
    ``device_id``'s."""
    with _FILE_LOCK:
        data = _load()
        rows = [r for r in (data.setdefault("found", {}).get(device_id) or [])
                if (r.get("host"), r.get("port")) != (host, port)]
        rows.insert(0, {"host": host, "port": int(port), "at": time.time()})
        data["found"][device_id] = rows[:8]
        _save(data)


def set_lan_allowed(allowed: bool) -> None:
    with _FILE_LOCK:
        data = _load()
        if bool(data.get("lanAllowed")) != bool(allowed):
            data["lanAllowed"] = bool(allowed)
            _save(data)


def may_dial_lan(environ=os.environ) -> bool:
    """Whether this backend may open a connection to a LAN address. On a Mac only when the app says the person allowed
    local network access and this backend's agent names the app (Apple TN3179; ``sync_discovery.associated``); on
    Linux always. ``CICADA_SYNC_LAN_DIAL=on|off`` sets it (a headless server, the suite)."""
    raw = (environ.get(LAN_DIAL_ENV) or "").strip().lower()
    if raw in ("on", "1", "true"):
        return True
    if raw in ("off", "0", "false"):
        return False
    if sys.platform != "darwin":
        return True
    from api.services import sync_discovery

    return sync_discovery.associated() and bool(_load().get("lanAllowed"))


# --- a replica's routes to its home -----------------------------------------------------------------------------------------

BOOK = Book("device", fingerprint=None)
_TAILNET_SELF: list = [None, -1e9]
_TARGET: dict = {"at": -1e9, "value": None}


def _fingerprint() -> str:
    from api.services import sync_door

    return sync_door.network_fingerprint()


BOOK.fingerprint = _fingerprint


TAILNET_ENV = "CICADA_SYNC_TAILNET"


def _i_am_on_a_tailnet() -> bool:
    """Tailscale is a route only when it already runs here (never required). ``CICADA_SYNC_TAILNET=off`` leaves it
    out (the suite: a developer's own tailnet never carries a test)."""
    if (os.environ.get(TAILNET_ENV) or "").strip().lower() in ("off", "0", "false"):
        return False
    now = time.monotonic()
    if now - _TAILNET_SELF[1] > 30.0:
        from api.services import sync_door

        _TAILNET_SELF[0] = bool(sync_door.local_addresses()["tailnet"])
        _TAILNET_SELF[1] = now
    return bool(_TAILNET_SELF[0])


def door_routes(info: dict | None, found_rows: list | None = None, *, lan_ok: bool, tailnet_ok: bool) -> list[Route]:
    """The door routes one device's door info gives: its LAN and tailnet addresses (a LAN one only when this backend
    may dial the LAN; loopback always, it never leaves this computer), plus where the app found it."""
    from api.services import sync_door

    out: list[Route] = []
    info = _clean_door(info) if info else None
    candidates = []
    for row in found_rows or []:
        if isinstance(row, dict) and time.time() - float(row.get("at") or 0) < 86_400:
            candidates.append((str(row.get("host") or ""), int(row.get("port") or 0)))
    if info:
        candidates += [(h, info["port"]) for h in info["lan"] + info["tailnet"]]
    for host, port in candidates:
        cls = sync_door.address_class(host)
        if not port or cls is None:
            continue
        if cls == "loopback" or (cls == "lan" and lan_ok):
            out.append(Route("lan", "door", host, port))
        elif cls == "tailnet" and tailnet_ok:
            out.append(Route("tailnet", "door", host, port))
    return out


def home_target():
    """``(Target, door info, found rows)`` for this copy's home — its id, its door key and signing key from the
    registry this copy mirrored, plus what it learned — or ``(None, None, None)``. Read at most every 5 s."""
    now = time.monotonic()
    if now - _TARGET["at"] < 5.0:
        return _TARGET["value"]
    _TARGET["at"] = now
    value = (None, None, None)
    try:
        from api.services import home_move, replica, runtime_layout, sync_door

        if not runtime_layout.is_replica() or not sync_door.enabled():
            _TARGET["value"] = value
            return value
        mp = replica.copy_path()
        if mp is None:
            _TARGET["value"] = value
            return value
        rows = home_move.load_mirror(mp)
        rec = home_move.record(mp)
        home_id = rec.to if rec is not None else next((r.get("id") for r in rows if r.get("is_self")), None)
        row = home_move.row(rows, home_id)
        data = _load()
        learned = (data.get("learned") or {}).get(home_id) or {}
        reg_door = None
        if row and row.get("door"):
            try:
                reg_door = json.loads(row["door"]) if isinstance(row["door"], str) else row["door"]
            except ValueError:
                reg_door = None
        info = None
        if learned and time.time() - float(learned.get("at") or 0) < LEARNED_TTL_S:
            info = dict(learned)
            if reg_door:
                for k in ("lan", "tailnet"):
                    info[k] = list(dict.fromkeys(list(info.get(k) or []) + list(reg_door.get(k) or [])))
                info["key"] = info.get("key") or reg_door.get("key")
        elif reg_door:
            info = reg_door
        key = (info or {}).get("key")
        if row and row.get("sign_jwk") and key and not row.get("revoked_at"):
            target = sync_door.Target(str(home_id), sync_door._b64d(key), json.loads(row["sign_jwk"]))  # noqa: SLF001
            value = (target, info, (data.get("found") or {}).get(home_id) or [])
    except Exception:  # noqa: BLE001 — no door route: the configured address, as before
        value = (None, None, None)
    _TARGET["value"] = value
    return value


def forget_target() -> None:
    _TARGET["at"] = -1e9


def home_routes(base: str | None, *, relay: bool, tailnet_ok: bool | None = None) -> tuple[list[Route], object]:
    """This copy's ordered routes to its home, and the door :class:`Target` they lead to (or None)."""
    from api.services import sync_transport

    target, info, found_rows = home_target()
    routes: list[Route] = []
    if target is not None:
        routes += door_routes(info, found_rows, lan_ok=may_dial_lan(),
                              tailnet_ok=_i_am_on_a_tailnet() if tailnet_ok is None else tailnet_ok)
    if base and sync_transport._endpoint(base) is not None:   # noqa: SLF001
        routes.append(Route("configured", "http", base=base))
    if relay:
        routes.append(Route("relay", "relay"))
    return order(routes), target


def wire(base: str | None = None) -> dict:
    """``GET /sync/routes``: this copy's routes to its home as kinds and states, the door here, never an address."""
    from api.services import sync_door, sync_transport

    try:
        routes, _t = home_routes(base, relay=sync_transport._link() is not None)   # noqa: SLF001
    except Exception:  # noqa: BLE001
        routes = []
    door = sync_door.SERVER.wire() if sync_door.SERVER is not None else {"open": False}
    door.pop("port", None)
    return {"toHome": BOOK.wire(routes), "door": door, "lanDial": may_dial_lan(),
            "away": {"on": False, "text": "Reaching your memory away from home is not built yet."}}


def reset_for_tests() -> None:
    BOOK.reset()
    _TARGET["at"] = -1e9
    _TAILNET_SELF[1] = -1e9
