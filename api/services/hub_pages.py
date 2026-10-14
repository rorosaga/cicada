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
  survey is skipped (its writer's to commit) — unless it holds exactly what an interrupted run of this migration
  wrote, which a rerun finishes and commits. A second run changes nothing.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
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
    resumed: int = 0
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


def _head_bytes(memory_path: Path, rel: str) -> bytes | None:
    proc = subprocess.run(["git", "-C", str(memory_path), "cat-file", "blob", f"HEAD:{rel}"], capture_output=True,
                          env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
    return proc.stdout if proc.returncode == 0 else None


def _expected(memory_path: Path, rel: str, edges_by_entity: dict) -> tuple[bytes, bytes | None] | None:
    """What this migration writes for the page as HEAD holds it — ``(page bytes, ledger bytes or None)`` — computed on
    a scratch copy of HEAD's page and ledger, never touching the bank. ``None`` when HEAD has no such page."""
    page = _head_bytes(memory_path, rel)
    if page is None:
        return None
    ledger = _head_bytes(memory_path, claims_ledger.rel_for(rel))
    with tempfile.TemporaryDirectory(prefix="cicada-hub-") as scratch:
        tmp = Path(scratch) / "entities" / Path(rel).name
        tmp.parent.mkdir()
        tmp.write_bytes(page)
        if ledger is not None:
            claims_ledger.path_for(tmp).write_bytes(ledger)
        plan = _plan(tmp, memory_path, edges_by_entity, Survey())
        if plan is None:
            return page, ledger
        _text, fm, body = plan
        fm, body, written = claims_ledger.split(tmp, fm, body)
        return markdown_parser._render(fm, body), (written if written is not None else ledger)


def _read(path: Path) -> bytes | None:
    return path.read_bytes() if path.is_file() else None


def _resumable(memory_path: Path, dirty: frozenset, edges_by_entity: dict) -> dict[str, tuple[bytes, bytes | None]]:
    """The pages left dirty by an interrupted run of this migration, ``{rel: expected bytes}``: every dirty page, or
    page whose ledger is dirty, whose page and ledger each hold either HEAD's bytes or exactly what this migration
    writes from HEAD's (the ledger is written before its page, so a run can stop between the two). Anything else on a
    dirty page is someone's edit: never this migration's to commit."""
    pages = sorted({rel[:-len(claims_ledger.SUFFIX)] + ".md" if rel.endswith(claims_ledger.SUFFIX) else rel
                    for rel in dirty if rel.startswith("entities/")
                    and (rel.endswith(".md") or rel.endswith(claims_ledger.SUFFIX)) and rel.count("/") == 1})
    out = {}
    for rel in pages:
        try:
            expected = _expected(memory_path, rel, edges_by_entity)
        except (claims.MalformedClaimsBlockError, ValueError, OSError):
            continue
        if expected is None:
            continue
        lrel = claims_ledger.rel_for(rel)
        now_page, now_ledger = _read(memory_path / rel), _read(memory_path / lrel)
        if now_page in (_head_bytes(memory_path, rel), expected[0]) and \
                now_ledger in (_head_bytes(memory_path, lrel), expected[1]):
            out[rel] = expected
    return out


def apply(memory_path, *, sleep_running: Callable[[], bool]) -> Survey:
    """Write the survey's pages and commit them in ONE commit authored ``cicada``. Raises :class:`SleepRunning` before
    writing anything when Sleep holds the pages or a run is in progress. A rerun after an interrupted run finishes it:
    the pages that run left dirty with exactly this migration's bytes (:func:`_resumable`) are written if still
    needed and committed with the rest (``resumed``)."""
    memory_path = Path(memory_path)
    written: list[Path] = []
    git = (memory_path / ".git").exists()
    with write_admission.admitted(memory_path, refuse=lambda: SleepRunning("Sleep is holding this bank's pages")):
        if sleep_running():
            raise SleepRunning("a Sleep run is in progress; split after it ends")
        with page_lock.page_lock(memory_path):
            result = survey(memory_path)
            dirty = git_service.dirty_paths_sync(memory_path, "entities") if git else frozenset()
            ours = _resumable(memory_path, dirty, conflict_resolver._edges_by_entity(memory_path)) if dirty else {}
            for path, (surveyed, fm, body) in result._todo.items():
                rel = f"entities/{path.name}"
                touched = rel in dirty or claims_ledger.rel_for(rel) in dirty
                if path.read_text(encoding="utf-8") != surveyed or (touched and rel not in ours):
                    result.dirty += 1
                    continue
                markdown_parser.write(path, fm, body)
                written.append(path)
            result.written = len(written)
            done = {f"entities/{p.name}" for p in written}
            # An interrupted run's pages: committed now when they hold exactly what this migration writes.
            resumed = [rel for rel, (page, _ledger) in ours.items()
                       if rel not in done and _read(memory_path / rel) == page]
            result.resumed = len(resumed)
            rels = sorted(done | set(resumed))
            if rels and git:
                message = git_service.build_commit_message(
                    f"Hub pages: {len(rels)} page(s) split",
                    [f"{rel}: updated (trigger: {TRIGGER})" for rel in rels],
                    authors=["cicada"],
                )
                git_service.commit_paths_sync(memory_path, message, rels)
                result.committed = True
    if written or result.resumed:
        logger.info(f"hub pages: {len(written)} page(s) split, {result.resumed} finished from an interrupted run")
    return result
