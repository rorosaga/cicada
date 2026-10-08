"""Stage 2: Entity Resolution & Deduplication."""

import asyncio
import functools
import re
from collections import Counter
from typing import Callable

import litellm
from loguru import logger
from thefuzz import fuzz

from api.config import Settings
from api.services import (
    agent_engine, alias_policy, engine_errors, entity_body, json_parse, owner_identity, section_provenance,
)
from api.services.clarification_manager import (
    CONFIDENCE_THRESHOLD,
    ClarificationManager,
)
from api.services.id_utils import sanitize_id
from api.services.vector_index import PendingEntity, SqliteVecIndexer


def endpoint_id(name: str, name_to_id: dict[str, str]) -> str | None:
    """The id Stage 2 resolved ``name`` to, or ``None`` — the edge rule, as one function.

    Exact (lower-cased) first, then the first ``fuzz.ratio > 85`` over
    ``name_to_id`` in insertion order, exactly as the relationship loop in
    :func:`resolve` always did inline. G141 PJ-0 (R-PJ17) made it a function so
    Sleep's claims key their subject and object through the SAME rule as the
    edge between them: a claim used to be keyed by ``sanitize_id(raw name)``,
    so a short name Stage 2 had matched ("Hana" → ``hana-example``) keyed a
    page that did not exist, and the claim was dropped while its edge landed.
    """
    key = (name or "").lower()
    hit = name_to_id.get(key)
    if hit:
        return hit
    for known_name, known_id in name_to_id.items():
        if fuzz.ratio(key, known_name) > 85:
            return known_id
    return None


def _edge_endpoint(name: str, name_to_id: dict[str, str], refs: "owner_identity.SelfReferences") -> str | None:
    """:func:`endpoint_id`, with a speaker reference keyed to the owner page (G169) —
    and to nothing when the bank has none, never to a page named after a pronoun.
    A name a non-person page or entity holds ("Owner" the company) is not one."""
    if refs.is_speaker(name):
        return refs.owner_id
    return endpoint_id(name, name_to_id)


async def resolve(
    extracted: list[dict],
    existing: list[dict],
    settings: Settings,
    *,
    cancel_check: Callable[[], bool] | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> dict:
    """Resolve extracted entities against existing graph. Enforce promotion model.

    ``progress_callback(done, total)`` (Sleep page v5): names finished of the names
    to sort, fired as each one starts and once more at the end. ``total`` is fixed
    when the loop starts (the names left after the exact-name dedup).

    Returns dict with 'changes' (entity updates) and 'relationships' (resolved edges).

    ``cancel_check`` (sleep-control): an optional zero-arg predicate polled at
    the top of every iteration of the per-name judging loop below, and before
    every judge call taken ahead of it (``sleep_resolve_concurrency``). Once it
    starts returning ``True``, no new judge call starts — the ones in flight
    finish, never interrupted — and this returns whatever it has accumulated so far; the
    caller (``sleep_cycle._run_stages``) discards a partial result like this
    entirely on a cancelled cycle, so returning early rather than raising
    keeps this function's contract simple. ``None`` (the default, and every
    existing call site) means "never cancel" — behavior is unchanged.

    Transactional Stage 2 (Devin PR #27 round 1, CRITICAL): every disk
    mutation this stage can make — a new/resolved clarification file
    (``ClarificationManager.create`` / ``.check_organic_resolution``, the
    latter of which can *delete* an inbox item) and a pending-entity index
    write (``SqliteVecIndexer.index_pending_entity`` / ``.promote_from_
    pending`` / ``.rebuild_pending_index``) — used to run INLINE, interleaved
    with the per-name loop, before ``sleep_cycle`` ever got to check
    ``cancel_check()`` and discard the returned ``changes``. A cancel after
    even one name had already left those side effects behind: a dirty bank —
    precisely what "cancel must never leave a dirty bank" promises never
    happens — and worse, an organically-resolved clarification could be
    permanently deleted with no corresponding entity update ever reaching
    Stage 5 to justify it. Silent data loss on an action advertised as safe.

    Fixed by recording every one of those calls into ``pending_actions``
    during the loop — never executing them there — and flushing the list
    (in the same order they were queued) ONLY if the loop ran to completion
    without cancelling. A cancelled call therefore makes ZERO disk writes,
    exactly like every other Stage 1-4 abort point already guarantees; the
    deferred actions are simply dropped along with the (already-discarded)
    return value. Disclosed trade-off: flushing at the end means a pending-
    index write from an early name in THIS SAME loop is no longer visible to
    a ``pending_by_name`` read for a later name in the SAME loop (only a
    PRIOR cycle's committed writes are) — arguably the more correct reading
    of "was this already staged as pending" anyway, and the actual cross-
    cycle promotion-from-pending path this exists for is unaffected.
    """
    disambig_model = (
        getattr(settings, "litellm_disambiguation_model", "") or settings.litellm_model
    )
    logger.info(f"Stage 2 disambiguation model: {disambig_model}")

    existing_by_name: dict[str, dict] = {}
    for e in existing:
        name = e["frontmatter"].get("name", e["id"].replace("-", " ").title())
        if agent_engine.is_runtime_path(str(name)):
            continue  # an old leaked page: never a merge target, endpoint or judge candidate
        existing_by_name[name.lower()] = e
    aliases = _alias_index(existing_by_name)

    # G169: a speaker reference ("User", "the user", "me", "yo", "mí"...) is the
    # bank's owner, never a page of its own. One qualified decision
    # (`owner_identity.SelfReferences`), built from the same inputs by Sleep's
    # claims (`claim_pipeline`) and wikilink edges (`wikilink_resolver`).
    refs = owner_identity.self_references(existing, extracted, getattr(settings, "memory_path", None), settings)
    owner_id = refs.owner_id
    owner_entity = next((e for e in existing if e["id"] == owner_id), None) if owner_id else None
    self_entities = [
        entity for extraction in extracted for entity in extraction.get("entities", [])
        if refs.is_speaker(entity.get("name", ""), entity.get("type"))
    ]
    if self_entities:
        logger.info(f"Stage 2: {len(self_entities)} self-reference(s) "
                    + ("merged into the owner page" if owner_entity else "dropped (this bank has no owner page)"))

    # Count mentions across episodes for promotion threshold
    mention_counts: Counter = Counter()
    episode_mentions: dict[str, set[str]] = {}  # entity_name -> set of episode_ids

    all_entities: list[dict] = []
    all_relationships: list[dict] = []
    # episode_id -> list of entity names mentioned in that episode
    episode_cooccurrences: dict[str, list[str]] = {}
    # Count how many relationships each entity_name participates in within a
    # single episode. Signals "substantively discussed in this conversation".
    in_episode_relationship_count: dict[tuple[str, str], int] = {}

    for extraction in extracted:
        episode_id = extraction["episode_id"]
        per_episode_names: list[str] = []
        for entity in extraction.get("entities", []):
            name = entity["name"]
            if refs.is_speaker(name, entity.get("type")):
                continue
            if agent_engine.is_runtime_path(name):
                logger.debug("Stage 2: dropped an entity named for the engine runtime path")
                continue
            mention_counts[name.lower()] += 1
            episode_mentions.setdefault(name.lower(), set()).add(episode_id)
            all_entities.append(entity)
            if name not in per_episode_names:
                per_episode_names.append(name)
        if per_episode_names:
            episode_cooccurrences[episode_id] = per_episode_names

        episode_relationships = extraction.get("relationships", [])
        all_relationships.extend(episode_relationships)
        for rel in episode_relationships:
            for endpoint in (rel.get("source"), rel.get("target")):
                if not endpoint:
                    continue
                key = (episode_id, str(endpoint).lower())
                in_episode_relationship_count[key] = (
                    in_episode_relationship_count.get(key, 0) + 1
                )

    # Track name -> final entity_id so we can resolve relationships to existing IDs
    name_to_id: dict[str, str] = {}

    # First, register all existing entities
    for existing_name, existing_data in existing_by_name.items():
        name_to_id[existing_name] = existing_data["id"]

    # Deduplicate entities by exact normalized name: the strongest extraction
    # (first on ties) is judged and promoted for the name. Every other one is
    # kept beside it and folded into whatever that judgment produces — each is a
    # conversation that mentioned the page, with its own facts and G118 evidence,
    # and used to be dropped whole, credit included.
    best_by_name: dict[str, dict] = {}
    extractions_by_name: dict[str, list[dict]] = {}
    for entity in all_entities:
        name_lower = entity["name"].lower()
        extractions_by_name.setdefault(name_lower, []).append(entity)
        current = best_by_name.get(name_lower)
        if current is None or entity.get("confidence", 0) > current.get("confidence", 0):
            best_by_name[name_lower] = entity

    # Pending store — sub-threshold entities from previous cycles
    try:
        indexer = SqliteVecIndexer(settings.memory_path)
    except Exception as e:
        logger.debug(f"LEANN pending store unavailable: {e}")
        indexer = None

    clarifier = ClarificationManager(settings.memory_path)

    # LLM disambiguation cache — keyed on (new_name_lower, candidate_id). Same
    # pair can come up more than once inside one cycle and we do not want to
    # pay for duplicate judge calls.
    llm_match_cache: dict[tuple[str, str], str] = {}
    resolved_updates: dict[str, dict] = {}
    resolved_creates: dict[str, dict] = {}

    # Transactional Stage 2 (see the docstring above): every clarifier/index
    # WRITE the loop below would have made inline is recorded here instead —
    # (callable, args, kwargs), executed in this exact order only if the
    # loop completes without cancelling. `cancelled` records whether it did.
    pending_actions: list[tuple[Callable, tuple, dict]] = []
    cancelled = False

    # A self-reference's facts are the owner's: they land on the owner page, under
    # its own name and type (a "User" concept must not retype or rename it). With
    # no owner page they are dropped — never a `user` page, never a pending line,
    # never a "Who is User?" question (R-CS2).
    if owner_entity is not None:
        owner_fm = owner_entity.get("frontmatter") or {}
        for entity in self_entities:
            _merge_into_update(
                updates_by_id=resolved_updates,
                existing_entity=owner_entity,
                incoming={
                    **entity,
                    "name": owner_fm.get("name") or entity.get("name"),
                    "type": "person",
                    "aliases": [a for a in entity.get("aliases") or [] if not refs.is_speaker(a)],
                },
            )

    # Process more specific names first so "Bob Example" becomes the
    # canonical in-cycle entity and "Bob" can merge into it rather than
    # the other way around.
    ordered_entities = sorted(
        best_by_name.items(),
        key=lambda item: _specificity_key(item[1]),
        reverse=True,
    )

    # What a name an alias brings to its page was connected to in this batch:
    # the judge's context for "same thing, or another thing with the same letters?".
    connections = {
        name_lower: _batch_connections(name_lower, all_relationships, episode_mentions, episode_cooccurrences, refs)
        for name_lower, _ in best_by_name.items() if name_lower.strip() in aliases
    }

    total_names = len(ordered_entities)
    if progress_callback is not None:
        progress_callback(0, total_names)
    # The judge calls against pages on disk run ahead of this loop, bounded
    # (``sleep_resolve_concurrency``; 1 is the plain serial loop). Every
    # decision is still made here, in this order (``_Lookahead``).
    concurrency = max(1, int(getattr(settings, "sleep_resolve_concurrency", 1) or 1))
    lookahead = (
        _Lookahead(_lookahead_plan(ordered_entities, existing_by_name, aliases), settings=settings,
                   cache=llm_match_cache, concurrency=concurrency, cancel_check=cancel_check,
                   connections=connections)
        if concurrency > 1 else None
    )
    try:
        for done_names, (name_lower, entity) in enumerate(ordered_entities):
            if progress_callback is not None and done_names:
                progress_callback(done_names, total_names)
            # Sleep-control checkpoint. Checked BEFORE each name's own (possibly
            # LLM-calling) judge — never mid-judge — so a cancel stops taking new
            # names without ever interrupting a call already in flight (the
            # lookahead polls the same predicate before each of its calls).
            if cancel_check is not None and cancel_check():
                cancelled = True
                break
            name = entity["name"]
            siblings = [e for e in extractions_by_name.get(name_lower, []) if e is not entity]
            match = _find_direct_candidate_match(
                new_entity=entity,
                existing_by_name=existing_by_name,
                created_by_id=resolved_creates,
            )
            if match is not None and lookahead is not None:
                lookahead.discard(done_names)
            if match is None:
                match = await _find_llm_candidate_match(
                    new_entity=entity,
                    existing_by_name=existing_by_name,
                    created_by_id=resolved_creates,
                    cache=llm_match_cache,
                    settings=settings,
                    aliases=aliases,
                    connections=connections.get(name_lower, ""),
                    prejudged=await lookahead.take(done_names) if lookahead is not None else None,
                    gate=lookahead.gate if lookahead is not None else None,
                )

            if match is not None and match["decision"] == "same":
                candidate = match["candidate"]
                name_to_id[name_lower] = candidate["id"]
                # Deferred (see the transactional-Stage-2 docstring above): this
                # can DELETE an inbox item, which must never happen for a name
                # whose match a cancellation is about to discard.
                pending_actions.append((
                    clarifier.check_organic_resolution,
                    (),
                    {"entity_name": name, "confidence": float(entity.get("confidence", 0.0) or 0.0)},
                ))

                for incoming in (entity, *siblings):
                    if candidate["source"] == "existing":
                        _merge_into_update(
                            updates_by_id=resolved_updates,
                            existing_entity=candidate["data"],
                            incoming=incoming,
                        )
                    else:
                        _merge_into_create(resolved_creates[candidate["id"]], incoming)
                continue

            ambiguous_match = match is not None and match["decision"] == "unsure"

            # New entity — check promotion threshold
            episodes_seen = len(episode_mentions.get(name_lower, set()))
            linked_to_existing = _is_linked_to_existing(name, all_relationships, existing_by_name, owner_id=owner_id, refs=refs)

            # Promote if the entity is already in pending from a previous cycle
            pending_entry = None
            if indexer is not None:
                try:
                    pending_entry = indexer.pending_by_name(name)
                except Exception:
                    pending_entry = None

            substantively_discussed = _is_substantively_discussed(
                entity,
                in_episode_relationship_count=in_episode_relationship_count,
            )

            should_promote = (
                episodes_seen >= settings.sleep_promotion_threshold
                or linked_to_existing
                or pending_entry is not None
                or substantively_discussed
            )

            if ambiguous_match:
                pending_actions.append((
                    _create_duplicate_clarification,
                    (),
                    {"clarifier": clarifier, "entity": entity, "candidate": match["candidate"]},
                ))

            if should_promote and not ambiguous_match:
                entity_id = sanitize_id(name)
                name_to_id[name_lower] = entity_id
                if pending_entry is not None:
                    merged_history = list(entity.get("history_entries", []) or [])
                    for h in pending_entry.history_entries or []:
                        if h not in merged_history:
                            merged_history.append(h)
                    if merged_history:
                        entity["history_entries"] = merged_history
                resolved_creates[entity_id] = {
                    "id": entity_id,
                    "action": "create",
                    "entity": entity,
                    "existing": None,
                    "source_episode": entity.get("source_episode", ""),
                    "source_episodes": [entity.get("source_episode", "")] if entity.get("source_episode") else [],
                    "source_episode_timestamp": entity.get("source_episode_timestamp"),
                    "source_episode_timestamps": [entity.get("source_episode_timestamp")] if entity.get("source_episode_timestamp") else [],
                    "source_episode_days": _source_days(entity),
                    "untimed": bool(entity.get("untimed")),
                    "trigger": "sleep/promotion",
                }
                for sibling in siblings:
                    _merge_into_create(resolved_creates[entity_id], sibling)
                # Deferred (same reasoning as the "same"-match branch above).
                pending_actions.append((
                    clarifier.check_organic_resolution,
                    (),
                    {"entity_name": name, "confidence": float(entity.get("confidence", 0.0) or 0.0)},
                ))
                if indexer is not None and pending_entry is not None:
                    pending_actions.append((indexer.promote_from_pending, (name,), {}))
            else:
                confidence = float(entity.get("confidence", 0.3) or 0.3)
                if confidence < CONFIDENCE_THRESHOLD and not ambiguous_match:
                    pending_actions.append((
                        clarifier.create,
                        (),
                        {
                            "entity_name": name,
                            "source_episode": entity.get("source_episode", ""),
                            "uncertainty_type": _infer_uncertainty_type(entity),
                            "suggested_classification": (
                                f"{entity.get('type', 'concept')} — "
                                f"{(entity.get('description') or '')[:120]}"
                            ),
                            "suggested_confidence": confidence,
                            "source_context": entity.get("description", "") or "",
                            "source_episode_timestamp": entity.get("source_episode_timestamp"),
                        },
                    ))

                if indexer is not None:
                    # One pending line per name: what every mention said rides on it
                    # (the line keeps the strongest mention's episode, as before).
                    parked = entity
                    for sibling in siblings:
                        parked = _merge_entity_payload(parked, sibling)
                    pending_actions.append((
                        indexer.index_pending_entity,
                        (PendingEntity(
                            name=name,
                            type=entity.get("type", "concept"),
                            description=parked.get("description", "") or "",
                            source_episode=entity.get("source_episode", ""),
                            confidence=confidence,
                            tags=list(parked.get("tags", []) or []),
                            history_entries=list(parked.get("history_entries", []) or []),
                        ),),
                        {},
                    ))

    finally:
        if lookahead is not None:
            # Starts nothing more and waits out the calls in flight, on every exit.
            await lookahead.close()
    if lookahead is not None and lookahead.error is not None and not cancelled:
        raise lookahead.error  # a plan limit met ahead of the loop is still the batch's pause

    if progress_callback is not None and not cancelled:
        progress_callback(total_names, total_names)
    resolved = list(resolved_updates.values()) + list(resolved_creates.values())

    # Resolve relationships — only keep edges where both endpoints survived promotion
    resolved_edges: list[dict] = []
    seen_edges: set[tuple[str, str, str]] = set()
    for rel in all_relationships:
        label = rel.get("label", "related to")
        # Self-references first (G169), then exact, then fuzzy — one rule,
        # shared with Sleep's claims (G141 PJ-0, `claim_pipeline.subject_resolver`).
        source_id = _edge_endpoint(rel.get("source", ""), name_to_id, refs)
        target_id = _edge_endpoint(rel.get("target", ""), name_to_id, refs)

        if source_id and target_id and source_id != target_id:
            key = (source_id, target_id, label.lower())
            if key not in seen_edges:
                seen_edges.add(key)
                resolved_edges.append({
                    "source": source_id,
                    "target": target_id,
                    "label": label,
                })

    # Transactional Stage 2 (see the module docstring above): flush every
    # deferred clarifier/index write ONLY if the loop was never cancelled —
    # a cancelled call makes ZERO disk writes, in the same exact order the
    # loop would have made them inline. Each is wrapped individually so one
    # failed write (a duplicate clarification collision, a locked index
    # file) can never stop the rest from applying — the same resilience
    # every original inline call site already had on its own.
    if not cancelled:
        for fn, args, kwargs in pending_actions:
            try:
                fn(*args, **kwargs)
            except Exception as e:
                logger.debug(
                    f"Deferred Stage 2 side effect failed "
                    f"({getattr(fn, '__name__', fn)}): {type(e).__name__}: {e}"
                )

        # Rebuild the pending LEANN index once, after all sub-threshold
        # entities have been appended to the store. Rebuilding per-entity is
        # O(N^2) and sends every passage back to OpenAI on every call.
        if indexer is not None:
            try:
                indexer.rebuild_pending_index()
            except Exception as e:
                logger.debug(f"Pending index rebuild failed: {e}")
    elif pending_actions:
        logger.info(
            f"Stage 2 cancelled — discarding {len(pending_actions)} deferred "
            f"clarifier/index write(s) instead of applying them; nothing was "
            f"written to disk"
        )

    return {
        "changes": resolved,
        "relationships": resolved_edges,
        "episode_cooccurrences": episode_cooccurrences,
        # G141 PJ-0 (R-PJ17): the map the edges above resolved through, so
        # Stage 5.56's claims land on the same pages (`claim_pipeline`).
        "name_to_id": dict(name_to_id),
        # G169: the qualified self-reference decision this stage keyed by.
        "self_references": refs,
    }


def existing_by_name(existing: list[dict]) -> dict[str, dict]:
    """The ``name.lower() -> entity`` index ``resolve`` builds at its top (the
    four lines at the head of that function), exposed so a caller that only
    needs the Stage-2 *judgment* (G102 recon) indexes the graph the same way."""
    out: dict[str, dict] = {}
    for e in existing:
        name = e["frontmatter"].get("name", e["id"].replace("-", " ").title())
        out[str(name).lower()] = e
    return out


async def match_existing(
    entity: dict, existing_by_name: dict[str, dict], settings: Settings, *, cache: dict | None = None
) -> str | None:
    """Is ``entity`` an EXISTING page? The Stage-2 judgment alone (G102 R5).

    Exactly the two matchers ``resolve`` runs per name — the strict/fuzzy
    ``_find_direct_candidate_match`` then the type-gated, token-gated
    ``_find_llm_candidate_match`` with the same judge and cache — and nothing
    else: no promotion, no page creation, no clarification. ``resolve`` itself
    would (a) create a page for anything clearing the promotion threshold,
    (b) queue a "Who is X?" clarification for every low-confidence name — an
    inbox flood from bookmark blurbs — and (c) promote pending entries; the
    promotion rule (CLAUDE.md) says a single link mention must never create
    an entity. Returns the existing id only on a ``same`` verdict against an
    on-disk entity; ``unsure`` is ``None`` (a bookmark blurb must never open
    a "Who is X?" inbox item), and a first mention is left to the caller to
    record as a pending candidate — the promotion model's rung 1 — so a
    later conversation mention still promotes it. An engine failure inside
    the judge propagates (G74(a)); the caller decides what that means.
    """
    cache = cache if cache is not None else {}
    match = _find_direct_candidate_match(new_entity=entity, existing_by_name=existing_by_name, created_by_id={})
    if match is None:
        match = await _find_llm_candidate_match(
            new_entity=entity, existing_by_name=existing_by_name, created_by_id={}, cache=cache, settings=settings,
        )
    if match is not None and match["decision"] == "same" and match["candidate"].get("source") == "existing":
        return match["candidate"]["id"]
    return None


def _specificity_key(entity: dict) -> tuple[int, int, float]:
    name = (entity.get("name") or "").strip()
    tokens = _name_tokens(name)
    confidence = float(entity.get("confidence", 0.0) or 0.0)
    return (len(tokens), len(name), confidence)


def _merge_entity_payload(base: dict, incoming: dict) -> dict:
    merged = dict(base)
    merged["name"] = _preferred_entity_name(
        base.get("name", ""),
        incoming.get("name", ""),
        float(base.get("confidence", 0.0) or 0.0),
        float(incoming.get("confidence", 0.0) or 0.0),
    )
    if not merged.get("type") or merged.get("type") == "concept":
        merged["type"] = incoming.get("type", merged.get("type", "concept"))
    # A proposal only the other input made is still proposed (both re-pass their
    # rails where they are written: `agent_class`, `fact_sources.propose_site`).
    for field in ("website", "decay_class"):
        if not merged.get(field) and incoming.get(field):
            merged[field] = incoming[field]
    merged["confidence"] = max(
        float(base.get("confidence", 0.0) or 0.0),
        float(incoming.get("confidence", 0.0) or 0.0),
    )

    # One effective summary per input — `summary`, falling back to the legacy
    # `description` (G169 review r2) — and the longer one is the merge's summary
    # AND, when either input carried one, its description (synthesis runs on a
    # `description`, so a summary-only merge still takes the deterministic path).
    # Every other distinct one is still something said about it: kept, once, as a key fact.
    base_text, incoming_text = _effective_summary(base), _effective_summary(incoming)
    chosen = incoming_text if len(incoming_text) > len(base_text) else base_text
    merged["summary"] = chosen
    had_description = (base.get("description") or "").strip() or (incoming.get("description") or "").strip()
    merged["description"] = chosen if had_description else ""

    # Additive fields are unions (G169 review): two extractions of one thing —
    # "User" and "me" both landing on the owner page — each carry their own facts,
    # links, questions and aliases, and the first payload's lists used to win whole.
    key_facts = _union_text(base.get("key_facts"), incoming.get("key_facts"))
    folded = " ".join(chosen.split()).lower()
    for text in (base_text, incoming_text, *_effective_summaries(base), *_effective_summaries(incoming)):
        if text and " ".join(text.split()).lower() not in folded:
            key_facts = _union_text(key_facts, [text])
    if key_facts:
        merged["key_facts"] = key_facts
    for field in ("open_questions", "aliases"):
        values = _union_text(base.get(field), incoming.get(field))
        if values:
            merged[field] = values
    links = _union_links(base.get("links"), incoming.get("links"))
    if links:
        merged["links"] = links

    merged["tags"] = sorted(
        set(base.get("tags", []) or []) | set(incoming.get("tags", []) or [])
    )
    merged["history_entries"] = _dedupe_history_entries(
        list(base.get("history_entries", []) or [])
        + list(incoming.get("history_entries", []) or [])
    )
    merged["source_episode"] = (
        incoming.get("source_episode")
        or base.get("source_episode")
        or ""
    )
    merged["source_episode_timestamp"] = _latest_timestamp(
        base.get("source_episode_timestamp"),
        incoming.get("source_episode_timestamp"),
    )
    merged[section_provenance.INPUTS] = section_provenance.merge_selected(
        base, incoming, merged,
    )
    return merged


def _effective_summary(entity: dict) -> str:
    """An input's one orientation line: ``summary``, else the legacy ``description``."""
    return str(entity.get("summary") or entity.get("description") or "").strip()


def _effective_summaries(entity: dict) -> tuple[str, ...]:
    """Both orientation fields of one input, when it carries two different ones."""
    return tuple(str(entity.get(k) or "").strip() for k in ("summary", "description"))


def _union_text(*lists) -> list:
    """Every distinct string, first spelling and order kept (case-insensitive)."""
    out: list = []
    seen: set[str] = set()
    for values in lists:
        for value in values or []:
            key = " ".join(str(value).split()).lower()
            if key and key not in seen:
                seen.add(key)
                out.append(value)
    return out


def _union_links(*lists) -> list[dict]:
    """Every distinct link by its URL, the first entry for a URL kept."""
    out: list[dict] = []
    seen: set[str] = set()
    for values in lists:
        for link in values or []:
            url = str((link or {}).get("url") or "").strip() if isinstance(link, dict) else ""
            if url and url not in seen:
                seen.add(url)
                out.append(link)
    return out


def _preferred_entity_name(
    left: str,
    right: str,
    left_confidence: float,
    right_confidence: float,
) -> str:
    if not left:
        return right
    if not right:
        return left
    left_key = (len(_name_tokens(left)), len(left), left_confidence)
    right_key = (len(_name_tokens(right)), len(right), right_confidence)
    return right if right_key > left_key else left


def _dedupe_history_entries(entries: list[dict]) -> list[dict]:
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for entry in entries:
        event = str(entry.get("event", "")).strip()
        event_date = str(entry.get("date", "")).strip()
        if not event:
            continue
        key = (event_date, event)
        if key in seen:
            continue
        seen.add(key)
        out.append(entry)
    return out


def _source_days(entity: dict) -> list[str]:
    """G194: the conversation's day as Stage 1 resolved it (timestamp, else the id's date) — prompt-only metadata
    for Stage 3's merge and contradiction prompts; nothing writes it to a page."""
    day = entity.get("source_episode_day")
    return [str(day)] if day else []


def _merge_into_create(change: dict, incoming: dict) -> None:
    """Fold one more extraction into an in-cycle create: its payload and its credit."""
    change["entity"] = _merge_entity_payload(change.get("entity", {}) or {}, incoming)
    _append_change_source(change, incoming)


def _append_change_source(change: dict, entity: dict) -> None:
    episode_id = entity.get("source_episode", "")
    if episode_id:
        episodes = change.setdefault("source_episodes", [])
        if episode_id not in episodes:
            episodes.append(episode_id)

    timestamp = entity.get("source_episode_timestamp")
    if timestamp:
        timestamps = change.setdefault("source_episode_timestamps", [])
        if timestamp not in timestamps:
            timestamps.append(timestamp)

    for day in _source_days(entity):
        days = change.setdefault("source_episode_days", [])
        if day not in days:
            days.append(day)

    # Only memory export entries in the change: its facts are new, but nothing came up ("facts yes, activity no").
    change["untimed"] = bool(change.get("untimed")) and bool(entity.get("untimed"))
    change["source_episode"] = episode_id or change.get("source_episode", "")
    latest = _latest_timestamp(
        change.get("source_episode_timestamp"),
        timestamp,
    )
    if latest:
        change["source_episode_timestamp"] = latest


def _merge_into_update(
    updates_by_id: dict[str, dict],
    existing_entity: dict,
    incoming: dict,
) -> None:
    entity_id = existing_entity["id"]
    current = updates_by_id.get(entity_id)
    if current is None:
        current = {
            "id": entity_id,
            "action": "update",
            "entity": incoming,
            "existing": existing_entity,
            "source_episode": incoming.get("source_episode", ""),
            "source_episodes": [incoming.get("source_episode", "")] if incoming.get("source_episode") else [],
            "source_episode_timestamp": incoming.get("source_episode_timestamp"),
            "source_episode_timestamps": [incoming.get("source_episode_timestamp")] if incoming.get("source_episode_timestamp") else [],
            "source_episode_days": _source_days(incoming),
            "untimed": bool(incoming.get("untimed")),
            "trigger": "sleep/extraction",
        }
        updates_by_id[entity_id] = current
        return

    current["entity"] = _merge_entity_payload(current.get("entity", {}) or {}, incoming)
    _append_change_source(current, incoming)


def _find_direct_candidate_match(
    new_entity: dict,
    existing_by_name: dict[str, dict],
    created_by_id: dict[str, dict],
) -> dict | None:
    new_name = (new_entity.get("name") or "").strip()
    new_name_lower = new_name.lower()

    existing_match = existing_by_name.get(new_name_lower)
    if existing_match is not None:
        return {
            "decision": "same",
            "candidate": {"source": "existing", "id": existing_match["id"], "data": existing_match},
        }

    for existing_name, existing_data in existing_by_name.items():
        if fuzz.ratio(new_name_lower, existing_name) > 85:
            return {
                "decision": "same",
                "candidate": {"source": "existing", "id": existing_data["id"], "data": existing_data},
            }

    for candidate_id, create_change in created_by_id.items():
        candidate_entity = create_change.get("entity", {}) or {}
        candidate_name = str(candidate_entity.get("name", "")).lower()
        if not candidate_name:
            continue
        if candidate_name == new_name_lower or fuzz.ratio(new_name_lower, candidate_name) > 85:
            return {
                "decision": "same",
                "candidate": {"source": "created", "id": candidate_id, "data": create_change},
            }

    return None


def _page_aliases(page: dict) -> list[str]:
    values = (page.get("frontmatter") or {}).get("aliases")
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return []
    return [text for text in (str(v or "").strip() for v in values) if text]


def _alias_index(existing_by_name: dict[str, dict]) -> dict[str, list[dict]]:
    """``alias.lower() -> the pages listing it`` (frontmatter ``aliases``, which Stage 5
    unions from every extraction merged into the page and a manual merge fills with the
    loser's name). A hit makes the page a judge candidate, never a decision: one page
    holding an alias today says nothing about the next thing with those letters."""
    index: dict[str, list[dict]] = {}
    for page in existing_by_name.values():
        for alias in _page_aliases(page):
            if alias_policy.is_reference(alias):
                continue  # "the lock" names nothing on its own; a lead from it is a wasted judge call
            holders = index.setdefault(alias.lower(), [])
            if all(held["id"] != page["id"] for held in holders):
                holders.append(page)
    return index


#: The most connections of each kind a judge call is shown for one name.
ALIAS_CONTEXT_CONNECTIONS = 12


def _batch_connections(
    name_lower: str,
    relationships: list[dict],
    episode_mentions: dict[str, set[str]],
    episode_cooccurrences: dict[str, list[str]],
    refs: "owner_identity.SelfReferences",
) -> str:
    """What ``name_lower`` was connected to in this batch, as bullet lines: its
    relationships, then the names mentioned in the same conversations. A speaker
    reference is left out (everything the person mentions is linked to them).
    Built before the loop from the extractions alone, so a judgment that reads it
    is still a function of the name and the bank (``_Lookahead``)."""
    edges: list[str] = []
    for rel in relationships:
        source, target = str(rel.get("source") or ""), str(rel.get("target") or "")
        label = str(rel.get("label") or "related to")
        if source.lower() == name_lower and target and not refs.is_speaker(target):
            line = f"- {label} {target}"
        elif target.lower() == name_lower and source and not refs.is_speaker(source):
            line = f"- {source} {label} it"
        else:
            continue
        if line not in edges:
            edges.append(line)
    alongside: list[str] = []
    for episode_id in sorted(episode_mentions.get(name_lower, ())):
        for other in episode_cooccurrences.get(episode_id, ()):
            if other.lower() != name_lower and other not in alongside:
                alongside.append(other)
    lines = edges[:ALIAS_CONTEXT_CONNECTIONS]
    if alongside:
        lines.append("- mentioned alongside: " + ", ".join(alongside[:ALIAS_CONTEXT_CONNECTIONS]))
    return "\n".join(lines)


def _create_duplicate_clarification(
    clarifier: ClarificationManager,
    entity: dict,
    candidate: dict,
) -> None:
    candidate_name = _candidate_display_name(candidate)
    try:
        clarifier.create(
            entity_name=entity.get("name", "unknown"),
            source_episode=entity.get("source_episode", ""),
            uncertainty_type=f"Possible duplicate of {candidate_name}",
            suggested_classification=(
                f"{entity.get('type', 'concept')} — "
                f"could refer to the same entity as {candidate_name}"
            ),
            suggested_confidence=float(entity.get("confidence", 0.0) or 0.0),
            source_context=(
                (entity.get("description") or "").strip()
                or f"Could not safely decide whether this refers to {candidate_name}."
            ),
            source_episode_timestamp=entity.get("source_episode_timestamp"),
        )
    except Exception as e:
        logger.debug(
            f"Failed to create duplicate clarification for {entity.get('name', 'unknown')}: {e}"
        )


def _candidate_display_name(candidate: dict) -> str:
    if candidate["source"] == "existing":
        fm = candidate["data"].get("frontmatter", {}) or {}
        return str(fm.get("name", candidate["data"]["id"]))
    entity = candidate["data"].get("entity", {}) or {}
    return str(entity.get("name", candidate["id"]))


def _candidate_type(candidate: dict) -> str:
    if candidate["source"] == "existing":
        fm = candidate["data"].get("frontmatter", {}) or {}
        return str(fm.get("type", "concept")).lower()
    entity = candidate["data"].get("entity", {}) or {}
    return str(entity.get("type", "concept")).lower()


def _candidate_description(candidate: dict) -> str:
    if candidate["source"] == "existing":
        return candidate["data"].get("body", "") or ""
    entity = candidate["data"].get("entity", {}) or {}
    description = (entity.get("description") or "").strip()
    history = entity.get("history_entries", []) or []
    if history:
        lines = []
        for entry in history:
            event = str(entry.get("event", "")).strip()
            event_date = str(entry.get("date", "")).strip()
            if not event:
                continue
            lines.append(f"{event_date}: {event}" if event_date else event)
        if lines:
            return description + "\n" + "\n".join(lines)
    return description


#: The order a page's sections are shown to the judge for an alias candidate:
#: what it is and what it is connected to before its timeline, so the judge's
#: 2,000-character cut never drops them behind a long history.
_ALIAS_CONTEXT_SECTIONS = ("", "Summary", "Key Facts", "Related", "History", "Links", "Open Questions")


def _alias_page_context(page: dict) -> str:
    """The page as the judge sees it when an alias brought it: its other names on
    record, then summary, key facts and connections ahead of the rest."""
    from api.services.claims import strip_claims_block

    fm = page.get("frontmatter") or {}
    sections = entity_body.parse_sections(strip_claims_block(page.get("body", "") or ""))
    parts: list[str] = []
    names = [str(fm.get("name") or ""), *_page_aliases(page)]
    others = [n for n in dict.fromkeys(names[1:]) if n and n != names[0]]
    if others:
        parts.append("Other names on record: " + ", ".join(others))
    order = [*_ALIAS_CONTEXT_SECTIONS, *(t for t in sections if t not in _ALIAS_CONTEXT_SECTIONS)]
    for title in order:
        text = (sections.get(title) or "").strip()
        if text:
            parts.append(f"## {title}\n{text}" if title else text)
    return "\n\n".join(parts)


def _latest_timestamp(left: str | None, right: str | None) -> str | None:
    candidates = [c for c in (left, right) if c]
    if not candidates:
        return None
    return max(candidates)


def _is_linked_to_existing(
    name: str, relationships: list[dict], existing: dict[str, dict], *, owner_id: str | None = None,
    refs: "owner_identity.SelfReferences | None" = None,
) -> bool:
    """Check if entity is linked to a high-confidence existing entity.

    The owner's page never counts (G169): everything the person talks about is
    linked to them, so that link is no sign a first mention matters — the
    promotion rule would otherwise promote every name on its first mention."""
    for rel in relationships:
        partner = None
        if rel.get("source", "").lower() == name.lower():
            partner = rel.get("target", "").lower()
        elif rel.get("target", "").lower() == name.lower():
            partner = rel.get("source", "").lower()

        speaker = refs.is_speaker(partner) if refs is not None else owner_identity.is_self_reference(partner or "")
        if partner and speaker:
            continue
        if partner and partner in existing:
            if owner_id and existing[partner]["id"] == owner_id:
                continue
            confidence = existing[partner]["frontmatter"].get("confidence", 0)
            if confidence >= 0.6:
                return True
    return False


SUBSTANTIVE_CONFIDENCE = 0.75
SUBSTANTIVE_DESCRIPTION_CHARS = 200
SUBSTANTIVE_HISTORY_ENTRIES = 2
SUBSTANTIVE_RELATIONSHIP_COUNT = 2


def _is_substantively_discussed(
    entity: dict,
    in_episode_relationship_count: dict[tuple[str, str], int],
) -> bool:
    """Decide whether a single-episode entity was discussed deeply enough to promote.

    The extractor's own `confidence` field is defined as "how substantive the
    discussion was", so a high score plus a meaty description is the strongest
    signal. We also promote when the extractor produced multiple history
    entries (indicating a timeline worth preserving) or when the entity
    connects to several other entities within the same conversation.
    """
    confidence = float(entity.get("confidence", 0.0) or 0.0)
    description = (entity.get("description") or "").strip()
    history_entries = entity.get("history_entries", []) or []

    if (
        confidence >= SUBSTANTIVE_CONFIDENCE
        and len(description) >= SUBSTANTIVE_DESCRIPTION_CHARS
    ):
        return True

    if len(history_entries) >= SUBSTANTIVE_HISTORY_ENTRIES:
        return True

    episode_id = entity.get("source_episode", "")
    name_lower = (entity.get("name") or "").lower()
    if episode_id and name_lower:
        rel_count = in_episode_relationship_count.get((episode_id, name_lower), 0)
        if rel_count >= SUBSTANTIVE_RELATIONSHIP_COUNT:
            return True

    return False


# ---------- LLM disambiguation ----------
#
# The fuzz.ratio threshold catches typos and minor spelling variants but it
# fails completely when one name is a strict subset of another — e.g.
# "Francesco" and "Francesco Baldissera" score around 62, well below the 85
# cutoff. The resolver used to treat those as two different entities, which
# is how a single person ended up split across multiple Topics rows.
#
# We fix this with a token-overlap pre-filter plus a one-shot LLM judge. The
# pre-filter is cheap and only forwards real candidates to the LLM, so the
# number of calls per cycle is bounded by the number of name collisions, not
# the size of the graph.

# Tokens that don't carry identity on their own. A shared "the" between two
# names is not a reason to ask the LLM anything.
_STOPWORD_TOKENS = {
    "the", "a", "an", "of", "and", "or", "for", "to", "in", "on", "at",
    "de", "del", "la", "el", "los", "las",  # common Spanish fillers a bank's data hits often
}


_NAME_TOKEN_RE = re.compile(r"[\w'-]+")


@functools.lru_cache(maxsize=65536)
def _name_tokens(name: str) -> frozenset[str]:
    """Lowercased content tokens from an entity name, stopwords removed.

    Memoised: Stage 2 asks it of every page in the bank for every name a batch extracted
    (``_existing_llm_candidates``) — ~10^5–10^6 regex runs on a large bank, on the event loop."""
    raw = _NAME_TOKEN_RE.findall((name or "").lower())
    return frozenset(t for t in raw if t and t not in _STOPWORD_TOKENS and len(t) >= 2)


def _share_content_token(a: str, b: str) -> bool:
    return bool(_name_tokens(a) & _name_tokens(b))


_DISAMBIG_PROMPT = """You are deciding whether two entity entries from a personal knowledge graph refer to the same real-world thing.

Both entries have overlapping names (for example a bare first name and that same first name with a surname) but the existing one was built from different conversations, so you need to look at the descriptions and decide whether merging them would be correct.
{alias_note}
ENTITY A (existing in graph)
Name: {existing_name}
Type: {existing_type}
Description:
{existing_body}

ENTITY B (new extraction)
Name: {new_name}
Type: {new_type}
Description:
{new_description}{new_connections}

Guidelines:
- Say SAME only when the descriptions clearly point at the same real person, project, company, concept, tool, deadline, skill, or location. Shared last names alone are not enough. Shared first names alone are definitely not enough.
- Say SAME when one description is a vague subset of the other and nothing in either description contradicts the merge.
- Say DIFFERENT when the descriptions place the entities in clearly different contexts (different roles, different companies, different cities) or when one description is empty and the names don't obviously line up.
- Say UNSURE when there is overlap in the name tokens but the descriptions are too weak to merge safely. If you are hesitating, return UNSURE.
- If the type fields disagree (e.g. person vs project), they are not the same.

Respond with JSON only:
{{"decision": "same" | "different" | "unsure", "reason": "one short sentence"}}
"""

# An alias hit is a lead, never a decision (2026-10-08): acronyms, short forms
# and first names are shared by different things, so the judge is told the
# page recorded the name and asked to decide on the context.
_ALIAS_NOTE = """
Entity A's page already lists "{new_name}" among the other names it goes by (its aliases), so the names need not share a word. That is a lead, not proof: acronyms, short forms and first names are often shared by different things. Say SAME only when B's description and connections fit A's; say DIFFERENT when they point at something else; say UNSURE when there is too little to tell.
"""


async def _llm_judge_same_entity(
    new_name: str,
    new_type: str,
    new_description: str,
    existing_name: str,
    existing_type: str,
    existing_body: str,
    settings: Settings,
    *,
    recorded_alias: bool = False,
    new_connections: str = "",
) -> str:
    """One LLM call: same, different, or unsure.

    ``recorded_alias``: the page already lists ``new_name`` among its aliases —
    the prompt says so, and that an alias is a lead, not proof
    (``_ALIAS_NOTE``); ``new_connections`` is what the name was connected to in
    the batch. Without them the prompt is the plain one, byte for byte."""
    from api.services.claims import strip_claims_block

    if new_type and existing_type and new_type.lower() != existing_type.lower():
        return "different"
    prompt = _DISAMBIG_PROMPT.format(
        existing_name=existing_name,
        existing_type=existing_type or "unknown",
        existing_body=strip_claims_block(existing_body)[:2000] or "(empty)",
        new_name=new_name,
        new_type=new_type or "unknown",
        new_description=(new_description or "")[:1500] or "(empty)",
        alias_note=_ALIAS_NOTE.format(new_name=new_name) if recorded_alias else "",
        new_connections=f"\nConnections in its conversations:\n{new_connections[:800]}" if new_connections else "",
    )
    # Stage 2 disambiguation has its own dedicated model so we can route the
    # judge to a cheaper/faster model without downgrading the rest of Sleep.
    # Fall back to the main cycle model if the setting is empty.
    disambig_model = (
        getattr(settings, "litellm_disambiguation_model", "") or settings.litellm_model
    )
    try:
        from api.services.providers import resolve_llm_fn

        llm_fn = resolve_llm_fn(
            settings, model=disambig_model, completion=litellm.acompletion, stage="disambiguation"
        )
        response = await llm_fn(
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            # Disable provider-side reasoning + cap the call: a same/different
            # judgment needs no chain-of-thought, and on GLM 5.2 reasoning-on
            # made each disambiguation ~15-21s, crawling Stage 2 to hours. Mirrors
            # the entity_extractor hardening. No-op for non-reasoning models.
            extra_body={"reasoning": {"enabled": False}},
            timeout=120,
        )
        raw = response.choices[0].message.content or "{}"
        parsed = json_parse.parse_json_object(raw)
        decision = str(parsed.get("decision", "")).strip().lower()
        if decision in {"same", "different", "unsure"}:
            return decision
        return "unsure"
    except engine_errors.EngineError:
        # G74(a): an ENGINE failure is not a model's uncertainty. Flattening it
        # to "unsure" here created a clarification and split the entity page —
        # the inbox floods and the graph fragments while the cycle reports
        # success. Propagate so the cycle stops with the episode queue intact.
        raise
    except Exception as e:
        logger.debug(f"Disambiguation judge failed for {new_name} vs {existing_name}: {e}")
        return "unsure"


def _existing_llm_candidates(
    new_entity: dict, existing_by_name: dict[str, dict], aliases: dict[str, list[dict]] | None = None,
) -> list[dict]:
    """The pages on disk the judge weighs ``new_entity`` against, in judging order.

    First the same-type pages that list the name among their ``aliases`` (marked
    ``alias``; they need share no word with it — an acronym, a short form), then
    the same-type pages that share a content token with the name and are not
    already a strict-fuzz match. A function of the name and the bank alone —
    nothing the per-name loop decides changes it — which is what lets ``resolve``
    judge these ahead of the loop (``_Lookahead``)."""
    new_name = new_entity.get("name") or ""
    new_type = (new_entity.get("type") or "concept").lower()
    candidates: list[dict] = []
    for page in (aliases or {}).get(new_name.strip().lower(), ()) if new_name else ():
        candidate = {"source": "existing", "id": page["id"], "data": page, "alias": True}
        if _candidate_type(candidate) == new_type:
            candidates.append(candidate)
    if not new_name or not _name_tokens(new_name):
        return candidates
    new_name_lower = new_name.lower()
    held = {candidate["id"] for candidate in candidates}
    for existing_name_lower, existing_data in existing_by_name.items():
        if existing_data["id"] in held:
            continue
        candidate = {"source": "existing", "id": existing_data["id"], "data": existing_data}
        if _candidate_type(candidate) != new_type:
            continue
        existing_display = _candidate_display_name(candidate)
        if not _share_content_token(new_name, existing_display):
            continue
        if fuzz.ratio(new_name_lower, existing_name_lower) > 85:
            continue
        candidates.append(candidate)
    return candidates


def _created_llm_candidates(new_entity: dict, created_by_id: dict[str, dict]) -> list[dict]:
    """The in-cycle creates the judge weighs ``new_entity`` against — what the loop has decided so far."""
    new_name = new_entity.get("name") or ""
    if not new_name or not _name_tokens(new_name):
        return []
    new_name_lower = new_name.lower()
    new_type = (new_entity.get("type") or "concept").lower()
    candidates: list[dict] = []
    for candidate_id, create_change in created_by_id.items():
        candidate = {"source": "created", "id": candidate_id, "data": create_change}
        existing_display = _candidate_display_name(candidate)
        if _candidate_type(candidate) != new_type:
            continue
        if not _share_content_token(new_name, existing_display):
            continue
        if fuzz.ratio(new_name_lower, existing_display.lower()) > 85:
            continue
        candidates.append(candidate)
    return candidates


async def _judge_candidates(
    new_entity: dict,
    candidates: list[dict],
    cache: dict[tuple[str, str], str],
    settings: Settings,
    *,
    gate: asyncio.Semaphore | None = None,
    stop: Callable[[], bool] | None = None,
    connections: str = "",
) -> list[tuple[dict, str]]:
    """Judge ``candidates`` in order, one call each, stopping at the first ``same``.

    Returns ``(candidate, decision)`` per candidate judged. ``gate`` bounds the
    calls in flight across every name ``resolve`` is judging; ``stop`` is polled
    before each call so a cancel or a plan limit starts nothing new. A candidate an
    alias brought is judged with the alias note, the page's context first
    (``_alias_page_context``) and the name's ``connections`` in the batch."""
    new_name = new_entity.get("name") or ""
    new_name_lower = new_name.lower()
    new_type = (new_entity.get("type") or "concept").lower()
    new_description = new_entity.get("description") or ""
    judged: list[tuple[dict, str]] = []
    for candidate in candidates:
        cache_key = (new_name_lower, candidate["id"])
        if cache_key in cache:
            decision = cache[cache_key]
        else:
            if stop is not None and stop():
                break
            kwargs = dict(
                new_name=new_name,
                new_type=new_type,
                new_description=new_description,
                existing_name=_candidate_display_name(candidate),
                existing_type=_candidate_type(candidate),
                existing_body=_candidate_description(candidate),
                settings=settings,
            )
            if candidate.get("alias"):
                kwargs.update(existing_body=_alias_page_context(candidate["data"]), recorded_alias=True,
                              new_connections=connections)
            if gate is None:
                decision = await _llm_judge_same_entity(**kwargs)
            else:
                async with gate:
                    if stop is not None and stop():  # stopped while waiting for a slot
                        break
                    decision = await _llm_judge_same_entity(**kwargs)
            cache[cache_key] = decision
        judged.append((candidate, decision))
        if decision == "same":
            break
    return judged


def _pick_match(new_name: str, judged: list[tuple[dict, str]]) -> dict | None:
    """The first ``same`` in judging order, else the first ``unsure``, else ``None``."""
    unsure_candidate: dict | None = None
    for candidate, decision in judged:
        if decision == "same":
            logger.info(f"LLM disambiguation merged '{new_name}' -> '{_candidate_display_name(candidate)}'")
            return {"decision": "same", "candidate": candidate}
        if decision == "unsure" and unsure_candidate is None:
            unsure_candidate = candidate
    if unsure_candidate is not None:
        logger.info(
            f"LLM disambiguation deferred '{new_name}' for clarification "
            f"against '{_candidate_display_name(unsure_candidate)}'"
        )
        return {"decision": "unsure", "candidate": unsure_candidate}
    return None


async def _find_llm_candidate_match(
    new_entity: dict,
    existing_by_name: dict[str, dict],
    created_by_id: dict[str, dict],
    cache: dict[tuple[str, str], str],
    settings: Settings,
    *,
    aliases: dict[str, list[dict]] | None = None,
    connections: str = "",
    prejudged: list[tuple[dict, str]] | None = None,
    gate: asyncio.Semaphore | None = None,
) -> dict | None:
    """Look for an existing or in-cycle entity that the LLM judges as same/unsure.

    Candidates are same-type entities that share at least one content token with
    the new entity's name and do not already fall under the strict-fuzz match:
    the pages on disk first — those listing the name among their ``aliases``
    ahead of the rest — then the in-cycle creates. Returns the first SAME
    match; otherwise the first UNSURE match so the caller can create a
    clarification instead of inventing a new page.

    ``prejudged`` is the existing-page part already judged ahead of the loop
    (``_Lookahead``: the same calls, in the same order, with the same early
    exit); only the in-cycle creates are then judged here.
    """
    new_name = new_entity.get("name") or ""
    if not new_name:
        return None

    if prejudged is None:
        judged = await _judge_candidates(
            new_entity, _existing_llm_candidates(new_entity, existing_by_name, aliases), cache, settings,
            gate=gate, connections=connections)
    else:
        judged = list(prejudged)
    if not any(decision == "same" for _, decision in judged):
        judged += await _judge_candidates(
            new_entity, _created_llm_candidates(new_entity, created_by_id), cache, settings, gate=gate)
    return _pick_match(new_name, judged)


#: How many names per concurrent slot ``_Lookahead`` takes ahead of the loop.
#: A name's own calls stay sequential, so while the loop waits on a name with a
#: long candidate list the other slots keep working on names further ahead; the
#: window bounds what a cancel can waste (judgments taken but never used).
LOOKAHEAD_NAMES_PER_SLOT = 4


def _lookahead_plan(
    ordered_entities: list[tuple[str, dict]], existing_by_name: dict[str, dict],
    aliases: dict[str, list[dict]] | None = None,
) -> list[tuple[dict, list[dict]] | None]:
    """What ``_Lookahead`` may judge ahead: per name in the loop's order, its
    existing-page candidates — or ``None`` where the loop makes no existing-page
    call (a direct match on disk, no candidate) or may settle the name on an
    in-cycle create before judging (an earlier name in the batch within the
    direct-match fuzz of it; an in-cycle create can only carry a batch name).
    The plan only decides what runs early: the loop re-checks every match itself."""
    plan: list[tuple[dict, list[dict]] | None] = []
    earlier: list[str] = []
    for _, entity in ordered_entities:
        name_lower = (entity.get("name") or "").strip().lower()
        entry: tuple[dict, list[dict]] | None = None
        if (_find_direct_candidate_match(entity, existing_by_name, {}) is None
                and not any(name_lower == other or fuzz.ratio(name_lower, other) > 85 for other in earlier)):
            candidates = _existing_llm_candidates(entity, existing_by_name, aliases)
            if candidates:
                entry = (entity, candidates)
        plan.append(entry)
        earlier.append(str(entity.get("name") or "").lower())
    return plan


class _Lookahead:
    """Stage 2's judgments against EXISTING pages, taken ahead of the per-name loop.

    A name's existing-page judgments depend only on its own extraction and the
    bank, so they can run while the loop is still deciding earlier names. Each
    name's candidates are still judged one after another with the first-``same``
    exit (the very calls the serial loop made); different names overlap, at most
    ``concurrency`` calls in flight (the gate the loop's own inline calls share).
    At most ``LOOKAHEAD_NAMES_PER_SLOT × concurrency`` names are taken ahead of the loop's position, so
    a cancel or a plan limit wastes a bounded number of calls.

    ``plan[i]`` is ``(entity, candidates)`` for the i-th name in the loop's
    order, or ``None`` when the loop would make no existing-page call for it
    (a direct match, no candidate) or might settle it on an in-cycle
    create first — those are left to the loop, exactly as before.
    ``close`` starts nothing more and waits out the calls in flight: a call is
    never interrupted (a plan call runs in a worker thread), and none outlives
    the batch.
    """

    def __init__(self, plan: list[tuple[dict, list[dict]] | None], *, settings: Settings,
                 cache: dict[tuple[str, str], str], concurrency: int,
                 cancel_check: Callable[[], bool] | None = None, connections: dict[str, str] | None = None):
        self._plan = plan
        self._connections = connections or {}
        self._cancel_check = cancel_check
        self._settings = settings
        self._cache = cache
        self.gate = asyncio.Semaphore(concurrency)
        self._window = LOOKAHEAD_NAMES_PER_SLOT * concurrency
        self._tasks: dict[int, asyncio.Task] = {}
        self._dropped: list[asyncio.Task] = []
        self._next = 0
        self._stopped = False
        self._error: BaseException | None = None

    @property
    def error(self) -> BaseException | None:
        """The first engine error a lookahead call met, if any."""
        return self._error

    def _stop(self) -> bool:
        if not self._stopped and self._cancel_check is not None and self._cancel_check():
            self._stopped = True
        return self._stopped

    def _fill(self, cursor: int) -> None:
        while (not self._stopped and self._next < len(self._plan)
               and sum(1 for i in self._tasks if i >= cursor) < self._window):
            index = self._next
            self._next += 1
            if self._plan[index] is not None:
                self._tasks[index] = asyncio.create_task(self._judge(index))

    async def _judge(self, index: int) -> list[tuple[dict, str]]:
        entity, candidates = self._plan[index]
        try:
            # The loop's cache is shared safely: names are deduplicated before the
            # loop, so no two names write the same ``(name, candidate)`` key.
            return await _judge_candidates(entity, candidates, self._cache, self._settings,
                                           gate=self.gate, stop=self._stop, connections=self._connections_of(entity))
        except BaseException as exc:
            if self._error is None and not isinstance(exc, asyncio.CancelledError):
                self._error = exc
            self._stopped = True
            raise

    async def take(self, index: int) -> list[tuple[dict, str]] | None:
        """The existing-page judgments for the loop's ``index``-th name, or
        ``None`` when the loop is to judge that name itself. Raises the first
        engine error any lookahead call met — the drain's pause, as before."""
        self._fill(index)
        if self._error is not None:
            raise self._error
        task = self._tasks.pop(index, None)
        if task is None:
            return None
        judged = await task
        if self._error is not None:
            raise self._error
        entity, candidates = self._plan[index]
        if len(judged) < len(candidates) and not any(decision == "same" for _, decision in judged):
            # Stopped between this name's candidates (a cancel): the loop is on this
            # name, and the serial loop always finished the name it was on — so
            # finish it here, never decide it on half its judgments.
            judged += await _judge_candidates(entity, candidates[len(judged):], self._cache, self._settings,
                                              gate=self.gate, connections=self._connections_of(entity))
        self._fill(index + 1)
        return judged

    def _connections_of(self, entity: dict) -> str:
        return self._connections.get(str(entity.get("name") or "").lower(), "")

    def discard(self, index: int) -> None:
        """The loop settled ``index`` without its judgments (a direct match to an
        in-cycle create): drop them. A call already made is not undone."""
        task = self._tasks.pop(index, None)
        if task is not None:
            self._dropped.append(task)  # still awaited by `close`
        self._fill(index + 1)

    async def close(self) -> None:
        self._stopped = True
        pending = [*self._tasks.values(), *self._dropped]
        self._tasks.clear()
        self._dropped.clear()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


def _infer_uncertainty_type(entity: dict) -> str:
    """Map an extracted low-confidence entity to a clarification uncertainty type."""
    etype = (entity.get("type") or "").lower()
    description = (entity.get("description") or "").strip()
    if etype == "person":
        return "Unknown relationship details"
    if not description or len(description) < 40:
        return "Insufficient context to classify"
    return "Ambiguous type or role"
