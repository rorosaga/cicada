from collections import Counter
from pathlib import Path

import yaml

from api.models.schemas import GraphLink, GraphNode, GraphResponse
from api.services.markdown_parser import parse

# Module-level mtime cache. The full (unfiltered) graph is expensive to build
# over ~1882 entities; keying on the entities-dir + edges-file + inbox mtimes
# means the first GET after a sleep cycle pays the scan once and every repeat is
# a dict lookup. Filters are applied on top of the cached full graph cheaply.
_CACHE: dict = {"key": None, "value": None}


def build_graph(
    memory_path: Path,
    *,
    types: set[str] | None = None,
    statuses: set[str] | None = None,
    min_confidence: float = 0.0,
    tags: set[str] | None = None,
    include_hubs: bool = True,
    hubs_only: bool = False,
) -> GraphResponse:
    """Build the graph response, with server-side degree/flags and filtering."""
    full = _build_full(Path(memory_path))
    return _apply_filters(
        full,
        types=types,
        statuses=statuses,
        min_confidence=min_confidence,
        tags=tags,
        include_hubs=include_hubs,
        hubs_only=hubs_only,
    )


def _build_full(memory_path: Path) -> GraphResponse:
    entities_dir = memory_path / "entities"
    edges_file = memory_path / "graph_edges.yaml"
    hubs_dir = memory_path / "hubs"

    key = (
        _dir_mtime(entities_dir),
        _mtime(edges_file),
        _dir_mtime(hubs_dir),
        _inbox_mtime(memory_path),
    )
    if _CACHE["key"] == key:
        return _CACHE["value"]

    pending_ids = _load_pending_entity_ids(memory_path)
    raw_links = _load_edges(memory_path)

    # Degree from canonical edges (string endpoints at this stage).
    degree: Counter = Counter()
    for link in raw_links:
        degree[link.source] += 1
        degree[link.target] += 1

    nodes: list[GraphNode] = []
    entity_ids: set[str] = set()
    for filepath in sorted(entities_dir.glob("*.md")):
        try:
            fm = parse(filepath).frontmatter
        except Exception:
            continue
        eid = filepath.stem
        entity_ids.add(eid)
        nodes.append(
            GraphNode(
                id=eid,
                name=fm.get("name", eid.replace("-", " ").title()),
                type=fm.get("type", "concept"),
                status=fm.get("status", "active"),
                confidence=fm.get("confidence", 0.5),
                tags=fm.get("tags", []) or [],
                degree=degree.get(eid, 0),
                has_pending=eid in pending_ids,
            )
        )

    # Inject hub anchor nodes + `member of` edges from memory/hubs/*.md.
    hub_links: list[GraphLink] = []
    member_to_hub: dict[str, str] = {}
    if hubs_dir.exists():
        for filepath in sorted(hubs_dir.glob("*.md")):
            try:
                fm = parse(filepath).frontmatter
            except Exception:
                continue
            if fm.get("type") != "hub":
                continue
            hub_id = f"hub:{filepath.stem}"
            members = fm.get("members") or []
            nodes.append(
                GraphNode(
                    id=hub_id,
                    name=fm.get("name", filepath.stem),
                    type="hub",
                    status="active",
                    confidence=1.0,
                    tags=[],
                    degree=len(members),
                    is_hub=True,
                    member_count=int(fm.get("member_count", len(members)) or 0),
                    hub_kind=fm.get("hub_kind"),
                )
            )
            for m in members:
                mid = m.get("id") if isinstance(m, dict) else None
                if not mid or mid not in entity_ids:
                    continue
                hub_links.append(GraphLink(source=hub_id, target=mid, label="member of"))
                # First hub claiming a member wins for the gravity anchor.
                member_to_hub.setdefault(mid, hub_id)

    # Surface hubId on member entity nodes so the d3 layout can apply hub gravity.
    for node in nodes:
        if node.id in member_to_hub:
            node.hub_id = member_to_hub[node.id]

    # Filter canonical edges to endpoints that exist (drops legacy dangling slugs).
    valid_ids = entity_ids | {n.id for n in nodes if n.is_hub}
    links = [l for l in raw_links if l.source in valid_ids and l.target in valid_ids]
    links.extend(hub_links)

    resp = GraphResponse(nodes=nodes, links=links)
    _CACHE.update(key=key, value=resp)
    return resp


def _apply_filters(
    full: GraphResponse,
    *,
    types: set[str] | None,
    statuses: set[str] | None,
    min_confidence: float,
    tags: set[str] | None,
    include_hubs: bool,
    hubs_only: bool,
) -> GraphResponse:
    if (
        not types
        and not statuses
        and not tags
        and min_confidence <= 0.0
        and include_hubs
        and not hubs_only
    ):
        return full

    nodes = full.nodes
    if hubs_only:
        kept_hubs = [n for n in nodes if n.is_hub]
        hub_ids = {n.id for n in kept_hubs}
        member_ids = {
            l.target for l in full.links if l.label == "member of" and l.source in hub_ids
        }
        members = [n for n in nodes if n.id in member_ids]
        kept_nodes = kept_hubs + members
        kept_ids = {n.id for n in kept_nodes}
        kept_links = [
            l for l in full.links if l.source in kept_ids and l.target in kept_ids
        ]
        return GraphResponse(nodes=kept_nodes, links=kept_links)

    def keep(n: GraphNode) -> bool:
        if n.is_hub:
            return include_hubs
        if types and n.type not in types:
            return False
        if statuses and n.status.value not in statuses:
            return False
        if min_confidence > 0.0 and n.confidence < min_confidence:
            return False
        if tags and not (set(n.tags) & tags):
            return False
        return True

    kept_nodes = [n for n in nodes if keep(n)]
    kept_ids = {n.id for n in kept_nodes}
    kept_links = [l for l in full.links if l.source in kept_ids and l.target in kept_ids]
    return GraphResponse(nodes=kept_nodes, links=kept_links)


def _load_edges(memory_path: Path) -> list[GraphLink]:
    """Load labeled edges from graph_edges.yaml — the sole canonical edge source."""
    edges_file = memory_path / "graph_edges.yaml"
    if not edges_file.exists():
        return []
    try:
        data = yaml.safe_load(edges_file.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    return [
        GraphLink(source=e["source"], target=e["target"], label=e.get("label", "related to"))
        for e in data.get("edges", [])
        if e.get("source") and e.get("target")
    ]


def _load_pending_entity_ids(memory_path: Path) -> set[str]:
    """Entity ids referenced by any pending inbox item.

    Reads memory/inbox/ first; falls back to legacy nudges/+clarifications/ so
    the has_pending flag works both before and after the inbox migration.
    """
    ids: set[str] = set()
    inbox = memory_path / "inbox"
    dirs = [inbox] if inbox.exists() else [
        d for d in (memory_path / "nudges", memory_path / "clarifications") if d.exists()
    ]
    for d in dirs:
        for filepath in d.glob("*.md"):
            try:
                fm = parse(filepath).frontmatter
            except Exception:
                continue
            eid = str(fm.get("entity_id", "") or "")
            if eid:
                ids.add(eid)
    return ids


# ---------- mtime helpers (cache invalidation) ----------


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _dir_mtime(path: Path) -> float:
    """Max mtime across a directory's .md files + the dir itself."""
    if not path.exists():
        return 0.0
    latest = _mtime(path)
    for filepath in path.glob("*.md"):
        m = _mtime(filepath)
        if m > latest:
            latest = m
    return latest


def _inbox_mtime(memory_path: Path) -> float:
    latest = 0.0
    for sub in ("inbox", "nudges", "clarifications"):
        m = _dir_mtime(memory_path / sub)
        if m > latest:
            latest = m
    return latest
