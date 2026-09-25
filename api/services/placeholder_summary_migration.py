"""F1 (owner review 2026-09-23; R-FX10) — one-shot, idempotent: give every page
``agentic_write`` created with the ``<name> — created via agentic write.``
placeholder a real first line, composed from its own open claims.

The owner found such pages all over the graph: the Summary box showed the stub
line and, under it, the claims fence flattened into YAML. Readers no longer
show the fence (R-FX8) and the writer no longer writes the stub (R-FX9); this
repairs the pages already on disk.

Scope, exactly: a non-``media`` page whose ``## Summary`` (fence stripped) is
one line matching :data:`PLACEHOLDER_RE` and that has at least one open claim.
The new line is ``entity_body.summary_from_claims`` over its claims — no LLM.
Nothing else moves: frontmatter is untouched (no ``version`` bump, no
``last_referenced`` — a repair is not a mention), every other section is kept,
and the claims list round-trips unchanged to where ``write_claims`` always puts
it, after the last section. The only deterministic writer of ``page`` evidence
spans, ``link_recon``, cites media pages, which this skips; a span an agent
hand-cited on one of these pages would read ``stale`` afterwards (the G118 hash
guard) — never a mis-highlight. A page with no open claim keeps its line; the
app hides it (R-FX11). Marker-guarded, one commit scoped to exactly the
rewritten pages, ``Cicada-Author: cicada``. One page that cannot be rewritten
never stops the rest, what did land is still committed (left dirty, it would
ride the next ``git add -A`` under another author — the G85-class smear), and
the marker stays off so the next start retries it. Never raises.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from loguru import logger

from api.services import entity_body, git_service, markdown_parser
from api.services.claims import MalformedClaimsBlockError, parse_claims, strip_claims_block, write_claims

PLACEHOLDER_RE = re.compile(r"^.+ — created via agentic write\.$")
_MARKER = ".placeholder_summaries_v1"
TRIGGER = "maintenance/placeholder_summary"


def rewrite_placeholder_summaries(memory_path) -> int:
    """Rewrite one bank. Returns how many pages were rewritten."""
    try:
        memory_path = Path(memory_path)
        entities = memory_path / "entities"
        if not entities.exists() or (memory_path / _MARKER).exists():
            return 0
        written: list[Path] = []
        failed = False
        for path in sorted(entities.glob("*.md")):
            try:
                if _rewrite_one(path):
                    written.append(path)
            except Exception as e:
                logger.error(f"Placeholder summary for {path.name} FAILED — will retry on next start: {e}")
                failed = True
        if written:
            try:
                _commit(memory_path, [f"entities/{p.name}" for p in written])
            except Exception as e:
                # Right on disk but uncommitted (or not a git repo): no marker,
                # the next start finds nothing left to rewrite and writes it —
                # the `export_origin_migration` trade.
                logger.warning(f"Placeholder-summary commit skipped: {e}")
                return len(written)
        if not failed:
            (memory_path / _MARKER).write_text("v1", encoding="utf-8")
        return len(written)
    except Exception as e:
        # Never raises (the bank_migrations contract): no marker, next start retries.
        logger.error(f"Placeholder-summary rewrite FAILED — will retry on next start: {e}")
        return 0


def _rewrite_one(path: Path) -> bool:
    try:
        parsed = markdown_parser.parse(path)
    except Exception:
        return False
    fm = parsed.frontmatter or {}
    if str(fm.get("type") or "") == "media":
        return False
    sections = entity_body.parse_sections(strip_claims_block(parsed.body))
    summary = (sections.get("Summary") or "").strip()
    if "\n" in summary or not PLACEHOLDER_RE.match(summary):
        return False
    try:
        claims = parse_claims(parsed.body, strict=True)
    except MalformedClaimsBlockError as exc:
        logger.error(f"corrupt claims block on {path.name}, placeholder kept: {exc}")
        return False
    line = entity_body.summary_from_claims(claims)
    if not line:
        return False
    sections["Summary"] = line
    new_body = write_claims(entity_body.render_sections(sections), claims)
    if new_body == parsed.body:
        return False
    markdown_parser.write(path, fm, new_body)
    return True


def _commit(memory_path: Path, rel: list[str]) -> None:
    message = git_service.build_commit_message(
        f"Write placeholder summaries {date.today().isoformat()}",
        [f"{p}: updated (trigger: {TRIGGER})" for p in rel],
        authors=["cicada"],
    )
    git_service.commit_paths_sync(memory_path, message, rel)  # F2-back R-B1: the bank's one write lock
