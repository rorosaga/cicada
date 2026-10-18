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

Rails: no model and no fetch here; frontmatter only for the predicate (the cached ``bank_index`` scan); every write
under the bank's episode lock, re-checked before it flips; nothing here logs a title or a query.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

#: ``processed_by`` of an episode read by the index, never by a model.
INDEXED_BY = "index"
#: ``source`` of a watch-history day (``watch_history.SOURCE``) and of a month's summary.
HISTORY_SOURCE = "watch-history"
HISTORY_PREFIX = "watch-history:"
MONTH_SOURCE = "watch-history-month"
MONTH_PREFIX = "watch-history-month:"
#: Origins only a platform's saved list writes (an export archive, or the person's agent reading Watch later).
LIST_ORIGINS = frozenset({"youtube-playlist", "instagram-saved", "tiktok-saved", "x-likes", "linkedin-saved"})
#: Origins a connector shares with an export: the export's rows are told apart by the folder its reader names
#: (the Reddit connector files under ``r/<sub>``, the X connector under no folder).
LIST_FOLDERS: dict[str, frozenset[str]] = {
    "reddit-saved": frozenset({"Saved posts", "Saved comments"}),
    "x-bookmarks": frozenset({"Bookmarks"}),
}
#: Frontmatter flag on a list save that carries the person's own note or reason: their words are read by Sleep.
NOTE_KEY = "has_note"
#: Paths per retirement commit: a commit names each path three times on git's command line.
COMMIT_STEP = 500


def kind(fm: dict | None) -> str | None:
    """``history`` (a watched day), ``month`` (a month's summary), ``list`` (a save from a platform's saved list),
    or ``None`` — an episode Sleep reads with a model."""
    if not isinstance(fm, dict):
        return None
    source = str(fm.get("source") or "")
    sid = str(fm.get("source_id") or "")
    if source == HISTORY_SOURCE or sid.startswith(HISTORY_PREFIX):
        return "history"
    if source == MONTH_SOURCE or sid.startswith(MONTH_PREFIX):
        return "month"
    origin = str(fm.get("origin") or "")
    if fm.get(NOTE_KEY):
        return None
    if origin in LIST_ORIGINS:
        return "list"
    folders = LIST_FOLDERS.get(origin)
    if folders is not None and str(fm.get("folder") or "") in folders:
        return "list"
    return None


def is_index_only(fm: dict | None) -> bool:
    return kind(fm) is not None


def waits_for_model(fm: dict | None) -> bool:
    """Is this episode waiting for Sleep's model read? Not when it is read, and never when it is index-only."""
    if not isinstance(fm, dict) or fm.get("processed", False):
        return False
    return not is_index_only(fm)


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


def retire(memory_path: Path, *, skip: frozenset[str] = frozenset()) -> Retired:
    """Mark every queued index-only episode read, ``processed_by: index``. Pure files; the caller commits
    ``paths``. ``skip``: memory-relative paths dirty in git before this ran — an uncommitted capture keeps its own
    author (its writer's commit, or the next run, takes it); it stays out of every model batch meanwhile
    (:func:`waits_for_model`). Each file is re-read under the episode lock and flipped only if it is still queued
    and still index-only, exactly as Sleep retires what it read (audit A01)."""
    from api.services import bank_index, episode_ids, markdown_parser

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
            fm["processed"] = True
            fm["processed_by"] = INDEXED_BY
            if "turns" in fm:
                fm["turns"] = fm.pop("turns")   # R-PB4: the sidecar stays the last key
            markdown_parser.write(f.path, fm, parsed.body)
        out.paths.append(rel)
        out.by_kind[k] += 1
    return out


TRIGGER = "sleep/index"
AUTHOR = "cicada"


def commit_message(paths: list[str], day: str, *, part: int = 1, parts: int = 1) -> str:
    """``Indexed without a model <date>``: one manifest line per file, ``Cicada-Author: cicada``, no engine trailer
    (no model ran — the G85 shape)."""
    from api.services import git_service

    suffix = f" (part {part} of {parts})" if parts > 1 else ""
    return git_service.build_commit_message(
        f"Indexed without a model {day}{suffix}",
        [f"{p}: indexed (source: n/a, trigger: {TRIGGER})" for p in paths],
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
           "MONTH_SOURCE", "NOTE_KEY", "Retired", "TRIGGER", "commit_message", "count", "is_index_only", "kind", "restore",
           "retire", "waits_for_model"]
