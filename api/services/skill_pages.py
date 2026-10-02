"""A page in the memory graph for an installed agent skill (G166, owner 2026-09-30).

The owner: "make sure to have this link to the skill in the memory graph and
label it as a skill accordingly." A skill the person chose in Settings, How your
agent reads (or added with "Add to your graph") becomes a ``type: skill`` page
tagged ``agent-skill`` (``skill_tag``), so it is a node they can open, that
recall can name, and that Stage 2 matches a later mention to (the page ``name`` is
the hyphenated upstream name, so ``fuzz.ratio`` clears its threshold).

**This module is the only writer**, and it runs only on the person's own action
(``routers/agent_methods.py``): no Sleep tail step, no seed at bank creation — a
skill page is never written for a tool the person did not choose. A grep-style
test keeps it that way.

* **Idempotent.** A page that carries the tag is ``exists``: nothing written,
  nothing committed, mtime untouched.
* **Adoption, when it is safe** (a page with the id already exists — Stage 1 often
  files the tool a person talks about as a ``tool`` or ``concept`` page). On the
  person's selection, a ``tool``/``concept``/``skill`` page that is not human-edited
  (``human_edited``, or a hand-added section) and has no ``picture:`` is retyped
  ``skill``, tagged, given the catalog ``sources:`` entry and pinned evergreen, in
  one ``user`` commit whose manifest reads ``updated``, keeping every claim and
  episode. Any other page is ``foreign``: left byte-identical, and the row links to it.
* **Refused, not skipped.** While Sleep is writing (the one shared predicate,
  ``sleep_cycle.is_writing``): ``busy``. A demo bank: ``demo``. A skill with no role
  or page name: ``none``. One ``asyncio.Lock`` per process.
* **Frontmatter is static.** Nothing machine-dependent (install state, the person's
  choice) is ever stored — it would be stale by the next click. ``human_edited: true``
  keeps a later Stage-1 mention additive-only (no LLM rewrite of the summary or the
  one Upstream link). ``decay_class: evergreen``: the anti-pollution rail reserves it
  for ingest writers and the user, and this writer runs on the user's action; the page
  describes an artifact the person chose, not a belief that goes stale.
* **No claims.** A claim would decay, could conflict and needs a predicate the
  vocabulary lacks; the page is a labelled pointer.
* **One commit over one path**, ``Cicada-Author: user``, trigger ``user/companion_app``;
  a failed commit is rolled back (tree and index) so nothing is swept into the next
  ``git add -A`` writer's commit under the wrong author.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from loguru import logger

from api.services import (
    decay_policy, demo_guard, entity_body, fact_sources, git_service, markdown_parser, skill_catalog,
)
from api.services.decay_policy import DecayClass
from api.services.id_utils import sanitize_id
from api.services.skill_tag import AGENT_SKILL_TAG, is_agent_skill

__all__ = ["AGENT_SKILL_TAG", "PageResult", "page_id", "lookup", "ensure"]

_LOCK = asyncio.Lock()
_ADOPTABLE_TYPES = frozenset({"tool", "concept", "skill"})


@dataclass(frozen=True)
class PageResult:
    state: str  # created | adopted | exists | foreign | busy | demo | none
    entity_id: str | None = None


def _entry(skill_id: str, catalog: dict | None) -> dict | None:
    catalog = catalog or skill_catalog.load()
    return next((e for e in catalog["skills"] if e.get("id") == skill_id and e.get("roles")
                 and (e.get("pageName") or e.get("invoke"))), None)


def page_id(entry: dict) -> str:
    return sanitize_id(entry.get("pageName") or entry.get("invoke") or entry["id"])


def _path(memory_path: Path, entity_id: str) -> Path:
    return Path(memory_path) / "entities" / f"{entity_id}.md"


def lookup(memory_path: Path, entry: dict) -> PageResult | None:
    """Read-only: ``exists`` (a tagged page), ``foreign`` (a page with that id that is not
    this writer's), or ``None`` — what ``GET /agent-methods`` reports per skill."""
    entity_id = page_id(entry)
    path = _path(memory_path, entity_id)
    if not path.is_file():
        return None
    try:
        fm = markdown_parser.parse(path).frontmatter or {}
    except Exception:  # noqa: BLE001
        return PageResult("foreign", entity_id)
    return PageResult("exists" if is_agent_skill(fm) else "foreign", entity_id)


def _sleep_writing() -> bool:
    from api.services import sleep_cycle

    return bool(sleep_cycle.is_writing())


def _adoptable(fm: dict, body: str) -> bool:
    from api.services import conflict_resolver

    if str(fm.get("type") or "") not in _ADOPTABLE_TYPES or fm.get("picture") or fm.get("owner"):
        return False
    try:
        sections = entity_body.parse_sections(body)
    except Exception:  # noqa: BLE001
        return False
    return not conflict_resolver._is_human_edited(fm, sections)


def _frontmatter(entry: dict, name: str, today: str) -> dict:
    return {
        "name": name,
        "type": "skill",
        "status": "active",
        "confidence": 1.0,
        "created": today,
        "last_referenced": today,
        "decayed_through": today,
        **decay_policy.frontmatter_fields(DecayClass.evergreen),
        "source_episodes": [],
        "tags": [AGENT_SKILL_TAG],
        "aliases": [a for a in {name.replace("-", " ")} if a != name],
        "related": [],
        "version": 1,
        "layout_version": 2,
        "human_edited": True,
    }


def _body(entry: dict) -> str:
    summary = (entry.get("pageSummary") or entry.get("summary") or "").strip()
    return entity_body.compose_body_v2(
        summary=summary, key_facts=[], history_entries=[], related=[],
        links=[{"title": "Upstream repository", "url": entry["sourceUrl"]}] if entry.get("sourceUrl") else [],
        open_questions=[])


def _rollback(memory_path: Path, rel: str, path: Path, original: bytes | None) -> None:
    """A failed commit must leave neither an untracked page nor a staged one behind (the picture
    writer's precedent): unstage under the bank's write lock, then restore or remove the file."""
    try:
        git_service.run_git_write_sync(memory_path, "reset", "-q", "--", rel)
    except Exception:  # noqa: BLE001
        pass
    try:
        if original is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(original)
    except OSError:
        pass


async def ensure(memory_path: Path, skill_id: str, *, catalog: dict | None = None,
                 today: date | None = None) -> PageResult:
    """The page for ``skill_id`` in this bank: create it, adopt an agent-made page, or report
    what stands in the way. Never raises for a policy reason; a commit failure is rolled back
    and raised as-is for the router to word."""
    memory_path = Path(memory_path)
    entry = _entry(skill_id, catalog)
    if entry is None:
        return PageResult("none")
    entity_id = page_id(entry)
    if demo_guard.is_demo(memory_path):
        return PageResult("demo", entity_id)
    async with _LOCK:
        path = _path(memory_path, entity_id)
        day = (today or date.today()).isoformat()
        existing = path.is_file()
        original = path.read_bytes() if existing else None
        if existing:
            parsed = markdown_parser.parse(path)
            fm = dict(parsed.frontmatter or {})
            if is_agent_skill(fm):
                return PageResult("exists", entity_id)
            if not _adoptable(fm, parsed.body):
                return PageResult("foreign", entity_id)
        if _sleep_writing():
            return PageResult("busy", entity_id)
        rel = f"entities/{entity_id}.md"
        if existing:
            fm["type"] = "skill"
            fm["tags"] = sorted({*(str(t) for t in (fm.get("tags") or [])), AGENT_SKILL_TAG})
            fm["human_edited"] = True
            fm.update(decay_policy.frontmatter_fields(DecayClass.evergreen))
            markdown_parser.write(path, fm, parsed.body)
            verb = "updated"
        else:
            name = str(entry.get("pageName") or entry.get("invoke") or entry["id"])
            markdown_parser.write(path, _frontmatter(entry, name, day), _body(entry))
            verb = "created"
        try:
            if entry.get("sourceUrl"):
                try:
                    fact_sources.add_source(memory_path, entity_id, entry["sourceUrl"], kind="url",
                                            added_by="cicada", added_at=day)
                except fact_sources.InvalidSource:
                    pass   # a removed key, a full page or a ref the scrub refuses: the page itself still lands
            message = git_service.build_commit_message(
                f"Skill page {entity_id} {day}",
                [f"{rel}: {verb} (trigger: user/companion_app)"], authors=["user"])
            await git_service.commit_paths(memory_path, message, [rel])
        except Exception:
            logger.warning("skill page write failed; rolled back")
            _rollback(memory_path, rel, path, original)
            raise
        return PageResult("adopted" if existing else "created", entity_id)
