"""An agent's own memory notes, captured as its words (owner ruling 43, 2026-10-27; G105, G110).

Claude Code keeps auto-memory notes per project — ``~/.claude/projects/<project>/memory/*.md``, each with a short YAML
head (``name``, ``description``, ``metadata: {type, originSessionId, modified}``) and a ``MEMORY.md`` index of them.
They are agent-written, curated summaries, often a cleaner record than the raw turns (which event it was, what was
left to the person, which session did it). Ruling 43: Cicada may read them. It is NOT the transcripts: their rail is
unchanged.

**Who reads the files.** The harness's own hook (``api/hooks/memory_notes.py``), on the machine where the notes live,
posts their bytes here; the backend never opens a path for this source. Three reasons: the backend's one read under
``~/.claude`` stays the transcript read it already validates (CLAUDE.md, "Transcripts under ~/.claude/ are never read
anywhere else"); a client of a server elsewhere (ruling 28) and a headless server with no app work the same way,
because the reader is wherever Claude Code runs; and the hook fires exactly when notes change — inside a session.

**What this module does** — pure parsing plus the one stager (``episode_staging``), no model:

* One episode per note, keyed ``agent-memory:<harness>:<device>:<project>/<file>``: an edit updates it in place,
  re-queued (``processed: false``); a note gone from a complete listing is tombstoned, never unlinked; every body is
  scrubbed by the stager.
* **An agent's words, never the person's.** The body is one ``assistant:`` turn and the episode declares
  ``evidence_kind: assistant`` (the ruling-32 relay precedent): read by Sleep, searchable, never counted as the
  person's own words — not for promotion's own-words rung, not for ruling 29's settling, and a claim resting on it
  never closes one resting on the person's words (``inbox_tend.may_close``).
* **Dated when the note was last written** (ruling 39): ``timestamp`` is the note's own ``modified`` (else the file's
  modification time the hook sent); ``received_at`` is stamped by ``episode_ids.create_episode`` as on every episode.
* **No mention** (``episode_time.UNTIMED_SOURCES``): a note's date is when the summary was last edited, not when
  anything in it came up — the same rule as a chat export's memory entry. Its facts are kept; the session that wrote
  it is captured on its own, so counting the note too would count that session twice. Sleep is told it is an older,
  lower-trust summary (``entity_extractor.MEMORY_SOURCE_NOTE``), so a newer conversation's statement is preferred.
* **Which agent and session:** ``harness`` names the agent; ``origin_session_id`` is the note's ``originSessionId``,
  and ``origin_episode`` that session's episode when Cicada holds it (linked again on a later sync once it does).
* The ``MEMORY.md`` index is mostly one link line per note, each captured as its own episode; a line that links to a
  note file is dropped (its note says it, or it was deleted and the pointer is stale), and an index with nothing else
  is no episode.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from api.services import bank_index, episode_ids, episode_scrub, episode_staging
from api.services.episode_staging import EpisodeDraft, Turn

SOURCE = "agent-memory"
WRITER = "agent-memory"
HARNESSES = ("claude-code",)
INDEX_FILE = "MEMORY.md"
SETTINGS_FILENAME = "agent_memory.json"
#: The device a post signed with the server's own token is filed under (a device token names its own id).
LOCAL_DEVICE = "local"
#: The most notes one post may carry, and the most characters one note may hold (the largest seen is ~50 KB).
MAX_NOTES = 2000
MAX_NOTE_CHARS = 256 * 1024
_DESCRIPTION_MAX = 300
_SESSION_RE = re.compile(r"^[0-9a-fA-F-]{8,64}$")
_NAME_RE = re.compile(r"^[^/\\\x00]{1,255}$")
_LINK_RE = re.compile(r"\]\(([^)\s]+\.md)\)")
_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)


# --- The switch ------------------------------------------------------------------------------------------------------

def settings_path(memory_path: Path) -> Path:
    return Path(memory_path) / "sources" / SETTINGS_FILENAME


def load_settings(memory_path: Path) -> dict:
    """On unless the person turned it off (ruling 43: on by default)."""
    try:
        data = json.loads(settings_path(memory_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return {"enabled": bool(data.get("enabled", True)) if isinstance(data, dict) else True}


def save_settings(memory_path: Path, *, enabled: bool) -> dict:
    path = settings_path(memory_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"enabled": bool(enabled)}
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data


# --- Parsing ---------------------------------------------------------------------------------------------------------

def parse_note(text: str) -> tuple[dict, str]:
    """``(head, body)``: the YAML head as a dict (``{}`` when there is none or it does not parse) and the rest."""
    match = _FRONTMATTER_RE.match(text or "")
    if not match:
        return {}, (text or "").strip()
    try:
        head = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        head = None
    return (head if isinstance(head, dict) else {}), text[match.end():].strip()


def _field(head: dict, key: str):
    """A head field, top level first, then under ``metadata`` (both shapes are in use)."""
    value = head.get(key)
    if value in (None, ""):
        meta = head.get("metadata")
        value = meta.get(key) if isinstance(meta, dict) else None
    return value


def _aware(value) -> str | None:
    """An aware moment as the stored UTC shape, or ``None`` — a naive or unreadable value is never guessed."""
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str) and value.strip():
        try:
            moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if moment.tzinfo is None:
        return None
    return episode_ids.to_utc_iso(moment.astimezone(timezone.utc))


def _text(value, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def source_id(harness: str, device: str, project: str, file: str) -> str:
    return f"agent-memory:{harness}:{device}:{project}/{file}"


def note_sha(note: dict) -> str:
    """A note's identity apart from the folder it sits in: its file name and its bytes. Claude Code names a project's
    folder after the checkout's path, so a renamed, moved or re-cloned repository whose notes came along files the
    same notes under a new folder; this is what recognises them (``episode_staging``'s rename by content)."""
    return hashlib.sha256(f"{note['file']}\0{note['text']}".encode("utf-8", "surrogateescape")).hexdigest()[:16]


def session_episodes(memory_path: Path) -> dict[str, str]:
    """``session_id`` → episode id for every captured harness session in the bank (the frontmatter cache)."""
    out: dict[str, str] = {}
    try:
        for f in bank_index.files(Path(memory_path), "episodes"):
            fm = f.frontmatter or {}
            sid = str(fm.get("session_id") or "").strip()
            if sid and fm.get("capture_kind") == "transcript" and sid not in out:
                out[sid] = str(fm.get("id") or f.stem)
    except OSError:
        return out
    return out


def note_draft(note: dict, *, harness: str, device: str, sessions: dict[str, str]) -> EpisodeDraft | None:
    """One note as an episode draft, or ``None`` when it holds no words."""
    head, body = parse_note(note["text"])
    if not body:
        return None
    project, file = note["project"], note["file"]
    # The head's words are scrubbed like the body (review of #560): they ride the frontmatter, the title and, for a
    # feedback/user note, the handshake's "How to work with me". The stager scrubs every extra too.
    name = episode_scrub.scrub(_text(head.get("name"), 200))[0] or file.removesuffix(".md")
    description = episode_scrub.scrub(_text(head.get("description"), _DESCRIPTION_MAX))[0]
    when = _aware(_field(head, "modified")) or _aware(note.get("modified_at"))
    session = str(_field(head, "originSessionId") or "").strip()
    session = session if _SESSION_RE.match(session) else ""
    memo: dict = {"project": project, "file": file}
    kind = _text(_field(head, "type"), 40)
    if kind:
        memo["type"] = kind
    if description:
        memo["description"] = description
    extra: dict = {"evidence_kind": "assistant", "harness": harness, "agent_memory": memo}
    if device != LOCAL_DEVICE:
        extra["device"] = device
    if session:
        extra["origin_session_id"] = session
        if sessions.get(session):
            extra["origin_episode"] = sessions[session]
    words = f"{description}\n\n{body}" if description and description not in body else body
    return EpisodeDraft(
        title=f"Agent memory: {name}", source_id=source_id(harness, device, project, file),
        source_updated_at=when, timestamp=when, original_date=episode_ids.id_day(when) if when else None,
        source=SOURCE, origin=harness, turns=[Turn(text=words, speaker="assistant", ts=when)],
        extra=extra, writer=WRITER, redate=when is not None, content_sha=note_sha(note),
    )


def index_draft(note: dict, *, harness: str, device: str) -> EpisodeDraft | None:
    """``MEMORY.md`` without its link lines; ``None`` when nothing but links and headings is left."""
    _head, body = parse_note(note["text"])
    kept = [line for line in body.splitlines() if not _LINK_RE.search(line)]
    words = "\n".join(kept).strip()
    if not any(line.strip() and not line.lstrip().startswith("#") for line in kept):
        return None
    when = _aware(note.get("modified_at"))
    return EpisodeDraft(
        title=f"Agent memory index: {note['project']}"[:200],
        source_id=source_id(harness, device, note["project"], note["file"]),
        source_updated_at=when, timestamp=when, original_date=episode_ids.id_day(when) if when else None,
        source=SOURCE, origin=harness, turns=[Turn(text=words, speaker="assistant", ts=when)],
        extra={"evidence_kind": "assistant", "harness": harness,
               "agent_memory": {"project": note["project"], "file": note["file"], "type": "index"},
               **({"device": device} if device != LOCAL_DEVICE else {})},
        writer=WRITER, redate=when is not None, content_sha=note_sha(note),
    )


def clean_notes(raw) -> list[dict]:
    """What arrived, re-checked: a project folder and a ``.md`` file name each one path segment, text within its cap.
    Anything else is dropped (the hook sends nothing else)."""
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for item in (raw or [])[:MAX_NOTES]:
        if not isinstance(item, dict):
            continue
        project, file, text = str(item.get("project") or ""), str(item.get("file") or ""), item.get("text")
        if not (_NAME_RE.match(project) and _NAME_RE.match(file) and file.endswith(".md")) \
                or project in (".", "..") or not isinstance(text, str) or len(text) > MAX_NOTE_CHARS:
            continue
        if (project, file) in seen:
            continue
        seen.add((project, file))
        out.append({"project": project, "file": file, "text": text, "modified_at": item.get("modified_at")})
    return out


# --- Ingest ----------------------------------------------------------------------------------------------------------

def ingest(memory_path: Path, notes, *, harness: str, device: str | None, complete: bool) -> dict:
    """Stage one posted snapshot. ``complete``: the post holds every note the harness root has, so a note this device
    posted before and not now was deleted — tombstoned. An incomplete or empty post tombstones nothing (a half-read
    root never makes every note look deleted)."""
    memory_path = Path(memory_path)
    episodes_dir = memory_path / "episodes"
    device = device or LOCAL_DEVICE
    notes = clean_notes(notes)
    sessions = session_episodes(memory_path) if notes else {}
    drafts: list[EpisodeDraft] = []
    present: set[str] = set()
    for note in notes:
        present.add(source_id(harness, device, note["project"], note["file"]))
        if note["file"] == INDEX_FILE:
            draft = index_draft(note, harness=harness, device=device)
        else:
            draft = note_draft(note, harness=harness, device=device, sessions=sessions)
        if draft is not None:
            drafts.append(draft)
    prefix = f"agent-memory:{harness}:{device}:"
    deleted: list[str] = []
    copies = 0
    if notes:
        index, _ = episode_staging.scan(episodes_dir)
        if complete:
            deleted = sorted(sid for sid, e in index.items()
                             if sid.startswith(prefix) and sid not in present and not e.fm.get("source_deleted_at"))
        # A repository renamed, moved or cloned again gets a new Claude Code folder. Notes that came along unchanged
        # are the notes already held: a moved one (its old folder gone from a complete snapshot) is repointed by the
        # stager's rename by content, keeping its episode; a copy (the old folder still there, or a partial read)
        # is no second episode.
        held = {str(e.fm.get("content_sha")) for sid, e in index.items()
                if sid.startswith(prefix) and e.fm.get("content_sha") and not e.fm.get("source_deleted_at")
                and sid not in deleted}
        kept = [d for d in drafts if d.source_id in index or d.content_sha not in held]
        copies = len(drafts) - len(kept)
        drafts = kept
    staged = episode_staging.stage(drafts, episodes_dir, deleted_source_ids=deleted, bank=memory_path.name)
    paths = list(staged.paths)
    linked = _link_sessions(memory_path, drafts, staged, paths)
    return {"notes": len(notes), "created": staged.created, "updated": staged.updated, "skipped": staged.skipped,
            "tombstoned": staged.tombstoned, "linked": linked, "paths": paths,
            "moved": len(staged.renamed_sources), "copies": copies}


def _link_sessions(memory_path: Path, drafts: list[EpisodeDraft], staged, paths: list[str]) -> int:
    """An unchanged note whose session was captured after the note was: link it now (frontmatter only, queue
    untouched — ``episode_staging.reattribute``)."""
    wanted = {d.source_id: d.extra["origin_episode"] for d in drafts if d.extra.get("origin_episode")}
    if not wanted:
        return 0
    index, _ = episode_staging.scan(memory_path / "episodes")
    linked = 0
    for sid, ep in wanted.items():
        entry = index.get(sid)
        if entry is None or entry.fm.get("origin_episode") == ep:
            continue
        if episode_staging.reattribute(entry.path, extra={"origin_episode": ep}, queue_for_sleep=True):
            linked += 1
            rel = f"episodes/{entry.path.name}"
            if rel not in paths:
                paths.append(rel)
    return linked
