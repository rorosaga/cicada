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
as it is — unless the person asks for the archive below.

**Archiving skill pages with no traceable conversation (owner ruling 2026-10-09)** — only with ``archive=True``
(``--archive-unsourced``), never by default. A skill page that stays unsourced after grounding is set to ``status:
archived`` — never deleted — when its git history PROVES it is the old Stage-4 writer's page that nobody else touched
(:func:`_stage4_untouched`):

* the commit that added it is a Sleep cycle commit, and the page it added has exactly the old writer's shape
  (``type: skill``, ``source_episodes``/``tags``/``related`` empty, ``created`` = ``last_referenced``, ``version: 1``,
  no other key but the decay class);
* every later commit that touched it is a Sleep commit carrying Sleep's own decay line for it
  (``<page>: … (source: n/a, trigger: sleep/decay``) — an inbox answer, an agent, a hand edit committed on its own,
  any other maintenance commit, or a Sleep commit that merely swept it up makes it unproven;
* and the page now differs from what was added only in what decay writes (``confidence``, ``status`` active or
  decaying, ``decayed_through``), body unchanged — a decay commit stages the whole file, so a hand edit it carried
  shows here.

Anything else is counted (``skill_archive_unproven``) and kept. Archived pages are skipped by decay, so no decay nudge
follows; the archive writes no inbox item.

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
ARCHIVE_TRIGGER = "maintenance/skill-archive"
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
    skill_archivable: int = 0
    skill_archive_unproven: int = 0
    alias_pages: int = 0
    alias_references: int = 0
    alias_references_kept: int = 0
    alias_references_unproven: int = 0
    alias_names_other_page: int = 0
    dirty: int = 0
    repaired: int = 0
    archived: int = 0
    committed: bool = False
    _todo: dict[Path, tuple[str, dict]] = field(default_factory=dict, repr=False)
    _archive: list[str] = field(default_factory=list, repr=False)
    _archive_unproven: list[str] = field(default_factory=list, repr=False)
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


#: The frontmatter the old Stage-4 writer stamped on every skill page (``inbox_generator`` before #251); the decay
#: class pair joined it with G66.
_STAGE4_KEYS = frozenset({"name", "type", "status", "confidence", "created", "last_referenced", "source_episodes",
                          "tags", "related", "version"})
_STAGE4_OPTIONAL = frozenset({"decay_class", "decay_rate"})
#: What Sleep's decay writes on a page (``conflict_resolver.apply_changes``, the decay branch).
_DECAY_KEYS = frozenset({"confidence", "status", "decayed_through"})


def _stage4_shape(fm: dict) -> bool:
    keys = set(fm)
    return (_STAGE4_KEYS <= keys <= _STAGE4_KEYS | _STAGE4_OPTIONAL and fm.get("type") == "skill"
            and fm.get("status") == "active" and fm.get("version") == 1
            and not fm.get("source_episodes") and not fm.get("tags") and not fm.get("related")
            and str(fm.get("created") or "") == str(fm.get("last_referenced") or "") != "")


def _decay_line(body: str, rel: str) -> bool:
    """Does this Sleep commit carry Sleep's own decay line for ``rel`` (``_finalize``: the decay commit's lines, or a
    decay change folded into the main commit)?"""
    prefix = f"{rel}: "
    return any(line.strip().startswith(prefix) and "(source: n/a, trigger: sleep/decay" in line
               for line in body.splitlines())


def _stage4_untouched(memory_path: Path, rel: str, fm: dict, body: str) -> bool:
    """True only when git PROVES ``rel`` is the old Stage-4 writer's page that no one but Sleep's decay has touched
    since (see the module docstring). Any doubt — no history, an unreadable version, a commit of anyone else — is
    False: the page is kept."""
    try:
        log = git_service._git_sync(memory_path, "log", "--reverse", "--format=%H%x1f%s%x1f%B%x1e", "--", rel)
    except git_service.GitError:
        return False
    records = [r.strip("\n").split("\x1f", 2) for r in log.split("\x1e") if r.strip()]
    if not records or any(len(r) != 3 for r in records):
        return False
    sha, subject, _body = records[0]
    if git_service._cycle_kind(subject) != "sleep":
        return False
    try:
        split = markdown_parser.split_frontmatter(git_service._git_sync(memory_path, "show", f"{sha}:{rel}"))
        added = markdown_parser.load_yaml(split[0]) if split else None
    except Exception:
        return False
    if not isinstance(added, dict) or not _stage4_shape(added):
        return False
    for _sha, subject, commit_body in records[1:]:
        if git_service._cycle_kind(subject) not in ("sleep", "decay") or not _decay_line(commit_body, rel):
            return False
    if split[1].strip() != body.strip() or str(fm.get("status") or "") not in ("active", "decaying"):
        return False
    keys = set(fm) | set(added)
    return all(fm.get(k) == added.get(k) for k in keys - _DECAY_KEYS)


def survey(memory_path, *, archive: bool = False) -> Survey:
    """What ``apply`` would do, read-only. ``archive``: also archive the skill pages that stay unsourced and that git
    proves are the old Stage-4 writer's, untouched (``skill_archivable``); without it they are only counted."""
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
                elif str(fm.get("status") or "active") in ("archived", "dropped"):
                    pass   # already out of the way
                elif has_git and _stage4_untouched(memory_path, rel, fm, body):
                    result.skill_archivable += 1
                    result._archive.append(stem)
                    if archive:
                        new["status"] = "archived"
                        changed = True
                else:
                    result.skill_archive_unproven += 1
                    result._archive_unproven.append(stem)

        if changed:
            if rel in dirty:
                result.dirty += 1
                continue
            result._todo[memory_path / rel] = (texts[stem], new)
    return result


def apply(memory_path, *, sleep_running: Callable[[], bool], archive: bool = False) -> Survey:
    """Write every repair the survey found and commit them in ONE commit authored ``cicada``; with ``archive``, the
    provable unsourced Stage-4 skill pages are archived in the same commit. Raises :class:`SleepRunning` before
    writing anything when Sleep holds the pages or a run is in progress."""
    memory_path = Path(memory_path)
    written: list[tuple[Path, str]] = []
    with write_admission.admitted(memory_path, refuse=lambda: SleepRunning("Sleep is holding this bank's pages")):
        if sleep_running():
            raise SleepRunning("a Sleep run is in progress; repair after it ends")
        with page_lock.page_lock(memory_path):
            result = survey(memory_path, archive=archive)
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
            archived = {f"entities/{stem}.md" for stem in result._archive} if archive else set()
            result.archived = sum(1 for rel in rels if rel in archived)
            result.repaired = len(rels) - result.archived
            if rels and (memory_path / ".git").exists():
                parts = ([f"Skill sources and aliases repaired: {result.repaired} page(s)"] if result.repaired else [])
                if result.archived:
                    parts.append(f"{'u' if parts else 'U'}nsourced skill pages archived: {result.archived} page(s)")
                subject = "; ".join(parts)
                message = git_service.build_commit_message(
                    subject,
                    [f"{rel}: archived (trigger: {ARCHIVE_TRIGGER})" if rel in archived
                     else f"{rel}: repaired (trigger: {TRIGGER})" for rel in rels],
                    authors=["cicada"],
                )
                git_service.commit_paths_sync(memory_path, message, rels)
                result.committed = True
    if written:
        logger.info(f"skill/alias repair: {len(written)} page(s), {result.archived} archived")
    return result
