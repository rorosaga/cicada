"""Keyless Apple Notes one-way import connector.

The companion app reads Notes.app with one batched AppleScript
(``AppleNotesReader.swift`` — every note across every account/folder in one
call) and posts the raw dump; this module parses it, diffs against what has
already been ingested, and stages ONE episode per note into the standard
episode inbox (the same "episode inbox" ``telegram_capture``/``media_ingestor``
write to). One-way: Cicada never writes back into Notes.app.

No new dedup architecture — mirrors ``bookmark_sync``'s "diff against an
index, only ingest what's new" shape, but note ids aren't URLs, so this gets
its own ``memory/sources/notes_index.json`` keyed on note id (falling back to
a hash of name+creation-date for the rare note with no id). Storing the
last-seen *modification* date (not just presence) lets an edited note
be staged again while an unchanged note is skipped on every subsequent sync.
An edited note is **revised in place** (2026-11-23, G104): the same episode through
``episode_staging``, re-queued as a revision Sleep reads for what changed only — never
a second episode, which restated every fact of the note in new words after each edit.

The backend never runs ``osascript`` (the ``~/Library`` rail: the app reads,
the backend parses bytes). Run from the launchd backend, macOS asked whether
"python3.12" may control Notes — and an Allow there reached every script that
interpreter runs. Everything here is pure (the dump is a plain string) or file
I/O against the bank.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import threading
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from api.services import (bank_index, episode_ids, episode_scrub, episode_staging, evidence, history_index, markdown_parser,
                          sensitive_flags, sync_state, write_admission)

NOTES_INDEX_FILENAME = "notes_index.json"

# Delimiters chosen to be vanishingly unlikely inside real note text: ASCII
# Record/Unit Separator control characters, never typed by a human and
# stripped by essentially every text editor.
FIELD_SEP = "\x1e"
RECORD_SEP = "\x1d"
_EXPECTED_FIELDS = 6  # id, name, body, created, modified, folder
#: 2026-10-23: the app adds two after the folder — the modification date as Notes' own locale-free ISO local time
#: (AppleScript's ``«class isot»``) and the Mac's UTC offset in seconds — so a note is dated when it was written,
#: never the day it was synced. `created`/`modified` stay the human strings: `modified` is the dedup key, and a new
#: spelling would re-emit every note an older sync already kept. A 6-field record (an older app) still parses. The
#: offset is today's, so a note from the other side of a daylight-saving change is an hour off (its day rarely moves).
_DATED_FIELDS = 8
#: 2026-11-04 (owner: "replicate this layout inside Apple Notes, starting from those that are iCloud … and then you go
#: into it … you can see folders") — a ninth field after the offset: the Notes ACCOUNT the folder belongs to ("iCloud",
#: "On My Mac", a mail account's name), so the Sources page browses account → folder → notes. Kept in the index
#: (`account`, `folder`), never in a note's dedup key: an 8-field record still parses, and a note an older sync kept is
#: placed on the next read without a new episode.
_ACCOUNT_FIELDS = 9

# A note body beyond this is truncated before it becomes an episode — an
# episode is a lightweight staging chunk, not a full document store; the Sleep
# cycle only needs enough text to extract entities/claims from.
MAX_NOTE_BODY_CHARS = 20_000

#: G234 (owner, Linear ROR-93): "respect locked notes … people keep passwords and the like there". A locked note's body
#: is never requested (`AppleNotesReader`'s filter), never stored here even when a post carries one, and nothing per
#: note stays in the bank: only a count, beside the channel's last sync.
ORIGIN = "apple-notes"
LOCKED_COUNT_KEY = "locked"
#: What a retired stub is titled, since its own title is exactly what must not stay.
LOCKED_TITLE = "Locked note"
#: What an episode held from before its note was locked, moved out of `episodes/` (`kept_path`).
KEPT_DIRNAME = "locked_notes"
KEPT_SUFFIX = ".locked"
#: Everything a retired stub keeps: the record that an episode existed, and none of what named it.
_STUB_KEEPS = ("id", "timestamp", "received_at", "source", "origin", "processed", "processed_by")
#: Serialises the Notes index between a sync and Sleep's retirement in its worker thread.
_INDEX_LOCK = threading.Lock()


# --- Parsing -----------------------------------------------------------------


@dataclass
class NoteRecord:
    note_id: str
    name: str
    body: str
    created: str
    modified: str
    folder: str
    #: When the note was last modified, aware ISO-8601; '' when the app did not send it (an older app).
    modified_at: str = ""
    #: The Notes account the folder belongs to; '' from an older app.
    account: str = ""
    #: A.4 (G245, 2026-11-24): the folder's whole path in the account, outermost first, ending in ``folder``; empty from
    #: an older app (which sends the leaf only) and for a note whose path the app could not name.
    folder_path: list[str] = field(default_factory=list)
    #: The Mac's UTC offset in seconds, as the record carried it (`_DATED_FIELDS`): what the creation moment is read with.
    offset: str = ""
    #: G245 (arrival join, 2026-11-24): when the note was CREATED, aware ISO-8601; '' when the app did not send it. The
    #: human ``created`` string is a locale's own words and is never parsed; this one comes beside the dump
    #: (``note_created``) as Notes' locale-free ISO local time, like ``modified_at``. A note's ``timestamp`` is its LAST
    #: modification, so only this says when a note was begun.
    created_at: str = ""


def parse_notes_dump(raw: str) -> list[NoteRecord]:
    """Parse the delimited ``osascript`` dump into ``NoteRecord``s.

    Records are ``RECORD_SEP``-joined; each record is 6 ``FIELD_SEP``-joined
    fields (id, name, body, created, modified, folder). A record with the
    wrong field count — a malformed/truncated emission — is skipped, never
    raised; empty/whitespace-only chunks (e.g. a trailing separator) are
    silently dropped.
    """
    if not raw:
        return []
    records: list[NoteRecord] = []
    for chunk in raw.split(RECORD_SEP):
        if not chunk.strip():
            continue
        fields = chunk.split(FIELD_SEP)
        if len(fields) not in (_EXPECTED_FIELDS, _DATED_FIELDS, _ACCOUNT_FIELDS):
            logger.debug(f"Skipping malformed note record ({len(fields)} field(s), expected {_EXPECTED_FIELDS})")
            continue
        note_id, name, body, created, modified, folder = fields[:_EXPECTED_FIELDS]
        modified_at = _aware(*fields[_EXPECTED_FIELDS:_DATED_FIELDS]) if len(fields) >= _DATED_FIELDS else ""
        account = fields[_DATED_FIELDS].strip() if len(fields) == _ACCOUNT_FIELDS else ""
        records.append(NoteRecord(
            note_id=note_id.strip(),
            name=name.strip(),
            body=body,
            created=created.strip(),
            modified=modified.strip(),
            folder=folder.strip(),
            modified_at=modified_at,
            account=account,
            offset=fields[_EXPECTED_FIELDS + 1].strip() if len(fields) >= _DATED_FIELDS else "",
        ))
    return records


def _aware(local_iso: str, offset_seconds: str) -> str:
    """``2026-03-03T11:30:00`` + ``3600`` -> ``2026-03-03T10:30:00+00:00``; '' when either is unreadable or the moment
    lies in the future (a clock the record cannot be dated by)."""
    try:
        naive = datetime.fromisoformat(local_iso.strip())
        offset = timedelta(seconds=int(offset_seconds.strip()))
    except (ValueError, OverflowError):
        return ""
    if naive.tzinfo is not None or abs(offset) > timedelta(hours=18):
        return ""
    moment = naive.replace(tzinfo=timezone(offset)).astimezone(timezone.utc)
    return moment.isoformat() if moment <= datetime.now(timezone.utc) else ""


#: G245 (arrival join): the episode's frontmatter key for when its note was begun (aware ISO). Frontmatter alone, outside the
#: body and the hash, like a folder path: a note an earlier sync kept gains it without a new episode or a re-read.
CREATED_KEY = "created_at"


def _aware_created(iso, offset) -> str:
    """The note's creation moment from the app's locale-free local ISO and the record's own UTC offset (`_aware`); ''
    when either is unreadable or the moment lies in the future."""
    return _aware(str(iso or ""), str(offset or "")) if iso and offset not in (None, "") else ""


#: A folder's path is at most this deep and each name at most this long: Notes allows no more than a person draws.
MAX_PATH_DEPTH = 10
NAME_CAP = 120
#: A stored folder list (the empty folders and Notes' own order) is at most this long.
MAX_FOLDERS = 500
FOLDERS_KEY = "folders"
PINS_READ_KEY = "pins_read"


def _name(raw) -> str:
    text = " ".join(str(raw or "").split())
    return text if len(text) <= NAME_CAP else text[: NAME_CAP - 1].rstrip() + "…"


def clean_path(raw, leaf: str = "") -> list[str]:
    """A posted folder path as names, outermost first: whitespace folded, clipped, empties dropped. ``leaf`` (the dump's
    own folder field) must end it — the two come from separate Apple events, so a path that does not end in the note's
    folder is stale and names nothing."""
    if not isinstance(raw, (list, tuple)):
        return []
    names = [n for n in (_name(x) for x in raw[:MAX_PATH_DEPTH]) if n]
    if not names:
        return []
    return names if not leaf or _name(leaf).casefold() == names[-1].casefold() else []


def clean_folders(raw) -> list[dict]:
    """The folders the app listed, in Notes' own order: ``[{account, path}]``, each clipped, no repeats, at most
    ``MAX_FOLDERS``. A folder is a filing label: names only, never a note's anything."""
    out: list[dict] = []
    seen: set[tuple] = set()
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        path = clean_path(entry.get("path"))
        account = _name(entry.get("account"))
        key = (account, tuple(path))
        if not path or key in seen:
            continue
        seen.add(key)
        out.append({"account": account, "path": path})
        if len(out) >= MAX_FOLDERS:
            break
    return out


def stored_folders(memory_path: Path) -> list[dict]:
    """The folder list the last read kept beside the channel's sync (``[{account, path}]``, Notes' own order); empty from
    an older app."""
    entry = sync_state.read_sync_state(Path(memory_path)).get("notes")
    return clean_folders((entry or {}).get(FOLDERS_KEY) if isinstance(entry, dict) else None)


def pins_read(memory_path: Path) -> bool | None:
    """Whether the last read could tell which notes are pinned (the app reads pins only with Full Disk Access it already
    holds): True, False, or None before any read said (an older app)."""
    entry = sync_state.read_sync_state(Path(memory_path)).get("notes")
    value = (entry or {}).get(PINS_READ_KEY) if isinstance(entry, dict) else None
    return value if isinstance(value, bool) else None


def _note_key(note: NoteRecord) -> str:
    """Dedup key: the note's own id, falling back to a hash of
    name+creation-date for the rare note that comes back with no id."""
    if note.note_id:
        return note.note_id
    return hashlib.sha256(f"{note.name}|{note.created}".encode()).hexdigest()[:16]


def _truncate_body(body: str) -> str:
    if len(body) <= MAX_NOTE_BODY_CHARS:
        return body
    return body[:MAX_NOTE_BODY_CHARS] + "\n\n… [truncated]"


# --- Dedup index ---------------------------------------------------------


def _notes_index_path(memory_path: Path) -> Path:
    return Path(memory_path) / "sources" / NOTES_INDEX_FILENAME


def _load_notes_index(memory_path: Path) -> dict:
    import json

    idx_file = _notes_index_path(memory_path)
    if not idx_file.exists():
        return {}
    try:
        return json.loads(idx_file.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _save_notes_index(memory_path: Path, idx: dict) -> None:
    import json

    sources_dir = memory_path / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    _notes_index_path(memory_path).write_text(
        json.dumps(idx, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# --- Episode draft ---------------------------------------------------------


#: One Notes note is one episode for good (G104): the stager's identity for it. The note's own key (its id, or the hash of
#: its name and creation date when a record has none), so an edit finds the episode it made before.
SOURCE_PREFIX = "apple-notes:"
#: A.4: the frontmatter key and index field holding a note's folder path (a list of names, outermost first). Never part
#: of the body (the body names the leaf only, so no edit and no existing note changes its hash), never evidence.
FOLDER_PATH_KEY = "folder_path"


def source_id(note: NoteRecord) -> str:
    return f"{SOURCE_PREFIX}{_note_key(note)}"


def _episode_body(note: NoteRecord) -> str:
    """What Sleep reads: the title, the folder and the note's text. **Not the modification date**, which changes on every
    edit: in the body it would be a "changed line" of every revision and would make an unchanged note look changed. The
    date is the episode's ``timestamp`` and ``source_updated_at`` (frontmatter, outside the hash)."""
    lines = [f"# {note.name or 'Untitled note'}", ""]
    if note.folder:
        lines.append(f"**Folder:** {note.folder}")
    lines += ["", _truncate_body(note.body)]
    return "\n".join(lines)


def _draft(note: NoteRecord, pinned: bool = False) -> episode_staging.EpisodeDraft:
    """The note as the stager's draft. Read on time (owner 2026-10-16): a note is dated when it was last written, not the
    day it was synced; an older app sends no date: now, as before. ``redate`` is set by :func:`_stage`, not here."""
    extra: dict = {
        "note_id": note.note_id,
        # Folder name as a tag hint for the Sleep extractor/entity tagging — mirrors bookmark_sync tagging synced items
        # with their origin.
        "tags": [note.folder] if note.folder else [],
    }
    if note.folder:
        extra["folder"] = note.folder
    if note.account:
        extra["account"] = note.account
    if note.folder_path:
        extra[FOLDER_PATH_KEY] = list(note.folder_path)
    if pinned:
        extra[episode_staging.PINNED_KEY] = True   # ROR-15: outside the content hash; see `_apply_pin`
    if note.created_at:
        extra[CREATED_KEY] = note.created_at
    return episode_staging.EpisodeDraft(
        title=note.name or "Untitled note", source_id=source_id(note),
        source_updated_at=note.modified_at or note.modified or None,
        timestamp=note.modified_at or None,
        original_date=episode_ids.id_day(note.modified_at) if note.modified_at else None,
        source=ORIGIN, origin=ORIGIN, body=_episode_body(note), extra=extra, writer="apple-notes")


# --- Locked notes (G234) -----------------------------------------------------


@dataclass
class Retired:
    #: memory-relative paths written, for a scoped commit.
    paths: list[str] = field(default_factory=list)
    #: the episode ids retired.
    episodes: list[str] = field(default_factory=list)
    #: stubs emptied of their title and folder.
    stubs: int = 0
    #: episodes that hold the note's text from before it was locked: hidden everywhere, the text left in place. Whether
    #: it is destroyed is the person's call, never a sync's.
    with_text: int = 0


def locked_count(memory_path: Path) -> int:
    """How many locked notes the last read found (the Sources page's one line)."""
    entry = sync_state.read_sync_state(Path(memory_path)).get("notes")
    try:
        return max(0, int((entry or {}).get(LOCKED_COUNT_KEY) or 0))
    except (TypeError, ValueError, AttributeError):
        return 0


def locked_key(name: str) -> str:
    """A locked note's name, hashed (`AppleNotesReader.lockedKey`, the same bytes), so the name never leaves the app.
    Measured 2026-11-04: locking gives a note a new id and its name survives, so this finds an episode kept under the
    id it had before. Not its dates: they would miss a note edited before the lock (the usual way a secret gets into
    one), and the stored date is a string in the locale and time zone of the read that wrote it."""
    return hashlib.sha256(unicodedata.normalize("NFC", (name or "").strip()).encode()).hexdigest()


def is_stub(body: str) -> bool:
    """Does an episode's body hold nothing but what `_episode_body` renders around a note's text? An unlocked note's
    plaintext always carries at least its title line (measured 2026-11-04), so no text means Notes withheld it."""
    lines = [ln for ln in (body or "").splitlines() if ln.strip()]
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    while lines and lines[0].startswith(("**Folder:**", "**Modified:**")):
        lines = lines[1:]
    return not lines


def kept_path(memory_path: Path, stem: str) -> Path:
    """Where an episode's text from before its note was locked waits for the person's decision. Not an episode and no
    `.md`, so no reader, index or bank walk reaches it; `api/tests/test_locked_notes.py` fails if another module names it."""
    return Path(memory_path) / "sources" / KEPT_DIRNAME / f"{stem}{KEPT_SUFFIX}"


def kept_copy(memory_path: Path, stem: str) -> Path | None:
    """An episode's kept file, if it has one. `sensitive_flags` alone asks, for the person's own review and Remove, which
    find a value in it with no model; no engine or agent door reads it. The test beside `kept_path` holds that."""
    path = kept_path(memory_path, stem)
    return path if path.is_file() else None


def _retire_file(memory_path: Path, path: Path, at: str, out: Retired) -> bool:
    """Retire one episode, under the episode lock: the file stays, as an empty record with no title, folder or note id,
    so its id is never reused and whatever cites it finds nothing. Text from before the lock moves whole to
    `kept_path`, because destroying it is the person's call and every reader of `episodes/` must find it gone (git
    still holds the earlier versions either way). Also finishes an episode an earlier version only stamped. Returns
    whether it changed."""
    with episode_ids.episode_lock(path.parent):
        parsed = markdown_parser.parse(path)
        fm = dict(parsed.frontmatter or {})
        stub = is_stub(parsed.body)
        if fm.get(evidence.LOCKED_NOTE_KEY) and stub:
            return False
        kept = None
        if not stub:
            kept = kept_path(memory_path, path.stem)
            kept.parent.mkdir(parents=True, exist_ok=True)
            markdown_parser.write(kept, fm, parsed.body)
        retired_at = fm.get("source_deleted_at") if fm.get(evidence.LOCKED_NOTE_KEY) else None
        record = {key: fm[key] for key in _STUB_KEEPS if key in fm}
        record["title"] = LOCKED_TITLE
        sensitive = sensitive_flags.record_for_stub(fm, parsed.body)
        if sensitive:
            record[sensitive_flags.KEY] = sensitive
        if not record.get("processed"):
            record["processed"] = True
            record["processed_by"] = history_index.INDEXED_BY
        record[evidence.LOCKED_NOTE_KEY] = True
        record["source_deleted_at"] = retired_at or at
        markdown_parser.write(path, record, "")
    out.paths.append(f"episodes/{path.name}")
    if kept is None:
        out.stubs += 1
    else:
        out.paths.append(kept.relative_to(memory_path).as_posix())
        out.with_text += 1
    return True


def _forget_in_index(memory_path: Path, retired_ids: set[str], note_ids: set[str]) -> bool:
    """Drop the retired notes from the Notes index, which names each one's folder. A note unlocked later is then simply
    new. Returns whether the index changed."""
    with _INDEX_LOCK:
        idx = _load_notes_index(memory_path)
        gone = [key for key, entry in idx.items()
                if key in note_ids or (isinstance(entry, dict) and (str(entry.get("note_id") or "") in note_ids
                                                                    or str(entry.get("episode_id") or "") in retired_ids))]
        for key in gone:
            del idx[key]
        if gone:
            _save_notes_index(memory_path, idx)
    return bool(gone)


def retire_locked(memory_path: Path, note_ids: set[str], keys: set[str] | None = None,
                  unlocked_ids: set[str] | None = None) -> Retired:
    """Retire every episode of these notes, and every Notes episode with no text. Keyed on the episodes' own `note_id`,
    not the index, which points only at a note's latest episode. `keys` (`locked_key`) find an episode kept under the
    id the note had before it was locked, and with it every episode of that older id; a note this same read saw
    unlocked (`unlocked_ids`) is never one of them, however its title reads. Pure files; the caller commits `paths`."""
    memory_path = Path(memory_path)
    out = Retired()
    at = episode_ids.utc_now_seconds()
    retired_ids: set[str] = set()
    notes = [f for f in bank_index.files(memory_path, "episodes") if (f.frontmatter or {}).get("origin") == ORIGIN]
    note_ids = set(note_ids)
    for f in notes:
        fm = f.frontmatter or {}
        older_id = str(fm.get("note_id") or "")
        if keys and older_id and older_id not in (unlocked_ids or ()) and locked_key(str(fm.get("title") or "")) in keys:
            note_ids.add(older_id)
    for f in notes:
        fm = f.frontmatter or {}
        try:
            if str(fm.get("note_id") or "") not in note_ids and not is_stub(f.body()):
                # An episode stamped by an earlier version keeps its text: finished here, whatever the post named.
                if not fm.get(evidence.LOCKED_NOTE_KEY):
                    continue
            if _retire_file(memory_path, f.path, at, out):
                retired_ids.add(str(fm.get("id") or f.path.stem))
                out.episodes.append(f.path.stem)
        except Exception as exc:  # noqa: BLE001 — one unreadable file never stops the rest
            logger.warning(f"Notes: could not retire an episode: {type(exc).__name__}")
    if _forget_in_index(memory_path, retired_ids, note_ids):
        out.paths.append(f"sources/{NOTES_INDEX_FILENAME}")
    return out


def _forget_derived(memory_path: Path, retired: Retired) -> None:
    """The retired words leave both derived indexes now: the words index would serve its rows for a few seconds and
    the vectors keep theirs until Sleep's next whole sync (`vector_index._without_locked_notes` holds until then if
    this fails). Never raises: a disposable index is never the reason a retirement fails."""
    from api.services import search_index, vector_index

    try:
        search_index.ensure_fresh(Path(memory_path), wait=True, max_age_s=0)
        if retired.episodes:
            vector_index.forget_passages(Path(memory_path), (), tuple(retired.episodes))
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Notes: could not clear a retired note from an index: {type(exc).__name__}")


class _SleepHolds(Exception):
    pass


async def _review_in_step(memory_path: Path) -> None:
    """The review item's rows carry each conversation's title, so a retired note's row loses its name now. One admitted
    transaction with its own commit; while Sleep holds the pages it is left to Sleep's tail, which does this same step on
    every exit path, and an item dirty before this is left, as that tail leaves it. Never raises."""
    from api.services import git_service, page_lock

    has_git = (Path(memory_path) / ".git").exists()

    def step(skip: frozenset[str]) -> None:
        with page_lock.page_lock(memory_path):
            bank_index.invalidate(memory_path)
            report = sensitive_flags.sync_review(memory_path, skip)
            if report.paths and has_git:
                git_service.commit_touched_sync(memory_path, sensitive_flags.commit_message(report, date.today()), report.paths)

    async def body() -> None:
        await asyncio.to_thread(step, await git_service.dirty_paths(memory_path) if has_git else frozenset())

    try:
        await write_admission.run_admitted(memory_path, body, refuse=_SleepHolds)
    except _SleepHolds:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Notes: could not bring the review in step: {type(exc).__name__}")


async def _commit_retired(memory_path: Path, paths: list[str], author: str, trigger: str) -> None:
    """Its own commit, naming paths only: nothing about a note reaches a commit message."""
    from api.services import git_service

    if not (Path(memory_path) / ".git").exists():
        return
    message = git_service.build_commit_message(
        "Locked notes retired", [f"{p}: updated (trigger: {trigger})" for p in paths], authors=[author])
    await git_service.commit_paths(memory_path, message, paths)


async def retire_stubs_safely(memory_path: Path) -> None:
    """Sleep's guard (G234): before anything is frozen, retire the Notes episodes that hold no text, so a run that
    starts before the next sync reads none of them. A failed commit is logged and the retirement kept: restoring would
    put the title back in the queue. Never raises."""
    try:
        retired = await asyncio.to_thread(retire_locked, memory_path, set())
        if retired.paths:
            logger.info(f"Notes: {retired.stubs} locked note stub(s) retired before reading")
            await asyncio.to_thread(_forget_derived, memory_path, retired)
            await _commit_retired(memory_path, retired.paths, "cicada", "sleep/locked_notes")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Notes: retiring locked stubs failed: {type(exc).__name__}")


# --- Sync (diff + emit only what's new/changed) -----------------------------


def _placement(note: NoteRecord, known: dict | None = None) -> tuple[str | None, str | None, list[str] | None]:
    """The note's account, folder and folder path as the index keeps them. A record that names no account or path (an
    older app) keeps the one already known."""
    known = known or {}
    kept = known.get(FOLDER_PATH_KEY)
    path = list(note.folder_path) or (list(kept) if isinstance(kept, list) and kept else None)
    return note.account or known.get("account") or None, note.folder or None, path


def _index_entry(episode_id: str, note: NoteRecord, known: dict | None = None, pinned: bool = False) -> dict:
    account, folder, path = _placement(note, known)
    entry = {"episode_id": episode_id, "modified": note.modified, "note_id": note.note_id,
             "account": account, "folder": folder}
    if path:
        entry[FOLDER_PATH_KEY] = path   # only ever present once the app has sent one: an older library's index is what it was
    if pinned:
        entry["pinned"] = True   # only ever present when true: an unpinned library's index is byte-for-byte what it was
    return entry


def _apply_pin(memory_path: Path, existing: dict, pinned: bool) -> bool:
    """ROR-15: a pin moved in Notes while the note itself did not. The index entry and the note's latest episode take
    the new state through `episode_staging.set_pinned` (one frontmatter key, under the episode lock): the body, the hash,
    ``processed`` and ``revised`` stay as they were, so nothing is queued and Sleep reads nothing again. A pin that
    changes on a note Sleep already read does nothing to memory. Returns whether anything changed."""
    if bool(existing.get("pinned")) == pinned:
        return False
    if pinned:
        existing["pinned"] = True
    else:
        existing.pop("pinned", None)
    path = _episode_path(memory_path, str(existing.get("episode_id") or ""))
    if path is not None:
        try:
            episode_staging.set_pinned(path, pinned)
        except Exception as exc:  # noqa: BLE001 — a pin is metadata: it never fails a sync
            logger.warning(f"Notes: could not record a pin: {type(exc).__name__}")
    return True


def _apply_path(memory_path: Path, existing: dict, path: list[str] | None) -> None:
    """A.4: where a note lives moved (or the app now says its whole path) while its words did not. The note's latest
    episode takes the path in its frontmatter alone (`episode_staging.amend_frontmatter`): the body, hash and queue are
    untouched, so nothing is re-read. Metadata, like a pin: it never fails a sync."""
    ep = _episode_path(memory_path, str(existing.get("episode_id") or ""))
    if ep is None or not path:
        return
    def edit(fm: dict) -> bool:
        if fm.get(FOLDER_PATH_KEY) == path:
            return False
        fm[FOLDER_PATH_KEY] = list(path)
        return True

    try:
        episode_staging.amend_frontmatter(ep, edit)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Notes: could not record a folder path: {type(exc).__name__}")


def _apply_created(memory_path: Path, existing: dict, created_at: str) -> bool:
    """G245: the app now says when this note was begun and its latest episode does not carry it yet. The episode's
    frontmatter takes it alone (`episode_staging.amend_frontmatter`): body, hash and queue untouched, nothing re-read.
    Written once — a note's creation moment never moves. Metadata: it never fails a sync."""
    ep = _episode_path(memory_path, str(existing.get("episode_id") or ""))
    if ep is None:
        return False

    def edit(fm: dict) -> bool:
        if fm.get(CREATED_KEY):
            return False
        fm[CREATED_KEY] = created_at
        return True

    try:
        return bool(episode_staging.amend_frontmatter(ep, edit))
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Notes: could not record a creation date: {type(exc).__name__}")
        return False


def _episode_path(memory_path: Path, episode_id: str) -> Path | None:
    if not episode_id or "/" in episode_id or "\\" in episode_id or ".." in episode_id:
        return None
    path = Path(memory_path) / "episodes" / f"{episode_id}.md"
    return path if path.is_file() else None


def _stage(memory_path: Path, pending: list[tuple[NoteRecord, dict | None, bool]]) -> list[tuple[str, str]]:
    """Stage the new and edited notes through the one stager (G104): ``[(verdict, episode id)]`` in order, the verdict
    ``created``, ``updated`` or ``skipped``. An edited note is **its one episode, edited in place** — same id, same
    file, ``processed: false`` and a ``revised`` record, so Sleep reads only what changed and the note stays one
    conversation for every count; it never mints a second.

    Episodes an earlier version wrote carry ``note_id`` and no ``source_id`` (the index points at a note's latest). Only
    when that note is edited, the latest one takes the stager's identity (`episode_staging.adopt_source`, one
    frontmatter key) and is then edited like any other: an unchanged note is never in ``pending``, so an upgrade
    rewrites nothing. Its old ``content_hash`` is a hash of the key and the date, never of the words, so it always
    reads as changed once; the body Sleep read (git) still carries the old ``**Modified:**`` line, which the revision
    sees as removed text, once, and reads nothing for."""
    episodes_dir = memory_path / "episodes"
    by_source, _hashes = episode_staging.scan(episodes_dir)
    adopted = False
    drafts = []
    for note, existing, pinned in pending:
        draft = _draft(note, pinned)
        if existing is not None and draft.source_id not in by_source:
            path = _episode_path(memory_path, str(existing.get("episode_id") or ""))
            adopted = (path is not None and episode_staging.adopt_source(path, draft.source_id)) or adopted
        drafts.append(draft)
    if adopted:
        by_source, _hashes = episode_staging.scan(episodes_dir)
    for draft in drafts:
        # The note's own date moves with its edits (`timestamp` is when it was last written), only when the words did:
        # a note Notes touched with no change in its text stays as it was.
        entry = by_source.get(draft.source_id)
        if entry is not None and draft.timestamp:
            digest = episode_staging.content_hash(episode_staging.render(draft)[0])
            draft.redate = entry.fm.get("content_hash") not in (digest, episode_staging.content_hash(draft.body or ""))
    result = episode_staging.stage(drafts, episodes_dir, bank=memory_path.name)
    return [(verdict, result.episode_ids.get(draft.source_id, ""))
            for verdict, draft in zip(result.verdicts, drafts)]


async def sync_notes(memory_path: Path, *, dump: str, accounts: dict[str, str] | None = None,
                     locked_ids: list[str] | None = None, locked_keys: list[str] | None = None,
                     pinned_ids: list[str] | None = None, folder_paths: dict[str, list[str]] | None = None,
                     folders: list[dict] | None = None, created: dict[str, str] | None = None) -> dict[str, Any]:
    """Parse ``dump`` and stage one episode per note, through the stager (`episode_staging`, G104).

    A brand-new note id -> a new episode. A previously-seen note whose ``modified`` changed -> **its one episode is
    edited in place** (same id and file, ``processed: false``, a ``revised`` record: Sleep reads only what changed and
    the note is one conversation for every count); the index keeps pointing at it. An unchanged note (same id, same
    ``modified``) is skipped entirely, with no write. See :func:`_stage` for episodes an earlier version wrote.

    Returns ``{"new": int, "updated": int, "skipped": int, "total": int,
    "excluded": int, "locked": int, "retired": int}``.

    G234: a record whose id is in ``locked_ids`` is dropped whatever it carries, and every episode of that note is
    retired; ``locked_keys`` (`locked_key`) find what was kept under an id the note had before its lock. A record with no
    text is never staged either. An older app sends no ``locked_ids``, so its blank records
    are taken as locked (that is what Notes returned for a locked note); what it cannot be protected from is a body it
    reads while a locked note is open, which looks like any other note.

    ROR-15: ``pinned_ids`` are the notes the person pinned in Notes (the app maps them from Notes' store, only with Full
    Disk Access it already holds). ``None`` means the app could not tell, and leaves every pin as it was; a list, empty
    included, is the whole truth. A pin is frontmatter metadata that never reaches the content hash or the queue
    (:func:`_apply_pin`); an id that names no readable note in this post is ignored.

    A.4 (G245): ``folder_paths`` (note id -> the folder's names, outermost first) and ``folders`` (every folder the app
    listed, in Notes' own order) travel beside the dump like ``accounts``, so an older backend ignores them. A path is
    metadata beside the leaf the body already names: it enters the index and the episode's frontmatter, never the body or
    the hash, so no existing note is re-staged or doubled — an unchanged note is only *placed* (:func:`_apply_path`). A
    note of a locked id gets none. A folder is a filing label, never evidence.

    G245 (arrival join): ``created`` (note id -> Notes' locale-free local ISO creation time, read with the record's own UTC
    offset) travels beside the dump the same way. A note's ``created_at`` is frontmatter beside the folder path — never the
    body or the hash — and a note an earlier sync kept takes it without a new episode (:func:`_apply_created`); an older
    app sends none, and a note without it simply has no creation day (`arrival_join` never dates a note by its last edit).

    Folder exclusion: ``CICADA_NOTES_EXCLUDE_FOLDERS`` (comma-separated,
    case-insensitive folder names, default empty) drops matching notes
    BEFORE the dedup index ever sees them — so an excluded folder ingests
    cleanly later if the exclusion is lifted. Motivating case: a
    password-notes folder must never land in a plaintext memory graph that
    LLM clients read.
    """
    memory_path = Path(memory_path)
    flagged = {str(i).strip() for i in (locked_ids or []) if str(i).strip()}
    readable: list[NoteRecord] = []
    unlocked_ids: set[str] = set()
    for note in parse_notes_dump(dump):
        if note.note_id in flagged:
            continue
        unlocked_ids.add(note.note_id)
        if not note.body.strip():
            if locked_ids is None and note.note_id:
                flagged.add(note.note_id)
            continue
        readable.append(note)
    notes = readable
    locked_found = len(flagged)
    keys = {str(k) for k in (locked_keys or []) if k}
    retired = retire_locked(memory_path, flagged, keys, unlocked_ids) if flagged or keys else Retired()
    if retired.paths:
        logger.info(f"Notes: {len(retired.paths)} path(s) retired for locked notes")
        await asyncio.to_thread(_forget_derived, memory_path, retired)
        try:
            await _commit_retired(memory_path, retired.paths, "user", "user/notes_sync")
        except Exception as e:
            logger.warning(f"Locked notes commit failed: {type(e).__name__}")
        await _review_in_step(memory_path)
    # 2026-11-04 — the app sends each note's account beside the dump (`note_accounts`), so a backend that predates it
    # still reads the 8-field records; a ninth field in the dump itself is read too.
    for note in notes:
        if not note.account and accounts and (named := accounts.get(note.note_id)):
            note.account = " ".join(str(named).split())[:120]
        if folder_paths and note.note_id not in flagged and not note.folder_path:
            note.folder_path = clean_path(folder_paths.get(note.note_id), note.folder)
        if created and note.note_id not in flagged and (when := created.get(note.note_id)):
            note.created_at = _aware_created(str(when).strip()[:40], note.offset)
    excluded_folders = excluded_folder_names()
    excluded_count = 0
    if excluded_folders:
        kept = []
        for note in notes:
            # A folder below an excluded one is excluded with it: the path names every ancestor.
            if note.folder.casefold() in excluded_folders or any(n.casefold() in excluded_folders
                                                                  for n in note.folder_path):
                excluded_count += 1
            else:
                kept.append(note)
        notes = kept
    new_count = 0
    updated_count = 0
    skipped_count = 0
    pins_moved = 0
    skipped_touched = 0
    pins = None if pinned_ids is None else {str(i).strip() for i in pinned_ids if str(i).strip()}
    episodes_dir = memory_path / "episodes"

    placed = 0
    _INDEX_LOCK.acquire()
    try:
        idx = _load_notes_index(memory_path)
        pending: list[tuple[NoteRecord, dict | None, bool]] = []
        for note in notes:
            key = _note_key(note)
            existing = idx.get(key)
            pinned = bool((existing or {}).get("pinned")) if pins is None else note.note_id in pins
            if existing is None or existing.get("modified") != note.modified:
                pending.append((note, existing, pinned))
            else:
                skipped_count += 1
                if _apply_pin(memory_path, existing, pinned):
                    pins_moved += 1
                if note.created_at and _apply_created(memory_path, existing, note.created_at):
                    placed += 1   # frontmatter only, like a placement: nothing Sleep reads changed
                # 2026-11-04 — where a note lives (its account and folder) is kept current in the index alone: a note moved
                # to another folder, or kept by a sync from before accounts were sent, is placed without a new episode
                # (nothing Sleep reads changed).
                now_placed = _placement(note, existing)
                if now_placed != (existing.get("account"), existing.get("folder"), existing.get(FOLDER_PATH_KEY)):
                    moved_path = now_placed[2] != existing.get(FOLDER_PATH_KEY)
                    existing["account"], existing["folder"] = now_placed[0], now_placed[1]
                    if now_placed[2]:
                        existing[FOLDER_PATH_KEY] = now_placed[2]
                    if moved_path:
                        _apply_path(memory_path, existing, now_placed[2])
                    placed += 1
        # New and edited notes: one stage call (one scan of the bank), the edited ones in place (G104).
        staged = _stage(memory_path, pending) if pending else []
        for (note, existing, pinned), (verdict, episode_id) in zip(pending, staged):
            idx[_note_key(note)] = _index_entry(episode_id, note, existing, pinned)
            if verdict == "created":
                new_count += 1
            elif verdict == "updated":
                updated_count += 1
            else:
                skipped_count += 1
                skipped_touched += 1   # Notes touched it, its words did not move: the index takes the new date only
                # ...and the folder path, if it moved: the stager's unchanged branch writes no filing key of its own, so the
                # episode's frontmatter takes it here (frontmatter alone, nothing re-read), as the unmoved-date branch does.
                if existing is not None:
                    _apply_path(memory_path, idx[_note_key(note)], idx[_note_key(note)].get(FOLDER_PATH_KEY))
            if existing is not None and (path := _episode_path(memory_path, episode_id)) is not None:
                try:
                    episode_staging.set_pinned(path, pinned)   # an edit and a pin moved together: the pin follows the note
                except Exception as exc:  # noqa: BLE001 — a pin is metadata: it never fails a sync
                    logger.warning(f"Notes: could not record a pin: {type(exc).__name__}")
        if new_count or updated_count or placed or pins_moved or pending:
            _save_notes_index(memory_path, idx)
    finally:
        _INDEX_LOCK.release()

    if new_count or updated_count or placed or pins_moved or skipped_touched:
        try:
            await _commit_notes_sync(memory_path, new_count, updated_count)
        except Exception as e:
            logger.warning(f"Notes sync commit failed: {type(e).__name__}: {e}")

    return {
        "new": new_count,
        "updated": updated_count,
        "skipped": skipped_count,
        "total": len(notes),
        "excluded": excluded_count,
        "locked": locked_found,
        "retired": retired.stubs + retired.with_text,
    }


def excluded_folder_names() -> set[str]:
    """``CICADA_NOTES_EXCLUDE_FOLDERS`` as the names a sync drops (case-insensitive)."""
    return {f.strip().casefold() for f in os.environ.get("CICADA_NOTES_EXCLUDE_FOLDERS", "").split(",") if f.strip()}


def state_extra(locked: int, pins_were_read: bool, folders: list[dict] | None) -> dict:
    """What the channel's last sync keeps (`sync_state`): the locked count (G234), whether pins could be read (A.4), and
    the folder list in Notes' own order with an excluded folder, and everything below it, left out. A post with no folder
    list (an older app) keeps none, and the page builds its tree from the notes alone."""
    out: dict[str, Any] = {LOCKED_COUNT_KEY: int(locked), PINS_READ_KEY: bool(pins_were_read)}
    excluded = excluded_folder_names()
    listed = [f for f in clean_folders(folders) if not any(n.casefold() in excluded for n in f["path"])]
    if listed:
        out[FOLDERS_KEY] = listed
    return out


async def _commit_notes_sync(memory_path: Path, new_count: int, updated_count: int) -> None:
    from api.services import git_service

    date_str = datetime.now().strftime("%Y-%m-%d")
    message = git_service.build_commit_message(
        f"Notes sync {date_str}",
        [
            f"memory/sources/{NOTES_INDEX_FILENAME}: updated (trigger: user/notes_sync)",
            f"{new_count} new + {updated_count} updated note episode(s) (trigger: user/notes_sync)",
        ],
        authors=["user"],
    )
    await git_service.commit_changes(memory_path, message)
