"""Page quality on an existing bank — a survey of counts, and a prose repair the person runs.

Pages written before the 2026-10-09 page-quality fix carry what the old writers
left (`docs/architecture/capture-and-sleep.md`, *Page quality*): a Summary glued
from several conversations' orientations, a fallback Summary that says the
person's role "is not established" beside Key Facts that establish it,
"Undated background:" History bullets that repeat a Key Fact, facts that only
say the thing came up in a conversation, and pages that rest on one
conversation that the measured promotion bar would not have written.

:func:`survey` counts all of it, read-only, never a name or a word of the bank.
:func:`apply` repairs only what the Sleep writer would now write on the page's
next update, on machine pages (never one with human prose, `entity_body
.has_human_prose`), and only losslessly:

* an "Undated background:" bullet leaves History; what it says that the page
  does not becomes a Key Fact (`entity_body.retain_orientation`);
* a Summary over the budget, or one that re-introduces the thing, keeps its
  leading whole sentences and moves the rest to Key Facts (`entity_body
  .bound_summary`);
* the fallback's "Its present role for the owner is not established." clause
  is dropped (`summary_policy.fallback`);
* a fact that only says the thing came up in a conversation is dropped
  (`fact_policy.about_the_conversation`) — the page's sources already say so.

Never repaired, only counted (owner decisions): near-duplicate facts already
on a page (removing one rewrites text the page holds), facts phrased as what
the assistant said, and the one-conversation pages below the bar (archiving
them is a separate, explicit decision). Refused while Sleep runs; a page
written since the survey or dirty in git is skipped; one `cicada` commit.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from loguru import logger

from api.services import (
    claims, entity_body, evidence, fact_policy, git_service, markdown_parser, page_lock, promotion,
    section_provenance, summary_policy, write_admission,
)

TRIGGER = "maintenance/page-quality"
_FALLBACK_CLAUSE = " Its present role for the owner is not established."
_BACKGROUND = "Undated background: "
_ASSISTANT = re.compile(r"\b(?:the )?assistant (?:suggested|recommended|said|described|explained|proposed)"
                        r"|\bwas described as\b", re.I)


class SleepRunning(RuntimeError):
    """Sleep holds this bank's pages, or a run is in progress: repair nothing."""


@dataclass
class Survey:
    """Counts only — never a name, a path or a word of the bank."""

    pages: int = 0
    human_pages: int = 0
    one_conversation: int = 0
    one_conversation_clears_by_exchanges: int = 0
    one_conversation_clears_by_link: int = 0
    one_conversation_below_bar: int = 0
    one_conversation_unreadable: int = 0
    # Which of the old proxies would have let each one-conversation page through (not exclusive; approximate:
    # read back from what the page kept — its confidence, Summary length, History bullets and claims).
    old_rung_confident_long: int = 0
    old_rung_two_history: int = 0
    old_rung_two_relationships: int = 0
    old_rung_any_link: int = 0
    summary_glued: int = 0
    summary_over_budget: int = 0
    summary_fallback_clause: int = 0
    background_bullets: int = 0
    background_restated: int = 0
    background_to_facts: int = 0
    facts: int = 0
    facts_about_the_conversation: int = 0
    facts_restated_on_page: int = 0
    facts_assistant_phrased: int = 0
    skipped_free_prose: int = 0
    pages_to_repair: int = 0
    dirty: int = 0
    repaired: int = 0
    committed: bool = False
    _todo: dict[Path, tuple[str, dict, str]] = field(default_factory=dict, repr=False)

    def counts(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}


def _clears_bar(memory_path: Path, fm: dict, body: str, owner_ids: set[str], pages: dict) -> tuple[str | None, bool]:
    """``(rung, readable)`` for a one-conversation page: ``"exchanges"`` or ``"link"`` when the
    measured bar (`promotion`) is met on its conversation, ``None`` when it is not."""
    episodes = [str(e) for e in fm.get("source_episodes") or [] if e]
    if not episodes:
        return None, False
    path = evidence.source_path(memory_path, episodes[0])
    if path is None or not path.is_file():
        return None, False
    try:
        episode = markdown_parser.parse(path)
    except Exception:
        return None, False
    text = claims.strip_claims_block(episode.body)
    units = promotion.exchanges(text, override=str(episode.frontmatter.get("evidence_kind") or "") or None,
                                gaps=evidence.gap_ranges(episode.frontmatter, text))
    exchanges, named = promotion.measure(
        {"name": fm.get("name"), "aliases": fm.get("aliases") or [], "type": fm.get("type")}, units)
    if exchanges > promotion.MIN_EXCHANGES and named:
        return "exchanges", True
    for claim in claims.parse_claims(body):
        other = claim.object if claim.object_kind == "node" else None
        partner = pages.get(other or "")
        if not partner or other in owner_ids or float(partner.get("confidence", 0) or 0) < 0.6:
            continue
        if promotion.person_said({"evidence": [e.to_dict() for e in claim.evidence]}):
            return "link", True
    return None, True


def _old_rungs(stem: str, fm: dict, body: str, owner_ids: set[str], pages: dict, result: Survey) -> None:
    """Count the pre-2026-10-09 proxies a one-conversation page clears, from what it kept."""
    sections = entity_body.parse_sections(claims.strip_claims_block(body))
    if float(fm.get("confidence", 0) or 0) >= 0.75 and len(sections.get("Summary", "")) >= 200:
        result.old_rung_confident_long += 1
    if sum(1 for h in entity_body._bullet_lines(sections.get("History", "")) if h[:4].isdigit()) >= 2:
        result.old_rung_two_history += 1
    episode = str((fm.get("source_episodes") or [""])[0])
    mine = [c for c in claims.parse_claims(body) if stem in (c.subject, c.object)
            and (not episode or episode in (c.source_episodes or []))]
    if len(mine) >= 2:
        result.old_rung_two_relationships += 1
    for claim in mine:
        other = claim.object if claim.subject == stem else claim.subject
        partner = pages.get(other or "")
        if partner and other not in owner_ids and float(partner.get("confidence", 0) or 0) >= 0.6:
            result.old_rung_any_link += 1
            break


def _repair(fm: dict, body: str, result: Survey) -> str:
    """The repaired body (equal to ``body`` when nothing changes), counting as it goes."""
    prose = claims.strip_claims_block(body)
    sections = entity_body.parse_sections(prose)
    name, kind = str(fm.get("name") or ""), str(fm.get("type") or "")
    summary = sections.get("Summary", "")

    if summary.endswith(_FALLBACK_CLAUSE):
        result.summary_fallback_clause += 1
        sections["Summary"] = summary[: -len(_FALLBACK_CLAUSE)]
    facts = entity_body._bullet_lines(sections.get("Key Facts", ""))
    result.facts += len(facts)
    result.facts_assistant_phrased += sum(bool(_ASSISTANT.search(f)) for f in facts)
    result.facts_restated_on_page += sum(
        1 for i, f in enumerate(facts) if fact_policy.covered(f, facts[:i] + facts[i + 1:]))
    narration = [f for f in facts if fact_policy.about_the_conversation(f)]
    if narration:
        result.facts_about_the_conversation += len(narration)
        kept = [f for f in facts if f not in narration]
        if kept:
            sections["Key Facts"] = entity_body._bullets_block(kept)
        else:
            sections.pop("Key Facts", None)

    history = entity_body._bullet_lines(sections.get("History", ""))
    background = [h for h in history if h.startswith(_BACKGROUND)]
    if background:
        result.background_bullets += len(background)
        rest = [h for h in history if not h.startswith(_BACKGROUND)]
        if rest:
            sections["History"] = entity_body._bullets_block(rest)
        else:
            sections.pop("History", None)
        for bullet in background:
            text = bullet[len(_BACKGROUND):].replace("\n  ", "\n")
            added = entity_body.retain_orientation(sections, text)
            result.background_to_facts += added
            result.background_restated += int(added == 0)

    current = sections.get("Summary", "")
    if current:
        kept, _rest = entity_body.lead(current, names=[name, *(fm.get("aliases") or [])])
        if not summary_policy.usable(current):
            result.summary_over_budget += 1
        elif kept and kept != " ".join(current.split()):
            result.summary_glued += 1
        sections = entity_body.bound_summary(sections, name=name, entity_type=kind,
                                             names=[str(a) for a in fm.get("aliases") or []])
    new_prose = entity_body.render_sections(sections)
    if new_prose == entity_body.render_sections(entity_body.parse_sections(prose)):
        return body
    return claims.preserve_claims_blocks(body, new_prose)


def survey(memory_path) -> Survey:
    """What :func:`apply` would do, and the counts it never acts on. Read-only."""
    memory_path = Path(memory_path)
    result = Survey()
    dirty: frozenset[str] = frozenset()
    if (memory_path / ".git").exists():
        try:
            dirty = git_service.dirty_paths_sync(memory_path, "entities")
        except git_service.GitError:
            dirty = frozenset()
    pages: dict[str, tuple[dict, str, str]] = {}
    for path in sorted((memory_path / "entities").glob("*.md")):
        try:
            parsed = markdown_parser.parse(path)
        except Exception:
            continue
        pages[path.stem] = (dict(parsed.frontmatter or {}), parsed.body, path.read_text(encoding="utf-8"))
    frontmatters = {stem: fm for stem, (fm, _b, _t) in pages.items()}
    owner_ids = {stem for stem, fm in frontmatters.items() if fm.get("owner") is True}

    for stem, (fm, body, text) in pages.items():
        if str(fm.get("status") or "active") in ("archived", "dropped"):
            continue
        result.pages += 1
        if stem not in owner_ids and len(fm.get("source_episodes") or []) <= 1 and fm.get("type") != "media":
            result.one_conversation += 1
            _old_rungs(stem, fm, body, owner_ids, frontmatters, result)
            rung, readable = _clears_bar(memory_path, fm, body, owner_ids, frontmatters)
            if not readable:
                result.one_conversation_unreadable += 1
            elif rung == "exchanges":
                result.one_conversation_clears_by_exchanges += 1
            elif rung == "link":
                result.one_conversation_clears_by_link += 1
            else:
                result.one_conversation_below_bar += 1
        prose = claims.strip_claims_block(body)
        sections = entity_body.parse_sections(prose)
        if entity_body.has_human_prose(fm, sections):
            result.human_pages += 1
            continue
        if any(line.strip() and not line[:1].isspace() and not line.startswith(("- ", "* "))
               for title in ("Key Facts", "History") for line in sections.get(title, "").splitlines()):
            # Free prose a legacy writer left in a list section: rebuilding the list would lose it.
            result.skipped_free_prose += 1
            continue
        repaired = _repair(fm, body, result)
        if repaired != body:
            result.pages_to_repair += 1
            rel = f"entities/{stem}.md"
            if rel in dirty:
                result.dirty += 1
                continue
            result._todo[memory_path / rel] = (text, fm, repaired)
    return result


def apply(memory_path, *, sleep_running: Callable[[], bool]) -> Survey:
    """Write the survey's repairs and commit them in ONE commit authored ``cicada``. Raises
    :class:`SleepRunning` before writing anything when Sleep holds the pages or a run is in progress."""
    memory_path = Path(memory_path)
    written: list[tuple[Path, str]] = []
    with write_admission.admitted(memory_path, refuse=lambda: SleepRunning("Sleep is holding this bank's pages")):
        if sleep_running():
            raise SleepRunning("a Sleep run is in progress; repair after it ends")
        with page_lock.page_lock(memory_path):
            result = survey(memory_path)
            for path, (surveyed, fm, body) in result._todo.items():
                if path.read_text(encoding="utf-8") != surveyed:   # written since the survey: its writer's to commit
                    result.dirty += 1
                    continue
                original = markdown_parser.parse(path).body
                section_provenance.refresh(fm, original, body, {})
                markdown_parser.write(path, fm, body)
                written.append((path, path.read_text(encoding="utf-8")))
            rels = [f"entities/{p.name}" for p, _ in written]
            result.repaired = len(rels)
            if rels and (memory_path / ".git").exists():
                message = git_service.build_commit_message(
                    f"Page prose repaired: {len(rels)} page(s)",
                    [f"{rel}: repaired (trigger: {TRIGGER})" for rel in rels],
                    authors=["cicada"],
                )
                git_service.commit_paths_sync(memory_path, message, rels)
                result.committed = True
    if written:
        logger.info(f"page-quality repair: {len(written)} page(s)")
    return result
