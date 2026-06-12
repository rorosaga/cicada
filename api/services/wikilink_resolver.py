"""Stage 5.5 — materialize `[[wikilinks]]` in entity bodies as `mentions` edges.

681 of the entity bodies in the live memory dir carry ``[[Display Name]]``
wikilinks that no Python code parsed — they were decorative. This module reads
every entity body, resolves each wikilink to a real entity id via a bulk
name→id index, and merges the resolved links into ``graph_edges.yaml`` as
``mentions`` edges. ``graph_edges.yaml`` is the single canonical edge source
(see docs/design/hubs-and-traversal.md §4); ``related`` frontmatter is a derived
denormalization. This step is idempotent and additive: re-running produces the
same edge set and never deletes relationship edges.
"""

from __future__ import annotations

import re
from pathlib import Path

from api.services import markdown_parser
from api.services.id_utils import build_name_index, resolve_entity_id
from api.services.inbox_generator import _write_graph_edges

_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


def extract_wikilinks(body: str) -> list[str]:
    """Return the display names from every ``[[Display Name]]`` in ``body``.

    Strips any ``|alias`` so ``[[Real Name|alias]]`` yields ``Real Name``.
    """
    names: list[str] = []
    for raw in _WIKILINK_RE.findall(body or ""):
        name = raw.split("|", 1)[0].strip()
        if name:
            names.append(name)
    return names


def materialize_wikilink_edges(memory_path: Path) -> int:
    """Parse every entity body's wikilinks and merge them as `mentions` edges.

    Idempotent and additive. Returns the number of distinct `mentions` edges
    emitted this run (pre-dedup count of resolved, non-self links).
    """
    entities_dir = Path(memory_path) / "entities"
    if not entities_dir.exists():
        return 0

    name_index = build_name_index(entities_dir)

    new_edges: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for filepath in sorted(entities_dir.glob("*.md")):
        source_id = filepath.stem
        try:
            body = markdown_parser.parse(filepath).body
        except Exception:
            continue
        for display in extract_wikilinks(body):
            target_id = resolve_entity_id(entities_dir, display, name_index)
            if not target_id or target_id == source_id:
                continue
            key = (source_id, target_id)
            if key in seen:
                continue
            seen.add(key)
            new_edges.append({"source": source_id, "target": target_id, "label": "mentions"})

    if new_edges:
        _write_graph_edges(memory_path, new_edges)
    return len(new_edges)
