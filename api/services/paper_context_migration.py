"""F1 (owner review 2026-09-23; R-FX4, R-FX6, R-FX7) — one-shot, idempotent:
move folder-paper claims off the ``folder:<id>:<section>`` context, and project
every paper's claim edges.

Before F1, ``papers.desired_claims`` stored a ``saved-because`` claim's folder
and section in its ``context``. The M5b facet rule then gave every annotated
paper two empty graph satellites — one named after that raw value, one
``general`` — and the Graph legend listed the raw value as a context. The
writer now says ``general`` and a sync repairs what it re-reads, but a file
nobody edits is never re-read, so existing pages are repaired here once.

Scope, exactly: claims with ``origin == folder`` whose context starts with
``folder:``, on ``media.kind: paper`` pages. Ids do not change (they always
named the slot, R-FX5), nothing else on a claim moves, and no evidence span goes
stale (the fence is not part of a page's evidence text, G118 R1). The same pass
projects every paper page's claim edges (``graph_builder.upsert_claim_edges``),
so a paper sits by the project that cites it without waiting for a Sleep cycle.
Marker-guarded, one commit scoped to exactly the rewritten paths,
``Cicada-Author: cicada`` — the ``export_origin_migration`` shape — and held
under ``folder_source._LOCK`` through the commit, so a folder sync cannot slip
its own rows into the ``graph_edges.yaml`` committed here. One page that cannot
be read or written never stops the rest, and what did land is still committed
(left dirty, it would ride the next ``git add -A`` under another author — the
G85-class smear); any such failure keeps the marker off so the next start
retries. A corrupt claims block is skipped, not retried: a later folder sync
repairs whatever it re-reads (R-FX6(b)). Never raises.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from loguru import logger

from api.services import bank_index, folder_source, git_service, graph_builder, markdown_parser, papers
from api.services.claims import MalformedClaimsBlockError, parse_claims, write_claims

_MARKER = ".paper_contexts_v1"
TRIGGER = "maintenance/paper_contexts"
_LEGACY_PREFIX = "folder:"
_NOTHING = {"pages": 0, "claims": 0, "edges": False}


def repair_paper_contexts(memory_path) -> dict:
    """Repair one bank. Returns ``{"pages": n, "claims": n, "edges": bool}``."""
    memory_path = Path(memory_path)
    if not (memory_path / "entities").exists() or (memory_path / _MARKER).exists():
        return dict(_NOTHING)
    try:
        with folder_source._LOCK:
            written, moved, paper_ids, failed = _rewrite(memory_path)
            try:
                edges = graph_builder.upsert_claim_edges(memory_path, paper_ids)
            except Exception as e:
                logger.error(f"Paper-edge projection FAILED — will retry on next start: {e}")
                edges, failed = False, True
            report = {"pages": len(written), "claims": moved, "edges": edges}
            rel = [f"entities/{p.name}" for p in written] + (["graph_edges.yaml"] if edges else [])
            if rel:
                try:
                    _commit(memory_path, rel)
                except Exception as e:
                    # Files are right on disk but uncommitted (or this bank is
                    # not a git repo). No marker, so the next boot re-scans,
                    # finds nothing left, and writes it; the files ride the
                    # bank's next commit — the trade `export_origin_migration`
                    # makes, because a bank without git must still be repaired.
                    logger.warning(f"Paper-context repair commit skipped: {e}")
                    return report
    except Exception as e:
        # No marker: the next boot retries, and finds done whatever did land.
        logger.error(f"Paper-context repair FAILED — will retry on next start: {e}")
        return dict(_NOTHING)
    if not failed:
        (memory_path / _MARKER).write_text("v1", encoding="utf-8")
    return report


def _rewrite(memory_path: Path) -> tuple[list[Path], int, list[str], bool]:
    """``(pages written, claims moved, every paper page's id, whether any page failed)``."""
    written: list[Path] = []
    moved = 0
    paper_ids: list[str] = []
    failed = False
    bank_index.invalidate(memory_path)
    for f in bank_index.files(memory_path, "entities"):
        if not papers.is_paper(f.frontmatter or {}):
            continue
        paper_ids.append(f.stem)
        try:
            parsed = markdown_parser.parse(f.path)
            claims = parse_claims(parsed.body, strict=True)
        except MalformedClaimsBlockError as exc:
            logger.error(f"corrupt claims block on {f.path.name}, paper contexts skipped: {exc}")
            continue
        except Exception as exc:
            logger.error(f"could not read {f.path.name}, paper contexts retried next start: {exc}")
            failed = True
            continue
        here = 0
        for c in claims:
            if c.origin == papers.ORIGIN and c.context.startswith(_LEGACY_PREFIX):
                c.context = papers.PAPER_CONTEXT
                here += 1
        if not here:
            continue
        try:
            markdown_parser.write(f.path, parsed.frontmatter, write_claims(parsed.body, claims))
        except Exception as exc:
            logger.error(f"could not rewrite {f.path.name}, paper contexts retried next start: {exc}")
            failed = True
            continue
        written.append(f.path)
        moved += here
    return written, moved, paper_ids, failed


def _commit(memory_path: Path, rel: list[str]) -> None:
    message = git_service.build_commit_message(
        f"Repair paper contexts {date.today().isoformat()}",
        [f"{p}: updated (trigger: {TRIGGER})" for p in rel],
        authors=["cicada"],
    )
    git_service.commit_paths_sync(memory_path, message, rel)  # F2-back R-B1: the bank's one write lock
