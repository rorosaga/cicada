"""G61 S3-a (D8) — link a source to its own memory node, when it is EXACTLY that node.

A source entry may carry ``entity: <page id>``: "this page knows more about it".
The person sets it in the card and an agent through ``cicada_add_source`` /
``cicada_change_source``; this module fills it in for the sources that already
exist, engine-free and with no name-based guessing, ever:

- a ``url`` source whose ``media_ingestor.url_hash`` equals a saved media page's
  (``sources/url_index.json``) links to that page;
- a ``path`` source that equals a ``directory``/``location`` page's own declared
  ``path:`` links to that page.

It only ever fills an EMPTY ``entity:`` — a link the person or an agent set is
never overwritten — and never creates a page. The write is a page's frontmatter;
the caller commits (``commit_message``), so the Sleep tail and the maintenance
route share one shape and one author (``cicada``, trigger ``sleep/source-links``).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from loguru import logger

from api.services import bank_index, fact_sources, git_service, markdown_parser

TRIGGER = "sleep/source-links"
AUTHOR = "cicada"
_LOCATION_TYPES = frozenset({"directory", "location"})


@dataclass
class Report:
    paths: list[str] = field(default_factory=list)   # memory-relative pages written
    linked: int = 0                                  # sources given an `entity:`


def _norm_path(value) -> str:
    text = str(value or "").strip()
    return text.rstrip("/") if len(text) > 1 else text


def backfill(memory_path: Path, skip: frozenset[str] = frozenset()) -> Report:
    """Fill every empty ``entity:`` an exact match can name. Pages in ``skip``
    (memory-relative paths dirty before the run) are left alone."""
    from api.services import media_ingestor

    memory_path = Path(memory_path)
    report = Report()
    url_pages: dict[str, str] = {}
    for h, row in (media_ingestor.load_url_index(memory_path) or {}).items():
        if isinstance(row, dict) and row.get("media_entity_id"):
            url_pages[str(h)] = str(row["media_entity_id"])
    path_pages: dict[str, str] = {}
    files = bank_index.files(memory_path, "entities")
    for f in files:
        fm = f.frontmatter or {}
        if str(fm.get("type") or "") in _LOCATION_TYPES and str(fm.get("status") or "") != "dropped" and fm.get("path"):
            path_pages.setdefault(_norm_path(fm.get("path")), f.stem)
    if not url_pages and not path_pages:
        return report
    for f in files:
        fm = f.frontmatter or {}
        raw = fm.get("sources")
        if not isinstance(raw, list) or not any(isinstance(s, dict) and s.get("ref") and not s.get("entity") for s in raw):
            continue
        rel = f"entities/{f.stem}.md"
        if rel in skip:
            continue
        parsed = markdown_parser.parse(f.path)
        sources = parsed.frontmatter.get("sources")
        touched = 0
        for src in sources if isinstance(sources, list) else []:
            if not isinstance(src, dict) or not src.get("ref") or src.get("entity"):
                continue
            ref = str(src["ref"]).strip()
            kind = str(src.get("kind") or fact_sources.infer_kind(ref))
            target = None
            if kind == fact_sources.KIND_URL:
                target = url_pages.get(media_ingestor.url_hash(ref))
            elif kind == fact_sources.KIND_PATH:
                target = path_pages.get(_norm_path(ref))
            if not target or target == f.stem:
                continue
            try:
                src["entity"] = fact_sources.resolve_entity_link(memory_path, target, self_id=f.stem)
            except fact_sources.InvalidSource:
                continue   # the page is gone or dropped: no link, never a guess
            touched += 1
        if touched:
            markdown_parser.write(f.path, parsed.frontmatter, parsed.body)
            report.paths.append(rel)
            report.linked += touched
    if report.paths:
        bank_index.invalidate(memory_path)
    return report


def commit_message(report: Report, today: date, trigger: str = TRIGGER) -> str:
    """``Source links <date>``, ``Cicada-Author: cicada``, no engine trailer — no LLM ran."""
    return git_service.build_commit_message(
        f"Source links {today.isoformat()}",
        [f"{p}: updated (source: n/a, trigger: {trigger})" for p in report.paths],
        authors=[AUTHOR])


def restore(memory_path: Path, report: Report) -> None:
    """Undo a run whose commit failed: the pages come back from HEAD, so the next
    ``git add -A`` writer never sweeps them under the wrong author (the G85 smear)."""
    memory_path = Path(memory_path)
    if report.paths and (memory_path / ".git").exists():
        try:
            git_service.run_git_write_sync(memory_path, "checkout", "--", *report.paths)
        except git_service.GitError as exc:
            logger.warning(f"source-link restore failed: {type(exc).__name__}")
    bank_index.invalidate(memory_path)
