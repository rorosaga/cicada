"""Keyless Apple Notes one-way import connector.

Enumerates the local Notes.app database via a single batched ``osascript``
call (one AppleScript invocation returns every note across every account/
folder — never one invocation per note), diffs against what has already been
ingested, and writes ONE episode per new or modified note into the standard
episode inbox (the same "episode inbox" ``telegram_capture``/``media_ingestor``
write to). One-way: Cicada never writes back into Notes.app.

No new dedup architecture — mirrors ``bookmark_sync``'s "diff against an
index, only ingest what's new" shape, but note ids aren't URLs, so this gets
its own ``memory/sources/notes_index.json`` keyed on note id (falling back to
a hash of name+creation-date for the rare note with no id). Storing the
last-seen *modification* date (not just presence) lets an edited note
re-emit an updated episode while an unchanged note is skipped on every
subsequent sync.

TESTS MUST NEVER INVOKE REAL ``osascript`` — it triggers a macOS TCC consent
prompt and is inherently non-hermetic/non-portable. The one function that
shells out, ``_run_osascript``, is deliberately tiny and is the single seam
every test monkeypatches; everything else in this module is pure (takes the
raw dump as a plain string) or file I/O against a ``tmp_path`` workspace.
"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from api.services import markdown_parser
from api.services.media_ingestor import _next_episode_id

NOTES_INDEX_FILENAME = "notes_index.json"

# Delimiters chosen to be vanishingly unlikely inside real note text: ASCII
# Record/Unit Separator control characters, never typed by a human and
# stripped by essentially every text editor.
FIELD_SEP = "\x1e"
RECORD_SEP = "\x1d"
_EXPECTED_FIELDS = 6  # id, name, body, created, modified, folder

# A note body beyond this is truncated before it becomes an episode — an
# episode is a lightweight staging chunk, not a full document store; the Sleep
# cycle only needs enough text to extract entities/claims from.
MAX_NOTE_BODY_CHARS = 20_000

# Single batched AppleScript: walks every account -> folder -> note and emits
# one RECORD_SEP-terminated, FIELD_SEP-joined record per note. A per-note
# `try` block means one note Notes.app can't read (rare, corrupt note) is
# skipped rather than aborting the whole dump.
_APPLESCRIPT = """
tell application "Notes"
    set out to ""
    repeat with acc in accounts
        repeat with fld in folders of acc
            repeat with nt in notes of fld
                try
                    set noteId to id of nt as string
                    set noteName to name of nt as string
                    set noteBody to plaintext of nt as string
                    set cDate to (creation date of nt) as string
                    set mDate to (modification date of nt) as string
                    set folderName to name of fld as string
                    set out to out & noteId & (ASCII character 30) & noteName & (ASCII character 30) & noteBody & (ASCII character 30) & cDate & (ASCII character 30) & mDate & (ASCII character 30) & folderName & (ASCII character 29)
                end try
            end repeat
        end repeat
    end repeat
    return out
end tell
""".strip()


# --- The one real I/O seam --------------------------------------------------


def _run_osascript() -> str:
    """The single real call to ``osascript`` — kept intentionally small so
    every test monkeypatches exactly this function instead of touching
    ``subprocess``/the real Notes.app directly.

    Raises on a non-zero exit (e.g. no Notes.app, AppleScript automation
    denied, not macOS) or if ``osascript`` isn't on ``PATH``; callers degrade
    that to an empty sync rather than crashing (see ``sync_from_local_notes``).
    Never invoked by the test suite.
    """
    result = subprocess.run(
        ["osascript", "-e", _APPLESCRIPT],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"osascript failed: {result.stderr.strip()}")
    return result.stdout


# --- Parsing -----------------------------------------------------------------


@dataclass
class NoteRecord:
    note_id: str
    name: str
    body: str
    created: str
    modified: str
    folder: str


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
        if len(fields) != _EXPECTED_FIELDS:
            logger.debug(f"Skipping malformed note record ({len(fields)} field(s), expected {_EXPECTED_FIELDS})")
            continue
        note_id, name, body, created, modified, folder = fields
        records.append(NoteRecord(
            note_id=note_id.strip(),
            name=name.strip(),
            body=body,
            created=created.strip(),
            modified=modified.strip(),
            folder=folder.strip(),
        ))
    return records


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
    now = datetime.now()
    ep_date = now.strftime("%Y-%m-%d")
    episode_id = _next_episode_id(episodes_dir, ep_date)
    timestamp = now.isoformat() + "Z"

    body = _episode_body(note)
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
    markdown_parser.write(episodes_dir / f"{episode_id}.md", frontmatter, body)
    return episode_id


# --- Sync (diff + emit only what's new/changed) -----------------------------


async def sync_notes(memory_path: Path, *, dump: str) -> dict[str, Any]:
    """Parse ``dump`` and write one episode per new or modified note.

    A brand-new note id -> new episode. A previously-seen note whose
    ``modified`` timestamp changed -> a fresh episode is written (an "updated"
    episode, not an edit-in-place — the episode log is append-only, same as
    every other connector) and the index is repointed at it. An unchanged
    note (same id, same ``modified``) is skipped entirely.

    Returns ``{"new": int, "updated": int, "skipped": int, "total": int}``.
    """
    memory_path = Path(memory_path)
    notes = parse_notes_dump(dump)
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
    }


async def sync_from_local_notes(memory_path: Path) -> dict[str, Any]:
    """Best-effort, offline-safe sync against the real local Notes.app.

    Calls ``_run_osascript()`` — the one seam that shells out. Any failure
    (no Notes.app, AppleScript automation denied, not macOS) degrades to an
    empty sync rather than raising. Not exercised against real ``osascript``
    in tests.
    """
    try:
        raw = _run_osascript()
    except Exception as e:
        logger.debug(f"Could not read Apple Notes: {type(e).__name__}: {e}")
        return {"new": 0, "updated": 0, "skipped": 0, "total": 0}

    return await sync_notes(memory_path, dump=raw)


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
