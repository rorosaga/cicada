"""A watched folder of notes as a memory source (G133 · R-F1 · R-F2).

The APP owns the folder: it holds a bookmark to it, runs a recursive FSEvents
watch, and posts the bytes of changed files with their relative paths. The
backend never opens the folder path — the rail CLAUDE.md states for
``~/Library`` applies to ``~/Documents``, ``~/Desktop`` and ``~/Downloads`` too
(TCC-gated; the launchd backend has no grant). The absolute path is stored per
device only to display it and to relink a moved folder (the G27 shape).

One episode per file through the G20 stager (``episode_staging``): the same
bytes skip, an edit rewrites the file's episode in place and re-queues it, a
rename keeps identity by content hash, a deletion stamps ``source_deleted_at``
and keeps the episode. A file past ``SPLIT_CHARS`` (4 × Stage 1's chunk) is one
episode per H2 section, so an edit re-reads one section (R-LS12).

Authorship (R-F2): a per-folder glob list decides whose words a file holds.
``archive/**`` defaults to ``agent`` — dated research sweeps an agent wrote. An
agent-written file is stored and searchable but never credited to the person
(``evidence_kind: assistant``) and never queued for Sleep (R-LS10).

Concurrency (Task 2 review, round 1): ``sync`` runs in the threadpool, and the
watcher's batch can overlap a manual Sync. ``_LOCK`` is held across the whole
of ``sync`` (scan → decide → stage → registry stamp) and around every registry
read-modify-write, so two batches never decide against the same stale scan and
two saves never lose each other's edit. ``episode_staging.STAGE_LOCK`` still
guards the id mint for every other writer; the order is always ``_LOCK`` then
``STAGE_LOCK``, never the reverse.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import os
import re
import threading
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

from loguru import logger

from api.services import bank_index, decay_policy, episode_ids, episode_staging, markdown_parser
from api.services.id_utils import sanitize_id

FOLDERS_FILENAME = "folders.json"
ORIGIN = "folder"
CHANNEL_PREFIX = "folder:"
DEFAULT_INCLUDE = ("**/*.md", "**/*.markdown", "**/*.txt")
DEFAULT_EXCLUDE = ("**/.git/**", "**/node_modules/**", "**/.obsidian/**", "**/.trash/**")
DEFAULT_AUTHORSHIP = ({"glob": "archive/**", "authorship": "agent"},)
AUTHORSHIPS = ("user", "agent")
# Stage 1's chunking, mirrored rather than imported: `entity_extractor` pulls the
# LLM stack, and this module is a capture path (no LLM at capture time). The
# test suite pins both numbers to `entity_extractor.CHUNK_SIZE`/`CHUNK_OVERLAP`.
STAGE1_CHUNK = 12_000
STAGE1_OVERLAP = 500
SPLIT_CHARS = STAGE1_CHUNK * 4
MAX_FILE_BYTES = 2_000_000
MAX_BATCH_FILES = 200
MAX_BATCH_BYTES = 8_000_000
_MAX_RELPATH = 512
_H2 = re.compile(r"^##[ \t]+(.+?)[ \t]*#*[ \t]*$")
_FENCE = re.compile(r"^[ \t]*(`{3}|~{3})")
#: Re-entrant: ``sync`` holds it and then calls ``set_flags``, which takes it too.
_LOCK = threading.RLock()


@dataclass
class IncomingFile:
    relpath: str
    mtime: float
    sha256: str
    content_b64: str


# --- Registry ---------------------------------------------------------------


def registry_path(memory_path: Path) -> Path:
    return Path(memory_path) / "sources" / FOLDERS_FILENAME


def list_folders(memory_path: Path) -> list[dict]:
    """Every registered folder; a missing or corrupt registry is an empty list,
    never an error (the `feed_registry` convention)."""
    try:
        data = json.loads(registry_path(memory_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    folders = data.get("folders") if isinstance(data, dict) else None
    return [f for f in (folders or []) if isinstance(f, dict) and f.get("id")]


def _save(memory_path: Path, folders: list[dict]) -> None:
    path = registry_path(memory_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # A per-writer temp name: a shared ``folders.json.tmp`` let one writer's
    # ``replace`` move the other's file away mid-save (FileNotFoundError → 500).
    tmp = path.with_suffix(f".json.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps({"folders": folders}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def get_folder(memory_path: Path, folder_id: str) -> dict | None:
    return next((f for f in list_folders(memory_path) if f.get("id") == folder_id), None)


def channel_id(folder_id: str) -> str:
    return f"{CHANNEL_PREFIX}{folder_id}"


def _clean_rules(rules) -> list[dict]:
    out: list[dict] = []
    for rule in rules or []:
        rule = rule if isinstance(rule, dict) else {}
        glob = str(rule.get("glob") or "").strip()
        who = str(rule.get("authorship") or "").strip()
        if glob and who in AUTHORSHIPS and len(glob) <= 200:
            out.append({"glob": glob, "authorship": who})
    return out


def register(memory_path: Path, *, label: str, path: str, include=None, exclude=None,
             authorship=None, project_id: str | None = None, device: str | None = None) -> dict:
    """Create or update the folder at ``(device, path)`` (R-LS9: an upsert, so a
    re-pick of the same folder keeps its id, its episodes and its history).

    On an existing record a rule list left as ``None`` keeps what is stored — a
    re-pick, or the add sheet's second POST without rules, must not wipe what
    the person set in Manage (``authorship: []`` coming back as ``archive/** =
    agent`` would park those files again; Task 2 review, round 1). Only a new
    record gets the defaults."""
    from api.services import local_refs

    device = device or local_refs.current_device_id()
    with _LOCK:
        return _register_locked(memory_path, label=label, path=path, include=include, exclude=exclude,
                                authorship=authorship, project_id=project_id, device=device)


def _register_locked(memory_path: Path, *, label: str, path: str, include, exclude, authorship,
                     project_id: str | None, device: str) -> dict:
    folders = list_folders(memory_path)
    existing = next((f for f in folders if f.get("device") == device and f.get("path") == path), None)
    key = hashlib.sha1(f"{device}\x00{path}".encode()).hexdigest()[:6]
    slug = (sanitize_id(label) or "folder")[:40].strip("-") or "folder"
    record = existing if existing is not None else {"id": f"{slug}-{key}", "created_at": episode_ids.utc_now_iso()}
    record.update({
        "label": (label or "").strip() or Path(path).name or "Folder",
        "path": path,
        "device": device,
        "include": list(include) if include else list(record.get("include") or DEFAULT_INCLUDE),
        "exclude": list(exclude) if exclude else list(record.get("exclude") or DEFAULT_EXCLUDE),
        "authorship": _clean_rules(authorship) if authorship is not None
        else _clean_rules(record["authorship"]) if "authorship" in record
        else [dict(r) for r in DEFAULT_AUTHORSHIP],
        "project_id": project_id or record.get("project_id"),
    })
    if existing is None:
        folders.append(record)
    _save(memory_path, folders)
    return record


def update(memory_path: Path, folder_id: str, *, label: str | None = None, authorship=None) -> dict | None:
    with _LOCK:
        folders = list_folders(memory_path)
        record = next((f for f in folders if f.get("id") == folder_id), None)
        if record is None:
            return None
        if label is not None and label.strip():
            record["label"] = label.strip()
        if authorship is not None:
            record["authorship"] = _clean_rules(authorship)
        _save(memory_path, folders)
        return record


def remove(memory_path: Path, folder_id: str) -> bool:
    """Forget the registration. Episodes stay — the history is the history (R-F1)."""
    with _LOCK:
        folders = list_folders(memory_path)
        kept = [f for f in folders if f.get("id") != folder_id]
        if len(kept) == len(folders):
            return False
        _save(memory_path, kept)
        return True


def set_flags(memory_path: Path, folder_id: str, **fields) -> None:
    with _LOCK:
        folders = list_folders(memory_path)
        for f in folders:
            if f.get("id") == folder_id:
                f.update(fields)
                _save(memory_path, folders)
                return


# --- Paths and globs --------------------------------------------------------


@lru_cache(maxsize=512)
def _glob_re(pattern: str) -> re.Pattern[str]:
    """``**/`` = any number of directories (zero included), ``**`` = anything,
    ``*`` = anything but ``/``, ``?`` = one character but ``/``. Python's
    ``fnmatch`` lets ``*`` cross ``/`` and gives ``**`` no meaning, which would
    make ``*.md`` match a nested file and ``**/*.md`` miss a root one."""
    i, out = 0, []
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out))


def glob_match(pattern: str, relpath: str) -> bool:
    return _glob_re(pattern).fullmatch(relpath) is not None


def is_included(relpath: str, include, exclude) -> bool:
    return (any(glob_match(p, relpath) for p in include)
            and not any(glob_match(p, relpath) for p in exclude))


def authorship_for(relpath: str, rules) -> str:
    """First matching rule wins; no match is the person's own words."""
    for rule in rules or []:
        if glob_match(str(rule.get("glob") or ""), relpath):
            return str(rule.get("authorship") or "user")
    return "user"


def clean_relpath(raw) -> str | None:
    """A relative path inside the folder, or ``None``: no absolute paths, no
    ``..``, no empty segments, no NUL — the app sends paths it computed, but the
    backend never trusts a path it is about to key an episode on."""
    rel = str(raw or "").replace("\\", "/").strip()
    if not rel or rel.startswith("/") or "\x00" in rel or len(rel) > _MAX_RELPATH:
        return None
    if any(part in ("", ".", "..") for part in rel.split("/")):
        return None
    return rel


# --- Drafts -----------------------------------------------------------------


def split_sections(text: str) -> list[tuple[str, str, str]]:
    """``[(slug, heading, section_text)]`` split on H2 lines outside code fences
    (R-LS12). Text before the first H2 is the ``intro`` section when not blank;
    repeated headings get ``-2``, ``-3``."""
    sections: list[tuple[str | None, str]] = []
    heading: str | None = None
    buf: list[str] = []
    in_fence = False
    for line in text.splitlines(keepends=True):
        if _FENCE.match(line):
            in_fence = not in_fence
        m = None if in_fence else _H2.match(line.rstrip("\r\n"))
        if m:
            sections.append((heading, "".join(buf)))
            heading, buf = m.group(1).strip(), [line]
        else:
            buf.append(line)
    sections.append((heading, "".join(buf)))
    out: list[tuple[str, str, str]] = []
    seen: dict[str, int] = {}
    for head, body in sections:
        if head is None:
            if not body.strip():
                continue
            slug, title = "intro", ""
        else:
            slug = (sanitize_id(head) or "section")[:60].strip("-") or "section"
            title = head
        seen[slug] = seen.get(slug, 0) + 1
        if seen[slug] > 1:
            slug = f"{slug}-{seen[slug]}"
        out.append((slug, title, body))
    return out


def drafts_for_file(folder: dict, relpath: str, text: str, *, mtime_iso: str, sha: str) -> list[episode_staging.EpisodeDraft]:
    authorship = authorship_for(relpath, folder.get("authorship") or [])
    base = f"{channel_id(folder['id'])}:{relpath}"
    extra = {"folder_id": folder["id"], "relpath": relpath, "authorship": authorship,
             "evidence_kind": "user" if authorship == "user" else "assistant"}
    label = folder.get("label") or "Folder"
    parts = split_sections(text) if len(text) > SPLIT_CHARS else [("", "", text)]
    return [
        episode_staging.EpisodeDraft(
            title=f"{label} › {relpath}" + (f" › {heading}" if heading else ""),
            source_id=base if not slug else f"{base}#{slug}",
            source_updated_at=mtime_iso, timestamp=mtime_iso, original_date=mtime_iso[:10],
            source=ORIGIN, origin=ORIGIN, body=section, extra=dict(extra),
            queue_for_sleep=authorship == "user", content_sha=sha, writer="folder",
        )
        for slug, heading, section in parts
    ]


def stage1_passes(text: str) -> int:
    """How many Stage-1 calls Sleep will spend on ``text`` — shown as a count,
    never a price (the 2026-09-03 ruling)."""
    return math.ceil(len(text) / (STAGE1_CHUNK - STAGE1_OVERLAP)) if text.strip() else 0


def _by_relpath(index: dict, folder_id: str) -> dict[str, list[tuple[str, episode_staging.IndexEntry]]]:
    out: dict[str, list[tuple[str, episode_staging.IndexEntry]]] = {}
    for sid, entry in index.items():
        if entry.fm.get("folder_id") == folder_id and entry.fm.get("relpath"):
            out.setdefault(str(entry.fm["relpath"]), []).append((sid, entry))
    return out


def live_file_count(memory_path: Path, folder_id: str) -> int:
    index, _ = episode_staging.scan(Path(memory_path) / "episodes")
    return sum(1 for entries in _by_relpath(index, folder_id).values()
               if any(not e.fm.get("source_deleted_at") for _, e in entries))


# --- Sync -------------------------------------------------------------------


def sync(memory_path: Path, folder: dict, files: list[IncomingFile], deleted: list[str], *,
         preview: bool = False) -> dict:
    """Stage (or, with ``preview``, only count) one posted batch. Never opens
    the folder; decodes and re-hashes what the app sent. Returns the counts the
    route serialises, plus ``_staged`` (the ``StageResult``) and ``_texts``
    (relpath -> decoded text) for the paper step (Task 3).

    Held under ``_LOCK`` end to end (see the module docstring). ``last_sync`` is
    stamped only when something landed: ``folders.json`` is versioned, and a
    no-change rescan (the app's full pass on launch) stamping it made a
    ``Folder sync`` commit and moved the ``sources`` ETag every time — the
    projection churn ``sleep.next_at`` was taken out of ``_state.md`` for.
    ``sync_state.json`` still records that the sync ran."""
    with _LOCK:
        return _sync_locked(Path(memory_path), folder, files, deleted, preview=preview)


def _sync_locked(memory_path: Path, folder: dict, files: list[IncomingFile], deleted: list[str], *,
                 preview: bool) -> dict:
    # Re-read under the lock: the caller's copy may predate a Manage save that
    # landed while this batch waited, and the rules decide authorship.
    folder = get_folder(memory_path, folder["id"]) or folder
    episodes_dir = memory_path / "episodes"
    index, _ = episode_staging.scan(episodes_dir)
    mine = _by_relpath(index, folder["id"])
    include = folder.get("include") or DEFAULT_INCLUDE
    exclude = folder.get("exclude") or DEFAULT_EXCLUDE
    rules = folder.get("authorship") or []
    out = {"preview": preview, "files_new": 0, "files_changed": 0, "files_unchanged": 0,
           "files_deleted": 0, "agent_files": 0, "stage1_passes": 0, "errors": [],
           "created": 0, "updated": 0, "renamed": 0, "tombstoned": 0}
    drafts: list[episode_staging.EpisodeDraft] = []
    deleted_sids: list[str] = []
    texts: dict[str, str] = {}
    for f in files:
        rel = clean_relpath(f.relpath)
        if rel is None:
            out["errors"].append({"relpath": str(f.relpath)[:200], "reason": "unsafe path"})
            continue
        if not is_included(rel, include, exclude):
            out["errors"].append({"relpath": rel, "reason": "excluded"})
            continue
        try:
            raw = base64.b64decode(f.content_b64, validate=True)
        except (binascii.Error, ValueError):
            out["errors"].append({"relpath": rel, "reason": "bad encoding"})
            continue
        if len(raw) > MAX_FILE_BYTES:
            out["errors"].append({"relpath": rel, "reason": "too large"})
            continue
        sha = hashlib.sha256(raw).hexdigest()
        if sha != (f.sha256 or "").strip().lower():
            out["errors"].append({"relpath": rel, "reason": "checksum mismatch"})
            continue
        try:
            mtime_iso = episode_ids.to_utc_iso(float(f.mtime))
        except (OverflowError, ValueError, OSError, TypeError):
            # NaN, ±inf or a year past 9999: one bad file, not a 500 for the batch.
            out["errors"].append({"relpath": rel, "reason": "bad mtime"})
            continue
        who = authorship_for(rel, rules)
        kind = "user" if who == "user" else "assistant"
        existing = mine.get(rel, [])
        live = [e for _, e in existing if not e.fm.get("source_deleted_at")]
        # Idempotent on (relpath, sha256) AND the authorship the rules give it now
        # — a glob flip must re-stage the same bytes (R-LS10).
        if live and all(e.fm.get("content_sha") == sha and e.fm.get("evidence_kind") == kind for e in live):
            out["files_unchanged"] += 1
            continue
        text = raw.decode("utf-8", errors="replace").lstrip("﻿")
        texts[rel] = text
        out["files_changed" if existing else "files_new"] += 1
        if who == "agent":
            out["agent_files"] += 1
        else:
            out["stage1_passes"] += stage1_passes(text)
        new = drafts_for_file(folder, rel, text, mtime_iso=mtime_iso, sha=sha)
        drafts.extend(new)
        new_sids = {d.source_id for d in new}
        deleted_sids += [sid for sid, e in existing if sid not in new_sids and not e.fm.get("source_deleted_at")]
    for raw_rel in deleted:
        rel = clean_relpath(raw_rel)
        if rel is None:
            continue
        gone = [sid for sid, e in mine.get(rel, []) if not e.fm.get("source_deleted_at")]
        if gone:
            out["files_deleted"] += 1
            deleted_sids += gone
    out["_texts"] = texts
    if preview:
        out["_staged"] = None
        return out
    staged = episode_staging.stage(drafts, episodes_dir, deleted_source_ids=deleted_sids, bank=memory_path.name)
    out.update(created=staged.created, updated=staged.updated, renamed=staged.renamed,
               tombstoned=staged.tombstoned)
    out["_staged"] = staged
    if staged.paths:
        set_flags(memory_path, folder["id"], last_sync=episode_ids.utc_now_iso())
    return out


# --- The project anchor (R-LS13) --------------------------------------------


def ensure_project(memory_path: Path, name: str, *, path: str, device: str) -> tuple[str, bool]:
    """``(project entity id, created)`` for the name the person gave the folder.
    Zero-LLM match against ``project`` pages (Stage 2's direct matcher only);
    otherwise a new ``project`` page, because the person typed the name. Either
    way the page learns ``paths: [{path, device}]``."""
    from api.services import entity_resolver

    memory_path = Path(memory_path)
    name = " ".join((name or "").split())
    if not name:
        return "", False
    projects = [{"id": f.stem, "frontmatter": f.frontmatter} for f in bank_index.files(memory_path, "entities")
                if (f.frontmatter or {}).get("type") == "project"]
    match = entity_resolver._find_direct_candidate_match(
        {"name": name}, entity_resolver.existing_by_name(projects), {})
    entry = {"path": path, "device": device}
    if match is not None:
        eid = match["candidate"]["id"]
        page = memory_path / "entities" / f"{eid}.md"
        parsed = markdown_parser.parse(page)
        fm = dict(parsed.frontmatter)
        paths = [p for p in (fm.get("paths") or []) if isinstance(p, dict)]
        if entry not in paths:
            fm["paths"] = paths + [entry]
            markdown_parser.write(page, fm, parsed.body)
        return eid, False
    eid = sanitize_id(name)
    page = memory_path / "entities" / f"{eid}.md"
    if page.exists():
        eid = f"{eid}-{hashlib.sha1(name.encode()).hexdigest()[:4]}"
        page = memory_path / "entities" / f"{eid}.md"
    today = date.today().isoformat()
    fm = {
        "name": name, "type": "project", "status": "active", "confidence": 0.8,
        "created": today, "last_referenced": today,
        **decay_policy.frontmatter_fields(decay_policy.default_class_for("project")),
        "source_episodes": [], "tags": ["folder"], "related": [], "version": 1,
        "paths": [entry],
    }
    page.parent.mkdir(parents=True, exist_ok=True)
    markdown_parser.write(page, fm, f"## Summary\n{name} — a folder of notes Cicada keeps in memory.")
    return eid, True


# --- Commits (R-LS30) -------------------------------------------------------


async def commit_paths_for(memory_path: Path, paths: list[str], *, subject: str, trigger: str,
                           author: str = "user") -> None:
    """A commit scoped to exactly ``paths`` — never ``git add -A``. Best effort:
    a bank that is not a git repo (most unit tests) must not fail a sync."""
    from api.services import git_service

    rels = sorted({p for p in paths if p})
    if not rels:
        return
    lines = [f"{p}: updated (trigger: {trigger})" for p in rels[:200]]
    if len(rels) > 200:
        lines.append(f"… and {len(rels) - 200} more (trigger: {trigger})")
    message = git_service.build_commit_message(subject, lines, authors=[author])
    try:
        await git_service.commit_paths(Path(memory_path), message, rels)
    except Exception as e:  # pragma: no cover - non-git workspace
        logger.warning(f"folder commit failed: {type(e).__name__}: {e}")
