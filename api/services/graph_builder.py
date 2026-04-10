from pathlib import Path

import yaml

from api.models.schemas import GraphLink, GraphNode, GraphResponse
from api.services.markdown_parser import parse


def build_graph(memory_path: Path) -> GraphResponse:
    """Build the graph response from entity files and graph_edges.yaml."""
    entities_dir = memory_path / "entities"
    nodes: list[GraphNode] = []

    for filepath in sorted(entities_dir.glob("*.md")):
        parsed = parse(filepath)
        fm = parsed.frontmatter
        entity_id = filepath.stem
        nodes.append(
            GraphNode(
                id=entity_id,
                name=fm.get("name", entity_id.replace("-", " ").title()),
                type=fm.get("type", "concept"),
                status=fm.get("status", "active"),
                confidence=fm.get("confidence", 0.5),
                tags=fm.get("tags", []) or [],
            )
        )

    links = _load_edges(memory_path)
    return GraphResponse(nodes=nodes, links=links)


def _load_edges(memory_path: Path) -> list[GraphLink]:
    """Load labeled edges from graph_edges.yaml, falling back to related fields."""
    edges_file = memory_path / "graph_edges.yaml"
    if edges_file.exists():
        data = yaml.safe_load(edges_file.read_text(encoding="utf-8")) or {}
        return [
            GraphLink(source=e["source"], target=e["target"], label=e.get("label", "related to"))
            for e in data.get("edges", [])
        ]

    # Fallback: derive from related fields with generic label
    links: list[GraphLink] = []
    entities_dir = memory_path / "entities"
    for filepath in entities_dir.glob("*.md"):
        parsed = parse(filepath)
        entity_id = filepath.stem
        for related_id in parsed.frontmatter.get("related", []):
            links.append(GraphLink(source=entity_id, target=str(related_id), label="related to"))
    return links
