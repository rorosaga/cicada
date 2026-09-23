"""Wispr Flow meetings, notes and (opt-in) dictation (G134 · R-N1 · R-N2 · R-N3).

Wispr Flow keeps everything in a local SQLite database under
``~/Library/Application Support/Wispr Flow`` plus one ``refined.ndjson`` of
diarized utterances per meeting. The APP opens both read-only and posts a
whitelisted projection (R-N1, R-LS21); this module is the one parser — pure,
fixture-tested — and it re-applies the same whitelist and the same filters
(deleted, demo and unfinished meetings never become memory) to whatever
arrives, so a newer or buggier app cannot widen what is stored.

Speakers (R-N2, R-LS22): an utterance is ``speaker:<label>: text`` — the
speaker's name slug, else their numeric id — and ``user:`` only when the name is
one the person listed as theirs (``owner_speaker_names``). Wispr Flow's own
summary, notes and to-dos are its model's words and sit under an ``assistant:``
line. Every meeting is ``consent: unknown`` until the person says otherwise
(G95's rail). Emails never enter a name or a participant list.

Dictation (R-LS23) is off by default — dictated text goes into every app,
passwords included. When on, only ``timestamp``, ``formattedText``/``editedText``,
``app`` and ``numWords`` are read, one episode per UTC day, merged across posts
through the day's own ``turns`` sidecar; password-manager apps are dropped. Every
body is scrubbed by the stager (R-N3).
"""

from __future__ import annotations

import html
import json
import re
import threading
from datetime import datetime
from pathlib import Path

from api.services import episode_ids, episode_scrub, episode_staging, evidence, markdown_parser
from api.services.episode_staging import EpisodeDraft, Turn
from api.services.id_utils import sanitize_id

SETTINGS_FILENAME = "wispr_flow.json"
ORIGIN = "wispr-flow"
CHANNEL_ID = "wispr-flow"
MEETING_COLUMNS = ("id", "title", "createdAt", "modifiedAt", "endedAt", "isDeleted", "finalized",
                   "isTourDemo", "transcriptDeletedAt", "participantNames", "speakerMap", "notes", "summary")
NOTE_COLUMNS = ("id", "title", "content", "createdAt", "modifiedAt", "isDeleted")
TODO_COLUMNS = ("meetingId", "title", "status", "isDeleted")
HISTORY_COLUMNS = ("timestamp", "formattedText", "editedText", "app", "numWords")
UTTERANCE_KEYS = ("timestamp", "text", "speaker")
#: Never read on either side, whatever a future Wispr Flow schema adds (R-LS21).
FORBIDDEN_COLUMNS = ("audio", "builtInAudio", "screenshot", "axText", "axHTML", "textboxContents",
                     "pastedText", "url", "asrText")
DONE_STATUSES = frozenset({"done", "completed", "complete", "cancelled", "canceled", "archived"})
DICTATION_APP_DENYLIST = frozenset({
    "com.1password.1password", "com.agilebits.onepassword7", "com.agilebits.onepassword-osx",
    "com.apple.keychainaccess", "com.apple.Passwords", "com.bitwarden.desktop",
    "com.lastpass.LastPass", "com.dashlane.dashlanephonefinal", "org.keepassxc.keepassxc",
})
MAX_MEETINGS = 200
MAX_HISTORY = 5000
_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")
_HTML_TAG_RE = re.compile(r"<[^>]+>")


# --- Settings ---------------------------------------------------------------


def settings_path(memory_path: Path) -> Path:
    return Path(memory_path) / "sources" / SETTINGS_FILENAME


def _clean_names(value) -> list[str]:
    out: list[str] = []
    for raw in value if isinstance(value, list) else []:
        name = " ".join(str(raw or "").split())[:80]
        if name and not _EMAIL_RE.search(name) and name not in out:
            out.append(name)
    return out[:10]


def load_settings(memory_path: Path) -> dict:
    try:
        data = json.loads(settings_path(memory_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data = data if isinstance(data, dict) else {}
    return {"enabled": bool(data.get("enabled", False)),
            "include_dictation": bool(data.get("include_dictation", False)),
            "owner_speaker_names": _clean_names(data.get("owner_speaker_names"))}


def save_settings(memory_path: Path, *, enabled: bool, include_dictation: bool, owner_speaker_names) -> dict:
    data = {"enabled": bool(enabled), "include_dictation": bool(include_dictation),
            "owner_speaker_names": _clean_names(owner_speaker_names)}
    with _LOCK:
        pending = load_todos_pending(memory_path)
        _write(memory_path, {**data, TODOS_PENDING_KEY: pending} if pending else data)
    return data


def _write(memory_path: Path, data: dict) -> None:
    path = settings_path(memory_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


# --- To-dos a running Sleep deferred (L final review, finding 5) --------------
#
# A to-do claim lands on the OWNER's page — the page Stage 5 rewrites. The
# folder route already defers every entity write while a cycle runs (R-LS17);
# this path did not, and the app's watcher posts here on its own, so a sync
# mid-cycle could lose its claims to Sleep's read-modify-write or ride Sleep's
# `git add -A` under the model's name. Deferred meetings are listed here and
# replayed from their STORED episodes on the next sync outside a cycle, or by
# the Sleep tail — the `papers_pending` / `papers.reconcile_pending` shape.

TODOS_PENDING_KEY = "todos_pending"
_LOCK = threading.RLock()
_TODOS_HEADING = "To-dos (from Wispr Flow)"


def load_todos_pending(memory_path: Path) -> list[str]:
    try:
        data = json.loads(settings_path(memory_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    raw = data.get(TODOS_PENDING_KEY) if isinstance(data, dict) else None
    return [str(s) for s in raw if str(s).startswith("wispr:meeting:")] if isinstance(raw, list) else []


def _save_todos_pending(memory_path: Path, source_ids: list[str]) -> None:
    """Rewrite only the pending list; the person's settings keep their values."""
    try:
        data = json.loads(settings_path(memory_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data = data if isinstance(data, dict) else {}
    if source_ids:
        data[TODOS_PENDING_KEY] = sorted(set(source_ids))
    else:
        data.pop(TODOS_PENDING_KEY, None)
    _write(memory_path, data)


def todos_in_episode(body: str) -> list[str]:
    """The open to-do titles a stored meeting episode lists — what
    `meeting_draft` rendered as its `To-dos (from Wispr Flow)` turn."""
    out: list[str] = []
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if line.rstrip().endswith(_TODOS_HEADING) and line.startswith("assistant:"):
            for item in lines[i + 1:]:
                if not item.startswith("- "):
                    break
                title = item[2:].strip()
                if title and title not in out:
                    out.append(title)
            break
    return out


def replay_pending_todos(memory_path: Path, *, skip: set[str] = frozenset()) -> dict:
    """Write the to-do claims a running cycle deferred, from each meeting's
    stored episode, and clear the list. ``skip`` names meetings the caller just
    wrote itself. A meeting deleted meanwhile has nothing left to claim."""
    memory_path = Path(memory_path)
    with _LOCK:
        pending = load_todos_pending(memory_path)
        if not pending:
            return {"replayed": 0, "written": 0, "paths": []}
        index, _ = episode_staging.scan(memory_path / "episodes")
        touched: dict[str, str] = {}
        meeting_todos: dict[str, list[str]] = {}
        for sid in pending:
            entry = index.get(sid)
            if sid in skip or entry is None or entry.fm.get("source_deleted_at"):
                continue
            titles = todos_in_episode(markdown_parser.parse(entry.path).body)
            if titles:
                touched[sid], meeting_todos[sid] = entry.id, titles
        claims = write_todo_claims(memory_path, _Touched(touched), meeting_todos)
        _save_todos_pending(memory_path, [])
        return {"replayed": len(touched), "written": claims["written"],
                "paths": claims["paths"] + [f"sources/{SETTINGS_FILENAME}"]}


class _Touched:
    """`write_todo_claims` reads only `.touched` off a stage result."""

    def __init__(self, touched: dict[str, str]):
        self.touched = touched


# --- Field helpers ----------------------------------------------------------


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes"}


def _ts(value) -> str | None:
    """Any timestamp shape Wispr Flow might store — ISO text, epoch seconds or
    epoch milliseconds — as aware UTC (G114 R2), or ``None``."""
    if value is None or isinstance(value, bool) or value == "":
        return None
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 1e11 else value
        try:
            return episode_ids.to_utc_iso(float(seconds))
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return _ts(float(text))
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return episode_ids.to_utc_iso(dt)


def _turn_ts(value) -> str | None:
    """An utterance time: aware UTC when it is a date, else the raw offset
    ("00:23:41") — informational only, it lives in the ``turns`` sidecar."""
    parsed = _ts(value)
    if parsed or value in (None, ""):
        return parsed
    return str(value).strip()[:32] or None


def _json_or(value, default):
    if isinstance(value, (list, dict)):
        return value
    if isinstance(value, str) and value.strip()[:1] in ("[", "{"):
        try:
            return json.loads(value)
        except ValueError:
            return default
    return default


def _one_name(item) -> str | None:
    raw = item.get("name") if isinstance(item, dict) else item
    name = " ".join(str(raw or "").split())[:80]
    return name if name and not _EMAIL_RE.search(name) else None


def _names(value) -> list[str]:
    raw = _json_or(value, None)
    if raw is None:
        raw = str(value or "").split(",")
    out: list[str] = []
    for item in raw if isinstance(raw, list) else []:
        name = _one_name(item)
        if name and name not in out:
            out.append(name)
    return out


def _speaker_map(value) -> dict[str, str]:
    raw = _json_or(value, {})
    out: dict[str, str] = {}
    if isinstance(raw, dict):
        for key, item in raw.items():
            name = _one_name(item)
            if name:
                out[str(key)] = name
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and item.get("id") is not None:
                name = _one_name(item)
                if name:
                    out[str(item["id"])] = name
    return out


def _plain(value) -> str:
    text = str(value or "")
    if "<" in text and ">" in text:
        text = html.unescape(_HTML_TAG_RE.sub("\n", text))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def speaker_marker(speaker, speaker_map: dict[str, str], owner_names: set[str]) -> str:
    """``user`` for a name the person listed as theirs, else ``speaker:<label>``
    (R-N2 / R-LS22). The label is a slug, never containing ``:``, so
    ``evidence._SPEAKER_RE`` reads it back."""
    speaker = speaker if isinstance(speaker, dict) else {}
    raw_id = speaker.get("id")
    sid = re.sub(r"[^A-Za-z0-9_-]", "", "" if raw_id is None else str(raw_id))[:32]
    name = _one_name(speaker) or speaker_map.get(sid) or ""
    if name and name.casefold() in owner_names:
        return "user"
    label = sanitize_id(name)[:48].strip("-") if name else ""
    if label and label != "unnamed":
        return f"speaker:{label}"
    return f"speaker:{sid or 'unknown'}"


# --- Drafts -----------------------------------------------------------------


def meeting_draft(item: dict, todos: list[dict], owner_names: set[str]) -> tuple[EpisodeDraft | None, list[str]]:
    """One finalized meeting as one episode, and its open to-do titles."""
    row = {k: (item.get("row") or {}).get(k) for k in MEETING_COLUMNS}
    meeting_id = str(row["id"] or "").strip()
    if (not meeting_id or _truthy(row["isDeleted"]) or _truthy(row["isTourDemo"])
            or not _truthy(row["finalized"])):
        return None, []
    speaker_map = _speaker_map(row["speakerMap"])
    turns: list[Turn] = []
    summary = _plain(row["summary"])
    if summary:
        turns.append(Turn(f"Summary (written by Wispr Flow)\n{summary}", "assistant"))
    notes = _plain(row["notes"])
    if notes:
        turns.append(Turn(f"Notes (Wispr Flow)\n{notes}", "assistant"))
    open_todos: list[str] = []
    for todo in todos:
        todo = {k: todo.get(k) for k in TODO_COLUMNS}
        title = " ".join(str(todo["title"] or "").split())
        if (title and not _truthy(todo["isDeleted"]) and title not in open_todos
                and str(todo["status"] or "").strip().lower() not in DONE_STATUSES):
            open_todos.append(title)
    if open_todos:
        turns.append(Turn("To-dos (from Wispr Flow)\n" + "\n".join(f"- {t}" for t in open_todos), "assistant"))
    if not row["transcriptDeletedAt"]:
        for utterance in item.get("utterances") or []:
            if not isinstance(utterance, dict):
                continue
            u = {k: utterance.get(k) for k in UTTERANCE_KEYS}
            text = " ".join(str(u["text"] or "").split())
            if text:
                turns.append(Turn(text, speaker_marker(u["speaker"], speaker_map, owner_names), _turn_ts(u["timestamp"])))
    if not turns:
        return None, []
    created = _ts(row["createdAt"])
    return EpisodeDraft(
        title=" ".join(str(row["title"] or "").split()) or "Meeting",
        source_id=f"wispr:meeting:{meeting_id}",
        source_updated_at=_ts(row["modifiedAt"]) or created, timestamp=created,
        original_date=created[:10] if created else None, source=ORIGIN, origin=ORIGIN, turns=turns,
        extra={"wispr_kind": "meeting",
               "participants": _names(row["participantNames"]) or sorted(set(speaker_map.values())),
               "consent": "unknown", "meeting_ended_at": _ts(row["endedAt"])},
        writer="wispr-flow",
    ), open_todos


def note_draft(raw: dict) -> EpisodeDraft | None:
    row = {k: raw.get(k) for k in NOTE_COLUMNS}
    note_id = str(row["id"] or "").strip()
    body = _plain(row["content"])
    if not note_id or _truthy(row["isDeleted"]) or not body:
        return None
    created = _ts(row["createdAt"])
    return EpisodeDraft(
        title=" ".join(str(row["title"] or "").split()) or "Wispr Flow note",
        source_id=f"wispr:note:{note_id}", source_updated_at=_ts(row["modifiedAt"]) or created,
        timestamp=created, original_date=created[:10] if created else None, source=ORIGIN, origin=ORIGIN,
        body=body, extra={"wispr_kind": "note"}, writer="wispr-flow",
    )


def _stored_dictation(entry) -> list[tuple[str, str]]:
    """``(ts, text)`` rows of a stored dictation day, rebuilt from its own
    marker lines and ``turns`` sidecar (R-LS23, R-PB4) — the app posts only what
    is new, so a day is merged here rather than replaced. The turns come from
    ``evidence.turns`` (the one marker parser) and each time from the sidecar
    entry at exactly that turn's start, so a turn is never dropped for a
    missing entry; one past ``MAX_TURN_STAMPS`` comes back without a time."""
    if entry is None:
        return []
    body = markdown_parser.parse(entry.path).body
    stamps = evidence.turn_stamps(entry.fm)
    return [(str(t.ts or ""), body[t.content_start:t.end])
            for t in evidence.turns(body, stamps=stamps) if t.marker is not None]


def dictation_drafts(rows: list[dict], index: dict) -> list[EpisodeDraft]:
    by_day: dict[str, dict] = {}
    for raw in rows:
        r = {k: (raw or {}).get(k) for k in HISTORY_COLUMNS}
        app = str(r["app"] or "").strip()
        if app in DICTATION_APP_DENYLIST:
            continue
        text = " ".join(str(r["editedText"] or r["formattedText"] or "").split())
        ts = _ts(r["timestamp"])
        if not text or not ts:
            continue
        day = by_day.setdefault(ts[:10], {"rows": {}, "apps": set()})
        day["rows"][(ts, episode_scrub.scrub(text)[0])] = True
        if app:
            day["apps"].add(app)
    drafts: list[EpisodeDraft] = []
    for day, data in sorted(by_day.items()):
        sid = f"wispr:dictation:{day}"
        entry = index.get(sid)
        merged = dict.fromkeys(_stored_dictation(entry))
        merged.update(data["rows"])
        ordered = sorted(merged)
        apps = sorted(set((entry.fm.get("dictation_apps") or []) if entry else []) | data["apps"])
        drafts.append(EpisodeDraft(
            title=f"Dictation · {day}", source_id=sid, source_updated_at=ordered[-1][0],
            timestamp=ordered[0][0], original_date=day, source=ORIGIN, origin=ORIGIN,
            turns=[Turn(text, "user", ts) for ts, text in ordered],
            extra={"wispr_kind": "dictation", "dictation_apps": apps}, writer="wispr-flow",
        ))
    return drafts


# --- To-dos (R-LS24) --------------------------------------------------------


def write_todo_claims(memory_path: Path, staged, meeting_todos: dict[str, list[str]]) -> dict:
    """Each open to-do of a new or changed meeting as a ``committed-to`` claim on
    the owner's page: ``observer: agent`` at 0.5 (Wispr Flow's model extracted
    it, and a to-do may be someone else's), with a span on the to-do line. No
    owner page, no claims — never a guessed subject."""
    from api.config import get_settings
    from api.services import agentic_write, git_service, owner_identity

    out = {"written": 0, "skipped_no_owner": 0, "paths": []}
    touched = {sid: ep for sid, ep in staged.touched.items() if sid in meeting_todos}
    if not touched:
        return out
    owner = owner_identity.resolve_observer(memory_path, get_settings())
    if not (Path(memory_path) / "entities" / f"{owner}.md").exists():
        out["skipped_no_owner"] = sum(len(meeting_todos[s]) for s in touched)
        return out
    for sid, ep_id in touched.items():
        for title in meeting_todos[sid]:
            result = agentic_write.write_claim(
                memory_path, owner, "committed-to", title, observer="agent", object_kind="literal",
                confidence=0.5, source_episode=ep_id, origin=ORIGIN,
                # F2-back R-B11: Wispr Flow's model wrote the list (its spans are `assistant`).
                authored_by=git_service.AGENT_AUTHOR,
                evidence=[{"episode": ep_id, "quote": f"- {title}"}])
            if result.get("action") not in {"error", "ambiguous_subject", "corrupt_claims_block"}:
                out["written"] += 1
    if out["written"]:
        out["paths"].append(f"entities/{owner}.md")
    return out


# --- Ingest -----------------------------------------------------------------


def ingest(memory_path: Path, payload: dict, settings: dict, *, defer_todos: bool = False) -> dict:
    """Stage one posted batch. ``defer_todos`` (a Sleep cycle is running): the
    episodes land now, the to-do claims wait in ``todos_pending`` (finding 5)."""
    memory_path = Path(memory_path)
    episodes_dir = memory_path / "episodes"
    owner_names = {n.casefold() for n in settings.get("owner_speaker_names") or []}
    todos: dict[str, list[dict]] = {}
    for todo in payload.get("todos") or []:
        if isinstance(todo, dict):
            todos.setdefault(str(todo.get("meetingId") or ""), []).append(todo)
    counts = {"meetings_seen": 0, "notes_seen": 0, "dictation_days": 0, "dictation_refused": 0}
    drafts: list[EpisodeDraft] = []
    meeting_todos: dict[str, list[str]] = {}
    for item in (payload.get("meetings") or [])[:MAX_MEETINGS]:
        if not isinstance(item, dict):
            continue
        meeting_id = str((item.get("row") or {}).get("id") or "")
        draft, open_todos = meeting_draft(item, todos.get(meeting_id, []), owner_names)
        if draft is None:
            continue
        drafts.append(draft)
        counts["meetings_seen"] += 1
        if open_todos:
            meeting_todos[draft.source_id] = open_todos
    for raw in payload.get("notes") or []:
        draft = note_draft(raw) if isinstance(raw, dict) else None
        if draft is not None:
            drafts.append(draft)
            counts["notes_seen"] += 1
    history = payload.get("history") or []
    if history:
        if settings.get("include_dictation"):
            index, _ = episode_staging.scan(episodes_dir)
            days = dictation_drafts(history[:MAX_HISTORY], index)
            drafts += days
            counts["dictation_days"] = len(days)
        else:
            counts["dictation_refused"] = len(history)  # R-LS23: opted out, never stored
    deleted = ([f"wispr:meeting:{i}" for i in payload.get("deleted_meeting_ids") or [] if str(i).strip()]
               + [f"wispr:note:{i}" for i in payload.get("deleted_note_ids") or [] if str(i).strip()])
    staged = episode_staging.stage(drafts, episodes_dir, deleted_source_ids=deleted, bank=memory_path.name)
    todo_sids = {sid for sid in staged.touched if sid in meeting_todos}
    pending_paths: list[str] = []
    if defer_todos:
        claims = {"written": 0, "skipped_no_owner": 0, "paths": []}
        with _LOCK:
            before = load_todos_pending(memory_path)
            if todo_sids - set(before):
                _save_todos_pending(memory_path, before + sorted(todo_sids))
                pending_paths.append(f"sources/{SETTINGS_FILENAME}")
        todos_pending = len(set(before) | todo_sids)
    else:
        claims = write_todo_claims(memory_path, staged, meeting_todos)
        # Anything an earlier batch deferred, now that no cycle runs. The
        # meetings just written are skipped — their claims are already down.
        replay = replay_pending_todos(memory_path, skip=todo_sids)
        claims["written"] += replay["written"]
        pending_paths = replay["paths"]
        todos_pending = 0
    index, _ = episode_staging.scan(episodes_dir)
    live = sum(1 for sid, e in index.items()
               if sid.startswith(("wispr:meeting:", "wispr:note:")) and not e.fm.get("source_deleted_at"))
    return {**counts, "created": staged.created, "updated": staged.updated, "skipped": staged.skipped,
            "tombstoned": staged.tombstoned, "todo_claims": claims["written"],
            "todos_skipped_no_owner": claims["skipped_no_owner"], "todos_pending": todos_pending,
            "live": live, "paths": staged.paths + claims["paths"] + pending_paths}
