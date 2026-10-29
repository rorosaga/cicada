"""Moving the home (G132 phase 2, ruling 51a): one device orders writes and runs Sleep, and it can change.

Owner, 2026-10-29: *"Changing the 'main machine' should be easy"*, and *"Sleep page on the app should show the selected
device running consolidation and you should be able to easily switch."* "Who consolidates" and "who orders writes"
are one concept, **the home**: this module moves both together, or neither.

**One orderer at every instant.** A device admits a write only while it is the home *by its own durable evidence*:
it runs in local mode, publishes this bank, holds no ``handoff.json`` (this computer's hand-off state, outside every
bank), and its history's last ``_home.json`` (``home_record``) does not name another device. Every step that changes
that evidence is written down before the step that depends on it:

1. **The move, on the old home** (:func:`start_move`): ``handoff.json`` ``leaving`` first (fsynced) — from that
   instant every bank writer is refused here (``replica_guard.blocks``), the app's writes and the tool door answer
   503 ``home_moving`` (a device's outbox and the hooks' spool keep them; they re-target to the new home by
   themselves, since they carry the bank's id, not an address); a running Sleep is parked (cancelled at its next safe
   point; what it filed stays filed, the rest waits); writers already admitted are waited out (``write_admission``);
   what is still uncommitted here is carried in one commit of its own, with no author; then the signed record naming
   the target is committed **alone, as the last commit this home makes**, and ``handoff.json`` says ``left``.
2. **The target** (a replica) fast-forwards to that commit like any other, reads the record, checks the signature
   against the key the registry holds for the old home, and promotes itself (:func:`promote`): ``promote.json``
   first, then the group's device registry taken into its own, its copy made its own bank, publishing on, the
   schedule the old home had, ``replica_of`` removed — and it starts again as the home.
3. **The old home**, seeing the target answer as the home of a higher term, becomes its replica (:func:`demote`):
   ``demote.json`` first, then its own device token, its bank marked a copy, publishing off, ``replica_of`` the new
   home — and it starts again following it. Other replicas re-point the moment the record reaches them
   (:func:`after_apply`): the registry gives the new home's address.

Between 1 and 2 nobody admits (the write downtime). A crash anywhere leaves at most one device that may admit:

* the old home cut before its record committed → at its next start ``handoff.json`` ``leaving`` with no record naming
  another device is undone (:func:`finish_at_start`): it is the home again, and the target never saw a record;
* cut after the record → the record names the target: it stays closed and goes on demoting;
* the target cut mid-promotion → ``promote.json`` is finished first thing at its next start (before the mode is
  read), idempotently; until then it is still a replica and admits nothing;
* the old home cut mid-demotion → ``demote.json`` the same.

**A lost home** (:func:`take_over`): a replica may take over only on the person's OK, after it was shown how far
behind it is ("N changes behind the last home it saw, at <time>"), and only while that home does not answer. It
writes and signs the record itself (term + 1, the take-over point = its own head) and promotes. **The term is the
fence:** any device that learns of a record of a higher term than the one it acts under stops ordering writes at
once. A home that was only unreachable — not gone — learns it from any device it can reach (:func:`check_peers`, every
minute while it publishes, and at its start) and becomes a replica; what it ordered after the take-over point is set
aside on a ref, **never merged and never dropped**, and offered back to the new home as transactions
(:func:`reconcile`): episodes as the episodes, every other change as the call that made it (``admitted_log``). The
person sees the count, in words. The person's confirmation is what stands in for a quorum Cicada does not have: with
two devices that cannot see each other, only the person can say the other is gone; the term makes sure the history
never forks into two that are both kept.

**Unset or off, nothing changes**: a computer that does not publish and is no replica never writes any of these files,
starts no thread and answers ``/sync/home`` with ``{"shared": false}``. **A demo bank never moves** (it is never
published or copied). **Credentials never go in a bank**: the record carries device ids, names and a public key; the
registry a full device mirrors carries token hashes outside every bank; the old home's own token is a 0600 file.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

HANDOFF = "handoff.json"
PROMOTE = "promote.json"
DEMOTE = "demote.json"
SELF_TOKEN = "self_token"
MIRROR = "devices.json"
SET_ASIDE = "set_aside.json"
SET_ASIDE_REF = "refs/cicada/set-aside"
DEVICE_URL_ENV = "CICADA_DEVICE_URL"

#: How long a running Sleep may take to reach its next safe point before the move is called off.
PARK_MAX_S = 600.0
#: Writers admitted before the move closed: waited out at most this long (``write_admission``), else called off.
WRITERS_MAX_S = 60.0
#: Before closing, the target is given at most this long to catch up (``CATCH_UP_WITHIN``).
CATCH_UP_S = 5.0
#: How often a publishing home asks its peers whether another took over (:func:`check_peers`).
PEER_EVERY_S = 60.0
#: A replica whose home has been unreachable this long asks the other devices whether one of them is the home now
#: (``CICADA_SYNC_PEER_AFTER_S`` changes it — the suite's three-machine test, never a person's setting).
PEER_AFTER_OFFLINE_S = 20.0


def peer_after_offline_s() -> float:
    try:
        return float(os.environ.get("CICADA_SYNC_PEER_AFTER_S") or PEER_AFTER_OFFLINE_S)
    except ValueError:
        return PEER_AFTER_OFFLINE_S
PEER_TIMEOUT_S = 3.0
#: A device counts as online when it reached the home this recently.
ONLINE_WITHIN_S = 120.0
#: A move's refusal stays on the Sleep page this long.
REFUSAL_SHOWN_S = 300.0
#: A home that recorded a move whose target has not taken over after this long may take its memory back.
TAKE_BACK_AFTER_S = 60.0

MOVING_TEXT = ("Your memory is moving to {to}. Changes wait a moment and go there; reading works as before.")
MOVED_TEXT = ("Your memory moved to {to}. This computer now follows it; changes go there.")
SUPERSEDED_TEXT = ("{to} took over your memory while this computer was away. This computer now follows it; what "
                   "was changed here meanwhile is set aside and offered to it.")


class MoveRefused(Exception):
    """A move or a take-over that cannot start: the sentence says why. ``code`` for the wire."""

    def __init__(self, code: str, text: str, status: int = 409):
        super().__init__(text)
        self.code = code
        self.text = text
        self.status = status


# --- files outside every bank -----------------------------------------------------------------------------------------

def _sync_root(create: bool = False) -> Path:
    from api.services import runtime_layout

    root = runtime_layout.cicada_home() / "sync"
    if create:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(root, 0o700)
    return root


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    _CACHE.clear()


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_line(path: Path, value: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(value + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


_CACHE: dict[str, tuple[tuple[int, int], dict | None]] = {}


def handoff() -> dict | None:
    """This computer's hand-off state (``leaving`` / ``left`` / ``superseded``), or None. One ``stat`` when it has
    not changed: the write backstop asks on every write."""
    path = _sync_root() / HANDOFF
    try:
        st = path.stat()
    except OSError:
        return None
    stamp = (st.st_mtime_ns, st.st_size)
    hit = _CACHE.get(str(path))
    if hit is not None and hit[0] == stamp:
        return hit[1]
    data = _read_json(path)
    _CACHE[str(path)] = (stamp, data)
    return data


#: The phases in which the backstop refuses every bank writer. ``leaving`` / ``superseding`` close only the doors
#: (the app's writes, the tool door, the stdio door, Sleep's start): a writer admitted before the close finishes its
#: whole write and commit — as under Sleep's window — and only then is the bank sealed.
SEALED = frozenset({"sealed", "left", "superseded"})
#: Every phase in which this computer no longer admits a write (what ``role`` answers then).
CLOSED_ROLES = frozenset({"leaving", "sealed", "left", "superseding", "superseded"})


def writes_closed() -> bool:
    """Is this computer closed to new writes because its home is moving or moved away? (The doors' question.)"""
    return handoff() is not None


def writes_sealed() -> bool:
    """Is every bank writer refused here — the doors closed AND the writers admitted before them finished? (The
    backstop's question, ``replica_guard.blocks``.)"""
    state = handoff()
    return state is not None and state.get("phase") in SEALED


def closed_text() -> str:
    state = handoff() or {}
    to = ((state.get("to") or {}).get("name")) or "another computer"
    phase = state.get("phase")
    if phase in ("superseding", "superseded"):
        return SUPERSEDED_TEXT.format(to=to)
    return (MOVED_TEXT if phase == "left" else MOVING_TEXT).format(to=to)


def _clear_handoff() -> None:
    (_sync_root() / HANDOFF).unlink(missing_ok=True)
    _CACHE.clear()


# --- who this computer is in the group ---------------------------------------------------------------------------------

def my_device_id() -> str | None:
    """This computer's id in the group: on a replica, the id of the device token the home issued it; on a home, its
    own row (``device_tokens.own``)."""
    from api.services import device_tokens, runtime_layout

    if runtime_layout.is_replica():
        match = device_tokens.TOKEN_RE.match(runtime_layout.replica_token())
        return match.group(1) if match else None
    try:
        own = device_tokens.store().own()
    except Exception:  # noqa: BLE001
        return None
    return own.id if own is not None else None


def ensure_own_identity() -> str | None:
    """A home that shares its memory has its own row in its own registry (``device_tokens.make_own``): the id the
    record names, the public key it signs with, and the token it will send once it follows another home (0600,
    ``$CICADA_HOME/sync/self_token``). Made once, on the first share; a lost token file makes a new row."""
    from api.services import device_key, device_status, device_tokens, runtime_layout

    store = device_tokens.store()
    own = store.own()
    token_file = _sync_root() / SELF_TOKEN
    if own is not None and token_file.exists():
        return own.id
    if runtime_layout.is_replica():
        return my_device_id()
    device, token = store.make_own(device_status.machine_name(), device_key.public_jwk(create=True))
    _write_line(_sync_root(create=True) / SELF_TOKEN, token)
    return device.id


def own_address() -> str | None:
    """Where the person's other devices reach this computer's backend: ``CICADA_DEVICE_URL`` when set (checked like
    ``CICADA_API_BASE``), else the address this computer serves on the person's tailnet when it serves one (the
    Devices page's reach step, read at most every five minutes), else None. Phase 3's relay replaces it."""
    from api.services import runtime_layout

    raw = (os.environ.get(DEVICE_URL_ENV) or "").strip()
    if raw:
        try:
            return runtime_layout._checked_base(raw, DEVICE_URL_ENV)   # noqa: SLF001
        except ValueError:
            return None
    now = time.monotonic()
    if _REACH[1] and now - _REACH[1] < 300:
        return _REACH[0]
    url = None
    try:
        from api.remote import reach

        guide = reach.guide(runtime_layout.port())
        url = guide.get("url") if guide.get("step") == "ready" else None
    except Exception:  # noqa: BLE001 — no overlay: no address yet
        url = None
    _REACH[0], _REACH[1] = url, now
    return url


_REACH: list = [None, 0.0]


def pinned_by_environment() -> str | None:
    """The sentence when this computer's part in the group is fixed by its environment, so a hand-off cannot change
    it; else None."""
    from api.services import runtime_layout, sync_publish

    if (os.environ.get(runtime_layout.REPLICA_ENV) or "").strip():
        return (f"This computer follows its home because {runtime_layout.REPLICA_ENV} is set where it starts; remove "
                f"it so the home can move.")
    if (os.environ.get(sync_publish.ENV) or "").strip():
        return f"This computer shares its memory because {sync_publish.ENV} is set where it starts; remove it so " \
               "the home can move."
    if (os.environ.get(runtime_layout.API_BASE_ENV) or "").strip():
        return "This computer uses a Cicada server elsewhere; it holds no copy to move."
    return None


# --- the registry every full device shares -------------------------------------------------------------------------------

def mirror_path(memory_path) -> Path:
    from api.services import sync_publish

    return sync_publish.bank_dir(memory_path, create=True) / MIRROR


def load_mirror(memory_path) -> list[dict]:
    data = _read_json(mirror_path(memory_path))
    rows = (data or {}).get("devices")
    return rows if isinstance(rows, list) else []


def save_mirror(memory_path, rows: list[dict]) -> None:
    _write_json(mirror_path(memory_path), {"devices": rows, "at": time.time()})


def registry(memory_path) -> list[dict]:
    """The group's registry as this computer knows it: on the home, its own store (its own row's address and
    signing key current); on a replica, what it mirrored from its home, beside its own store's rows."""
    from api.services import device_key, device_tokens, runtime_layout

    store = device_tokens.store()
    if runtime_layout.is_replica():
        # A replica's own store (the devices it issued while it was a home, if it was one), then what it mirrored
        # from its home on top: an old home that now follows still answers with the whole group.
        rows = {r.get("id"): r for r in store.export()}
        rows.update({r.get("id"): r for r in load_mirror(memory_path) if isinstance(r, dict)})
        return list(rows.values())
    own = store.own()
    if own is not None:
        store.announce(own.id, address=own_address() or "", sign_jwk=device_key.public_jwk(create=True))
    return store.export()


def registry_digest(rows: list[dict]) -> str:
    """What changes when a device joins, leaves, moves address or registers its key — never a seq or a time — so a
    replica asks for the registry again only when it changed."""
    keys = ("id", "token_hash", "revoked_at", "kind", "key_thumbprint", "sign_jwk", "address", "is_self")
    flat = sorted(json.dumps({k: r.get(k) for k in keys}, sort_keys=True) for r in rows if isinstance(r, dict))
    return hashlib.sha256("\n".join(flat).encode("utf-8")).hexdigest()[:16]


def row(rows: list[dict], device_id: str | None) -> dict | None:
    return next((r for r in rows if r.get("id") == device_id), None) if device_id else None


def thumbprint_of(r: dict | None) -> str | None:
    from api.services import device_key

    if not r or not r.get("sign_jwk"):
        return None
    try:
        return device_key.thumbprint(json.loads(r["sign_jwk"]))
    except (TypeError, ValueError):
        return None


def _token_ok(token: str, rows: list[dict]) -> str | None:
    """The device id a bearer token belongs to, checked against ``rows`` (sha256 of the secret, never the token),
    or None."""
    import hmac

    from api.services import device_tokens

    match = device_tokens.TOKEN_RE.match(token or "")
    if not match:
        return None
    device_id, secret = match.groups()
    r = row(rows, device_id)
    if r is None or r.get("revoked_at"):
        return None
    digest = hashlib.sha256(secret.encode("ascii")).hexdigest()
    return device_id if hmac.compare_digest(str(r.get("token_hash") or ""), digest) else None


def peer_caller(memory_path, token: str | None) -> str | None:
    """``GET /sync/peer``'s check: a device of the group (this computer's own store, or the registry it mirrored)."""
    from api.services import device_tokens

    try:
        device = device_tokens.store().verify(token)
    except Exception:  # noqa: BLE001
        device = None
    if device is not None:
        return device.id
    try:
        return _token_ok(token or "", load_mirror(memory_path))
    except Exception:  # noqa: BLE001
        return None


# --- where this computer stands ------------------------------------------------------------------------------------------

def record(memory_path, rev: str = "HEAD"):
    from api.services import home_record

    return home_record.at(memory_path, rev)


def term(memory_path) -> int:
    rec = record(memory_path)
    return rec.term if rec is not None else 0


def role(memory_path) -> str:
    """``local`` (one computer, nothing shared — nothing here applies), ``home``, ``leaving``, ``left``,
    ``superseded`` or ``replica``."""
    from api.services import replica_guard, runtime_layout, sync_publish

    # The mode this process STARTED in counts too (`replica_guard.active`, frozen by a backend's lifespan): a copy that
    # has just written its promotion files is still a copy — every writer refused — until it starts again as the home.
    if runtime_layout.is_replica() or replica_guard.active():
        return "replica"
    state = handoff()
    if state is not None:
        return str(state.get("phase") or "leaving")
    if not sync_publish.publishable(memory_path):
        return "local"
    rec = record(memory_path)
    me = my_device_id()
    if rec is not None and rec.to and me and rec.to != me:
        return "left"
    return "home"


def peer_answer(memory_path) -> dict:
    """``GET /sync/peer``: ids and numbers only — which memory, which term, whether this computer is its home."""
    from api.services import sync_log

    pin = _pin()
    rec = record(memory_path)
    me = role(memory_path)
    try:
        seq = sync_log.head_seq(memory_path) if me == "home" else _replica_seq()
    except Exception:  # noqa: BLE001
        seq = None
    return {"bankId": pin.id if pin is not None else None, "term": rec.term if rec is not None else 0,
            "role": me, "device": my_device_id(), "seq": seq,
            "home": rec.to if rec is not None else (my_device_id() if me == "home" else None),
            "canHost": pinned_by_environment() is None}


def _replica_seq() -> int | None:
    from api.services import replica

    return replica.seq()


# --- talking to another device directly ------------------------------------------------------------------------------------

def _ask(address: str, path: str, token: str, *, method: str = "GET", body: dict | None = None,
         timeout: float = PEER_TIMEOUT_S):
    """``(status | None, body)`` from another device of the group at ``address``. Never follows a redirect."""
    import urllib.error
    import urllib.request

    from api.services import runtime_layout

    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(f"{address.rstrip('/')}{path}", data=data, method=method, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/json", "Content-Type": "application/json"})
    try:
        with runtime_layout.opener().open(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read() or b"null")
        except ValueError:
            return exc.code, None
    except Exception:  # noqa: BLE001 — not reachable
        return None, None


def _own_token() -> str:
    from api.services import runtime_layout

    if runtime_layout.is_replica():
        return runtime_layout.replica_token()
    try:
        return (_sync_root() / SELF_TOKEN).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


# --- the move, on the home ---------------------------------------------------------------------------------------------------

_MOVE_LOCK = threading.Lock()
_PROGRESS: dict = {}


def progress() -> dict:
    return dict(_PROGRESS)


def _step(**changes) -> None:
    _PROGRESS.update(changes, updatedAt=time.time())


def start_move(memory_path, target_id: str) -> dict:
    """The person's "make <device> the home": checked here, then run in the background (:func:`_move`). Returns the
    progress the Sleep page shows. :class:`MoveRefused` with the sentence when it cannot start."""
    from api.services import demo_guard, device_tokens, sync_log, sync_publish

    memory_path = Path(memory_path)
    if demo_guard.is_demo(memory_path):
        raise MoveRefused("demo", "A demo memory never moves.")
    if not sync_publish.publishable(memory_path):
        raise MoveRefused("not_shared", "This memory is not shared with your other computers yet, so there is no "
                                        "other computer to move it to.")
    current = role(memory_path)
    if current != "home":
        raise MoveRefused("not_home", closed_text() if current in CLOSED_ROLES
                          else "This computer does not hold your memory now.")
    pinned = pinned_by_environment()
    if pinned:
        raise MoveRefused("pinned", pinned)
    me = ensure_own_identity()
    if target_id == me:
        raise MoveRefused("already_home", "This computer already holds your memory.")
    pin = _pin()
    bank_id = pin.id if pin is not None else None
    target = device_tokens.store().get(target_id) if device_tokens.ID_RE.match(target_id or "") else None
    if target is None or not target.active:
        raise MoveRefused("unknown_device", "That device is not one of your devices.", 404)
    if target.kind != "full" or target.copy_bank_id != bank_id:
        raise MoveRefused("no_copy", f"{target.name} does not keep a copy of this memory. Turn on \"Keep a full "
                                     f"copy here\" on it first.")
    if not target.address:
        raise MoveRefused("no_address", f"Your other devices cannot reach {target.name} yet. On {target.name}, "
                                        f"open Settings → Devices and share it on your network.")
    status, peer = _ask(target.address, "/sync/peer", _own_token())
    if status != 200 or not isinstance(peer, dict) or peer.get("bankId") != bank_id:
        raise MoveRefused("target_away", f"{target.name} does not answer right now. Try again when it is on.", 503)
    if not peer.get("canHost", True):
        raise MoveRefused("target_pinned", f"{target.name} is set where it starts to follow this computer; remove "
                                           f"CICADA_REPLICA_OF there so it can hold your memory.")
    if not _MOVE_LOCK.acquire(blocking=False):
        raise MoveRefused("moving", "Your memory is already moving.")
    _PROGRESS.clear()
    _step(phase="starting", to={"device": target.id, "name": target.name}, startedAt=time.time(),
          text=MOVING_TEXT.format(to=target.name), headSeq=sync_log.head_seq(memory_path))
    to = {"device": target.id, "name": target.name, "address": target.address}
    threading.Thread(target=_move_thread, args=(memory_path, to, me, bank_id), name="cicada-home-move",
                     daemon=True).start()
    return progress()


def _move_thread(memory_path: Path, to: dict, me: str, bank_id: str | None) -> None:
    try:
        _move(memory_path, to, me, bank_id)
    except MoveRefused as exc:
        _step(phase="refused", text=exc.text, code=exc.code)
    except Exception as exc:  # noqa: BLE001 — never a crash: say so; the history decides who holds the memory
        logger.warning(f"home move: called off ({type(exc).__name__})")
        _step(phase="refused", text="Moving your memory was called off; this computer still holds it.",
              code="error")
    finally:
        if _MOVE_LOCK.locked():
            _MOVE_LOCK.release()


#: Before closing, the target catches up to within this many commits (a copy that streams forwarded saves never
#: reaches the head exactly) or for at most ``CATCH_UP_S``; it takes whatever is left after the record anyway.
CATCH_UP_WITHIN = 25


def _wait_target_caught_up(memory_path: Path, to: dict, bank_id: str | None) -> None:
    from api.services import device_tokens, sync_log

    deadline = time.monotonic() + CATCH_UP_S
    while time.monotonic() < deadline:
        head = sync_log.head_seq(memory_path) or 0
        target = device_tokens.store().get(to["device"])
        if target is not None and target.copy_bank_id == bank_id and (target.copy_seq or 0) >= head - CATCH_UP_WITHIN:
            return
        time.sleep(0.25)


def _recorded(memory_path: Path, to: dict, new_term: int) -> bool:
    """Does the history already name ``to`` under ``new_term`` (or later)? Then this computer must never admit again
    until it follows — whatever went wrong after the commit."""
    rec = record(memory_path)
    return rec is not None and rec.term >= new_term and rec.to == to.get("device")


def _park_sleep(memory_path: Path) -> None:
    """Ruling 51a: a running Sleep is parked before the hand-off — cancelled at its next safe point (never mid-write);
    what it filed stays filed, everything not read waits for the new home. A paused run is ended (its record lives on
    this computer only); the queue is untouched."""
    from api.services import sleep_autocontinue, sleep_cycle, sleep_paused, sleep_runs

    if sleep_cycle.get_sleep_state().status == "running":
        _step(phase="parking")
        sleep_cycle.request_cancel()
        deadline = time.monotonic() + PARK_MAX_S
        while sleep_cycle.get_sleep_state().status == "running":
            if time.monotonic() > deadline:
                raise MoveRefused("sleep_busy", "Sleep did not reach a safe point to stop; try again in a moment.")
            time.sleep(0.25)
    record_ = sleep_paused.load(memory_path)
    if record_:
        sleep_autocontinue.disarm(memory_path)
        sleep_paused.clear(memory_path)
        try:
            sleep_runs.close_open_pause(memory_path, str(record_.get("run_id")))
        except Exception:  # noqa: BLE001
            pass


#: Files beside the pages that are this computer's own and never travel: the primer cursor (``_state.md`` is
#: regenerated by whichever computer is the home, and commits alone — never carried), the schedule (adopted from the
#: frame instead). An untracked file at the bank's root is a machine-local marker (a migration's) and stays here too.
_STAYS = frozenset({"_state.md", "sleep_schedule.yaml"})
CURSOR = "_state.md"


def carry_uncommitted(memory_path: Path) -> int:
    """What is uncommitted here — a save made on this computer (which stays uncommitted until Sleep), a hand edit, a
    tracked file changed by hand — is committed in one commit of its own, with **no author** (the kept-apart
    convention: never attributed to Cicada or a guess), so the next home has it and this computer's tree is clean when
    it starts following. ``_state.md`` is put back to what HEAD holds instead (a cursor the next home regenerates).
    Called inside ``replica_guard.applying()``. Returns how many paths it carried."""
    from api.services import git_service

    memory_path = Path(memory_path)
    tracked = _tracked_dirty(memory_path)
    if CURSOR in tracked:
        git_service.run_git_write_sync(memory_path, "checkout", "HEAD", "--", CURSOR)
    wanted = {p for p in tracked if p not in _STAYS}
    wanted |= {p for p in _untracked(memory_path) if "/" in p and p not in _STAYS}
    current: dict[str, bytes | None] = {}
    for rel in sorted(wanted):
        try:
            current[rel] = (memory_path / rel).read_bytes() if (memory_path / rel).is_file() else None
        except OSError:
            current[rel] = None
    if not current:
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [f"{rel}: {'updated' if data is not None else 'deleted'} (source: n/a, trigger: sync/handoff-carry)"
             for rel, data in sorted(current.items())]
    message = git_service.build_commit_message(f"Uncommitted edits carried to the next home {stamp}", lines)
    with git_service.write_lock(memory_path):
        git_service._commit_kept_apart_sync(memory_path, current, message)   # noqa: SLF001 — exactly these bytes
    return len(current)


def _tracked_dirty(memory_path: Path) -> set[str]:
    """Tracked paths that differ from HEAD (staged or not; both sides of a rename). A read."""
    try:
        out = subprocess.run(["git", "status", "--porcelain", "-z", "--untracked-files=no"], cwd=str(memory_path),
                             capture_output=True, timeout=60).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return set()
    from api.services import git_service

    return set(git_service._parse_status_z(out))   # noqa: SLF001


def _untracked(memory_path: Path) -> list[str]:
    try:
        out = subprocess.run(["git", "ls-files", "-z", "--others", "--exclude-standard"], cwd=str(memory_path),
                             capture_output=True, timeout=60).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return []
    return [p for p in out.split("\0") if p]


def _close(memory_path: Path, phase: str, to: dict, term_: int, **extra) -> None:
    _write_json(_sync_root(create=True) / HANDOFF, {"phase": phase, "to": to, "term": term_,
                                                     "bank": str(Path(memory_path)), "startedAt": time.time(),
                                                     **extra})


def _move(memory_path: Path, to: dict, me: str, bank_id: str | None) -> None:
    from api.services import capture_commit, device_status, home_record, replica_guard, sync_log, write_admission

    _step(phase="catching_up")
    _wait_target_caught_up(memory_path, to, bank_id)
    new_term = term(memory_path) + 1
    # 1. The doors close: no new write is admitted here; a writer admitted before finishes its write and commit.
    _close(memory_path, "leaving", to, new_term)
    t_closed = time.monotonic()
    _step(phase="leaving", closedAt=time.time())
    try:
        _park_sleep(memory_path)
        _step(phase="waiting_writers")
        if not write_admission.wait_for_writers(memory_path, give_up_after=WRITERS_MAX_S):
            raise MoveRefused("writers_busy", "A change was still being saved; try moving again in a moment.")
        # 2. Sealed: every bank writer refused now (the backstop), but the hand-off's own commits below.
        _close(memory_path, "sealed", to, new_term)
        with replica_guard.applying():
            try:
                capture_commit.sweep(memory_path, everything=True)   # every capture record, settled or not
            except Exception:  # noqa: BLE001 — carried below instead
                pass
            carried = carry_uncommitted(memory_path)
            seq = sync_log.head_seq(memory_path) or 0
            after = _head(memory_path)
            rec = home_record.make(bank_id=bank_id or "", term=new_term, kind="move", seq=seq, after=after,
                                   source={"device": me, "name": device_status.machine_name()},
                                   to={"device": to["device"], "name": to["name"]}, signer=me)
            sha = home_record.commit(memory_path, rec, subject=f"Home moved to {to['name']}")
    except BaseException:
        if not _recorded(memory_path, to, new_term):
            _clear_handoff()        # nothing names the target: this computer is the home again
            raise
        sha = _head(memory_path)    # the record landed before the error: closed for good, go on handing off
        carried = 0
    # 3. The record is the last commit this home made: it says so, and waits for the target to take it up.
    _close(memory_path, "left", to, new_term, recordSha=sha, closedFor=round(time.monotonic() - t_closed, 3))
    _step(phase="left", recordSha=sha, carried=carried, recordAt=time.time())
    logger.info(f"home move: the record is committed (term {new_term}); waiting for the new home")
    _wait_and_demote(memory_path, to, new_term)


def _wait_and_demote(memory_path: Path, to: dict, new_term: int) -> None:
    """Wait until the new home answers as the home of ``new_term`` (or a later one), then follow it. Stops when this
    computer took its memory back (:func:`take_over` on a home whose target never came)."""
    delay = 0.25
    while True:
        if handoff() is None:
            return
        status, peer = _ask(to["address"], "/sync/peer", _own_token())
        if status == 200 and isinstance(peer, dict) and peer.get("role") == "home" \
                and int(peer.get("term") or 0) >= new_term:
            _step(phase="demoting", homeAt=time.time())
            demote(memory_path, to, new_term)
            return
        time.sleep(delay)
        delay = min(delay * 1.5, 5.0)


def _head(memory_path: Path) -> str:
    from api.services import sync_service

    return sync_service.git_head(memory_path) or ""


# --- becoming a replica of the new home ----------------------------------------------------------------------------------

def demote(memory_path: Path, to: dict, new_term: int, *, restart: bool = True) -> None:
    """This computer follows ``to`` from its next start: ``demote.json`` first, then the files (:func:`_finish_demote`),
    then a restart in place."""
    from api.services import bank_registry

    name, path, bank_id = bank_registry._active_record(Path(_settings().memory_root))   # noqa: SLF001
    _write_json(_sync_root(create=True) / DEMOTE, {"bank": name, "bankPath": str(path), "bankId": bank_id,
                                                    "to": to, "term": new_term, "at": time.time()})
    _finish_demote()
    if restart:
        restart_in_place()


def _finish_demote() -> bool:
    from api.services import bank_registry, replica, runtime_layout, sync_log, sync_publish

    journal = _read_json(_sync_root() / DEMOTE)
    if not journal:
        return False
    home = runtime_layout.cicada_home()
    token = _own_token() if not runtime_layout.is_replica() else runtime_layout.replica_token()
    if token:
        _write_line(home / runtime_layout.DEVICE_TOKEN_FILE, token)
    root = Path(_settings().memory_root)
    registry_ = bank_registry.load_registry(root)
    record_ = (registry_.get("banks") or {}).get(journal.get("bank"))
    if isinstance(record_, dict):
        record_["replica"] = True
        record_["previous"] = None
        registry_["active"] = journal.get("bank")
        bank_registry.save_registry(root, registry_)
    path = Path(journal.get("bankPath") or "")
    if path.exists():
        try:
            seq = sync_log.head_seq(path) or 0
        except Exception:  # noqa: BLE001
            seq = 0
        replica._write_marker(path, {"home": _host(journal["to"].get("address")), "bankId": journal.get("bankId"),   # noqa: SLF001
                                     "seq": seq, "sha": _head(path), "appliedAt": time.time(), "previous": None,
                                     "demotedAt": time.time()})
    sync_publish.set_enabled(False)
    _write_line(home / runtime_layout.REPLICA_FILE, journal["to"]["address"])
    _clear_handoff()
    (_sync_root() / DEMOTE).unlink(missing_ok=True)
    logger.info("home move: this computer now follows the new home")
    return True


def _host(address: str | None) -> str:
    from api.services import tool_client

    try:
        return tool_client.host_of(address or "")
    except ValueError:
        return ""


def _settings():
    from api.config import get_settings

    return get_settings()


class _Pin:
    __slots__ = ("id",)

    def __init__(self, bank_id: str) -> None:
        self.id = bank_id


def _pin() -> _Pin | None:
    """The active bank's id — read from the registry, so it is right in the follower's and the peer watch's own
    threads too (a request's pinned bank lives only in that request)."""
    from api.services import bank_registry

    try:
        _name, _path, bank_id = bank_registry._active_record(Path(_settings().memory_root))   # noqa: SLF001
    except Exception:  # noqa: BLE001
        return None
    return _Pin(bank_id) if bank_id else None


# --- becoming the home (the target, or a take-over) ------------------------------------------------------------------------

def after_apply(memory_path: Path) -> str | None:
    """The follower's question after every apply (and at its start): does the history now name another home? Returns
    what it did — ``promoted``, ``repointed``, ``unverified`` — or None when nothing changed."""
    from api.services import runtime_layout

    rec = record(memory_path)
    if rec is None or not rec.to:
        return None
    me = my_device_id()
    rows = _rows_with_signer(memory_path, rec)
    problem = _check(rec, rows)
    if problem:
        _note("unverified", problem)
        return "unverified"
    if rec.to == me:
        promote(memory_path, rec)
        return "promoted"
    target = row(rows, rec.to)
    address = (target or {}).get("address")
    if not address:
        rows = _refresh_mirror(memory_path) or rows
        address = (row(rows, rec.to) or {}).get("address")
    if not address:
        _note("no_address", f"Your memory moved to {rec.to_name}, which this computer cannot reach yet.")
        return None
    try:
        current = runtime_layout.replica_of()
    except ValueError:
        current = ""
    if current.rstrip("/") == address.rstrip("/"):
        return None
    if (os.environ.get(runtime_layout.REPLICA_ENV) or "").strip():
        _note("pinned", pinned_by_environment() or "")
        return None
    repoint(address)
    logger.info(f"home move: following the new home (term {rec.term})")
    return "repointed"


def _note(code: str, text: str) -> None:
    _NOTES.clear()
    _NOTES.update({"code": code, "text": text, "at": time.time()})


_NOTES: dict = {}


def notes() -> dict:
    return dict(_NOTES)


def _check(rec, rows: list[dict]) -> str | None:
    from api.services import home_record

    return home_record.verify(rec, thumbprint_of(row(rows, rec.signer)))


def _rows_with_signer(memory_path: Path, rec) -> list[dict]:
    rows = registry(memory_path)
    if rec.signer and not thumbprint_of(row(rows, rec.signer)):
        rows = _refresh_mirror(memory_path) or rows
    return rows


def _refresh_mirror(memory_path: Path, address: str | None = None) -> list[dict] | None:
    """Ask the home (or ``address``) for the group's registry and keep it (``devices.json``)."""
    from api.services import replica, runtime_layout

    if not runtime_layout.is_replica():
        return None
    try:
        if address:
            status, body = _ask(address, "/sync/devices", _own_token(), timeout=10)
        else:
            status, _h, body = replica.request("GET", "/sync/devices", timeout=10)
    except Exception:  # noqa: BLE001 — no token, offline
        return None
    if status == 200 and isinstance(body, dict) and isinstance(body.get("devices"), list):
        save_mirror(memory_path, body["devices"])
        return body["devices"]
    return None


def repoint(address: str) -> None:
    """Follow the home at ``address`` from now on (``replica_of``, read on every request): queued transactions go
    there by themselves."""
    from api.services import replica, runtime_layout

    with replica.MODE_LOCK:
        _write_line(runtime_layout.cicada_home() / runtime_layout.REPLICA_FILE, address)
    replica.wake()


def promote(memory_path: Path, rec) -> None:
    """This replica is named the home: ``promote.json`` first, then the files (:func:`_finish_promote`), then a
    restart in place as the home."""
    from api.services import bank_registry, replica, runtime_layout

    if (os.environ.get(runtime_layout.REPLICA_ENV) or "").strip():
        _note("pinned", pinned_by_environment() or "")
        return
    name, path, bank_id = bank_registry._active_record(Path(_settings().memory_root))   # noqa: SLF001
    frame = replica.home_frame() or {}
    _write_json(_sync_root(create=True) / PROMOTE, {
        "bank": name, "bankPath": str(path), "bankId": bank_id, "term": rec.term, "me": my_device_id(),
        "schedule": frame.get("schedule"), "rows": registry(memory_path), "at": time.time()})
    replica.stop(timeout=0.2)   # the process is started again in a moment: no thread needs waiting for
    _finish_promote()
    restart_in_place()


def _finish_promote() -> bool:
    from api.services import bank_registry, device_tokens, replica, runtime_layout, sync_publish

    journal = _read_json(_sync_root() / PROMOTE)
    if not journal:
        return False
    home = runtime_layout.cicada_home()
    me = journal.get("me")
    device_tokens.store().import_rows(journal.get("rows") or [], me=me)
    token = runtime_layout.replica_token()
    if token:
        _write_line(_sync_root(create=True) / SELF_TOKEN, token)       # the token it sends if it follows again
    root = Path(_settings().memory_root)
    registry_ = bank_registry.load_registry(root)
    record_ = (registry_.get("banks") or {}).get(journal.get("bank"))
    if isinstance(record_, dict):
        record_["replica"] = False
        registry_["active"] = journal.get("bank")
        bank_registry.save_registry(root, registry_)
    path = Path(journal.get("bankPath") or "")
    if path.exists():
        replica.marker_path(path, create=False).unlink(missing_ok=True)
        _adopt_schedule(path, journal.get("schedule"))
    sync_publish.set_enabled(True)
    with replica.MODE_LOCK:
        (home / runtime_layout.REPLICA_FILE).unlink(missing_ok=True)
    (_sync_root() / PROMOTE).unlink(missing_ok=True)
    logger.info(f"home move: this computer is the home now (term {journal.get('term')})")
    return True


def _adopt_schedule(memory_path: Path, schedule: dict | None) -> None:
    """Sleep moves with the home: the schedule the last home ran on (it lives beside the bank, never committed)."""
    if not isinstance(schedule, dict) or not schedule.get("mode"):
        return
    from api.models.schemas import ScheduleConfig
    from api.services import sleep_scheduler

    # A copy never ran Sleep, so whatever schedule file its folder holds is not the person's: the home's wins.
    try:
        sleep_scheduler.save_schedule(memory_path, ScheduleConfig(
            mode=schedule.get("mode"), enabled=bool(schedule.get("enabled")), hour=int(schedule.get("hour") or 3),
            minute=int(schedule.get("minute") or 0), interval_hours=int(schedule.get("intervalHours") or 6)))
    except Exception:  # noqa: BLE001 — the person sets it again on the Sleep page
        pass


def finish_at_start() -> str | None:
    """The backend's first step, before its mode is read: finish a promotion or a demotion cut short, and undo a move
    that closed this home but never committed its record. Returns what it did, or None."""
    try:
        if _finish_promote():
            return "promoted"
        if _finish_demote():
            return "demoted"
        state = handoff()
        if state is None:
            return None
        bank = Path(str(state.get("bank") or ""))
        rec = record(bank) if bank.exists() else None
        phase = state.get("phase")
        if phase in ("leaving", "sealed"):
            if rec is None or rec.term < int(state.get("term") or 0):
                _clear_handoff()
                logger.info("home move: a move cut short before its record was written was called off; this "
                            "computer still holds the memory")
                return "undone"
            _write_json(_sync_root() / HANDOFF, {**state, "phase": "left"})
        elif phase == "superseding":
            # Another device holds the memory under a newer term: closed for good; the writers it admitted are gone
            # with the old process, so it seals and goes on following.
            _write_json(_sync_root() / HANDOFF, {**state, "phase": "superseded"})
        return "closed"
    except Exception as exc:  # noqa: BLE001 — never keeps the backend from starting
        logger.warning(f"home move: could not finish a hand-off at start ({type(exc).__name__})")
        return None


def at_start(memory_path: Path) -> None:
    """The home's lifespan, once: while this computer shares its memory, watch the group for a newer home, go on with
    a hand-off it already recorded, and drop journal lines past their 8 days. Shares nothing: nothing at all."""
    from api.services import admitted_log, sync_publish

    if not sync_publish.publishable(memory_path):
        return
    start_peer_watch(memory_path)
    resume_after_start(memory_path)
    admitted_log.prune(memory_path)
    from api.services import runtime_layout

    if (runtime_layout.cicada_home() / "spool" / "tx").is_dir():
        threading.Thread(target=_flush_own_outbox, name="cicada-home-own-outbox", daemon=True).start()


def _flush_own_outbox() -> None:
    """A computer that just became the home may still hold writes it queued while it was a copy (its home was closed
    to move them): they are applied here now, in order, through this computer's own doors, each keyed once — sent with
    its own device token to its own loopback backend, as a copy sends to its home."""
    import urllib.request

    from api.services import replica, runtime_layout, tx_outbox

    if not tx_outbox.entries():
        return
    base = runtime_layout.local_backend_url()
    for _ in range(60):                      # the backend is starting: wait until it answers
        try:
            with urllib.request.urlopen(f"{base}/healthz", timeout=2):
                break
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    env = {"CICADA_REPLICA_OF": base, "CICADA_HOME": str(runtime_layout.cicada_home())}

    def here(entry):
        try:
            return replica._send(entry, environ=env)   # noqa: SLF001
        except replica.NoDeviceToken:
            return None, None

    try:
        tx_outbox.flush(here, deadline_s=120.0)
    except Exception as exc:  # noqa: BLE001 — tried again at the next start
        logger.info(f"home move: own outbox flush skipped ({type(exc).__name__})")


def resume_after_start(memory_path: Path) -> None:
    """A home closed by a move whose record is written goes on waiting for the new home (after a restart)."""
    state = handoff()
    if not state or state.get("phase") not in ("left", "superseding", "superseded"):
        return
    to = state.get("to") or {}
    if not to.get("address"):
        return
    if state.get("phase") in ("superseding", "superseded"):
        target = _superseded_demote
    else:
        target = _wait_and_demote
    threading.Thread(target=target, args=(Path(memory_path), to, int(state.get("term") or 0)),
                     name="cicada-home-demote", daemon=True).start()


def restart_in_place(memory_path: Path | None = None) -> None:
    """Start this backend again in a moment (the same process image, ``os.execv``), so its new part — the home, or a
    replica — is the one it starts in. Whatever started it (the background service, the app) keeps it."""
    import sys

    def again():
        time.sleep(0.3)
        os.execv(sys.executable, list(getattr(sys, "orig_argv", None) or [sys.executable, *sys.argv]))

    threading.Thread(target=again, name="cicada-restart", daemon=True).start()


# --- a lost home: the person's take-over ---------------------------------------------------------------------------------

def take_over_preview(memory_path: Path) -> dict:
    """What the person sees before they confirm: how far behind this copy is of the last home it saw, and when, and
    whether that home answers now (then it is a move, not a take-over)."""
    from api.services import replica, runtime_layout

    if not runtime_layout.is_replica():
        if role(memory_path) == "left":
            return _take_back_preview(memory_path)
        return {"possible": False, "code": "not_a_copy", "text": "This computer holds no copy to take over with."}
    pinned = pinned_by_environment()
    if pinned:
        return {"possible": False, "code": "pinned", "text": pinned}
    state = replica.state()
    rec = record(memory_path)
    home_name = _home_name(memory_path, rec)
    try:
        status, _h, _b = replica.request("GET", "/sync/peer", timeout=PEER_TIMEOUT_S)
    except replica.NoDeviceToken:
        status = None
    if status == 200:
        return {"possible": False, "code": "home_reachable", "home": home_name,
                "text": f"{home_name} answers, so it is not lost: move your memory from the Sleep page instead."}
    seq = state.get("seq") or 0
    last_home = state.get("homeSeq") if isinstance(state.get("homeSeq"), int) else seq
    behind = max(0, last_home - seq)
    seen = state.get("lastContact") or state.get("appliedAt")     # after a restart: when it last caught up
    when = _when(seen)
    text = (f"This computer is {behind} change{'s' if behind != 1 else ''} behind the last home it saw, "
            f"{home_name}, {when}. If you take over, those changes are not in your memory here; if {home_name} "
            f"comes back, what it changed is offered to this computer, never merged.")
    return {"possible": True, "behind": behind, "lastSeenAt": seen, "home": home_name, "seq": seq, "text": text}


def _take_back_preview(memory_path: Path) -> dict:
    """A home that recorded a move whose target never took over (it died for good after the record) may take its
    memory back: nothing is behind — it made the last change — but only while the target does not answer as the
    home (then the move is simply finishing)."""
    state = handoff() or {}
    to = state.get("to") or {}
    status, peer = _ask(to.get("address") or "", "/sync/peer", _own_token()) if to.get("address") else (None, None)
    if status == 200 and isinstance(peer, dict) and peer.get("role") == "home":
        return {"possible": False, "code": "home_reachable", "home": to.get("name"),
                "text": f"{to.get('name')} holds your memory now; this computer follows it in a moment."}
    return {"possible": True, "behind": 0, "lastSeenAt": None, "home": to.get("name"), "seq": None, "takeBack": True,
            "text": f"Your memory was moving to {to.get('name') or 'another computer'}, which has not taken over. "
                    f"This computer made the last change, so nothing is behind. If {to.get('name') or 'it'} comes "
                    f"back, what it changed is offered to this computer, never merged."}


def _when(iso: str | None) -> str:
    if not iso:
        return "at a time this computer did not record"
    try:
        moment = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return "at a time this computer did not record"
    seconds = max(0, int((datetime.now(timezone.utc) - moment).total_seconds()))
    if seconds < 90:
        return "a moment ago"
    if seconds < 5400:
        return f"{seconds // 60} minutes ago"
    if seconds < 172800:
        return f"{seconds // 3600} hours ago"
    return f"on {moment.strftime('%Y-%m-%d')}"


def _home_name(memory_path: Path, rec) -> str:
    if rec is not None and rec.to:
        return rec.to_name
    own = next((r for r in load_mirror(memory_path) if r.get("is_self")), None)
    return str((own or {}).get("name") or "the computer that held your memory")


def take_over(memory_path: Path, *, behind_seen: int | None) -> dict:
    """The person confirmed: this replica writes and signs the take-over record (the take-over point = its own head)
    and becomes the home. ``behind_seen`` is the number they were shown; if it changed, they are shown again."""
    from api.services import device_status, home_record, replica, replica_guard, sync_log

    preview = take_over_preview(memory_path)
    if not preview.get("possible"):
        raise MoveRefused(preview.get("code") or "refused", preview.get("text") or "")
    if behind_seen is None or int(behind_seen) != int(preview["behind"]):
        raise MoveRefused("changed", "How far behind this computer is changed since you looked; look again before "
                                     "you confirm.")
    if preview.get("takeBack"):
        return _take_back(memory_path, preview)
    me = my_device_id()
    if not me:
        raise MoveRefused("no_token", replica.TEXTS["no_token"])
    pin = _pin()
    rec_now = record(memory_path)
    lost = rec_now.to if rec_now is not None else (next((r.get("id") for r in load_mirror(memory_path)
                                                          if r.get("is_self")), None))
    replica.stop(timeout=0.2)   # the process is started again in a moment: no thread needs waiting for
    with replica.MODE_LOCK, replica_guard.applying():
        seq = sync_log.head_seq(memory_path) or 0
        rec = home_record.make(bank_id=pin.id if pin is not None else "", term=term(memory_path) + 1,
                               kind="take-over", seq=seq, after=_head(memory_path),
                               source={"device": lost, "name": preview.get("home")},
                               to={"device": me, "name": device_status.machine_name()}, signer=me)
        home_record.commit(memory_path, rec, subject=f"Taken over by {device_status.machine_name()}")
    logger.info(f"home move: this computer took over (term {rec.term}, {preview['behind']} behind)")
    promote(memory_path, rec)
    return {"took": True, "term": rec.term, "behind": preview["behind"]}


def _take_back(memory_path: Path, preview: dict) -> dict:
    """The old home takes its memory back (the person confirmed): a take-over record of the next term naming itself,
    signed, committed alone; then it admits again — it is already the home in every other respect."""
    from api.services import device_status, home_record, replica_guard, sync_log

    state = handoff() or {}
    to = state.get("to") or {}
    me = ensure_own_identity()
    pin = _pin()
    with replica_guard.applying():
        seq = sync_log.head_seq(memory_path) or 0
        rec = home_record.make(bank_id=pin.id if pin is not None else "", term=term(memory_path) + 1,
                               kind="take-over", seq=seq, after=_head(memory_path),
                               source={"device": to.get("device"), "name": to.get("name")},
                               to={"device": me, "name": device_status.machine_name()}, signer=me)
        home_record.commit(memory_path, rec, subject=f"Taken back by {device_status.machine_name()}")
    _clear_handoff()
    _PROGRESS.clear()
    logger.info(f"home move: this computer took its memory back (term {rec.term})")
    return {"took": True, "term": rec.term, "behind": 0, "takeBack": True}


# --- a replica whose home is gone looks for the new one ----------------------------------------------------------------

def find_home(memory_path: Path) -> str | None:
    """A replica whose home has not answered for a while asks the other devices of the group (the registry it
    mirrored, each at the address it gave): the first that is the home of this memory under a newer record — or the
    one this copy's own record names — is followed from now on. Returns its address, or None."""
    from api.services import runtime_layout

    pin = _pin()
    rec = record(memory_path)
    mine = rec.term if rec is not None else 0
    token = _own_token()
    if not token:
        return None
    me = my_device_id()
    try:
        current = runtime_layout.replica_of().rstrip("/")
    except ValueError:
        current = ""
    for r in registry(memory_path):          # its own store too: an old home that follows knows the group
        address = (r.get("address") or "").rstrip("/")
        if r.get("revoked_at") or r.get("kind") not in (None, "full") or not address or r.get("id") == me \
                or address == current:
            continue
        status, peer = _ask(address, "/sync/peer", token)
        if status != 200 or not isinstance(peer, dict) or peer.get("bankId") != (pin.id if pin else None):
            continue
        theirs = int(peer.get("term") or 0)
        if peer.get("role") == "home" and (theirs > mine or (rec is not None and peer.get("device") == rec.to)):
            if (os.environ.get(runtime_layout.REPLICA_ENV) or "").strip():
                _note("pinned", pinned_by_environment() or "")
                return None
            repoint(address)
            logger.info(f"home move: found the home under term {theirs}; following it")
            return address
    return None


def announce_body(memory_path: Path, seq: int | None) -> dict:
    """What a replica tells its home about itself (``POST /sync/devices/me``)."""
    from api.services import device_key

    pin = _pin()
    return {"signKey": device_key.public_jwk(create=True), "address": own_address() or "",
            "bankId": pin.id if pin is not None else None, "seq": seq}


# --- the old home comes back -------------------------------------------------------------------------------------------

_PEER_THREAD: list[threading.Thread] = []
_PEER_STOP = threading.Event()


def start_peer_watch(memory_path: Path) -> None:
    """While this computer publishes and is the home: ask the group, at its start and every minute, whether another
    device holds the memory under a newer record (a take-over made while this one was away)."""
    if any(t.is_alive() for t in _PEER_THREAD):
        return
    _PEER_STOP.clear()
    t = threading.Thread(target=_peer_loop, args=(Path(memory_path),), name="cicada-home-peers", daemon=True)
    _PEER_THREAD[:] = [t]
    t.start()


def stop_peer_watch() -> None:
    _PEER_STOP.set()


def _peer_loop(memory_path: Path) -> None:
    _PEER_STOP.wait(2.0)
    while not _PEER_STOP.is_set():
        try:
            if role(memory_path) == "home":
                check_peers(memory_path)
        except Exception as exc:  # noqa: BLE001
            logger.info(f"home move: peer check skipped ({type(exc).__name__})")
        _PEER_STOP.wait(PEER_EVERY_S)


def check_peers(memory_path: Path) -> dict | None:
    """Ask each device of the group that has an address whether it is the home of this memory under a newer term. The
    first that is: this computer stops ordering writes at once and follows it. Returns that peer's answer, or None."""
    from api.services import device_tokens

    pin = _pin()
    mine = term(memory_path)
    token = _own_token()
    if not token:
        return None
    me = my_device_id()
    for device in device_tokens.store().list():
        if not device.active or device.kind != "full" or not device.address or device.id == me:
            continue
        status, peer = _ask(device.address, "/sync/peer", token)
        if status != 200 or not isinstance(peer, dict) or peer.get("bankId") != (pin.id if pin else None):
            continue
        if peer.get("role") == "home" and int(peer.get("term") or 0) > mine:
            to = {"device": peer.get("device") or device.id, "name": device.name, "address": device.address}
            logger.info(f"home move: {device.id} holds this memory under a newer term; following it")
            _close(memory_path, "superseding", to, int(peer.get("term") or 0))   # the doors at once
            threading.Thread(target=_superseded_demote, args=(memory_path, to, int(peer.get("term") or 0)),
                             name="cicada-home-demote", daemon=True).start()
            return peer
    return None


def _superseded_demote(memory_path: Path, to: dict, new_term: int) -> None:
    """Superseded: wait out the writers already admitted, carry what is uncommitted into the set-aside range, follow."""
    from api.services import replica_guard, write_admission

    _park_sleep(memory_path)
    write_admission.wait_for_writers(memory_path, give_up_after=WRITERS_MAX_S)
    _close(memory_path, "superseded", to, new_term)               # sealed: the admitted writers are done
    try:
        with replica_guard.applying():
            carry_uncommitted(memory_path)
    except Exception as exc:  # noqa: BLE001 — set aside as it is
        logger.info(f"home move: nothing carried ({type(exc).__name__})")
    demote(memory_path, to, new_term)


# --- what an old home made after the take-over point: set aside, offered back ------------------------------------------

def reconcile(memory_path: Path, bundle: Path) -> dict | None:
    """The follower met a home whose history does not contain this copy's head (``unknown_base``). When the home's
    record is newer than this copy's and its take-over point is in this copy's history, the commits past that point
    are set aside on ``refs/cicada/set-aside/term-<n>`` — never merged, never dropped — and offered back as
    transactions; the copy then takes the home's history. Returns the summary (words, counts), or None when the
    copy simply diverged (the person's "Copy again")."""
    from api.services import git_service, replica_guard, tx_outbox

    memory_path = Path(memory_path)
    with git_service.write_lock(memory_path), replica_guard.applying():
        git_service._git_sync(memory_path, "fetch", "-q", "--no-tags", "--no-write-fetch-head", str(bundle),   # noqa: SLF001
                              f"+HEAD:{git_service.HOME_REF}")
    theirs = record(memory_path, git_service.HOME_REF)
    mine = record(memory_path)
    if theirs is None or theirs.term <= (mine.term if mine is not None else 0) or not theirs.after:
        return None
    rows = _rows_with_signer(memory_path, theirs)
    if _check(theirs, rows):
        return None
    old = _head(memory_path)
    if not (_is_ancestor(memory_path, theirs.after, old) and _is_ancestor(memory_path, theirs.after,
                                                                          git_service.HOME_REF)):
        return None
    orphans = [c for c in _git_read(memory_path, "rev-list", "--first-parent", f"{theirs.after}..{old}").split() if c]
    me = my_device_id()
    was_home = bool(mine is None or (mine.to == me)) and bool(me) and theirs.source == me
    offers = _offers(memory_path, theirs, old, was_home=was_home or _has_journal(memory_path))
    ref = f"{SET_ASIDE_REF}/term-{theirs.term}"
    with git_service.write_lock(memory_path), replica_guard.applying():
        if orphans:
            git_service._git_sync(memory_path, "update-ref", ref, old)   # noqa: SLF001
        git_service.fast_forward_sync(memory_path, bundle, rewrite=True)
    for entry in offers["entries"]:
        tx_outbox.keep(entry)
    from api.services import admitted_log

    admitted_log.clear(memory_path)
    summary = {"term": theirs.term, "home": theirs.to_name, "ref": ref if orphans else None,
               "commits": len(orphans), "episodes": offers["episodes"], "calls": offers["calls"],
               "at": time.time(), "wasHome": offers["wasHome"]}
    summary["text"] = set_aside_text(summary)
    _write_json(_set_aside_path(memory_path), summary)
    logger.info(f"home move: {len(orphans)} commits set aside, {offers['episodes']} episodes and {offers['calls']} "
                f"calls offered to the new home")
    return summary


def set_aside_text(s: dict) -> str:
    n, home = int(s.get("commits") or 0), s.get("home") or "the new home"
    if n == 0 and not s.get("episodes") and not s.get("calls"):
        return f"{home} took over; nothing made here was left out."
    plural = "s" if n != 1 else ""
    lead = (f"{n} change{plural} made on this computer after {home} took over" if s.get("wasHome")
            else f"{n} change{plural} this copy had that {home} never received")
    sent = []
    if s.get("episodes"):
        sent.append(f"{s['episodes']} conversation{'s' if s['episodes'] != 1 else ''} and note"
                    f"{'s' if s['episodes'] != 1 else ''}")
    if s.get("calls"):
        sent.append(f"{s['calls']} other change{'s' if s['calls'] != 1 else ''}")
    tail = (f" {' and '.join(sent)} were sent to {home} to apply; what Sleep wrote from them, {home} writes again "
            f"when it reads them." if sent else " None of them could be sent as a change to apply.")
    return f"{lead} {'are' if n != 1 else 'is'} kept aside here, never merged.{tail}"


def _set_aside_path(memory_path: Path) -> Path:
    from api.services import sync_publish

    return sync_publish.bank_dir(memory_path, create=True) / SET_ASIDE


def set_aside(memory_path: Path) -> dict | None:
    return _read_json(_set_aside_path(memory_path))


def _has_journal(memory_path: Path) -> bool:
    from api.services import admitted_log

    return bool(admitted_log.entries(memory_path))


def _is_ancestor(memory_path: Path, a: str, b: str) -> bool:
    try:
        return subprocess.run(["git", "merge-base", "--is-ancestor", a, b], cwd=str(memory_path),
                              capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _git_read(memory_path: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=str(memory_path), capture_output=True,
                              timeout=120).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return ""


def _offers(memory_path: Path, theirs, old: str, *, was_home: bool) -> dict:
    """The transactions that offer the set-aside range back: first the calls this computer admitted as the home
    after the take-over point (``admitted_log``; a copy that never was the home has none), then every episode the
    range added or changed, through the new home's own episode writer (``POST /capture/offered``)."""
    from api.services import admitted_log, git_service, tx_outbox

    bank_id = theirs.bank_id
    entries: list[dict] = []
    calls = 0
    if was_home:
        for e in admitted_log.entries(memory_path, since_seq=theirs.seq):
            key = hashlib.sha256(json.dumps(e, sort_keys=True).encode("utf-8")).hexdigest()[:32]
            if e.get("kind") == "tool":
                entries.append(tx_outbox.tool_entry(e.get("tool"), e.get("arguments") or {}, bank_id=bank_id,
                                                    base_seq=None, caller=e.get("caller") or {},
                                                    surface=e.get("surface") or "mcp", options=e.get("options") or {},
                                                    key=key))
            elif e.get("kind") == "rest":
                try:
                    entries.append(tx_outbox.rest_entry(e["method"], e["path"], e.get("query") or "",
                                                        base64.b64decode(e.get("body") or ""), e.get("contentType"),
                                                        bank_id=bank_id, base_seq=None, key=key))
                except (KeyError, ValueError):
                    continue
            else:
                continue
            calls += 1
    fields = [f for f in _git_read(memory_path, "diff", "--name-status", "-z", "--no-renames", theirs.after, old,
                                   "--", "episodes/").split("\0") if f]
    paths = [p for status, p in zip(fields[0::2], fields[1::2])
             if not status.startswith("D") and p.startswith("episodes/ep_") and p.endswith(".md")]
    blobs = git_service._blobs_at(memory_path, old, paths) if paths else {}   # noqa: SLF001
    me = my_device_id()
    episodes = 0
    for rel in paths:
        text = blobs.get(rel)
        if not text:
            continue
        body = json.dumps({"episode": text.decode("utf-8", "replace"), "from": me, "term": theirs.term}).encode()
        key = hashlib.sha256(f"{bank_id}|{rel}|{hashlib.sha256(text).hexdigest()}".encode()).hexdigest()[:32]
        try:
            entries.append(tx_outbox.rest_entry("POST", "/capture/offered", "", body, "application/json",
                                                bank_id=bank_id, base_seq=None, key=key))
            episodes += 1
        except ValueError:
            continue
    return {"entries": entries, "calls": calls, "episodes": episodes, "wasHome": was_home}


# --- the Sleep page ------------------------------------------------------------------------------------------------------

def overview(memory_path: Path) -> dict:
    """``GET /sync/home``: the device that runs consolidation (the home) with its state, every other device with
    whether it is online and how far behind its copy is, and what a move or a take-over would say. One computer that
    shares nothing gets ``{"shared": false}`` and the Sleep page shows nothing new."""
    from api.services import demo_guard, device_status, replica, sync_log

    me_role = role(memory_path)
    if me_role == "local" or demo_guard.is_demo(memory_path):
        return {"shared": False, "role": me_role}
    pin = _pin()
    rec = record(memory_path)
    me = my_device_id() if me_role != "home" else ensure_own_identity()
    rows = registry(memory_path)
    now = datetime.now(timezone.utc)
    if me_role == "replica":
        state = replica.state()
        home_seq = state.get("homeSeq") if isinstance(state.get("homeSeq"), int) else state.get("seq")
        home_id = rec.to if rec is not None else next((r.get("id") for r in rows if r.get("is_self")), None)
        home_online = state.get("status") == "following"
        home_sleep = replica.home_sleep() or {}
    else:
        home_seq = sync_log.head_seq(memory_path)
        home_id = (rec.to if me_role in CLOSED_ROLES and rec is not None and rec.to != me else me)
        home_online = me_role == "home"
        home_sleep = None
    home_row = row(rows, home_id) or {}
    devices = []
    for r in rows:
        if r.get("revoked_at") or r.get("kind") not in (None, "full") or r.get("id") == home_id:
            continue
        if r.get("copy_bank_id") and pin is not None and r.get("copy_bank_id") != pin.id:
            continue
        keeps = bool(r.get("copy_bank_id"))
        seen = _parse(r.get("copy_at")) or _parse(r.get("last_used_at"))
        online = bool(seen and (now - seen).total_seconds() <= ONLINE_WITHIN_S)
        behind = None
        if keeps and isinstance(home_seq, int) and isinstance(r.get("copy_seq"), int):
            behind = max(0, home_seq - r["copy_seq"])
        if r.get("id") == me and me_role == "replica":
            state = replica.state()
            behind, online = state.get("behind"), True
        devices.append({"id": r.get("id"), "name": r.get("name"), "me": r.get("id") == me, "online": online,
                        "keepsCopy": keeps, "behind": behind, "lastSeenAt": _iso(seen),
                        "canBeHome": keeps and bool(r.get("address")) and me_role in ("home", "replica")})
    body = {"shared": True, "role": me_role, "bankId": pin.id if pin is not None else None,
            "term": rec.term if rec is not None else 0,
            "home": {"id": home_id, "name": home_row.get("name") or (device_status.machine_name() if me_role != "replica"
                                                                     else _home_name(memory_path, rec)),
                     "me": home_id == me, "online": home_online, "seq": home_seq,
                     "sleep": _sleep_summary(home_sleep if me_role == "replica" else None)},
            "devices": sorted(devices, key=lambda d: (not d["me"], str(d.get("name") or ""))),
            "moving": None, "takeOver": None, "setAside": set_aside(memory_path), "note": notes() or None}
    phase = _PROGRESS.get("phase")
    recent = time.time() - float(_PROGRESS.get("updatedAt") or 0) < REFUSAL_SHOWN_S
    if me_role in CLOSED_ROLES:
        body["moving"] = {**progress(), "phase": me_role, "text": closed_text()}
    elif phase in ("starting", "catching_up") or (phase == "refused" and recent):
        body["moving"] = {**progress(), "phase": phase, "text": _PROGRESS.get("text")}
    if me_role == "left" and time.time() - float((handoff() or {}).get("startedAt") or time.time()) > TAKE_BACK_AFTER_S:
        to_name = ((handoff() or {}).get("to") or {}).get("name") or "the other computer"
        body["takeOver"] = {"possible": True, "behind": 0, "lastSeenAt": None,
                            "text": f"{to_name} has not taken over yet. If it is lost, this computer can take your "
                                    f"memory back; it made the last change, so nothing is behind."}
    if me_role == "replica":
        # Review of #570: a move pressed on a copy runs at the home, so this process's progress knows nothing of it —
        # the home's own words are asked for (3 s; away, the app keeps its own "moving" until a poll shows the new home).
        if body["moving"] is None:
            body["moving"] = _home_moving()
        state = replica.state()
        if state.get("status") in ("offline", "error"):
            body["takeOver"] = {"possible": True, "behind": max(0, (home_seq or 0) - (state.get("seq") or 0)),
                                "lastSeenAt": state.get("lastContact"),
                                "text": "The computer that held your memory is not answering. If it is lost, this "
                                        "computer can take over; you see how far behind it is first."}
    return body


def _home_moving() -> dict | None:
    """The home's ``moving`` block, as its own ``GET /sync/home`` says it (a copy's overview), or None."""
    from api.services import replica

    try:
        status, _h, body = replica.request("GET", "/sync/home", timeout=3)
    except Exception:  # noqa: BLE001 — no token, away: nothing to say
        return None
    moving = (body or {}).get("moving") if status == 200 and isinstance(body, dict) else None
    return moving if isinstance(moving, dict) else None


def _sleep_summary(home_sleep: dict | None) -> dict:
    """The home's Sleep in a few keys (status, stage, waiting) — the home's own when this computer is the home."""
    if home_sleep is None:
        from api.services import sleep_cycle

        st = sleep_cycle.get_sleep_state()
        return {"status": st.status, "stage": st.stage, "totalStages": st.total_stages}
    return {k: home_sleep.get(k) for k in ("status", "stage", "totalStages", "unprocessedCount", "writing")
            if k in home_sleep}


def _parse(value) -> datetime | None:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _iso(moment: datetime | None) -> str | None:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if moment else None
