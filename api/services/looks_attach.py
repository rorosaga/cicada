"""Put the looks already saved on the pages of the things they show (owner 2026-10-20) — the one-time move from the
retired Looks board to each page's ``## Looks`` section, run by the person (``api/scripts/attach_looks.py``).

For every look record (``design_refs``):

* one already on a page that is there keeps it (its page's section is written when it is missing or stale);
* any other is placed by the writer's own rule (:func:`design_refs.subject_for`): exactly one page whose trusted site
  is the look's site, else the saved link's own page — and **never a page invented**: a look with neither (or two
  pages claiming the site) stays unattached and is listed, for the person to place from a page. A look that named a
  page which is gone has that stale ``entity:`` cleared.

**Never another writer's change under this repair's name** (the ``list_hub_repair`` rules, #355). A record, a page or a
page's claims ledger dirty in git is skipped — unless its only change from HEAD is this repair's own (a record whose
``entity:`` alone moved, a page whose ``## Looks`` section alone differs): that is what an interrupted ``--apply``
leaves, and it is adopted and committed by the next run. A run that cannot ask git which files are dirty refuses. Each
file is re-read just before it is written and dropped when it changed since the survey. Writes are committed
:data:`COMMIT_STEP` paths at a time (a page with the looks moving onto it, together), so a stop leaves at most one step
uncommitted — which the next run adopts.

Idempotent: a second run finds every look placed or listed and every section right, and writes nothing. Deterministic,
no model, nothing fetched. Order: write admission → page lock → git; every commit authored ``cicada``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from loguru import logger

from api.services import bank_index, design_refs, git_service, markdown_parser, page_edits, page_lock, write_admission

TRIGGER = "maintenance/attach-looks"
#: Paths per commit: a commit names each path on git's command line (``history_index.COMMIT_STEP``'s reason).
COMMIT_STEP = 500


class Refused(RuntimeError):
    """The move cannot run safely now: nothing is written."""


class SleepRunning(Refused):
    pass


@dataclass
class Survey:
    looks: int = 0
    on_page: int = 0                 # already on a page that is there
    by_site: int = 0                 # would go on the one page whose trusted site is the look's
    by_link: int = 0                 # would go on the saved link's own page
    unattached: int = 0              # no page shows it: left for the person
    ambiguous: int = 0               # two or more pages claim the site: left for the person
    page_gone: int = 0               # named a page that is no longer there (placed by the rule, else cleared)
    pages_to_write: int = 0          # pages whose ``## Looks`` section changes
    adopted: int = 0                 # files an interrupted run wrote and never committed (only this repair's change)
    dirty: int = 0                   # files holding someone else's uncommitted change: skipped
    written: int = 0
    committed: bool = False
    _moves: dict[str, str | None] = field(default_factory=dict, repr=False)   # look id -> page id (None: clear)
    _unplaced: list[dict] = field(default_factory=list, repr=False)          # [{id, site, why}]
    _pages: dict[str, str] = field(default_factory=dict, repr=False)         # page id -> its text when surveyed
    _records: dict[str, str] = field(default_factory=dict, repr=False)       # look id -> its record text
    _adopt: list[str] = field(default_factory=list, repr=False)              # rel paths to commit as they are

    def counts(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}

    def listing(self) -> dict:
        """For the person's own terminal only (look ids carry site names): what stays unattached and why."""
        return {"unattached": self._unplaced, "moves": self._moves}


def _dirty(memory_path: Path, strict: bool) -> frozenset[str]:
    if not (memory_path / ".git").exists():
        return frozenset()
    try:
        return git_service.dirty_paths_sync(memory_path, "entities", design_refs.DESIGN_DIR)
    except git_service.GitError as exc:
        if strict:   # an apply never treats a file it cannot check as clean
            raise Refused(f"git could not say which files hold uncommitted changes: {type(exc).__name__}") from exc
        return frozenset()


def _head(memory_path: Path, rel: str) -> str | None:
    try:
        return git_service._git_sync(memory_path, "show", f"HEAD:{rel}")
    except git_service.GitError:
        return None


def _split(text: str) -> tuple[dict, str] | None:
    parts = markdown_parser.split_frontmatter(text)
    if not parts:
        return None
    try:
        fm = markdown_parser.load_yaml(parts[0])
    except Exception:  # noqa: BLE001 — a hand-broken file is never ours
        return None
    return (fm, parts[1]) if isinstance(fm, dict) else None


def _record_ours(memory_path: Path, rel: str, text: str) -> bool:
    """A dirty record whose only change from HEAD is its ``entity:`` (this repair's move)."""
    head = _head(memory_path, rel)
    now, then = _split(text), _split(head) if head is not None else None
    if now is None or then is None or now[1].strip() != then[1].strip():
        return False
    strip = lambda fm: {k: v for k, v in fm.items() if k != "entity"}  # noqa: E731
    return strip(now[0]) == strip(then[0])


def _without_looks(body: str) -> str:
    prose, rest = page_edits.split_prose(body)
    return design_refs.with_section(prose, "").strip() + "\n" + rest.strip()


def _page_ours(memory_path: Path, rel: str, text: str) -> bool:
    """A dirty page whose only change from HEAD is its ``## Looks`` section (this repair's write)."""
    head = _head(memory_path, rel)
    now, then = _split(text), _split(head) if head is not None else None
    if now is None or then is None or now[0] != then[0]:
        return False
    return _without_looks(now[1]) == _without_looks(then[1])


def survey(memory_path, *, strict: bool = False) -> Survey:
    """What :func:`apply` would do, read-only. ``strict`` (the apply's own survey) raises :class:`Refused` when git
    cannot list the dirty files, instead of treating every file as clean."""
    memory_path = Path(memory_path)
    out = Survey()
    dirty = _dirty(memory_path, strict)
    refs = design_refs.list_refs(memory_path)
    out.looks = len(refs)
    pages = [(f.stem, f.frontmatter or {}) for f in bank_index.files(memory_path, "entities")]
    placed: dict[str, str | None] = {}
    for ref in refs:
        rel = ref.path
        text = (memory_path / rel).read_text(encoding="utf-8")
        out._records[ref.id] = text
        held = rel in dirty
        if held and not _record_ours(memory_path, rel, text):
            out.dirty += 1                       # someone else's change: the look stays exactly as it is
            placed[ref.id] = ref.entity if design_refs.page_exists(memory_path, ref.entity) else None
            continue
        if held:
            out.adopted += 1
            out._adopt.append(rel)
        if ref.entity and design_refs.page_exists(memory_path, ref.entity):
            out.on_page += 1
            placed[ref.id] = ref.entity
            continue
        if ref.entity:
            out.page_gone += 1
        target, how = design_refs.subject_for(memory_path, ref.url, pages=pages)
        placed[ref.id] = target
        if target is None:
            if how == "ambiguous":
                out.ambiguous += 1
            else:
                out.unattached += 1
            out._unplaced.append({"id": ref.id, "site": ref.site, "why": how})
            if ref.entity:
                out._moves[ref.id] = None        # the page it named is gone: the stale entity is cleared
            continue
        out._moves[ref.id] = target
        if how == "site":
            out.by_site += 1
        else:
            out.by_link += 1
    by_page: dict[str, list] = {}
    for ref in refs:
        if placed.get(ref.id):
            by_page.setdefault(placed[ref.id], []).append(ref)
    for eid in sorted(by_page):
        page = memory_path / "entities" / f"{eid}.md"
        rel = f"entities/{eid}.md"
        text = page.read_text(encoding="utf-8")
        if f"entities/{eid}.claims.jsonl" in dirty or (rel in dirty and not _page_ours(memory_path, rel, text)):
            out.dirty += 1                       # the page or its ledger holds someone else's change
            continue
        if rel in dirty:
            out.adopted += 1
            out._adopt.append(rel)
        prose, _ = page_edits.split_prose(markdown_parser.parse(page, ledger=False).body)
        if design_refs.with_section(prose, design_refs.page_section(by_page[eid])).rstrip() != prose.rstrip():
            out._pages[eid] = text
    out.pages_to_write = len(out._pages)
    return out


def _commit(memory_path: Path, rels: list[str], n: int, total: int) -> None:
    subject = f"Looks attached to their pages: {len(rels)} file(s)" + (f" (part {n} of {total})" if total > 1 else "")
    git_service.commit_paths_sync(memory_path, git_service.build_commit_message(
        subject, [f"{rel}: updated (trigger: {TRIGGER})" for rel in rels], authors=["cicada"]), rels)


def apply(memory_path, *, sleep_running: Callable[[], bool]) -> Survey:
    """Write the survey's moves and sections and commit them :data:`COMMIT_STEP` paths at a time, authored ``cicada``
    (a page and the looks moving onto it in one step). Raises :class:`SleepRunning` before writing anything when Sleep
    holds the pages or a run is in progress, :class:`Refused` when git cannot be asked."""
    memory_path = Path(memory_path)
    has_git = (memory_path / ".git").exists()
    with write_admission.admitted(memory_path, refuse=lambda: SleepRunning("Sleep is holding this bank's pages")):
        if sleep_running():
            raise SleepRunning("a Sleep run is in progress; attach the looks after it ends")
        with page_lock.page_lock(memory_path):
            result = survey(memory_path, strict=True)
            # Steps: what an interrupted run left (as it is), then each page with the looks moving onto it, then the
            # looks whose stale page is cleared.
            steps: list[list[tuple[str, str]]] = [[("adopt", rel)] for rel in result._adopt]
            onto: dict[str | None, list[str]] = {}
            for ref_id, eid in result._moves.items():
                onto.setdefault(eid, []).append(ref_id)
            for eid in sorted({*result._pages, *(e for e in onto if e)}):
                steps.append([("record", r) for r in onto.get(eid, [])] + ([("page", eid)] if eid in result._pages
                                                                             else []))
            steps += [[("record", r)] for r in onto.get(None, [])]
            chunks: list[list[tuple[str, str]]] = []
            for step in steps:
                if chunks and len(chunks[-1]) + len(step) <= COMMIT_STEP:
                    chunks[-1] += step
                else:
                    chunks.append(list(step))
            for n, chunk in enumerate(chunks, 1):
                rels: list[str] = []
                for kind, key in chunk:
                    if kind == "adopt":
                        rels.append(key)
                    elif kind == "record":
                        ref = design_refs.get_ref(memory_path, key)
                        path = memory_path / design_refs.DESIGN_DIR / f"{key}.md"
                        if ref is None or path.read_text(encoding="utf-8") != result._records.get(key):
                            result.dirty += 1    # written since the survey: its writer's to commit
                            continue
                        design_refs._set_entity(memory_path, ref, result._moves[key])
                        rels.append(ref.path)
                    else:
                        page = memory_path / "entities" / f"{key}.md"
                        if page.read_text(encoding="utf-8") != result._pages[key]:
                            result.dirty += 1
                            continue
                        if (rel := design_refs.sync_page(memory_path, key)) is not None:
                            rels.append(rel)
                rels = list(dict.fromkeys(rels))
                result.written += len([r for r in rels if r not in result._adopt])
                if rels and has_git:
                    _commit(memory_path, rels, n, len(chunks))
                    result.committed = True
    if result.written:
        logger.info(f"looks attach: {len(result._moves)} look(s) moved, {len(result._pages)} page(s) written")
    return result
