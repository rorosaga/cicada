"""A saved list is provenance, not a hub — the repair for banks written before (owner 2026-10-19).

    api/.venv/bin/python -m api.scripts.repair_list_hubs --bank <path>            # dry run: counts only
    api/.venv/bin/python -m api.scripts.repair_list_hubs --bank <path> --apply    # `cicada` commit(s)

"In the graph I see that my YouTube playlists are like hubs … This should be just a provenance thing: the video was
taken from this playlist and that's it." The media writer used to copy a slug of a save's ``folder`` — a YouTube
playlist, an Instagram collection, a Pinterest board, a Reddit subreddit, a browser bookmark folder, a device's
Safari tabs — into the page's ``tags`` (the Netscape bookmark parser the raw folder name too), and Stage 5.6 turns
any tag shared by five or more active pages into a ``topic-<tag>`` hub, so every list with enough saves became a
hub node with a ``member of`` edge to each of its saves. The writer no longer does it and the hub tier ignores those
tags (``hub_builder._topic_tags``); this repair takes them off the pages, where ``folder:`` already says the same
thing, and regenerates the hub tier through its one writer (``hub_builder.regenerate_hubs_and_index``), which
removes each list hub nothing else holds up.

Only a tag :func:`id_utils.folder_tags` names for the page's own ``folder:`` goes, and never the page's media type;
``folder:``, the body, claims and sources stay as they are. Deterministic, no model, no network. The dry run prints
counts only, never a page, a tag or a list name. ``--apply`` refuses while Sleep runs or holds the pages, or when the
backend cannot be asked; a page dirty in git (or whose claims ledger is), or written after the survey, is skipped.
A second run changes nothing. On a bank past :data:`COMMIT_STEP` changed pages
the commit is split into parts, the hub tier in the last. Order: write admission → page lock → git.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from loguru import logger

from api.services import git_service, markdown_parser, page_lock, write_admission
from api.services.id_utils import folder_tags

TRIGGER = "maintenance/list-hubs"
#: Pages per commit: a commit names each path on git's command line (``history_index.COMMIT_STEP``'s reason).
COMMIT_STEP = 500


class SleepRunning(RuntimeError):
    """Sleep holds this bank's pages, or a run is in progress: repair nothing."""


@dataclass
class Survey:
    """Counts only — never a name, a path, a tag or a word of the bank."""

    pages: int = 0
    with_folder: int = 0
    to_untag: int = 0          # pages carrying a tag their own folder left
    tags_removed: int = 0
    list_hubs: int = 0         # hub files a folder-derived tag holds up
    dirty: int = 0
    untagged: int = 0
    hubs_removed: int = 0
    committed: bool = False
    _todo: dict[Path, tuple[str, list[str]]] = field(default_factory=dict, repr=False)   # path -> (text, new tags)

    def counts(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}


def _frontmatter(text: str) -> dict | None:
    split = markdown_parser.split_frontmatter(text)
    if not split:
        return None
    try:
        fm = markdown_parser.load_yaml(split[0])
    except Exception:
        return None
    return fm if isinstance(fm, dict) else None


def _folder_drop(fm: dict) -> set[str]:
    """The tags this page's folder left on it, less the page's own media type (``hub_builder._topic_tags``'s rule)."""
    media = fm.get("media") if isinstance(fm.get("media"), dict) else {}
    return folder_tags(fm.get("folder")) - {str(media.get("media_type") or "")}


def _hub_rels(memory_path: Path) -> set[str]:
    hubs = memory_path / "hubs"
    return {f"hubs/{p.name}" for p in hubs.glob("*.md")} if hubs.is_dir() else set()


def survey(memory_path) -> Survey:
    """What :func:`apply` would do, read-only."""
    memory_path = Path(memory_path)
    result = Survey()
    dirty: frozenset[str] = frozenset()
    if (memory_path / ".git").exists():
        try:
            dirty = git_service.dirty_paths_sync(memory_path, "entities")
        except git_service.GitError:
            dirty = frozenset()
    list_tags: set[str] = set()
    for path in sorted((memory_path / "entities").glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        fm = _frontmatter(text)
        if fm is None:
            continue
        result.pages += 1
        drop = _folder_drop(fm)
        if not drop:
            continue
        result.with_folder += 1
        list_tags |= drop
        tags = [str(t) for t in (fm.get("tags") or []) if t] if isinstance(fm.get("tags"), list) else []
        kept = [t for t in tags if t not in drop]
        if len(kept) == len(tags):
            continue
        result.to_untag += 1
        if f"entities/{path.name}" in dirty or f"entities/{path.stem}.claims.jsonl" in dirty:
            # The page or its ledger holds someone else's uncommitted change: committing it would put that change
            # under this repair's name.
            result.dirty += 1
            continue
        result.tags_removed += len(tags) - len(kept)
        result._todo[path] = (text, kept)
    for rel in sorted(_hub_rels(memory_path)):
        fm = _frontmatter((memory_path / rel).read_text(encoding="utf-8", errors="replace")) or {}
        if fm.get("type") == "hub" and fm.get("hub_kind") == "tag" and str(fm.get("source_tag") or "") in list_tags:
            result.list_hubs += 1
    return result


def _commit(memory_path: Path, rels: list[str], hubs_before: set[str], hubs_after: set[str], result: Survey) -> None:
    """The pages, the hubs and ``_index.md`` under ``cicada``: one commit, or one per :data:`COMMIT_STEP` pages on a
    bank that large (a commit names each path on git's command line), the hub tier riding the last."""
    chunks = [rels[i:i + COMMIT_STEP] for i in range(0, len(rels), COMMIT_STEP)] or [[]]
    removed = sorted(hubs_before - hubs_after)
    for n, chunk in enumerate(chunks, 1):
        last = n == len(chunks)
        lines = [f"{rel}: list tags removed (trigger: {TRIGGER})" for rel in chunk]
        paths = list(chunk)
        if last:
            lines += [f"{rel}: removed (trigger: {TRIGGER})" for rel in removed]
            lines += [f"{rel}: regenerated (trigger: {TRIGGER})" for rel in sorted(hubs_after)]
            lines.append(f"_index.md: regenerated (trigger: {TRIGGER})")
            paths += [*sorted(hubs_before | hubs_after), "_index.md"]
        part = f" (part {n} of {len(chunks)})" if len(chunks) > 1 else ""
        message = git_service.build_commit_message(
            f"Saved lists are provenance, not hubs: {len(rels)} page(s) untagged, "
            f"{result.hubs_removed} hub(s) removed{part}",
            lines,
            authors=["cicada"],
        )
        git_service.commit_touched_sync(memory_path, message, paths)
    result.committed = True


def apply(memory_path, *, sleep_running: Callable[[], bool], settings=None) -> Survey:
    """Untag every page the survey found, regenerate the hub tier when a page changed or a list hub stands, and
    commit both in ONE commit authored ``cicada``. Raises :class:`SleepRunning` before writing anything when Sleep
    holds the pages or a run is in progress."""
    from api.config import Settings
    from api.services.hub_builder import regenerate_hubs_and_index

    memory_path = Path(memory_path)
    settings = settings or Settings(_env_file=None)
    with write_admission.admitted(memory_path, refuse=lambda: SleepRunning("Sleep is holding this bank's pages")):
        if sleep_running():
            raise SleepRunning("a Sleep run is in progress; repair after it ends")
        with page_lock.page_lock(memory_path):
            result = survey(memory_path)
            written: list[Path] = []
            for path, (surveyed, kept) in result._todo.items():
                if path.read_text(encoding="utf-8") != surveyed:   # written since the survey: its writer's to commit
                    result.dirty += 1
                    continue
                parsed = markdown_parser.parse(path)
                markdown_parser.write(path, {**parsed.frontmatter, "tags": kept}, parsed.body)
                written.append(path)
            result.untagged = len(written)
            if not written and not result.list_hubs:
                return result
            hubs_before = _hub_rels(memory_path)
            regenerate_hubs_and_index(memory_path, settings)
            hubs_after = _hub_rels(memory_path)
            result.hubs_removed = len(hubs_before - hubs_after)
            if (memory_path / ".git").exists():
                _commit(memory_path, [f"entities/{p.name}" for p in written], hubs_before, hubs_after, result)
    logger.info(f"list hub repair: {result.untagged} page(s) untagged, {result.hubs_removed} hub(s) removed")
    return result
