"""Bring an existing bank's hub pages to their new shape once — run by the person, never automatically (owner page,
2026-10-14; ``api.scripts.split_hub_pages``).

Sleep gives a page this shape the next time it writes it: a claims fence over ``claims_ledger.FENCE_MAX_CHARS`` moves
its oldest claims into the page's ledger (``markdown_parser.write``), and a ``## Related`` over
``entity_body.RELATED_MAX`` links rolls up (``conflict_resolver._reconcile_related``). This applies both now, in one
``cicada`` commit, so the owner's page — which Sleep rewrites with every batch, under that batch's model — is not
reshaped inside an unrelated Sleep commit, and so the article rebuild (``api.scripts.rebuild_page_articles``) can run on
it right after.

Lossless by construction and checked page by page before anything is written: every claim id and evidence span the
page held is read back from the page and its ledger, and every page the old Related linked is still an edge or a
line. A page that fails the check is left as it was and counted.

* :func:`survey` counts, read-only, never a name or a word of the bank;
* :func:`apply` writes the survey's pages and commits them in ONE ``cicada`` commit (trigger
  ``maintenance/hub-pages``), refused while Sleep runs or holds the pages; a page dirty in git or written since the
  survey is skipped (its writer's to commit). A second run changes nothing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from loguru import logger

from api.services import (
    claims, claims_ledger, conflict_resolver, entity_body, git_service, markdown_parser, page_lock, write_admission,
)

TRIGGER = "maintenance/hub-pages"
_RELATED_RE = re.compile(r"^## Related[ \t]*\n(?P<block>.*?)(?=^## |^```claims[ \t]*$|\Z)", re.M | re.S)
_LINK = re.compile(r"\[\[([^\]|#]+)")


class SleepRunning(RuntimeError):
    """Sleep holds this bank's pages, or a run is in progress: write nothing."""


@dataclass
class Survey:
    """Counts only — never a name, a path or a word of the bank."""

    pages: int = 0
    over_fence: int = 0
    over_related: int = 0
    selected: int = 0
    claims_moved: int = 0
    page_bytes_before: int = 0
    page_bytes_after: int = 0
    ledger_bytes_after: int = 0
    related_lines_before: int = 0
    related_lines_after: int = 0
    failed_check: int = 0
    unreadable: int = 0
    dirty: int = 0
    written: int = 0
    committed: bool = False
    _todo: dict = field(default_factory=dict, repr=False)

    def counts(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}


def _related_block(body: str) -> str:
    match = _RELATED_RE.search(claims.strip_claims_block(body))
    return match.group("block") if match else ""


def _bullets(block: str) -> int:
    return sum(1 for line in block.splitlines() if line.lstrip().startswith("- "))


def _with_related(body: str, block: str) -> str:
    """``body`` with its Related section's content replaced, every other byte kept."""
    match = _RELATED_RE.search(body)
    if match is None:
        return body
    return body[:match.start("block")] + block.strip("\n") + "\n\n" + body[match.end("block"):].lstrip("\n")


def _fingerprint(body: str) -> tuple[set, set]:
    every = claims.parse_claims(body, strict=True)
    ids = {c.id for c in every}
    spans = {(c.id, e.episode, e.start, e.end, e.kind, e.hash) for c in every for e in c.evidence}
    return ids, spans


def _plan(path: Path, memory_path: Path, edges_by_entity: dict, result: Survey):
    """``(text as read, frontmatter, body)`` to write, or ``None`` when the page needs nothing."""
    text = path.read_text(encoding="utf-8")
    split = markdown_parser.split_frontmatter(text)
    _match, own = claims_ledger._fence(split[1] if split else text)
    over_fence = sum(len(line) + 1 for line in own or []) > claims_ledger.FENCE_MAX_CHARS
    parsed = markdown_parser.parse(path)
    body = parsed.body
    old_related = _related_block(body)
    links_before = {n.strip().lower() for n in _LINK.findall(old_related)}
    over_related = len(links_before) > entity_body.RELATED_MAX
    if not (over_fence or over_related):
        return None
    new_body = body
    if over_related:
        block = conflict_resolver._reconcile_related(path.stem, parsed.frontmatter, memory_path, edges_by_entity)
        if block:
            new_body = _with_related(new_body, block)
    fm, page_body, ledger = claims_ledger.split(path, parsed.frontmatter, new_body)
    if ledger is None and markdown_parser._render(fm, page_body) == text.encode("utf-8"):
        return None   # already in shape: a second run changes nothing
    # The check: every claim and span the page held, read back from what would be written (page + ledger).
    lines = ([line for line in ledger.decode("utf-8").split("\n") if line.strip()] if ledger is not None
             else claims_ledger.read_lines(claims_ledger.path_for(path)))
    if _fingerprint(claims_ledger.merged(page_body, lines)) != _fingerprint(body):
        result.failed_check += 1
        return None
    rolled = _related_block(page_body)
    if over_related:
        kept = {n.strip().lower() for n in _LINK.findall(rolled)}
        edges = {str(e.get("target", "")).lower() for e in edges_by_entity.get(path.stem, ())}
        names = kept | edges | {str(s).lower() for s in parsed.frontmatter.get("related") or []}
        # A link the old Related showed is still a line, an edge or a `related:` slug (by name or id).
        if not all(n in names or n.replace(" ", "-") in names for n in links_before):
            result.failed_check += 1
            return None
    result.over_fence += over_fence
    result.over_related += over_related
    result.related_lines_before += _bullets(old_related)
    result.related_lines_after += _bullets(rolled)
    result.page_bytes_before += len(text.encode("utf-8"))
    result.page_bytes_after += len(markdown_parser._render(fm, page_body))
    if ledger is not None:
        result.ledger_bytes_after += len(ledger)
        result.claims_moved += len(lines) - len(claims_ledger.read_lines(claims_ledger.path_for(path)))
    return text, parsed.frontmatter, new_body


def survey(memory_path) -> Survey:
    memory_path = Path(memory_path)
    result = Survey()
    edges_by_entity = conflict_resolver._edges_by_entity(memory_path)
    for path in sorted((memory_path / "entities").glob("*.md")):
        result.pages += 1
        try:
            plan = _plan(path, memory_path, edges_by_entity, result)
        except (claims.MalformedClaimsBlockError, ValueError, OSError):
            result.unreadable += 1
            continue
        if plan is not None:
            result.selected += 1
            result._todo[path] = plan
    return result


def apply(memory_path, *, sleep_running: Callable[[], bool]) -> Survey:
    """Write the survey's pages and commit them in ONE commit authored ``cicada``. Raises :class:`SleepRunning` before
    writing anything when Sleep holds the pages or a run is in progress."""
    memory_path = Path(memory_path)
    written: list[Path] = []
    with write_admission.admitted(memory_path, refuse=lambda: SleepRunning("Sleep is holding this bank's pages")):
        if sleep_running():
            raise SleepRunning("a Sleep run is in progress; split after it ends")
        with page_lock.page_lock(memory_path):
            result = survey(memory_path)
            rels = {path: f"entities/{path.name}" for path in result._todo}
            dirty = git_service.dirty_paths_sync(memory_path, *claims_ledger.with_ledgers(
                memory_path, list(rels.values()))) if rels and (memory_path / ".git").exists() else frozenset()
            for path, (surveyed, fm, body) in result._todo.items():
                ledger_rel = claims_ledger.rel_for(rels[path])
                if path.read_text(encoding="utf-8") != surveyed or rels[path] in dirty or ledger_rel in dirty:
                    result.dirty += 1
                    continue
                markdown_parser.write(path, fm, body)
                written.append(path)
            result.written = len(written)
            if written and (memory_path / ".git").exists():
                message = git_service.build_commit_message(
                    f"Hub pages: {len(written)} page(s) split",
                    [f"entities/{p.name}: updated (trigger: {TRIGGER})" for p in written],
                    authors=["cicada"],
                )
                git_service.commit_paths_sync(memory_path, message, [rels[p] for p in written])
                result.committed = True
    if written:
        logger.info(f"hub pages: {len(written)} page(s) split")
    return result
