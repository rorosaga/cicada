"""Repair of the connector posts written as the person's own words (G245, owner 2026-11-24).

Until this change the X connector and the Pinterest connector wrote a post's text into the episode's person section,
``## User note``, and stamped the episode ``has_note`` — so Sleep read what a stranger wrote as something the person
said. New posts are written as the post's own description (``saved_reading``, ``connectors/x.py``,
``connectors/pinterest.py``). This module finds the episodes already written the old way and, when turned on, puts
them right: the heading becomes the post's description (``## Description``; ``## Post text`` where the episode already
holds a description of the linked page) and ``has_note`` goes. Nothing else changes — ``processed`` and
``processed_by`` stay, so an episode Sleep read stays read, and one still waiting becomes a bare save (index-only,
exactly like every other save) at the next ``history_index.retire``.

**On** (:data:`REPAIR`, the one constant, set to ``True`` with ruling 80's switch, owner 2026-11-24: every save is read).
It has to be on BEFORE saves are read, or a stranger's post written the old way would be read as the person's own words
on the first night; a bank with no such row (the author's, by a dry run) changes nothing. ``False`` counts what it would
change and changes nothing, and the dry run (``python -m api.scripts.connector_text_dry_run --bank <path>``: counts only,
never a word of a post) always does, whatever :data:`REPAIR` says.

* **Idempotent.** An episode is repaired only while it still carries the old shape (one ``## User note``, ``has_note``,
  no reason, no why-answer, no agent session); once healed it matches nothing, so a second run counts zero.
* **Never a revision.** The repair is committed by itself, before anything else this run commits, so ``HEAD`` holds the
  healed body with the episode's own ``processed_by``: a later wake diffs the body against that version and finds
  nothing changed (``episode_revision`` diffs against the version Sleep read, which is this one).
* **What Sleep already wrote stays.** The claims an earlier read made from such an episode rest on the old body and
  stay in git; their spans, judged on read, go stale rather than lying (``source_spans``). The report counts the
  pages and claims they sit on, so the person decides what to do about them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from api.services import saved_reading

#: The one switch. ``True`` (ruling 80: saves are read, so a post written as his words must be put right first);
#: ``False``: report only (count, change nothing).
REPAIR = True

USER_NOTE = "## User note"
DESCRIPTION = "## Description"
POST_TEXT = "## Post text"
TRIGGER = "sleep/connector-text"
AUTHOR = "cicada"
#: Sections or keys that say the person (or an agent) added something of their own: such an episode is never touched.
_THEIRS_KEYS = ("saved_why", "saved_why_earlier", "readable_by_folder", "session_id", "book")
_THEIRS_SECTIONS = ("## Saved because", "## Why it was saved", "## Note")


def _lines(body: str) -> list[str]:
    return [ln.strip() for ln in (body or "").splitlines()]


def old_shape(fm: dict | None, body: str) -> bool:
    """Is this episode a connector post written the old way: the post's text under the person's ``## User note``?"""
    if not isinstance(fm, dict) or str(fm.get("origin") or "") not in saved_reading.CONNECTOR_TEXT_ORIGINS:
        return False
    if not fm.get("has_note") or any(fm.get(k) for k in _THEIRS_KEYS):
        return False
    lines = _lines(body)
    return lines.count(USER_NOTE) == 1 and not any(h in lines for h in _THEIRS_SECTIONS)


def _healed(body: str) -> str:
    """``body`` with its one ``## User note`` heading renamed (the line's own spelling elsewhere is untouched)."""
    heading = POST_TEXT if DESCRIPTION in _lines(body) else DESCRIPTION
    out, done = [], False
    for line in (body or "").splitlines(keepends=True):
        if not done and line.strip() == USER_NOTE:
            out.append(line.replace(USER_NOTE, heading, 1))
            done = True
        else:
            out.append(line)
    return "".join(out)


@dataclass
class Repair:
    """What the repair found (and, when :data:`REPAIR` was on, changed). Counts and ids only — never a word of a post."""

    applied: bool = False
    #: memory-relative paths of the episodes written the old way
    paths: list[str] = field(default_factory=list)
    #: of those, how many Sleep (a model) already read as the person's words, how many wait, how many the index read
    read_by_sleep: int = 0
    waiting: int = 0
    indexed: int = 0
    by_origin: dict[str, int] = field(default_factory=dict)
    #: pages that cite such an episode, and the claims on them resting on one that are not the post's author's
    pages: int = 0
    claims: int = 0
    #: files this run rewrote (``0`` when report-only)
    changed: list[str] = field(default_factory=list)
    skipped_dirty: int = 0

    def counts(self) -> dict:
        return {"repair_on": self.applied, "found": len(self.paths), "read_by_sleep": self.read_by_sleep,
                "waiting": self.waiting, "indexed": self.indexed, "by_origin": dict(sorted(self.by_origin.items())),
                "pages_citing": self.pages, "claims_not_the_authors": self.claims, "changed": len(self.changed),
                "skipped_dirty": self.skipped_dirty}


def _claims_resting_on(memory_path: Path, ids: set[str]) -> tuple[int, int]:
    """``(pages, claims)``: pages whose frontmatter cites one of ``ids`` and, on them, claims resting on one whose
    observer is not an ``external:`` author. Read only; a malformed page counts nothing."""
    from api.services import bank_index, markdown_parser
    from api.services.claims import parse_claims

    pages = claims = 0
    for f in bank_index.files(memory_path, "entities"):
        cited = f.frontmatter.get("source_episodes") if isinstance(f.frontmatter, dict) else None
        if not isinstance(cited, list) or not ids.intersection(str(e) for e in cited):
            continue
        pages += 1
        try:
            parsed = markdown_parser.parse(f.path)
            for claim in parse_claims(parsed.body):
                if ids.intersection(claim.source_episodes or []) and not str(claim.observer or "").startswith("external:"):
                    claims += 1
        except Exception:  # noqa: BLE001 - one unreadable page costs its own count, never the report
            continue
    return pages, claims


def repair(memory_path: Path, *, apply: bool | None = None, skip: frozenset[str] = frozenset()) -> Repair:
    """Find the connector episodes written the old way and, when ``apply`` (default :data:`REPAIR`), rewrite them.
    Pure files: the caller commits ``changed``. ``skip``: memory-relative paths dirty in git before this ran (an
    uncommitted capture keeps its own author). Each file is re-read under the episode lock and rewritten only if it
    still has the old shape. Never raises into the caller beyond what a file error raises for one episode, which
    leaves that episode as it was."""
    from api.services import bank_index, episode_ids, markdown_parser

    memory_path = Path(memory_path)
    do = REPAIR if apply is None else apply
    out = Repair(applied=bool(do))
    episodes_dir = memory_path / "episodes"
    ids: set[str] = set()
    for f in bank_index.files(memory_path, "episodes"):
        fm = f.frontmatter or {}
        if str(fm.get("origin") or "") not in saved_reading.CONNECTOR_TEXT_ORIGINS or not fm.get("has_note"):
            continue   # cheap header test first: no body of any other episode is read
        rel = f"episodes/{f.path.name}"
        try:
            body = f.body()
        except Exception:  # noqa: BLE001
            continue
        if not old_shape(fm, body):
            continue
        if rel in skip:
            out.skipped_dirty += 1
            continue
        out.paths.append(rel)
        ids.add(str(fm.get("id") or f.path.stem))
        origin = str(fm.get("origin"))
        out.by_origin[origin] = out.by_origin.get(origin, 0) + 1
        if not fm.get("processed", False):
            out.waiting += 1
        elif str(fm.get("processed_by") or "") == "index":
            out.indexed += 1
        else:
            out.read_by_sleep += 1
        if not do:
            continue
        with episode_ids.episode_lock(episodes_dir):
            try:
                parsed = markdown_parser.parse(f.path)
                fm = dict(parsed.frontmatter)   # an episode: no page, no claims fence — nothing to refresh
                if not old_shape(fm, parsed.body):
                    continue
                fm.pop("has_note", None)
                markdown_parser.write(f.path, fm, _healed(parsed.body))
            except Exception as exc:  # noqa: BLE001 - one malformed file never stops the rest
                logger.warning(f"Connector text repair skipped one episode: {type(exc).__name__}")
                continue
        out.changed.append(rel)
    if ids:
        out.pages, out.claims = _claims_resting_on(memory_path, ids)
    return out


def commit_message(paths: list[str], day: str, *, part: int = 1, parts: int = 1) -> str:
    """``Connector posts' text is the post's <date>``: one manifest line per file, ``Cicada-Author: cicada``, no engine
    trailer (no model ran)."""
    from api.services import git_service

    suffix = f" (part {part} of {parts})" if parts > 1 else ""
    return git_service.build_commit_message(
        f"Connector posts' text is the post's, not the person's {day}{suffix}",
        [f"{p}: healed (source: n/a, trigger: {TRIGGER})" for p in paths],
        authors=[AUTHOR],
    )


__all__ = ["REPAIR", "Repair", "commit_message", "old_shape", "repair"]
