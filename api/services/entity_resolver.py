"""Stage 2: Entity Resolution & Deduplication."""

import json
from collections import Counter

import litellm
from thefuzz import fuzz

from api.config import Settings


async def resolve(
    extracted: list[dict], existing: list[dict], settings: Settings
) -> list[dict]:
    """Resolve extracted entities against existing graph. Enforce promotion model."""
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

    for entity in all_entities:
        name = entity["name"]
        name_lower = name.lower()

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
                entity_id = name.lower().replace(" ", "-")
                resolved.append({
                    "id": entity_id,
                    "action": "create",
                    "entity": entity,
                    "existing": None,
                    "source_episode": entity.get("source_episode", ""),
                    "trigger": "sleep/promotion",
                })

    return resolved


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
