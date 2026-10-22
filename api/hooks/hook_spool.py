"""The client's capture spool (G181 phase 2): what a hook could not deliver, kept under ``$CICADA_HOME`` until the
server answers again.

``$CICADA_HOME/spool/capture/`` (0700), one JSON file per post (0600, written atomically): the route, the full body,
and — for a session — its key and its transcript's path. A session's posts are cumulative (each Stop re-reads the
whole session), so a session keeps ONE entry, the newest (``s-<hash of the key>.json``): a server away for a day
holds one entry per session, not one per reply, and a resend never carries a snapshot older than one already sent.
A per-turn post (Cursor, Gemini CLI) is not cumulative: each is its own entry, flushed in order, and a new turn waits
behind any already waiting so the episode's turn order holds.

A flush sends oldest first while the hook's budget lasts and stops at the first post that does not land because the
server is away or refuses this device; a post the server answered but did not take (a 5xx, a 409) waits on its own —
a session is skipped, a turn holds the turns behind it. A session's resend first re-reads its transcript's SIZE (never its bytes) so the server can tell a
stale snapshot from a replaced file. Bounded: past :data:`MAX_ENTRIES` or :data:`MAX_BYTES` the oldest entries are
dropped and counted in the log — never their content. Nothing here holds a token; the body is the same scrubbed,
capped payload the hook would have sent.

**Each entry names the memory it was captured for** (D1 of the 2026-10-22 two-device test, G202): ``target`` is the
server's address (``runtime_layout.api_base``, normalised) and, when this machine has heard it, the id of the bank
that server last filed this machine's captures in (``.servers``, learned from each answer's ``bankId``). A flush
sends only the entries whose address is the one this machine points at now; the rest wait, never dropped, and are
counted apart (``waiting``) so the hook's log, ``cicada status`` and the app's Devices page can say so. A resend
carries the entry's bank id in its body (``bank_id``), and the server refuses it (409 ``bank_mismatch``) when the bank
it would file it in is another one — so a capture waiting for one memory never lands in another, even behind the same
address (an SSH tunnel's local port pointed at a second server). An entry written before targets existed (``v`` 1)
names nothing and goes to whichever server answers, as it always did.

**A refused bank never blocks the live lane** (review of #408): the server refuses a ``bank_id`` only when it names no
bank of that server's memory (another memory behind the same address; a bank switch on the server itself files the
resend where a live capture would go). A refused entry is *held* (``held_at``): counted as waiting for another memory,
never in front of this server's turns, retried at most every :data:`HOLD_RETRY_S`; and the address's remembered bank
is forgotten, so new entries stop carrying it. A capture that lands teaches the address its bank again.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

MAX_ENTRIES = 2000
MAX_BYTES = 128 * 1024 * 1024
#: Leave this much of the budget unspent: the log line and the process exit come after the last send.
MARGIN_S = 0.3
#: A held entry (its bank refused, ``bank_mismatch``) is tried again at most this often: the memory it was captured
#: for may come back behind this address, and until then a retry is one request, never a block.
HOLD_RETRY_S = 600.0


def spool_dir(home: Path) -> Path:
    path = Path(home) / "spool" / "capture"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    return path


#: Which bank each server last filed this machine's captures in: ``{normalised base: bank id}`` (0600). Not an entry:
#: its name never ends in ``.json``.
SERVERS_FILE = ".servers"


def same_server(a: str | None, b: str | None) -> bool:
    """Two addresses name the same server: scheme and host compared without case, a trailing slash ignored."""
    return bool(a) and bool(b) and _norm(a) == _norm(b)


def _norm(base: str) -> str:
    try:
        parts = urlsplit(str(base).strip())
    except ValueError:
        return str(base).strip()
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}{parts.path.rstrip('/')}"


def host_of(base: str | None) -> str:
    """What a log line or a status line may say about a server: its host (and port), never a path or a credential."""
    try:
        parts = urlsplit(str(base or ""))
        host = parts.hostname or ""
        return f"{host}:{parts.port}" if host and parts.port else host or "another server"
    except ValueError:
        return "another server"


def _read_servers(home: Path) -> dict:
    try:
        data = json.loads((spool_dir(home) / SERVERS_FILE).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def bank_for(home: Path, base: str | None) -> str | None:
    """The bank this server last filed this machine's captures in, or None when it never said."""
    if not base:
        return None
    value = _read_servers(home).get(_norm(base))
    return value if isinstance(value, str) and value else None


def remember_bank(home: Path, base: str | None, bank_id) -> None:
    """A capture landed and the server named its bank (``bankId``): later entries for this server carry it."""
    if not base or not isinstance(bank_id, str) or not bank_id or len(bank_id) > 128:
        return
    servers = _read_servers(home)
    if servers.get(_norm(base)) == bank_id:
        return
    servers[_norm(base)] = bank_id
    folder = spool_dir(home)
    tmp = folder / f".servers.{secrets.token_hex(4)}.tmp"
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, json.dumps(servers).encode("utf-8"))
        finally:
            os.close(fd)
        os.replace(tmp, folder / SERVERS_FILE)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass


def forget_bank(home: Path, base: str | None, bank_id) -> None:
    """The server refused ``bank_id`` (409 ``bank_mismatch``): stop stamping new entries with it — the next capture
    that lands says which bank this address files in now."""
    if not base or not bank_id:
        return
    servers = _read_servers(home)
    if servers.get(_norm(base)) != bank_id:
        return
    servers.pop(_norm(base), None)
    folder = spool_dir(home)
    tmp = folder / f".servers.{secrets.token_hex(4)}.tmp"
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, json.dumps(servers).encode("utf-8"))
        finally:
            os.close(fd)
        os.replace(tmp, folder / SERVERS_FILE)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass


def _held(entry: dict) -> bool:
    return isinstance(entry, dict) and isinstance(entry.get("held_at"), (int, float))


def _due(entry: dict, now: float | None = None) -> bool:
    return not _held(entry) or (now or time.time()) - float(entry["held_at"]) >= HOLD_RETRY_S


def _hold(path: Path, entry: dict) -> None:
    """Mark an entry held (its bank refused), in place and atomically; its body is unchanged."""
    entry = {**entry, "held_at": time.time()}
    tmp = path.parent / f".{path.name}.{secrets.token_hex(4)}.tmp"
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, json.dumps(entry).encode("utf-8"))
        finally:
            os.close(fd)
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass


def mismatch(status, text) -> bool:
    """A 409 whose code is ``bank_mismatch``: the server says this entry's bank is not one of its memory's."""
    if status != 409 or not isinstance(text, str):
        return False
    try:
        return json.loads(text).get("code") == "bank_mismatch"
    except (ValueError, AttributeError):
        return False


def target_for(home: Path, base: str | None) -> dict | None:
    """What a new entry names: the server it was meant for and, when known, that server's bank."""
    if not base:
        return None
    return {"base": base, "bank_id": bank_for(home, base)}


def _target_of(entry: dict) -> dict | None:
    target = entry.get("target") if isinstance(entry, dict) else None
    return target if isinstance(target, dict) and isinstance(target.get("base"), str) and target["base"] else None


def _for(target: dict | None, base: str | None) -> bool:
    """Whether an entry may go to ``base``: one that names no server (written before targets, or while no address was
    set) goes wherever this machine points; one that names a server goes only there."""
    return target is None or base is None or same_server(target["base"], base)


def _name(key: str | None, target: dict | None = None) -> str:
    if key:
        scope = ""
        if target and target.get("base"):
            scope = "\0" + _norm(target["base"]) + "\0" + str(target.get("bank_id") or "")
        return "s-" + hashlib.sha256((key + scope).encode("utf-8")).hexdigest()[:24] + ".json"
    return f"t-{time.time_ns():020d}-{secrets.token_hex(3)}.json"


def put(home: Path, route: str, body: dict, *, key: str | None = None, transcript_path: str | None = None,
        target: dict | None = None) -> int:
    """Keep one post for later, for the server ``target`` names; returns how many old entries the bounds dropped. A
    session keeps one entry per server: a newer snapshot for the same server replaces it, one for another server
    waits beside it."""
    folder = spool_dir(home)
    entry = {"v": 2, "route": route, "body": body, "key": key, "transcript_path": transcript_path,
             "queued_at": time.time(), "target": target}
    data = json.dumps(entry).encode("utf-8")
    path = folder / _name(key, target)
    tmp = folder / f".{path.name}.{secrets.token_hex(4)}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    return _trim(folder, keep=path.name)


def drop(home: Path, key: str, base: str | None = None, bank_ids=()) -> None:
    """A session's newer post landed on ``base``: the older one waiting for that server (filed for one of
    ``bank_ids``, or for no bank in particular) is obsolete, and so is one written before targets existed. One
    waiting for another server, or for another of this server's banks, stays: it was never sent where it was meant."""
    folder = spool_dir(home)
    names = {_name(key)}
    if base:
        names |= {_name(key, {"base": base, "bank_id": b}) for b in (None, *bank_ids)}
    for name in names:
        try:
            (folder / name).unlink()
        except OSError:
            pass


def entries(home: Path) -> list[Path]:
    folder = Path(home) / "spool" / "capture"
    if not folder.is_dir():
        return []          # a read never makes the folder: a machine that never spooled keeps no spool
    found = []
    for p in folder.glob("*.json"):
        try:
            found.append((p.stat().st_mtime_ns, p.name, p))
        except OSError:
            continue
    return [p for _, _, p in sorted(found)]


def pending(home: Path) -> int:
    try:
        return len(entries(home))
    except OSError:
        return 0


def _read(path: Path) -> dict | None:
    try:
        entry = json.loads(path.read_text(encoding="utf-8"))
        return entry if isinstance(entry, dict) else None
    except (OSError, ValueError):
        return None


def waiting(home: Path, base: str | None) -> dict:
    """What waits, by the server it was meant for: ``{"here": n, "elsewhere": {host: n}}``. ``here`` is what a flush to
    ``base`` would send; ``base`` None (this machine is no client now) makes every entry ``elsewhere``, an entry that
    names no server under ``""``. Counts only; nothing of a body is read out."""
    here, elsewhere = 0, {}
    try:
        paths = entries(home)
    except OSError:
        return {"here": 0, "elsewhere": {}}
    for path in paths:
        entry = _read(path) or {}
        target = _target_of(entry)
        if base is not None and _for(target, base) and not _held(entry):
            here += 1
            continue
        host = host_of(target["base"]) if target else ""
        if _held(entry):
            host = f"{host} (another memory)" if host else "another memory"
        elsewhere[host] = elsewhere.get(host, 0) + 1
    return {"here": here, "elsewhere": elsewhere}


def pending_for(home: Path, base: str | None) -> int:
    """How many entries a flush to ``base`` would try now: this server's, plus a held one whose retry is due."""
    count, now = 0, time.time()
    for path in entries(home):
        entry = _read(path) or {}
        if (base is None or _for(_target_of(entry), base)) and _due(entry, now):
            count += 1
    return count


def has_turns(home: Path, base: str | None = None) -> bool:
    """A per-turn post waits for ``base`` (any server when None): a new turn for it queues behind. A held turn (its
    bank refused) waits for its own memory and never holds this server's turns."""
    for path in entries(home):
        if not path.name.startswith("t-"):
            continue
        entry = _read(path) or {}
        if not _held(entry) and (base is None or _for(_target_of(entry), base)):
            return True
    return False


def _trim(folder: Path, *, keep: str) -> int:
    found = []
    total = 0
    for p in folder.glob("*.json"):
        try:
            st = p.stat()
        except OSError:
            continue
        found.append((st.st_mtime_ns, p.name, p, st.st_size))
        total += st.st_size
    found.sort()
    dropped = 0
    while found and (len(found) > MAX_ENTRIES or total > MAX_BYTES):
        _, name, p, size = found.pop(0)
        if name == keep:
            continue
        try:
            p.unlink()
            dropped += 1
            total -= size
        except OSError:
            pass
    return dropped


def flush(home: Path, send: Callable[[str, dict], int | None], *, deadline: float,
          keep: Callable[[int | None], bool], size_of: Callable[[str | None, int], int],
          base: str | None = None) -> tuple[int, int, int]:
    """Send the posts waiting for ``base`` oldest first until one does not land or the budget ends; posts meant for
    another server are never sent here (``base`` None: every post, the behaviour before targets). ``send(route,
    body)`` returns the HTTP status or None. ``(sent, dropped_as_final, left for base)``. One flusher at a time (a
    non-blocking ``flock``): a second hook firing meanwhile leaves the queue to the first."""
    folder = spool_dir(home)
    left = (lambda: pending_for(home, base)) if base is not None else (lambda: pending(home))
    try:
        lock_fd = os.open(folder / ".flush.lock", os.O_WRONLY | os.O_CREAT, 0o600)
    except OSError:
        return 0, 0, left()
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return 0, 0, left()
        sent, final = _flush_locked(home, send, deadline=deadline, keep=keep, size_of=size_of, base=base)
        return sent, final, left()
    finally:
        os.close(lock_fd)


#: Answers that say the SERVER is away or refuses this device — every later post would get the same, so a flush stops.
#: Any other answer that is not final (a 5xx, a 409) is about one post: a session's entry is skipped and kept, so one
#: stuck session never holds back every turn queued behind it (backend hunt, 2026-10-16); a turn waits, and so do
#: the turns behind it, so an episode's turn order holds.
_STOP_ALL = (None, 401, 403)


def _flush_locked(home, send, *, deadline, keep, size_of, base) -> tuple[int, int]:
    sent = final = 0
    turns_waiting = False
    for path in entries(home):
        if time.monotonic() + MARGIN_S >= deadline:
            break
        is_turn = not path.name.startswith("s-")
        if is_turn and turns_waiting:
            continue
        try:
            stamp = path.stat().st_mtime_ns
            entry = json.loads(path.read_text(encoding="utf-8"))
            route, body = entry["route"], entry["body"]
        except (OSError, ValueError, KeyError, TypeError):
            try:
                path.unlink()      # an entry nobody can read is never resent
            except OSError:
                pass
            continue
        target = _target_of(entry)
        if not _for(target, base):
            continue               # meant for another server: it waits for that one (D1, G202)
        held = _held(entry)
        if held and not _due(entry):
            continue               # its memory refused it lately: it waits apart, and never in front of others
        if target and target.get("bank_id") and isinstance(body, dict):
            body["bank_id"] = target["bank_id"]   # the server refuses it if its memory has no such bank
        if entry.get("key") and isinstance(body, dict) and "transcript_bytes" in body:
            body["transcript_size"] = size_of(entry.get("transcript_path"), int(body.get("transcript_bytes") or 0))
        answer = send(route, body)
        status, text = answer if isinstance(answer, tuple) else (answer, "")
        if status is not None and 200 <= status < 300:
            sent += 1
            try:
                remember_bank(home, base, json.loads(text).get("bankId") if text else None)
            except (ValueError, AttributeError):
                pass
        elif mismatch(status, text):
            # Another memory answers at this address: hold the entry for its own, never block this server's lane,
            # and stop stamping new entries with the refused bank (review of #408).
            _hold(path, entry)
            forget_bank(home, base, (target or {}).get("bank_id"))
            continue
        elif held:
            continue               # a held entry's retry that did not land changes nothing else
        elif keep(status):
            if status in _STOP_ALL:
                break
            turns_waiting = turns_waiting or is_turn
            continue
        else:
            final += 1
        try:
            if path.stat().st_mtime_ns == stamp:   # a newer post for the same session replaced it meanwhile: keep that
                path.unlink()
        except OSError:
            pass
    return sent, final
