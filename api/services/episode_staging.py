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
* ``turns`` — per-turn chronology as a frontmatter sidecar, entries of
  ``{offset, ts, speaker}`` into the stored body: G118 slice 2's R-PB4 shape,
  the one ``evidence.turn_stamps`` reads for the Reader. OUTSIDE the content
  hash on purpose: timestamps in the body would change every export's hash and
  re-queue the whole corpus on the next import (💸). An entry only for a turn
  that has a time, always the LAST frontmatter key, capped head-stable at
  ``MAX_TURN_STAMPS``, omitted when no turn has a time. (This track first wrote
  a ``turn_index`` of ``[offset, ts, speaker]`` rows, R-LS1/R-LS2, because the
  Stop hook's ``turns:`` is an integer count; the merge with G118 slice 2 kept
  ONE key — the hook's int reads as "no stamps" in ``turn_stamps`` — and turn
  numbering now comes from the body's marker lines, ``evidence.turn_at``.)
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

One process-wide lock serialises ``stage`` (Track L Task 2 review, round 1):
the scan, the id mint (``max_suffix_by_date``) and the write are a
read-modify-write, and two overlapping callers — the folder watcher plus a
manual Sync, two folder batches, a chat import landing mid-sync — both minted
the same ``ep_<date>_NNN`` and ``markdown_parser.write`` silently overwrote the
first episode. Reproduced with two threads on one date; the lock is here, in
the stager, so every source that stages is covered, not only the folder route.
"""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from api.services import bank_index, episode_ids, episode_scrub, markdown_parser

#: Keys of one ``turns`` sidecar entry (R-PB4) — the coordination contract, exactly.
TURN_STAMP_KEYS = ("offset", "ts", "speaker")
#: The sidecar's head-stable cap (R-PB4, moved here from the conversations
#: router with the stager): frontmatter is parsed on every cold ``bank_index``
#: scan, so turns past the cap carry no time — the Reader shows a time only when
#: one is stored and never infers one.
MAX_TURN_STAMPS = 500
#: ``processed_by`` of an episode a deterministic parser consolidated (R-LS10).
PARSED_ONLY = "parser"
#: Serialises every ``stage`` call in this process (see the module docstring).
#: Re-entrant so a caller that already holds it (a source that scans, decides and
#: stages under one critical section) can call ``stage`` without deadlocking.
STAGE_LOCK = threading.RLock()


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
    #: one verb per draft, in order — ``created`` / ``updated`` / ``renamed`` /
    #: ``skipped`` — so ``plan`` can say which draft lands where (Track I T2).
    verdicts: list[str] = field(default_factory=list)

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


def _line(turn: Turn, text: str) -> str:
    """One body line — the ONLY place a turn's ``<marker>: text`` shape is
    spelled, so the hashed body and the sidecar's offsets cannot disagree."""
    return f"{turn.speaker}: {text}"


def _stamps(turns: list[Turn], texts: list[str]) -> list[dict]:
    """``[{offset, ts, speaker}]`` for the body ``texts`` render to (R-PB4).
    ``offset`` is the turn's marker-line start (a turn start ``evidence.turns``
    finds); ``ts`` the turn's own time in the one aware-UTC shape; a turn
    without a time gets no entry (it would only repeat the marker)."""
    out: list[dict] = []
    offset = 0
    for turn, text in zip(turns, texts):
        ts = normalise_timestamp(turn.ts)
        if ts and len(out) < MAX_TURN_STAMPS:
            out.append({"offset": offset, "ts": ts, "speaker": str(turn.speaker)})
        offset += len(_line(turn, text)) + 1
    return out


def render(draft: EpisodeDraft) -> tuple[str, list[dict], int]:
    """``(body, turns sidecar, replacements)``. Each turn is scrubbed BEFORE
    its offset is taken, so every offset points into the text that is stored."""
    if draft.body is not None:
        body, n = episode_scrub.scrub(draft.body)
        return body, [], n
    texts: list[str] = []
    total = 0
    for turn in draft.turns:
        text, n = episode_scrub.scrub(turn.text)
        total += n
        texts.append(text)
    body = "\n".join(_line(t, x) for t, x in zip(draft.turns, texts))
    return body, _stamps(draft.turns, texts), total


def stamps_for(draft: EpisodeDraft, body: str) -> list[dict]:
    """The sidecar for ``body`` when it is exactly ``draft``'s own rendering
    (scrubbed or raw), else ``[]`` — the offsets would vouch for text they do
    not index. For the router's compat wrappers, which take a body as given."""
    if draft.body is not None:
        return []
    for texts in ([episode_scrub.scrub(t.text)[0] for t in draft.turns], [t.text for t in draft.turns]):
        if "\n".join(_line(t, x) for t, x in zip(draft.turns, texts)) == body:
            return _stamps(draft.turns, texts)
    return []


def _raw_render(draft: EpisodeDraft) -> str:
    if draft.body is not None:
        return draft.body
    return "\n".join(_line(t, t.text) for t in draft.turns)


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


def _apply_common(fm: dict, draft: EpisodeDraft, stamps: list[dict]) -> None:
    fm.update(draft.extra)
    if draft.content_sha:
        fm["content_sha"] = draft.content_sha
    if draft.queue_for_sleep:
        fm["processed"] = False
        # G114 R6: `processed_by` is written only beside `processed: true`.
        fm.pop("processed_by", None)
    else:
        fm["processed"] = True
        fm["processed_by"] = PARSED_ONLY
    # R-PB4: the new body's times replace the old ones, as the LAST key so the
    # episode's identity reads first; a body that lost them drops the key
    # rather than keeping stale offsets.
    fm.pop("turns", None)
    if stamps:
        fm["turns"] = stamps


def write_new(draft: EpisodeDraft, episodes_dir: Path, body: str, digest: str,
              stamps: list[dict], date_counts: dict[str, int]) -> Path:
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
    _apply_common(fm, draft, stamps)
    path = episodes_dir / f"{episode_id}.md"
    markdown_parser.write(path, fm, body)
    return path


def update_in_place(path: Path, draft: EpisodeDraft, body: str, digest: str, stamps: list[dict]) -> None:
    """Same file, same id, same original timestamp; new body, re-queued (G20)."""
    fm = dict(markdown_parser.parse(path).frontmatter)
    fm["title"] = draft.title or fm.get("title", "Untitled")
    fm["content_hash"] = digest
    fm["source_updated_at"] = draft.source_updated_at
    fm["source_id"] = draft.source_id
    if draft.origin:
        fm["origin"] = draft.origin
    fm.pop("source_deleted_at", None)
    _apply_common(fm, draft, stamps)
    markdown_parser.write(path, fm, body)


def _refresh(path: Path, draft: EpisodeDraft) -> None:
    """Same body, changed metadata (an authorship flip, a returning file). A
    parser-only episode that is now owner-authored is queued; a queued one that
    is now agent-authored is parked. An episode Sleep already consolidated is
    never un-processed — its claims exist either way."""
    parsed = markdown_parser.parse(path)
    fm = dict(parsed.frontmatter)
    fm.pop("source_deleted_at", None)
    fm.update(draft.extra)
    if draft.content_sha:
        fm["content_sha"] = draft.content_sha
    if draft.source_updated_at:
        fm["source_updated_at"] = draft.source_updated_at
    _requeue_for_authorship(fm, draft)
    markdown_parser.write(path, fm, parsed.body)


def _requeue_for_authorship(fm: dict, draft: EpisodeDraft) -> None:
    """The queue rule for an episode whose BODY is unchanged but whose
    authorship may have moved (R-LS10 / R-F2): a parser-only episode that is now
    the person's own words is queued; an unconsolidated one that is now an
    agent's is parked as parser-only. An episode Sleep already consolidated is
    never un-processed — its claims exist either way.

    Shared by ``_refresh`` (a glob flip) and ``_repoint`` (a rename). Before it
    was shared, a rename across an authorship glob (``notes.md`` →
    ``archive/notes.md``) flipped ``evidence_kind`` but not the queue state, so
    Sleep consolidated agent prose — or never saw the person's words — and the
    folder's idempotence check (``content_sha`` + ``evidence_kind``) then read
    the file as unchanged forever (Track L Task 2 review, round 1)."""
    if draft.queue_for_sleep and fm.get("processed_by") == PARSED_ONLY:
        fm["processed"] = False
        # G114 R6: `processed_by` is written only beside `processed: true`.
        fm.pop("processed_by", None)
    elif not draft.queue_for_sleep and not fm.get("processed"):
        fm["processed"] = True
        fm["processed_by"] = PARSED_ONLY


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
    _requeue_for_authorship(fm, draft)
    markdown_parser.write(path, fm, parsed.body)


def _tombstone(path: Path, at: str) -> None:
    parsed = markdown_parser.parse(path)
    fm = dict(parsed.frontmatter)
    fm["source_deleted_at"] = at
    markdown_parser.write(path, fm, parsed.body)


def _mark(result: StageResult, verb: str, sid: str, entry: IndexEntry, episodes_dir: Path) -> None:
    setattr(result, verb, getattr(result, verb) + 1)
    result.verdicts.append(verb)
    result.episode_ids[sid] = entry.id
    result.touched[sid] = entry.id
    result.paths.append(_rel(entry.path, episodes_dir))


#: Called once per draft, after its verdict is on disk: ``progress(verb)``.
Progress = Callable[[str], None]


def stage(drafts: Iterable[EpisodeDraft], episodes_dir: Path, *,
          deleted_source_ids: Iterable[str] = (), bank: str | None = None,
          progress: Progress | None = None) -> StageResult:
    """Create / skip / update / rename / tombstone, delta-aware by ``source_id``.

    A draft WITHOUT a ``source_id`` keeps the pre-G20 content-hash behaviour
    exactly (create or skip, never update). Runs under ``STAGE_LOCK``.

    ``progress`` is the intake job's counter (Track I T2b): a large import
    stages in ONE call and reports per draft, instead of one call per batch —
    each call scans the bank, and per-batch calls measured 177 s for 1,000
    threads into a 2,000-episode bank against 9.9 s as one call (Track I final
    review, finding 2)."""
    with STAGE_LOCK:
        return _stage_locked(list(drafts), episodes_dir,
                             deleted_source_ids=list(deleted_source_ids), bank=bank,
                             progress=progress)


def plan(drafts: Iterable[EpisodeDraft], episodes_dir: Path) -> StageResult:
    """What ``stage`` WOULD do, writing nothing — the intake preview's
    new · grown · already-here (Track I T2, R-IA5).

    The same loop as ``stage`` with every write skipped, not a mirror of it:
    the branch-local mirror this replaced hashed the RAW body while the stager
    compares the scrubbed digest or the legacy raw one, so any thread a scrub
    rule touched previewed as "grew" and then staged as a skip (Track I final
    review, finding 1). No lock — nothing is minted or written — no directory
    is created and no scrub telemetry is recorded: a sniff runs on every drop."""
    return _stage_locked(list(drafts), episodes_dir, deleted_source_ids=[], bank=None, dry_run=True)


def _stage_locked(drafts: list[EpisodeDraft], episodes_dir: Path, *,
                  deleted_source_ids: list[str], bank: str | None,
                  dry_run: bool = False, progress: Progress | None = None) -> StageResult:
    write = not dry_run
    if write:
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
        body, stamps, n = render(draft)
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
                    if write:
                        _repoint(entry.path, draft, old)
                    entry.fm.update(source_id=sid, evidence_kind=draft.extra.get("evidence_kind"))
                    entry.fm.pop("source_deleted_at", None)
                    index[sid] = entry
                    result.renamed_sources.append((old, sid))
                    _mark(result, "renamed", sid, entry, episodes_dir)
                    _report(progress, "renamed")
                    continue
            if entry is None:
                path = (write_new(draft, episodes_dir, body, digest, stamps, date_counts) if write
                        else _planned_path(episodes_dir, draft, date_counts))
                known_hashes.add(digest)
                entry = IndexEntry(path=path, id=path.stem, fm={
                    "content_hash": digest, "content_sha": draft.content_sha,
                    "evidence_kind": draft.extra.get("evidence_kind")})
                index[sid] = entry
                _mark(result, "created", sid, entry, episodes_dir)
                _report(progress, "created")
                continue
            same_body = entry.fm.get("content_hash") in (digest, legacy)
            same_meta = (entry.fm.get("evidence_kind") == draft.extra.get("evidence_kind")
                         and not entry.fm.get("source_deleted_at"))
            if same_body and same_meta:
                if draft.content_sha and entry.fm.get("content_sha") != draft.content_sha:
                    # An unchanged H2 section of an edited file: its words did not
                    # move, but the file's hash did. Restamp it (no re-queue) or a
                    # later rename could not match it by (sha, fragment) (R-LS12).
                    if write:
                        _restamp(entry.path, draft)
                    entry.fm["content_sha"] = draft.content_sha
                    result.restamped += 1
                    result.paths.append(_rel(entry.path, episodes_dir))
                result.skipped += 1
                result.verdicts.append("skipped")
                result.episode_ids[sid] = entry.id
                _report(progress, "skipped")
                continue
            if same_body and write:
                _refresh(entry.path, draft)
            elif not same_body:
                if write:
                    update_in_place(entry.path, draft, body, digest, stamps)
                known_hashes.add(digest)
                entry.fm["content_hash"] = digest
            entry.fm["evidence_kind"] = draft.extra.get("evidence_kind")
            entry.fm.pop("source_deleted_at", None)
            _mark(result, "updated", sid, entry, episodes_dir)
            _report(progress, "updated")
            continue
        if digest in known_hashes or legacy in known_hashes:
            result.skipped += 1
            result.verdicts.append("skipped")
            _report(progress, "skipped")
            continue
        path = (write_new(draft, episodes_dir, body, digest, stamps, date_counts) if write
                else _planned_path(episodes_dir, draft, date_counts))
        known_hashes.add(digest)
        result.created += 1
        result.verdicts.append("created")
        result.paths.append(_rel(path, episodes_dir))
        _report(progress, "created")

    for sid in deleted:
        entry = index.get(sid)
        if entry is None or entry.fm.get("source_deleted_at"):
            continue
        if write:
            _tombstone(entry.path, now)
        entry.fm["source_deleted_at"] = now
        result.tombstoned += 1
        result.tombstoned_sources[sid] = entry.id
        result.paths.append(_rel(entry.path, episodes_dir))
    if write:
        episode_scrub.record(writer, result.scrubbed, bank=bank)
    return result


def _planned_path(episodes_dir: Path, draft: EpisodeDraft, date_counts: dict[str, int]) -> Path:
    """The file ``write_new`` would mint for ``draft`` — ``plan`` bumps the same
    per-date counter so its ``paths`` and ids read like a real run's."""
    ep_date = draft.original_date or datetime.now().strftime("%Y-%m-%d")
    date_counts[ep_date] = date_counts.get(ep_date, 0) + 1
    return episodes_dir / f"ep_{ep_date}_{date_counts[ep_date]:03d}.md"


def _report(progress: Progress | None, verb: str) -> None:
    if progress is not None:
        progress(verb)
