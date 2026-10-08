"""Repair what Stage 4 and Stage 1 left before the G112/alias fix — run by the person, never automatically.

    api/.venv/bin/python -m api.scripts.repair_skills_aliases --bank <path>           # dry run: counts only
    api/.venv/bin/python -m api.scripts.repair_skills_aliases --bank <path> --apply   # one `cicada` commit

Two repairs, both deterministic (no model, no network), both counted without a page name or a word of the bank:

**Skill pages with no source.** The old Stage-4 writer created ``type: skill`` pages with ``source_episodes: []``.
Each such page was born in one Sleep batch commit, and that commit names the conversations the batch read (their
``episodes/`` files and the ``source:`` of its other lines). The skill was detected over exactly those. The repair
narrows them to the conversations in which the pages the skill's own text names came up — two of them together
when two or more of them came up in the batch, as Stage 4 now does (``skill_grounding``) — and writes ``source_episodes``, ``created``
(the earliest of their days), ``last_referenced`` (the latest) and ``related``. The silence clock is not moved:
``decayed_through`` keeps the day Cicada learned the skill, so an older ``last_referenced`` charges no back-dated
decay (TODO ruling 1). The body is not touched. A page whose batch or evidence cannot be found is counted and left
as it is: what to do with it (keep, archive) is the person's call, not this tool's.

**References Sleep recorded as aliases.** ``alias_policy.is_reference`` ("the lock", "this project") — removed only
when the page's git history PROVES Sleep wrote it: the commit that last added the alias is a Sleep cycle commit whose
body carries Sleep's own ``<page>: create (source: …`` line, so the page did not exist before Sleep wrote it and no
one else's edit can be in that version. Everything else stays (``alias_references_kept``):

* an alias first written by anything but a Sleep cycle — the person's inbox merge (which records the losing page's
  name), a hand edit committed on its own, a dedup, an agent — or never committed, or unreadable in the history;
* an alias added in a Sleep cycle commit that UPDATED the page or merely swept it up (``alias_references_unproven``,
  a subset of kept). A Sleep commit runs ``git add -A`` (``sleep_cycle._finalize``), so a page the person edited by
  hand and left uncommitted is committed under Sleep's subject; even Sleep's own update line cannot tell Sleep's
  merge from the person's edit of the same page in the same cycle (the precedent: ``claim_recovery`` excludes a hand
  edit a Sleep commit swept up). When both may have touched it, the alias stays.

Who added an alias is stored nowhere but git; a guess that deletes something the person typed is worse than one more
judge call. ``--list`` prints, for the person's own terminal, each page id with the aliases ``--apply`` would remove
(``removals``) and the unproven ones it keeps (``unproven``, for the person to remove by hand if they agree) — never
paste it into the repo or a PR.

An alias that is another page's name is COUNTED only (``alias_names_other_page``) — it may be a wrong alias or the
lead for a merge, and only the person can tell.

Refuses like the claims-fence conversion (``api.scripts.migrate_claims_jsonl``): while Sleep holds the pages or the
backend cannot say clearly that no run is in progress; a page with uncommitted changes, or written after the survey, is skipped. Order: write admission →
page lock → git.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from loguru import logger

from api.services import (
    alias_policy, claims, episode_time, git_service, markdown_parser, page_lock, write_admission,
)
from api.services.skill_tag import is_agent_skill

TRIGGER = "maintenance/skill-provenance"
_EP_RE = re.compile(r"\bep_\d{4}-\d{2}-\d{2}_\d+\b")
#: A name shorter than this is too common a word to count as the skill naming a page.
MIN_NAME_CHARS = 3


class SleepRunning(RuntimeError):
    """Sleep holds this bank's pages, or a run is in progress: repair nothing."""


@dataclass
class Survey:
    """Counts only — never a name, a path or a word of the bank."""

    pages: int = 0
    skill_pages: int = 0
    skill_unsourced: int = 0
    skill_groundable: int = 0
    skill_no_batch: int = 0
    skill_no_evidence: int = 0
    alias_pages: int = 0
    alias_references: int = 0
    alias_references_kept: int = 0
    alias_references_unproven: int = 0
    alias_names_other_page: int = 0
    dirty: int = 0
    repaired: int = 0
    committed: bool = False
    _todo: dict[Path, tuple[str, dict]] = field(default_factory=dict, repr=False)
    _removals: dict[str, list[str]] = field(default_factory=dict, repr=False)
    _unproven: dict[str, list[str]] = field(default_factory=dict, repr=False)

    def counts(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}


def _batch_episodes(memory_path: Path, rel: str) -> set[str]:
    """The conversations of the Sleep commit that created ``rel`` (its oldest add), or an empty set."""
    try:
        shas = git_service._git_sync(memory_path, "log", "--diff-filter=A", "--format=%H", "--", rel).split()
        if not shas:
            return set()
        shown = git_service._git_sync(memory_path, "show", "--name-only", "--format=%B", shas[-1])
    except git_service.GitError:
        return set()
    return {ep for ep in _EP_RE.findall(shown) if (memory_path / "episodes" / f"{ep}.md").is_file()}


def _sleep_created(body: str, rel: str) -> bool:
    """Does this Sleep commit's body carry Sleep's OWN create line for ``rel`` (``sleep_cycle._finalize``:
    ``<path>: create (source: …``)? A page a Sleep commit merely swept up with ``git add -A`` gets a porcelain line
    without ``source:``, and an update line cannot tell Sleep's merge from the person's uncommitted edit of the same
    page in the same cycle."""
    prefix = f"{rel}: create (source: "
    return any(line.strip().startswith(prefix) for line in body.splitlines())


def _sleep_added(memory_path: Path, rel: str, candidates: list[str]) -> tuple[set[str], set[str]]:
    """``(proven, unproven)`` among ``candidates`` still on ``rel``, by the commit that last ADDED each (absent before
    it, listed after it). Proven: that commit is a Sleep cycle that CREATED the page — the page did not exist before
    Sleep wrote it, so nobody else's edit can be in it. Unproven: a Sleep cycle commit that updated or swept up the
    page — the person may have typed the alias and Sleep's ``git add -A`` committed it. Anything else (a person's
    merge, a hand edit committed on its own, an agent, never committed, unreadable) is neither: it is not Sleep's."""
    try:
        log = git_service._git_sync(memory_path, "log", "--reverse", "--format=%H%x1f%s%x1f%B%x1e", "--", rel)
    except git_service.GitError:
        return set(), set()
    keys = {c.lower(): c for c in candidates}
    adder: dict[str, str] = {}           # alias -> "proven" | "unproven" | "other", for its LATEST addition
    before: set[str] = set()
    for record in log.split("\x1e"):
        parts = record.strip("\n").split("\x1f", 2)
        if len(parts) != 3:
            continue
        sha, subject, body = parts
        try:
            split = markdown_parser.split_frontmatter(git_service._git_sync(memory_path, "show", f"{sha}:{rel}"))
            listed = (markdown_parser.load_yaml(split[0]) or {}).get("aliases") if split else None
        except Exception:
            listed = None   # deleted or unreadable at this commit: nothing is listed
        now = {str(a).lower() for a in listed} if isinstance(listed, list) else set()
        for key in keys:
            if key in now and key not in before:
                if git_service._cycle_kind(subject) != "sleep":
                    adder[key] = "other"
                else:
                    adder[key] = "proven" if _sleep_created(body, rel) else "unproven"
        before = now
    current = {k: v for k, v in adder.items() if k in before}
    return ({keys[k] for k, v in current.items() if v == "proven"},
            {keys[k] for k, v in current.items() if v == "unproven"})


def _named(text: str, labels: list[str]) -> bool:
    folded = text.lower()
    for label in labels:
        label = label.strip().lower()
        if len(label) >= MIN_NAME_CHARS and re.search(rf"(?<!\w){re.escape(label)}(?!\w)", folded):
            return True
    return False


def _episode_day(memory_path: Path, ep_id: str) -> str | None:
    try:
        fm = markdown_parser.parse(memory_path / "episodes" / f"{ep_id}.md").frontmatter or {}
    except Exception:
        return None
    if not episode_time.counts_as_activity(fm):
        return None
    stamp = str(fm.get("timestamp") or "")[:10]
    return stamp if re.fullmatch(r"\d{4}-\d{2}-\d{2}", stamp) else None


def _ground_skill(memory_path: Path, rel: str, fm: dict, body: str, pages: dict[str, tuple[dict, str]],
                  result: Survey) -> dict | None:
    batch = _batch_episodes(memory_path, rel)
    if not batch:
        result.skill_no_batch += 1
        return None
    stem = Path(rel).stem
    text = f"{fm.get('name') or ''}\n{claims.strip_claims_block(body)}"
    support: dict[str, int] = {}
    evidence: list[str] = []
    for other, (ofm, _body) in pages.items():
        if other == stem or str(ofm.get("type") or "") == "skill":
            continue
        eps = set(ofm.get("source_episodes") or []) & batch
        labels = [str(ofm.get("name") or ""), *alias_policy.keep(ofm.get("aliases"))]
        if eps and _named(text, labels):
            evidence.append(other)
            for ep in eps:
                support[ep] = support.get(ep, 0) + 1
    need = min(2, len(evidence))
    chosen = sorted(ep for ep, n in support.items() if need and n >= need)
    if not chosen:
        result.skill_no_evidence += 1
        return None
    new = dict(fm)
    new["source_episodes"] = chosen
    new["related"] = sorted(set(fm.get("related") or []) | set(evidence))
    days = sorted(d for d in (_episode_day(memory_path, ep) for ep in chosen) if d)
    if days:
        # The clock of silence stays where Cicada learned the skill; only the mention's date moves.
        learned = str(fm.get("decayed_through") or fm.get("last_referenced") or "")[:10]
        if learned:
            new["decayed_through"] = learned
        new["created"] = min(days[0], str(fm.get("created") or days[0])[:10])
        new["last_referenced"] = days[-1]
    return new


def survey(memory_path) -> Survey:
    """What ``apply`` would do, read-only."""
    memory_path = Path(memory_path)
    result = Survey()
    dirty: frozenset[str] = frozenset()
    has_git = (memory_path / ".git").exists()
    if has_git:
        try:
            dirty = git_service.dirty_paths_sync(memory_path, "entities")
        except git_service.GitError:
            dirty = frozenset()
    pages: dict[str, tuple[dict, str]] = {}
    texts: dict[str, str] = {}
    for path in sorted((memory_path / "entities").glob("*.md")):
        try:
            parsed = markdown_parser.parse(path)
        except Exception:
            continue
        pages[path.stem] = (dict(parsed.frontmatter or {}), parsed.body)
        texts[path.stem] = path.read_text(encoding="utf-8")
    names = {str(fm.get("name") or "").strip().lower(): stem for stem, (fm, _b) in pages.items()}
    names.update({stem.replace("-", " "): stem for stem in pages})

    for stem, (fm, body) in pages.items():
        result.pages += 1
        rel = f"entities/{stem}.md"
        new = dict(fm)
        changed = False

        aliases = fm.get("aliases")
        if isinstance(aliases, list) and aliases:
            for alias in alias_policy.keep(aliases):
                if names.get(alias.strip().lower(), stem) != stem:
                    result.alias_names_other_page += 1
            references = [a for a in aliases if isinstance(a, str) and alias_policy.is_reference(a)]
            by_sleep, unproven = (_sleep_added(memory_path, rel, references) if references and has_git
                                  else (set(), set()))
            result.alias_references_kept += len(references) - len(by_sleep)
            result.alias_references_unproven += len(unproven)
            if unproven:
                result._unproven[stem] = sorted(unproven)
            if by_sleep:
                result.alias_pages += 1
                result.alias_references += len(by_sleep)
                new["aliases"] = [a for a in aliases if a not in by_sleep]
                result._removals[stem] = sorted(by_sleep)
                changed = True

        if str(fm.get("type") or "") == "skill" and not is_agent_skill(fm):
            result.skill_pages += 1
            if not fm.get("source_episodes"):
                result.skill_unsourced += 1
                grounded = _ground_skill(memory_path, rel, new, body, pages, result) if has_git else None
                if not has_git:
                    result.skill_no_batch += 1
                if grounded is not None:
                    result.skill_groundable += 1
                    new = grounded
                    changed = True

        if changed:
            if rel in dirty:
                result.dirty += 1
                continue
            result._todo[memory_path / rel] = (texts[stem], new)
    return result


def apply(memory_path, *, sleep_running: Callable[[], bool]) -> Survey:
    """Write every repair the survey found and commit them in ONE commit authored ``cicada``. Raises
    :class:`SleepRunning` before writing anything when Sleep holds the pages or a run is in progress."""
    memory_path = Path(memory_path)
    written: list[tuple[Path, str]] = []
    with write_admission.admitted(memory_path, refuse=lambda: SleepRunning("Sleep is holding this bank's pages")):
        if sleep_running():
            raise SleepRunning("a Sleep run is in progress; repair after it ends")
        with page_lock.page_lock(memory_path):
            result = survey(memory_path)
            for path, (surveyed, new_fm) in result._todo.items():
                if path.read_text(encoding="utf-8") != surveyed:   # written since the survey: its writer's to commit
                    result.dirty += 1
                    continue
                parsed = markdown_parser.parse(path)
                markdown_parser.write(path, new_fm, parsed.body)
                written.append((path, path.read_text(encoding="utf-8")))
            changed = [p for p, text in written if p.read_text(encoding="utf-8") != text]
            result.dirty += len(changed)
            rels = [f"entities/{p.name}" for p, _ in written if p not in changed]
            result.repaired = len(rels)
            if rels and (memory_path / ".git").exists():
                message = git_service.build_commit_message(
                    f"Skill sources and aliases repaired: {len(rels)} page(s)",
                    [f"{rel}: repaired (trigger: {TRIGGER})" for rel in rels],
                    authors=["cicada"],
                )
                git_service.commit_paths_sync(memory_path, message, rels)
                result.committed = True
    if written:
        logger.info(f"skill/alias repair: {len(written)} page(s)")
    return result
