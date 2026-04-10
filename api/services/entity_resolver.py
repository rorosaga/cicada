"""Stage 2: Entity Resolution & Deduplication."""

import asyncio
import json
from collections import Counter

import litellm
from loguru import logger
from thefuzz import fuzz

from api.config import Settings
from api.services.clarification_manager import (
    CONFIDENCE_THRESHOLD,
    ClarificationManager,
)
from api.services.id_utils import sanitize_id
from api.services.leann_indexer import LeannIndexer, PendingEntity


async def resolve(
    extracted: list[dict], existing: list[dict], settings: Settings
) -> dict:
    """Resolve extracted entities against existing graph. Enforce promotion model.

    Returns dict with 'changes' (entity updates) and 'relationships' (resolved edges).
    """
    disambig_model = (
        getattr(settings, "litellm_disambiguation_model", "") or settings.litellm_model
    )
    logger.info(f"Stage 2 disambiguation model: {disambig_model}")

    existing_by_name: dict[str, dict] = {}
    for e in existing:
        name = e["frontmatter"].get("name", e["id"].replace("-", " ").title())
        existing_by_name[name.lower()] = e

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

    # Deduplicate entities by exact normalized name (keep the strongest extraction).
    best_by_name: dict[str, dict] = {}
    for entity in all_entities:
        name_lower = entity["name"].lower()
        current = best_by_name.get(name_lower)
        if current is None or entity.get("confidence", 0) > current.get("confidence", 0):
            best_by_name[name_lower] = entity

    # Pending store — sub-threshold entities from previous cycles
    try:
        indexer = LeannIndexer(settings.memory_path)
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

    # Process more specific names first so "Rodrigo Sagastegui" becomes the
    # canonical in-cycle entity and "Rodrigo" can merge into it rather than
    # the other way around.
    ordered_entities = sorted(
        best_by_name.items(),
        key=lambda item: _specificity_key(item[1]),
        reverse=True,
    )

    for name_lower, entity in ordered_entities:
        name = entity["name"]
        match = _find_direct_candidate_match(
            new_entity=entity,
            existing_by_name=existing_by_name,
            created_by_id=resolved_creates,
        )
        if match is None:
            match = await _find_llm_candidate_match(
                new_entity=entity,
                existing_by_name=existing_by_name,
                created_by_id=resolved_creates,
                cache=llm_match_cache,
                settings=settings,
            )

        if match is not None and match["decision"] == "same":
            candidate = match["candidate"]
            name_to_id[name_lower] = candidate["id"]
            try:
                clarifier.check_organic_resolution(
                    entity_name=name,
                    confidence=float(entity.get("confidence", 0.0) or 0.0),
                )
            except Exception as e:
                logger.debug(f"Organic clarification check failed for {name}: {e}")

            if candidate["source"] == "existing":
                _merge_into_update(
                    updates_by_id=resolved_updates,
                    existing_entity=candidate["data"],
                    incoming=entity,
                )
            else:
                create_change = resolved_creates[candidate["id"]]
                create_change["entity"] = _merge_entity_payload(
                    create_change.get("entity", {}) or {},
                    entity,
                )
                _append_change_source(create_change, entity)
            continue

        ambiguous_match = match is not None and match["decision"] == "unsure"

        # New entity — check promotion threshold
        episodes_seen = len(episode_mentions.get(name_lower, set()))
        linked_to_existing = _is_linked_to_existing(name, all_relationships, existing_by_name)

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
            _create_duplicate_clarification(
                clarifier=clarifier,
                entity=entity,
                candidate=match["candidate"],
            )

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
                "trigger": "sleep/promotion",
            }
            try:
                clarifier.check_organic_resolution(
                    entity_name=name,
                    confidence=float(entity.get("confidence", 0.0) or 0.0),
                )
            except Exception as e:
                logger.debug(
                    f"Organic clarification check failed for {name}: {e}"
                )
            if indexer is not None and pending_entry is not None:
                try:
                    indexer.promote_from_pending(name)
                except Exception as e:
                    logger.debug(
                        f"Failed to clear pending entry for {name}: {e}"
                    )
        else:
            confidence = float(entity.get("confidence", 0.3) or 0.3)
            if confidence < CONFIDENCE_THRESHOLD and not ambiguous_match:
                try:
                    clarifier.create(
                        entity_name=name,
                        source_episode=entity.get("source_episode", ""),
                        uncertainty_type=_infer_uncertainty_type(entity),
                        suggested_classification=(
                            f"{entity.get('type', 'concept')} — "
                            f"{(entity.get('description') or '')[:120]}"
                        ),
                        suggested_confidence=confidence,
                        source_context=entity.get("description", "") or "",
                        source_episode_timestamp=entity.get("source_episode_timestamp"),
                    )
                except Exception as e:
                    logger.debug(
                        f"Failed to create clarification for {name}: {e}"
                    )

            if indexer is not None:
                try:
                    indexer.index_pending_entity(PendingEntity(
                        name=name,
                        type=entity.get("type", "concept"),
                        description=entity.get("description", "") or "",
                        source_episode=entity.get("source_episode", ""),
                        confidence=confidence,
                        tags=list(entity.get("tags", []) or []),
                        history_entries=list(entity.get("history_entries", []) or []),
                    ))
                except Exception as e:
                    logger.debug(f"Failed to store pending entity {name}: {e}")

    resolved = list(resolved_updates.values()) + list(resolved_creates.values())

    # Resolve relationships — only keep edges where both endpoints survived promotion
    resolved_edges: list[dict] = []
    seen_edges: set[tuple[str, str, str]] = set()
    for rel in all_relationships:
        source_name = rel.get("source", "").lower()
        target_name = rel.get("target", "").lower()
        label = rel.get("label", "related to")

        source_id = name_to_id.get(source_name)
        target_id = name_to_id.get(target_name)

        # Also try fuzzy match for relationship endpoints
        if not source_id:
            for known_name, known_id in name_to_id.items():
                if fuzz.ratio(source_name, known_name) > 85:
                    source_id = known_id
                    break
        if not target_id:
            for known_name, known_id in name_to_id.items():
                if fuzz.ratio(target_name, known_name) > 85:
                    target_id = known_id
                    break

        if source_id and target_id and source_id != target_id:
            key = (source_id, target_id, label.lower())
            if key not in seen_edges:
                seen_edges.add(key)
                resolved_edges.append({
                    "source": source_id,
                    "target": target_id,
                    "label": label,
                })

    # Rebuild the pending LEANN index once, after all sub-threshold entities
    # have been appended to the store. Rebuilding per-entity is O(N^2) and
    # sends every passage back to OpenAI on every call.
    if indexer is not None:
        try:
            indexer.rebuild_pending_index()
        except Exception as e:
            logger.debug(f"Pending index rebuild failed: {e}")

    return {
        "changes": resolved,
        "relationships": resolved_edges,
        "episode_cooccurrences": episode_cooccurrences,
    }


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
    merged["confidence"] = max(
        float(base.get("confidence", 0.0) or 0.0),
        float(incoming.get("confidence", 0.0) or 0.0),
    )

    base_desc = (base.get("description") or "").strip()
    incoming_desc = (incoming.get("description") or "").strip()
    if len(incoming_desc) > len(base_desc):
        merged["description"] = incoming_desc
    else:
        merged["description"] = base_desc

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
    return merged


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


def _latest_timestamp(left: str | None, right: str | None) -> str | None:
    candidates = [c for c in (left, right) if c]
    if not candidates:
        return None
    return max(candidates)


def _is_linked_to_existing(
    name: str, relationships: list[dict], existing: dict[str, dict]
) -> bool:
    """Check if entity is linked to a high-confidence existing entity."""
    for rel in relationships:
        partner = None
        if rel.get("source", "").lower() == name.lower():
            partner = rel.get("target", "").lower()
        elif rel.get("target", "").lower() == name.lower():
            partner = rel.get("source", "").lower()

        if partner and partner in existing:
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
    "de", "del", "la", "el", "los", "las",  # common Spanish fillers Rodrigo's data hits often
}


def _name_tokens(name: str) -> set[str]:
    """Lowercased content tokens from an entity name, stopwords removed."""
    import re
    raw = re.findall(r"[\w'-]+", (name or "").lower())
    return {t for t in raw if t and t not in _STOPWORD_TOKENS and len(t) >= 2}


def _share_content_token(a: str, b: str) -> bool:
    return bool(_name_tokens(a) & _name_tokens(b))


_DISAMBIG_PROMPT = """You are deciding whether two entity entries from a personal knowledge graph refer to the same real-world thing.

Both entries have overlapping names (for example "Francesco" and "Francesco Baldissera") but the existing one was built from different conversations, so you need to look at the descriptions and decide whether merging them would be correct.

ENTITY A (existing in graph)
Name: {existing_name}
Type: {existing_type}
Description:
{existing_body}

ENTITY B (new extraction)
Name: {new_name}
Type: {new_type}
Description:
{new_description}

Guidelines:
- Say SAME only when the descriptions clearly point at the same real person, project, company, concept, tool, deadline, skill, or location. Shared last names alone are not enough. Shared first names alone are definitely not enough.
- Say SAME when one description is a vague subset of the other and nothing in either description contradicts the merge.
- Say DIFFERENT when the descriptions place the entities in clearly different contexts (different roles, different companies, different cities) or when one description is empty and the names don't obviously line up.
- Say UNSURE when there is overlap in the name tokens but the descriptions are too weak to merge safely. If you are hesitating, return UNSURE.
- If the type fields disagree (e.g. person vs project), they are not the same.

Respond with JSON only:
{{"decision": "same" | "different" | "unsure", "reason": "one short sentence"}}
"""


async def _llm_judge_same_entity(
    new_name: str,
    new_type: str,
    new_description: str,
    existing_name: str,
    existing_type: str,
    existing_body: str,
    settings: Settings,
) -> str:
    """One LLM call: same, different, or unsure."""
    if new_type and existing_type and new_type.lower() != existing_type.lower():
        return "different"
    prompt = _DISAMBIG_PROMPT.format(
        existing_name=existing_name,
        existing_type=existing_type or "unknown",
        existing_body=(existing_body or "")[:2000] or "(empty)",
        new_name=new_name,
        new_type=new_type or "unknown",
        new_description=(new_description or "")[:1500] or "(empty)",
    )
    # Stage 2 disambiguation has its own dedicated model so we can route the
    # judge to a cheaper/faster model without downgrading the rest of Sleep.
    # Fall back to the main cycle model if the setting is empty.
    disambig_model = (
        getattr(settings, "litellm_disambiguation_model", "") or settings.litellm_model
    )
    try:
        response = await litellm.acompletion(
            model=disambig_model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or "{}"
        parsed = json.loads(raw)
        decision = str(parsed.get("decision", "")).strip().lower()
        if decision in {"same", "different", "unsure"}:
            return decision
        return "unsure"
    except Exception as e:
        logger.debug(f"Disambiguation judge failed for {new_name} vs {existing_name}: {e}")
        return "unsure"


async def _find_llm_candidate_match(
    new_entity: dict,
    existing_by_name: dict[str, dict],
    created_by_id: dict[str, dict],
    cache: dict[tuple[str, str], str],
    settings: Settings,
) -> dict | None:
    """Look for an existing or in-cycle entity that the LLM judges as same/unsure.

    Candidates are same-type entities that share at least one content token with
    the new entity's name and do not already fall under the strict-fuzz match.
    Returns the first SAME match immediately; otherwise returns the strongest
    UNSURE match so the caller can create a clarification instead of inventing
    a new page.
    """
    new_name = new_entity.get("name") or ""
    new_name_lower = new_name.lower()
    new_type = (new_entity.get("type") or "concept").lower()
    new_description = new_entity.get("description") or ""

    if not new_name or not _name_tokens(new_name):
        return None

    candidates: list[dict] = []
    for existing_name_lower, existing_data in existing_by_name.items():
        candidate = {"source": "existing", "id": existing_data["id"], "data": existing_data}
        if _candidate_type(candidate) != new_type:
            continue
        existing_display = _candidate_display_name(candidate)
        if not _share_content_token(new_name, existing_display):
            continue
        if fuzz.ratio(new_name_lower, existing_name_lower) > 85:
            continue
        candidates.append(candidate)

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

    unsure_candidate: dict | None = None
    for candidate in candidates:
        existing_display = _candidate_display_name(candidate)
        cache_key = (new_name_lower, candidate["id"])
        if cache_key in cache:
            decision = cache[cache_key]
            if decision == "same":
                return {"decision": "same", "candidate": candidate}
            if decision == "unsure" and unsure_candidate is None:
                unsure_candidate = candidate
            continue

        decision = await _llm_judge_same_entity(
            new_name=new_name,
            new_type=new_type,
            new_description=new_description,
            existing_name=existing_display,
            existing_type=_candidate_type(candidate),
            existing_body=_candidate_description(candidate),
            settings=settings,
        )
        cache[(new_name_lower, candidate["id"])] = decision
        if decision == "same":
            logger.info(
                f"LLM disambiguation merged '{new_name}' -> '{existing_display}'"
            )
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


def _infer_uncertainty_type(entity: dict) -> str:
    """Map an extracted low-confidence entity to a clarification uncertainty type."""
    etype = (entity.get("type") or "").lower()
    description = (entity.get("description") or "").strip()
    if etype == "person":
        return "Unknown relationship details"
    if not description or len(description) < 40:
        return "Insufficient context to classify"
    return "Ambiguous type or role"


