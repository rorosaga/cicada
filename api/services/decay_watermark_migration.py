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
and lacks the field, so decay begins accruing from the moment this fix lands
rather than retroactively over the outage. This is a WATERMARK BACKFILL ONLY:
`confidence`, `status`, `last_referenced` and everything else are left
untouched -- historical values are never rewritten, matching Wave-1 1.1's
contract.

**"Exposed to decay math" is NOT the same test for an entity's own frontmatter
as it is for its claims (Devin PR #24 round 1, finding 3).** The entity engine
(`conflict_resolver.resolve_and_prune`) skips `archived`/`dropped` entities
outright, so their frontmatter watermark is correctly left alone. But the
claim engine (`claim_reconciler._decay_claims`) does NOT gate on the subject's
`status` at all -- only on the subject's decay class (evergreen subjects'
claims never decay; everyone else's do, archived or not, per
`decay_policy.claim_multiplier`). So an archived page's OPEN claims are still
decayed every Sleep cycle and MUST still be backfilled even though the page
itself is archived. The two eligibility checks below are deliberately
different for exactly this reason.

**A malformed ```claims block degrades PER-CLAIM, not per-file (finding 3).**
`claims.parse_claims(..., strict=True)` aborts the WHOLE block on a single bad
entry -- correct for a real read-modify-write caller (its own docstring warns
that the lenient `strict=False` mode silently DROPS a malformed entry on
re-serialize, which would be genuine data loss here). This module instead
parses the block by hand: a well-formed entry becomes a real `Claim`
(candidate for backfill); anything that fails to parse is preserved VERBATIM
via `_RawClaimEntry`, a duck-typed passthrough `write_claims` treats exactly
like a `Claim` (it only ever calls `.to_dict()`) -- so one bad entry no longer
takes the rest of a page's claims hostage. Only a block that fails to parse as
YAML at all, or isn't a list, has no per-entry structure to salvage; that page
still logs and moves on (its ENTITY frontmatter watermark is still backfilled
independently).

A per-cycle cap (`conflict_resolver.MAX_DECAY_DAYS_PER_CYCLE` /
`claim_reconciler.MAX_DECAY_DAYS_PER_CYCLE`) is the INDEPENDENT safety rail
for any future gap this migration doesn't cover (a page created after this
migration ran, once it goes stale for the first time with a huge natural
gap -- unlikely but not impossible, e.g. a page whose `last_referenced` was
backdated by an import). This migration's job is narrower: absorb the ONE
100%-certain historical gap (the engine outage) so it costs nothing on the
first cycle after Sleep resumes.

**Crash-recoverable, not just idempotent (Devin PR #24 round 1, finding 2.)**
A run that rewrites pages on disk but fails to COMMIT them left the marker
unwritten, correctly -- but a *retry* re-scanned frontmatter, found the
watermark already present (the write DID succeed), concluded there was
"nothing to do", and wrote the marker anyway over still-uncommitted pages. A
`.decay_watermarked.pending` journal names exactly which relative paths were
rewritten-but-not-yet-committed, written BEFORE the commit is attempted (so it
survives a crash, not just a caught exception) and cleared only after a
successful commit. A retry unions the journal with anything newly rewritten
and re-attempts the commit for the union, so a page is never silently
abandoned dirty.

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

import yaml
from loguru import logger

from api.models.schemas import DecayClass
from api.services import decay_policy, git_service, markdown_parser
from api.services.claims import _CLAIMS_BLOCK_RE, Claim, write_claims

_MARKER = ".decay_watermarked"
# The write-ahead journal for finding 2 — see module docstring.
_PENDING_MARKER = ".decay_watermarked.pending"

TRIGGER = "maintenance/decay_watermark_backfill"


class _RawClaimEntry:
    """A ```claims block entry that failed to parse as a `Claim`, preserved
    verbatim (finding 3). Duck-types a `Claim` for `write_claims`'s purposes
    — `_render_claims_block` only ever calls `.to_dict()` on each element —
    so it round-trips through the SAME serialization path as every real
    claim without `claims.py` needing to know this type exists.
    """

    __slots__ = ("_raw",)

    def __init__(self, raw: object) -> None:
        self._raw = raw

    def to_dict(self) -> object:
        return self._raw


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

    pending_path = memory_path / _PENDING_MARKER
    pending_rel = _read_pending(pending_path)

    try:
        counts, written = _rewrite_pages(entities_dir)
    except Exception as e:
        logger.error(f"Decay-watermark backfill FAILED — leaving entities/ untouched: {e}")
        counts, written = {"entities": 0, "claims": 0}, []

    written_rel = {str(p.relative_to(memory_path)) for p in written}
    # Recover any path a prior run rewrote but never committed (finding 2).
    # Filter to what still exists — a page may have been deleted/merged
    # between runs, and `git add` on a vanished path would just error.
    recovered_rel = {r for r in pending_rel if r not in written_rel and (memory_path / r).exists()}
    all_rel = sorted(written_rel | recovered_rel)
    # A recovered page's watermark was already stamped by the run that
    # first rewrote it — its per-claim breakdown isn't in this run's tally,
    # but it IS one more page whose backfill is finalizing now, so it still
    # counts toward `entities` (page-level granularity) even though we don't
    # re-derive its exact open-claims count without re-parsing it.
    counts["entities"] += len(recovered_rel)

    if not all_rel:
        pending_path.unlink(missing_ok=True)
        marker.write_text("v1", encoding="utf-8")
        return counts

    # Record the journal BEFORE attempting the commit — recoverable even if
    # the process dies mid-commit, not just on a caught exception.
    _write_pending(pending_path, all_rel)

    try:
        _commit_backfill(memory_path, counts, all_rel)
    except Exception as e:
        # Pages are correct on disk but not yet committed (or this isn't a
        # git repo). Do NOT write the marker — the pending journal makes the
        # next run retry the commit for exactly these paths, even though
        # `_rewrite_pages` alone would now see them as already-watermarked.
        logger.warning(
            f"Decay-watermark backfill commit skipped ({len(all_rel)} page(s) pending retry): {e}"
        )
        return counts

    pending_path.unlink(missing_ok=True)
    marker.write_text("v1", encoding="utf-8")
    return counts


def _read_pending(pending_path: Path) -> list[str]:
    if not pending_path.exists():
        return []
    try:
        text = pending_path.read_text(encoding="utf-8")
    except Exception:
        return []
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def _write_pending(pending_path: Path, rel_paths: list[str]) -> None:
    pending_path.write_text("\n".join(rel_paths) + "\n", encoding="utf-8")


def _rewrite_pages(entities_dir: Path) -> tuple[dict, list[Path]]:
    """Rewrite the pages that need a watermark. Returns ``(counts, written_paths)``.

    Two SEPARATE eligibility checks (finding 3): the entity's own frontmatter
    watermark only matters when the entity engine would actually read it
    (active/decaying, non-evergreen — archived/dropped/evergreen never decay,
    so backfilling them is pure noise). A page's CLAIMS backfill is broader —
    the claim engine decays an open claim regardless of its subject's
    `status`, so only `evergreen` exempts a page's claims here.
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
        entity_decay_eligible = (
            status not in ("archived", "dropped") and decay_class is not DecayClass.evergreen
        )
        # The claim engine ignores `status` entirely — see module docstring.
        claims_decay_eligible = decay_class is not DecayClass.evergreen

        changed = False

        if entity_decay_eligible and not fm.get("decayed_through"):
            fm["decayed_through"] = today
            changed = True

        body = parsed.body
        if claims_decay_eligible:
            entries, readable = _load_claims_tolerant(body, filepath)
            if not readable:
                pass  # whole block unreadable — nothing to salvage per-entry
            elif entries:
                claim_changed = False
                for c in entries:
                    if isinstance(c, Claim) and c.valid_to is None and not c.decayed_through:
                        c.decayed_through = today
                        claim_changed = True
                        counts["claims"] += 1
                if claim_changed:
                    body = write_claims(body, entries)
                    changed = True

        if not changed:
            continue

        markdown_parser.write(filepath, fm, body)
        written.append(filepath)
        counts["entities"] += 1

    return counts, written


def _load_claims_tolerant(body: str, filepath: Path) -> tuple[list, bool]:
    """Parse a page's ```claims block, degrading PER-ENTRY (finding 3).

    Returns ``(entries, readable)``. ``entries`` mixes real `Claim`s with
    `_RawClaimEntry` passthroughs for anything that failed to parse — never
    silently dropped (contrast `claims.parse_claims(strict=False)`, whose own
    docstring warns that a lenient re-serialize destroys a malformed entry).
    ``readable`` is False only when the block as a WHOLE isn't parseable
    (bad YAML, or not a list) — there is no per-entry structure to salvage in
    that case, so the caller leaves the page's claims untouched this run.
    """
    match = _CLAIMS_BLOCK_RE.search(body or "")
    if not match:
        return [], True  # no block at all — nothing to do, not an error

    try:
        loaded = yaml.safe_load(match.group("payload"))
    except yaml.YAMLError as exc:
        logger.warning(
            f"decay-watermark backfill: unreadable ```claims block in {filepath.name}, "
            f"skipping its claims this run ({exc})"
        )
        return [], False
    if loaded is None:
        return [], True
    if not isinstance(loaded, list):
        logger.warning(
            f"decay-watermark backfill: ```claims block in {filepath.name} is not a "
            "list, skipping its claims this run"
        )
        return [], False

    entries: list = []
    for item in loaded:
        if not isinstance(item, dict):
            logger.warning(
                f"decay-watermark backfill: non-mapping ```claims entry in "
                f"{filepath.name}, leaving it as-is"
            )
            entries.append(_RawClaimEntry(item))
            continue
        try:
            entries.append(Claim.from_dict(item))
        except Exception as exc:  # never let one bad entry abort the page
            logger.warning(
                f"decay-watermark backfill: unparseable ```claims entry in "
                f"{filepath.name}, leaving it as-is ({exc})"
            )
            entries.append(_RawClaimEntry(item))
    return entries, True


def _commit_backfill(memory_path: Path, counts: dict, rel: list[str]) -> None:
    """Commit scoped to EXACTLY the pages this migration rewrote (see module
    docstring / `decay_migration._commit_backfill` for why a directory
    pathspec is never used here). ``rel`` is relative path strings — may
    include paths recovered from a prior failed commit's pending journal, not
    only ones rewritten THIS run.
    """
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
