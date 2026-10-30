"""The capture commit: while the home publishes, the episodes the capture writers wrote are committed (ruling 51e1).

**Why.** The session, turn and relay capture paths (``transcript_capture``, ``turn_capture``, ``relay_capture``, all
through ``transcript_capture.write_session``) write the episode file and make no commit; Sleep's batch ``add -A`` or a
poll's sweep commits it later. A replica follows commits, so without this its consolidation queue would differ from
the home's (51d).

**What.** Only while publishing is on (``sync_publish.publishable``) — off, nothing here runs or is written:

* ``write_session`` calls :func:`note_written` right after its own write, under the bank's episode lock, with what
  the file held before. The record is the path, the sha256 of the bytes the writer wrote, when, and the hash of what
  the path held before this writer's chain of writes began (its *base*). Records live outside every bank,
  ``$CICADA_HOME/sync/<bank key>/captured.json`` (paths, hashes and times — never a title or a word of the episode);
  the base's bytes are held in memory only, for the kept-apart case below.
* A debounced background step (:func:`sweep`) commits a path once it has settled for :data:`SETTLE_S` and at most once
  per :data:`MIN_INTERVAL_S` per bank (every due path in one commit), **only while the file still hashes to what the
  writer recorded** — the bytes it reads and checks are the bytes it commits (a private index, ``git_service.
  commit_contents_sync``), so a later edit is never swept in. It commits as ``cicada`` with trigger ``sync/capture``,
  holds write admission shared (G183), is skipped while Sleep is writing (G177), and never touches another path or
  ``_state.md``.
* **Another author's edit stays theirs.** A path whose hash no longer matches (the person's hand edit, another writer)
  is dropped from the records and left uncommitted. When the writer's base was itself someone else's uncommitted edit
  (HEAD holds something else), that edit is committed first, alone, as ``Uncommitted edit kept apart <date>`` with no
  author — ``agent_commits``' rule — and the capture commit carries only the writer's change; if the base's bytes are
  gone (a restart), the path is left for Sleep as before. **Kept apart is only ever bytes that are neither committed
  nor a capture writer's** (review of #565): the record keeps every hash its chain wrote (hashes only), and HEAD
  holding the base or any of them — a poll's or a Sleep batch's ``add -A`` committed one of our writes — is clean, so
  an older state is never committed back on top of a newer one.

**Debounce, measured** (owner-bank copy, 28 captured sessions, 1,090 reply gaps; one write per agent reply): gaps p10
34 s, p50 211 s. A 10 s settle alone gives a session's busiest hour p50 8 / p90 25 / max 54 commits; with a 60 s
minimum interval p50 8 / p90 24 / max 41 — one commit per reply at a normal pace, bursts coalesced. A replica's queue
lags the home by at most about 70 s.

Lock order (``write_admission``): admission, then git's write lock, then the episode lock — and the records' own lock
is never held across any of them.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from loguru import logger

from api.services import sync_publish

SETTLE_S = 10.0
MIN_INTERVAL_S = 60.0
RECORDS_FILE = "captured.json"
TRIGGER = "sync/capture"
KEPT_TRIGGER = "sync/kept-apart"
#: How often the background step looks while records wait (it stops when none do).
_TICK_MIN_S = 0.5
_TICK_MAX_S = 15.0
#: Off in a test that drives :func:`sweep` itself.
AUTOSTART = True
_MISSING = object()


@dataclass
class _Rec:
    hash: str
    at: float
    base: str | None   # sha256 of what the path held before this chain of capture writes; None: the writer made it
    #: Every hash this chain's capture writes produced (the latest included). HEAD holding any of them means another
    #: writer's ``add -A`` (a poll, a Sleep batch) committed one of OUR writes: nothing foreign sits under the chain.
    chain: tuple[str, ...] = ()
    #: The chain outgrew :data:`CHAIN_MAX` and forgot its oldest hashes (see :func:`note_written`).
    overflow: bool = False

    def clean_against(self, head_hash: str | None) -> bool:
        """Nothing uncommitted and foreign lies under this chain, given what HEAD holds at the path: the writer made
        the file, or HEAD holds the base or any hash the chain itself wrote."""
        if self.base is None:
            return True
        return head_hash is not None and (head_hash == self.base or head_hash in self.chain)


#: Bound on a chain's remembered hashes (one per capture write since the last capture commit).
CHAIN_MAX = 512


class _Bank:
    def __init__(self, memory_path: Path):
        self.memory_path = memory_path
        self.lock = threading.Lock()
        self.records: dict[str, _Rec] = {}
        self.base_bytes: dict[str, bytes] = {}
        self.last_commit_at = 0.0
        self.loaded = False


_BANKS: dict[str, _Bank] = {}
_GUARD = threading.Lock()
_WAKE = threading.Condition()
_THREAD: threading.Thread | None = None


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _bank(memory_path) -> _Bank:
    key = os.path.realpath(os.fspath(memory_path))
    with _GUARD:
        bank = _BANKS.get(key)
        if bank is None:
            bank = _BANKS[key] = _Bank(Path(memory_path))
    return bank


def _records_path(memory_path) -> Path:
    return sync_publish.bank_dir(memory_path) / RECORDS_FILE


def _load(bank: _Bank) -> None:
    """Called with ``bank.lock`` held: the records a previous process left (their bases' bytes are gone with it)."""
    if bank.loaded:
        return
    bank.loaded = True
    try:
        data = json.loads(_records_path(bank.memory_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    for rel, rec in (data.get("records") or {}).items() if isinstance(data, dict) else ():
        if isinstance(rec, dict) and isinstance(rec.get("hash"), str) and _episode_rel(rel):
            chain = tuple(h for h in (rec.get("chain") or [rec["hash"]]) if isinstance(h, str))
            bank.records[rel] = _Rec(rec["hash"], float(rec.get("at") or 0), rec.get("base"), chain,
                                     bool(rec.get("overflow")))
    bank.last_commit_at = float(data.get("last_commit_at") or 0) if isinstance(data, dict) else 0.0


def _save(bank: _Bank) -> None:
    """Called with ``bank.lock`` held. Atomic, 0600."""
    path = _records_path(bank.memory_path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    payload = {"v": 1, "last_commit_at": bank.last_commit_at,
               "records": {rel: {"hash": r.hash, "at": r.at, "base": r.base, "chain": list(r.chain),
                                 "overflow": r.overflow}
                           for rel, r in bank.records.items()}}
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    os.replace(tmp, path)


def _episode_rel(rel: str) -> bool:
    return rel.startswith("episodes/ep_") and rel.endswith(".md") and "/" not in rel[len("episodes/"):]


def recording(memory_path) -> bool:
    """Should a capture writer record its write? (Publishing on, a git bank, never a demo.)"""
    try:
        return sync_publish.publishable(memory_path)
    except Exception:  # noqa: BLE001 — a record never fails a capture
        return False


def note_written(memory_path, path: Path, *, before: bytes | None, now: float | None = None) -> None:
    """A capture writer wrote ``path`` (an ``episodes/ep_*.md``); ``before`` is what it held just before (``None``: the
    writer created it). Called right after the write, under the bank's episode lock. Never raises."""
    try:
        mp = Path(memory_path)
        rel = f"episodes/{Path(path).name}"
        if not _episode_rel(rel):
            return
        data = Path(path).read_bytes()
        bank = _bank(mp)
        with bank.lock:
            _load(bank)
            prev = bank.records.get(rel)
            before_hash = _sha(before) if before is not None else None
            digest = _sha(data)
            overflow = False
            if prev is not None and before_hash == prev.hash:
                base = prev.base          # the same writer's chain goes on: the base stays where it began
                whole = (*prev.chain, digest)
                chain = whole[-CHAIN_MAX:]
                # Review of #565: past the bound the oldest hashes are forgotten, so "HEAD holds none of ours" can
                # no longer be told apart from "HEAD holds one we forgot" — recorded, and the sweep never keeps
                # anything apart for this chain then.
                overflow = prev.overflow or len(whole) > CHAIN_MAX
            else:
                base = before_hash        # a new chain: whatever was there before is someone's — or HEAD
                chain = (digest,)
                bank.base_bytes.pop(rel, None)
                if before is not None:
                    bank.base_bytes[rel] = before
            bank.records[rel] = _Rec(digest, time.time() if now is None else now, base, chain, overflow)
            _save(bank)
    except Exception as exc:  # noqa: BLE001 — provenance never blocks memory
        logger.info(f"capture commit: record skipped ({type(exc).__name__})")
        return
    _kick(mp)


def pending(memory_path) -> dict[str, str]:
    """``{path: hash}`` of the records waiting (a test and status seam)."""
    bank = _bank(memory_path)
    with bank.lock:
        _load(bank)
        return {rel: r.hash for rel, r in bank.records.items()}


def resume(memory_path) -> None:
    """Pick up records a previous process left (the publishing routes call it). Cheap when there are none."""
    if not recording(memory_path):
        return
    bank = _bank(memory_path)
    with bank.lock:
        _load(bank)
        waiting = bool(bank.records)
    if waiting:
        _kick(memory_path)


def _message(paths: list[str], new: set[str]) -> str:
    from api.services import git_service

    return git_service.build_commit_message(
        f"Capture {date.today().isoformat()}",
        [f"{p}: {'created' if p in new else 'updated'} (source: n/a, trigger: {TRIGGER})" for p in sorted(paths)],
        authors=["cicada"])


def _kept_message(paths: list[str]) -> str:
    from api.services import git_service

    return git_service.build_commit_message(
        f"Uncommitted edit kept apart {date.today().isoformat()}",
        [f"{p}: updated (trigger: {KEPT_TRIGGER})" for p in sorted(paths)])


def next_due(memory_path) -> float | None:
    bank = _bank(memory_path)
    with bank.lock:
        if not bank.records:
            return None
        return max(min(r.at for r in bank.records.values()) + SETTLE_S, bank.last_commit_at + MIN_INTERVAL_S)


def sweep(memory_path, *, now: float | None = None, everything: bool = False) -> int:
    """Commit the settled capture writes of one bank; the number of commits made (0, 1, or 2 with a kept-apart edit).
    Skipped (0) while Sleep holds the pages, while publishing is off, or before anything is due. ``everything`` (G132
    phase 2: the home is handing off, closed to writes) commits every recorded path now, settled or not."""
    from api.services import episode_ids, git_service, write_admission

    mp = Path(memory_path)
    now = time.time() if now is None else now
    if not recording(mp):
        return 0
    bank = _bank(mp)
    with bank.lock:
        _load(bank)
        if not everything and now - bank.last_commit_at < MIN_INTERVAL_S:
            return 0
        due = {rel: _Rec(r.hash, r.at, r.base, r.chain, r.overflow) for rel, r in bank.records.items()
               if everything or now - r.at >= SETTLE_S}
        bases = {rel: bank.base_bytes.get(rel, _MISSING) for rel in due}
    if not due or write_admission.probe():
        return 0
    ours: dict[str, bytes] = {}
    kept: dict[str, bytes] = {}
    new: set[str] = set()
    drop: set[str] = set()
    made = 0
    try:
        with write_admission.admitted(mp), git_service.write_lock(mp):
            with episode_ids.episode_lock(mp / "episodes"):
                for rel, rec in due.items():
                    try:
                        data = (mp / rel).read_bytes()
                    except OSError:
                        drop.add(rel)
                        continue
                    if _sha(data) != rec.hash:
                        drop.add(rel)          # changed after the writer: someone else's edit stays uncommitted
                        continue
                    head = git_service.head_blob_sync(mp, rel)
                    if head == data:
                        drop.add(rel)          # already committed (Sleep's batch, a poll's sweep)
                        continue
                    # Kept apart only bytes that are neither committed nor a capture writer's: clean when the writer
                    # made the file, or HEAD holds the base or any hash this chain wrote (a poll's or a Sleep batch's
                    # `add -A` committed one of our writes — review of #565). Otherwise the bytes it wrote over were
                    # someone's uncommitted edit (or an untracked file): committed first, alone, with no author.
                    if not rec.clean_against(_sha(head) if head is not None else None):
                        before = bases.get(rel, _MISSING)
                        if before is _MISSING or rec.overflow:
                            # Its bytes are gone, or the chain forgot hashes it wrote (overflow): never guess —
                            # left for Sleep's batch, nothing kept apart.
                            drop.add(rel)      # someone's edit was under this write and its bytes are gone
                            continue
                        kept[rel] = before
                    if head is None:
                        new.add(rel)
                    ours[rel] = data
            if kept and git_service.commit_contents_sync(mp, kept, _kept_message(list(kept))):
                made += 1
            if ours and git_service.commit_contents_sync(mp, ours, _message(list(ours), new)):
                made += 1
    except write_admission.SleepHolding:
        return 0
    except Exception as exc:  # noqa: BLE001 — the files stand; Sleep commits them as before
        logger.warning(f"capture commit skipped ({type(exc).__name__}); the episodes stay for Sleep")
        return 0
    with bank.lock:
        for rel in (*ours, *drop):
            rec = bank.records.get(rel)
            if rec is not None and rec.hash == due[rel].hash:   # a newer write since stays recorded
                del bank.records[rel]
                bank.base_bytes.pop(rel, None)
        if ours:
            bank.last_commit_at = now
        _save(bank)
    if made:
        logger.info(f"capture commit: {len(ours)} episode(s){' and a kept-apart edit' if kept else ''}")
    return made


def _kick(memory_path) -> None:
    global _THREAD
    if not AUTOSTART:
        return
    with _WAKE:
        if _THREAD is None or not _THREAD.is_alive():
            _THREAD = threading.Thread(target=_loop, name="cicada-capture-commit", daemon=True)
            _THREAD.start()
        _WAKE.notify_all()


def _loop() -> None:
    """One daemon thread for every bank; it ends when no record waits (nothing is left running)."""
    global _THREAD
    while True:
        with _GUARD:
            banks = [b for b in _BANKS.values() if b.records]
        if not banks:
            with _WAKE:
                with _GUARD:
                    if not any(b.records for b in _BANKS.values()):
                        _THREAD = None
                        return
            continue
        now = time.time()
        waits = []
        for bank in banks:
            due = next_due(bank.memory_path)
            if due is None:
                continue
            if due <= now:
                sweep(bank.memory_path, now=now)
                due = next_due(bank.memory_path)
                if due is not None and due <= now:
                    due = now + _TICK_MAX_S   # skipped (Sleep, a failure): look again later
            if due is not None:
                waits.append(due - now)
            if not recording(bank.memory_path):
                with bank.lock:
                    bank.records.clear()   # publishing went off: nothing more is committed (the file remains)
                    bank.base_bytes.clear()
        if not waits:
            continue   # nothing waits any more: the top of the loop ends the thread
        delay = min(max(min(waits), _TICK_MIN_S), _TICK_MAX_S)
        with _WAKE:
            _WAKE.wait(delay)
