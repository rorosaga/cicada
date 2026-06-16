"""Stage 5: Inbox Generation, Clarification Queue & Versioning."""

from datetime import date
from pathlib import Path

import yaml

from api.services import markdown_parser
from api.services.conflict_resolver import apply_changes
from api.services.id_utils import sanitize_id


async def generate(
    changes: list[dict],
    skills: list[dict],
    memory_path: Path,
    relationships: list[dict] | None = None,
) -> None:
    """Generate inbox items, apply entity changes, persist relationships."""
    inbox_dir = memory_path / "inbox"
    entities_dir = memory_path / "entities"
    inbox_dir.mkdir(parents=True, exist_ok=True)

    # Apply entity file changes (create, update, archive, decay)
    apply_changes(changes, memory_path)

    # Persist relationships to graph_edges.yaml (merge with existing)
    if relationships:
        _write_graph_edges(memory_path, relationships)

    # Also update each entity's `related` field based on new relationships
    if relationships:
        _update_related_fields(entities_dir, relationships)

    # Generate inbox items for decay and conflict changes. Seed from max-id+1
    # so deletions (resolved items) never cause an id collision — the old bug
    # used len(glob), which reset after files were removed.
    next_num = _next_inbox_num(inbox_dir)

    for change in changes:
        action = change.get("action", "")

        if action == "decay_nudge":
            entity_id = change["id"]
            entity_path = entities_dir / f"{entity_id}.md"
            entity_name = entity_id.replace("-", " ").title()
            if entity_path.exists():
                parsed = markdown_parser.parse(entity_path)
                entity_name = parsed.frontmatter.get("name", entity_name)

            item_id = f"inbox-{next_num:03d}"
            next_num += 1
            new_confidence = float(change.get("new_confidence", 0) or 0)
            frontmatter = {
                "kind": "decay",
                "required_input": "choice",
                "status": "pending",
                "priority": new_confidence,
                "entity_id": entity_id,
                "entity_name": entity_name,
                "title": f"No recent mentions of {entity_name}",
                "created_date": str(date.today()),
                "options": None,
            }
            body = (
                f"{entity_name} hasn't been mentioned recently and its confidence "
                f"has dropped to {new_confidence:.2f}. "
                f"Should we keep tracking it or archive it?"
            )
            markdown_parser.write(inbox_dir / f"{item_id}.md", frontmatter, body)

        elif action == "conflict_nudge":
            entity_id = change["id"]
            item_id = f"inbox-{next_num:03d}"
            next_num += 1
            entity_name = change.get("entity", {}).get("name", entity_id.replace("-", " ").title())
            frontmatter = {
                "kind": "conflict",
                "required_input": "choice",
                "status": "pending",
                "priority": 0.8,
                "entity_id": entity_id,
                "entity_name": entity_name,
                "title": f"Conflicting information about {entity_name}",
                "created_date": str(date.today()),
                "options": change.get("options", []),
            }
            body = change.get("conflict_context", f"New information conflicts with existing data for {entity_name}.")
            markdown_parser.write(inbox_dir / f"{item_id}.md", frontmatter, body)

    # Create skill entities — sanitize_id keeps skills in lockstep with the
    # entity path so names like "AI/ML project framing" don't try to write to
    # a non-existent `ai/` subdirectory and crash Stage 5.
    for skill in skills:
        skill_id = sanitize_id(skill["name"])
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


def _next_inbox_num(inbox_dir: Path) -> int:
    """Next inbox number = max existing number + 1 (never count-based)."""
    max_num = 0
    for filepath in inbox_dir.glob("inbox-*.md"):
        try:
            max_num = max(max_num, int(filepath.stem.split("-")[-1]))
        except ValueError:
            continue
    return max_num + 1
