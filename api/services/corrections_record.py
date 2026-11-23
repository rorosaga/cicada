"""The Corrections record (G104 slice 3, T4, owner 2026-11-23): the person is told, not asked.

``revision_cascade`` and ``revision_prose`` change things when a conversation corrects itself. This module is the one
place that says *what*, in three forms that carry the same facts:

* a **batch entry** — one batch's cascade report plus the claim and passage counts, folded into the drain
  (``DrainState.corrections``) when the batch commits, and into the run's machine-local summary (``sleep_runs``, one
  ``corrections`` object a run with no revision never has) that ``GET /sleep/runs/{id}`` draws;
* **one dated History line** on each page a correction changed, naming the corrected conversation's id — never a second
  one for a page and conversation ``revision_prose`` already wrote a line for in the same batch;
* **two lines in the Sleep commit body** (``corrections: revised ep_…``, ``corrections: archived <page>``): ids only,
  shaped so no manifest parser reads them as a file.

Ids, counts and enums only — never a title, an alias, a held name or a claim's words (the run record, the commit body and
telemetry carry nothing else). ``None`` is "no revision", never a record of zeros."""
from __future__ import annotations

from pathlib import Path

from loguru import logger

from api.services import markdown_parser

#: A run's lists are bounded (they are ids; a long drain of edits must not grow ``runs.json`` without end).
MAX_LISTED = 200
#: How many ids a commit-body line names; the rest is a count.
MAX_IN_COMMIT = 30

_COUNTS = ("claims_withdrawn", "claims_superseded", "passages_rewritten", "aliases_dropped", "held_dropped",
           "questions_withdrawn")


def batch_entry(cascade: dict | None, *, withdrawn: int = 0, superseded: int = 0, rewritten: int = 0,
                revised_out: dict[str, str] | None = None) -> dict | None:
    """One batch's record, or ``None`` when no conversation was revised. ``cascade`` is ``Report.as_dict()``;
    ``withdrawn`` / ``superseded`` the claim pipeline's counts for the claims only the removed text said (closed with a
    record, replaced by the revision's own value); ``rewritten`` the passages ``revision_prose`` rewrote. A conversation
    that only replaced a claim's value counts as revised too (``revised_out``'s episodes)."""
    cascade = cascade or {}
    revised = sorted({*(cascade.get("revised") or []), *(revised_out or {}).values()})
    if not revised:
        return None
    held = cascade.get("held") or {}
    return {
        "revised": revised,
        "claims_withdrawn": int(withdrawn or 0),
        "claims_superseded": int(superseded or 0),
        "passages_rewritten": int(rewritten or 0),
        "pages_archived": [{"page": str(r["page"]), "episode": str(r["episode"])}
                           for r in cascade.get("pages_archived") or []],
        "pages_kept": [{"page": str(r["page"]), "episode": str(r["episode"]), "support": str(r.get("support") or "")}
                       for r in cascade.get("pages_kept") or []],
        "aliases_dropped": sum(int(r.get("count") or 0) for r in cascade.get("aliases_dropped") or []),
        "held_dropped": int(held.get("claims_dropped") or 0) + int(held.get("claims_withdrawn") or 0),
        "questions_withdrawn": len(cascade.get("questions") or []),
    }


def _union(a: list[dict], b: list[dict], key) -> list[dict]:
    seen: dict = {}
    for row in [*a, *b]:
        seen.setdefault(key(row), row)
    return list(seen.values())[:MAX_LISTED]


def merge(a: dict | None, b: dict | None) -> dict | None:
    """Two records as one: counts add, a conversation and a page are listed once. ``None`` is the identity."""
    if not a:
        return dict(b) if b else None
    if not b:
        return dict(a)
    out = {"revised": sorted({*a.get("revised", []), *b.get("revised", [])})[:MAX_LISTED]}
    for name in _COUNTS:
        out[name] = int(a.get(name) or 0) + int(b.get(name) or 0)
    out["pages_archived"] = _union(a.get("pages_archived") or [], b.get("pages_archived") or [], lambda r: r["page"])
    out["pages_kept"] = _union(a.get("pages_kept") or [], b.get("pages_kept") or [],
                               lambda r: (r["page"], r["episode"]))
    return out


def public(record: dict | None) -> dict | None:
    """The record as the run detail reads it: ``None`` unless a conversation was revised."""
    if not isinstance(record, dict) or not record.get("revised"):
        return None
    return record


# --------------------------------------------------------------------------- the commit body


def commit_lines(entry: dict | None) -> list[str]:
    """Two body lines for the batch's Sleep commit — the revised conversations and the archived pages. They have no
    ``(…)`` tail, so ``git_service``'s manifest reader skips them; the trailers stay the commit's last block."""
    if not entry:
        return []
    out: list[str] = []
    for label, ids in (("revised", entry.get("revised") or []),
                       ("archived", [r["page"] for r in entry.get("pages_archived") or []])):
        if not ids:
            continue
        more = len(ids) - MAX_IN_COMMIT
        out.append(f"corrections: {label} {', '.join(ids[:MAX_IN_COMMIT])}" + (f" (+{more} more)" if more > 0 else ""))
    return out


# --------------------------------------------------------------------------- History


def history_events(cascade: dict | None, *, skip: dict[str, set[str]] | None = None) -> dict[str, dict[str, list[str]]]:
    """``{page id: {episode: [History lines]}}`` for every page the cascade changed: archived, a kept page that lost
    claims, a page whose alias was dropped. ``skip`` is ``{page: {episodes}}`` that ``revision_prose`` already wrote a
    line for. Counts and the conversation id only — the page's own name is its page."""
    cascade = cascade or {}
    skip = skip or {}
    out: dict[str, dict[str, list[str]]] = {}

    def add(page: str, episode: str, line: str) -> None:
        if episode in skip.get(page, ()):
            return
        out.setdefault(page, {}).setdefault(episode, []).append(line)

    for r in cascade.get("pages_archived") or []:
        add(r["page"], r["episode"], f"Archived: the conversation it rested on ({r['episode']}) was corrected and no "
                                     "longer says it. Restoring it puts it back.")
    for r in cascade.get("pages_kept") or []:
        n = len(r.get("claims") or [])
        if n:
            add(r["page"], r["episode"], f"Conversation {r['episode']} was corrected: {n} claim(s) only it supported "
                                         "were closed. The page stays because something else supports it.")
    for r in cascade.get("aliases_dropped") or []:
        n = int(r.get("count") or 0)
        if n:
            add(r["page"], r["episode"], f"Conversation {r['episode']} was corrected: {n} alias(es) only it gave "
                                         "were dropped.")
    return out


def write_history(memory_path: Path, cascade: dict | None, *, today: str,
                  skip: dict[str, set[str]] | None = None, days: dict[str, str] | None = None) -> list[str]:
    """One dated History line per page and corrected conversation (:func:`history_events`), merged in place like
    ``revision_prose``'s (deduped, so a repeat writes nothing). Returns the memory-relative paths written. Never raises:
    a page it cannot read is skipped."""
    from api.services import entity_article, revision_prose

    written: list[str] = []
    days = days or {}
    for page, by_episode in history_events(cascade, skip=skip).items():
        path = Path(memory_path) / "entities" / f"{page}.md"
        try:
            if not path.is_file():
                continue
            parsed = markdown_parser.parse(path)
            fm, original = dict(parsed.frontmatter), parsed.body
            body = original
            for episode in sorted(by_episode):
                body = revision_prose._add_history(  # noqa: SLF001 - the one History writer
                    body, days.get(episode) or today, by_episode[episode])
            if body.rstrip() == original.rstrip():     # the line was there already
                continue
            entity_article.carry_stamp(fm, original, body)
            markdown_parser.write(path, fm, body)
            written.append(f"entities/{page}.md")
        except Exception as exc:  # noqa: BLE001 - a History line is never worth the batch
            logger.warning(f"Corrections History skipped a page: {type(exc).__name__}")
    return written
