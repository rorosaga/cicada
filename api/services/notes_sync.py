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

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from api.services import episode_ids, episode_scrub

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

# A note body beyond this is truncated before it becomes an episode — an
# episode is a lightweight staging chunk, not a full document store; the Sleep
# cycle only needs enough text to extract entities/claims from.
MAX_NOTE_BODY_CHARS = 20_000


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
        if len(fields) not in (_EXPECTED_FIELDS, _DATED_FIELDS):
            logger.debug(f"Skipping malformed note record ({len(fields)} field(s), expected {_EXPECTED_FIELDS})")
            continue
        note_id, name, body, created, modified, folder = fields[:_EXPECTED_FIELDS]
        modified_at = _aware(*fields[_EXPECTED_FIELDS:]) if len(fields) == _DATED_FIELDS else ""
        records.append(NoteRecord(
            note_id=note_id.strip(),
            name=name.strip(),
            body=body,
            created=created.strip(),
            modified=modified.strip(),
            folder=folder.strip(),
            modified_at=modified_at,
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
        # Folder name as a tag hint for the Sleep extractor/entity tagging —
        # mirrors bookmark_sync tagging synced items with their origin.
        "tags": [note.folder] if note.folder else [],
    }
    episode_id = episode_ids.create_episode(episodes_dir, frontmatter, body)
    return episode_id


# --- Sync (diff + emit only what's new/changed) -----------------------------


async def sync_notes(memory_path: Path, *, dump: str) -> dict[str, Any]:
    """Parse ``dump`` and write one episode per new or modified note.

    A brand-new note id -> new episode. A previously-seen note whose
    ``modified`` timestamp changed -> a fresh episode is written (an "updated"
    episode, not an edit-in-place — the episode log is append-only, same as
    every other connector) and the index is repointed at it. An unchanged
    note (same id, same ``modified``) is skipped entirely.

    Returns ``{"new": int, "updated": int, "skipped": int, "total": int,
    "excluded": int}``.

    Folder exclusion: ``CICADA_NOTES_EXCLUDE_FOLDERS`` (comma-separated,
    case-insensitive folder names, default empty) drops matching notes
    BEFORE the dedup index ever sees them — so an excluded folder ingests
    cleanly later if the exclusion is lifted. Motivating case: a
    password-notes folder must never land in a plaintext memory graph that
    LLM clients read.
    """
    memory_path = Path(memory_path)
    notes = parse_notes_dump(dump)
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
    idx = _load_notes_index(memory_path)

    new_count = 0
    updated_count = 0
    skipped_count = 0
    episodes_dir = memory_path / "episodes"

    for note in notes:
        key = _note_key(note)
        existing = idx.get(key)
        if existing is None:
            episode_id = _write_note_episode(episodes_dir, note)
            idx[key] = {
                "episode_id": episode_id,
                "modified": note.modified,
                "note_id": note.note_id,
            }
            new_count += 1
        elif existing.get("modified") != note.modified:
            episode_id = _write_note_episode(episodes_dir, note)
            idx[key] = {
                "episode_id": episode_id,
                "modified": note.modified,
                "note_id": note.note_id,
            }
            updated_count += 1
        else:
            skipped_count += 1

    if new_count or updated_count:
        _save_notes_index(memory_path, idx)
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
