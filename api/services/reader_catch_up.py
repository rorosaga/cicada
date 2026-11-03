"""What a machine's app is catching up on after it was closed (G229, owner 2026-11-03: "i knew some stuff from sources
like messages, claude conversations and such were going to be pending but there is no syncing indicator").

The backend runs whether or not the app is open, so a harness's Stop hook, a Cursor turn or a connector keeps landing
in ``episodes/`` while the app is closed. Many sources are read only by the app (the capture rail: Messages for ticked
chats, Notes, Calendar, Contacts, the browsers, tab groups, watched folders, Wispr Flow, WhatsApp…), so when it opens
it has a catch-up to do. The app says what its readers are doing (``PUT /sources/catch-up``) and this module holds it,
so every client — the Sleep page and Home on that Mac, another device's Sleep page, Settings → Devices, a future CLI —
reads one answer from ``GET /devices/status`` (each machine's ``catchUp``).

* **In memory, outside every bank, never logged.** A catch-up is a live state of one app session: kept per (reporter,
  bank) — the reporter is the device whose token signed the report, ``None`` for this server's own app — and gone
  with the process. A report left ``reading`` with no word for :data:`READING_TTL_S` (the app quit mid-read) is
  dropped; a finished one is shown for :data:`SHOWN_AFTER_DONE_S`, then dropped.
* **The app says what it reads; the bank says what came in.** The app sends each reader's state (``reading``,
  ``done``, ``failed`` with the reader's own sentence naming the fix — the capture rail's "the exact fix in the app")
  and whether its catch-up is over. It never sends a count: ``arrived`` (waiting conversations and notes whose file
  changed between ``awaySince`` — when the app was last open, as the app remembers it — and ``openedAt``) and
  ``new`` (those that changed since ``openedAt``) are counted here from ``bank_index``'s cached headers, never a body,
  so a harness capture that landed while the app was closed counts as having come in while the person was away. A
  finished catch-up's counts are frozen at its end, so a later capture never moves "caught up" numbers.
* **Waiting only.** Both counts are what waits for Sleep (``history_index.waits_for_model``), the same set as the
  strip's "N waiting": what a scheduled read already took in is not pending. A file's ``mtime`` stands for "came in
  or changed": a Messages day the app appends to is staged in place (``episode_staging``), so ``received_at`` — stamped
  once, at creation — would miss it.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

READING_TTL_S = 15 * 60
SHOWN_AFTER_DONE_S = 10 * 60
#: How far the app's own clock may put ``openedAt`` behind this server's (a launch long ago is a launch now).
MAX_OPENED_AGO_S = 60 * 60
STATES = ("reading", "done", "failed")
MAX_READERS = 64

_lock = threading.Lock()
_state: dict[tuple[str | None, str], "_CatchUp"] = {}


@dataclass
class _CatchUp:
    session: str
    opened_at: datetime
    away_since: datetime | None
    readers: list[dict] = field(default_factory=list)
    done: bool = False
    updated_at: datetime | None = None
    done_at: datetime | None = None
    frozen: tuple[int | None, int] | None = None


def _utc(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _iso(moment: datetime | None) -> str | None:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if moment else None


def _key(reporter: str | None, memory_path: Path) -> tuple[str | None, str]:
    return reporter, str(Path(memory_path))


def reset() -> None:
    """Tests only: forget every catch-up."""
    with _lock:
        _state.clear()


def report(reporter: str | None, memory_path: Path, *, session: str, opened_at: datetime | None,
           away_since: datetime | None, readers: list[dict], done: bool, now: datetime | None = None) -> None:
    """The app's whole word on its catch-up, replacing the last one. A new ``session`` (the app launched again) starts
    a new catch-up; within one session ``openedAt`` and ``awaySince`` are the first report's, and a catch-up once done
    takes no further word (a reader that starts later is the app's ordinary reading, not this catch-up)."""
    now = _utc(now) or datetime.now(timezone.utc)
    opened = min(_utc(opened_at) or now, now)
    opened = max(opened, now - timedelta(seconds=MAX_OPENED_AGO_S))
    away = _utc(away_since)
    if away is not None and away >= opened:
        away = None
    cleaned = [{"channel": r["channel"], "label": r["label"], "state": r["state"],
                "fix": r.get("fix") if r["state"] == "failed" else None} for r in readers[:MAX_READERS]]
    key = _key(reporter, memory_path)
    with _lock:
        current = _state.get(key)
        if current is None or current.session != session:
            current = _CatchUp(session=session, opened_at=opened, away_since=away)
            _state[key] = current
        if current.done:
            return   # over: what the app reads later is its ordinary reading, not this catch-up
        # A finished catch-up has nothing still reading: a row the app sent as reading with `done` was not part of it.
        current.readers = [r for r in cleaned if r["state"] != "reading"] if done else cleaned
        if done:
            current.done = True
            current.done_at = now
        current.updated_at = now


def _counts(files, opened_at: datetime, away_since: datetime | None, until: datetime | None) -> tuple[int | None, int]:
    from api.services import history_index

    opened_ns = int(opened_at.timestamp() * 1e9)
    away_ns = int(away_since.timestamp() * 1e9) if away_since else None
    until_ns = int(until.timestamp() * 1e9) if until else None
    arrived = 0 if away_ns is not None else None
    new = 0
    for f in files:
        if not history_index.waits_for_model(f.frontmatter):
            continue
        if f.mtime_ns >= opened_ns:
            if until_ns is None or f.mtime_ns <= until_ns:
                new += 1
        elif away_ns is not None and f.mtime_ns >= away_ns:
            arrived += 1
    return arrived, new


def _live(entry: _CatchUp, now: datetime) -> bool:
    if entry.done:
        return entry.done_at is not None and (now - entry.done_at).total_seconds() <= SHOWN_AFTER_DONE_S
    return entry.updated_at is not None and (now - entry.updated_at).total_seconds() <= READING_TTL_S


def views(memory_path: Path, *, files=None, now: datetime | None = None) -> dict[str | None, dict]:
    """Every live catch-up of this bank, by reporter (``None`` = this server's own app), on the wire. ``files`` is the
    bank's episode headers when the caller already holds them (``device_status.snapshot`` scans once for both)."""
    now = _utc(now) or datetime.now(timezone.utc)
    bank = str(Path(memory_path))
    with _lock:
        for key in [k for k, entry in _state.items() if not _live(entry, now)]:
            del _state[key]
        entries = {reporter: entry for (reporter, b), entry in _state.items() if b == bank}
    if not entries:
        return {}
    if files is None:
        from api.services import bank_index

        files = bank_index.files(Path(memory_path), "episodes")
    out: dict[str | None, dict] = {}
    for reporter, entry in entries.items():
        if entry.frozen is not None:
            arrived, new = entry.frozen
        else:
            arrived, new = _counts(files, entry.opened_at, entry.away_since, entry.done_at)
            if entry.done:
                with _lock:
                    entry.frozen = (arrived, new)
        out[reporter] = {
            "state": "done" if entry.done else "reading",
            "openedAt": _iso(entry.opened_at),
            "awaySince": _iso(entry.away_since),
            "doneAt": _iso(entry.done_at),
            "readers": [dict(r) for r in entry.readers],
            "arrived": arrived,
            "new": new,
        }
    return out


def view(reporter: str | None, memory_path: Path, *, now: datetime | None = None) -> dict | None:
    return views(memory_path, now=now).get(reporter)
