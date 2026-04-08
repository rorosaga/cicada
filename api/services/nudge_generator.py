"""Stage 5: Nudge Generation, Clarification Queue & Versioning."""

from datetime import date
from pathlib import Path

from api.services import markdown_parser
from api.services.conflict_resolver import apply_changes


async def generate(
    changes: list[dict], skills: list[dict], memory_path: Path
) -> None:
    """Generate nudge/clarification files and apply entity changes."""
    nudges_dir = memory_path / "nudges"
    entities_dir = memory_path / "entities"
    nudges_dir.mkdir(parents=True, exist_ok=True)

    # Apply entity file changes (create, update, archive, decay)
    apply_changes(changes, memory_path)

    # Generate nudge files for decay and conflict items
    nudge_count = _count_existing_nudges(nudges_dir)

    for change in changes:
        action = change.get("action", "")

        if action == "decay_nudge":
            nudge_count += 1
            entity_id = change["id"]
            entity_path = entities_dir / f"{entity_id}.md"
            entity_name = entity_id.replace("-", " ").title()
            if entity_path.exists():
                parsed = markdown_parser.parse(entity_path)
                entity_name = parsed.frontmatter.get("name", entity_name)

            nudge_id = f"nudge-{nudge_count:03d}"
            frontmatter = {
                "entity_name": entity_name,
                "entity_id": entity_id,
                "type": "decay",
                "short_description": f"No recent mentions of {entity_name}",
                "created_date": str(date.today()),
                "options": None,
            }
            body = (
                f"{entity_name} hasn't been mentioned recently and its confidence "
                f"has dropped to {change.get('new_confidence', 0):.2f}. "
                f"Should we keep tracking it or archive it?"
            )
            markdown_parser.write(nudges_dir / f"{nudge_id}.md", frontmatter, body)

        elif action == "conflict_nudge":
            nudge_count += 1
            entity_id = change["id"]
            nudge_id = f"nudge-{nudge_count:03d}"
            entity_name = change.get("entity", {}).get("name", entity_id.replace("-", " ").title())
            frontmatter = {
                "entity_name": entity_name,
                "entity_id": entity_id,
                "type": "conflict",
                "short_description": f"Conflicting information about {entity_name}",
                "created_date": str(date.today()),
                "options": change.get("options", []),
            }
            body = change.get("conflict_context", f"New information conflicts with existing data for {entity_name}.")
            markdown_parser.write(nudges_dir / f"{nudge_id}.md", frontmatter, body)

    # Create skill entities
    for skill in skills:
        skill_id = skill["name"].lower().replace(" ", "-")
        skill_path = entities_dir / f"{skill_id}.md"
        if not skill_path.exists():
            frontmatter = {
                "name": skill["name"],
                "type": "skill",
                "status": "active",
                "confidence": skill.get("confidence", 0.5),
                "created": str(date.today()),
                "last_referenced": str(date.today()),
                "decay_rate": 0.02,
                "source_episodes": [],
                "tags": [],
                "related": [],
                "version": 1,
            }
            markdown_parser.write(skill_path, frontmatter, skill.get("description", ""))


def _count_existing_nudges(nudges_dir: Path) -> int:
    """Count existing nudge files to determine next nudge number."""
    return len(list(nudges_dir.glob("*.md")))
