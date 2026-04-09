"""Stage 3: Conflict Resolution & Temporal Decay."""

from datetime import date

from api.config import Settings
from api.services import markdown_parser


async def resolve_and_prune(
    resolved: list[dict], existing: list[dict], settings: Settings
) -> list[dict]:
    """Apply conflict resolution and temporal decay to all entities."""
    changes: list[dict] = list(resolved)

    # IDs of entities referenced in this cycle
    referenced_ids = {r["id"] for r in resolved}

    # Temporal decay for unreferenced entities
    for entity_data in existing:
        entity_id = entity_data["id"]
        if entity_id in referenced_ids:
            continue

        fm = entity_data["frontmatter"]
        status = fm.get("status", "active")
        if status in ("archived", "dropped"):
            continue

        confidence = fm.get("confidence", 0.5)
        decay_rate = fm.get("decay_rate", 0.05)
        new_confidence = max(0.0, confidence - decay_rate)

        if new_confidence < settings.archive_threshold:
            changes.append({
                "id": entity_id,
                "action": "archive",
                "new_confidence": new_confidence,
                "new_status": "archived",
                "source_episode": "",
                "trigger": "sleep/decay",
            })
        elif new_confidence < settings.decay_nudge_threshold:
            changes.append({
                "id": entity_id,
                "action": "decay_nudge",
                "new_confidence": new_confidence,
                "new_status": "decaying",
                "source_episode": "",
                "trigger": "sleep/decay",
            })
        else:
            changes.append({
                "id": entity_id,
                "action": "decay",
                "new_confidence": new_confidence,
                "new_status": status,
                "source_episode": "",
                "trigger": "sleep/decay",
            })

    return changes


def apply_changes(changes: list[dict], memory_path) -> None:
    """Write entity changes to disk."""
    entities_dir = memory_path / "entities"

    for change in changes:
        entity_id = change["id"]
        action = change["action"]
        filepath = entities_dir / f"{entity_id}.md"

        if action == "create":
            entity = change.get("entity", {})
            frontmatter = {
                "name": entity.get("name", entity_id.replace("-", " ").title()),
                "type": entity.get("type", "concept"),
                "status": "active",
                "confidence": entity.get("confidence", 0.5),
                "created": str(date.today()),
                "last_referenced": str(date.today()),
                "decay_rate": 0.05,
                "source_episodes": [change.get("source_episode", "")],
                "tags": entity.get("tags", []) or [],
                "related": [],
                "version": 1,
            }
            body = entity.get("description", "") or ""
            markdown_parser.write(filepath, frontmatter, body)

        elif action == "update" and filepath.exists():
            parsed = markdown_parser.parse(filepath)
            parsed.frontmatter["last_referenced"] = str(date.today())
            parsed.frontmatter["version"] = parsed.frontmatter.get("version", 1) + 1
            episodes = parsed.frontmatter.get("source_episodes", [])
            source_ep = change.get("source_episode", "")
            if source_ep and source_ep not in episodes:
                episodes.append(source_ep)
            parsed.frontmatter["source_episodes"] = episodes

            # Merge new tags and append new description info to body
            new_entity = change.get("entity", {})
            new_tags = new_entity.get("tags", []) or []
            if new_tags:
                existing_tags = set(parsed.frontmatter.get("tags", []) or [])
                parsed.frontmatter["tags"] = sorted(existing_tags | set(new_tags))

            # Append new description content if it's substantive and different
            new_desc = new_entity.get("description", "") or ""
            if new_desc and len(new_desc) > 50 and new_desc not in parsed.body:
                updated_body = parsed.body.rstrip() + f"\n\n{new_desc}"
            else:
                updated_body = parsed.body

            markdown_parser.write(filepath, parsed.frontmatter, updated_body)

        elif action in ("decay", "decay_nudge", "archive") and filepath.exists():
            parsed = markdown_parser.parse(filepath)
            parsed.frontmatter["confidence"] = change.get("new_confidence", 0.0)
            if "new_status" in change:
                parsed.frontmatter["status"] = change["new_status"]
            markdown_parser.write(filepath, parsed.frontmatter, parsed.body)
