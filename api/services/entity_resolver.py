"""Stage 2: Entity Resolution & Deduplication."""

import asyncio
import functools
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import litellm
from loguru import logger
from thefuzz import fuzz

from api.config import Settings
from api.services import (agent_engine, alias_policy, application_page, authorship, contact_identity, contacts_local, correspondents, engine_errors,
                          entity_body, entity_relations, entity_types, fact_policy, json_parse, owner_identity, people_directory, person_leads,
                          project_birth, promotion, quiet_pages, role_people, section_provenance, text_fold,
                          wrong_aliases)
from api.services.clarification_manager import (
    CONFIDENCE_THRESHOLD,
    ClarificationManager,
)
from api.services.id_utils import sanitize_id
from api.services.vector_index import PendingEntity, SqliteVecIndexer


#: ``name_to_id``'s value for a name Stage 2 HELD although an existing page bears it (2026-10-27): no endpoint — its
#: edges are dropped and its claims never keyed to that page by name (`claim_pipeline.subject_resolver`).
HELD_ENDPOINT = "\x00held"
#: G209 (2026-10-27): a "Possible duplicate" question Stage 2 raised about a mention it HELD — the mention, never the
#: page that may share its id. The answer releases what the mention's line holds (`inbox_service._release_answered`),
#: and Sleep's settle never folds the page sharing the id (`inbox_service._resolve_clarification`).
HELD_MENTION_KEY = "held_mention"


def endpoint_id(name: str, name_to_id: dict[str, str]) -> str | None:
    """The id Stage 2 resolved ``name`` to, or ``None`` — the edge rule, as one function.

    Exact (lower-cased) first, then the first fuzzy spelling (:func:`fuzzy_same`:
    ``fuzz.ratio > 85`` and not :func:`distinct_names`) over ``name_to_id`` in
    insertion order, as the relationship loop in :func:`resolve` always did inline. G141 PJ-0 (R-PJ17) made it a function so
    Sleep's claims key their subject and object through the SAME rule as the
    edge between them: a claim used to be keyed by ``sanitize_id(raw name)``,
    so a short name Stage 2 had matched ("Hana" → ``hana-example``) keyed a
    page that did not exist, and the claim was dropped while its edge landed.
    """
    key = (name or "").lower()
    hit = name_to_id.get(key)
    if hit == HELD_ENDPOINT:
        return None   # held: it is no page yet, least of all the one that shares its name
    if hit:
        return hit
    for known_name, known_id in name_to_id.items():
        # 2026-10-27: a fuzzy spelling only — a name with a word or a number the other lacks ("<agency> <city>" /
        # "<city>") is another thing, and its edge resolves to nothing rather than to that page (`distinct_names`).
        if known_id != HELD_ENDPOINT and fuzzy_same(key, known_name):
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

    # A person named only by their relation to the owner ("<owner>'s partner", "my dad") is titled by the
    # relation and attached to the ONE page that holds it, before anything keys a name (`role_people`): every
    # later step — promotion, claims, wikilink edges — reads the same renamed batch. Never the owner's name.
    owner_page_id = owner_identity.owner_page_id(existing, getattr(settings, "memory_path", None), settings)
    owner_page = next((e for e in existing if owner_page_id and e.get("id") == owner_page_id), None)
    role_people.canonicalize(extracted, existing, (owner_page or {}).get("frontmatter"))

    existing_by_name: dict[str, dict] = {}
    same_title: dict[str, list[dict]] = {}
    for e in existing:
        name = e["frontmatter"].get("name", e["id"].replace("-", " ").title())
        if agent_engine.is_runtime_path(str(name)):
            continue  # an old leaked page: never a merge target, endpoint or judge candidate
        held = existing_by_name.get(name.lower())
        if held is None or str(held.get("id")) != sanitize_id(name):
            # G227: two pages may share a title now (a new same-named page keeps the clean title, `_another_id`): the
            # page whose own id the title spells keeps the name's key, so a join on the name never moves to the newer
            # page by listing order.
            existing_by_name[name.lower()] = e
        if str(e["frontmatter"].get("status") or "") != "dropped":
            # G227: every page by its title — two pages may share one, and `existing_by_name` keeps only the last.
            same_title.setdefault(str(name).lower(), []).append(e)
    aliases = _alias_index(existing_by_name)
    # The pairs the person said are different (`merge_rejections`): a shared alias or a close spelling never brings
    # one of them back to the judge.
    rejected_pairs = _load_rejected(getattr(settings, "memory_path", None))
    name_index = NameIndex(existing_by_name)   # every name and alias, once: the leads' lookups (2026-10-27)
    # One person across sources (owner 2026-10-28): a chat participant's address-book card -> the one page carrying
    # that card's G61 source (`contact_identity`). Read before any name.
    card_page_ids = contact_identity.card_pages(existing)
    existing_by_id = {str(e.get("id")): e for e in existing if e.get("id")}

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
    # G179: a message conversation's other side, as Stage 1 marked it (`correspondents`) — resolved to a page of its
    # own type below, never through the by-name path every other name takes.
    correspondent_entities: list[dict] = []
    # episode_id -> list of entity names mentioned in that episode
    episode_cooccurrences: dict[str, list[str]] = {}

    # G209: "Full Name (handle)" / "handle (Full Name)" is one mention the record paired: keyed by the full name with
    # the handle as its alias, never parked as a literal third name. The raw spelling still resolves (edges, claims).
    named_handles: dict[str, str] = {}
    # 2026-10-27: an alias the extractor gave one thing that is the name of another thing it extracted from the same
    # conversation is co-occurrence, not another name — dropped before anything keys a name, and before the handle
    # split below adds the handle the record paired on purpose.
    crossed = _drop_conversation_names(extracted)
    if crossed:
        logger.info(f"Stage 2: {crossed} alias(es) dropped that name another thing in the same conversation")
    for extraction in extracted:
        for entity in extraction.get("entities", []):
            if str(entity.get("type") or "").lower() != "person":
                continue
            split = person_leads.split_named_handle(entity.get("name", ""))
            if split is None:
                continue
            full, handle = split
            named_handles[str(entity["name"]).strip().lower()] = full.lower()
            entity["name"] = full
            entity["aliases"] = [*(entity.get("aliases") or []), handle]

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
            if entity.pop(promotion.LABEL_ONLY, False):
                # Owner 2026-10-29: a name the conversation carries only as a filing label (a bookmark's folder, a
                # reminder's list) is no mention: never a conversation for the 2+ rule, never a held line.
                logger.debug("Stage 2: dropped a name only a filing label carried")
                continue
            # A texted person saved under a relation ("Mom") is `role_people`'s: one relation page, a person already.
            if (correspondents.from_mark(entity.get(correspondents.MARK)) is not None
                    and not entity.get(role_people.UNNAMED_KEY)):
                correspondent_entities.append(entity)
                if name not in per_episode_names:
                    per_episode_names.append(name)
                continue
            mention_counts[name.lower()] += 1
            episode_mentions.setdefault(name.lower(), set()).add(episode_id)
            all_entities.append(entity)
            if name not in per_episode_names:
                per_episode_names.append(name)
        if per_episode_names:
            episode_cooccurrences[episode_id] = per_episode_names

        all_relationships.extend(extraction.get("relationships", []))

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
    remote_cache: dict = {}   # the bank's family → hashed remotes, read once when a birth carries one
    resolved_updates: dict[str, dict] = {}
    resolved_creates: dict[str, dict] = {}

    # Transactional Stage 2 (see the docstring above): every clarifier/index
    # WRITE the loop below would have made inline is recorded here instead —
    # (callable, args, kwargs), executed in this exact order only if the
    # loop completes without cancelling. `cancelled` records whether it did.
    pending_actions: list[tuple[Callable, tuple, dict]] = []
    promoted_pending: list[str] = []
    cancelled = False
    # Owner ruling 2026-10-20: the address-book cards that matched no page wait outside the bank; a first mention that
    # names exactly one of them in full is enough to promote, and the page is born under the card's name.
    waiting_cards = _waiting_cards(settings)
    existing_ids = {str(e.get("id")) for e in existing}
    person_keys = _person_page_keys(existing) if waiting_cards.cards else set()
    episode_kind = (quiet_pages.episode_lookup(Path(settings.memory_path)) if waiting_cards.cards
                    else (lambda _episode: None))
    card_creates: dict[str, str] = {}   # card id -> the page this batch is creating for it
    # G209: the person pages keyed for leads (an alias or a linked account another page carries), and the pending
    # lines the extractor parked as "handle (Full Name)", by their full name.
    person_index = person_leads.PersonIndex(existing)
    # 2026-10-27: the same alias lead for organisations, labs, projects and tools (one lab on three pages, each listing
    # another's name among its own) — asked, never merged.
    org_index = person_leads.PersonIndex(existing, person_leads.ORG_TYPES)
    lead_pairs: set[tuple[str, str]] = set()
    lead_relations: list[dict] = []   # what the judge said an org lead's two pages are to each other (2026-10-29)
    named_handle_lines = _named_handle_lines(settings.memory_path)
    held_people: list[tuple[dict, list[dict]]] = []   # person names this batch held below the bar (W1, below)
    held_names: set[str] = set()   # every name this batch held (its endpoints follow the hold, below)
    decided_names: set[str] = set()   # every name this batch joined to a page or gave one

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

    # G179: the other side of a message conversation gets (or keeps) a page of its own type, and the conversation's
    # own edges and claims about them are pinned to it — before any other name is judged, so nothing below can
    # take its id.
    correspondent_pages: frozenset[str] = frozenset()
    if correspondent_entities:
        pinned, correspondent_pages = _resolve_correspondents(
            correspondent_entities, extracted, existing, resolved_updates, resolved_creates, name_to_id,
            general_names=frozenset(best_by_name), memory_path=getattr(settings, "memory_path", None),
            threshold=settings.sleep_promotion_threshold,
            linked=lambda n: _is_linked_to_existing(n, all_relationships, existing_by_name, owner_id=owner_id,
                                                    refs=refs),
            park=indexer.index_pending_entity if indexer is not None else None,
            pending_actions=pending_actions, promoted_pending=promoted_pending)
        logger.info(f"Stage 2: {len(correspondent_entities)} correspondent mention(s), {pinned} endpoint(s) pinned")

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
    batch_aliases = {person_leads.handle_key(a) for e in all_entities for a in e.get("aliases") or [] if str(a).strip()}
    connections = {
        name_lower: _batch_connections(name_lower, all_relationships, episode_mentions, episode_cooccurrences, refs)
        for name_lower, _ in best_by_name.items()
        if person_leads.handle_key(name_lower) in aliases or person_leads.handle_key(name_lower) in batch_aliases
    }

    def hold(name: str, entity: dict, siblings: list[dict], ambiguous_match: bool) -> None:
        """A name below the bar: asked about when its confidence is low, and parked as one pending line."""
        held_names.add(name.strip().lower())
        confidence = float(entity.get("confidence", 0.3) or 0.3)
        if (entity.get("type") or "").lower() == "person" and not ambiguous_match:
            held_people.append((entity, siblings))
        # A placeholder person is asked for a name once it has a page (`role_people`), never "Who or
        # what is Partner?" — whose answer would become the page's prose, not its name.
        if confidence < CONFIDENCE_THRESHOLD and not ambiguous_match and not entity.get(role_people.UNNAMED_KEY):
            pending_actions.append((
                clarifier.create,
                (),
                {
                    "entity_name": name,
                    "source_episode": entity.get("source_episode", ""),
                    "uncertainty_type": _infer_uncertainty_type(entity),
                    "suggested_classification": (
                        f"{entity.get('type', 'concept')} — "
                        f"{_effective_summary(entity)[:120]}"
                    ),
                    "suggested_confidence": confidence,
                    "source_context": _effective_summary(entity),
                    "source_episode_timestamp": entity.get("source_episode_timestamp"),
                },
            ))

        if indexer is not None:
            # One pending line per name: what every mention said rides on it
            # (the line keeps the strongest mention's episode, as before).
            parked = entity
            for sibling in siblings:
                parked = _merge_entity_payload(parked, sibling)
            line = _pending_line(name, entity, parked, siblings, confidence)
            against = existing_by_name.get(name.strip().lower())
            if against is not None:
                line.held_against = str(against.get("id") or "")   # held although a page bears its name (G209)
            pending_actions.append((indexer.index_pending_entity, (line,), {}))

    unborn: list[_Unborn] = []   # project names with no birth, decided after the loop (`_settle_unborn`)
    #: (name, page) pairs this batch holds as "could be the same" — asked or quiet (review of #545, B1): a pair the
    #: judge's raw verdict called related but `_never_cleared` turned unsure is a question, never also a relation.
    unsure_pairs: set[tuple[str, str]] = set()
    total_names = len(ordered_entities)
    if progress_callback is not None:
        progress_callback(0, total_names)
    # The judge calls against pages on disk run ahead of this loop, bounded
    # (``sleep_resolve_concurrency``; 1 is the plain serial loop). Every
    # decision is still made here, in this order (``_Lookahead``).
    concurrency = max(1, int(getattr(settings, "sleep_resolve_concurrency", 1) or 1))
    lookahead = (
        _Lookahead(_lookahead_plan(ordered_entities, existing_by_name, aliases, rejected_pairs, name_index), settings=settings,
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
            card_id = (contact_identity.card_of(entity, siblings)
                       if _is_person(entity) and not any(e.get(role_people.UNNAMED_KEY) for e in (entity, *siblings))
                       else None)
            match = _card_match(card_id, card_page_ids, existing_by_id, owner_page_id)
            # G227 (#546 review): the pages the person said THIS mention is not — only on a re-read of the conversations
            # their answer covered (its pending line's `apart`), never for every later mention of the name.
            apart_here = _apart_here(indexer, name, episode_mentions.get(name_lower, set()))
            # …and for the judge, a lead or a question, the held line's own verdict whatever the conversation: that
            # mention is never weighed against, or asked about, a page the person said it is not. A join on the name
            # itself is never suppressed by it (only `apart_here` above, on a re-read).
            line_apart = _apart_here(indexer, name, None)
            if match is None:
                match = _find_direct_candidate_match(
                    new_entity=entity,
                    existing_by_name=existing_by_name,
                    created_by_id=resolved_creates,
                    aliases=aliases,
                    same_title=same_title,
                    rejected=apart_here,
                )
            if match is None:
                # G227: a title the name alone may not join (two pages share it, or none is of the mention's kind).
                match = await _same_title_match(entity, same_title, llm_match_cache, settings,
                                                gate=lookahead.gate if lookahead is not None else None,
                                                stop=cancel_check, rejected=line_apart)
                if match is not None and match["decision"] == "different":
                    match = None
            if match is None:
                match = _answered_match(entity, aliases)
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
                    rejected=rejected_pairs | line_apart,
                    index=name_index,
                )
                # One person across sources (owner 2026-10-28): a one-word name heard outside a chat that the judge
                # would join to a chat participant's full-name page is asked about instead — a shared first name is
                # never enough on its own, whatever else the two conversations share.
                # An "unsure" judge's question is worded the same way, saying where each was heard.
                if match is not None and match.get("decision") in ("same", "unsure") and card_id is None:
                    heard = _first_name_across(settings.memory_path, entity, match, existing)
                    if heard is not None:
                        match = {**match, "decision": "unsure", "heard_in": heard}

            if match is None and _written_type(entity, siblings) == "project":
                # D2 amended (owner 2026-10-29): a repository renamed, moved or cloned again keeps its hashed remote,
                # so a birth from it is the project page that remote already has — never a second page.
                match = _same_repository_match(entity, siblings, existing, resolved_creates,
                                               settings.memory_path, remote_cache)
            if match is None and _written_type(entity, siblings) == "project":
                # W2 (benchmarks/newuser, 2026-10-22): a project mention whose own recorded alias names exactly one
                # project page brings that page to the judge — never a decision (owner 2026-10-08,
                # `capture-and-sleep.md`). A pair already judged keeps its verdict (the cache); a pair the person said
                # were different is not brought.
                alias_page = _project_alias_candidate(entity, siblings, existing_by_name, resolved_creates)
                if alias_page is not None and not _said_different(settings.memory_path, name, alias_page["id"]):
                    match = _pick_match(name, await _judge_candidates(
                        entity, [alias_page], llm_match_cache, settings,
                        gate=lookahead.gate if lookahead is not None else None,
                        connections=connections.get(name_lower, "")))
                if match is None and project_birth.birth_of(entity, siblings) is not None:
                    # Owner 2026-10-23 (review of #441): a mention WITH a birth may be the thing a fallback page already
                    # holds under another spelling ("Canoe restoration" against a page whose name shares no word with
                    # it). Weighed against every fallback page as `_settle_unborn` weighs a name with no birth —
                    # aliases count, no shared word needed, the judge decides — so the birth retypes that page in
                    # place instead of minting a second page beside it.
                    match = await _fallback_match(entity, siblings, existing, resolved_creates, resolved_updates,
                                                  llm_match_cache, settings, cancel_check)
            if match is not None and match["decision"] == "same":
                candidate = match["candidate"]
                name_to_id[name_lower] = candidate["id"]
                decided_names.add(name_lower)   # its held claims may follow it there (`pending_store.ready`)
                # Deferred (see the transactional-Stage-2 docstring above): this
                # can DELETE an inbox item, which must never happen for a name
                # whose match a cancellation is about to discard.
                pending_actions.append((
                    clarifier.check_organic_resolution,
                    (),
                    {"entity_name": name, "confidence": float(entity.get("confidence", 0.0) or 0.0),
                     "merged_into": candidate["id"]},
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
                change = (resolved_updates if candidate["source"] == "existing" else resolved_creates)[candidate["id"]]
                if _is_fallback(candidate):
                    _settle_fallback(change, project_birth.birth_of(entity, siblings))
                _fold_named_handle_lines(change, name_lower, named_handle_lines, name_to_id, promoted_pending)
                family = (person_index if _candidate_type(candidate) == "person"
                          else org_index if _candidate_type(candidate) in person_leads.ORG_TYPES else None)
                if candidate["source"] == "existing" and family is not None:
                    # G209: a page that matched by name still meets the page that carries that name as an alias or
                    # a linked account — as a question, never a merge. 2026-10-27: an organisation, lab, project or
                    # tool too, by alias only.
                    for lead in family.leads_for(candidate["id"]):
                        if (lead.page, lead.holder) not in lead_pairs:
                            lead_pairs.add((lead.page, lead.holder))
                            if family is org_index:
                                # 2026-10-29: an alias lead between two things meets the judge before it reaches the
                                # person — a part, a product, an alternative or a version is a relation, never "same?".
                                verdict = await _judge_lead(lead, family, settings,
                                                            gate=lookahead.gate if lookahead is not None else None)
                                if verdict not in ("same", "unsure"):
                                    relation = entity_relations.relation_of(verdict)
                                    b_name = person_leads.page_name(family.by_id.get(lead.page) or {})
                                    a_name = person_leads.page_name(family.by_id.get(lead.holder) or {})
                                    plausible = relation is not None and entity_relations.plausible(
                                        relation, b_name, a_name)
                                    if plausible:
                                        lead_relations.append(_lead_relation(lead, family, verdict, entity))
                                    if lead.kind == "alias" and settings.memory_path is not None:
                                        # The alias that made two things look like one is the cause: Cicada
                                        # proposes removing it (`wrong_aliases`, the person applies or leaves it).
                                        why = (entity_relations.phrase(relation, b_name, a_name) + "."
                                               if plausible else f"{b_name} and {a_name} are different things.")
                                        pending_actions.append((wrong_aliases.propose, (
                                            settings.memory_path, lead.holder, b_name or lead.key, why), {}))
                                    continue
                            pending_actions.append((_create_lead_clarification, (),
                                                    {"clarifier": clarifier, "lead": lead, "index": family,
                                                     "entity": entity}))
                continue

            ambiguous_match = match is not None and match["decision"] == "unsure"
            if ambiguous_match:
                unsure_pairs.add((name_lower, str(match["candidate"]["id"])))
            if ambiguous_match and _said_different(settings.memory_path, name, match["candidate"]["id"]):
                # The person already said these are different: the name goes on by the usual rule (its own page or
                # a pending line), never held back by a question that will not be asked again.
                match, ambiguous_match = None, False
            if match is None and (entity.get("type") or "").lower() == "person":
                # G209: a new name that another person page links as its account is asked about, not given a page.
                linked = [(pid, kind) for pid, kind in person_index.holders_of(name)
                          if kind.startswith("profile:") and not _said_different(settings.memory_path, name, pid)]
                if linked:
                    pid, kind = linked[0]
                    match = {"decision": "unsure", "candidate": {"source": "existing", "id": pid,
                                                                 "data": person_index.by_id[pid]},
                             "lead": person_leads.Lead(page=sanitize_id(name), holder=pid, kind=kind,
                                                       key=person_leads.handle_key(name))}
                    ambiguous_match = True

            # New entity — the promotion rule, measured (`promotion`): 2+ conversations
            # (this batch's, plus any an earlier batch parked the name from), more than
            # 3 exchanges with the person's own words in one, or a link the person made
            # to an existing high-confidence page.
            heard_now = episode_mentions.get(name_lower, set())
            linked_to_existing = _is_linked_to_existing(name, all_relationships, existing_by_name, owner_id=owner_id, refs=refs)

            pending_entry = None
            if indexer is not None:
                try:
                    pending_entry = indexer.pending_by_name(name)
                except Exception:
                    pending_entry = None
            # A line parked from this same conversation (a resumed one read again, G104) is not a second one.
            heard_before = set(pending_entry.episodes()) - heard_now if pending_entry is not None else set()
            if pending_entry is not None and not pending_entry.episodes():
                heard_before = {"(unrecorded)"}  # a line from before episodes were kept: an earlier conversation

            # Ruling 42: one conversation is enough for a specific event, program or application the person (or an
            # agent, for them) acted on — measured on the conversation at Stage 1 (`application_page`).
            applied = application_page.birth_of(entity, siblings)
            should_promote = (
                # Ruling 43: counted by conversation — an agent's memory note is its session's, never one of its own.
                len(promotion.conversation_keys(heard_now | heard_before, getattr(settings, "memory_path", None)))
                >= settings.sleep_promotion_threshold
                or linked_to_existing
                or any(promotion.substantive(e) for e in (entity, *siblings))
                or applied is not None
            )
            card = None if ambiguous_match else _card_for(entity, siblings, waiting_cards, person_keys, episode_kind,
                                                          memory_path=Path(settings.memory_path))
            if card is None and card_id and should_promote and not ambiguous_match:
                # A participant the usual rules promote is born under their own card (its name, photo and sources),
                # found by id: a card is still never used below the bar (owner 2026-10-20).
                card = waiting_cards.by_id(card_id)
            if card is not None and str(card["id"]) in card_creates:
                # A second spelling of a name this batch already gave a card's page to ("Example Bob"): the same page.
                card_page = card_creates[str(card["id"])]
                name_to_id[name_lower] = card_page
                for incoming in (entity, *siblings):
                    _merge_into_create(resolved_creates[card_page], incoming)
                continue
            if card is not None:
                card_page = sanitize_id(contacts_local.card_name(card))
                if card_page in existing_ids or card_page in resolved_creates:
                    card = None   # the card's name is already another page's id: an ordinary name, by the usual rule
            should_promote = should_promote or card is not None
            # Ruling 36 D4 (G141): a project is born from a repository the person works in or their own words calling
            # it one (`project_birth`), never from the rule above alone; below it, it stays a mention.
            birth = project_birth.birth_of(entity, siblings)
            # W4: the gate reads the type the create will WRITE — a sibling's "project" overrides a "concept" when the
            # payloads merge (`_merge_entity_payload`), so a page was once written as a project with no birth.
            if _written_type(entity, siblings) == "project" and birth is None and applied is not None:
                # Ruling 42: an event or program applied to is no project (D4 still holds); its page is the fallback
                # type, born from the application.
                for e in (entity, *siblings):
                    if e.get("type") == "project":
                        e["type"] = project_birth.FALLBACK_TYPE
            if _written_type(entity, siblings) == "project":
                if birth is None and not ambiguous_match:
                    # Owner 2026-10-23 (amends D4): no birth, so never a project page — but one thing said under
                    # several names is one thing. Decided after this loop, over every spelling the judge joins
                    # (`_settle_unborn`): a fallback page over the bar, a held mention below it.
                    unborn.append(_Unborn(name=name, key=name_lower, entity=entity, siblings=siblings,
                                          pending=pending_entry, heard=heard_now | heard_before,
                                          passes=should_promote))
                    continue
                should_promote = birth is not None

            if ambiguous_match and match.get("lead") is not None:
                pending_actions.append((_create_lead_clarification, (),
                                        {"clarifier": clarifier, "lead": match["lead"], "index": person_index,
                                         "entity": entity, "held": True}))
            elif ambiguous_match and not match.get("quiet"):
                pending_actions.append((
                    _create_duplicate_clarification,
                    (),
                    {"clarifier": clarifier, "entity": entity, "candidate": match["candidate"],
                     **({"heard_in": match["heard_in"]} if match.get("heard_in") else {}),
                     **({"same_title": match["same_title"]} if match.get("same_title") else {})},
                ))

            own_id: str | None = None   # G227: a page of its own under a name another page already spells
            taken = (should_promote and not ambiguous_match and card is None
                     and sanitize_id(name) in existing_ids)
            if taken:
                page = next((e for e in existing if str(e.get("id")) == sanitize_id(name)), None)
                apart_line = page is not None and pending_entry is not None and page["id"] in pending_entry.apart_pages()
                if page is not None and (apart_line or _said_different(settings.memory_path, name, page["id"])):
                    # The person said it is someone else ("Another one", or "No, different"): a page of its own
                    # beside the one with that name — the same clean title, a distinct id; the qualifier tells them
                    # apart on every surface (G227, owner 2026-10-29: no stored "(another)").
                    own_id = _another_id(name, existing_ids, resolved_creates)
                    taken = False
                elif page is not None:
                    # 2026-10-27: the page with this exact id is another one it did not join (a name several people
                    # answer to, judged different or with no lead): never a create over it — held, and asked.
                    shared = [p["id"] for p in same_title.get(name_lower) or ()]
                    pending_actions.append((
                        _create_duplicate_clarification, (),
                        {"clarifier": clarifier, "entity": entity,
                         "candidate": {"source": "existing", "id": page["id"], "data": page},
                         **({"same_title": shared} if shared else {})}))
                    ambiguous_match = True
                    unsure_pairs.add((name_lower, str(page["id"])))
            if should_promote and not ambiguous_match:
                if card is not None:
                    entity = _card_entity(entity, card)
                entity_id = own_id or sanitize_id(entity["name"])
                name_to_id[name_lower] = entity_id
                decided_names.add(name_lower)
                resolved_creates[entity_id] = _create_change(entity_id, entity)
                if birth is not None and _written_type(entity, siblings) == "project":
                    resolved_creates[entity_id]["project_birth"] = birth
                if card is not None:
                    # Stage 5 writes the card's sources and photo on the page it creates (`contacts_local.seed_page`).
                    resolved_creates[entity_id]["contacts_card"] = card
                    card_creates[str(card["id"])] = entity_id
                    name_to_id[entity["name"].lower()] = entity_id
                for sibling in siblings:
                    _merge_into_create(resolved_creates[entity_id], sibling)
                if pending_entry is not None:
                    # What the earlier conversations said, and the credit for each of them.
                    _fold_pending(resolved_creates[entity_id], pending_entry)
                _fold_named_handle_lines(resolved_creates[entity_id], name_lower, named_handle_lines, name_to_id,
                                         promoted_pending)
                # Deferred (same reasoning as the "same"-match branch above).
                pending_actions.append((
                    clarifier.check_organic_resolution,
                    (),
                    {"entity_name": name, "confidence": float(entity.get("confidence", 0.0) or 0.0)},
                ))
                if pending_entry is not None:
                    # The line leaves the store only once Stage 5 has written the page that now carries
                    # what it held (`sleep_cycle`): a cancel before that keeps it, and the next run
                    # promotes it again with everything it heard.
                    promoted_pending.append(name)
            else:
                hold(name, entity, siblings, ambiguous_match)

    finally:
        if lookahead is not None:
            # Starts nothing more and waits out the calls in flight, on every exit.
            await lookahead.close()
    if lookahead is not None and lookahead.error is not None and not cancelled:
        raise lookahead.error  # a plan limit met ahead of the loop is still the batch's pause
    if unborn and not cancelled:
        cancelled = await _settle_unborn(
            unborn, existing=existing, resolved_updates=resolved_updates, resolved_creates=resolved_creates,
            name_to_id=name_to_id, pending_actions=pending_actions, promoted_pending=promoted_pending,
            clarifier=clarifier, hold=hold, cache=llm_match_cache, settings=settings, cancel_check=cancel_check,
            unsure_pairs=unsure_pairs)

    if progress_callback is not None and not cancelled:
        progress_callback(total_names, total_names)
    for change in resolved_creates.values():
        if change.get("contacts_card"):
            # A merged spelling never renames it: a page born from a card carries the card's name.
            change["entity"]["name"] = contacts_local.card_name(change["contacts_card"])
    if card_creates:
        logger.info(f"Stage 2: {len(card_creates)} page(s) promoted on a waiting card's first mention")  # never a name
    if not cancelled:
        pending_actions.extend(_held_alias_questions(held_people, existing, resolved_creates, clarifier,
                                                     settings.memory_path, owner_page_id=owner_page_id))
    for held in held_names:
        # 2026-10-27: a held name that is also an existing page's name (registered above) must not have its edges and
        # claims keyed to that page by name: the hold says Stage 2 did not decide it is that page.
        if held in existing_by_name:
            name_to_id[held] = HELD_ENDPOINT
    relations = [] if cancelled else _judged_relations(
        llm_match_cache, best_by_name, existing_by_id, resolved_creates, name_to_id,
        skip=unsure_pairs | _asked_pairs(pending_actions)) + lead_relations
    if relations:
        logger.info(f"Stage 2: {len(relations)} relation(s) the judge named instead of a duplicate question")
    resolved = list(resolved_updates.values()) + list(resolved_creates.values())
    for raw, full in named_handles.items():
        if full in name_to_id and raw not in name_to_id:
            name_to_id[raw] = name_to_id[full]

    # Resolve relationships — only keep edges where both endpoints survived promotion
    resolved_edges: list[dict] = []
    seen_edges: set[tuple[str, str, str]] = set()
    for rel in all_relationships:
        label = rel.get("label", "related to")
        # A conversation's own correspondent first (G179, pinned above), then self-references (G169), then exact,
        # then fuzzy — one rule, shared with Sleep's claims (G141 PJ-0, `claim_pipeline.subject_resolver`).
        # (A pin to a correspondent still held below the promotion bar has no page yet: no edge, as for any name.)
        source_id = _pinned(rel, correspondents.SOURCE_PAGE, correspondent_pages, resolved_creates)
        if source_id is None:
            source_id = _edge_endpoint(rel.get("source", ""), name_to_id, refs)
        target_id = _pinned(rel, correspondents.TARGET_PAGE, correspondent_pages, resolved_creates)
        if target_id is None:
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
        # G209: the names this batch decided (joined or created): a line held against a page releases only on these.
        "decided_names": sorted(decided_names),
        # G169: the qualified self-reference decision this stage keyed by.
        "self_references": refs,
        # The pending lines this batch's creates folded in, for Stage 5 to take once the pages exist.
        "promoted_pending": [] if cancelled else promoted_pending,
        # 2026-10-29 (`entity_relations`): what the judge said two names are to each other instead of "the same?" —
        # Stage-1-shaped relationships Stage 5.56 writes as claims through the claim pipeline.
        "relations": relations,
    }


def _asked_pairs(pending_actions: list) -> set[tuple[str, str]]:
    """Every (name, page) pair a duplicate question this batch queued is about."""
    out: set[tuple[str, str]] = set()
    for fn, _args, kwargs in pending_actions:
        if fn is _create_duplicate_clarification:
            name = str((kwargs.get("entity") or {}).get("name") or "").lower()
            out.add((name, str((kwargs.get("candidate") or {}).get("id") or "")))
    return out


def _judged_relations(cache: dict[tuple[str, str], str], best_by_name: dict[str, dict],
                      existing_by_id: dict[str, dict], resolved_creates: dict[str, dict],
                      name_to_id: dict[str, str], *, skip: set[tuple[str, str]] = frozenset()) -> list[dict]:
    """One relationship per ``related:<relation>`` verdict this batch's judge gave between a name and a page (on disk
    or born this batch) — never for a name that landed on that page (a part folded into its whole), never between
    two spellings of one name, never for a pair in ``skip`` (asked about, or held as possibly the same — review of
    #545: one pair is never both a question and a relation), at most one per pair. A relation that reverses the
    names' own containment ("<A> Head" read as the line <A> is a version of) is dropped
    (`entity_relations.plausible`)."""
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for (name_lower, page_id), decision in cache.items():
        relation = entity_relations.relation_of(decision)
        entity = best_by_name.get(name_lower)
        if relation is None or entity is None or (name_lower, page_id) in seen or (name_lower, page_id) in skip:
            continue
        page = existing_by_id.get(page_id)
        if page is not None:
            page_name = str((page.get("frontmatter") or {}).get("name") or page.get("name") or page_id)
        elif page_id in resolved_creates:
            page_name = str((resolved_creates[page_id].get("entity") or {}).get("name") or page_id)
        else:
            continue   # an unborn group or a parked line: no page to hold the claim
        name = str(entity.get("name") or "")
        if not name or name.strip().lower() == page_name.strip().lower() or name_to_id.get(name_lower) == page_id:
            continue
        if not entity_relations.plausible(relation, name, page_name):
            continue
        seen.add((name_lower, page_id))
        # Both sides pinned: the claim lands on the page weighed against (whatever other page shares its letters), the
        # name its object by the id it now has, or its slug while it waits (never a held endpoint).
        name_id = name_to_id.get(name_lower)
        out.append(entity_relations.relationship(
            relation, name, page_name, a_id=page_id,
            b_id=name_id if name_id and name_id != HELD_ENDPOINT else sanitize_id(name),
            episode=str(entity.get("source_episode") or ""), timestamp=entity.get("source_episode_timestamp")))
    return out


def _resolve_correspondents(
    entities: list[dict],
    extracted: list[dict],
    existing: list[dict],
    updates_by_id: dict[str, dict],
    creates_by_id: dict[str, dict],
    name_to_id: dict[str, str],
    *,
    general_names: frozenset[str],
    memory_path=None,
    threshold: int = 2,
    linked: Callable[[str], bool] = lambda _name: False,
    park: Callable[[PendingEntity], None] | None = None,
    pending_actions: list | None = None,
    promoted_pending: list | None = None,
) -> tuple[int, frozenset[str]]:
    """G179: each correspondent Stage 1 marked lands on a page of its own type (`correspondents`) — never on a
    same-name page of another type, and never through the by-name path.

    An existing page of that type named so (else listing the name as an alias) is updated. Otherwise the
    correspondent faces the promotion rule like any name (`promotion`: 2+ conversations — this batch's and the ones
    its held line heard —, more than 3 exchanges with the person's own words, or a link the person made to an
    existing page). Below it, it waits in the pending store under its OWN key: a line named by the id its page will
    get (`correspondents.free_id`, always ``<id>-agent`` / ``<id>-person``, never the plain same-name id) and marked
    with the correspondent, so Stage 5.56 holds its claims there (``pending_store.hold`` keys by that slug) and no
    same-name page or same-name pending line ever receives them. Once the rule passes, the page is created under that
    id with everything the line held (`_fold_pending`, the held claims released by Stage 5.56).

    Every relationship of a correspondent episode whose endpoint names them is pinned to that id (``source_page`` /
    ``target_page``): its claim lands there, held or written; its edge is drawn only once the page exists (the caller
    drops a pin to a page that does not). ``name_to_id`` maps the name to the page only when the page exists or is
    created now and no other conversation in the batch extracted that name. Returns ``(endpoints pinned, the ids of
    pages that exist or are created this batch)``."""
    from api.services import pending_store

    groups: dict[tuple[str, str], list[dict]] = {}
    idents: dict[tuple[str, str], correspondents.Identity] = {}
    for entity in entities:
        ident = correspondents.from_mark(entity.get(correspondents.MARK))
        key = (ident.key, ident.kind)
        groups.setdefault(key, []).append(entity)
        idents.setdefault(key, ident)

    entities_dir = Path(memory_path) / "entities" if memory_path else None
    try:
        lines = pending_store.load(memory_path) if memory_path else []
    except Exception:  # noqa: BLE001 - an unreadable store holds nothing to find; the line is written fresh
        lines = []
    taken = {str(page.get("id")) for page in existing} | set(creates_by_id) | {sanitize_id(ln.name) for ln in lines}
    pages: dict[tuple[str, str], str] = {}
    live: set[str] = set()
    card_pids = contact_identity.card_pages(existing)
    for key, group in groups.items():
        ident = idents[key]
        best = group[0]
        for entity in group[1:]:
            if float(entity.get("confidence", 0) or 0) > float(best.get("confidence", 0) or 0):
                best = entity
        siblings = [entity for entity in group if entity is not best]
        # A texted person's address-book card names their page across every source (`contact_identity`), first.
        card_pid = card_pids.get(contact_identity.card_of(best, siblings) or "")
        page = next((p for p in existing if str(p.get("id")) == card_pid), None) if card_pid else None
        page = page or correspondents.find_page(existing, ident)
        if page is not None:
            page_id = page["id"]
            for incoming in (best, *siblings):
                _merge_into_update(updates_by_id=updates_by_id, existing_entity=page, incoming=incoming)
            live.add(page_id)
        else:
            line = correspondents.held_line(lines, ident)
            page_id = line.name if line is not None else correspondents.free_id(ident, taken, entities_dir)
            taken.add(page_id)
            heard_now = {str(e.get("source_episode") or "") for e in group} - {""}
            heard_before = set(line.episodes()) - heard_now if line is not None else set()
            promote = (len(promotion.conversation_keys(heard_now | heard_before, memory_path)) >= threshold
                       or any(promotion.substantive(e) for e in group)
                       or any(linked(str(e.get("name") or "")) for e in group))
            if promote:
                entity = {**best, "name": ident.name, "type": ident.page_type}
                if str(best.get("name") or "") != ident.name and alias_policy.admits(best.get("name")):
                    entity["aliases"] = [*(best.get("aliases") or []), best.get("name")]
                creates_by_id[page_id] = {
                    "id": page_id,
                    "action": "create",
                    "entity": entity,
                    "existing": None,
                    "source_episode": best.get("source_episode", ""),
                    "source_episodes": [best.get("source_episode", "")] if best.get("source_episode") else [],
                    "source_episode_timestamp": best.get("source_episode_timestamp"),
                    "source_episode_timestamps": ([best.get("source_episode_timestamp")]
                                                  if best.get("source_episode_timestamp") else []),
                    "source_episode_days": _source_days(best),
                    "untimed": bool(best.get("untimed")),
                    "trigger": "sleep/correspondent",
                }
                for sibling in siblings:
                    _merge_into_create(creates_by_id[page_id], sibling)
                if line is not None:
                    # What the earlier sittings said and their credit; the line leaves after Stage 5 (its held claims
                    # through Stage 5.56's release), as a promoted name's does.
                    _fold_pending(creates_by_id[page_id], line)
                    creates_by_id[page_id]["entity"].update(name=ident.name, type=ident.page_type)
                    if promoted_pending is not None:
                        promoted_pending.append(line.name)
                live.add(page_id)
            elif park is not None and pending_actions is not None:
                parked = best
                for sibling in siblings:
                    parked = _merge_entity_payload(parked, sibling)
                held = _pending_line(page_id, best, parked, siblings,
                                     float(best.get("confidence", 0.5) or 0.5))
                held.type = ident.page_type
                held.correspondent = ident.to_dict()
                pending_actions.append((park, (held,), {}))
        pages[key] = page_id
        if page_id in live:
            for entity in group:
                name_lower = str(entity.get("name") or "").lower()
                if name_lower and name_lower not in general_names:
                    name_to_id[name_lower] = page_id

    pinned = 0
    for extraction in extracted:
        ident = correspondents.from_mark(extraction.get(correspondents.MARK))
        if ident is None:
            continue
        page_id = pages.get((ident.key, ident.kind))
        if page_id is None:
            page = correspondents.find_page(existing, ident)
            line = correspondents.held_line(lines, ident) if page is None else None
            page_id = page["id"] if page is not None else (line.name if line is not None else None)
            if page is not None:
                live.add(page_id)
        if page_id is None:
            continue
        # The names this conversation's own entity for them went by (an alias the model listed), and theirs.
        names = {ident.key}
        for entity in extraction.get("entities") or []:
            if isinstance(entity, dict) and entity.get(correspondents.MARK):
                names |= {correspondents.agent_detectors.fold(str(n)) for n in correspondents.entity_names(entity) if n}
        for rel in extraction.get("relationships") or []:
            if not isinstance(rel, dict):
                continue
            for end, pin in (("source", correspondents.SOURCE_PAGE), ("target", correspondents.TARGET_PAGE)):
                if correspondents.agent_detectors.fold(str(rel.get(end) or "")) in names:
                    rel[pin] = page_id
                    pinned += 1
    return pinned, frozenset(live)


def _pinned(rel: dict, key: str, live: frozenset[str], creates: dict) -> str | None:
    """A correspondent pin (`_resolve_correspondents`) whose page exists or is created now; ``""`` (no edge, and no
    by-name fallback) for one still held; ``None`` for an endpoint with no pin."""
    pin = rel.get(key)
    if not pin:
        return None
    return pin if (pin in live or pin in creates) else ""


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


def _waiting_cards(settings: Settings) -> "contacts_local.WaitingIndex":
    """This bank's waiting address-book cards (`contacts_local.waiting_index`): empty with no bank path, on a demo bank,
    or when nothing waits — and never an error, a read failure only means no card promotes tonight."""
    memory_path = getattr(settings, "memory_path", None)
    if memory_path is None:
        return contacts_local.WaitingIndex()
    try:
        return contacts_local.waiting_index(Path(memory_path))
    except Exception as exc:  # noqa: BLE001 — the directory is outside the bank and disposable
        logger.warning(f"Stage 2: waiting cards unreadable ({type(exc).__name__})")
        return contacts_local.WaitingIndex()


def _person_page_keys(existing: list[dict]) -> set[str]:
    """Every folded name and alias an existing person page holds: a card whose name one of them already carries is that
    page's (the sync or the tail's rematch matches it), never the seed of a second one."""
    keys: set[str] = set()
    for e in existing:
        fm = e.get("frontmatter") or {}
        if fm.get("type") != "person" or fm.get("status") == "dropped":
            continue
        for label in [fm.get("name") or str(e.get("id") or "").replace("-", " "), *(fm.get("aliases") or [])]:
            if key := people_directory.fold(label):
                keys.add(key)
    return keys


#: Episodes whose text is a title or an item list, never a turn the person typed — a tab group's tab titles, a
#: calendar's event titles. A body with no turn markers is never a person's turn here anyway (`_said_in_person_turn`);
#: these are refused by name too, so a marker-shaped title can never pass.
CARD_REFUSED_SOURCES = frozenset({"tab-group", "calendar", "calendar-local"})


def _said_in_person_turn(memory_path: Path | None, episode_id: str, card: dict) -> bool:
    """Did the person themselves say this card's full name — in a MARKED turn of theirs (``user:`` or a meeting's
    ``speaker:``)? Not a reply of the agent's, not a relayed turn (``evidence_kind: assistant``, ruling 32), and not a
    document with no turn markers, which `promotion.exchanges` reads as the person's own writing (a tab group, a
    calendar, a feed item, a note): a card promotes only on the person's own words (owner ruling 2026-10-20)."""
    from api.services import bank_index, evidence

    if memory_path is None or not str(episode_id or "").startswith("ep_"):
        return False
    entry = bank_index.file(memory_path, "episodes", f"{episode_id}.md")
    if entry is None:
        return False
    fm = entry.frontmatter or {}
    if str(fm.get("source") or "") in CARD_REFUSED_SOURCES or str(fm.get("origin") or "") in CARD_REFUSED_SOURCES:
        return False
    try:
        text = entry.body()
    except Exception:
        return False
    keys = contacts_local.name_keys(card.get("given_name"), card.get("family_name"))
    for turn in evidence.turns(text, override=authorship.of(fm)):
        # In a group only the person's own lines are theirs (`promotion.person_kinds`, #499 review).
        if turn.marker is None or turn.role not in promotion.person_kinds(fm):
            continue
        said = f" {people_directory.fold(text[turn.content_start:turn.end])} "
        if any(f" {key} " in said for key in keys):
            return True
    return False


def _card_match(card_id: str | None, card_page_ids: dict[str, str], existing_by_id: dict[str, dict],
                owner_page_id: str | None) -> dict | None:
    """The page a chat participant's address-book card already names (`contact_identity.card_pages`), as a "same"
    decision — never the owner's page."""
    pid = card_page_ids.get(card_id or "")
    if not pid or pid == owner_page_id or pid not in existing_by_id:
        return None
    return {"decision": "same", "candidate": {"source": "existing", "id": pid, "data": existing_by_id[pid]}}


def _card_for(entity: dict, siblings: list[dict], waiting: "contacts_local.WaitingIndex",
              person_keys: set[str], episode_kind: Callable[[str], str | None], *,
              memory_path: Path | None = None) -> dict | None:
    """The ONE waiting card this person mention names in full (owner ruling 2026-10-20), or None.

    Only a ``person`` mention the person made in their own words: Stage 1 measured it named by a person
    (``named_by_person``), in a conversation (not a save, a watch or a check: `quiet_pages.episode_kind`), and the
    card's full name stands in one of the person's own marked turns (:func:`_said_in_person_turn` — never an agent's
    reply, a relayed turn, a tab title or a calendar entry). Never one titled by a relation to the owner
    (`role_people` — a person known only as "my partner" is never named from a card without the person's words); the
    mention's own name or an alias must be a card's given + family name in either order (`WaitingIndex.match`: never a
    one-part name, never a name two cards share); and no existing person page may hold that name already (two pages,
    or a card that is some page's)."""
    if not waiting.cards:
        return None
    group = (entity, *siblings)
    if any(entity_types.in_set(e.get("type")) != "person" or e.get(role_people.UNNAMED_KEY) for e in group):
        return None
    labels = [label for e in group for label in [e.get("name"), *(e.get("aliases") or [])] if label]
    card = waiting.match(labels)
    if card is None:
        return None
    if contacts_local.name_keys(card.get("given_name"), card.get("family_name")) & person_keys:
        return None
    spoken = [e for e in group if e.get("named_by_person")
              and episode_kind(str(e.get("source_episode") or "")) == quiet_pages.CONVERSATION]
    if not any(_said_in_person_turn(memory_path, str(e.get("source_episode") or ""), card) for e in spoken):
        return None
    return card


def _card_entity(entity: dict, card: dict) -> dict:
    """The mention, renamed to the card's name; the name the conversation used is kept as an alias when it differs."""
    name = contacts_local.card_name(card)
    aliases = [a for a in entity.get("aliases") or [] if a]
    said = str(entity.get("name") or "")
    if said and people_directory.fold(said) != people_directory.fold(name) and said not in aliases \
            and alias_policy.admits(said):
        aliases.append(said)
    aliases = [a for a in aliases if people_directory.fold(a) != people_directory.fold(name)]
    return {**entity, "name": name, "aliases": aliases}


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
    # A fact repeated (the same text after trivial normalization, `fact_policy.restates`)
    # is kept once; so is a sentence of a summary that lost.
    key_facts, _ = fact_policy.union([], _union_text(base.get("key_facts"), incoming.get("key_facts")))
    said = fact_policy.sentences(chosen)
    key_facts = [f for f in key_facts if not fact_policy.covered(str(f), said)]
    folded = " ".join(chosen.split()).lower()
    names = [merged.get("name"), base.get("name"), incoming.get("name"),
             *_union_text(base.get("aliases"), incoming.get("aliases"))]
    for text in (base_text, incoming_text, *_effective_summaries(base), *_effective_summaries(incoming)):
        if text and " ".join(text.split()).lower() not in folded:
            for sentence in fact_policy.standalone(text, names):
                if not fact_policy.covered(sentence, said + [str(f) for f in key_facts]):
                    key_facts = _union_text(key_facts, [sentence])
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


def _create_change(entity_id: str, entity: dict) -> dict:
    """A promotion's create, credited with its first mention."""
    return {
        "id": entity_id,
        "action": "create",
        "entity": entity,
        "existing": None,
        "source_episode": entity.get("source_episode", ""),
        "source_episodes": [entity.get("source_episode", "")] if entity.get("source_episode") else [],
        "source_episode_timestamp": entity.get("source_episode_timestamp"),
        "source_episode_timestamps": ([entity.get("source_episode_timestamp")]
                                      if entity.get("source_episode_timestamp") else []),
        "source_episode_days": _source_days(entity),
        "untimed": bool(entity.get("untimed")),
        "trigger": "sleep/promotion",
    }


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


def _pending_line(name: str, entity: dict, parked: dict, siblings: list[dict], confidence: float) -> PendingEntity:
    """The pending line for a name below the bar: what every mention in this batch
    said about it — summary, facts, links, questions, aliases, their G118 item
    records — and every conversation it came up in (page quality, 2026-10-09).
    The line keeps the strongest mention's episode, as before."""
    heard = []
    for e in (entity, *siblings):
        episode = e.get("source_episode") or ""
        if episode and episode not in {h["episode"] for h in heard}:
            heard.append({"episode": episode, "timestamp": e.get("source_episode_timestamp"),
                          "day": e.get("source_episode_day")})
    return PendingEntity(
        name=name,
        type=entity.get("type", "concept"),
        description=parked.get("description", "") or "",
        source_episode=entity.get("source_episode", ""),
        confidence=confidence,
        tags=list(parked.get("tags", []) or []),
        history_entries=list(parked.get("history_entries", []) or []),
        summary=_effective_summary(parked),
        key_facts=[str(f) for f in parked.get("key_facts") or [] if str(f).strip()],
        links=[link for link in parked.get("links") or [] if isinstance(link, dict) and link.get("url")],
        open_questions=[str(q) for q in parked.get("open_questions") or [] if str(q).strip()],
        aliases=[str(a) for a in parked.get("aliases") or [] if str(a).strip()],
        item_inputs=list(parked.get(section_provenance.INPUTS) or []),
        heard_in=heard,
    )


def _pending_payload(line: PendingEntity) -> dict:
    """What a pending line held, as an extraction payload."""
    return {
        "name": line.name, "type": line.type, "confidence": line.confidence,
        "summary": line.summary or line.description, "description": line.description,
        "key_facts": list(line.key_facts), "links": list(line.links),
        "open_questions": list(line.open_questions), "aliases": list(line.aliases),
        "tags": list(line.tags or []), "history_entries": list(line.history_entries or []),
        section_provenance.INPUTS: list(line.item_inputs),
    }


def _fold_pending(change: dict, line: PendingEntity) -> None:
    """Fold a pending line into the create its promotion made: its text through the
    same seam a same-name extraction uses, and one source credit per conversation
    it heard the name in (its timestamp and day, when the line kept them)."""
    change["entity"] = _merge_entity_payload(change.get("entity", {}) or {}, _pending_payload(line))
    records = {str(r.get("episode")): r for r in line.heard_in if isinstance(r, dict) and r.get("episode")}
    for episode in line.episodes():
        record = records.get(episode, {})
        _append_change_source(change, {"source_episode": episode,
                                       "source_episode_timestamp": record.get("timestamp"),
                                       "source_episode_day": record.get("day")})


def _answered_match(entity: dict, aliases: dict[str, list[dict]]) -> dict | None:
    """G209: the page the person said this name is. Their merge answer recorded the name among the page's aliases and
    left its note (`person_leads.answered_same`): the person's own word, so the name goes there with no judge and no
    question. Same type only; two pages carrying the answer for one name is no answer."""
    name = entity.get("name") or ""
    new_type = (entity.get("type") or "concept").lower()
    holders = [page for page in aliases.get(person_leads.handle_key(name), ())
               if str((page.get("frontmatter") or {}).get("type") or "concept").lower() == new_type
               and person_leads.answered_same(page, name)]
    if len(holders) != 1:
        return None
    return {"decision": "same", "candidate": {"source": "existing", "id": holders[0]["id"], "data": holders[0]}}


def _load_rejected(memory_path) -> frozenset:
    from api.services import merge_rejections

    try:
        return frozenset(merge_rejections.load_rejected(Path(memory_path))) if memory_path else frozenset()
    except Exception:
        return frozenset()


def _rejected_pair(rejected, name: str, page_id: str) -> bool:
    return bool(rejected) and tuple(sorted((sanitize_id(name), str(page_id)))) in rejected


def _apart_here(indexer, name: str, heard_now: set[str] | None) -> frozenset:
    """G227: ``(slug, page)`` pairs — in `_rejected_pair`'s shape — for the pages the person said the mention held under
    ``name`` is not. With ``heard_now``, ONLY when this read is one of the conversations that answer covered (what the
    join on the name honours: a new conversation naming one of those pages still joins it); ``None`` is the line's
    verdict whatever the conversation (what the judge, a lead and a question honour)."""
    if indexer is None:
        return frozenset()
    try:
        line = indexer.pending_by_name(name)
    except Exception:  # noqa: BLE001
        return frozenset()
    if line is None or not line.apart_pages():
        return frozenset()
    if heard_now is not None and not (set(heard_now) & line.apart_episodes()):
        return frozenset()
    slug = sanitize_id(name)
    return frozenset(tuple(sorted((slug, p))) for p in line.apart_pages())


def _said_different(memory_path, name: str, page_id: str) -> bool:
    """The person answered that ``name`` and ``page_id`` are not the same (`merge_rejections`)."""
    from api.services import merge_rejections

    try:
        if merge_rejections.is_rejected(Path(memory_path), sanitize_id(name), page_id):
            return True
        # G227 (#546 review): the person's answer about the mention held under this name, kept on its own line.
        from api.services import pending_store

        key = (name or "").strip().lower()
        return any(line.name.lower() == key and str(page_id) in line.apart_pages()
                   for line in pending_store.load(Path(memory_path)))
    except Exception:
        return False


def _named_handle_lines(memory_path) -> dict[str, list[PendingEntity]]:
    """G209: the pending person lines parked under a "handle (Full Name)" spelling, keyed by the full name's lowercase
    form. Read-only; an unreadable store is no lines."""
    from api.services import pending_store

    out: dict[str, list[PendingEntity]] = {}
    try:
        lines = pending_store.load(Path(memory_path))
    except Exception:
        return out
    for line in lines:
        if str(line.type or "").lower() != "person" or line.correspondent:
            continue
        split = person_leads.split_named_handle(line.name)
        if split is not None:
            out.setdefault(split[0].lower(), []).append(line)
    return out


def _fold_named_handle_lines(change: dict, name_lower: str, lines: dict[str, list[PendingEntity]],
                             name_to_id: dict[str, str], promoted_pending: list[str]) -> None:
    """Fold the "handle (Full Name)" lines parked for ``name_lower`` into the page that name resolved to: what they
    held, a credit per conversation, the handle as an alias, and the line leaves the store once Stage 5 wrote the page
    (``promoted_pending``; its held claims follow ``name_to_id``)."""
    for line in lines.pop(name_lower, ()):
        full, handle = person_leads.split_named_handle(line.name) or (line.name, "")
        renamed = PendingEntity.from_dict({**line.to_dict(), "name": full,
                                           "aliases": [*line.aliases, *([handle] if handle else [])]})
        _fold_pending(change, renamed)
        name_to_id.setdefault(line.name.lower(), change["id"])
        promoted_pending.append(line.name)


def _written_type(entity: dict, siblings) -> str:
    """The type a create from ``entity`` and its ``siblings`` is written with — ``_merge_entity_payload``'s rule, read
    in the order the loop merges them: an empty or ``concept`` type takes the next mention's."""
    kind = str(entity.get("type") or "").lower()
    for sibling in siblings:
        if not kind or kind == "concept":
            kind = str(sibling.get("type") or kind or "concept").lower()
    return kind or "concept"


@dataclass
class _Unborn:
    """A name Stage 1 called a project that nothing gave a birth (`_settle_unborn`): one of this batch's names with
    its same-name ``siblings`` and its ``pending`` line, or a line an earlier batch parked (``stored``). ``heard`` is
    every conversation it came up in; ``passes`` says it clears the promotion bar on its own."""

    name: str
    key: str
    entity: dict
    siblings: list[dict]
    pending: PendingEntity | None
    heard: set[str]
    passes: bool
    stored: bool = False
    #: Judged a part of the page it lands on (2026-10-29): its own other names are never that page's aliases.
    part: bool = False

    def mentions(self) -> tuple[dict, ...]:
        if self.stored:
            return ()
        if self.part:
            return tuple({**e, "aliases": []} for e in (self.entity, *self.siblings))
        return (self.entity, *self.siblings)

    def names(self) -> list[str]:
        out = [self.name]
        for e in (self.entity, *self.siblings):
            out += [str(a) for a in e.get("aliases") or [] if str(a).strip()]
        return out

    def episodes(self) -> set[str]:
        out = {str(e.get("source_episode")) for e in self.mentions() if e.get("source_episode")}
        return out | set(self.pending.episodes() if self.pending is not None else ())


#: How many candidates one name with no birth is weighed against after the loop (`_settle_unborn`): two judge calls.
MAX_UNBORN_CANDIDATES = 2 * 6


def _settle_fallback(change: dict, birth) -> None:
    """A change that lands on a fallback page (owner 2026-10-23): with a birth it becomes the project — the birth rides
    to Stage 5, which writes ``born`` once and retypes the page on disk (`project_birth.retype_on_birth`), and a create
    in this batch drops its marker; without one the page keeps its type whatever the mention said."""
    if isinstance(birth, dict):
        prior = change.get("project_birth")
        change["project_birth"] = project_birth.birth_of({"project_birth": birth},
                                                         [{"project_birth": prior}] if isinstance(prior, dict) else [])
        change.pop(project_birth.PROPOSED_KEY, None)
    kind = "project" if isinstance(change.get("project_birth"), dict) else project_birth.FALLBACK_TYPE
    change["entity"] = {**(change.get("entity") or {}), "type": kind}


def _unborn_group_candidate(index: int, members: list[_Unborn]) -> dict:
    payload: dict = {}
    for m in members:
        for incoming in (*m.mentions(), *((_pending_payload(m.pending),) if m.stored and m.pending else ())):
            payload = _merge_entity_payload(payload, incoming) if payload else dict(incoming)
    payload["type"] = "project"
    return {"source": "unborn", "id": f"unborn:{members[0].key}", "data": {"entity": payload}, "index": index}


_EPISODE_DAY = re.compile(r"^ep_(\d{4})-?(\d{2})-?(\d{2})")


def _line_recency(line: _Unborn) -> str:
    """The latest day a parked line heard its name, as an ISO string ("" when it kept none)."""
    days = [str(r.get("timestamp") or r.get("day") or "") for r in (line.pending.heard_in if line.pending else [])
            if isinstance(r, dict)]
    for ep in line.episodes():
        m = _EPISODE_DAY.match(ep)
        if m:
            days.append(f"{m.group(1)}-{m.group(2)}-{m.group(3)}")
    return max(days, default="")


def _page_candidates(existing: list[dict], resolved_creates: dict[str, dict],
                     resolved_updates: dict[str, dict]) -> list[tuple[dict, list[str], set[str], str]]:
    """The pages a name with no birth may already be: every project page and fallback page on disk (not dropped), and
    every project this batch created — as ``(candidate, names, cited conversations, latest mention)``."""
    out = []
    for page in existing:
        fm = page.get("frontmatter") or {}
        candidate = {"source": "existing", "id": page["id"], "data": page}
        if "project" not in _candidate_types(candidate) or str(fm.get("status") or "active") == "dropped":
            continue
        cited = {str(e) for e in fm.get("source_episodes") or []} | set(
            (resolved_updates.get(page["id"]) or {}).get("source_episodes") or [])
        out.append((candidate, [str(fm.get("name") or page["id"]), *_page_aliases(page)], cited,
                    str(fm.get("last_referenced") or "")))
    for pid, change in resolved_creates.items():
        candidate = {"source": "created", "id": pid, "data": change}
        if "project" not in _candidate_types(candidate):
            continue
        entity = change.get("entity") or {}
        out.append((candidate, [str(entity.get("name") or pid), *(str(a) for a in entity.get("aliases") or [])],
                    set(change.get("source_episodes") or []), str(change.get("source_episode_timestamp") or "")))
    return out


def _unborn_candidates(u: _Unborn, groups: list[list[_Unborn]], pages, stored: dict[str, _Unborn],
                       memory_path) -> list[dict]:
    """What one name with no birth is weighed against, in this order, at most ``MAX_UNBORN_CANDIDATES``: what shares
    a conversation with it (this batch's other such names, project and fallback pages), then what shares a word or an
    alias (those, and the lines an earlier batch parked), then this batch's other such names, then the other pages and
    parked lines, latest mention first. A candidate that shares no word with it is judged with ``_UNSHARED_NOTE``; a
    page the person said is a different thing is never brought."""
    episodes, names = u.episodes(), u.names()
    keys = {person_leads.handle_key(n) for n in names}

    def shares_word(other: list[str]) -> bool:
        return (any(_share_content_token(a, b) for a in names for b in other)
                or bool(keys & {person_leads.handle_key(n) for n in other}))

    tiers: list[list[dict]] = [[], [], [], []]
    late: list[tuple[str, dict]] = []

    def place(candidate: dict, other: list[str], cited: set[str], recency: str, *, group: bool = False) -> None:
        candidate["names"] = other
        if episodes & cited:
            tiers[0].append({**candidate, "shared": True})
        elif shares_word(other):
            tiers[1].append({**candidate, "shared": True})
        elif group:
            tiers[2].append(candidate)
        else:
            late.append((recency, candidate))

    for i, members in enumerate(groups):
        place(_unborn_group_candidate(i, members), [n for m in members for n in m.names()],
              set().union(*(m.episodes() for m in members)), "", group=True)
    for candidate, other, cited, recency in pages:
        if not _said_different(memory_path, u.name, candidate["id"]):
            place(dict(candidate), other, cited, recency)
    for line in stored.values():
        place({"source": "held", "id": f"held:{line.key}", "data": {"entity": line.entity}, "line": line.key},
              line.names(), line.episodes(), _line_recency(line))
    tiers[3] = [c for _, c in sorted(late, key=lambda pair: pair[0], reverse=True)]
    out = [c for tier in tiers for c in tier][:MAX_UNBORN_CANDIDATES]
    for c in out:
        if not shares_word(c.pop("names")):
            c["note"] = _UNSHARED_NOTE
    return out


async def _judge_shared_first(entity: dict, candidates: list[dict], cache: dict, settings: Settings,
                              stop: Callable[[], bool] | None = None) -> list[tuple[dict, str]]:
    """What shares a word or a conversation is judged in a call of its own, before the pairs with no lead: in one
    crowded call the newuser canoe's two spellings stayed apart, though the judge joins them alone every time."""
    judged = await _judge_candidates(entity, [c for c in candidates if c.get("shared")], cache, settings, stop=stop)
    if not any(decision == "same" for _, decision in judged):
        judged += await _judge_candidates(entity, [c for c in candidates if not c.get("shared")], cache, settings,
                                          stop=stop)
    return judged


async def _fallback_match(entity: dict, siblings: list[dict], existing: list[dict], resolved_creates: dict[str, dict],
                          resolved_updates: dict[str, dict], cache: dict, settings: Settings,
                          cancel_check: Callable[[], bool] | None = None) -> dict | None:
    """The fallback page (on disk, or made in this batch) a project mention with a birth is judged the same as, or
    unsure about; ``None`` when it is none of them. The candidates are `_unborn_candidates`' over fallback pages only:
    aliases count, no shared word is needed, a page the person said is different is never brought, and "different"
    is final. An unsure verdict on a pair with no shared word or conversation is marked ``quiet``: the name is held,
    and no question is raised (as in `_settle_unborn`)."""
    pages = [p for p in _page_candidates(existing, resolved_creates, resolved_updates) if _is_fallback(p[0])]
    if not pages:
        return None
    u = _Unborn(name=str(entity.get("name") or ""), key=str(entity.get("name") or "").lower(), entity=entity,
                siblings=list(siblings), pending=None, heard=set(), passes=False)
    candidates = _unborn_candidates(u, [], pages, {}, Path(settings.memory_path))
    judged = await _judge_shared_first({**entity, "type": "project"}, candidates, cache, settings, cancel_check)
    match = _pick_match(u.name, judged)
    if match is not None and match["decision"] == "unsure" and not match["candidate"].get("shared"):
        match["quiet"] = True
    return match


async def _settle_unborn(
    unborn: list[_Unborn], *, existing: list[dict], resolved_updates: dict[str, dict],
    resolved_creates: dict[str, dict], name_to_id: dict[str, str], pending_actions: list, promoted_pending: list[str],
    clarifier: ClarificationManager, hold: Callable, cache: dict, settings: Settings,
    cancel_check: Callable[[], bool] | None = None, unsure_pairs: set[tuple[str, str]] | None = None,
) -> bool:
    """Owner 2026-10-23 (amends ruling 36 D4): what becomes of this batch's project names that nothing gave a birth.

    A project page still needs a repository or the person's own words. But the same thing said under several names —
    a canoe, its hull, the hull build — is one thing, so each name is first weighed by the judge (never by an alias
    alone, owner 2026-10-08) against the fallback pages already on disk, the other such names in this batch and the
    lines an earlier batch parked (`_unborn_candidates`). A name judged the same as a page — a project page, on disk
    or born in this batch, or a fallback page — lands on it (a mention needs no birth to join a page). The
    names judged the same as each other form one group, and the ordinary promotion rule is read over the whole group:
    2+ conversations between them, or one name clearing the bar on its own (more than 3 exchanges with the person's
    own words, a link the person made). A group over the bar gets ONE fallback page — a concept marked
    ``proposed_type: project``, under the name heard in the most conversations — carrying every member's mentions,
    pending lines and held claims. A group below it is held, each name as its own line, as before.

    Returns True when a cancel stopped it (the caller then discards the batch, as for any cancel)."""
    from api.services import pending_store

    memory_path = Path(settings.memory_path)
    threshold = settings.sleep_promotion_threshold
    existing_ids = {str(e.get("id")) for e in existing}
    pages = _page_candidates(existing, resolved_creates, resolved_updates)
    taken = {u.key for u in unborn} | {str(n).lower() for n in promoted_pending} | set(name_to_id)
    stored: dict[str, _Unborn] = {}
    try:
        lines = pending_store.load(memory_path)
    except Exception:
        lines = []
    for line in lines:
        key = line.name.lower()
        if str(line.type or "").lower() != "project" or line.correspondent or key in taken or key in stored:
            continue
        stored[key] = _Unborn(name=line.name, key=key, entity={**_pending_payload(line), "type": "project"},
                              siblings=[], pending=line, heard=set(line.episodes()) or {f"(unrecorded) {key}"},
                              passes=False, stored=True)

    groups: list[list[_Unborn]] = []
    on_page: dict[str, tuple[dict, list[_Unborn]]] = {}
    for u in unborn:
        if cancel_check is not None and cancel_check():
            return True
        candidates = _unborn_candidates(u, groups, pages, stored, memory_path)
        judged = await _judge_shared_first({**u.entity, "type": "project"}, candidates, cache, settings, cancel_check)
        if cancel_check is not None and cancel_check():
            return True
        match = _pick_match(u.name, judged)
        # Review of #545 (B2): only when nothing came back same or unsure — "unsure" about one page holds and asks.
        whole = _part_of_page(judged, u.name) if match is None else None
        if whole is not None:
            # 2026-10-29, the owner's 2026-10-23 rule ("a canoe, its hull, the hull build — is one thing"): a name the
            # judge calls a part, feature, stage, task or pull request of a page lands on that page as a mention of it
            # — never a question "is the part the same as the whole?", never a page competing with it.
            u.part = True
            on_page.setdefault(whole["id"], (whole, []))[1].append(u)
            continue
        candidate = match["candidate"] if match is not None else None
        if match is not None and match["decision"] == "same":
            if candidate["source"] in ("existing", "created"):
                on_page.setdefault(candidate["id"], (candidate, []))[1].append(u)
            elif candidate["source"] == "unborn":
                groups[candidate["index"]].append(u)
            else:   # a line an earlier batch parked: the two are one group from now on
                groups.append([stored.pop(candidate["line"]), u])
            continue
        unsure_pages = [c for c, decision in judged if decision == "unsure" and c["source"] in ("existing", "created")]
        if unsure_pages and unsure_pairs is not None:
            unsure_pairs.update((u.key, str(c["id"])) for c in unsure_pages)
        if unsure_pages:
            # Unsure about a page: held — never a second page beside the one it may be (as in the loop) — and asked
            # only when the two share a word or a conversation. A pair with no lead at all ("Epoxy workshop" against
            # "Cedar-strip canoe") is no question for the person: the name waits, and its next mention is judged again.
            asked = next((c for c in unsure_pages if c.get("shared")), None)
            if asked is not None:
                pending_actions.append((_create_duplicate_clarification, (),
                                        {"clarifier": clarifier, "entity": u.entity, "candidate": asked}))
            hold(u.name, u.entity, u.siblings, True)
            continue
        groups.append([u])

    def credit(change: dict, m: _Unborn, page_id: str) -> None:
        if m.pending is not None:
            _fold_pending(change, m.pending)
            promoted_pending.append(m.pending.name)
        name_to_id[m.key] = page_id
        pending_actions.append((clarifier.check_organic_resolution, (),
                                {"entity_name": m.name, "confidence": float(m.entity.get("confidence", 0.0) or 0.0),
                                 **({"merged_into": page_id} if page_id in existing_ids else {})}))

    for page_id, (candidate, members) in on_page.items():
        for m in members:
            for incoming in m.mentions():
                if candidate["source"] == "existing":
                    _merge_into_update(resolved_updates, candidate["data"], incoming)
                else:
                    _merge_into_create(resolved_creates[page_id], incoming)
            change = (resolved_updates if candidate["source"] == "existing" else resolved_creates)[page_id]
            credit(change, m, page_id)
            if _is_fallback(candidate):
                _settle_fallback(change, None)

    made = 0
    for members in groups:
        heard = set().union(*(m.heard for m in members))
        if not (any(m.passes for m in members) or len(promotion.conversation_keys(heard, memory_path)) >= threshold):
            for m in members:
                if not m.stored:
                    hold(m.name, m.entity, m.siblings, False)
            continue
        rep = max(members, key=lambda m: (len(m.heard), not m.stored, _specificity_key(m.entity)))
        entity_id = sanitize_id(rep.name)
        if entity_id in existing_ids or entity_id in resolved_creates:
            for m in members:   # that id is another page's: never folded into by its spelling
                if not m.stored:
                    hold(m.name, m.entity, m.siblings, False)
            continue
        change = _create_change(entity_id, dict(rep.entity) if not rep.stored else {
            "name": rep.name, "type": "project", "confidence": rep.entity.get("confidence", 0.5)})
        for m in members:
            for incoming in m.mentions():
                if incoming is not rep.entity:
                    _merge_into_create(change, incoming)
            credit(change, m, entity_id)
        # The page keeps the name it was heard by most (a merge would take the longest spelling, "Hull build project");
        # every other spelling the judge joined is an alias, so the next one is brought to the judge by it.
        others = [m.name for m in members if m is not rep]
        change["entity"] = {**change["entity"], "name": rep.name,
                            "aliases": _union_text(change["entity"].get("aliases"), others)}
        change[project_birth.PROPOSED_KEY] = "project"
        _settle_fallback(change, None)
        resolved_creates[entity_id] = change
        made += 1
    logger.info(f"Stage 2: {len(unborn)} project name(s) with no birth → {len(groups)} group(s), {made} fallback "
                f"page(s), {sum(len(m) for _, m in on_page.values())} onto existing pages")   # counts, never names
    return False


def _part_of_page(judged: list[tuple[dict, str]], name: str) -> dict | None:
    """The first page (on disk or born this batch) the judge called the name a part of, in judging order — never one
    whose own name carries the mention's whole name (the direction guard, `entity_relations.plausible`)."""
    return next((c for c, decision in judged
                 if entity_relations.relation_of(decision) == "part_of" and c.get("source") in ("existing", "created")
                 and entity_relations.plausible("part_of", name, _candidate_display_name(c))), None)


def _same_repository_match(entity: dict, siblings, existing: list[dict],
                           created_by_id: dict[str, dict], memory_path, cache: dict) -> dict | None:
    """``{"decision": "same", candidate}`` when this project mention's repository birth carries a hashed remote that
    exactly one project page's repository has (`project_birth.same_repository_page`); a pair the person said were
    different is never joined. ``cache`` holds the bank's family → remotes map, read once per resolve and only when
    a birth carries a remote."""
    birth = project_birth.birth_of(entity, siblings)
    if not ((birth or {}).get("repo") or {}).get("remote"):
        return None
    if "families" not in cache:
        cache["families"] = project_birth.remote_families(memory_path)
    by_id = {str(d["id"]): d for d in existing if str((d.get("frontmatter") or {}).get("status") or "") != "dropped"
             and "project" in _candidate_types({"source": "existing", "id": d["id"], "data": d})}
    pid = project_birth.same_repository_page(birth, [(i, d.get("frontmatter") or {}) for i, d in by_id.items()],
                                             families=cache["families"])
    if pid is not None:
        candidate = {"source": "existing", "id": pid, "data": by_id[pid]}
    else:
        made = [(cid, {"born": change.get("project_birth")}) for cid, change in created_by_id.items()
                if isinstance(change.get("project_birth"), dict)]
        pid = project_birth.same_repository_page(birth, made, families=cache["families"])
        if pid is None:
            return None
        candidate = {"source": "created", "id": pid, "data": created_by_id[pid]}
    if _said_different(memory_path, str(entity.get("name") or ""), pid):
        return None
    return {"decision": "same", "candidate": candidate}


def _project_alias_candidate(entity: dict, siblings, existing_by_name: dict[str, dict],
                             created_by_id: dict[str, dict]) -> dict | None:
    """The judge's candidate for a project mention whose recorded alias is the name (or an alias) of exactly ONE
    project page — on disk, else born in this batch. ``None`` when no alias names one, or two do."""
    names = {person_leads.handle_key(a) for e in (entity, *siblings) for a in (e.get("aliases") or [])
             if str(a).strip()} - {person_leads.handle_key(entity.get("name") or "")}
    if not names:
        return None
    hits: dict[str, dict] = {}
    for data in existing_by_name.values():
        candidate = {"source": "existing", "id": data["id"], "data": data}
        fm = data.get("frontmatter") or {}
        keys = {person_leads.handle_key(fm.get("name") or data["id"])} | {
            person_leads.handle_key(a) for a in (fm.get("aliases") or []) if str(a).strip()}
        if "project" in _candidate_types(candidate) and names & keys:
            hits[data["id"]] = candidate
    if not hits:
        for pid, change in created_by_id.items():
            candidate = {"source": "created", "id": pid, "data": change}
            created = change.get("entity") or {}
            keys = {person_leads.handle_key(created.get("name") or pid)} | {
                person_leads.handle_key(a) for a in (created.get("aliases") or []) if str(a).strip()}
            if "project" in _candidate_types(candidate) and names & keys:
                hits[pid] = candidate
    if len(hits) != 1:
        return None
    return next(iter(hits.values()))


#: W1's bound: at most this many questions about a name with no page are open at once, so the first Sleep over a bank
#: whose pending store holds years of names raises three, and the next only as the person answers or dismisses one.
MAX_HELD_ALIAS_QUESTIONS = 3


def _held_alias_questions(held_people: list[tuple[dict, list[dict]]], existing: list[dict],
                          resolved_creates: dict[str, dict], clarifier: ClarificationManager,
                          memory_path, *, owner_page_id: str | None = None) -> list[tuple[Callable, tuple, dict]]:
    """W1 (benchmarks/newuser, 2026-10-22; G209): a person name held below the promotion bar — this batch's, or a line
    an earlier run parked — whose recorded alias is the name of exactly one person page (on disk, or born in this
    batch) raises the "Possible duplicate of …" question. Never a merge: who a person is takes the person's own answer
    (ruling 29). An alias two pages answer to asks nothing; a pair the person said were different (or dismissed) is
    never asked. At most ``MAX_HELD_ALIAS_QUESTIONS`` questions about a name with no page are open at once.

    Specific names are judged first, so a full name said once ("Teodor Brandt", aliases "Teo", "tbrandt") is held
    before the short name its other conversations promote ("Teo") has a page — the two never met.

    A held full name with no alias that names a page asks the same question when its given name is the whole title of
    exactly one person page ("Bea Example" held, a page titled "Bea"; benchmarks/newuser, 2026-10-23) and no
    other person page's name begins with that word — two Sams ask nothing. Never the owner's page or a page titled by
    a relation (`role_people`), never a name that has a page of its own."""
    pages: dict[str, list[tuple[str, str]]] = {}
    for page in existing:
        fm = page.get("frontmatter") or {}
        if str(fm.get("type") or "").lower() == "person" and page.get("id"):
            pages.setdefault(person_leads.handle_key(person_leads.page_name(page)), []).append(
                (str(page["id"]), person_leads.page_name(page)))
    for pid, change in resolved_creates.items():
        entity = change.get("entity") or {}
        if str(entity.get("type") or "").lower() == "person":
            pages.setdefault(person_leads.handle_key(entity.get("name") or ""), []).append(
                (pid, str(entity.get("name") or pid)))
    given_pages = _given_name_pages(existing, resolved_creates, owner_page_id)
    full_pages = _full_name_pages(existing, resolved_creates, owner_page_id)

    from api.services import pending_store

    held: dict[str, tuple[str, set[str], dict]] = {}
    for entity, siblings in held_people:
        name = str(entity.get("name") or "").strip()
        names = {a for e in (entity, *siblings) for a in (e.get("aliases") or []) if str(a).strip()}
        held[person_leads.handle_key(name)] = (name, names, entity)
    try:
        lines = pending_store.load(Path(memory_path)) if memory_path else []
    except Exception:  # noqa: BLE001 — an unreadable store holds nothing to ask about
        lines = []
    for line in lines:
        if str(line.type or "").lower() == "person" and person_leads.handle_key(line.name) not in held:
            held[person_leads.handle_key(line.name)] = (
                line.name, set(line.aliases or []),
                {"name": line.name, "source_episode": line.source_episode, "confidence": line.confidence})

    from api.services.inbox_generator import find_open

    page_ids = {str(page.get("id")) for page in existing} | set(resolved_creates)
    room = MAX_HELD_ALIAS_QUESTIONS - _open_held_duplicates(Path(memory_path), page_ids)
    actions: list[tuple[Callable, tuple, dict]] = []
    for key, (name, aliases, entity) in held.items():
        hits = {hit for alias in aliases if person_leads.handle_key(alias) != key
                for hit in pages.get(person_leads.handle_key(alias), [])}
        by_given = False
        heard_in = None
        if not hits and key not in pages:
            hit = given_pages.get(_given_name(name) or "")
            hits, by_given = ({hit}, True) if hit is not None else (hits, False)
        if not hits and key not in pages and len(_name_words(_bare(name))) == 1:
            # One person across sources (owner 2026-10-28): a one-word name heard outside a chat ("Alice" in a
            # harness session) whose word begins exactly one full-name person page heard in a chat is ASKED about,
            # never joined — a shared first name is no proof (G209). Only across sources: two people in one place
            # sharing a first name ask nothing here.
            hit = full_pages.get(_name_words(_bare(name))[0])
            if hit is not None:
                born = resolved_creates.get(hit[0])
                heard_in = _cross_source(memory_path, entity, hit[0], existing,
                                         [str(e) for e in (born or {}).get("source_episodes") or [] if e]
                                         if born is not None else None)
                hits = {hit} if heard_in is not None else hits
        if len({pid for pid, _ in hits}) != 1:
            continue
        pid, page_name = next(iter(hits))
        if _said_different(memory_path, name, pid):
            continue
        if find_open(Path(memory_path), "merge_suggestion", sanitize_id(name), pid) is None:
            if room <= 0:
                continue
            room -= 1
        said = sorted(a for a in aliases if person_leads.handle_key(a) == person_leads.handle_key(page_name))
        context = (f"{name} came up {heard_in['mention']}; {page_name} is someone {heard_in['page']}."
                   if heard_in is not None else
                   f"A conversation named {name} in full; {page_name}'s page carries only the given name."
                   if by_given else
                   f"A conversation also called {name} “{said[0] if said else page_name}”, "
                   f"the name {page_name}'s page carries.")
        actions.append((clarifier.create, (), {
            "entity_name": name,
            "source_episode": entity.get("source_episode", ""),
            "uncertainty_type": f"Possible duplicate of {page_name}",
            "suggested_classification": f"person — could refer to the same person as {page_name}",
            "suggested_confidence": float(entity.get("confidence", 0.0) or 0.0),
            "source_context": context,
            "source_episode_timestamp": entity.get("source_episode_timestamp"),
            **({"heard_in": heard_in} if heard_in is not None else {}),
        }))
    return actions


#: Where a mention was heard, as the question says it ("you talked to Claude about"); a chat is "in your group chat"
#: or "in your messages". A source not listed is "in another conversation".
HEARD_IN = {"claude-code": "you talked to Claude about", "claude-export": "you talked to Claude about",
            "codex": "you talked to Codex about", "cursor": "you talked to Cursor about",
            "gemini-cli": "you talked to Gemini about", "chatgpt-export": "you talked to ChatGPT about",
            "gemini-export": "you talked to Gemini about",
            # The origins those sources really write (#527 review): Apple Notes `apple-notes`, the Telegram bot's
            # notes `telegram`, Calendar on this Mac `calendar-local` and a subscribed one `calendar`, Reminders
            # `reminders-local`, a Notion export `notion-export`, Wispr Flow `wispr-flow`.
            "apple-notes": "in your notes", "telegram": "in a note you sent yourself",
            "calendar-local": "in your calendar", "calendar": "in your calendar",
            "reminders-local": "in your reminders", "notion-export": "in your Notion pages",
            "wispr-flow": "in something you dictated"}


def _episode_record(memory_path, episode_id: str) -> dict:
    from api.services import bank_index

    if not memory_path or not str(episode_id or "").startswith("ep_"):
        return {}
    entry = bank_index.file(Path(memory_path), "episodes", f"{episode_id}.md")
    return dict(entry.frontmatter or {}) if entry is not None else {}


def _cross_source(memory_path, entity: dict, page_id: str, existing: list[dict],
                  episodes: list[str] | None = None) -> dict | None:
    """``{mention, page}`` — where a held one-word name was heard and where the page's person was — when the page is
    a chat participant's (one of its conversations is a chat sitting, `contact_identity.chat_origins`) and the
    mention was heard elsewhere; else ``None``. ``episodes`` are a page born in this batch's own (it is not on disk)."""
    mention = _episode_record(memory_path, str(entity.get("source_episode") or ""))
    origin = str(mention.get("origin") or entity.get("origin") or "")
    chats_set = contact_identity.chat_origins()
    if not origin or origin in chats_set:
        return None
    if episodes is None:
        page = next((p for p in existing if str(p.get("id")) == page_id), None)
        episodes = [str(e) for e in ((page or {}).get("frontmatter") or {}).get("source_episodes") or []]
    chats = [rec for rec in (_episode_record(memory_path, e) for e in episodes[:50])
             if str(rec.get("origin") or "") in chats_set]
    if not chats:
        return None
    where = "in your group chat" if any(rec.get("group") for rec in chats) else "in your messages"
    return {"mention": HEARD_IN.get(origin, "in another conversation"), "page": where}


_TRAILING_NOTE = re.compile(r"\s*\([^()]*\)\s*$")


def _bare(name: str) -> str:
    """A name without the model's trailing note ("Alice (unnamed surname)" -> "Alice")."""
    return _TRAILING_NOTE.sub("", str(name or "")).strip()


def _first_name_across(memory_path, entity: dict, match: dict, existing: list[dict]) -> dict | None:
    """``heard_in`` when a one-word person name heard outside a chat was matched to a full-name person page — on disk,
    or born in this batch — that begins with that word and was heard in a chat (`_cross_source`); else ``None``."""
    candidate = match.get("candidate") or {}
    if not _is_person(entity) or candidate.get("source") not in ("existing", "created"):
        return None
    said = _name_words(_bare(str(entity.get("name") or "")))
    data = candidate.get("data") or {}
    if candidate["source"] == "existing":
        title, episodes = person_leads.page_name(data) if data else "", None
    else:
        title = str((data.get("entity") or {}).get("name") or "")
        episodes = [str(e) for e in data.get("source_episodes") or [data.get("source_episode")] if e]
    words = _name_words(title)
    if len(said) != 1 or not (2 <= len(words) <= 4) or words[0] != said[0]:
        return None
    return _cross_source(memory_path, entity, str(candidate.get("id") or ""), existing, episodes)


def _full_name_pages(existing: list[dict], resolved_creates: dict[str, dict],
                     owner_page_id: str | None) -> dict[str, tuple[str, str]]:
    """Folded first word -> ``(page id, title)`` of the ONE person page whose name begins with it and has two to four
    words, when no other person page's name begins with that word. The owner's page and a page titled by a relation
    (`role_people`) never count."""
    starts: dict[str, set[tuple[str, str]]] = {}
    rows = [(str(page.get("id") or ""), page.get("frontmatter") or {}, person_leads.page_name(page))
            for page in existing]
    rows += [(pid, change.get("entity") or {}, str((change.get("entity") or {}).get("name") or pid))
             for pid, change in resolved_creates.items()]
    for pid, fm, title in rows:
        if not pid or str(fm.get("type") or "").lower() != "person":
            continue
        if (pid == owner_page_id or fm.get("owner") or fm.get(role_people.UNNAMED_KEY)
                or role_people.parse(title, bare=True)):
            continue
        words = _name_words(title)
        if words:
            starts.setdefault(words[0], set()).add((pid, title, len(words)))
    return {word: (next(iter(hits))[0], next(iter(hits))[1]) for word, hits in starts.items()
            if len(hits) == 1 and 2 <= next(iter(hits))[2] <= 4}


def _name_words(name: str) -> list[str]:
    """The words of a person's name as written ("Bea Example", "Anne-Marie O'Neil"), folded; ``[]`` for anything
    else — a handle, a lowercase phrase, a parenthesis, a digit."""
    words = str(name or "").split()
    for word in words:
        bare = re.sub(r"['’.\-]", "", word)
        if not bare.isalpha() or not word[0].isupper():
            return []
    return [text_fold.fold(word) for word in words]


def _given_name(name: str) -> str | None:
    """A full name's given name, folded: the first of two to four name words; ``None`` for a one-word name."""
    words = _name_words(name)
    return words[0] if 2 <= len(words) <= 4 else None


def _given_name_pages(existing: list[dict], resolved_creates: dict[str, dict],
                      owner_page_id: str | None) -> dict[str, tuple[str, str]]:
    """Folded given name -> ``(page id, title)`` of the ONE person page titled by that word alone, on disk or born in
    this batch, when no other person page's name begins with it. The owner's page and a page titled by a relation
    (`role_people`) never count."""
    titled: dict[str, set[tuple[str, str]]] = {}
    starts: dict[str, set[str]] = {}
    rows = [(str(page.get("id") or ""), page.get("frontmatter") or {}, person_leads.page_name(page))
            for page in existing]
    rows += [(pid, change.get("entity") or {}, str((change.get("entity") or {}).get("name") or pid))
             for pid, change in resolved_creates.items()]
    for pid, fm, title in rows:
        if not pid or str(fm.get("type") or "").lower() != "person":
            continue
        if (pid == owner_page_id or fm.get("owner") or fm.get(role_people.UNNAMED_KEY)
                or role_people.parse(title, bare=True)):
            continue
        words = _name_words(title)
        if not words:
            continue
        starts.setdefault(words[0], set()).add(pid)
        if len(words) == 1:
            titled.setdefault(words[0], set()).add((pid, title))
    return {word: next(iter(hits)) for word, hits in titled.items()
            if len(hits) == 1 and starts.get(word) == {next(iter(hits))[0]}}


def _open_held_duplicates(memory_path: Path, page_ids: set[str]) -> int:
    """How many open "Possible duplicate" questions are about a name that has no page — W1's own, and a G209 lead's
    on a held name."""
    from api.services import markdown_parser

    count = 0
    for path in sorted((memory_path / "inbox").glob("inbox-*.md")):
        try:
            fm = markdown_parser.parse(path).frontmatter
        except Exception:  # noqa: BLE001 — an unreadable item is not counted
            continue
        if (fm.get("kind") == "merge_suggestion" and fm.get("status") == "pending"
                and str(fm.get("entity_id") or "") not in page_ids):
            count += 1
    return count


def _create_lead_clarification(clarifier: ClarificationManager, lead: "person_leads.Lead",
                               index: "person_leads.PersonIndex", entity: dict, held: bool = False) -> None:
    """The "Possible duplicate of …" question a G209 lead raises: the page carrying the name (``lead.page``) against
    the page that lists it (``lead.holder``), the lead in words as its context. Never a merge; a pair the person
    already said were different is never asked again (`ClarificationManager.create`)."""
    page = index.by_id.get(lead.page)
    holder = index.by_id.get(lead.holder) or {}
    holder_name = person_leads.page_name(holder)
    try:
        item = clarifier.create(
            # A name still below the promotion bar has no page: the question is about the name as it was said.
            entity_name=person_leads.page_name(page) if page is not None else str(entity.get("name") or lead.key),
            source_episode=entity.get("source_episode", ""),
            uncertainty_type=f"Possible duplicate of {holder_name}",
            suggested_classification=(f"person — could refer to the same person as {holder_name}"
                                      if index.types == person_leads.PERSON_TYPES else
                                      f"{_lead_type(page, holder)} — could refer to the same thing as {holder_name}"),
            suggested_confidence=float(entity.get("confidence", 0.0) or 0.0),
            source_context=person_leads.lead_reason(lead, holder_name),
            source_episode_timestamp=entity.get("source_episode_timestamp"),
        )
        if held:   # asked about the mention this batch held, not the page that carries its name
            _mark_held_mention(clarifier, item)
    except Exception as e:
        logger.debug(f"Failed to create a lead question: {type(e).__name__}")


#: Lead verdicts kept for the process, never in a bank (review of #545, B3): keyed by bank, the two pages and their
#: files' modification times, so a drain's later batches reuse the verdict and an edited page is judged afresh.
_LEAD_VERDICTS: dict[tuple, str] = {}
_LEAD_VERDICTS_MAX = 4096


def _lead_key(memory_path, lead: "person_leads.Lead") -> tuple | None:
    if memory_path is None:
        return None
    entities = Path(memory_path) / "entities"
    try:
        stamps = tuple((entities / f"{pid}.md").stat().st_mtime_ns for pid in (lead.page, lead.holder))
    except OSError:
        return None
    return (str(Path(memory_path).resolve()), lead.page, lead.holder, stamps)


async def _judge_lead(lead: "person_leads.Lead", index: "person_leads.PersonIndex", settings: Settings, *,
                      gate: asyncio.Semaphore | None = None) -> str:
    """The judge's word on an organisation/tool/project alias lead (2026-10-29): ``same`` / ``unsure`` (the question
    is asked, as before), ``different`` or ``related:<relation>`` (it is not). No call (review of #545, B3) when the
    record already relates the pair (`entity_relations.known`: ``different``), the person rejected it (``different``:
    never asked again), a question about it is already open (``unsure``: the open one is bumped, as before), or this
    process judged the same two page versions already (the memo); a lead with no page on its named side is asked."""
    from api.services.inbox_generator import find_open

    page = index.by_id.get(lead.page)
    holder = index.by_id.get(lead.holder)
    if page is None or holder is None:
        return "unsure"
    memory_path = getattr(settings, "memory_path", None)
    page_name = person_leads.page_name(page)
    if memory_path is not None:
        if _said_different(memory_path, page_name, lead.holder) or _said_different(memory_path, lead.page,
                                                                                    lead.holder):
            return "different"
        if find_open(Path(memory_path), "merge_suggestion", sanitize_id(page_name), lead.holder) is not None:
            return "unsure"
    if entity_relations.known(memory_path, lead.page, lead.holder):
        return "different"
    key = _lead_key(memory_path, lead)
    if key is not None and key in _LEAD_VERDICTS:
        return _LEAD_VERDICTS[key]
    page_candidate = {"source": "existing", "id": lead.page, "data": page}
    holder_candidate = {"source": "existing", "id": lead.holder, "data": holder}
    kwargs = dict(new_name=page_name, new_type=_candidate_type(page_candidate),
                  new_description=_candidate_description(page_candidate),
                  existing_name=person_leads.page_name(holder), existing_type=_candidate_type(holder_candidate),
                  existing_body=_alias_page_context(holder) if lead.kind == "alias" else
                  _candidate_description(holder_candidate),
                  settings=settings, recorded_alias=lead.kind == "alias", types_may_differ=True)
    if gate is None:
        verdict = await _llm_judge_same_entity(**kwargs)
    else:
        async with gate:
            verdict = await _llm_judge_same_entity(**kwargs)
    if key is not None:
        if len(_LEAD_VERDICTS) >= _LEAD_VERDICTS_MAX:
            _LEAD_VERDICTS.clear()
        _LEAD_VERDICTS[key] = verdict
    return verdict


def _lead_relation(lead: "person_leads.Lead", index: "person_leads.PersonIndex", verdict: str, entity: dict) -> dict:
    """A lead's relation as a relationship between its two pages, pinned by id."""
    relation = entity_relations.relation_of(verdict) or ""
    b_name = person_leads.page_name(index.by_id.get(lead.page) or {}) or lead.page
    a_name = person_leads.page_name(index.by_id.get(lead.holder) or {}) or lead.holder
    return entity_relations.relationship(relation, b_name, a_name, a_id=lead.holder, b_id=lead.page,
                                         episode=str(entity.get("source_episode") or ""),
                                         timestamp=entity.get("source_episode_timestamp"))


def _lead_type(page: dict | None, holder: dict) -> str:
    return str(((page or holder or {}).get("frontmatter") or {}).get("type") or "concept")


def _mark_held_mention(clarifier: ClarificationManager, item: object) -> None:
    """Mark a question Stage 2 just raised as one about the mention it held (:data:`HELD_MENTION_KEY`). A re-ask
    (``create`` returned ``None``) or a test double writes nothing."""
    path = getattr(clarifier, "dir", None)
    if not isinstance(item, str) or not isinstance(path, Path) or not (path / f"{item}.md").is_file():
        return
    from api.services import markdown_parser

    parsed = markdown_parser.parse(path / f"{item}.md")
    markdown_parser.write(path / f"{item}.md", {**parsed.frontmatter, HELD_MENTION_KEY: True}, parsed.body)


def _find_direct_candidate_match(
    new_entity: dict,
    existing_by_name: dict[str, dict],
    created_by_id: dict[str, dict],
    aliases: dict[str, list[dict]] | None = None,
    same_title: dict[str, list[dict]] | None = None,
    rejected: frozenset | set = frozenset(),
) -> dict | None:
    """A join on the name itself: the page titled exactly so, else a close spelling (``fuzz.ratio > 85``), else a
    create of this batch. ``same_title`` (G227; ``None`` keeps the old exact join): every page by its lower-cased title,
    so an exact title joins only the one page of the mention's kind (:func:`_same_title_pick`)."""
    new_name = (new_entity.get("name") or "").strip()
    new_name_lower = new_name.lower()
    person = _is_person(new_entity)

    existing_match = existing_by_name.get(new_name_lower)
    if existing_match is not None and same_title is not None and not person:
        # G227: a title two pages share, or a page of another kind than the mention, is never joined on the name
        # alone — the one page of the mention's kind is, and anything else goes to the same-title judge
        # (`_same_title_match`), which asks when it cannot tell.
        group = same_title.get(new_name_lower) or [existing_match]
        # A page the person said THIS mention is not (its line's `apart`, on a re-read of the same conversation) is never
        # joined on the name; a name→page rejection never stands in for that (#546 review).
        group = [p for p in group if not _rejected_pair(rejected, new_name, p.get("id"))]
        existing_match = _same_title_pick(new_entity, group) if group else None
        if existing_match is None:
            return None
    if existing_match is not None and not (person and _shared_name(new_name, existing_match, aliases)):
        return {
            "decision": "same",
            "candidate": {"source": "existing", "id": existing_match["id"], "data": existing_match},
        }

    if existing_match is None:
        for existing_name, existing_data in existing_by_name.items():
            if (fuzz.ratio(new_name_lower, existing_name) > 85
                    and (person or not distinct_names(new_name_lower, existing_name))
                    and not (person and (_near_person(new_name, existing_name)
                                         or _shared_name(new_name, existing_data, aliases)))):
                return {
                    "decision": "same",
                    "candidate": {"source": "existing", "id": existing_data["id"], "data": existing_data},
                }

    for candidate_id, create_change in created_by_id.items():
        candidate_entity = create_change.get("entity", {}) or {}
        candidate_name = str(candidate_entity.get("name", "")).lower()
        if not candidate_name:
            continue
        if candidate_name == new_name_lower or (fuzz.ratio(new_name_lower, candidate_name) > 85
                                                and (person or not distinct_names(new_name_lower, candidate_name))
                                                and not (person and _near_person(new_name, candidate_name))):
            return {
                "decision": "same",
                "candidate": {"source": "created", "id": candidate_id, "data": create_change},
            }

    return None


def _page_kind(page: dict) -> str:
    return entity_types.in_set(((page or {}).get("frontmatter") or {}).get("type") or "concept")


def _same_title_pick(new_entity: dict, group: list[dict]) -> dict | None:
    """The one page among those titled exactly as the mention that a join on the name may take (G227), or None.

    A page of the mention's own kind (a fallback page counts as a project, `_candidate_types`) when exactly one is; a
    ``concept`` mention — Stage 1's word for anything it could not place — the one page that is not a saved link when
    there is exactly one. Two of its kind, or none (a program said where only an IDE has the name), is the judge's."""
    new_type = entity_types.in_set(new_entity.get("type") or "concept")
    pages = [p for p in group if p is not None]
    same_kind = [p for p in pages if new_type in _candidate_types({"source": "existing", "id": p.get("id"), "data": p})]
    if len(same_kind) == 1:
        return same_kind[0]
    if not same_kind and new_type == "concept":
        placed = [p for p in pages if _page_kind(p) != "media"]
        if len(placed) == 1:
            return placed[0]
    return None


#: The same-title judge's note (G227): two kinds of thing are often called the same.
_SAME_TITLE_NOTE = ("Note: entity A's page has exactly this name, and the recorded types may differ. Different things "
                    "are often called the same (a program and a software tool, a company and a saved web page, two "
                    "people). A type recorded from one conversation can be wrong, so decide from the descriptions: "
                    "say SAME only when B's description clearly describes A; say DIFFERENT when it describes another "
                    "thing that shares the name; say UNSURE when there is too little to tell.\n")


async def _same_title_match(entity: dict, same_title: dict[str, list[dict]], cache: dict[tuple[str, str], str],
                            settings: Settings, *, gate: asyncio.Semaphore | None = None,
                            stop: Callable[[], bool] | None = None,
                            rejected: frozenset | set = frozenset()) -> dict | None:
    """G227: a mention titled exactly as one or more pages that a join on the name may not take
    (:func:`_same_title_pick`) — each page weighed by the judge, the types allowed to differ.

    ``same`` on one joins it; ``unsure`` holds the name and asks (the match carries ``same_title``: every page sharing
    the title, so the question names each one, `inbox_wording`); ``different`` on all is no match — the name goes on by
    the usual rule (a page of its own over the bar, which the qualifier tells apart, or a held line). Never a guess."""
    if _is_person(entity):
        return None
    name = (entity.get("name") or "").strip()
    key = name.lower()
    # The pages the person said THIS mention is not (`_apart_here`) are out: never judged, never asked again.
    group = [p for p in same_title.get(key) or () if p is not None and not _rejected_pair(rejected, name, p.get("id"))]
    if not group or _same_title_pick(entity, group) is not None:
        return None
    new_type = (entity.get("type") or "concept").lower()
    description = _effective_summary(entity)
    judged: list[tuple[dict, str]] = []
    for page in group:
        candidate = {"source": "existing", "id": page["id"], "data": page}
        decision = cache.get((key, page["id"]))
        if decision is None:
            if stop is not None and stop():
                break
            kwargs = dict(new_name=name, new_type=new_type, new_description=description,
                          existing_name=_candidate_display_name(candidate), existing_type=_candidate_type(candidate),
                          existing_body=_candidate_description(candidate), settings=settings,
                          note=_SAME_TITLE_NOTE, types_may_differ=True)
            if gate is None:
                decision = await _llm_judge_same_entity(**kwargs)
            else:
                async with gate:
                    decision = await _llm_judge_same_entity(**kwargs)
            cache[(key, page["id"])] = decision
        judged.append((candidate, decision))
        if decision == "same":
            break
    match = _pick_match(name, judged)
    if match is not None and match["decision"] == "unsure":
        match = {**match, "same_title": [p["id"] for p in group]}
    return match


def _shared_name(new_name: str, page: dict, aliases: dict[str, list[dict]] | None) -> bool:
    """A person name two or more other pages answer to, or a page titled by a nickname (owner ruling 2026-10-27): never a direct
    join on the name alone — the page goes to the judge with every other person page that lists the name. "Babe",
    "bro", initials: a nickname two people share says nothing about which one a new mention is."""
    fm = (page or {}).get("frontmatter") or {}
    if str(fm.get("type") or "").lower() != "person":
        return False
    if fm.get(role_people.NICKNAME_KEY):
        return True
    # One other page listing it is G209's lead (the mention stays on its own page and the question is asked); two or
    # more mean the name is common to several people.
    return sum(1 for other in (aliases or {}).get(person_leads.handle_key(new_name), ())
               if str(other.get("id")) != str(page.get("id")) and _page_type(other) == "person") >= 2


def _another_id(name: str, existing_ids: set[str], creates: dict[str, dict]) -> str:
    """The id for a page the person said is not the one already called ``name``: ``<slug>-2``, ``-3`` … (G227, owner
    2026-10-29). The title stays ``name`` — clean, never "(another)" — and the qualifier (`same_name`) tells the
    pages apart wherever the name shows; the id alone keeps them apart in links and on disk."""
    base = sanitize_id(name)
    n = 2
    while f"{base}-{n}" in existing_ids or f"{base}-{n}" in creates:
        n += 1
    return f"{base}-{n}"


def _is_person(entity: dict) -> bool:
    return str((entity or {}).get("type") or "").strip().lower() == "person"


def _near_person(a: str, b: str) -> bool:
    """Two person names the direct match's ``fuzz.ratio > 85`` would join that are NOT one spelling once case, accents,
    spacing and punctuation are set aside ("Delphine" / "Delfine") — 2026-10-27: two people are never joined on a
    name's resemblance (`role_people` rail, ruling 29), so such a pair goes to the judge as a close spelling instead."""
    return _spelling_key(a) != _spelling_key(b)


def _page_aliases(page: dict) -> list[str]:
    values = (page.get("frontmatter") or {}).get("aliases")
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return []
    return [text for text in (str(v or "").strip() for v in values) if text]


def _drop_conversation_names(extracted: list[dict]) -> int:
    """Take out of each extracted thing's ``aliases`` every name — or alias — of ANOTHER thing extracted from the same
    conversation (2026-10-27), unless that other thing lists this one's name back. Two people named in one conversation
    ("A and B applied together") are two things; an alias is a name this thing goes by, never a name (or a nickname)
    that belongs to someone beside it. Two entries that list each other ("Full Name" ↔ "Nick") are the extractor saying
    they are one thing: kept. A nickname two entries of one conversation both claim is ambiguous: dropped from both.

    Either way the two are marked ``NAMED_WITH`` each other, so the judge weighs the pair with a "named together in one
    conversation" note (`_spelling_lead`) and neither page is created unjudged. In place; returns how many went."""
    dropped = 0
    for extraction in extracted or []:
        entities = [e for e in extraction.get("entities", []) or [] if isinstance(e, dict)]
        by_key = {person_leads.handle_key(e.get("name") or ""): e for e in entities}
        by_key.pop("", None)
        alias_of: dict[str, list[dict]] = {}
        listed_by: dict[int, set[str]] = {}   # what each entry listed before any drop: the decision is order-free
        for e in entities:
            listed_by[id(e)] = {person_leads.handle_key(a) for a in e.get("aliases") or [] if isinstance(a, str)}
            for a in e.get("aliases") or []:
                if isinstance(a, str) and a.strip():
                    alias_of.setdefault(person_leads.handle_key(a), []).append(e)
        for entity in entities:
            listed = entity.get("aliases")
            if not isinstance(listed, list) or not listed:
                continue
            own = person_leads.handle_key(entity.get("name") or "")
            kept = []
            for alias in listed:
                key = person_leads.handle_key(alias)
                named_other = by_key.get(key) if key != own else None
                others = ([named_other] if named_other is not None else
                          [e for e in alias_of.get(key, ()) if e is not entity] if key != own else [])
                if named_other is None and len(key) >= 3 and any(w.startswith(key) for w in own.split()):
                    others = []   # the start of a word of its own name: its own short form
                if not others:
                    kept.append(alias)
                    continue
                for other in others:
                    for a, b in ((entity, other), (other, entity)):
                        named = a.setdefault(NAMED_WITH, [])
                        if b.get("name") and b["name"] not in named:
                            named.append(b["name"])
                if all(own in listed_by.get(id(o), ()) for o in others):
                    kept.append(alias)   # listed both ways: one thing, by the extractor's own word
            if len(kept) != len(listed):
                dropped += len(listed) - len(kept)
                entity["aliases"] = kept
    return dropped


#: An extracted entity's field (never written to a page): the names of things the same conversation's extraction
#: tied to it by an alias (`_drop_conversation_names`); each is a lead for the judge.
NAMED_WITH = "_named_with"


def _page_type(page: dict) -> str:
    return str(((page or {}).get("frontmatter") or {}).get("type") or "concept").lower()


def _alias_index(existing_by_name: dict[str, dict]) -> dict[str, list[dict]]:
    """``alias.lower() -> the pages listing it`` (frontmatter ``aliases``, which Stage 5
    unions from every extraction merged into the page and a manual merge fills with the
    loser's name). A hit makes the page a judge candidate, never a decision: one page
    holding an alias today says nothing about the next thing with those letters."""
    index: dict[str, list[dict]] = {}
    for page in existing_by_name.values():
        for alias in _page_aliases(page):
            holders = index.setdefault(person_leads.handle_key(alias), [])
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
    heard_in: dict | None = None,
    same_title: list[str] | None = None,
) -> None:
    """Ask whether ``entity`` is ``candidate``. ``same_title`` (G227): every page sharing the mention's exact title,
    so the item points at the candidate by id (never by a name two pages answer to) and the question names each."""
    candidate_name = _candidate_display_name(candidate)
    try:
        item = clarifier.create(
            **({"heard_in": heard_in} if heard_in else {}),
            **({"same_title": same_title, "target_id": candidate["id"]}
               if same_title and candidate.get("source") == "existing" else {}),
            entity_name=entity.get("name", "unknown"),
            source_episode=entity.get("source_episode", ""),
            uncertainty_type=f"Possible duplicate of {candidate_name}",
            suggested_classification=(
                f"{entity.get('type', 'concept')} — "
                f"could refer to the same entity as {candidate_name}"
            ),
            suggested_confidence=float(entity.get("confidence", 0.0) or 0.0),
            source_context=(
                _effective_summary(entity)
                or f"Could not safely decide whether this refers to {candidate_name}."
            ),
            source_episode_timestamp=entity.get("source_episode_timestamp"),
        )
        # Every caller holds the name it asks about (an unsure match, a name over a page it did not join).
        _mark_held_mention(clarifier, item)
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


def _is_fallback(candidate: dict) -> bool:
    """A fallback page (owner 2026-10-23, `project_birth.PROPOSED_KEY`): on disk, or created in this batch."""
    if candidate["source"] == "existing":
        return project_birth.proposed(candidate["data"].get("frontmatter"))
    return candidate["source"] == "created" and project_birth.proposed(candidate["data"])


def _candidate_types(candidate: dict) -> frozenset[str]:
    """The types a candidate is judged as: its own, and ``project`` for a fallback page — Stage 1 called its thing a
    project, so a later project mention of the same thing meets it at the judge instead of minting a second page."""
    own = _candidate_type(candidate)
    return frozenset((own, "project")) if _is_fallback(candidate) else frozenset((own,))


def _judge_type(candidate: dict, new_type: str) -> str:
    """The type the judge is shown for a candidate weighed against a ``new_type`` mention."""
    return new_type if new_type in _candidate_types(candidate) else _candidate_type(candidate)


def _candidate_description(candidate: dict) -> str:
    if candidate["source"] == "existing":
        return candidate["data"].get("body", "") or ""
    entity = candidate["data"].get("entity", {}) or {}
    description = _effective_summary(entity)
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


def _alias_context(candidate: dict) -> str:
    """``_alias_page_context`` for a page on disk or an in-cycle create (its other names, then what it says)."""
    if candidate["source"] == "existing":
        return _alias_page_context(candidate["data"])
    entity = candidate["data"].get("entity", {}) or {}
    name = str(entity.get("name") or "")
    others = [a for a in dict.fromkeys(str(x).strip() for x in entity.get("aliases") or []) if a and a != name]
    description = _candidate_description(candidate)
    parts = (["Other names on record: " + ", ".join(others)] if others else []) + ([description] if description else [])
    return "\n\n".join(parts)


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
    """Check if entity is linked to a high-confidence existing entity — explicitly.

    The owner's page never counts (G169): everything the person talks about is
    linked to them, so that link is no sign a first mention matters — the
    promotion rule would otherwise promote every name on its first mention.
    Explicit means the relationship's evidence is located in a person's own words
    (`promotion.person_said`): a link only the model's answer drew, or one it
    inferred, is the assistant's detail, not the person's."""
    for rel in relationships:
        if not promotion.person_said(rel):
            continue
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


def _spelling(name: str) -> str:
    """A name as it sounds when compared letter by letter: folded (case, accents), only letters and digits."""
    return "".join(ch for ch in text_fold.fold(name) if ch.isalnum())


def _edit_distance(a: str, b: str, limit: int) -> int:
    """Levenshtein distance, or ``limit + 1`` once it is over ``limit`` (names are short; no dependency)."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    row = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev, row[0] = row[0], i
        best = row[0]
        for j, cb in enumerate(b, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (ca != cb))
            best = min(best, row[j])
        if best > limit:
            return limit + 1
    return row[-1]


def close_spelling(a: str, b: str) -> bool:
    """Two names that are near spellings of one another — a dictated or misheard name ("Kovask" / "Kovasc"), not two
    words that merely share letters. Both at least 4 letters, the same first letter, different, and at most one edit
    apart (two when both have 6 or more letters). A spelling the direct match already takes (``fuzz.ratio > 85``) is
    not "close": it is the same name. Comparison only — a close spelling is a lead for the judge, never a decision."""
    x, y = _spelling_key(a), _spelling_key(b)
    if len(x) < 4 or len(y) < 4 or x == y or x[0] != y[0] or abs(len(x) - len(y)) > 2:
        return False
    limit = 2 if min(len(x), len(y)) >= 6 else 1
    if _edit_distance(x, y, limit) > limit:
        return False
    return fuzz.ratio(str(a or "").strip().lower(), str(b or "").strip().lower()) <= 85


@functools.lru_cache(maxsize=65536)
def _spelling_key(name: str) -> str:
    return _spelling(name)


#: The fuzzy join's threshold, as it always was: ``fuzz.ratio`` above this is "the same spelling" — when the two
#: names also pass :func:`distinct_names`.
FUZZY_SAME = 85


def _variant_words(x: str, y: str) -> bool:
    """Two words one spelling apart: one starts the other with 4 or more letters in common ("robot" / "robotic",
    "algo" / "algorithm"), or both have 5 or more letters and differ by one edit (two at 8 or more) — "andrej" /
    "andrew", or one is the other's plural ("hub" / "hubs", "lab" / "labs"). A short word must otherwise be the same
    word: "ebs" and "eks" are two things."""
    if x == y:
        return True
    if x.isdigit() or y.isdigit():
        return False
    short, long_ = sorted((x, y), key=len)
    if long_ in (short + "s", short + "es"):
        return True
    if len(short) >= 4 and long_.startswith(short):
        return True
    if min(len(x), len(y)) < 5 or x[0] != y[0]:
        return False
    limit = 2 if min(len(x), len(y)) >= 8 else 1
    return _edit_distance(x, y, limit) <= limit


@functools.lru_cache(maxsize=65536)
def distinct_names(a: str, b: str) -> bool:
    """Two names a ``fuzz.ratio > 85`` would join that name two different things (2026-10-27, the hook-note trace):
    a word on one side with no spelling of it on the other — "<agency> <city>" / "<city>", "Acme Chrome Extension" /
    "Chrome Extension", "Amazon EBS" / "Amazon EKS", "Best-first search" / "Breadth-first search" — or a different
    number ("Computer Programming 2" / "… 1", "Opus 5.5" / "Opus 4.6"). Spacing, case, accents and punctuation never
    count ("OpenAI" / "Open AI"), and a word spelt two ways is one word (:func:`_variant_words`). The fuzzy join
    used to take every such pair, so a city's page collected a company's claims and an edge landed on the wrong
    page; such a pair is now no fuzzy match: an entity goes to the judge with the pages it shares a word with, and
    an edge endpoint resolves to nothing rather than to the wrong page."""
    if _spelling_key(a) == _spelling_key(b):
        return False
    wa, wb = text_fold.words(a), text_fold.words(b)
    if sorted(w for w in wa if w.isdigit()) != sorted(w for w in wb if w.isdigit()):
        return True
    only_a = [w for w in wa if w not in wb and not w.isdigit()]
    only_b = [w for w in wb if w not in wa and not w.isdigit()]
    left_a: list[str] = []
    for word in only_a:
        partner = next((w for w in only_b if _variant_words(word, w)), None)
        if partner is None:
            left_a.append(word)
        else:
            only_b.remove(partner)
    left_b = only_b
    if left_a and left_b:
        return True   # a word swapped for another: "best-first" / "breadth-first", "EBS" / "EKS"
    # One name only adds words. A word hyphen-joined to a word both names share is part of that word's spelling
    # ("browser-use harness" / "browser-harness", "MPI-parallel solver" / "parallel solver"), not another name; a
    # separate word ("<agency> <city>") still is.
    extra, name, other = (left_a, a, wb) if left_a else (left_b, b, wa)
    return any(not _compound_part(w, name, other) for w in extra)


_COMPOUND = re.compile(r"[^\W_]+(?:-[^\W_]+)+", re.UNICODE)


def _compound_part(word: str, name: str, other_words: list[str]) -> bool:
    """Is ``word`` one part of a hyphenated compound in ``name`` whose other part is a word of the other name (or a
    spelling of one)?"""
    for compound in _COMPOUND.findall(name or ""):
        parts = text_fold.words(compound)
        if word in parts and any(p != word and any(_variant_words(p, o) for o in other_words) for p in parts):
            return True
    return False


def fuzzy_same(a: str, b: str) -> bool:
    """The fuzzy join, as one rule: ``fuzz.ratio > 85`` on the lower-cased names, unless they are
    :func:`distinct_names`."""
    a, b = str(a or "").strip().lower(), str(b or "").strip().lower()
    return fuzz.ratio(a, b) > FUZZY_SAME and not distinct_names(a, b)


def _spelling_lead(new_entity: dict, page_name: str, page_aliases) -> dict:
    """What ties a new name to a page beyond its own name (2026-10-27): ``shared_alias`` — a name the new extraction
    says it also goes by is the page's name or one of its aliases; ``close`` — the new name is a close spelling of the
    page's name or one of its aliases (:func:`close_spelling`); ``together`` — the page's name is one the same
    conversation's extraction tied to the new name by an alias (``NAMED_WITH``). Empty when none."""
    new_name = str(new_entity.get("name") or "")
    new_key = person_leads.handle_key(new_name)
    # A reference or a pronoun ("she", "the girlfriend") is no name, on either side (`alias_policy`).
    own = {person_leads.handle_key(a): str(a) for a in new_entity.get("aliases") or [] if str(a).strip()
           and person_leads.handle_key(a) != new_key and not alias_policy.is_reference(a)}
    together = {person_leads.handle_key(n) for n in new_entity.get(NAMED_WITH) or [] if str(n).strip()}
    lead: dict = {}
    if together and person_leads.handle_key(page_name) in together:
        lead["together"] = str(page_name)
    for text in (page_name, *(page_aliases or ())):
        text = str(text or "")
        if not text.strip() or alias_policy.is_reference(text):
            continue
        if "shared_alias" not in lead and own and person_leads.handle_key(text) in own:
            lead["shared_alias"] = own[person_leads.handle_key(text)]
        if "close" not in lead and close_spelling(new_name, text):
            lead["close"] = text
    return lead


def _lead_note(new_name: str, candidate: dict) -> str:
    """The judge's note for a candidate a shared alias or a close spelling brought (``_spelling_lead``)."""
    parts = []
    if candidate.get("together"):
        parts.append(f'B and "{candidate["together"]}" were named together in one conversation, and its extraction '
                     "tied them by an alias.")
    if candidate.get("shared_name"):
        parts.append(f'Several people in this memory are called "{candidate["shared_name"]}" (a name or a nickname '
                     "they share), so the name alone does not tell which one B is.")
    if candidate.get("shared_alias"):
        parts.append(f'B is also called "{candidate["shared_alias"]}", a name A goes by.')
    if candidate.get("close"):
        parts.append(f'"{new_name}" is a close spelling of "{candidate["close"]}", a name A goes by; a dictated or '
                     "misheard name is often written differently.")
    if not parts:
        return ""
    return ("Note: " + " ".join(parts) + " That is a lead, not proof: nicknames and similar names are shared by "
            "different people and things. Say SAME only when B's description fits A's; say DIFFERENT when they point "
            "at something else; say UNSURE when there is too little to tell.\n")


def _with_lead(candidate: dict, new_entity: dict, lead: dict) -> dict:
    if lead:
        candidate.update(lead)
        if not candidate.get("alias") or lead.get("together"):
            candidate["note"] = _lead_note(str(new_entity.get("name") or ""), candidate)
    return candidate


def _never_cleared(judged: list[tuple[dict, str]]) -> list[tuple[dict, str]]:
    """A page whose name the new name is a close spelling of AND that shares an alias with it is never cleared by the
    judge alone (2026-10-27): "different" reads as "unsure", so the name is held and the person is asked — it joins
    only on a "same", and never becomes a silent page of its own."""
    return [(c, "unsure" if (d == "different" or entity_relations.relation_of(d)) and c.get("close")
             and c.get("shared_alias") else d)
            for c, d in judged]


#: The judge's own short system message (perf report 2026-10-24, item 3): with none, a plan engine would send its own
#: default system prompt, ~2.3k tokens describing a coding agent, on every one of a night's judge calls.
_DISAMBIG_SYSTEM = ("You judge whether entries in one person's knowledge graph name the same real-world thing, from "
                    "the entries you are given, and answer in JSON.")

_DISAMBIG_PROMPT = ("""You are deciding whether two entity entries from a personal knowledge graph refer to the same real-world thing.

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
- Say RELATED when they are two different things and one stands to the other in one of these ways, and name it as "relation" (B is the new entry, A the existing one):
""" + entity_relations.PROMPT_LINES + """- A part is never the same as its whole, a product never the same as its maker, an alternative never the same as the original, one version never the same as the line it belongs to: those are RELATED, never SAME and never UNSURE. Two people are never RELATED: say DIFFERENT or UNSURE.
- Say DIFFERENT when the descriptions place the entities in clearly different contexts (different roles, different companies, different cities) or when one description is empty and the names don't obviously line up.
- Say UNSURE only when A and B could really be one thing under two names but the descriptions are too weak to merge safely. If you are hesitating between SAME and DIFFERENT, return UNSURE.
- If the type fields disagree (e.g. person vs project), they are not the same.

Respond with JSON only ("relation" only with "related"):
{{"decision": "same" | "different" | "unsure" | "related", "relation": "part_of" | "has_part" | "made_by" | "makes" | "alternative_to" | "version_of" | "has_version", "reason": "one short sentence"}}
""")

_TYPE_GUIDELINE = "- If the type fields disagree (e.g. person vs project), they are not the same."
#: G227's same-title judge: the types are a weak hint there, the descriptions decide (`_SAME_TITLE_NOTE`).
_TYPE_GUIDELINE_SAME_TITLE = ("- The type fields may disagree because one was recorded wrongly; let the descriptions "
                              "decide.")
assert _TYPE_GUIDELINE in _DISAMBIG_PROMPT

# An alias hit is a lead, never a decision (2026-10-08): acronyms, short forms
# and first names are shared by different things, so the judge is told the
# page recorded the name and asked to decide on the context.
_ALIAS_NOTE = """
Entity A's page already lists "{new_name}" among the other names it goes by (its aliases), so the names need not share a word. That is a lead, not proof: acronyms, short forms and first names are often shared by different things. Say SAME only when B's description and connections fit A's; say DIFFERENT when they point at something else; say UNSURE when there is too little to tell.
"""

# Owner 2026-10-23 (`_settle_unborn`): something the person works on but never called a project is often named
# differently in each conversation — the whole, a part, a stage of it — so the judge weighs those names together even
# when they share no word, and is told that this is no lead either way.
_UNSHARED_NOTE = ("Note: these names share no word. That is no lead either way: a person often names one endeavour "
                  "differently in different conversations (the whole, a part of it, a stage of it). Say SAME only "
                  "when both descriptions clearly point at the same endeavour; say DIFFERENT when they describe two; "
                  "say UNSURE when there is too little to tell.\n")


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
    note: str = "",
    types_may_differ: bool = False,
) -> str:
    """One LLM call: same, different, or unsure.

    ``note``: a candidate's own note, said where the alias note goes (``_UNSHARED_NOTE``).

    ``recorded_alias``: the page already lists ``new_name`` among its aliases —
    the prompt says so, and that an alias is a lead, not proof
    (``_ALIAS_NOTE``); ``new_connections`` is what the name was connected to in
    the batch. Without them the prompt is the plain one, byte for byte."""
    from api.services.claims import strip_claims_block

    if new_type and existing_type and new_type.lower() != existing_type.lower() and not types_may_differ:
        return "different"
    template = _DISAMBIG_PROMPT.replace(_TYPE_GUIDELINE, _TYPE_GUIDELINE_SAME_TITLE) if types_may_differ \
        else _DISAMBIG_PROMPT
    prompt = template.format(
        existing_name=existing_name,
        existing_type=existing_type or "unknown",
        existing_body=strip_claims_block(existing_body)[:2000] or "(empty)",
        new_name=new_name,
        new_type=new_type or "unknown",
        new_description=(new_description or "")[:1500] or "(empty)",
        alias_note=(_ALIAS_NOTE.format(new_name=new_name) + note if recorded_alias
                    else ("\n" + note if note else "")),
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
            messages=[{"role": "system", "content": _DISAMBIG_SYSTEM}, {"role": "user", "content": prompt}],
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
        related = entity_relations.parse(decision, parsed.get("relation"))
        if related is not None:
            return _for_type(related, new_type)
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


#: How many of one name's candidates one judge call weighs (2026-10-20). A name that shares a common word ("model",
#: "google", a first name) with many same-type pages used to cost one call per page, ~85 % of a night's calls ending
#: in "different"; now its candidates go to the judge together, in their judging order, at most this many a call.
#: A lone candidate keeps the one-pair prompt (`_DISAMBIG_PROMPT`) byte for byte.
JUDGE_BATCH = 6

_DISAMBIG_BATCH_PROMPT = ("""You are deciding whether a new entity entry from a personal knowledge graph refers to the same real-world thing as any of the existing entries listed below.

Each existing entry has a name that overlaps the new one (for example a bare first name and that same first name with a surname), or lists the new name among its other names, but was built from different conversations, so you need to look at the descriptions and decide, for each existing entry on its own, whether merging the new entry into it would be correct.

NEW ENTRY (B)
Name: {new_name}
Type: {new_type}
Description:
{new_description}{new_connections}

EXISTING ENTRIES (each one is an A, judged on its own against B)
{entries}
Guidelines:
- Say SAME only when the descriptions clearly point at the same real person, project, company, concept, tool, deadline, skill, or location. Shared last names alone are not enough. Shared first names alone are definitely not enough.
- Say SAME when one description is a vague subset of the other and nothing in either description contradicts the merge.
- Say RELATED when they are two different things and one stands to the other in one of these ways, and name it as "relation" (B is the new entry, A the existing one):
""" + entity_relations.PROMPT_LINES + """- A part is never the same as its whole, a product never the same as its maker, an alternative never the same as the original, one version never the same as the line it belongs to: those are RELATED, never SAME and never UNSURE. Two people are never RELATED: say DIFFERENT or UNSURE.
- Say DIFFERENT when the descriptions place the entities in clearly different contexts (different roles, different companies, different cities) or when one description is empty and the names don't obviously line up.
- Say UNSURE only when A and B could really be one thing under two names but the descriptions are too weak to merge safely. If you are hesitating between SAME and DIFFERENT, return UNSURE.
- If the type fields disagree (e.g. person vs project), they are not the same.

Respond with JSON only, one decision for every existing entry, in the order given ("relation" only with "related"; the new entry is B, each existing entry is A):
{{"decisions": [{{"entry": 1, "decision": "same" | "different" | "unsure" | "related", "relation": "part_of" | "has_part" | "made_by" | "makes" | "alternative_to" | "version_of" | "has_version", "reason": "one short sentence"}}]}}
""")

_BATCH_ENTRY = """[{index}] Name: {name}
Type: {type}
{alias_note}Description:
{body}
"""

#: `_ALIAS_NOTE` for one entry of a batch.
_BATCH_ALIAS_NOTE = ('Note: this entry already lists "{new_name}" among the other names it goes by (its aliases), so '
                     "the names need not share a word. That is a lead, not proof: acronyms, short forms and first "
                     "names are often shared by different things. Say SAME only when B's description and connections "
                     "fit this entry's; say DIFFERENT when they point at something else; say UNSURE when there is too "
                     "little to tell.\n")


def _for_type(decision: str, new_type: str) -> str:
    """A relation is between things: for a person it reads as ``different`` (the judge said two people)."""
    if entity_relations.relation_of(decision) is not None and (new_type or "").lower() == "person":
        return "different"
    return decision


def _batch_decisions(parsed: dict, count: int, new_type: str = "") -> list[str]:
    """One decision per entry from a batch answer, lined up by `json_parse.numbered_rows` (the numbers exactly 1..n,
    or no numbers and exactly n rows). An answer that does not line up is ``unsure`` for every entry, and a row whose
    decision is not one of the four words is ``unsure`` — the reading an unreadable one-pair answer gets; never a
    decision read against the wrong candidate. ``related`` reads as ``related:<relation>`` (`entity_relations`)."""
    rows = json_parse.numbered_rows(parsed.get("decisions") if isinstance(parsed, dict) else None, count, "entry")
    if rows is None:
        return ["unsure"] * count
    words = {"same", "different", "unsure"}
    out: list[str] = []
    for row in rows:
        decision = str(row.get("decision", "")).strip().lower()
        related = entity_relations.parse(decision, row.get("relation"))
        out.append(decision if decision in words else _for_type(related, new_type) if related else "unsure")
    return out


async def _llm_judge_batch(
    new_name: str,
    new_type: str,
    new_description: str,
    entries: list[dict],
    settings: Settings,
    *,
    new_connections: str = "",
) -> list[str]:
    """One LLM call over several existing entries: ``same``, ``different`` or ``unsure`` for each, in order.

    ``entries``: ``{name, type, body, alias}`` per candidate, the body already chosen as the one-pair call would
    (`_alias_page_context` for an alias candidate). Each entry is cut as the one-pair prompt cuts it and an alias
    entry carries the alias note; a type that disagrees is ``different`` without asking, as there."""
    from api.services.claims import strip_claims_block

    decisions: list[str | None] = [
        "different" if new_type and e["type"] and new_type.lower() != str(e["type"]).lower() else None
        for e in entries]
    asked = [i for i, d in enumerate(decisions) if d is None]
    if not asked:
        return [str(d) for d in decisions]
    blocks = []
    for number, i in enumerate(asked, start=1):
        entry = entries[i]
        blocks.append(_BATCH_ENTRY.format(
            index=number, name=entry["name"], type=entry["type"] or "unknown",
            alias_note=(_BATCH_ALIAS_NOTE.format(new_name=new_name) + str(entry.get("note") or "")
                        if entry.get("alias") else str(entry.get("note") or "")),
            body=strip_claims_block(entry["body"] or "")[:2000] or "(empty)"))
    prompt = _DISAMBIG_BATCH_PROMPT.format(
        new_name=new_name,
        new_type=new_type or "unknown",
        new_description=(new_description or "")[:1500] or "(empty)",
        new_connections=f"\nConnections in its conversations:\n{new_connections[:800]}" if new_connections else "",
        entries="\n".join(blocks),
    )
    disambig_model = (
        getattr(settings, "litellm_disambiguation_model", "") or settings.litellm_model
    )
    try:
        from api.services.providers import resolve_llm_fn

        llm_fn = resolve_llm_fn(
            settings, model=disambig_model, completion=litellm.acompletion, stage="disambiguation"
        )
        response = await llm_fn(
            messages=[{"role": "system", "content": _DISAMBIG_SYSTEM}, {"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            extra_body={"reasoning": {"enabled": False}},  # as the one-pair call: a judgment, no chain of thought
            timeout=120,
        )
        answered = _batch_decisions(json_parse.parse_json_object(response.choices[0].message.content or "{}"),
                                    len(asked), new_type)
    except engine_errors.EngineError:
        raise  # G74(a): an engine failure is never a model's uncertainty
    except Exception as e:
        logger.debug(f"Disambiguation judge failed for {new_name} against {len(asked)} pages: {e}")
        answered = ["unsure"] * len(asked)
    for i, decision in zip(asked, answered):
        decisions[i] = decision
    return [str(d) for d in decisions]


#: More pages than this answering to one name or nickname ("babe", "bro", initials) make it common, not a lead
#: (owner 2026-10-27, "many people sharing common nicknames"): its holders are not each judged as aliases. What is
#: more specific still points (the mention's own aliases, a name said with it, a close spelling, the page titled exactly
#: by that name), and a mention that meets none of them goes on by the usual rule.
MAX_NAME_HOLDERS = 5


class NameIndex:
    """The bank's names and aliases, indexed once per Stage 2 run (owner 2026-10-27: "should work at scale with many many
    nicknames"): ``by_key`` — a name's or alias's key → ``(text, page)`` for every page answering to it; ``buckets`` —
    ``(first letter, length)`` of its folded spelling → ``(text, page)``, so a close spelling is looked up among the few
    names of about its length, never by a scan over every alias of every page. References and pronouns are not indexed
    (`alias_policy`)."""

    def __init__(self, existing_by_name: dict[str, dict]):
        self.by_key: dict[str, list[tuple[str, dict]]] = {}
        self.buckets: dict[tuple[str, int], list[tuple[str, dict]]] = {}
        for page in existing_by_name.values():
            texts = [_candidate_display_name({"source": "existing", "id": page["id"], "data": page}),
                     *_page_aliases(page)]
            seen: set[str] = set()
            for text in texts:
                key = person_leads.handle_key(text)
                if not key or key in seen or alias_policy.is_reference(text):
                    continue
                seen.add(key)
                self.by_key.setdefault(key, []).append((text, page))
                spelled = _spelling_key(text)
                if len(spelled) >= 4:
                    self.buckets.setdefault((spelled[0], len(spelled)), []).append((text, page))

    def answering(self, text: str) -> list[tuple[str, dict]]:
        return self.by_key.get(person_leads.handle_key(text), [])

    def close_to(self, name: str) -> list[tuple[str, dict]]:
        spelled = _spelling_key(name)
        if len(spelled) < 4:
            return []
        return [(text, page) for n in range(len(spelled) - 2, len(spelled) + 3)
                for text, page in self.buckets.get((spelled[0], n), ()) if close_spelling(name, text)]


def _existing_llm_candidates(
    new_entity: dict, existing_by_name: dict[str, dict], aliases: dict[str, list[dict]] | None = None,
    rejected: frozenset | set = frozenset(), index: "NameIndex | None" = None,
) -> list[dict]:
    """The pages on disk the judge weighs ``new_entity`` against, in judging order.

    First the same-type pages that list the name among their ``aliases`` (marked
    ``alias``; they need share no word with it — an acronym, a short form, a
    nickname), then the same-type pages tied to it by a lead (``_spelling_lead``,
    2026-10-27: a shared alias, a close spelling, named together in one
    conversation; for a person, a page whose name it is but that several pages
    answer to, or one titled by a nickname), then the same-type pages that share a
    content token with the name; none already a direct match. Leads come from
    ``index`` (built once per run, `NameIndex`). A function of the extraction and
    the bank alone — nothing the per-name loop decides changes it — which is what
    lets ``resolve`` judge these ahead of the loop (``_Lookahead``)."""
    new_name = new_entity.get("name") or ""
    new_type = (new_entity.get("type") or "concept").lower()
    candidates: list[dict] = []
    holders = (aliases or {}).get(person_leads.handle_key(new_name), ()) if new_name else ()
    for page in holders if len(holders) <= MAX_NAME_HOLDERS else ():   # a common nickname is no lead
        candidate = {"source": "existing", "id": page["id"], "data": page, "alias": True}
        if new_type in _candidate_types(candidate):
            candidates.append(_with_lead(candidate, new_entity, _spelling_lead(
                new_entity, _candidate_display_name(candidate), _page_aliases(page))))
    if not new_name:
        return candidates
    if index is None:
        index = NameIndex(existing_by_name)
    new_name_lower = new_name.lower()
    new_key = person_leads.handle_key(new_name)
    tokens, person = bool(_name_tokens(new_name)), _is_person(new_entity)
    held = {candidate["id"] for candidate in candidates}

    # The pages a lead points at, looked up in the index — never a scan over every alias of every page.
    pointed: dict[str, dict] = {}
    for alias in new_entity.get("aliases") or []:
        if str(alias).strip() and person_leads.handle_key(alias) != new_key and not alias_policy.is_reference(alias):
            answering = index.answering(alias)
            for _text, page in answering if len(answering) <= MAX_NAME_HOLDERS else ():
                pointed.setdefault(page["id"], page)
    for other in new_entity.get(NAMED_WITH) or []:
        for _text, page in index.answering(other):
            pointed.setdefault(page["id"], page)
    for _text, page in index.close_to(new_name):
        pointed.setdefault(page["id"], page)
    if person:
        for name_lower, page in existing_by_name.items():
            # A person name the direct match would take is the judge's when it is not one spelling, or when several
            # pages answer to it (`_shared_name`).
            if fuzz.ratio(new_name_lower, name_lower) > 85 and (
                    _near_person(new_name, name_lower) or _shared_name(new_name, page, aliases)):
                pointed.setdefault(page["id"], page)

    shared: list[dict] = []
    for page_id, page in pointed.items():
        if page_id in held:
            continue
        candidate = {"source": "existing", "id": page_id, "data": page}
        if new_type not in _candidate_types(candidate):
            continue
        display = _candidate_display_name(candidate)
        lead = _spelling_lead(new_entity, display, _page_aliases(page))
        if person and fuzz.ratio(new_name_lower, display.lower()) > 85:
            if _near_person(new_name, display):
                lead.setdefault("close", display)
            elif _shared_name(new_name, page, aliases):
                lead.setdefault("shared_name", display)
        if not lead:
            continue
        held.add(page_id)
        if not _rejected_pair(rejected, new_name, page_id):
            shared.append(_with_lead(candidate, new_entity, lead))

    token_sharing: list[dict] = []
    if tokens:
        for existing_name_lower, existing_data in existing_by_name.items():
            if existing_data["id"] in held:
                continue
            candidate = {"source": "existing", "id": existing_data["id"], "data": existing_data}
            if new_type not in _candidate_types(candidate):
                continue
            if not _share_content_token(new_name, _candidate_display_name(candidate)):
                continue
            if fuzz.ratio(new_name_lower, existing_name_lower) > 85 and (
                    person or not distinct_names(new_name_lower, existing_name_lower)):
                continue   # the direct match's (a distinct name sharing a word is judged, 2026-10-27)
            token_sharing.append(candidate)
    return candidates + shared + token_sharing


def _created_llm_candidates(new_entity: dict, created_by_id: dict[str, dict],
                            rejected: frozenset | set = frozenset()) -> list[dict]:
    """The in-cycle creates the judge weighs ``new_entity`` against — what the loop has decided so far.

    The same order as on disk (G209): first the same-type creates whose extractions list the name among their aliases
    (marked ``alias``, judged with the alias note; they need share no word with it), then the token-sharing ones. An
    alias a create carries used to be invisible here, so a handle and the full name that listed it, born in one run,
    became two pages."""
    new_name = new_entity.get("name") or ""
    if not new_name:
        return []
    new_name_lower = new_name.lower()
    new_type = (new_entity.get("type") or "concept").lower()
    new_key = person_leads.handle_key(new_name)
    candidates: list[dict] = []
    for candidate_id, create_change in created_by_id.items():
        listed = (create_change.get("entity") or {}).get("aliases") or []
        candidate = {"source": "created", "id": candidate_id, "data": create_change, "alias": True}
        if (new_type in _candidate_types(candidate)
                and any(person_leads.handle_key(a) == new_key for a in listed if str(a).strip())):
            candidates.append(_with_lead(candidate, new_entity, _spelling_lead(
                new_entity, _candidate_display_name(candidate), listed)))
    tokens, person = bool(_name_tokens(new_name)), _is_person(new_entity)
    held = {candidate["id"] for candidate in candidates}
    shared: list[dict] = []
    token_sharing: list[dict] = []
    for candidate_id, create_change in created_by_id.items():
        if candidate_id in held:
            continue
        candidate = {"source": "created", "id": candidate_id, "data": create_change}
        existing_display = _candidate_display_name(candidate)
        if new_type not in _candidate_types(candidate):
            continue
        # The same leads as on disk (`_existing_llm_candidates`): a shared alias or a close spelling.
        lead = _spelling_lead(new_entity, existing_display, (create_change.get("entity") or {}).get("aliases"))
        if fuzz.ratio(new_name_lower, existing_display.lower()) > 85:
            if person and _near_person(new_name, existing_display):
                lead.setdefault("close", existing_display)
            elif person or not distinct_names(new_name_lower, existing_display.lower()):
                continue   # the direct match's; a distinct name sharing a word is judged (2026-10-27)
        if lead:
            if not _rejected_pair(rejected, new_name, candidate_id):
                shared.append(_with_lead(candidate, new_entity, lead))
        elif tokens and _share_content_token(new_name, existing_display):
            token_sharing.append(candidate)
    return candidates + shared + token_sharing


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
    """Judge ``candidates`` in order, up to ``JUDGE_BATCH`` of them a call, stopping after the first call (or cached
    decision) that says ``same``.

    Returns ``(candidate, decision)`` per candidate judged, in order — always a prefix of ``candidates``, which may
    run past the first ``same`` within its call (`_pick_match` takes the first). ``gate`` bounds the calls in flight
    across every name ``resolve`` is judging; ``stop`` is polled before each call so a cancel or a plan limit starts
    nothing new. A candidate an alias brought is judged with the alias note, the page's context first
    (``_alias_page_context``) and the name's ``connections`` in the batch. A call over one candidate is the one-pair
    judge (`_llm_judge_same_entity`), over several `_llm_judge_batch`."""
    new_name = new_entity.get("name") or ""
    new_name_lower = new_name.lower()
    new_type = (new_entity.get("type") or "concept").lower()
    # What the extraction said about the name: Stage 1 fills `summary`; `description` is a legacy field it almost
    # never fills (1 of 79 entities on the synthetic night, 2026-10-20), so the judge used to read "(empty)" for B.
    new_description = _effective_summary(new_entity)
    judged: list[tuple[dict, str]] = []
    index = 0
    while index < len(candidates):
        cached = cache.get((new_name_lower, candidates[index]["id"]))
        if cached is not None:
            judged.append((candidates[index], cached))
            index += 1
            if cached == "same":
                break
            continue
        chunk: list[dict] = []
        while (index + len(chunk) < len(candidates) and len(chunk) < JUDGE_BATCH
               and (new_name_lower, candidates[index + len(chunk)]["id"]) not in cache):
            chunk.append(candidates[index + len(chunk)])
        if stop is not None and stop():
            break

        async def ask(chunk=chunk) -> list[str]:
            if len(chunk) == 1:
                candidate = chunk[0]
                kwargs = dict(
                    new_name=new_name,
                    new_type=new_type,
                    new_description=new_description,
                    existing_name=_candidate_display_name(candidate),
                    existing_type=_judge_type(candidate, new_type),
                    existing_body=_candidate_description(candidate),
                    settings=settings,
                )
                if candidate.get("alias"):
                    kwargs.update(existing_body=_alias_context(candidate), recorded_alias=True,
                                  new_connections=connections)
                    if candidate.get("note"):
                        kwargs.update(note=candidate["note"])
                elif candidate.get("note"):
                    kwargs.update(note=candidate["note"])
                return [await _llm_judge_same_entity(**kwargs)]
            entries = [{"name": _candidate_display_name(c), "type": _judge_type(c, new_type),
                        "alias": bool(c.get("alias")), **({"note": c["note"]} if c.get("note") else {}),
                        "body": _alias_context(c) if c.get("alias") else _candidate_description(c)}
                       for c in chunk]
            return await _llm_judge_batch(
                new_name, new_type, new_description, entries, settings,
                new_connections=connections if any(c.get("alias") for c in chunk) else "")

        if gate is None:
            decisions = await ask()
        else:
            async with gate:
                if stop is not None and stop():  # stopped while waiting for a slot
                    break
                decisions = await ask()
        for candidate, decision in zip(chunk, decisions):
            cache[(new_name_lower, candidate["id"])] = decision
            judged.append((candidate, decision))
        index += len(chunk)
        if "same" in decisions:
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
    rejected: frozenset | set = frozenset(),
    index: "NameIndex | None" = None,
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
            new_entity, _existing_llm_candidates(new_entity, existing_by_name, aliases, rejected, index), cache,
            settings,
            gate=gate, connections=connections)
    else:
        judged = list(prejudged)
    if not any(decision == "same" for _, decision in judged):
        judged += await _judge_candidates(
            new_entity, _created_llm_candidates(new_entity, created_by_id, rejected), cache, settings, gate=gate,
            connections=connections)
    return _pick_match(new_name, _never_cleared(judged))


#: How many names per concurrent slot ``_Lookahead`` takes ahead of the loop.
#: A name's own calls stay sequential, so while the loop waits on a name with a
#: long candidate list the other slots keep working on names further ahead; the
#: window bounds what a cancel can waste (judgments taken but never used).
LOOKAHEAD_NAMES_PER_SLOT = 4


def _lookahead_plan(
    ordered_entities: list[tuple[str, dict]], existing_by_name: dict[str, dict],
    aliases: dict[str, list[dict]] | None = None, rejected: frozenset | set = frozenset(),
    index: "NameIndex | None" = None,
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
        if (_find_direct_candidate_match(entity, existing_by_name, {}, aliases) is None
                and not any(name_lower == other or fuzz.ratio(name_lower, other) > 85 for other in earlier)):
            candidates = _existing_llm_candidates(entity, existing_by_name, aliases, rejected, index)
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
