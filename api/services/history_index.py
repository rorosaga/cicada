"""Watch history and platform-export saves are indexed, not consolidated (owner ruling 2026-10-18; G71, G94).

The owner imported a YouTube Takeout with its watch history: 45,879 watches became 2,532 day episodes and 3,156
playlist saves became saved videos, and every one of them was queued for a full Stage-1 model read. Owner: "maybe
overanalyzing the watch history is too much … Maybe just have it there and then maybe the metadata has it as
embeddings or something." So these are a record to look up, never a conversation to read:

* **What is index-only** (:func:`kind`). A watch-history day (``source: watch-history``), the month summary built
  from those days (``source: watch-history-month``, :func:`watch_history.rollup`), and a save that came in from a
  platform's saved LIST — a Takeout playlist (Watch later included, whichever door read it), Instagram saves and
  likes, TikTok likes and favourites, an X archive's likes and bookmarks, Reddit's and LinkedIn's export CSVs. A link
  the person bookmarked in a browser, a single URL save, a connector poll (Reddit's ``r/<sub>`` folders, X's API
  bookmarks) and a save carrying the person's own note keep being read by Sleep: none of those has an index-only
  origin, no list door carries the person's words (the parsers never set ``note`` or ``reason``), and a list save
  that ever did is stamped ``has_note`` and queued like any save.
* **Read without a model.** Capture writes them already read — ``processed: true``, ``processed_by: index`` — and
  Sleep retires the ones a bank queued before this ruling (:func:`retire`) at the start of every run, before a
  drain freezes its ids, in its own ``cicada`` commit. :func:`waits_for_model` is the one predicate every "waiting
  for Sleep" count uses, so an index-only episode never enters a model batch, a drain's frozen list or its progress.
* **Found by lookup.** They stay files in ``episodes/``: the lexical and vector indexes cover every episode, so
  recall's excerpts, search and the timeline find them; a saved video stays in Saved with its media page.

**The lean pass (ruling 62, owner 2026-11-04):** "a leaner initial pass for consolidation on those things who have no
reason/user intent attached, but enough info so that it can come up in a relevant conversation and an agent can look
further into it." So every other bare save is index-only too (:func:`kind` ``saved``): a browser bookmark, a tab group,
a single saved link, a feed item, a connector poll, with no note and no reason. No model reads it; it makes no claim, no
page and no question; its title, link, site and date stay findable (``saved_lookup``). A save carrying a reason, or one
the person later talks about, is read once like any conversation (:func:`wake`, ``saved_mentions``). A save a model
already read keeps what it made and stays as it was: ``saved`` never names it.

Rails: no model and no fetch here; frontmatter only for the predicate (the cached ``bank_index`` scan); every write
under the bank's episode lock, re-checked before it flips; nothing here logs a title or a query.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from api.services import evidence as _evidence

#: ``processed_by`` of an episode read by the index, never by a model.
INDEXED_BY = "index"
#: ``source`` of a watch-history day (``watch_history.SOURCE``) and of a month's summary.
HISTORY_SOURCE = "watch-history"
HISTORY_PREFIX = "watch-history:"
MONTH_SOURCE = "watch-history-month"
MONTH_PREFIX = "watch-history-month:"
#: ``source`` of an activity-traces day summary (G218, ``trace_memory``): counted, index-only unless the person turned
#: on "Learn from traces" when it was written (``learn_from_traces`` in its frontmatter) — the one model read traces get.
TRACES_SOURCE = "traces-day"
TRACES_PREFIX = "traces-day:"
#: ``source`` of a reading day (G218, 2026-10-28, ``trace_memory.write_reading``): the pages activity traces saw read
#: on any site that day — index-only like a watched day (ruling 30), never read by a model. G89 (2026-11-04): the posts
#: the person's Substack History showed, ``reading-history:substack:<day>`` (``substack_reads``), are the same kind.
READING_SOURCE = "reading-history"
READING_PREFIX = "reading-history:"
#: ``source`` of a listening day (G32, ``listening_history``): what was played on Spotify that day, from the person's own
#: export — index-only like a watched day (ruling 30), never read by a model, never a mention.
LISTENING_SOURCE = "listening-history"
LISTENING_PREFIX = "listening-history:"
#: Origins only a platform's saved list writes (an export archive, or the person's agent reading Watch later or,
#: G206, a saved list on X, Instagram or LinkedIn — ``saved_lists``, which files X under the archive's ``Bookmarks``).
#: G230: GitHub's own lists, read with the person's token — the repositories they starred (a save each) and the ones
#: they own (a record GitHub keeps, offered as a project, never the person's words).
#: G232: Pinterest's saved pins, read by the person's agent in their browser.
#: G89 (2026-11-04): ``substack-saved`` — the posts the person's agent read off their Substack Saved list.
LIST_ORIGINS = frozenset({"youtube-playlist", "instagram-saved", "tiktok-saved", "x-likes", "linkedin-saved",
                          "spotify-saved", "github-starred", "github-owned", "pinterest-saved", "substack-saved"})
#: Origins a connector shares with an export: the export's rows are told apart by the folder its reader names
#: (the Reddit connector files under ``r/<sub>``, the X connector under no folder).
LIST_FOLDERS: dict[str, frozenset[str]] = {
    # G232: an upvote (a like) and a joined community (a follow), from the connector or the export, are index-only
    # like Instagram's likes; a connector save (``r/<sub>``) is still a connector poll Sleep reads (ruling 30).
    "reddit-saved": frozenset({"Saved posts", "Saved comments", "Upvoted", "Joined communities"}),
    "x-bookmarks": frozenset({"Bookmarks"}),
}
#: Ruling 62: what a bare save is, by its own record, beside the saving door's page link (``media_entity_id``, ``url``):
#: a tab group holds no page link, and an older bookmark episode may not.
SAVE_SUFFIXES = ("-bookmark", "-tab-group")
SAVE_SOURCES = frozenset({"tab-group"})
#: Ruling 62: an episode carrying a saved page's link that is NOT a save: an agent's report of what it read or watched,
#: or Cicada's own check. Each is written read, or read on its own terms.
NOT_A_SAVE = frozenset({"video-watch", "page-read", "profile-read", "web-check", "source-check", "source-refresh"})
#: A book's record (``books.EPISODE_KEY``): read for its notes, on its own terms.
BOOK_KEY = "book"
#: Frontmatter flag on a list save that carries the person's own note or reason: their words are read by Sleep.
NOTE_KEY = "has_note"
#: Ruling 62: why a bare save gets its one real read (``{why, at}``): the person mentioned it. Stamped by :func:`wake`,
#: it takes the episode out of :func:`kind` for good, so the read happens once and says why.
WOKEN_KEY = "read_asked"
#: Frontmatter a list save carries once the person said why they saved it (``saved_why``'s answer, its earlier
#: answers) or a note: any of them makes the save theirs to read, never index-only (review of #340).
PERSON_KEYS = (NOTE_KEY, "saved_why", "saved_why_earlier")
#: Body sections only the person's own words fill: ``saved_why``'s, a save's reason (Telegram, ``/save``), a note —
#: ``evidence``'s one list, which also makes them the only ``user`` words in a save.
PERSON_SECTIONS = _evidence.PERSON_SECTIONS
#: Ruling 62: an agent's note on a save (``## Note``) is not the person's words, and it still says why the link matters:
#: a save that has one is read like a save with a reason.
REASON_SECTIONS = (*PERSON_SECTIONS, "## Note")
#: Paths per retirement commit: a commit names each path three times on git's command line.
COMMIT_STEP = 500


def kind(fm: dict | None) -> str | None:
    """``history`` (a watched day), ``month`` (a month's summary), ``list`` (a save from a platform's saved list),
    ``traces`` (an index-only trace day written before 2026-10-28), ``reading`` (a reading day), ``listening``
    (a listening day, G32), ``locked`` (a retired locked note, G234: never read, never indexed), ``saved`` (a bare
    save, ruling 62's lean pass), or ``None`` — an episode Sleep reads with a model."""
    if not isinstance(fm, dict):
        return None
    if fm.get(_evidence.LOCKED_NOTE_KEY):
        return "locked"
    source = str(fm.get("source") or "")
    sid = str(fm.get("source_id") or "")
    if source == HISTORY_SOURCE or sid.startswith(HISTORY_PREFIX):
        return "history"
    if source == MONTH_SOURCE or sid.startswith(MONTH_PREFIX):
        return "month"
    if source == TRACES_SOURCE or sid.startswith(TRACES_PREFIX):
        return None if fm.get("learn_from_traces") is True else "traces"
    if source == READING_SOURCE or sid.startswith(READING_PREFIX):
        return "reading"
    if source == LISTENING_SOURCE or sid.startswith(LISTENING_PREFIX):
        return "listening"
    origin = str(fm.get("origin") or "")
    if any(fm.get(key) for key in PERSON_KEYS):
        return None
    if origin in LIST_ORIGINS:
        return "list"
    folders = LIST_FOLDERS.get(origin)
    if folders is not None and str(fm.get("folder") or "") in folders:
        return "list"
    return "saved" if _is_bare_save(fm, origin, source) else None


def _is_bare_save(fm: dict, origin: str, source: str) -> bool:
    """Ruling 62: a save nobody has said anything about yet, by its own record, never by what its body says. Not one a
    model or an agent already read (a save read before this ruling keeps what it made, and every reader goes on
    treating it as read), not one woken for its read, not a book's record, not an agent's report."""
    if fm.get(WOKEN_KEY) or fm.get(BOOK_KEY) or source in NOT_A_SAVE:
        return False
    if fm.get("processed", False) and fm.get("processed_by") != INDEXED_BY:
        return False
    if source in SAVE_SOURCES or origin.endswith(SAVE_SUFFIXES):
        return True
    return bool(fm.get("media_entity_id") and fm.get("url"))


def is_index_only(fm: dict | None) -> bool:
    return kind(fm) is not None


def owes_a_read(fm: dict | None) -> bool:
    """Ruling 62: a save queued for its real read that no model has taken yet: woken, or given a reason. A later sync
    re-stages it as a bare save; that never takes the read back (``episode_staging``)."""
    return (isinstance(fm, dict) and not fm.get("processed", False) and kind(fm) is None
            and (bool(fm.get(WOKEN_KEY)) or any(fm.get(key) for key in PERSON_KEYS)))


def is_unread_save(fm: dict | None) -> bool:
    """A save no claim holds yet, so only ``saved_lookup`` can bring it up: a bare one, or one woken and still waiting."""
    return kind(fm) == "saved" or (owes_a_read(fm) and bool(fm.get(WOKEN_KEY)))


def has_person_words(body: str | None) -> bool:
    """Does a save's body hold a section the person wrote (why they saved it, a reason, a note)?"""
    lines = {ln.strip() for ln in (body or "").splitlines()}
    return any(h in lines for h in PERSON_SECTIONS)


def has_a_reason(body: str | None) -> bool:
    """Ruling 62: does a save's body say why it was saved, in the person's words or an agent's note?"""
    lines = {ln.strip() for ln in (body or "").splitlines()}
    return any(h in lines for h in REASON_SECTIONS)


def mark_person_words(fm: dict) -> bool:
    """A list save just gained the person's own words: stamp it theirs (``has_note``) and, when the index had read it,
    queue it for Sleep again. Mutates ``fm``; ``True`` when it changed. The caller writes under the episode lock."""
    if kind(fm) not in ("list", "saved"):
        return False
    fm[NOTE_KEY] = True
    if fm.get("processed_by") == INDEXED_BY:
        fm["processed"] = False
        fm.pop("processed_by", None)   # G114 R6: written only beside processed: true
    return True


def wake(memory_path: Path, episode_id: str, why: str, at: str) -> str | None:
    """Ruling 62: a bare save gets its one real read, because the person mentioned it. Stamps :data:`WOKEN_KEY` and
    queues it for the next run, under the episode lock, re-checked. The memory-relative path, or ``None`` when it is no
    longer a bare save (read meanwhile, removed from its source). Only ``saved_mentions`` calls this: a retrieval hit
    never does."""
    from api.services import episode_ids, markdown_parser

    episodes_dir = Path(memory_path) / "episodes"
    path = episodes_dir / f"{episode_id}.md"
    with episode_ids.episode_lock(episodes_dir):
        try:
            parsed = markdown_parser.parse(path)
        except Exception:  # noqa: BLE001 — a missing or malformed file wakes nothing
            return None
        fm = dict(parsed.frontmatter)
        if kind(fm) != "saved" or fm.get("source_deleted_at"):
            return None
        fm[WOKEN_KEY] = {"why": why, "at": at}
        fm["processed"] = False
        fm.pop("processed_by", None)   # G114 R6: written only beside processed: true
        markdown_parser.write(path, fm, parsed.body)
    return f"episodes/{episode_id}.md"


def waits_for_model(fm: dict | None) -> bool:
    """Is this episode waiting for Sleep's model read? Not when it is read, and never when it is index-only."""
    if not isinstance(fm, dict) or fm.get("processed", False):
        return False
    return not is_index_only(fm)


def _now() -> str:
    from api.services import episode_ids

    return episode_ids.utc_now_iso()


def _origin(fm: dict) -> str:
    return str(fm.get("origin") or fm.get("source") or "unknown")


@dataclass
class Count:
    """What :func:`retire` would do: counts and enums only (never a title)."""

    waiting: int = 0                     # every episode with processed: false
    for_model: int = 0                   # what Sleep's model would still read
    index_only: Counter = field(default_factory=Counter)      # kind -> queued episodes
    by_origin: Counter = field(default_factory=Counter)       # origin -> queued index-only episodes
    already_indexed: Counter = field(default_factory=Counter)  # kind -> episodes read by the index

    def as_dict(self) -> dict:
        return {"waiting": self.waiting, "for_model": self.for_model,
                "index_only_queued": sum(self.index_only.values()),
                "index_only_by_kind": dict(sorted(self.index_only.items())),
                "index_only_by_origin": dict(sorted(self.by_origin.items())),
                "already_indexed_by_kind": dict(sorted(self.already_indexed.items()))}


def count(memory_path: Path) -> Count:
    """The dry run: one cached frontmatter pass, writes nothing."""
    from api.services import bank_index

    out = Count()
    for f in bank_index.files(Path(memory_path), "episodes"):
        fm = f.frontmatter or {}
        k = kind(fm)
        if fm.get("processed", False):
            if k is not None and fm.get("processed_by") == INDEXED_BY:
                out.already_indexed[k] += 1
            continue
        out.waiting += 1
        if k is None:
            out.for_model += 1
        else:
            out.index_only[k] += 1
            out.by_origin[_origin(fm)] += 1
    return out


@dataclass
class Retired:
    paths: list[str] = field(default_factory=list)     # memory-relative
    by_kind: Counter = field(default_factory=Counter)
    skipped_dirty: int = 0
    #: list saves whose body holds the person's own words: stamped theirs and left for the model
    returned: int = 0
    #: the ``paths`` left queued for a read rather than marked read (the manifest's word for them)
    queued: list[str] = field(default_factory=list)


def retire(memory_path: Path, *, skip: frozenset[str] = frozenset()) -> Retired:
    """Mark every queued index-only episode read, ``processed_by: index``. Pure files; the caller commits
    ``paths``. ``skip``: memory-relative paths dirty in git before this ran — an uncommitted capture keeps its own
    author (its writer's commit, or the next run, takes it); it stays out of every model batch meanwhile
    (:func:`waits_for_model`). Each file is re-read under the episode lock and flipped only if it is still queued
    and still index-only, exactly as Sleep retires what it read (audit A01)."""
    from api.services import bank_index, episode_ids, markdown_parser, saved_mentions

    memory_path = Path(memory_path)
    out = Retired()
    queued = [f for f in bank_index.files(memory_path, "episodes")
              if not (f.frontmatter or {}).get("processed", False) and is_index_only(f.frontmatter)]
    if not queued:
        return out
    episodes_dir = memory_path / "episodes"
    for f in queued:
        rel = f"episodes/{f.path.name}"
        if rel in skip:
            out.skipped_dirty += 1
            continue
        with episode_ids.episode_lock(episodes_dir):
            try:
                parsed = markdown_parser.parse(f.path)
            except Exception:  # noqa: BLE001 — one malformed file never stops the rest
                continue
            fm = dict(parsed.frontmatter)
            k = kind(fm)
            if fm.get("processed", False) or k is None:
                continue
            if (k == "list" and has_person_words(parsed.body)) or (k == "saved" and has_a_reason(parsed.body)):
                # The person's words reached it by a door that did not stamp it (an older writer): theirs to read.
                # Ruling 62: an agent's note on a save too, the one kind of reason no frontmatter ever said.
                mark_person_words(fm)
                markdown_parser.write(f.path, fm, parsed.body)
                out.paths.append(rel)
                out.queued.append(rel)
                out.returned += 1
                continue
            if k == "saved" and saved_mentions.page_lit(memory_path, fm):
                # Ruling 62: a conversation already tied to this page, before the save was ever indexed.
                fm[WOKEN_KEY] = {"why": saved_mentions.WHY_LIT, "at": _now()}
                markdown_parser.write(f.path, fm, parsed.body)
                out.paths.append(rel)
                out.queued.append(rel)
                out.returned += 1
                continue
            fm["processed"] = True
            fm["processed_by"] = INDEXED_BY
            markdown_parser.write(f.path, fm, parsed.body)
        out.paths.append(rel)
        out.by_kind[k] += 1
    return out


TRIGGER = "sleep/index"
AUTHOR = "cicada"


def commit_message(paths: list[str], day: str, *, part: int = 1, parts: int = 1,
                   queued: frozenset[str] = frozenset()) -> str:
    """``Indexed without a model <date>``: one manifest line per file, ``Cicada-Author: cicada``, no engine trailer
    (no model ran — the G85 shape). ``queued``: files this left waiting for a read, which were not indexed."""
    from api.services import git_service

    suffix = f" (part {part} of {parts})" if parts > 1 else ""
    return git_service.build_commit_message(
        f"Indexed without a model {day}{suffix}",
        [f"{p}: {'queued' if p in queued else 'indexed'} (source: n/a, trigger: {TRIGGER})" for p in paths],
        authors=[AUTHOR],
    )


def restore(memory_path: Path, paths: list[str]) -> None:
    """Put files back as HEAD has them after a failed commit; an untracked one (a month summary born this run) is
    removed. Through the bank's one write lock. Re-derived on the next run."""
    from api.services import git_service

    memory_path = Path(memory_path)
    if not paths or not (memory_path / ".git").exists():
        return
    tracked: list[str] = []
    for p in paths:
        try:
            known = bool(git_service.run_git_write_sync(memory_path, "ls-files", "--", p).strip())
        except git_service.GitError:
            known = True
        if known:
            tracked.append(p)
        else:
            try:
                (memory_path / p).unlink()
            except OSError:
                pass
    if tracked:
        try:
            git_service.run_git_write_sync(memory_path, "checkout", "--", *tracked)
        except git_service.GitError:
            pass


__all__ = ["AUTHOR", "COMMIT_STEP", "Count", "HISTORY_SOURCE", "INDEXED_BY", "LIST_FOLDERS", "LIST_ORIGINS",
           "MONTH_SOURCE", "NOTE_KEY", "PERSON_KEYS", "PERSON_SECTIONS", "Retired", "WOKEN_KEY", "has_a_reason", "is_unread_save", "owes_a_read",
           "has_person_words", "mark_person_words", "TRIGGER", "commit_message", "count", "is_index_only", "kind",
           "restore", "retire", "waits_for_model", "wake"]
