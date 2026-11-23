"""An agent's edit of a raw source file is a contribution (G244, TODO ruling 76, owner 2026-11-23).

An agent that edits a note or a meeting transcript in a watched folder is, to the folder sync, nobody: the app posts the
new bytes, ``folder_source`` stages them as a revision, and the corrected words read as the recorder's. Every write
through Cicada's own tools names its harness, session and model; this module gives a direct file edit the same
provenance — **recorded by the agent's hook (or its own ``cicada source-edit``), never by the agent's memory** (G105's
rule), and never by a guess over file times.

**The record carries a hash, never a path to open.** The agent's process matched the file against the folders the backend
lists and hashed its bytes; it posts ``{folder_id, relpath, sha256, harness, session, tool, at}``. The backend never
opens ``relpath`` (the app reads the folder, the backend parses bytes) and never stats a path a request names.

**Matched by content, in either order.** The app's sync of the new bytes and the agent's record race; neither waits.

* the record first: it is *held* (:func:`hold`) in a small store outside every bank and git, ``$CICADA_HOME/source-edits/
  <bank id>.json`` (0700 dir, 0600 file), keyed by ``(folder id, relpath, sha256)``, expiring after :data:`EXPIRY_DAYS`.
  ``folder_source`` takes the records whose file it is staging (:func:`pending_for`) onto the drafts it writes, and
  :func:`consume` drops them once an episode carries them;
* the sync first: :func:`receive` finds the folder's episodes that hold those bytes (``content_sha``) and attaches the
  contribution at once, in one commit under the agent as ``Cicada-Author`` and its session as ``Cicada-Session``.

**What an episode keeps** (``episode_staging.CONTRIBUTIONS_KEY``): ``contributions: [{harness, model?, effort?, session?,
at, content_hash, ranges}]``, newest first, at most 20. ``model`` and ``effort`` are the last agent turn's, from the
session's own transcript when the hook named one that ``transcript_capture.validate_transcript_path`` accepts, else from
the session's captured episode, else absent — never guessed. ``ranges`` are the changed character ranges of the body the
edit made against the body it replaced; a section of a split note whose body the edit left alone gets none (it is not
attached at all).

Rails held here: no model; the record is ids, hashes, enums and times (the store and the logs hold no word of any
file, no file name in a log line); an expired or unmatched record is simply dropped; a record names what it saw, and a
body that has moved on since keeps the contribution but no span is marked (`source_spans`)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from loguru import logger

from api.services import agent_turns, episode_staging, markdown_parser
from api.services.auth import cicada_home

DIRNAME = "source-edits"
EXPIRY_DAYS = 7
#: A held record is a hash and a few labels; a runaway poster cannot grow the file past this (oldest dropped first).
MAX_HELD = 500
#: How much of a transcript's tail is read for the last agent turn's model and effort.
TAIL_BYTES = 2 * 1024 * 1024
#: A time further in the future than this (the clients' clocks drift) is the server's now.
FUTURE_SLACK = timedelta(minutes=10)
#: How far back an episode's own git history is walked for the body an edit replaced.
HISTORY_MAX = 20

_SHA = re.compile(r"^[0-9a-f]{64}$")
_HARNESS = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
_SESSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_TOOL = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,31}$")

_LOCK = threading.Lock()

#: The reasons a record is refused — an enum, so the answer and the log never carry what was posted.
REFUSALS = ("unknown_folder", "bad_sha", "bad_harness", "bad_session", "bad_relpath", "replica", "demo_bank")


class Refused(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass
class Edit:
    """One agent edit, as the backend keeps it: what the file's bytes are (``sha``) and who made them."""
    folder_id: str
    relpath: str
    sha: str
    harness: str
    at: str
    session: str | None = None
    tool: str | None = None
    model: str | None = None
    effort: str | None = None

    def contribution(self) -> dict:
        """The part an episode's contribution is made of (`episode_staging.contribution_entries` adds the body's hash and
        ranges): only what is known."""
        return {k: v for k, v in (("harness", self.harness), ("model", self.model), ("effort", self.effort),
                                  ("session", self.session), ("at", self.at)) if v}


@dataclass
class Outcome:
    status: str                       # attached | held | refused
    episodes: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)    # bank-relative, for the caller's commit
    reason: str | None = None


# --- Validation ----------------------------------------------------------------------------------------------------


def utc_iso(raw, *, now: datetime | None = None) -> str:
    """``raw`` as an aware UTC ISO second; a missing, unreadable or future time is ``now``."""
    now = now or datetime.now(timezone.utc)
    try:
        when = datetime.fromisoformat(str(raw).strip().replace("Z", "+00:00")) if raw else now
    except ValueError:
        when = now
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    when = when.astimezone(timezone.utc)
    if when > now + FUTURE_SLACK:
        when = now
    return when.isoformat(timespec="seconds")


def clean(memory_path: Path, *, folder_id, relpath, sha256, harness, session_id=None, tool=None, at=None,
          now: datetime | None = None) -> Edit:
    """The posted values as an :class:`Edit`, or :class:`Refused` with an enum reason. Never opens ``relpath``."""
    from api.services import folder_source

    if folder_source.get_folder(memory_path, str(folder_id or "")) is None:
        raise Refused("unknown_folder")
    rel = folder_source.clean_relpath(relpath)
    if rel is None:
        raise Refused("bad_relpath")
    sha = str(sha256 or "").strip().lower()
    if not _SHA.match(sha):
        raise Refused("bad_sha")
    who = str(harness or "").strip().lower()
    if not _HARNESS.match(who) or who == "unknown":
        raise Refused("bad_harness")
    sid = str(session_id or "").strip() or None
    if sid is not None and not _SESSION.match(sid):
        raise Refused("bad_session")
    label = str(tool or "").strip()
    return Edit(folder_id=str(folder_id), relpath=rel, sha=sha, harness=who, at=utc_iso(at, now=now), session=sid,
                tool=label if _TOOL.match(label) else None)


# --- Who: the model and the effort ---------------------------------------------------------------------------------


def _tail_lines(path: Path) -> list[str]:
    size = path.stat().st_size
    with path.open("rb") as fh:
        if size > TAIL_BYTES:
            fh.seek(size - TAIL_BYTES)
            fh.readline()          # the first line is cut: drop it
        return [raw.decode("utf-8", "replace") for raw in fh]


def _from_transcript(harness: str, session: str, transcript_path: str) -> tuple[str | None, str | None]:
    from api.services import transcript_capture
    from api.services.transcript_extract import HARNESSES, extract

    if harness not in HARNESSES:
        return None, None
    try:
        path = transcript_capture.validate_transcript_path(harness, session, transcript_path)
        conv = extract(harness, _tail_lines(path), keep_assistant=True)
    except (transcript_capture.TranscriptRefused, OSError, ValueError):
        return None, None
    for turn in reversed(conv.turns):
        if turn.role == "assistant" and (turn.model or turn.effort):
            return turn.model, turn.effort
    return None, None


def _from_episode(memory_path: Path, harness: str, session: str) -> tuple[str | None, str | None]:
    from api.services import transcript_capture

    try:
        with transcript_capture._lock:  # noqa: SLF001 - the capture module's own lookup, under its own lock
            found = transcript_capture._find_session_episode(memory_path / "episodes", harness, session)
        if found is None:
            return None, None
        stamps = agent_turns.stamps(markdown_parser.parse(found).frontmatter)
    except Exception as exc:  # noqa: BLE001 - who made it is best effort; the contribution stands without
        logger.info(f"source edit: the session's episode could not be read ({type(exc).__name__})")
        return None, None
    for stamp in reversed(stamps):
        if stamp.speaker == "assistant" and (stamp.model or stamp.effort):
            return stamp.model, stamp.effort
    return None, None


def agent_fields(memory_path: Path, harness: str, session: str | None, transcript_path: str | None
                 ) -> tuple[str | None, str | None]:
    """``(model, effort)`` of the session's last agent turn: the transcript the hook named (only one
    ``validate_transcript_path`` accepts), else the session's captured episode, else ``(None, None)``. Never a guess; the
    two never mix (one turn's model with another's effort)."""
    if not session:
        return None, None
    if transcript_path:
        got = _from_transcript(harness, session, transcript_path)
        if got != (None, None):
            return got
    return _from_episode(memory_path, harness, session)


# --- The held records ----------------------------------------------------------------------------------------------


def bank_key(memory_path: Path) -> str:
    """The bank's id (``page_reads.bank_key``), else a digest of its path: a held record outlives nothing for long, so a
    path-keyed file for a bank with no id yet can never split anything that matters."""
    from api.services import page_reads

    key = page_reads.bank_key(Path(memory_path))
    return key or "path-" + hashlib.sha256(str(Path(memory_path).resolve()).encode()).hexdigest()[:24]


def store_path(memory_path: Path) -> Path:
    return cicada_home() / DIRNAME / f"{bank_key(memory_path)}.json"


def _read(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = data.get("records") if isinstance(data, dict) else None
    return [r for r in (rows or []) if isinstance(r, dict)]


def _write(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps({"records": rows}, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(path)


def _live(rows: list[dict], now: datetime) -> list[dict]:
    cutoff = (now - timedelta(days=EXPIRY_DAYS)).isoformat(timespec="seconds")
    return [r for r in rows if str(r.get("held_at") or "") >= cutoff]


def _key(row: dict) -> tuple:
    return row.get("folder_id"), row.get("relpath"), row.get("sha")


def hold(memory_path: Path, edit: Edit, *, now: datetime | None = None) -> None:
    """Keep ``edit`` until a sync stages its bytes (or it expires). The same record twice is one."""
    now = now or datetime.now(timezone.utc)
    path = store_path(memory_path)
    row = {"folder_id": edit.folder_id, "relpath": edit.relpath, "sha": edit.sha, "harness": edit.harness,
           "session": edit.session, "tool": edit.tool, "model": edit.model, "effort": edit.effort, "at": edit.at,
           "held_at": now.isoformat(timespec="seconds")}
    with _LOCK:
        rows = [r for r in _live(_read(path), now)
                if not (_key(r) == _key(row) and r.get("harness") == edit.harness and r.get("session") == edit.session)]
        rows.append({k: v for k, v in row.items() if v is not None})
        _write(path, rows[-MAX_HELD:])


def pending_for(memory_path: Path, folder_id: str, relpath: str, sha: str, *,
                now: datetime | None = None) -> list[dict]:
    """The held edits of exactly this file's bytes, as the dicts a draft carries (``EpisodeDraft.edits``). A read: nothing
    is dropped until :func:`consume`."""
    now = now or datetime.now(timezone.utc)
    path = store_path(memory_path)
    if not path.is_file():
        return []
    with _LOCK:
        rows = _live(_read(path), now)
    want = (folder_id, relpath, sha)
    return [{k: r[k] for k in ("harness", "model", "effort", "session", "at") if r.get(k)}
            for r in rows if _key(r) == want]


def consume(memory_path: Path, files: list[tuple[str, str, str]], *, now: datetime | None = None) -> int:
    """Drop the held edits of these ``(folder id, relpath, sha)`` files — an episode carries them now. Also drops what has
    expired. Returns how many were taken."""
    now = now or datetime.now(timezone.utc)
    path = store_path(memory_path)
    if not path.is_file():
        return 0
    drop = set(files)
    with _LOCK:
        rows = _read(path)
        live = _live(rows, now)
        kept = [r for r in live if _key(r) not in drop]
        if len(kept) != len(rows):
            _write(path, kept)
    return len(live) - len(kept)


def held_count(memory_path: Path, *, now: datetime | None = None) -> int:
    path = store_path(memory_path)
    if not path.is_file():
        return 0
    with _LOCK:
        return len(_live(_read(path), now or datetime.now(timezone.utc)))


def forget_bank(bank_id: str | None) -> None:
    """Deleting a bank deletes its held records. Never raises."""
    key = str(bank_id or "").strip()
    if not key or "/" in key or "\\" in key or key.startswith("."):
        return
    try:
        (cicada_home() / DIRNAME / f"{key}.json").unlink(missing_ok=True)
    except OSError as exc:
        logger.warning(f"source edits: wipe skipped ({type(exc).__name__})")


# --- After the sync: attach -----------------------------------------------------------------------------------------


def _prior_body(memory_path: Path, path: Path, sha: str) -> tuple[str | None, bool]:
    """``(the body this episode held before the file's bytes were ``sha``, whether that is known)``.

    Read from the episode's own git history: the newest committed version whose ``content_sha`` is another file's. No
    such version (a new episode: every version already holds ``sha``, or none is committed yet) is ``(None, True)`` —
    the whole body is the edit's. A bank with no git of its own is ``(None, False)``: unknown, so no span is claimed."""
    import subprocess

    from api.services import episode_revision

    if not (memory_path / ".git").exists():
        return None, False
    rel = f"episodes/{path.name}"
    try:
        proc = subprocess.run(["git", "log", f"-n{HISTORY_MAX}", "--format=%H", "--end-of-options", "HEAD", "--", rel],
                              cwd=str(memory_path), capture_output=True, text=True, timeout=30)
        commits = proc.stdout.split() if proc.returncode == 0 else []
        for blob in episode_revision._blobs(memory_path, [f"{c}:{rel}" for c in commits]):  # noqa: SLF001
            got = episode_revision._split(blob)  # noqa: SLF001 - the one reader of an old version
            if got is not None and got[0].get("content_sha") != sha:
                return got[1], True
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        logger.warning(f"source edit: the replaced body could not be read ({type(exc).__name__})")
        return None, False
    return None, True


def _holders(memory_path: Path, edit: Edit) -> list[episode_staging.IndexEntry]:
    index, _ = episode_staging.scan(memory_path / "episodes")
    return sorted((e for e in index.values()
                   if e.fm.get("folder_id") == edit.folder_id and e.fm.get("relpath") == edit.relpath
                   and e.fm.get("content_sha") == edit.sha and not e.fm.get("source_deleted_at")),
                  key=lambda e: e.id)


def attach(memory_path: Path, edit: Edit) -> Outcome:
    """Record ``edit`` on the episodes of its folder that hold its bytes. ``held`` when none does (the sync has not staged
    them; :func:`hold` keeps it). A split note's section the edit left alone gets nothing. Frontmatter only; the caller
    commits ``paths`` as the agent."""
    from api.services import episode_revision

    holders = _holders(memory_path, edit)
    if not holders:
        return Outcome("held")
    out = Outcome("attached")
    for entry in holders:
        parsed = markdown_parser.parse(entry.path)
        body = parsed.body
        prior, known = _prior_body(memory_path, entry.path, edit.sha)
        if known and prior is not None:
            changed, removed, _ = episode_revision.diff(prior, body)
            if not changed and not removed:
                continue            # a section of a split note the edit did not touch
        ranges = episode_staging.changed_ranges(prior, body) if known else []
        item = episode_staging.contribution_entries([edit.contribution()], str(parsed.frontmatter.get("content_hash")),
                                                    ranges)[0]
        held = [c for c in parsed.frontmatter.get(episode_staging.CONTRIBUTIONS_KEY) or [] if isinstance(c, dict)]
        if any(all(c.get(k) == item.get(k) for k in ("harness", "session", "at", "content_hash")) for c in held):
            out.episodes.append(entry.id)       # a repeated post: the episode has it already
        elif episode_staging.add_contribution(entry.path, item, content_sha=edit.sha):
            out.paths.append(f"episodes/{entry.path.name}")
            out.episodes.append(entry.id)
    if not out.episodes:
        out.reason = "no_change"
    return out


def receive(memory_path: Path, edit: Edit, transcript_path: str | None = None) -> Outcome:
    """The route's whole move: resolve who (model, effort), attach to the episodes that hold the bytes, else hold the
    record for the sync. Never opens the file the edit names."""
    if not edit.model and not edit.effort:
        edit.model, edit.effort = agent_fields(memory_path, edit.harness, edit.session, transcript_path)
    out = attach(memory_path, edit)
    if out.status == "held":
        hold(memory_path, edit)
    return out


def editors(memory_path: Path, episode_ids_: list[str]) -> dict[str, str]:
    """``{episode id: harness of its newest contribution}`` for the ids that carry one — what a correction's record names
    (`corrections_record`). Ids only; an unreadable episode has none."""
    from api.services import bank_index

    out: dict[str, str] = {}
    for ep in episode_ids_:
        try:
            indexed = bank_index.file(Path(memory_path), "episodes", f"{ep}.md")
            rows = (indexed.frontmatter or {}).get(episode_staging.CONTRIBUTIONS_KEY) if indexed is not None else None
        except Exception:  # noqa: BLE001
            continue
        first = next((c for c in rows or [] if isinstance(c, dict) and c.get("harness")), None)
        if first is not None:
            out[ep] = str(first["harness"])
    return out
