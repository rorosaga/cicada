"""M5f — the claim layer wired LOAD-BEARING into the live Sleep cycle.

This module is the **additive orchestration seam** that makes the claim core
(built + unit-tested in M5a/M5b/M5e) actually load-bearing during a real Sleep
cycle. It layers ON TOP of the legacy entity-extraction + ``conflict_resolver``
entity path — that path keeps working untouched; claims are reconciled and
written *in addition*, into the same editable entity pages.

Pipeline (called once from ``sleep_cycle.run`` after the entity path has written
its pages, so create-pages exist to host the ```claims block):

1. **Stage 1 (emit).** Project the Stage-1 extraction output into perspectival
   ``Claim`` objects via :func:`entity_extractor.entities_to_claims`
   (observer=agent, context=general, epistemic=explicit,
   source_trust=agent_extracted, origin propagated from the episode). Manual /
   clarification claims may be injected via ``extra_claims`` (already stamped
   ``user_stated`` + a human origin upstream).

2. **Stage 3 (reconcile).** Parse the existing in-page ```claims blocks, then run
   :func:`claim_reconciler.reconcile_stage3` — mechanical, trust-gated
   invalidate-and-supersede. **No agent claim ever closes a human claim** (the
   trust invariant holds end-to-end in the live cycle, not just in unit tests).
   Auto-folded predicates emit the mandatory ``normalization-audit`` nudge;
   per-epistemic×trust decay runs here.

3. **Stage 5 (write).** Write the reconciled claims back INTO each entity page via
   :func:`claims.write_claims`, which preserves all surrounding human prose
   verbatim (round-trip invariant). Subjects without an entity page are skipped
   (never raised) — the legacy promotion model owns page creation; a page-less
   claim simply waits for its subject to be promoted.

The reconciliation nudges (``conflict_nudge`` / ``divergence_nudge`` /
``normalization_audit`` / ``decay_nudge``) are returned in the inbox-generator
change shape so ``sleep_cycle`` can fold them into the inbox alongside the legacy
entity-path nudges. The claim-derived graph edges + claims index are rebuilt by
the existing Stage 5.7 / index steps in ``sleep_cycle`` (which already read the
in-page blocks this module just wrote).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from loguru import logger

from api.services import markdown_parser
from api.services.claim_reconciler import reconcile_stage3
from api.services.claims import Claim, parse_claims, write_claims
from api.services.entity_extractor import entities_to_claims


def _load_existing_claims_by_subject(memory_path: Path) -> dict[str, list[Claim]]:
    """Parse every entity page's ```claims block into ``{subject_id: [Claim]}``.

    Keyed by the page stem (the subject id), which is what Stage 1 emission and
    the reconciler use as ``claim.subject``. Pages with no block contribute an
    empty list so the reconciler still keys correctly.
    """
    entities_dir = memory_path / "entities"
    by_subject: dict[str, list[Claim]] = {}
    if not entities_dir.exists():
        return by_subject
    for filepath in sorted(entities_dir.glob("*.md")):
        try:
            parsed = markdown_parser.parse(filepath)
        except Exception:
            continue
        existing = parse_claims(parsed.body)
        # The page stem is the canonical subject id; existing claims may name a
        # different subject string, but for write-back we route by stem.
        by_subject[filepath.stem] = existing
    return by_subject


def run_claim_pipeline(
    extracted: list[dict],
    existing_entities: list[dict],
    memory_path: Path,
    settings,
    *,
    now_date: str | None = None,
    extra_claims: list[Claim] | None = None,
) -> dict:
    """Emit → reconcile → write claims over the live entity pages (additive).

    Args:
        extracted: Stage-1 extraction output (per-episode entities/relationships,
            origin-stamped). Projected into agent-extracted claims.
        existing_entities: the Stage-2 ``existing`` list (unused for write-back —
            we re-read pages from disk so we see the entity path's fresh writes —
            but accepted for signature symmetry with the rest of the cycle).
        memory_path: active memory bank dir.
        settings: carries ``litellm_model`` / thresholds / ``memory_path``.
        now_date: reconciliation/decay reference date (ISO); defaults to today.
        extra_claims: pre-built claims to inject alongside the projected ones —
            the manual-edit / clarification (``user_stated`` + human-origin) path.

    Returns a dict: ``{"nudges": [...], "audit": [...], "claims_written": int,
    "subjects_written": int, "subjects_skipped": int}``. Never raises on a
    missing subject page — the legacy promotion model owns page creation.
    """
    today = now_date or str(date.today())
    memory_path = Path(memory_path)

    # ---- Stage 1: emit claims from extraction (+ any injected manual claims) ----
    incoming: list[Claim] = entities_to_claims(extracted, memory_path)
    if extra_claims:
        incoming = incoming + list(extra_claims)

    # ---- Stage 3: reconcile against existing in-page claims (trust-gated) ----
    existing_by_subject = _load_existing_claims_by_subject(memory_path)
    reconciled, nudges, audit = reconcile_stage3(
        incoming,
        existing_by_subject,
        settings,
        now_date=today,
    )

    # ---- Stage 5: write reconciled claims back INTO each entity page ----
    entities_dir = memory_path / "entities"
    claims_written = 0
    subjects_written = 0
    subjects_skipped = 0
    for subject, claims in reconciled.items():
        if not claims:
            continue
        filepath = entities_dir / f"{subject}.md"
        if not filepath.exists():
            # No page yet — the subject hasn't crossed the promotion gate. The
            # claim is not lost (it will be re-emitted next cycle once the page
            # exists); we simply don't fabricate a page here (additive safety).
            subjects_skipped += 1
            continue
        try:
            parsed = markdown_parser.parse(filepath)
            new_body = write_claims(parsed.body, claims)
            if new_body != parsed.body:
                markdown_parser.write(filepath, parsed.frontmatter, new_body)
            subjects_written += 1
            claims_written += len(claims)
        except Exception as e:  # never let a single bad page abort the cycle
            logger.warning(
                f"claim write-back skipped for {subject}: {type(e).__name__}: {e}"
            )

    logger.info(
        f"Claim pipeline: {len(incoming)} emitted, "
        f"{subjects_written} pages written ({claims_written} claims), "
        f"{subjects_skipped} subjects without a page, "
        f"{len(nudges)} claim nudges"
    )

    return {
        "nudges": nudges,
        "audit": audit,
        "claims_written": claims_written,
        "subjects_written": subjects_written,
        "subjects_skipped": subjects_skipped,
    }
