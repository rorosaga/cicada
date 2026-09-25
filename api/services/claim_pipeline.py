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
   page is NOT written — the promotion model owns page creation — and this
   cycle marks its episode processed, so nothing extracts those claims again.
   So they are HELD with the subject's pending entity (G141 PJ-0b, ruled
   2026-09-23 as DECIDE (c); :func:`hold_page_less`), and released — first,
   through Stage 3 like any claim — in the cycle whose Stage 5 gave the name a
   page. What cannot be held is counted (``claims_page_less``).

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

from api.services import markdown_parser, owner_identity, pending_store, telemetry
from api.services.claim_reconciler import reconcile_stage3
from api.services.claims import Claim, is_event, parse_claims, write_claims
from api.services.entity_extractor import entities_to_claims
from api.services.entity_resolver import endpoint_id
from api.services.id_utils import sanitize_id
from api.services.pending_store import HoldOutcome, Release

#: What Stage 1 writes for an endpoint that IS the person — its prompt speaks of
#: "the user" (``entity_extractor.EXTRACTION_SYSTEM_PROMPT``). Closed on purpose
#: (R-PJ17, R-CS2): only these, only onto a page marked ``owner: true``;
#: whatever still misses is counted, and G141's M3 reads the count.
OWNER_SURFACES = frozenset({"user", "the user", "me", "myself", "i"})

#: G141 PJ-0b (R-HP2): the ids the owner surfaces key to when no owner page
#: exists. Never held — R-CS2 never invents a `user` page, and a pending
#: "User" line (Stage 1 listing the person as an entity) must not collect the
#: person's claims and hand them to a page named after a pronoun.
_OWNER_SLUGS = frozenset(sanitize_id(s) for s in OWNER_SURFACES)


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


def hold_page_less(offers: dict[str, list[Claim]], memory_path: Path) -> dict[str, HoldOutcome]:
    """G141 PJ-0b — hold what Sleep heard about a name that has no page yet.

    The owner ruled (G141 DECIDE (c), 2026-09-23; R-PJ17) that an unpromoted
    subject's claims wait WITH its pending entity and are written when it is
    promoted. ``offers`` maps each page-less subject id to this cycle's Stage-1
    claims on it; each goes to the pending line whose slug is that id
    (``pending_store.hold``, R-HP2) — the id Stage 2's promotion writes, so a
    held claim lands where the page will be.

    Never held, and so counted as ``claims_page_less`` exactly as PJ-0 did:
    - a subject with no pending line (Stage 1 named the endpoint differently
      from the entity, or never listed it) — no fuzzy match over pending names;
    - the owner surfaces (``_OWNER_SLUGS``, R-CS2);
    - a claim already closed in its own batch — Stage 3 never tests an incoming
      claim's own validity (``reconcile_stage3``'s ``same_key_open``), so a
      closed claim released later could close an open one;
    - an event (``is_event``) — only ``progress.py`` writes those (G141 §5.1).

    One read and at most one write of the store per cycle (R-HP10). Returns
    ``{subject: HoldOutcome(held, capped)}`` for every subject offered."""
    eligible = {
        subject: [c for c in claims if c.valid_to is None and not is_event(c)]
        for subject, claims in offers.items()
        if subject not in _OWNER_SLUGS
    }
    outcomes = pending_store.hold(memory_path, eligible)
    return {subject: outcomes.get(subject, HoldOutcome(0, 0)) for subject in offers}


def _release_target(name_to_id: dict[str, str] | None) -> Callable[[str, str], str]:
    """G141 PJ-0b (R-HP5): where a pending line's held claims go — Stage 2's own
    EXACT verdict on that name this cycle (a promotion keys it to its slug, a
    ``same`` match to the page it matched, a page named the same to that page),
    else the claims' own subject. Never fuzzy: a verdict Stage 2 did not reach
    is not invented here."""
    table = {str(k): str(v) for k, v in (name_to_id or {}).items()}

    def target(name: str, subject: str) -> str:
        return table.get((name or "").strip().lower()) or subject

    return target


def _releases(
    memory_path: Path, name_to_id: dict[str, str] | None, existing_by_subject: dict[str, list[Claim]],
) -> tuple[list[Release], list[Claim], dict[str, list[str]]]:
    """G141 PJ-0b (R-HP5, R-HP6, R-HP8): the held claims whose name has a page now,
    read WITHOUT touching the store — the lines leave only after the write
    succeeded (R-HP4). Returns ``(releases, claims for Stage 3, credit)``. A
    claim already on its target page is not offered again: a store removal
    that failed after a good write must not have the person asked about their
    own claim. ``credit`` maps each target page to the episodes its claims
    were heard in. A store that cannot be read releases nothing this cycle."""
    try:
        releases = pending_store.ready(memory_path, _release_target(name_to_id))
    except Exception as e:  # noqa: BLE001 - a hold is never worth the cycle's claims
        logger.warning(f"pending-store release skipped: {type(e).__name__}: {e}")
        return [], [], {}
    offered: list[Claim] = []
    credit: dict[str, list[str]] = {}
    for rel in releases:
        on_page = {c.id for c in existing_by_subject.get(rel.target, [])}
        episodes = credit.setdefault(rel.target, [])
        for claim in rel.claims:
            for ep in claim.source_episodes:
                if ep and ep not in episodes:
                    episodes.append(ep)
            if claim.id not in on_page:
                offered.append(claim)
    return releases, offered, credit


def _credit_episodes(frontmatter: dict, episodes: list[str] | None) -> bool:
    """R-HP8: the conversation a released claim was heard in credits the page —
    G48's transitive credit through ``source_episodes`` — in the same write.
    True when the frontmatter changed."""
    if not episodes:
        return False
    raw = frontmatter.get("source_episodes")
    have = [str(e) for e in raw] if isinstance(raw, list) else ([str(raw)] if raw else [])
    missing = [e for e in episodes if e and e not in have]
    if not missing:
        return False
    frontmatter["source_episodes"] = have + missing
    return True


def _settle_store(
    memory_path: Path, releases: list[Release], written: set[str],
    offers: dict[str, list[Claim]], stage1_ids: set[str],
) -> dict[str, int]:
    """G141 PJ-0b, after the write: release the lines whose page took their claims
    (R-HP4), then hold what is still page-less (R-HP2) — release first, so no
    line is handed new claims in the pass that retires it. Each store call is
    guarded (R-HP10): a failure is logged and costs only the hold — what could
    not be held is counted page-less by the caller. Returns R-HP12's counts."""
    counts = {"claims_held": 0, "claims_hold_capped": 0, "claims_released": 0, "claims_waiting": 0}
    done = [rel for rel in releases if rel.target in written]
    try:
        pending_store.release(memory_path, [rel.name for rel in done])
        counts["claims_released"] = sum(len(rel.claims) for rel in done)
    except Exception as e:  # noqa: BLE001 - the lines stay and release next cycle
        logger.warning(f"pending-store release not recorded: {type(e).__name__}: {e}")
    if len(done) < len(releases):
        logger.info(
            f"Claim pipeline: {len(releases) - len(done)} pending name(s) keep their held claims "
            f"until their page can be written"
        )
    try:
        outcomes = hold_page_less(
            {s: [c for c in claims if c.id in stage1_ids] for s, claims in offers.items()}, memory_path)
        counts["claims_held"] = sum(o.held for o in outcomes.values())
        counts["claims_hold_capped"] = sum(o.capped for o in outcomes.values())
    except Exception as e:  # noqa: BLE001 - unheld claims are counted page-less, never lost silently
        logger.warning(f"page-less claims not held: {type(e).__name__}: {e}")
    try:
        counts["claims_waiting"] = pending_store.waiting(memory_path)[0]
    except Exception:  # noqa: BLE001 - a count is never worth a failure
        pass
    return counts


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


def _relabel_event_labels(claims: list[Claim]) -> tuple[list[Claim], int]:
    """R-PJB12: a Stage-1 relationship labelled like an event predicate becomes
    `relates-to` — only progress.py writes events (G141 §5.1), and a projected
    relationship has no status and no born-closed validity. `predicate_raw` is
    dropped so Stage 3 raises no normalization-audit card: this is a code rail,
    not a vocabulary fold the person could confirm or undo. Counted, no text."""
    n = 0
    for c in claims:
        if is_event(c):
            c.predicate = "relates-to"
            if hasattr(c, "predicate_raw"):
                delattr(c, "predicate_raw")
            n += 1
    if n:
        logger.info(f"Claim pipeline: {n} event-labelled relationship(s) relabelled relates-to")
    return claims, n


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
    """Emit → release → reconcile → write → hold claims over the live entity pages (additive).

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
            Never held (R-HP2).
        name_to_id: Stage 2's ``resolve(...)["name_to_id"]`` — every endpoint is
            keyed through it (R-CS1), and a held name is released onto Stage 2's
            exact verdict for it (R-HP5). ``None`` keeps ``sanitize_id``.

    Returns a dict: ``{"nudges": [...], "audit": [...], "claims_written": int,
    "subjects_written": int, "subjects_skipped": int, "claims_page_less": int,
    "page_less_subjects": [ids], "relabelled_events": int, "claims_held": int,
    "claims_hold_capped": int, "claims_released": int, "claims_waiting": int}``.
    ``claims_page_less`` counts claims neither written nor held (G141 PJ-0b);
    ``page_less_subjects`` stays in memory only (R-CS3: a subject id is a slug
    of a name, so it is never logged); the four hold counts are R-HP12's;
    ``relabelled_events`` is R-PJB12's. Never raises on a missing subject page
    or a pending-store failure — the promotion model owns page creation, and a
    store failure costs the hold, never the cycle's claims (R-HP10).
    """
    today = now_date or str(date.today())
    memory_path = Path(memory_path)

    # ---- Stage 1: emit claims from extraction ----
    owner_id = _owner_page_id(existing_entities, memory_path, settings)
    incoming: list[Claim] = entities_to_claims(
        extracted, memory_path, resolve_id=subject_resolver(name_to_id, owner_id))
    incoming, relabelled = _relabel_event_labels(incoming)
    # Stage-1 only — never the person's extra_claims, never a released claim:
    # the only claims a hold ever takes (R-HP2).
    stage1_ids = {c.id for c in incoming}

    # ---- G141 PJ-0b: release what was held for a name that has a page now ----
    # Released claims go FIRST, so they meet Stage 3 as the page's own claims
    # would have had it existed when they were heard (R-HP6): a newer
    # single-valued claim supersedes them, where the other order would ask.
    existing_by_subject = _load_existing_claims_by_subject(memory_path)
    releases, released, credit = _releases(memory_path, name_to_id, existing_by_subject)
    incoming = released + incoming
    # G61 S1 reads this as "newly written by this pass" — true of a released claim too (R-HP8).
    emitted_ids = stage1_ids | {c.id for c in released}
    if extra_claims:
        incoming = incoming + list(extra_claims)

    # ---- Stage 3: reconcile against existing in-page claims (trust-gated) ----
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
    page_less_subjects: list[str] = []
    page_less_claim_ids: list[str] = []
    page_less_offers: dict[str, list[Claim]] = {}
    for subject, claims in reconciled.items():
        if not claims:
            continue
        filepath = entities_dir / f"{subject}.md"
        if not filepath.exists():
            # G141 PJ-0: not written — the promotion model owns page creation —
            # and never extracted again: this cycle marks the episode processed
            # (`sleep_cycle._mark_episodes_processed`). PJ-0b holds them with the
            # subject's pending entity after this loop; what it cannot hold is counted.
            subjects_skipped += 1
            page_less_subjects.append(subject)
            page_less_claim_ids.extend(c.id for c in claims)
            page_less_offers[subject] = claims
            continue
        try:
            parsed = markdown_parser.parse(filepath)
            # strict guard: if the existing block is unparseable, raise (caught
            # below) instead of overwriting claims we could not read.
            parse_claims(parsed.body, strict=True)
            new_body = write_claims(parsed.body, claims)
            # R-HP8: the conversation a released claim was heard in credits the page.
            credited = _credit_episodes(parsed.frontmatter, credit.get(subject))
            if new_body != parsed.body or credited:
                markdown_parser.write(filepath, parsed.frontmatter, new_body)
            subjects_written += 1
            written_subjects.append(subject)
            claims_written += len(claims)
        except Exception as e:  # never let a single bad page abort the cycle
            logger.warning(
                f"claim write-back skipped for {subject}: {type(e).__name__}: {e}"
            )

    # ---- G141 PJ-0b: settle the pending store — release, then hold (R-HP4, R-HP10) ----
    hold = _settle_store(memory_path, releases, set(written_subjects), page_less_offers, stage1_ids)
    claims_page_less = sum(len(claims) for claims in page_less_offers.values()) - hold["claims_held"]

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
        f"{hold['claims_held']} held for a pending name ({hold['claims_hold_capped']} over the cap), "
        f"{hold['claims_released']} released onto their page, {hold['claims_waiting']} waiting, "
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
        "relabelled_events": relabelled,
        **hold,
    }
