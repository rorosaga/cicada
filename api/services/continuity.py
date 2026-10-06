"""Where the last session in this folder stopped (G110 slice 1a).

Plan: ``docs/plans/2026-10-06-g110-continuity.md`` revision 4 (C1, C2, C4).

A fresh harness session started in the same folder as an earlier one is told
where the earlier session's *captured* work stopped — before Sleep has run —
and can read more through ``cicada_continue``. Nothing here is stored as a
projection: every answer is assembled when it is asked for, from

* the Stop-hook episodes (``capture_kind: transcript``) — their head scalars
  through a disposable metadata index, then at most ``MAX_CHOSEN_PARSE`` full
  parses;
* the continuity registry (``continuity_sessions``) — ids, a cwd hash, times.

Identity is the **exact** ``cwd`` string the harness's hook reports, which
capture stores as ``project_dir``. No folding, no prefix matching, no
repository key, no ``.git`` read: every note says the workspace state was not
checked.

**The index** (``<bank>/continuity_index.json``) maps every ``ep_*.md`` to
``(mtime_ns, size, row | "unreadable" | null)``. A row is read from the
episode's HEAD only — the bytes up to its first top-level ``turns:`` key or the
frontmatter's close, capped at ``HEAD_CAP`` — never a full parse inside a hook
request. A head that cannot be read that way is ``unreadable`` and makes the
search *incomplete*; only the stdio tool (no hook budget) may fully parse a few.
The index is persisted only when git is known to ignore it
(``bank_registry.derived_exclusion_state``) and a lock outside every bank is
available (``continuity_sessions.continuity_home``); otherwise it lives in
this process's memory. It is never an error and never an authoritative
absence.

Engine-free, read-only on the bank's markdown, and never logs a path, a title
or a turn.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml
from loguru import logger

from api.services import bank_registry, continuity_sessions, episode_ids, evidence, markdown_parser

SCHEMA = 1
INDEX_FILE = "continuity_index.json"
HEAD_CAP = 16_384
MAX_CHOSEN_PARSE = 3
ACTIVE_WINDOW_MIN = 15
TOOL_UNREADABLE_PARSES = 20
FULL_CHARS, COMPACT_CHARS, POINTER_CHARS = 1800, 800, 240
QUOTE_CHARS, REPLY_CHARS = 280, 600
COMPACT_QUOTE_CHARS, COMPACT_REPLY_CHARS = 160, 240
TITLE_CHARS = 60
MAX_LISTED = 3
#: The slice of an assembly's deadline kept for the one full parse after the index refresh.
VIEW_RESERVE_S = 0.05
HARNESS_NAMES = {"claude-code": "Claude Code", "codex": "Codex"}
UNREADABLE = "unreadable"

_ROW_STR_KEYS = ("id", "harness", "session_id", "project_dir", "captured_at", "last_turn_at", "processed_by")
_Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
_TURN_START = re.compile(r"\n(?=(?:user|assistant): )")


# --- the metadata index ------------------------------------------------------


@dataclass
class Snapshot:
    rows: dict[str, dict]          # filename -> row (Stop-hook episodes only)
    complete: bool
    unreadable: int = 0


_MEMO: dict[str, dict[str, list]] = {}
_MEMO_LOCK = threading.Lock()


def _iso(value) -> str | None:
    """A frontmatter time as aware-UTC ISO (YAML may hand back a datetime)."""
    if isinstance(value, datetime):
        return episode_ids.to_utc_iso(value)
    if isinstance(value, str) and value:
        try:
            moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return episode_ids.to_utc_iso(moment)
    return None


def _row(fm: dict) -> dict | str | None:
    """The index row for one episode's frontmatter: None for anything that is
    not a Stop-hook session episode, ``unreadable`` for one that is but whose
    scalars are malformed."""
    if fm.get("capture_kind") != "transcript":
        return None
    row: dict = {}
    for key in _ROW_STR_KEYS:
        value = fm.get(key)
        if key in ("captured_at", "last_turn_at"):
            value = _iso(value)
        if value is not None and not isinstance(value, str):
            return UNREADABLE
        if value:
            row[key] = value
    row["processed"] = fm.get("processed") is True
    if not row.get("session_id") or row.get("harness") not in continuity_sessions.HARNESSES:
        return UNREADABLE
    if not episode_ids.EPISODE_ID_RE.match(str(row.get("id") or "")):
        return UNREADABLE
    return row


def read_head(path: Path) -> dict | str | None:
    """One episode's index row from its head bytes only (≤ ``HEAD_CAP``)."""
    try:
        with open(path, "rb") as fh:
            raw = fh.read(HEAD_CAP)
    except OSError:
        return UNREADABLE
    text = raw.decode("utf-8", errors="replace")
    if not text.startswith("---\n"):
        return None
    cuts = [i for i in (text.find("\nturns:", 3), text.find("\n---\n", 3)) if i > 0]
    if not cuts:
        return UNREADABLE
    try:
        fm = yaml.load(text[4:min(cuts)], Loader=_Loader)
    except yaml.YAMLError:
        return UNREADABLE
    if not isinstance(fm, dict):
        return UNREADABLE
    return _row(fm)


def _full_row(path: Path) -> dict | str | None:
    try:
        return _row(markdown_parser.parse(path).frontmatter)
    except Exception:  # noqa: BLE001
        return UNREADABLE


def _index_path(memory_path: Path) -> Path:
    return Path(memory_path) / INDEX_FILE


def _load(memory_path: Path) -> dict[str, list]:
    key = os.path.realpath(memory_path)
    with _MEMO_LOCK:
        if key in _MEMO:
            return dict(_MEMO[key])
    try:
        doc = json.loads(_index_path(memory_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA or not isinstance(doc.get("entries"), dict):
        return {}
    out: dict[str, list] = {}
    for name, entry in doc["entries"].items():
        if not (isinstance(name, str) and name.startswith("ep_") and name.endswith(".md") and "/" not in name):
            continue
        if not (isinstance(entry, list) and len(entry) == 3 and all(isinstance(x, int) for x in entry[:2])):
            continue
        value = entry[2]
        if isinstance(value, dict):
            value = _row(value)
            if not isinstance(value, dict):
                continue
        elif value not in (None, UNREADABLE):
            continue
        out[name] = [entry[0], entry[1], value]
    return out


def _persist(memory_path: Path, entries: dict[str, list], bank_paths) -> None:
    """Write the index only where it is protected; else memory only."""
    if bank_registry.derived_exclusion_state(memory_path, INDEX_FILE) == "unprotected":
        bank_registry.ensure_derived_excluded(memory_path)
        if bank_registry.derived_exclusion_state(memory_path, INDEX_FILE) == "unprotected":
            return
    home = continuity_sessions.continuity_home(bank_paths)
    if home is None:
        return
    lock = home / f"{continuity_sessions.bank_file_id(memory_path)}.index.lock"
    try:
        fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError:
        return
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return      # another refresh is writing; this snapshot stays in memory
        target = _index_path(memory_path)
        tmp = target.with_name(f".{INDEX_FILE}.{secrets.token_hex(4)}.tmp")
        try:
            tmp.write_text(json.dumps({"schema": SCHEMA, "entries": entries}), encoding="utf-8")
            os.replace(tmp, target)
        except OSError:
            try:
                tmp.unlink()
            except OSError:
                pass
    finally:
        os.close(fd)


def refresh_index(memory_path: Path, *, bank_paths, deadline: float | None,
                  allow_full_parse: int = 0) -> Snapshot:
    """Bring the index up to date with the episodes directory, newest files
    first, until ``deadline`` (a ``time.monotonic()`` value; ``None`` = no
    limit). Files not reached and unreadable heads make the snapshot
    incomplete. ``allow_full_parse`` (the stdio tool only) fully parses that
    many unreadable heads."""
    memory_path = Path(memory_path)
    episodes = memory_path / "episodes"
    old = _load(memory_path)
    entries: dict[str, list] = {}
    pending = 0
    try:
        scan = []
        with os.scandir(episodes) as it:
            for e in it:
                if e.name.startswith("ep_") and e.name.endswith(".md") and e.is_file(follow_symlinks=False):
                    st = e.stat(follow_symlinks=False)
                    scan.append((st.st_mtime_ns, st.st_size, e.name))
    except OSError:
        return Snapshot({}, complete=True)
    scan.sort(reverse=True)
    for mtime, size, name in scan:
        cached = old.get(name)
        if cached and cached[0] == mtime and cached[1] == size:
            entries[name] = cached
            continue
        if deadline is not None and time.monotonic() >= deadline:
            pending += 1
            continue
        entries[name] = [mtime, size, read_head(episodes / name)]
    parsed = 0
    for name, entry in entries.items():
        if entry[2] == UNREADABLE and parsed < allow_full_parse:
            parsed += 1
            entry[2] = _full_row(episodes / name)
    unreadable = sum(1 for e in entries.values() if e[2] == UNREADABLE)
    if entries != old:
        with _MEMO_LOCK:
            _MEMO[os.path.realpath(memory_path)] = dict(entries)
        _persist(memory_path, entries, bank_paths)
    rows = {name: e[2] for name, e in entries.items() if isinstance(e[2], dict)}
    return Snapshot(rows, complete=pending == 0 and unreadable == 0, unreadable=unreadable)


def reset() -> None:
    """Forget every in-memory index (tests)."""
    with _MEMO_LOCK:
        _MEMO.clear()


# --- selection ---------------------------------------------------------------


@dataclass(frozen=True)
class Selection:
    kind: str                         # explicit | latest | ambiguous | none
    chosen: tuple[str, dict] | None   # (filename, row)
    listed: tuple[tuple[str, dict], ...] = ()
    reason: str = ""


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def activity(row: dict, registry_row: dict | None) -> str:
    """Captured activity, never file mtime: the last kept turn, the capture
    time, or a later prompt the registry saw."""
    stamps = [row.get("last_turn_at"), row.get("captured_at"), (registry_row or {}).get("last_prompt_at")]
    return max((s for s in stamps if s), default="")


def select(snapshot: Snapshot, registry_rows: dict[str, dict], *, cwd: str | None, exclude_session: str | None,
           session: str | None = None) -> Selection:
    """The total selection of plan C1: an exact ``session`` (episode id or full
    session id), else the most recent other session in this exact folder; two
    active within ``ACTIVE_WINDOW_MIN`` of each other is a question, never a
    guess."""
    def reg(row):
        return registry_rows.get(f"{row['harness']}:{row['session_id']}")

    if session:
        want = session.strip()
        hits = [(n, r) for n, r in snapshot.rows.items() if want in (r.get("id"), r.get("session_id"))]
        if len(hits) == 1:
            return Selection("explicit", hits[0], reason="explicit")
        if len(hits) > 1:
            return Selection("ambiguous", None, tuple(hits[:MAX_LISTED]), reason="explicit_many")
        return Selection("none", None, reason="no_such_session")
    if not cwd:
        return Selection("none", None, reason="no_folder")
    here = [(n, r) for n, r in snapshot.rows.items()
            if r.get("project_dir") == cwd and r.get("session_id") != exclude_session]
    if not here:
        return Selection("none", None, reason="none_here")
    here.sort(key=lambda nr: activity(nr[1], reg(nr[1])), reverse=True)
    if len(here) >= 2:
        a = _parse_time(activity(here[0][1], reg(here[0][1])))
        b = _parse_time(activity(here[1][1], reg(here[1][1])))
        if a and b and (a - b).total_seconds() <= ACTIVE_WINDOW_MIN * 60:
            close = [nr for nr in here[:MAX_LISTED]
                     if (t := _parse_time(activity(nr[1], reg(nr[1])))) and (a - t).total_seconds() <= ACTIVE_WINDOW_MIN * 60]
            return Selection("ambiguous", None, tuple(close), reason="active_together")
    return Selection("latest", here[0], tuple(here[1:MAX_LISTED]), reason="latest")


# --- one session, read in full ---------------------------------------------


@dataclass(frozen=True)
class Turn:
    n: int
    speaker: str
    at: str | None
    text: str
    exact: bool


@dataclass
class SessionView:
    filename: str
    episode_id: str
    harness: str
    session_id: str
    project_dir: str | None
    title: str
    content_hash: str
    processed: bool
    processed_by: str | None
    last_turn_at: str | None
    captured_at: str | None
    turn_count: int
    capture_gap: dict | None
    capture_flags: dict | None
    continues: str | None
    body: str = ""
    sidecar: list = field(default_factory=list)
    tail: list = field(default_factory=list)
    _turns: list | None = None

    def turns(self) -> list[Turn]:
        if self._turns is None:
            self._turns = split_turns(self.body, self.sidecar, self.tail, self.turn_count)
        return self._turns


def view(memory_path: Path, chosen: tuple[str, dict], *, deadline: float | None = None) -> SessionView | None:
    """One full parse of the chosen episode, re-validated against its index
    row (a file changed between scan and parse is dropped, never mixed)."""
    if deadline is not None and time.monotonic() >= deadline:
        return None
    name, row = chosen
    try:
        doc = markdown_parser.parse(Path(memory_path) / "episodes" / name)
    except Exception:  # noqa: BLE001
        return None
    fm = doc.frontmatter
    for key in ("id", "session_id", "harness", "project_dir"):
        if str(fm.get(key) or "") != str(row.get(key) or ""):
            return None
    return SessionView(
        filename=name, episode_id=str(fm["id"]), harness=str(fm["harness"]), session_id=str(fm["session_id"]),
        project_dir=fm.get("project_dir"), title=str(fm.get("title") or ""),
        content_hash=str(fm.get("content_hash") or ""), processed=fm.get("processed") is True,
        processed_by=fm.get("processed_by"), last_turn_at=_iso(fm.get("last_turn_at")),
        captured_at=_iso(fm.get("captured_at")), turn_count=int(fm.get("turn_count") or 0),
        capture_gap=fm.get("capture_gap") if isinstance(fm.get("capture_gap"), dict) else None,
        capture_flags=fm.get("capture_flags") if isinstance(fm.get("capture_flags"), dict) else None,
        continues=fm.get("continues") if isinstance(fm.get("continues"), str) else None,
        # The G118 sidecar through its one reader (R-PJ16): `evidence.turn_stamps`.
        body=doc.body, sidecar=[{"offset": o, **e} for o, e in evidence.turn_stamps(fm).items()],
        tail=fm.get("tail_turns") if isinstance(fm.get("tail_turns"), list) else [],
    )


def _offsets(entries) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for e in entries or []:
        if isinstance(e, dict) and isinstance(e.get("offset"), int) and e.get("speaker") in ("user", "assistant"):
            out[e["offset"]] = e
    return out


def split_turns(body: str, sidecar, tail, turn_count: int) -> list[Turn]:
    """The body's turns, numbered from 1. Boundaries come from exact offsets —
    the G118 sidecar (the first ≤ 500 timed turns) and ``tail_turns`` (the last
    8, consecutive) — and ``turn_count`` says how many there are. When those
    offsets account for every turn, every turn is exact. Otherwise the missing
    boundaries lie between the last sidecar offset and the first tail offset:
    if that region's ``user:``/``assistant:`` line starts number exactly the
    missing turns they are used, else every non-tail region is split that way.
    Either way a turn cut on a line start says ``exact=False`` ("boundaries
    approximate")."""
    if not body:
        return []
    side = _offsets(sidecar)
    tail_map = _offsets(tail)
    known = {**side, **tail_map}
    known.setdefault(0, {"offset": 0})
    starts = sorted(o for o in known if 0 <= o < len(body))
    end_of_body = len(body) + 1
    approx: set[int] = set()
    missing = (turn_count or 0) - len(starts)
    if missing > 0:
        first_tail = min(tail_map) if tail_map else end_of_body
        region_start = max((o for o in starts if o < first_tail), default=0)
        found = [m.start() + 1 for m in _TURN_START.finditer(body, region_start, max(region_start, first_tail - 1))]
        if len(found) == missing:
            approx = set(found) | {region_start}
            starts = sorted(set(starts) | set(found))
        else:
            extra: set[int] = set()
            for i, s0 in enumerate(starts):
                e0 = starts[i + 1] if i + 1 < len(starts) else end_of_body
                if s0 in tail_map:
                    continue
                pieces = [m.start() + 1 for m in _TURN_START.finditer(body, s0, max(s0, e0 - 1))]
                if pieces:
                    extra |= set(pieces) | {s0}
            approx = extra
            starts = sorted(set(starts) | extra)
    turns: list[Turn] = []
    for n, s0 in enumerate(starts, start=1):
        e0 = starts[n] if n < len(starts) else end_of_body
        chunk = body[s0:e0 - 1]
        speaker, _, text = chunk.partition(": ")
        if speaker not in ("user", "assistant"):
            speaker, text = "unknown", chunk
        meta = known.get(s0) or {}
        turns.append(Turn(n, speaker, _iso(meta.get("at") or meta.get("ts")), text, s0 not in approx))
    return turns


# --- assembly and the startup block -----------------------------------------


@dataclass
class WorkingContext:
    memory_path: Path
    selection: Selection
    complete: bool
    chosen: SessionView | None = None
    registry_row: dict | None = None
    listed: list = field(default_factory=list)            # (filename, row) of other sessions shown
    later_starts: list = field(default_factory=list)      # registry rows: sessions started here after, nothing captured
    now: datetime | None = None


def assemble(memory_path: Path, *, bank_paths, harness: str | None, session_id: str | None, cwd: str | None,
             session: str | None = None, deadline: float | None = None, allow_full_parse: int = 0,
             now: datetime | None = None) -> WorkingContext:
    """The working context for one request, on the pinned ``memory_path``."""
    memory_path = Path(memory_path)
    now = now or datetime.now(timezone.utc)
    snap = refresh_index(memory_path, bank_paths=bank_paths,
                         deadline=None if deadline is None else deadline - VIEW_RESERVE_S,
                         allow_full_parse=allow_full_parse)
    registry = continuity_sessions.all_rows(memory_path, bank_paths=bank_paths, now=now)
    sel = select(snap, registry, cwd=cwd, exclude_session=session_id, session=session)
    ctx = WorkingContext(memory_path, sel, snap.complete, listed=list(sel.listed), now=now)
    if sel.chosen is not None:
        ctx.chosen = view(memory_path, sel.chosen, deadline=deadline)
        if ctx.chosen is None:
            ctx.complete = False
            ctx.selection = Selection("none", None, reason="changed")
            return ctx
        row = sel.chosen[1]
        ctx.registry_row = registry.get(f"{row['harness']}:{row['session_id']}")
        if cwd:
            since = _parse_time(activity(row, ctx.registry_row))
            captured = {r.get("session_id") for r in snap.rows.values()}
            for reg in continuity_sessions.rows_for_cwd(memory_path, continuity_sessions.cwd_hash(cwd),
                                                        bank_paths=bank_paths, now=now):
                started = _parse_time(reg.get("started_at"))
                if (reg["session_id"] not in captured and reg["session_id"] != session_id
                        and started and since and started > since):
                    ctx.later_starts.append(reg)
    return ctx


def _local(stamp: str | None) -> str:
    moment = _parse_time(stamp)
    if moment is None:
        return "time not recorded"
    return moment.astimezone().strftime("%Y-%m-%d %H:%M %Z").strip()


def _hm(stamp: str | None) -> str:
    moment = _parse_time(stamp)
    return moment.astimezone().strftime("%H:%M") if moment else "an unrecorded time"


def _age(stamp: str | None, now: datetime) -> str:
    moment = _parse_time(stamp)
    if moment is None:
        return "an unknown time"
    minutes = max(0, int((now - moment).total_seconds() // 60))
    if minutes < 60:
        return f"{minutes} min"
    if minutes < 48 * 60:
        return f"{minutes // 60} h"
    return f"{minutes // 1440} days"


def clip(text: str, limit: int) -> str:
    flat = " ".join(str(text or "").split())
    if len(flat) <= limit:
        return flat
    cut = flat.rfind(" ", 0, limit - 1)
    return flat[: cut if cut > limit // 2 else limit - 1].rstrip() + "…"


def consolidation(v: SessionView) -> str:
    if not v.processed:
        return "not yet consolidated"
    return "consolidated by Sleep" if v.processed_by == "sleep" else "marked processed by an agent"


def gap_lines(ctx: WorkingContext) -> list[str]:
    """Every reason the note must not sound complete (plan C4)."""
    v = ctx.chosen
    out: list[str] = []
    turns = v.turns() if v else []
    last = turns[-1] if turns else None
    prompt_at = (ctx.registry_row or {}).get("last_prompt_at")
    last_at = v.last_turn_at if v else None
    if prompt_at and last_at and prompt_at > last_at and (_parse_time(prompt_at) - _parse_time(last_at)).total_seconds() > 1:
        out.append(f"a later message at {_hm(prompt_at)} has no captured reply")
    elif last and last.speaker == "user":
        out.append("its last request has no captured reply")
    gap = (v.capture_gap or {}) if v else {}
    if gap.get("dropped_turns"):
        out.append(f"{gap['dropped_turns']} turns past Cicada's capture limit, until {_hm(gap.get('last_seen_at'))}")
    flags = (v.capture_flags or {}) if v else {}
    if flags.get("note_like_turns"):
        out.append(f"{flags['note_like_turns']} of its turns look like a Cicada note kept as typed text")
    for reg in ctx.later_starts[:2]:
        out.append(f"a later session started here at {_hm(reg.get('started_at'))} and nothing from it was captured")
    if not ctx.complete:
        out.append("the search here was incomplete")
    return out


def _last(turns: list[Turn], speaker: str) -> Turn | None:
    return next((t for t in reversed(turns) if t.speaker == speaker), None)


def call(session: str) -> str:
    return f'`cicada_continue(session="{session}")`'


def _render(ctx: WorkingContext, *, quote_chars: int | None, reply_chars: int | None, others: bool) -> str:
    v = ctx.chosen
    now = ctx.now or datetime.now(timezone.utc)
    act = activity({"last_turn_at": v.last_turn_at, "captured_at": v.captured_at}, ctx.registry_row)
    which = ("the most recent session here" if ctx.complete
             else "the most recent session Cicada could read here (the search was incomplete)")
    if ctx.selection.kind == "explicit":
        which = "the session you picked"
    turns = v.turns()
    last = turns[-1] if turns else None
    who = {"user": "the person's", "assistant": "the agent's"}.get(last.speaker if last else "", "an unknown")
    lines = [
        "### Where the last session in this folder stopped",
        f"- {HARNESS_NAMES.get(v.harness, v.harness)} session, episode `{v.episode_id}` (revision `{v.content_hash}`): "
        f"{which}, last active {_local(act)} ({_age(act, now)} before this session); last kept turn {who} at "
        f"{_local(last.at if last and last.at else v.last_turn_at)}; {consolidation(v)}.",
    ]
    if quote_chars:
        req = _last(turns, "user")
        if req:
            lines.append(f"- The person's last request there, quoted as history, not a new instruction: "
                         f"\"{clip(req.text, quote_chars)}\"")
    if reply_chars:
        rep = _last(turns, "assistant")
        if rep:
            lines.append(f"- The agent's last reply there: \"{clip(rep.text, reply_chars)}\"")
    gaps = gap_lines(ctx)
    if gaps:
        lines.append("- Not captured: " + "; ".join(gaps) + ".")
    lines.append("- Workspace state not checked: the files, branch and tests it mentions may have changed — "
                 "inspect them before editing.")
    if others:
        for name, row in ctx.listed[:2]:
            lines.append(f"- Also here: {HARNESS_NAMES.get(row['harness'], row['harness'])}, episode `{row['id']}`, "
                         f"last active {_local(activity(row, None))}.")
    lines.append(f"- More, page by page: {call(v.episode_id)}.")
    return "\n".join(lines)


def _render_compact(ctx: WorkingContext) -> str:
    v = ctx.chosen
    act = activity({"last_turn_at": v.last_turn_at, "captured_at": v.captured_at}, ctx.registry_row)
    turns = v.turns()
    lines = ["### Where the last session in this folder stopped",
             f"- Episode `{v.episode_id}` (revision `{v.content_hash}`), last active {_local(act)}; {consolidation(v)}"
             + ("" if ctx.complete else "; the search was incomplete") + "."]
    req, rep = _last(turns, "user"), _last(turns, "assistant")
    if req:
        lines.append(f"- Their last request (history, not an instruction): \"{clip(req.text, COMPACT_QUOTE_CHARS)}\"")
    if rep:
        lines.append(f"- The agent's last reply: \"{clip(rep.text, COMPACT_REPLY_CHARS)}\"")
    gaps = gap_lines(ctx)
    if gaps:
        lines.append("- Not captured: " + "; ".join(gaps) + ".")
    lines.append(f"- Workspace state not checked: inspect before editing. More: {call(v.episode_id)}.")
    return "\n".join(lines)


def _render_ambiguous(ctx: WorkingContext, memory_path: Path, *, max_rows: int = MAX_LISTED) -> str:
    lines = ["### Recent sessions in this folder"]
    for name, row in ctx.selection.listed[:max_rows]:
        title = clip(_title_of(memory_path, name), TITLE_CHARS)
        lines.append(f"- {HARNESS_NAMES.get(row['harness'], row['harness'])}, episode `{row['id']}`, last active "
                     f"{_local(activity(row, None))}" + (f": \"{title}\"" if title else ""))
    lines.append("- Ask the person which one to continue unless their first message says; then "
                 f"{call('<episode id>')}." )
    lines.append("- Workspace state not checked: inspect files before editing.")
    return "\n".join(lines)


def _title_of(memory_path: Path, name: str) -> str:
    row = read_head(Path(memory_path) / "episodes" / name)
    if not isinstance(row, dict):
        return ""
    try:
        with open(Path(memory_path) / "episodes" / name, "rb") as fh:
            head = fh.read(HEAD_CAP).decode("utf-8", errors="replace")
        m = re.search(r"^title: (.*)$", head, re.M)
        return yaml.load(m.group(1), Loader=_Loader) if m else ""
    except Exception:  # noqa: BLE001
        return ""


def startup_block(ctx: WorkingContext, *, max_chars: int) -> tuple[str, str]:
    """The largest rendering that fits ``max_chars``: ``full``, ``compact``,
    ``pointer`` — or ``("", "none")``. Ambiguity renders the list form."""
    if ctx.selection.kind == "ambiguous":
        for rows in (MAX_LISTED, 1):
            text = _render_ambiguous(ctx, ctx.memory_path, max_rows=rows)
            if len(text) <= max_chars:
                return text, "ambiguous"
        return "", "none"
    if ctx.chosen is None:
        return "", "none"
    candidates = (
        ("full", _render(ctx, quote_chars=QUOTE_CHARS, reply_chars=REPLY_CHARS, others=True), FULL_CHARS),
        ("compact", _render_compact(ctx), COMPACT_CHARS),
    )
    for name, text, cap in candidates:
        if len(text) <= min(cap, max_chars):
            return text, name
    pointer = (f"### Where the last session in this folder stopped\n- Episode `{ctx.chosen.episode_id}`; workspace "
               f"state not checked; {call(ctx.chosen.episode_id)}.")
    if len(pointer) <= min(POINTER_CHARS, max_chars):
        return pointer, "pointer"
    return "", "none"
