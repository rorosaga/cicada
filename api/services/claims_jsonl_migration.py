"""DECIDE-1 (owner 2026-10-08): convert a bank's legacy YAML ```claims fences to JSON Lines, in one commit.

Never automatic: ``run_bank_migrations`` does not call it and no route does; only the person (or an operator on their
behalf) runs ``python -m api.scripts.migrate_claims_jsonl --bank <path>`` — a dry run that reports counts only — and
then ``--apply``. Until then the dual reader (``claims.load_fence_payload``) reads both forms, and every page a writer
touches is written as JSON Lines anyway; this converts the rest at once, so the format change is one reviewable commit
instead of a drift across hundreds of Sleep commits.

**What a conversion is.** The fence's raw entries (``claims.raw_claim_entries`` — unknown fields, key order and
values as YAML decoded them) become one JSON line each (``claims._jsonl_line``, the encoder every writer uses). The
prose, the frontmatter and the fence's position are byte-identical, so every evidence span into the page still points
at the same text. A page is converted only when the result reads back as the same claims (``parse_claims``) and the
same raw entries; otherwise it is counted and left alone. A page whose fence is unreadable, repeated or unterminated
(``fence_state``) is counted and never rewritten.

**When it refuses.** While Sleep holds the pages or the backend reports a run (asked over loopback, as the stdio MCP
server asks before it commits; a backend too slow to answer counts as running), and for a page with uncommitted
changes (counted, skipped: a commit commits alone, under its true author). It holds the bank's write admission (shared,
cross-process, so Sleep cannot open its window meanwhile), then the page lock, then git's write lock inside the commit
— the documented order.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from loguru import logger

from api.services import claims, git_service, markdown_parser, page_lock, write_admission

TRIGGER = "maintenance/claims-jsonl"


class SleepRunning(RuntimeError):
    """Sleep holds this bank's pages, or a run is in progress: convert nothing."""


@dataclass
class Survey:
    """Counts only — never a name, a path or a claim's words."""

    pages: int = 0
    no_fence: int = 0
    jsonl: int = 0
    legacy: int = 0
    legacy_claims: int = 0
    empty: int = 0
    unreadable: int = 0
    not_equivalent: int = 0
    dirty: int = 0
    converted: int = 0
    committed: bool = False
    _todo: list[Path] = field(default_factory=list, repr=False)

    def counts(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}


def convert_document(text: str) -> str | None:
    """The page with its one legacy fence rewritten as JSON Lines, or ``None`` when there is nothing to convert or the
    conversion would not read back as the same claims (the caller counts which)."""
    if claims.fence_state(text) != claims.FENCE_OK:
        return None
    match = claims._CLAIMS_BLOCK_RE.search(text)
    payload = match.group("payload")
    if claims.is_jsonl_payload(payload) or payload.strip() in ("", "[]"):
        return None
    entries = claims.raw_claim_entries(text)
    lines = "\n".join(claims._jsonl_line(e) for e in entries)
    out = text[:match.start("payload")] + lines + "\n" + text[match.end("payload"):]
    if claims.parse_claims(out, strict=True) != claims.parse_claims(text, strict=True):
        return None
    if [json.loads(claims._jsonl_line(e)) for e in claims.raw_claim_entries(out)] != \
            [json.loads(claims._jsonl_line(e)) for e in entries]:
        return None
    if claims.strip_claims_block(out) != claims.strip_claims_block(text):
        return None
    return out


def survey(memory_path) -> Survey:
    """What ``apply`` would do, read-only."""
    memory_path = Path(memory_path)
    result = Survey()
    dirty: frozenset[str] = frozenset()
    if (memory_path / ".git").exists():
        try:
            dirty = git_service.dirty_paths_sync(memory_path, "entities")
        except git_service.GitError:
            dirty = frozenset()
    for path in sorted((memory_path / "entities").glob("*.md")):
        result.pages += 1
        text = path.read_text(encoding="utf-8")
        state = claims.fence_state(text)
        if state == claims.FENCE_NONE:
            result.no_fence += 1
            continue
        if state != claims.FENCE_OK:
            result.unreadable += 1
            continue
        payload = claims._CLAIMS_BLOCK_RE.search(text).group("payload")
        if payload.strip() in ("", "[]"):
            result.empty += 1
            continue
        if claims.is_jsonl_payload(payload):
            result.jsonl += 1
            continue
        result.legacy += 1
        result.legacy_claims += len(claims.raw_claim_entries(text))
        if f"entities/{path.name}" in dirty:
            result.dirty += 1
            continue
        if convert_document(text) is None:
            result.not_equivalent += 1
            continue
        result._todo.append(path)
    return result


def apply(memory_path, *, sleep_running: Callable[[], bool]) -> Survey:
    """Convert every convertible legacy fence and commit them in ONE commit authored ``cicada``. Raises
    :class:`SleepRunning` before writing anything when Sleep holds the pages or a run is in progress."""
    memory_path = Path(memory_path)
    written: list[str] = []
    with write_admission.admitted(memory_path, refuse=lambda: SleepRunning("Sleep is holding this bank's pages")):
        if sleep_running():
            raise SleepRunning("a Sleep run is in progress; convert after it ends")
        with page_lock.page_lock(memory_path):
            result = survey(memory_path)
            for path in result._todo:
                converted = convert_document(path.read_text(encoding="utf-8"))
                if converted is None:          # changed since the survey: leave it for the next run
                    result.not_equivalent += 1
                    continue
                markdown_parser.write_document(path, converted)
                written.append(f"entities/{path.name}")
            result.converted = len(written)
            if written and (memory_path / ".git").exists():
                message = git_service.build_commit_message(
                    f"Claims fences to JSON Lines: {len(written)} page(s)",
                    [f"{rel}: claims fence converted (trigger: {TRIGGER})" for rel in written],
                    authors=["cicada"],
                )
                git_service.commit_paths_sync(memory_path, message, written)
                result.committed = True
    if written:
        logger.info(f"claims-jsonl: converted {len(written)} page(s)")
    return result
