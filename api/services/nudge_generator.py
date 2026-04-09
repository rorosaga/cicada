"""Stage 5: Nudge Generation, Clarification Queue & Versioning."""

from datetime import date
from pathlib import Path

import yaml

from api.services import markdown_parser
from api.services.conflict_resolver import apply_changes


async def generate(
    changes: list[dict],
    skills: list[dict],
    memory_path: Path,
    relationships: list[dict] | None = None,
) -> None:
    """Generate nudge/clarification files, apply entity changes, persist relationships."""
    nudges_dir = memory_path / "nudges"
    entities_dir = memory_path / "entities"
    nudges_dir.mkdir(parents=True, exist_ok=True)

    # Apply entity file changes (create, update, archive, decay)
    apply_changes(changes, memory_path)

    # Persist relationships to graph_edges.yaml (merge with existing)
    if relationships:
        _write_graph_edges(memory_path, relationships)

    # Also update each entity's `related` field based on new relationships
    if relationships:
        _update_related_fields(entities_dir, relationships)

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


def _write_graph_edges(memory_path: Path, new_edges: list[dict]) -> None:
    """Merge new edges into graph_edges.yaml (dedup by source+target+label)."""
    edges_file = memory_path / "graph_edges.yaml"

    existing_edges: list[dict] = []
    if edges_file.exists():
        try:
            data = yaml.safe_load(edges_file.read_text(encoding="utf-8")) or {}
            existing_edges = data.get("edges", [])
        except Exception:
            existing_edges = []

    # Dedup by (source, target, label)
    seen: set[tuple[str, str, str]] = set()
    merged: list[dict] = []
    for edge in existing_edges + new_edges:
        key = (edge.get("source", ""), edge.get("target", ""), edge.get("label", "").lower())
        if key not in seen:
            seen.add(key)
            merged.append({
                "source": edge.get("source", ""),
                "target": edge.get("target", ""),
                "label": edge.get("label", "related to"),
            })

    edges_file.write_text(
        yaml.dump({"edges": merged}, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def _update_related_fields(entities_dir: Path, relationships: list[dict]) -> None:
    """Update each entity's `related` frontmatter field based on new relationships."""
    # Build map of entity_id -> set of related IDs
    related_map: dict[str, set[str]] = {}
    for rel in relationships:
        src = rel.get("source", "")
        tgt = rel.get("target", "")
        if src and tgt:
            related_map.setdefault(src, set()).add(tgt)
            related_map.setdefault(tgt, set()).add(src)

    for entity_id, related_ids in related_map.items():
        filepath = entities_dir / f"{entity_id}.md"
        if not filepath.exists():
            continue
        parsed = markdown_parser.parse(filepath)
        existing_related = set(parsed.frontmatter.get("related", []) or [])
        updated = sorted(existing_related | related_ids)
        parsed.frontmatter["related"] = updated
        markdown_parser.write(filepath, parsed.frontmatter, parsed.body)


def _count_existing_nudges(nudges_dir: Path) -> int:
    """Count existing nudge files to determine next nudge number."""
    return len(list(nudges_dir.glob("*.md")))
