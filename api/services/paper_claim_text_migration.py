"""F2-back (R-B12, R-B13) — one-shot, idempotent: strip in-document anchor links
and footnote markers from the words of folder-paper claims written before the
writer learned to (`papers.clean_claim_text`).

A folder's markdown cross-references its own notes — `builds on [N50](#note-n50).`
— and `desired_claims` stored the note verbatim as a `saved-because` claim's text
and object, so the anchor showed on the paper's card. The writer now cleans at
write and a sync repairs what it re-reads, but a file nobody edits is never
re-read, so existing pages are repaired here once.

Scope, exactly: claims with ``origin == folder`` and a why-predicate on
``media.kind: paper`` pages. Only ``text`` and a literal ``object`` change; ids do
not (they were minted from the raw words, R-FX5); the episode is never touched,
so no evidence span moves (G118). The `paper_context_migration` shape (F1
R-FX6): marker-guarded, held under ``folder_source._LOCK`` through the commit, one
commit scoped to exactly the rewritten pages as ``Cicada-Author: cicada`` through
the bank's one write lock (R-B1). One page that cannot be read or written never
stops the rest, what did land is still committed, and any failure keeps the
marker off so the next start retries. Never raises.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from loguru import logger

from api.services import bank_index, folder_source, git_service, markdown_parser, papers
from api.services.claims import MalformedClaimsBlockError, parse_claims, write_claims

_MARKER = ".paper_claim_text_v1"
TRIGGER = "maintenance/paper_claim_text"
_NOTHING = {"pages": 0, "claims": 0}


def repair_paper_claim_text(memory_path) -> dict:
    """Repair one bank. Returns ``{"pages": n, "claims": n}``."""
    memory_path = Path(memory_path)
    if not (memory_path / "entities").exists() or (memory_path / _MARKER).exists():
        return dict(_NOTHING)
    try:
        with folder_source._LOCK:
            written, repaired, failed = _rewrite(memory_path)
            report = {"pages": len(written), "claims": repaired}
            rel = [f"entities/{p.name}" for p in written]
            if rel:
                try:
                    _commit(memory_path, rel)
                except Exception as e:
                    # Right on disk, uncommitted (or no git here): no marker, so the
                    # next start re-scans, finds nothing left and writes it.
                    logger.warning(f"Paper claim-text repair commit skipped: {e}")
                    return report
    except Exception as e:
        logger.error(f"Paper claim-text repair FAILED — will retry on next start: {e}")
        return dict(_NOTHING)
    if not failed:
        (memory_path / _MARKER).write_text("v1", encoding="utf-8")
    return report


def _rewrite(memory_path: Path) -> tuple[list[Path], int, bool]:
    """``(pages written, claims repaired, whether any page failed)``."""
    written: list[Path] = []
    repaired = 0
    failed = False
    bank_index.invalidate(memory_path)
    for f in bank_index.files(memory_path, "entities"):
        if not papers.is_paper(f.frontmatter or {}):
            continue
        try:
            parsed = markdown_parser.parse(f.path)
            claims = parse_claims(parsed.body, strict=True)
        except MalformedClaimsBlockError as exc:
            logger.error(f"corrupt claims block on {f.path.name}, paper claim text skipped: {exc}")
            continue
        except Exception as exc:
            logger.error(f"could not read {f.path.name}, paper claim text retried next start: {exc}")
            failed = True
            continue
        here = sum(1 for c in claims
                   if c.origin == papers.ORIGIN and c.predicate in papers.WHY_PREDICATES and papers.repair_claim_text(c))
        if not here:
            continue
        try:
            markdown_parser.write(f.path, parsed.frontmatter, write_claims(parsed.body, claims))
        except Exception as exc:
            logger.error(f"could not rewrite {f.path.name}, paper claim text retried next start: {exc}")
            failed = True
            continue
        written.append(f.path)
        repaired += here
    return written, repaired, failed


def _commit(memory_path: Path, rel: list[str]) -> None:
    message = git_service.build_commit_message(
        f"Repair paper claim text {date.today().isoformat()}",
        [f"{p}: updated (trigger: {TRIGGER})" for p in rel],
        authors=[git_service.CICADA_AUTHOR],
    )
    git_service.commit_paths_sync(memory_path, message, rel)
