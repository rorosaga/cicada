"""Put the looks already saved on the pages of the things they show (owner 2026-10-20) — the one-time move from the
retired Looks board to each page's ``## Looks`` section, run by the person (``api/scripts/attach_looks.py``).

For every look record (``design_refs``):

* one already on a page that is there keeps it (its page's section is written when it is missing or stale);
* any other is placed by the writer's own rule (:func:`design_refs.subject_for`): exactly one page whose trusted site
  is the look's site, else the saved link's own page — and **never a page invented**: a look with neither (or two
  pages claiming the site) stays unattached and is listed, for the person to place from a page.

Idempotent: a second run finds every look placed or listed and every section right, and writes nothing. Deterministic,
no model, nothing fetched. The apply holds the write admission and the page lock, re-surveys under them, and commits
what it wrote in ONE commit authored ``cicada``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from loguru import logger

from api.services import bank_index, design_refs, git_service, page_lock, write_admission

TRIGGER = "maintenance/attach-looks"


class SleepRunning(RuntimeError):
    pass


@dataclass
class Survey:
    looks: int = 0
    on_page: int = 0                 # already on a page that is there
    by_site: int = 0                 # would go on the one page whose trusted site is the look's
    by_link: int = 0                 # would go on the saved link's own page
    unattached: int = 0              # no page shows it: left for the person
    ambiguous: int = 0               # two or more pages claim the site: left for the person
    page_gone: int = 0               # named a page that is no longer there (then placed by the rule, or listed)
    pages_to_write: int = 0          # pages whose ``## Looks`` section changes
    written: int = 0
    committed: bool = False
    _moves: dict[str, str] = field(default_factory=dict, repr=False)      # look id -> page id
    _unplaced: list[dict] = field(default_factory=list, repr=False)       # [{id, site, why}]
    _pages: list[str] = field(default_factory=list, repr=False)

    def counts(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}

    def listing(self) -> dict:
        """For the person's own terminal only (look ids carry site names): what stays unattached and why."""
        return {"unattached": self._unplaced, "moves": self._moves}


def survey(memory_path) -> Survey:
    memory_path = Path(memory_path)
    out = Survey()
    refs = design_refs.list_refs(memory_path)
    out.looks = len(refs)
    pages = [(f.stem, f.frontmatter or {}) for f in bank_index.files(memory_path, "entities")]
    for ref in refs:
        if ref.entity and design_refs.page_exists(memory_path, ref.entity):
            out.on_page += 1
            continue
        if ref.entity:
            out.page_gone += 1
        target, how = design_refs.subject_for(memory_path, ref.url, pages=pages)
        if target is None:
            if how == "ambiguous":
                out.ambiguous += 1
            else:
                out.unattached += 1
            out._unplaced.append({"id": ref.id, "site": ref.site, "why": how})
            continue
        out._moves[ref.id] = target
        if how == "site":
            out.by_site += 1
        else:
            out.by_link += 1
    # Every page that shows a look after the moves, and whether its section would change.
    placed = {r.id: (out._moves.get(r.id) or (r.entity if design_refs.page_exists(memory_path, r.entity) else None))
              for r in refs}
    by_page: dict[str, list] = {}
    for ref in refs:
        if placed[ref.id]:
            by_page.setdefault(placed[ref.id], []).append(ref)
    from api.services import markdown_parser, page_edits

    for eid, mine in sorted(by_page.items()):
        page = memory_path / "entities" / f"{eid}.md"
        prose, _ = page_edits.split_prose(markdown_parser.parse(page, ledger=False).body)
        if design_refs.with_section(prose, design_refs.page_section(mine)).rstrip() != prose.rstrip():
            out._pages.append(eid)
    out.pages_to_write = len(out._pages)
    return out


def apply(memory_path, *, sleep_running: Callable[[], bool]) -> Survey:
    """Write the survey's moves and sections and commit them together, authored ``cicada``. Raises
    :class:`SleepRunning` before writing anything when Sleep holds the pages or a run is in progress."""
    memory_path = Path(memory_path)
    with write_admission.admitted(memory_path, refuse=lambda: SleepRunning("Sleep is holding this bank's pages")):
        if sleep_running():
            raise SleepRunning("a Sleep run is in progress; attach the looks after it ends")
        with page_lock.page_lock(memory_path):
            result = survey(memory_path)
            paths: list[str] = []
            for ref_id, eid in result._moves.items():
                ref = design_refs.get_ref(memory_path, ref_id)
                if ref is None:
                    continue
                design_refs._set_entity(memory_path, ref, eid)
                paths.append(ref.path)
            refs = design_refs.list_refs(memory_path)
            for eid in result._pages:
                if (rel := design_refs.sync_page(memory_path, eid, refs)) is not None:
                    paths.append(rel)
            result.written = len(paths)
            if paths and (memory_path / ".git").exists():
                message = git_service.build_commit_message(
                    f"Looks attached to their pages: {len(result._moves)} look(s), {len(result._pages)} page(s)",
                    [f"{rel}: updated (trigger: {TRIGGER})" for rel in paths], authors=["cicada"])
                git_service.commit_paths_sync(memory_path, message, paths)
                result.committed = True
    if result.written:
        logger.info(f"looks attach: {len(result._moves)} look(s) placed, {len(result._pages)} page(s) written")
    return result
