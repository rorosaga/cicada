"""The G20 stager, one seam for every source with a stable identity (R-F1 · G133 · G134).

Moved out of ``api/routers/conversations.py`` — where ``_stage_episodes`` /
``_write_new_episode`` / ``_update_episode_in_place`` lived beside the chat
parsers — because three new sources need exactly its contract (a watched
folder, one episode per file; Wispr Flow meetings and notes; every later
note-taker), and a service must not import from a router. The chat importers
still call it through the router's old names, so their behaviour is
byte-identical: the body is ``role: text`` lines and the hash
``sha256(body)[:12]``.

What the move adds — each additive, each inert to an episode that does not use it:

* ``EpisodeDraft`` — what a parser hands the stager. ``turns`` render to
  ``<marker>: text`` lines; ``body`` is a pre-rendered document (a folder file).
* ``turn_index`` — per-turn chronology as a frontmatter sidecar, rows of
  ``[offset, ts, speaker]`` into the stored body (R7 §5.1). OUTSIDE the content
  hash on purpose: timestamps in the body would change every export's hash and
  re-queue the whole corpus on the next import (💸). Not ``turns`` — that key is
  already an integer count on every hook-captured episode (R-LS1). Omitted, never
  truncated, above ``MAX_TURN_INDEX_ROWS`` (R-LS2).
* Rename by content — a tombstoned ``source_id`` and a brand-new one in the same
  batch with the same ``content_sha`` and ``#fragment`` repoint the existing
  episode instead of forking a copy (R-F1, R-LS12).
* Tombstones — ``deleted_source_ids`` stamp ``source_deleted_at`` and keep the
  file; a source that comes back clears the stamp (R-F1: the history is the history).
* Scrub — every turn and body goes through ``episode_scrub`` before it is hashed
  or written (R-N3). The hash describes the stored text; a match on the
  unscrubbed render counts as unchanged so a new scrub rule never re-queues or
  forks a legacy episode (R-LS4).
* ``queue_for_sleep=False`` — an episode a deterministic parser consolidated and
  Sleep never will (``processed_by: parser``, R-LS10).

The pre-scan reads ``bank_index``'s cached frontmatter instead of re-parsing
every episode per call (R-LS3): a watched folder stages on every save.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

from api.services import bank_index, episode_ids, episode_scrub, markdown_parser

#: Column order of one ``turn_index`` row (R-LS2).
TURN_INDEX_COLUMNS = ("offset", "ts", "speaker")
#: Above this many turns the sidecar is omitted, never truncated (R-LS2).
MAX_TURN_INDEX_ROWS = 4000
#: ``processed_by`` of an episode a deterministic parser consolidated (R-LS10).
PARSED_ONLY = "parser"


@dataclass
class Turn:
    text: str
    speaker: str = "user"
    ts: str | None = None


@dataclass
class EpisodeDraft:
    title: str = ""
    source_id: str | None = None
    source_updated_at: str | None = None
    timestamp: str | None = None
    original_date: str | None = None
    source: str = "unknown"
    origin: str | None = None
    turns: list[Turn] = field(default_factory=list)
    body: str | None = None
    extra: dict = field(default_factory=dict)
    queue_for_sleep: bool = True
    content_sha: str | None = None
    writer: str = "import"


@dataclass
class StageResult:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    renamed: int = 0
    tombstoned: int = 0
    #: unchanged bodies whose file hash moved (counted in ``skipped`` too).
    restamped: int = 0
    scrubbed: int = 0
    #: source_id -> episode id, for every draft with an id (skips included).
    episode_ids: dict[str, str] = field(default_factory=dict)
    #: source_id -> episode id for created, updated and renamed episodes only.
    touched: dict[str, str] = field(default_factory=dict)
    #: source_id -> episode id for episodes stamped deleted this call.
    tombstoned_sources: dict[str, str] = field(default_factory=dict)
    renamed_sources: list[tuple[str, str]] = field(default_factory=list)
    #: bank-relative paths written, for a scoped ``commit_paths``.
    paths: list[str] = field(default_factory=list)

    def as_tuple(self) -> tuple[int, int, int]:
        return self.created, self.updated, self.skipped


@dataclass
class IndexEntry:
    path: Path
    id: str
    fm: dict


def normalise_timestamp(ts) -> str | None:
    """``None`` stays ``None``; an aware ISO string becomes the R2 ``+00:00``
    shape; anything else (naive, unparseable) is returned as ``str(ts)``."""
    if ts is None:
        return None
    text = str(ts)
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return text
    if dt.tzinfo is None:
        return text
    return episode_ids.to_utc_iso(dt)


def draft_from_export(episode: dict) -> EpisodeDraft:
    """The chat importers' dict shape as a draft (G20 callers unchanged)."""
    return EpisodeDraft(
        title=episode.get("title") or "",
        source_id=episode.get("source_id"),
        source_updated_at=episode.get("source_updated_at"),
        timestamp=episode.get("timestamp"),
        original_date=episode.get("original_date"),
        source=episode.get("source", "unknown"),
        origin=episode.get("origin"),
        turns=[Turn(text=m["text"], speaker=m["role"], ts=m.get("timestamp"))
               for m in episode.get("messages", [])],
        writer="import",
    )


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def render(draft: EpisodeDraft) -> tuple[str, list[list], int]:
    """``(body, turn_index rows, replacements)``. Each turn is scrubbed BEFORE
    its offset is taken, so every offset points into the text that is stored."""
    if draft.body is not None:
        body, n = episode_scrub.scrub(draft.body)
        return body, [], n
    lines: list[str] = []
    rows: list[list] = []
    offset = total = 0
    for turn in draft.turns:
        text, n = episode_scrub.scrub(turn.text)
        total += n
        line = f"{turn.speaker}: {text}"
        rows.append([offset, turn.ts, turn.speaker])
        lines.append(line)
        offset += len(line) + 1
    return "\n".join(lines), rows, total


def _raw_render(draft: EpisodeDraft) -> str:
    if draft.body is not None:
        return draft.body
    return "\n".join(f"{t.speaker}: {t.text}" for t in draft.turns)


def _fragment(source_id: str) -> str:
    return source_id.partition("#")[2]


def _rel(path: Path, episodes_dir: Path) -> str:
    return f"{episodes_dir.name}/{path.name}"


def scan(episodes_dir: Path) -> tuple[dict[str, IndexEntry], set[str]]:
    """``source_id -> entry`` plus every stored content hash, from ONE cached
    read of the directory (R-LS3). Frontmatter is copied: ``bank_index`` hands
    out its cache and a caller must never mutate it."""
    by_source: dict[str, IndexEntry] = {}
    hashes: set[str] = set()
    for f in bank_index.files(episodes_dir.parent, episodes_dir.name):
        fm = dict(f.frontmatter or {})
        if fm.get("content_hash"):
            hashes.add(str(fm["content_hash"]))
        sid = fm.get("source_id")
        if sid:
            by_source[str(sid)] = IndexEntry(path=f.path, id=str(fm.get("id") or f.stem), fm=fm)
    return by_source, hashes


def _apply_common(fm: dict, draft: EpisodeDraft, rows: list[list]) -> None:
    fm.update(draft.extra)
    if draft.content_sha:
        fm["content_sha"] = draft.content_sha
    if rows and len(rows) <= MAX_TURN_INDEX_ROWS:
        fm["turn_index"] = rows
    else:
        fm.pop("turn_index", None)
    if draft.queue_for_sleep:
        fm["processed"] = False
        # G114 R6: `processed_by` is written only beside `processed: true`.
        fm.pop("processed_by", None)
    else:
        fm["processed"] = True
        fm["processed_by"] = PARSED_ONLY


def write_new(draft: EpisodeDraft, episodes_dir: Path, body: str, digest: str,
              rows: list[list], date_counts: dict[str, int]) -> Path:
    """A fresh episode with a chronological id (G114 R1: ``date_counts`` holds the
    highest suffix per date, seeded from ``max_suffix_by_date``)."""
    ep_date = draft.original_date or datetime.now().strftime("%Y-%m-%d")
    date_counts[ep_date] = date_counts.get(ep_date, 0) + 1
    episode_id = f"ep_{ep_date}_{date_counts[ep_date]:03d}"
    fm = {
        "id": episode_id,
        "timestamp": normalise_timestamp(draft.timestamp) or episode_ids.utc_now_iso(),
        "source": draft.source,
        "title": draft.title or "Untitled",
        "processed": False,
        "content_hash": digest,
    }
    if draft.origin:
        fm["origin"] = draft.origin
    if draft.source_id is not None:
        fm["source_id"] = draft.source_id
        fm["source_updated_at"] = draft.source_updated_at
    _apply_common(fm, draft, rows)
    path = episodes_dir / f"{episode_id}.md"
    markdown_parser.write(path, fm, body)
    return path


def update_in_place(path: Path, draft: EpisodeDraft, body: str, digest: str, rows: list[list]) -> None:
    """Same file, same id, same original timestamp; new body, re-queued (G20)."""
    fm = dict(markdown_parser.parse(path).frontmatter)
    fm["title"] = draft.title or fm.get("title", "Untitled")
    fm["content_hash"] = digest
    fm["source_updated_at"] = draft.source_updated_at
    fm["source_id"] = draft.source_id
    if draft.origin:
        fm["origin"] = draft.origin
    fm.pop("source_deleted_at", None)
    _apply_common(fm, draft, rows)
    markdown_parser.write(path, fm, body)


def _refresh(path: Path, draft: EpisodeDraft) -> None:
    """Same body, changed metadata (an authorship flip, a returning file). A
    parser-only episode that is now owner-authored is queued; a queued one that
    is now agent-authored is parked. An episode Sleep already consolidated is
    never un-processed — its claims exist either way."""
    parsed = markdown_parser.parse(path)
    fm = dict(parsed.frontmatter)
    was_parser_only = fm.get("processed_by") == PARSED_ONLY
    fm.pop("source_deleted_at", None)
    fm.update(draft.extra)
    if draft.content_sha:
        fm["content_sha"] = draft.content_sha
    if draft.source_updated_at:
        fm["source_updated_at"] = draft.source_updated_at
    if draft.queue_for_sleep and was_parser_only:
        fm["processed"] = False
        fm.pop("processed_by", None)
    elif not draft.queue_for_sleep and not fm.get("processed"):
        fm["processed"] = True
        fm["processed_by"] = PARSED_ONLY
    markdown_parser.write(path, fm, parsed.body)


def _restamp(path: Path, draft: EpisodeDraft) -> None:
    parsed = markdown_parser.parse(path)
    fm = dict(parsed.frontmatter)
    fm["content_sha"] = draft.content_sha
    if draft.source_updated_at:
        fm["source_updated_at"] = draft.source_updated_at
    markdown_parser.write(path, fm, parsed.body)


def _repoint(path: Path, draft: EpisodeDraft, old_sid: str) -> None:
    parsed = markdown_parser.parse(path)
    fm = dict(parsed.frontmatter)
    previous = [s for s in (fm.get("previous_source_ids") or []) if s]
    if old_sid not in previous:
        previous.append(old_sid)
    fm["previous_source_ids"] = previous
    fm["source_id"] = draft.source_id
    fm["source_updated_at"] = draft.source_updated_at
    if draft.title:
        fm["title"] = draft.title
    fm.pop("source_deleted_at", None)
    fm.update(draft.extra)
    markdown_parser.write(path, fm, parsed.body)


def _tombstone(path: Path, at: str) -> None:
    parsed = markdown_parser.parse(path)
    fm = dict(parsed.frontmatter)
    fm["source_deleted_at"] = at
    markdown_parser.write(path, fm, parsed.body)


def _mark(result: StageResult, verb: str, sid: str, entry: IndexEntry, episodes_dir: Path) -> None:
    setattr(result, verb, getattr(result, verb) + 1)
    result.episode_ids[sid] = entry.id
    result.touched[sid] = entry.id
    result.paths.append(_rel(entry.path, episodes_dir))


def stage(drafts: Iterable[EpisodeDraft], episodes_dir: Path, *,
          deleted_source_ids: Iterable[str] = (), bank: str | None = None) -> StageResult:
    """Create / skip / update / rename / tombstone, delta-aware by ``source_id``.

    A draft WITHOUT a ``source_id`` keeps the pre-G20 content-hash behaviour
    exactly (create or skip, never update)."""
    episodes_dir.mkdir(parents=True, exist_ok=True)
    index, known_hashes = scan(episodes_dir)
    date_counts = episode_ids.max_suffix_by_date(episodes_dir)
    result = StageResult()
    now = episode_ids.utc_now_iso()
    deleted = list(dict.fromkeys(s for s in deleted_source_ids if s))
    renames: dict[tuple[str, str], str] = {}
    for sid in deleted:
        entry = index.get(sid)
        sha = entry.fm.get("content_sha") if entry else None
        if sha:
            renames.setdefault((str(sha), _fragment(sid)), sid)

    writer = "import"
    for draft in drafts:
        writer = draft.writer
        body, rows, n = render(draft)
        result.scrubbed += n
        digest = content_hash(body)
        legacy = content_hash(_raw_render(draft))
        sid = draft.source_id
        if sid:
            entry = index.get(sid)
            if entry is None and draft.content_sha:
                old = renames.pop((draft.content_sha, _fragment(sid)), None)
                if old is not None and old in index:
                    entry = index.pop(old)
                    deleted.remove(old)
                    _repoint(entry.path, draft, old)
                    entry.fm.update(source_id=sid)
                    entry.fm.pop("source_deleted_at", None)
                    index[sid] = entry
                    result.renamed_sources.append((old, sid))
                    _mark(result, "renamed", sid, entry, episodes_dir)
                    continue
            if entry is None:
                path = write_new(draft, episodes_dir, body, digest, rows, date_counts)
                known_hashes.add(digest)
                entry = IndexEntry(path=path, id=path.stem, fm={
                    "content_hash": digest, "content_sha": draft.content_sha,
                    "evidence_kind": draft.extra.get("evidence_kind")})
                index[sid] = entry
                _mark(result, "created", sid, entry, episodes_dir)
                continue
            same_body = entry.fm.get("content_hash") in (digest, legacy)
            same_meta = (entry.fm.get("evidence_kind") == draft.extra.get("evidence_kind")
                         and not entry.fm.get("source_deleted_at"))
            if same_body and same_meta:
                if draft.content_sha and entry.fm.get("content_sha") != draft.content_sha:
                    # An unchanged H2 section of an edited file: its words did not
                    # move, but the file's hash did. Restamp it (no re-queue) or a
                    # later rename could not match it by (sha, fragment) (R-LS12).
                    _restamp(entry.path, draft)
                    entry.fm["content_sha"] = draft.content_sha
                    result.restamped += 1
                    result.paths.append(_rel(entry.path, episodes_dir))
                result.skipped += 1
                result.episode_ids[sid] = entry.id
                continue
            if same_body:
                _refresh(entry.path, draft)
            else:
                update_in_place(entry.path, draft, body, digest, rows)
                known_hashes.add(digest)
                entry.fm["content_hash"] = digest
            entry.fm["evidence_kind"] = draft.extra.get("evidence_kind")
            entry.fm.pop("source_deleted_at", None)
            _mark(result, "updated", sid, entry, episodes_dir)
            continue
        if digest in known_hashes or legacy in known_hashes:
            result.skipped += 1
            continue
        path = write_new(draft, episodes_dir, body, digest, rows, date_counts)
        known_hashes.add(digest)
        result.created += 1
        result.paths.append(_rel(path, episodes_dir))

    for sid in deleted:
        entry = index.get(sid)
        if entry is None or entry.fm.get("source_deleted_at"):
            continue
        _tombstone(entry.path, now)
        entry.fm["source_deleted_at"] = now
        result.tombstoned += 1
        result.tombstoned_sources[sid] = entry.id
        result.paths.append(_rel(entry.path, episodes_dir))
    episode_scrub.record(writer, result.scrubbed, bank=bank)
    return result
