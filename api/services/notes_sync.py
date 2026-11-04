"""Keyless Apple Notes one-way import connector.

The companion app reads Notes.app with one batched AppleScript
(``AppleNotesReader.swift`` — every note across every account/folder in one
call) and posts the raw dump; this module parses it, diffs against what has
already been ingested, and writes ONE episode per new or modified note into the standard
episode inbox (the same "episode inbox" ``telegram_capture``/``media_ingestor``
write to). One-way: Cicada never writes back into Notes.app.

No new dedup architecture — mirrors ``bookmark_sync``'s "diff against an
index, only ingest what's new" shape, but note ids aren't URLs, so this gets
its own ``memory/sources/notes_index.json`` keyed on note id (falling back to
a hash of name+creation-date for the rare note with no id). Storing the
last-seen *modification* date (not just presence) lets an edited note
re-emit an updated episode while an unchanged note is skipped on every
subsequent sync.

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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from api.services import bank_index, episode_ids, episode_scrub, evidence, history_index, markdown_parser, sync_state

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


# --- Episode writer --------------------------------------------------------


def _episode_body(note: NoteRecord) -> str:
    lines = [f"# {note.name or 'Untitled note'}", ""]
    if note.folder:
        lines.append(f"**Folder:** {note.folder}")
    if note.modified:
        lines.append(f"**Modified:** {note.modified}")
    lines += ["", _truncate_body(note.body)]
    return "\n".join(lines)


def _write_note_episode(episodes_dir: Path, note: NoteRecord) -> str:
    episodes_dir.mkdir(parents=True, exist_ok=True)
    # Read on time (owner 2026-10-16): a note is dated when it was last written, not the day it was synced — a first
    # sync of a years-old library is never a library of mentions today. An older app sends no date: now, as before.
    ep_date = episode_ids.id_day(note.modified_at) if note.modified_at else datetime.now().strftime("%Y-%m-%d")
    episode_id = episode_ids.next_episode_id(episodes_dir, ep_date)
    # Aware UTC (G114 R2) — the old naive `now` + a bare "Z" suffix stamped
    # LOCAL time and labelled it UTC, off by the machine's offset.
    timestamp = note.modified_at or episode_ids.utc_now_iso()

    body = episode_scrub.scrub_body(_episode_body(note), writer="apple-notes", bank=episodes_dir.parent.name)
    content_hash = hashlib.sha256(f"{_note_key(note)}|{note.modified}".encode()).hexdigest()[:12]

    frontmatter = {
        "id": episode_id,
        "timestamp": timestamp,
        "source": "apple-notes",
        "origin": "apple-notes",
        "title": note.name or "Untitled note",
        "processed": False,
        "content_hash": content_hash,
        "note_id": note.note_id,
        "folder": note.folder or None,
        "account": note.account or None,
        # G234: the note's own creation date survives a lock, as its id does not (`locked_key`).
        "note_created": note.created or None,
        # Folder name as a tag hint for the Sleep extractor/entity tagging —
        # mirrors bookmark_sync tagging synced items with their origin.
        "tags": [note.folder] if note.folder else [],
    }
    episode_id = episode_ids.create_episode(episodes_dir, frontmatter, body)
    return episode_id


# --- Locked notes (G234) -----------------------------------------------------


@dataclass
class Retired:
    #: memory-relative paths written, for a scoped commit.
    paths: list[str] = field(default_factory=list)
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


def locked_key(name: str, when: str) -> str:
    """A locked note's name with one of its dates, hashed (`AppleNotesReader.lockedKey`, the same bytes). Measured
    2026-11-04: locking gives a note a new id while its name and both dates survive, so this is what finds an episode
    kept under the id it had before. The app hashes it, so a name never travels."""
    text = f"{(name or '').strip()}\x1f{(when or '').strip()}"
    return hashlib.sha256(unicodedata.normalize("NFC", text).encode()).hexdigest()


def _modified_line(body: str) -> str:
    for line in (body or "").splitlines()[:6]:
        if line.startswith("**Modified:**"):
            return line.removeprefix("**Modified:**").strip()
    return ""


def _keys_of(fm: dict, body: str) -> set[str]:
    """What identifies a kept episode's note without its id: its title with the modified date in its body, and, on an
    episode written since this was added, with its creation date."""
    title = str(fm.get("title") or "")
    keys = {locked_key(title, _modified_line(body))}
    if fm.get("note_created"):
        keys.add(locked_key(title, str(fm["note_created"])))
    return keys


def is_stub(body: str) -> bool:
    """Does an episode's body hold nothing but what `_episode_body` renders around a note's text? An unlocked note's
    plaintext always carries at least its title line (measured 2026-11-04), so no text means Notes withheld it."""
    lines = [ln for ln in (body or "").splitlines() if ln.strip()]
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    while lines and lines[0].startswith(("**Folder:**", "**Modified:**")):
        lines = lines[1:]
    return not lines


def _retire_file(path: Path, at: str, out: Retired) -> bool:
    """Retire one episode, under the episode lock: never unlinked, never read again. A stub keeps no title, folder or
    note id (git still holds its earlier version until the person decides otherwise); an episode with text is
    stamped only. Returns whether it changed."""
    with episode_ids.episode_lock(path.parent):
        parsed = markdown_parser.parse(path)
        fm = dict(parsed.frontmatter or {})
        if fm.get(evidence.LOCKED_NOTE_KEY):
            return False
        stub = is_stub(parsed.body)
        if stub:
            fm = {key: fm[key] for key in _STUB_KEEPS if key in fm}
            fm["title"] = LOCKED_TITLE
        if not fm.get("processed"):
            fm["processed"] = True
            fm["processed_by"] = history_index.INDEXED_BY
        fm[evidence.LOCKED_NOTE_KEY] = True
        fm["source_deleted_at"] = at
        markdown_parser.write(path, fm, "" if stub else parsed.body)
    out.paths.append(f"episodes/{path.name}")
    if stub:
        out.stubs += 1
    else:
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


def retire_locked(memory_path: Path, note_ids: set[str], keys: set[str] | None = None) -> Retired:
    """Retire every episode of these notes, and every Notes episode with no text. Keyed on the episodes' own `note_id`,
    not the index, which points only at a note's latest episode; `keys` (`locked_key`) find an episode kept under the
    id the note had before it was locked, and with it every episode of that older id. Pure files; the caller commits
    `paths`."""
    memory_path = Path(memory_path)
    out = Retired()
    at = episode_ids.utc_now_seconds()
    retired_ids: set[str] = set()
    live = [f for f in bank_index.files(memory_path, "episodes")
            if (f.frontmatter or {}).get("origin") == ORIGIN and not (f.frontmatter or {}).get(evidence.LOCKED_NOTE_KEY)]
    note_ids = set(note_ids)
    if keys:
        for f in live:
            fm = f.frontmatter or {}
            older_id = str(fm.get("note_id") or "")
            try:
                if older_id and older_id not in note_ids and _keys_of(fm, f.body()) & keys:
                    note_ids.add(older_id)
            except Exception as exc:  # noqa: BLE001 — one unreadable file never stops the rest
                logger.warning(f"Notes: could not read an episode: {type(exc).__name__}")
    for f in live:
        fm = f.frontmatter or {}
        try:
            if str(fm.get("note_id") or "") not in note_ids and not is_stub(f.body()):
                continue
            if _retire_file(f.path, at, out):
                retired_ids.add(str(fm.get("id") or f.path.stem))
        except Exception as exc:  # noqa: BLE001 — one unreadable file never stops the rest
            logger.warning(f"Notes: could not retire an episode: {type(exc).__name__}")
    if _forget_in_index(memory_path, retired_ids, note_ids):
        out.paths.append(f"sources/{NOTES_INDEX_FILENAME}")
    return out


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
            await _commit_retired(memory_path, retired.paths, "cicada", "sleep/locked_notes")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Notes: retiring locked stubs failed: {type(exc).__name__}")


# --- Sync (diff + emit only what's new/changed) -----------------------------


def _placement(note: NoteRecord, known: dict | None = None) -> tuple[str | None, str | None]:
    """The note's account and folder as the index keeps them. A record that names no account (an older app) keeps
    the one already known."""
    return note.account or (known or {}).get("account") or None, note.folder or None


def _index_entry(episode_id: str, note: NoteRecord, known: dict | None = None) -> dict:
    account, folder = _placement(note, known)
    return {"episode_id": episode_id, "modified": note.modified, "note_id": note.note_id,
            "account": account, "folder": folder}


async def sync_notes(memory_path: Path, *, dump: str, accounts: dict[str, str] | None = None,
                     locked_ids: list[str] | None = None, locked_keys: list[str] | None = None) -> dict[str, Any]:
    """Parse ``dump`` and write one episode per new or modified note.

    A brand-new note id -> new episode. A previously-seen note whose
    ``modified`` timestamp changed -> a fresh episode is written (an "updated"
    episode, not an edit-in-place — the episode log is append-only, same as
    every other connector) and the index is repointed at it. An unchanged
    note (same id, same ``modified``) is skipped entirely.

    Returns ``{"new": int, "updated": int, "skipped": int, "total": int,
    "excluded": int, "locked": int, "retired": int}``.

    G234: a record whose id is in ``locked_ids`` is dropped whatever it carries, and every episode of that note is
    retired. A record with no text is never staged either. An older app sends no ``locked_ids``, so its blank records
    are taken as locked (that is what Notes returned for a locked note); what it cannot be protected from is a body it
    reads while a locked note is open, which looks like any other note.

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
    for note in parse_notes_dump(dump):
        if note.note_id in flagged:
            continue
        if not note.body.strip():
            if locked_ids is None and note.note_id:
                flagged.add(note.note_id)
            continue
        readable.append(note)
    notes = readable
    locked_found = len(flagged)
    keys = {str(k) for k in (locked_keys or []) if k}
    retired = retire_locked(memory_path, flagged, keys) if flagged or keys else Retired()
    if retired.paths:
        logger.info(f"Notes: {len(retired.paths)} path(s) retired for locked notes")
        try:
            await _commit_retired(memory_path, retired.paths, "user", "user/notes_sync")
        except Exception as e:
            logger.warning(f"Locked notes commit failed: {type(e).__name__}")
    # 2026-11-04 — the app sends each note's account beside the dump (`note_accounts`), so a backend that predates it
    # still reads the 8-field records; a ninth field in the dump itself is read too.
    for note in notes:
        if not note.account and accounts and (named := accounts.get(note.note_id)):
            note.account = " ".join(str(named).split())[:120]
    excluded_folders = {
        f.strip().casefold()
        for f in os.environ.get("CICADA_NOTES_EXCLUDE_FOLDERS", "").split(",")
        if f.strip()
    }
    excluded_count = 0
    if excluded_folders:
        kept = []
        for note in notes:
            if note.folder.casefold() in excluded_folders:
                excluded_count += 1
            else:
                kept.append(note)
        notes = kept
    new_count = 0
    updated_count = 0
    skipped_count = 0
    episodes_dir = memory_path / "episodes"

    placed = 0
    _INDEX_LOCK.acquire()
    try:
        idx = _load_notes_index(memory_path)
        for note in notes:
            key = _note_key(note)
            existing = idx.get(key)
            if existing is None:
                episode_id = _write_note_episode(episodes_dir, note)
                idx[key] = _index_entry(episode_id, note)
                new_count += 1
            elif existing.get("modified") != note.modified:
                episode_id = _write_note_episode(episodes_dir, note)
                idx[key] = _index_entry(episode_id, note, existing)
                updated_count += 1
            else:
                skipped_count += 1
                # 2026-11-04 — where a note lives (its account and folder) is kept current in the index alone: a note moved
                # to another folder, or kept by a sync from before accounts were sent, is placed without a new episode
                # (nothing Sleep reads changed).
                now_placed = _placement(note, existing)
                if now_placed != (existing.get("account"), existing.get("folder")):
                    existing["account"], existing["folder"] = now_placed
                    placed += 1
        if new_count or updated_count or placed:
            _save_notes_index(memory_path, idx)
    finally:
        _INDEX_LOCK.release()

    if new_count or updated_count or placed:
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
