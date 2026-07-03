"""Promote relationship targets that have no page but are the object of an edge
(e.g. 'reports to Diego Albano'), so name-search can resolve them. Creates a
backfilled stub with the relationships that name it."""
from __future__ import annotations
from pathlib import Path
import yaml
from api.services import markdown_parser


def _titleize(slug: str) -> str:
    return " ".join(w.capitalize() for w in slug.replace("-", " ").split())


def promote_relationship_targets(memory_path: Path, *, min_refs: int = 1) -> list[str]:
    ents = memory_path / "entities"
    edges_file = memory_path / "graph_edges.yaml"
    if not edges_file.exists():
        return []
    edges = (yaml.safe_load(edges_file.read_text()) or {}).get("edges", [])
    existing = {f.stem for f in ents.glob("*.md")}

    refs: dict[str, list] = {}
    for e in edges:
        tgt = e.get("target")
        if tgt and tgt not in existing:
            refs.setdefault(tgt, []).append(e)

    created = []
    for tgt, edge_list in refs.items():
        if len(edge_list) < min_refs:
            continue
        name = _titleize(tgt)
        facts = "\n".join(
            f"- {e.get('source')}: {e.get('label','related')}" for e in edge_list)
        body = (f"## Summary\n{name} — promoted from relationship references.\n\n"
                f"## Key Facts\n{facts}\n")
        fm = {"name": name, "type": "person", "status": "active", "confidence": 0.4,
              "source_episodes": [], "related": [e.get("source") for e in edge_list],
              "promoted_from": "relationship_target", "layout_version": 2}
        markdown_parser.write(ents / f"{tgt}.md", fm, body)
        created.append(tgt)
    return created
