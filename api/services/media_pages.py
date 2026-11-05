"""A page for every recording, video, Voice Memo and photo the person adds (ROR-117 / G43, owner ruling 68, 2026-11-05).

The owner: "being able to play videos, audios, see photos, etc all possible in the app, which all as entities have a
markdown attached to it which can have the summary, why its relevant, if there is a transcription available anywhere
(which we have to put the model that transcribed it as the contributor)."

**This module is the one writer of these pages** (the way ``github_repos`` is the one writer of a repository's): an
added file is a ``media`` page (``media.kind: file``), born here by file and git work alone — no model, nothing at
capture time. It never blocks ``POST /files/media``: the post records the item and asks :func:`start_sync`, which makes
the page moments later, and a bank Sleep is holding is tried again when Sleep ends. Stage 1 never produces ``media``;
these pages are never projects (ruling 56).

**What is in the bank, and why.** The page holds what belongs in git: the title, the kind, the item's own date
(``media.recorded_at``, ruling 39; a file the person picked has no other date than the day it was added), the file id,
the length, the language and, when a transcript exists, the model that made it (``media.transcribed_by``). Then two
empty sections a later change fills (``## Summary``, ``## Why it matters``); the app hides an empty one. **The
transcript is not in the bank, in git or in the page's text**: an hour of speech committed could never be forgotten,
and deleting a file promises its words go. The page draws them at view time from the store outside every bank
(``GET /files/{id}/transcript``, ``media_files.transcript``). The words stay the recording's, never the person's own.

**One page per file.** The store's ``meta.json`` remembers its page (``page``); a bank whose store lost that is read
back by ``media.file_id`` on the pages. The same bytes added again (the same sha256, so the same file id) reuse the
page; a store's own item (a Voice Memo) is keyed by the store's id. A page the person removed or merged away is never
made again by a sync. A page the person renamed keeps their name: a later sync updates only what the store knows.

**Quiet until mentioned.** ``media:`` with no episode is import evidence and no conversation evidence, so
``quiet_pages`` dims the page and no question is asked about it until a conversation mentions it. Decay is the one
resolver (``decay_policy``: a ``media`` page is evergreen — a recording does not become less true).

**Taking it out.** ``DELETE /files/{id}`` and ``retire_source`` queue the page's retirement in a journal beside the
store (ids only) before the words go; :func:`sync` removes the page in one commit, the person's own for a delete they
asked for and Cicada's for a store item that went away. A bank Sleep holds is tried again, never lost. What stays: the
page's earlier versions in git history (title, kind, date, file id, length, who transcribed it, and anything the person
or an agent wrote on it) — never the transcript, which was never committed.

**Cost.** ``sync`` lists the store once, indexes the bank's pages once (``bank_index``), writes one small file per item
and commits ``BATCH`` pages at a time, each batch inside its own admission so Sleep is never kept waiting for a whole
catch-up (measured at 1,000 items in the PR).
"""
from __future__ import annotations

import json
import threading
from datetime import date, datetime, timezone
from pathlib import Path

from loguru import logger

from api.services import bank_index, decay_policy, demo_guard, git_service, markdown_parser, media_files, page_lock
from api.services import write_admission
from api.services.id_utils import sanitize_id

KIND = "file"
PAGE_ORIGIN = "file"
#: What the page's tag and ``media_type`` say, for the store's ``audio | video | image``.
MEDIA_TYPES = {"audio": "recording", "video": "video", "image": "photo"}
#: Commit trigger: a store's catch-up is the sync door (``git_service.history_via``); a delete the person asked for is
#: theirs, in the app.
TRIGGER_SYNC = "sync/media_files"
TRIGGER_USER = "user/media_files"
#: Pages written under one admission and one commit.
BATCH = 250
SLUG_MAX = 60
SETTLE_S = 3.0          # a burst of added files folds into one run
RETRY_S = 60.0          # Sleep held the pages: try again
JOURNAL = "_retire.json"
SECTIONS = "## Summary\n\n## Why it matters\n"

_JOURNAL_LOCK = threading.Lock()


# --------------------------------------------------------------------------- reading a page


def is_file_page(fm: dict | None) -> bool:
    fm = fm or {}
    media = fm.get("media") if isinstance(fm.get("media"), dict) else {}
    return str(fm.get("type") or "") == "media" and media.get("kind") == KIND


def file_id_of(fm: dict | None) -> str | None:
    media = (fm or {}).get("media")
    fid = media.get("file_id") if isinstance(media, dict) else None
    return fid if isinstance(fid, str) and media_files.FILE_ID_RE.match(fid) else None


def transcriber(fm: dict | None) -> str | None:
    """The model that made this page's transcript, when the page says so (provenance's contributor, never a guess)."""
    media = (fm or {}).get("media")
    name = media.get("transcribed_by") if isinstance(media, dict) else None
    return " ".join(name.split()) if isinstance(name, str) and name.strip() else None


def transcript_line(memory_path: Path, entity_id: str) -> str | None:
    """How much transcript exists for a file page — a count and a length, never a word of it. ``None`` for any other
    page, a file with no words, or one the store no longer holds."""
    entry = bank_index.file(Path(memory_path), "entities", f"{entity_id}.md")
    fm = entry.frontmatter if entry is not None else None
    fid = file_id_of(fm) if is_file_page(fm) else None
    meta = media_files.get(memory_path, fid) if fid else None
    if not isinstance(meta, dict) or meta.get("deleted_at") or not meta.get("segments"):
        return None
    n = int(meta["segments"])
    length = meta.get("duration_s")
    span = f" of {media_files.clock(length)}" if isinstance(length, (int, float)) and length else ""
    return (f"The recording's words{span}: {n} segment{'' if n == 1 else 's'}, kept outside memory on this Mac. "
            "They are not returned here.")


# --------------------------------------------------------------------------- the page


def _title(meta: dict) -> str:
    name = str(meta.get("name") or "").strip()
    stem, dot, ext = name.rpartition(".")
    # "Standup 2026-10-03.m4a" is named "Standup 2026-10-03"; a name with no short extension is kept whole.
    if dot and stem and 1 <= len(ext) <= 5 and ext.isalnum():
        name = stem.strip()
    return name or f"A {MEDIA_TYPES.get(meta.get('kind'), 'file')}"


def _block(meta: dict, old: dict | None = None) -> dict:
    """The page's ``media:`` block from the store's description: stable facts only, so a re-post that changes nothing
    writes nothing. Keys the block already held that this does not own (a thumbnail, say) are kept."""
    block = dict(old or {})
    kind = str(meta.get("kind") or "")
    block.update({"kind": KIND, "media_type": MEDIA_TYPES.get(kind, "recording"), "file_id": meta["id"],
                  "recorded_at": meta.get("recorded_at") or meta.get("added_at")})
    if isinstance(meta.get("duration_s"), (int, float)) and meta["duration_s"] > 0:
        block["duration_s"] = int(round(meta["duration_s"]))
    else:
        block.pop("duration_s", None)
    for key, value in (("language", meta.get("language")),
                       ("transcribed_by", meta.get("transcribed_by") if meta.get("segments") else None)):
        if value:
            block[key] = value
        else:
            block.pop(key, None)
    return block


def _frontmatter(meta: dict, title: str, today: str) -> dict:
    kind = MEDIA_TYPES.get(str(meta.get("kind")), "recording")
    name = str(meta.get("name") or "").strip()
    return {
        "name": title, "type": "media", "status": "active", "confidence": 0.8,
        "created": today, "last_referenced": today,
        **decay_policy.frontmatter_fields(decay_policy.default_class_for("media", source="media")),
        "source_episodes": [],
        "aliases": [name] if name and name != title else [],
        "tags": [kind], "related": [], "version": 1, "origin": PAGE_ORIGIN,
        # Described by the store and the person's own file — never a fetched page.
        "enrichment_attempted": True,
        "media": _block(meta),
    }


def _page_id(entities: Path, title: str, file_id: str, taken: set[str], former: set[str]) -> str:
    slug = sanitize_id(title)[:SLUG_MAX].strip("-") or "file"
    plain = f"file-{slug}"
    if plain not in taken and plain not in former and not (entities / f"{plain}.md").exists():
        return plain
    return f"{plain}-{file_id[:8]}"


def _pages_by_file(memory_path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for entry in bank_index.files(memory_path, "entities"):
        fid = file_id_of(entry.frontmatter) if is_file_page(entry.frontmatter) else None
        if fid:
            out.setdefault(fid, entry.stem)
    return out


def page_for(memory_path: Path, file_id: str) -> str | None:
    """The page a stored file has: its store's record first, else the pages themselves."""
    meta = media_files.get(memory_path, file_id)
    page = meta.get("page") if isinstance(meta, dict) else None
    if isinstance(page, str) and page:
        return page
    return _pages_by_file(Path(memory_path)).get(file_id)


# --------------------------------------------------------------------------- the journal of retirements


def _journal_path(memory_path: Path) -> Path:
    return media_files.root(memory_path) / JOURNAL


def _journal(memory_path: Path) -> list[dict]:
    try:
        rows = json.loads(_journal_path(memory_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [r for r in rows if isinstance(r, dict) and isinstance(r.get("page"), str)] if isinstance(rows, list) else []


def _save_journal(memory_path: Path, rows: list[dict]) -> None:
    path = _journal_path(memory_path)
    if not rows:
        path.unlink(missing_ok=True)
        return
    media_files._write_atomic(path, json.dumps(rows).encode())


def queue_retirement(memory_path: Path, file_ids: list[str], *, by: str = git_service.CICADA_AUTHOR) -> int:
    """Note, before a file's words go, that its page is to be retired: page ids and who asked, nothing else. Called by
    ``media_files.delete`` and ``retire_source``; :func:`sync` does the removal. Returns how many pages were queued."""
    memory_path = Path(memory_path)
    pages = _pages_by_file(memory_path) if file_ids else {}
    rows_new = []
    for fid in file_ids:
        meta = media_files.get(memory_path, fid)
        page = (meta.get("page") if isinstance(meta, dict) else None) or pages.get(fid)
        if page:
            rows_new.append({"page": page, "file": fid, "by": by})
    if not rows_new:
        return 0
    with _JOURNAL_LOCK:
        rows = [r for r in _journal(memory_path) if r["page"] not in {n["page"] for n in rows_new}]
        _save_journal(memory_path, rows + rows_new)
    return len(rows_new)


# --------------------------------------------------------------------------- committing


def _commit(memory_path: Path, rows: list[tuple[str, str]], *, trigger: str, author: str) -> None:
    """One commit for ``rows`` (``(path, action)``), alone, under its true author."""
    paths = [p for p, _ in rows]
    message = git_service.build_commit_message(
        f"Recordings, videos and photos {datetime.now(timezone.utc).date().isoformat()}",
        [f"{p}: {action} (source: n/a, trigger: {trigger})" for p, action in rows], authors=[author])
    git_service.commit_paths_sync(memory_path, message, paths)


def _tracked(memory_path: Path, rels: list[str]) -> list[str]:
    """The removed paths git knows (``git add`` refuses a pathspec that matches nothing) plus every file still there."""
    known = set(git_service._git_sync(memory_path, "ls-files", "--", *rels).split("\n")) if rels else set()
    return [r for r in rels if (memory_path / r).exists() or r in known]


# --------------------------------------------------------------------------- the sync


def _store(memory_path: Path) -> list[dict]:
    """Every live item's description, oldest first, so a catch-up commits in the order things were added."""
    return sorted(media_files.list_files(memory_path), key=lambda m: str(m.get("added_at") or ""))


def _retire_queued(memory_path: Path) -> dict:
    with _JOURNAL_LOCK:
        rows = _journal(memory_path)
    if not rows:
        return {"retired": 0, "pending": 0}
    by_author: dict[str, list[dict]] = {}
    for r in rows:
        by_author.setdefault(str(r.get("by") or git_service.CICADA_AUTHOR), []).append(r)
    done: set[str] = set()
    for author, group in by_author.items():
        with write_admission.admitted(memory_path), page_lock.page_lock(memory_path):
            rels = []
            for r in group:
                for suffix in (".md", ".claims.jsonl"):
                    rel = f"entities/{r['page']}{suffix}"
                    (memory_path / rel).unlink(missing_ok=True)
                    rels.append(rel)
            tracked = _tracked(memory_path, rels)
            if tracked:
                _commit(memory_path, [(p, "deleted") for p in tracked],
                        trigger=TRIGGER_USER if author == git_service.USER_AUTHOR else TRIGGER_SYNC, author=author)
            bank_index.invalidate(memory_path)
            done |= {r["page"] for r in group}
    with _JOURNAL_LOCK:
        _save_journal(memory_path, [r for r in _journal(memory_path) if r["page"] not in done])
    return {"retired": len(done), "pending": len(rows) - len(done)}


def _remember(memory_path: Path, file_id: str, page: str) -> None:
    folder = media_files.root(memory_path) / file_id
    meta = media_files._json(folder / "meta.json")
    if isinstance(meta, dict) and meta.get("page") != page and not meta.get("deleted_at"):
        meta["page"] = page
        media_files._write_atomic(folder / "meta.json", (json.dumps(meta, indent=2, ensure_ascii=False) + "\n").encode())


def sync(memory_path: Path) -> dict:
    """Retire the pages queued for removal, then make the page of every stored item that has none and bring a page's
    facts up to the store's. Idempotent: a second run over the same store writes and commits nothing. Raises
    :class:`write_admission.SleepHolding` when Sleep holds the pages — the caller tries again, nothing is lost.
    ``{"created", "updated", "retired", "pending"}``."""
    memory_path = Path(memory_path)
    out = {"created": 0, "updated": 0, "retired": 0, "pending": 0}
    if demo_guard.is_demo(memory_path) or not media_files.root(memory_path).is_dir():
        return out
    out["retired"] = _retire_queued(memory_path)["retired"]
    items = _store(memory_path)
    if not items:
        return out
    entities = memory_path / "entities"
    entities.mkdir(parents=True, exist_ok=True)
    by_file = _pages_by_file(memory_path)
    todo: list[dict] = []
    for meta in items:
        page = meta.get("page") or by_file.get(meta["id"])
        if page and not (entities / f"{page}.md").is_file():
            continue                        # removed or merged away by the person: never made again
        if page and page != meta.get("page"):
            _remember(memory_path, meta["id"], page)
        todo.append(meta)                   # a new page, or an existing one checked for changed facts under the lock
    today = date.today().isoformat()
    for start in range(0, len(todo), BATCH):
        chunk = todo[start:start + BATCH]
        try:
            with write_admission.admitted(memory_path), page_lock.page_lock(memory_path):
                rows, remembered = _write_chunk(memory_path, chunk, by_file, today, out)
                if rows:
                    _commit(memory_path, rows, trigger=TRIGGER_SYNC, author=git_service.CICADA_AUTHOR)
                bank_index.invalidate(memory_path)
        except write_admission.SleepHolding:
            out["pending"] = len(todo) - start
            raise
        for fid, page in remembered:
            _remember(memory_path, fid, page)
    return out


def _write_chunk(memory_path: Path, chunk: list[dict], by_file: dict[str, str], today: str,
                 out: dict) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    from api.services import page_redirects

    entities = memory_path / "entities"
    former = set(page_redirects.load(memory_path))
    taken = set(by_file.values())
    rows: list[tuple[str, str]] = []
    remembered: list[tuple[str, str]] = []
    for meta in chunk:
        fid = meta["id"]
        page = meta.get("page") or by_file.get(fid)
        path = entities / f"{page}.md" if page else None
        if path is not None and path.is_file():
            parsed = markdown_parser.parse(path)
            fm = parsed.frontmatter
            if not is_file_page(fm):
                continue                    # the id now names another kind of page: left as it is
            block = _block(meta, fm.get("media") if isinstance(fm.get("media"), dict) else None)
            if block != fm.get("media"):
                fm["media"] = block
                markdown_parser.write(path, fm, parsed.body)
                rows.append((f"entities/{page}.md", "updated"))
                out["updated"] += 1
            if page != meta.get("page"):
                remembered.append((fid, page))
            continue
        if page:
            continue                        # gone (removed, or merged): never made again
        page = _page_id(entities, _title(meta), fid, taken, former)
        try:
            markdown_parser.write_new(entities / f"{page}.md", _frontmatter(meta, _title(meta), today), SECTIONS)
        except FileExistsError:
            page = f"{page}-{fid[:8]}"
            markdown_parser.write_new(entities / f"{page}.md", _frontmatter(meta, _title(meta), today), SECTIONS)
        taken.add(page)
        by_file[fid] = page
        remembered.append((fid, page))
        rows.append((f"entities/{page}.md", "created"))
        out["created"] += 1
    return rows, remembered


# --------------------------------------------------------------------------- the background run


class _Runner:
    def __init__(self) -> None:
        self.thread: threading.Thread | None = None
        self.timer: threading.Timer | None = None
        self.again = False


_RUNNERS: dict[str, _Runner] = {}
_GUARD = threading.Lock()


def start_sync(memory_path, *, delay_s: float = 0.0) -> bool:
    """Make the pages in the background: one run per bank at a time (a trigger during a run runs once more after it),
    a short ``delay_s`` folding a burst of added files into one run, and a bank Sleep holds tried again later. Never
    raises. A demo bank, or a bank with nothing stored, does nothing."""
    try:
        memory_path = Path(memory_path)
        if demo_guard.is_demo(memory_path):
            return False
        # A queued retirement outlives an empty store (the last file deleted, or a crash after the store's delete).
        if not media_files.any_files(memory_path) and not _journal(memory_path):
            return False
        key = str(memory_path.resolve())
        with _GUARD:
            runner = _RUNNERS.setdefault(key, _Runner())
            if runner.thread is not None and runner.thread.is_alive():
                runner.again = True
                return False
            if delay_s > 0:
                if runner.timer is not None and runner.timer.is_alive():
                    return False
                runner.timer = threading.Timer(delay_s, start_sync, args=(memory_path,))
                runner.timer.daemon = True
                runner.timer.start()
                return True
            runner.thread = threading.Thread(target=_run, args=(memory_path, runner), name="cicada-media-pages",
                                             daemon=True)
            runner.thread.start()
        return True
    except Exception as exc:  # noqa: BLE001 — a page is never a reason for a request to fail
        logger.debug(f"media pages: not started ({type(exc).__name__})")
        return False


def _run(memory_path: Path, runner: _Runner) -> None:
    while True:
        runner.again = False
        try:
            out = sync(memory_path)
            if out["created"] or out["updated"] or out["retired"]:
                logger.info(f"media pages: {out['created']} made, {out['updated']} updated, {out['retired']} retired")
        except write_admission.SleepHolding:
            _retry(memory_path)
            return
        except Exception as exc:  # noqa: BLE001 — the next trigger tries again
            logger.debug(f"media pages: skipped ({type(exc).__name__})")
            return
        if not runner.again:
            return


def _retry(memory_path: Path) -> None:
    with _GUARD:
        runner = _RUNNERS.setdefault(str(memory_path.resolve()), _Runner())
        if runner.timer is not None and runner.timer.is_alive():
            return
        runner.timer = threading.Timer(RETRY_S, start_sync, args=(memory_path,))
        runner.timer.daemon = True
        runner.timer.start()


def sync_or_later(memory_path: Path) -> dict | None:
    """The route's own attempt (a delete the person asked for): now when the pages are free, else in the background."""
    try:
        return sync(memory_path)
    except write_admission.SleepHolding:
        _retry(Path(memory_path))
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"media pages: skipped ({type(exc).__name__})")
    return None


__all__ = ["KIND", "is_file_page", "file_id_of", "transcriber", "transcript_line", "page_for", "queue_retirement",
           "sync", "start_sync", "sync_or_later"]
