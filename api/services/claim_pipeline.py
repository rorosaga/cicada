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
   verbatim (round-trip invariant). Each endpoint is keyed through Stage 2's
   ``name_to_id`` (G141 PJ-0), so a claim lands on the page its edge does, and
   "the user" lands on the ``owner: true`` page. A subject that still has no
   page is NOT written — the promotion model owns page creation — and its
   claims are counted (``claims_page_less``): this cycle marks the episode
   processed, so nothing re-extracts them. Holding them until the subject is
   promoted was ruled yes (G141 DECIDE (c), 2026-09-23) and is slice PJ-0b,
   which fills :func:`hold_page_less`.

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
from typing import Callable

from loguru import logger

from api.services import markdown_parser, owner_identity, telemetry
from api.services.claim_reconciler import reconcile_stage3
from api.services.claims import Claim, parse_claims, write_claims
from api.services.entity_extractor import entities_to_claims
from api.services.entity_resolver import endpoint_id
from api.services.id_utils import sanitize_id

#: What Stage 1 writes for an endpoint that IS the person — its prompt speaks of
#: "the user" (``entity_extractor.EXTRACTION_SYSTEM_PROMPT``). Closed on purpose
#: (R-PJ17, R-CS2): only these, only onto a page marked ``owner: true``;
#: whatever still misses is counted, and G141's M3 reads the count.
OWNER_SURFACES = frozenset({"user", "the user", "me", "myself", "i"})


def _owner_page_id(existing_entities: list[dict] | None, memory_path: Path, settings) -> str | None:
    """The bank's ``owner: true`` page among Stage 2's ``existing`` list, or ``None``.

    Two owner pages can exist (G117 R3's disclosed gap: re-onboarding under a
    new display name writes a second page); the one ``owner_identity`` resolves
    wins, else the first by id, so the answer never depends on file order."""
    owners = sorted(
        str(e.get("id")) for e in (existing_entities or [])
        if isinstance(e, dict) and e.get("id") and (e.get("frontmatter") or {}).get("owner")
    )
    if len(owners) <= 1:
        return owners[0] if owners else None
    try:
        resolved = owner_identity.resolve_observer(memory_path, settings)
    except Exception:  # noqa: BLE001 - a tie-break is never worth a failed cycle
        resolved = None
    return resolved if resolved in owners else owners[0]


def subject_resolver(name_to_id: dict[str, str] | None, owner_id: str | None) -> Callable[[str], str]:
    """G141 PJ-0 (R-PJ17, R-CS1): the page id a claim endpoint's raw name keys to.

    The owner surfaces first (only when an owner page exists), then Stage 2's
    own map through ``entity_resolver.endpoint_id`` — the rule its edges use —
    then ``sanitize_id``, the pre-PJ-0 key. Stage 2's decisions carry over
    whole, its fuzzy merges included (R-CS5)."""
    table = dict(name_to_id or {})

    def resolve(name: str) -> str:
        key = (name or "").strip().lower()
        if owner_id and key in OWNER_SURFACES:
            return owner_id
        return endpoint_id(key, table) or sanitize_id(name)

    return resolve


def hold_page_less(subject: str, claims: list[Claim], memory_path: Path) -> int:
    """R-PJ17 SEAM, filled by slice PJ-0b. The owner ruled (G141 DECIDE (c),
    2026-09-23) that Sleep holds an unpromoted subject's claims beside its
    pending entity and writes them when it is promoted. That changes the
    pending store, so it is its own slice and not built in PJ-0.
    Returns how many of ``claims`` were held — always 0 until PJ-0b; the
    pipeline counts the rest as ``claims_page_less``. PJ-0b changes this body
    (and the pending store) and nothing else in the pipeline."""
    return 0


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
    name_to_id: dict[str, str] | None = None,
) -> dict:
    """Emit → reconcile → write claims over the live entity pages (additive).

    Args:
        extracted: Stage-1 extraction output (per-episode entities/relationships,
            origin-stamped). Projected into agent-extracted claims.
        existing_entities: Stage 2's ``existing`` list — read for the
            ``owner: true`` page "the user" maps onto (G141 PJ-0). Write-back
            still re-reads pages from disk, to see the entity path's fresh writes.
        memory_path: active memory bank dir.
        settings: carries ``litellm_model`` / thresholds / ``memory_path``.
        now_date: reconciliation/decay reference date (ISO); defaults to today.
        extra_claims: pre-built claims to inject alongside the projected ones —
            the manual-edit / clarification (``user_stated`` + human-origin) path.
        name_to_id: Stage 2's ``resolve(...)["name_to_id"]`` — every endpoint is
            keyed through it (R-CS1). ``None`` keeps ``sanitize_id``.

    Returns a dict: ``{"nudges": [...], "audit": [...], "claims_written": int,
    "subjects_written": int, "subjects_skipped": int, "claims_page_less": int,
    "page_less_subjects": [ids]}`` — the last two in memory only (R-CS3: a
    subject id is a slug of a name, so it is never logged). Never raises on a
    missing subject page.
    """
    today = now_date or str(date.today())
    memory_path = Path(memory_path)

    # ---- Stage 1: emit claims from extraction (+ any injected manual claims) ----
    owner_id = _owner_page_id(existing_entities, memory_path, settings)
    incoming: list[Claim] = entities_to_claims(
        extracted, memory_path, resolve_id=subject_resolver(name_to_id, owner_id))
    emitted_ids = {c.id for c in incoming}  # Stage-1 only — never the person's extra_claims
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
    # G113 — every supersede/reject the reconciler decided lands in the ledger.
    # One pass covers every subject, so the subject is recovered per entry from
    # the claim ids involved rather than passed once for the whole batch.
    subject_by_id = {c.id: c.subject for claims in existing_by_subject.values() for c in claims}
    subject_by_id.update({c.id: c.subject for c in incoming})
    for entry in audit:
        subject = subject_by_id.get(entry.get("by") or entry.get("dropped")) or subject_by_id.get(
            entry.get("closed") or entry.get("kept")
        )
        telemetry.record_audit([entry], subject_hint=subject, bank=memory_path.name, stage="reconcile")

    # ---- Stage 5: write reconciled claims back INTO each entity page ----
    entities_dir = memory_path / "entities"
    claims_written = 0
    subjects_written = 0
    subjects_skipped = 0
    written_subjects: list[str] = []
    claims_page_less = 0
    page_less_subjects: list[str] = []
    page_less_claim_ids: list[str] = []
    for subject, claims in reconciled.items():
        if not claims:
            continue
        filepath = entities_dir / f"{subject}.md"
        if not filepath.exists():
            # G141 PJ-0: not written — the promotion model owns page creation —
            # and not re-emitted either: this cycle marks the episode processed
            # (`sleep_cycle._mark_episodes_processed`), so nothing brings the
            # claim back. Count it and offer it to the R-PJ17 seam (PJ-0b).
            held = hold_page_less(subject, claims, memory_path)
            subjects_skipped += 1
            claims_page_less += len(claims) - held
            page_less_subjects.append(subject)
            page_less_claim_ids.extend(c.id for c in claims)
            continue
        try:
            parsed = markdown_parser.parse(filepath)
            # strict guard: if the existing block is unparseable, raise (caught
            # below) instead of overwriting claims we could not read.
            parse_claims(parsed.body, strict=True)
            new_body = write_claims(parsed.body, claims)
            if new_body != parsed.body:
                markdown_parser.write(filepath, parsed.frontmatter, new_body)
            subjects_written += 1
            written_subjects.append(subject)
            claims_written += len(claims)
        except Exception as e:  # never let a single bad page abort the cycle
            logger.warning(
                f"claim write-back skipped for {subject}: {type(e).__name__}: {e}"
            )

    # ---- G61 phase 2 S1 (spec §5.2, plan R-AC33): a link the cited words contain ----
    # A URL sitting verbatim inside a newly written Stage-1 claim's evidence span
    # is where that fact can be checked. Zero LLM, never a URL Stage 1 made up;
    # only on a page this pass wrote, only for a world/artifact predicate. Its
    # frontmatter write rides this stage's pages into `_finalize`'s commit, under
    # the model that extracted it — the right author for it.
    sources_attached = 0
    if written_subjects:
        try:
            from api.services import fact_sources, predicates

            locus_of = predicates.build_locus_fn(memory_path)
            for subject in written_subjects:
                for claim in reconciled.get(subject, []):
                    if claim.id in emitted_ids and claim.valid_to is None:
                        sources_attached += len(fact_sources.attach_cited_urls(memory_path, subject, claim, locus_of))
        except Exception as e:  # a source is a convenience; it never costs the cycle
            logger.warning(f"cited-link source attach skipped: {type(e).__name__}: {e}")

    logger.info(
        f"Claim pipeline: {len(incoming)} emitted, "
        f"{subjects_written} pages written ({claims_written} claims), "
        f"{claims_page_less} claim(s) on {subjects_skipped} subject(s) without a page not written, "
        f"{sources_attached} cited links attached as sources, "
        f"{len(nudges)} claim nudges"
    )
    if page_less_claim_ids:
        # R-CS3: opaque claim ids only — never the subject, a slug of a name.
        logger.debug(f"Claim pipeline: page-less claim ids {sorted(page_less_claim_ids)}")

    return {
        "nudges": nudges,
        "audit": audit,
        "claims_written": claims_written,
        "subjects_written": subjects_written,
        "subjects_skipped": subjects_skipped,
        "claims_page_less": claims_page_less,
        "page_less_subjects": sorted(page_less_subjects),
    }
