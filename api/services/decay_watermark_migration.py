"""G85 §2 / Wave-1 1.8 -- one-shot backfill of the `decayed_through` watermark.

**Why this exists.** Wave-1 1.1 stopped decay re-charging the same interval on
EVERY run, but it does not by itself fix the FIRST charge: `conflict_resolver`
charges `rate * days_since_last_referenced / 7` with no `decayed_through` yet
on disk, and `claim_reconciler` anchors to `recorded_at`/`valid_from` with no
`decayed_through` yet on either. On a bank that has not been consolidated in
~75 days (an ENGINE OUTAGE, not user silence -- the user did not stop
mentioning things, the system stopped consolidating), the very first cycle
after Sleep resumes would charge the WHOLE 75-day gap in one shot -- measured
against the live bank, ~1,536 of 1,882 entity pages would flip to `archived`
on that first cycle. Charging an outage as if it were disinterest is simply
wrong.

**The fix.** Stamp `decayed_through: <today>` on every entity page (and every
OPEN claim inside its `claims` block) that is actually exposed to decay math
(active/decaying, non-evergreen) and lacks the field, so decay begins
accruing from the moment this fix lands rather than retroactively over the
outage. This is a WATERMARK BACKFILL ONLY: `confidence`, `status`,
`last_referenced` and everything else are left untouched -- historical values
are never rewritten, matching Wave-1 1.1's contract.

A per-cycle cap (`conflict_resolver.MAX_DECAY_DAYS_PER_CYCLE` /
`claim_reconciler.MAX_DECAY_DAYS_PER_CYCLE`) is the INDEPENDENT safety rail
for any future gap this migration doesn't cover (a page created after this
migration ran, once it goes stale for the first time with a huge natural
gap -- unlikely but not impossible, e.g. a page whose `last_referenced` was
backdated by an import). This migration's job is narrower: absorb the ONE
100%-certain historical gap (the engine outage) so it costs nothing on the
first cycle after Sleep resumes.

Runs once per bank -- on API startup for the boot-time bank and on
`POST /banks/{name}/activate` for a bank switched to at runtime (both via
`bank_migrations.run_bank_migrations`) -- guarded by a `.decay_watermarked`
marker in exactly the shape `decay_migration.backfill_decay_classes` uses.
This is a SYSTEM MAINTENANCE write -- no model and no user in the loop -- so
the commit is authored by the reserved `cicada` literal, and it commits
EXACTLY the pages it rewrote (never an `entities/` directory pathspec), so a
pre-existing dirty edit or a concurrent Sleep write is never mis-attributed.
"""

from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path

from loguru import logger

from api.models.schemas import DecayClass
from api.services import decay_policy, git_service, markdown_parser
from api.services.claims import MalformedClaimsBlockError, parse_claims, write_claims

_MARKER = ".decay_watermarked"

TRIGGER = "maintenance/decay_watermark_backfill"


def backfill_decay_watermarks(memory_path) -> dict:
    """Backfill one bank. Returns ``{"entities": n, "claims": n}``."""
    memory_path = Path(memory_path)
    empty = {"entities": 0, "claims": 0}
    entities_dir = memory_path / "entities"
    if not entities_dir.exists():
        return empty

    marker = memory_path / _MARKER
    if marker.exists():
        return empty

    try:
        counts, written = _rewrite_pages(entities_dir)
    except Exception as e:
        logger.error(f"Decay-watermark backfill FAILED — leaving entities/ untouched: {e}")
        return empty

    if written:
        try:
            _commit_backfill(memory_path, counts, written)
        except Exception as e:
            # Pages are corrected on disk but the commit failed (or this isn't
            # a git repo). Do NOT write the marker: the rewrite is idempotent
            # (an already-watermarked page/claim is skipped), so a later boot
            # retries the commit with 0 further changes.
            logger.warning(f"Decay-watermark backfill commit skipped: {e}")
            return counts

    marker.write_text("v1", encoding="utf-8")
    return counts


def _rewrite_pages(entities_dir: Path) -> tuple[dict, list[Path]]:
    """Rewrite the pages that need a watermark. Returns ``(counts, written_paths)``.

    Only pages actually exposed to decay math are touched — evergreen and
    archived/dropped entities never read `decayed_through` (the decay loop
    skips them outright), so backfilling them would be pure noise.
    """
    today = date.today().isoformat()
    counts = {"entities": 0, "claims": 0}
    written: list[Path] = []

    for filepath in sorted(entities_dir.glob("*.md")):
        try:
            parsed = markdown_parser.parse(filepath)
        except Exception:
            continue  # a malformed page is skipped, never fatal
        fm = parsed.frontmatter or {}
        if not isinstance(fm, dict):
            continue

        status = str(fm.get("status", "active") or "active")
        decay_class, _rate = decay_policy.resolve(fm)
        decay_eligible = status not in ("archived", "dropped") and decay_class is not DecayClass.evergreen

        changed = False

        if decay_eligible and not fm.get("decayed_through"):
            fm["decayed_through"] = today
            changed = True

        body = parsed.body
        if decay_eligible:
            try:
                claims = parse_claims(body, strict=True)
            except MalformedClaimsBlockError:
                claims = None  # unreadable block: leave the claims layer alone
            if claims:
                claim_changed = False
                for c in claims:
                    if c.valid_to is None and not c.decayed_through:
                        c.decayed_through = today
                        claim_changed = True
                        counts["claims"] += 1
                if claim_changed:
                    body = write_claims(body, claims)
                    changed = True

        if not changed:
            continue

        markdown_parser.write(filepath, fm, body)
        written.append(filepath)
        counts["entities"] += 1

    return counts, written


def _commit_backfill(memory_path: Path, counts: dict, written: list[Path]) -> None:
    """Commit scoped to EXACTLY the pages this migration rewrote (see module
    docstring / `decay_migration._commit_backfill` for why a directory
    pathspec is never used here)."""
    rel = [str(p.relative_to(memory_path)) for p in written]
    if not rel:
        return
    subprocess.run(["git", "add", "--", *rel], cwd=str(memory_path), check=True)
    status = subprocess.run(
        ["git", "status", "--porcelain", "--", *rel],
        cwd=str(memory_path), check=True, capture_output=True, text=True,
    )
    if not status.stdout.strip():
        return
    message = git_service.build_commit_message(
        f"Backfill decay watermarks {date.today().isoformat()}",
        [
            f"entities/: {counts['entities']} page(s) + {counts['claims']} open claim(s) "
            f"stamped decayed_through (trigger: {TRIGGER})"
        ],
        authors=["cicada"],
    )
    subprocess.run(
        ["git", "commit", "-m", message, "--", *rel],
        cwd=str(memory_path),
        check=True,
    )
