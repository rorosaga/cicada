"""Stage 2: Entity Resolution & Deduplication."""

import json
from collections import Counter

import litellm
from thefuzz import fuzz

from api.config import Settings


async def resolve(
    extracted: list[dict], existing: list[dict], settings: Settings
) -> dict:
    """Resolve extracted entities against existing graph. Enforce promotion model.

    Returns dict with 'changes' (entity updates) and 'relationships' (resolved edges).
    """
    existing_by_name: dict[str, dict] = {}
    for e in existing:
        name = e["frontmatter"].get("name", e["id"].replace("-", " ").title())
        existing_by_name[name.lower()] = e

    # Count mentions across episodes for promotion threshold
    mention_counts: Counter = Counter()
    episode_mentions: dict[str, set[str]] = {}  # entity_name -> set of episode_ids

    all_entities: list[dict] = []
    all_relationships: list[dict] = []

    for extraction in extracted:
        episode_id = extraction["episode_id"]
        for entity in extraction.get("entities", []):
            name = entity["name"]
            mention_counts[name.lower()] += 1
            episode_mentions.setdefault(name.lower(), set()).add(episode_id)
            all_entities.append(entity)
        all_relationships.extend(extraction.get("relationships", []))

    resolved: list[dict] = []
    # Track name -> final entity_id so we can resolve relationships to existing IDs
    name_to_id: dict[str, str] = {}

    # First, register all existing entities
    for existing_name, existing_data in existing_by_name.items():
        name_to_id[existing_name] = existing_data["id"]

    # Deduplicate entities by name (keep best confidence)
    best_by_name: dict[str, dict] = {}
    for entity in all_entities:
        name_lower = entity["name"].lower()
        current = best_by_name.get(name_lower)
        if current is None or entity.get("confidence", 0) > current.get("confidence", 0):
            best_by_name[name_lower] = entity

    for name_lower, entity in best_by_name.items():
        name = entity["name"]

        # Check if already exists (exact match)
        match = existing_by_name.get(name_lower)

        # Fuzzy match against existing
        if not match:
            for existing_name, existing_data in existing_by_name.items():
                if fuzz.ratio(name_lower, existing_name) > 85:
                    match = existing_data
                    break

        if match:
            # Existing entity — merge/update
            name_to_id[name_lower] = match["id"]
            resolved.append({
                "id": match["id"],
                "action": "update",
                "entity": entity,
                "existing": match,
                "source_episode": entity.get("source_episode", ""),
                "trigger": "sleep/extraction",
            })
        else:
            # New entity — check promotion threshold
            episodes_seen = len(episode_mentions.get(name_lower, set()))
            linked_to_existing = _is_linked_to_existing(name, all_relationships, existing_by_name)

            if episodes_seen >= settings.sleep_promotion_threshold or linked_to_existing:
                entity_id = _sanitize_id(name)
                name_to_id[name_lower] = entity_id
                resolved.append({
                    "id": entity_id,
                    "action": "create",
                    "entity": entity,
                    "existing": None,
                    "source_episode": entity.get("source_episode", ""),
                    "trigger": "sleep/promotion",
                })

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

    return {"changes": resolved, "relationships": resolved_edges}


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


def _sanitize_id(name: str) -> str:
    """Convert entity name to a safe filesystem ID."""
    import re
    # Lowercase, replace spaces and unsafe chars with hyphens, collapse multiples
    safe = name.lower()
    safe = re.sub(r"[/\\:*?\"<>|.]+", "-", safe)  # filesystem-unsafe chars
    safe = safe.replace(" ", "-")
    safe = re.sub(r"-+", "-", safe)  # collapse multiple hyphens
    safe = safe.strip("-")
    return safe or "unnamed"
