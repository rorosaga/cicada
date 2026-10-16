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


def materialize_wikilink_edges(memory_path: Path, extracted: list[dict] | None = None, settings=None) -> int:
    """Parse every entity body's wikilinks and merge them as `mentions` edges.

    Idempotent and additive. Returns the number of distinct `mentions` edges
    emitted this run (pre-dedup count of resolved, non-self links).

    G169: a wikilink spelled like a self-reference (``[[User]]``, ``[[the user|them]]``,
    ``[[mí]]``) is the bank's owner when it is a speaker reference — the same
    qualified decision Stage 2 and the claims key by (``owner_identity.
    SelfReferences``, built from the pages, the pending lines and ``extracted``,
    this batch's Stage-1 output, with ``settings`` for the owner tie-break when a
    bank holds two owner pages) — never an old duplicate ``user`` page; a page that holds the name
    (the company "Owner") keeps its links. The prose is never rewritten.
    """
    from api.services import owner_identity

    entities_dir = Path(memory_path) / "entities"
    if not entities_dir.exists():
        return 0

    name_index = build_name_index(entities_dir)

    pages: list[tuple[str, dict, str]] = []
    for filepath in sorted(entities_dir.glob("*.md")):
        try:
            parsed = markdown_parser.parse(filepath)
        except Exception:
            continue
        pages.append((filepath.stem, parsed.frontmatter or {}, parsed.body))
    refs = owner_identity.self_references(
        [{"id": stem, "frontmatter": fm} for stem, fm, _ in pages], extracted, Path(memory_path), settings)

    new_edges: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for source_id, _fm, body in pages:
        for display in extract_wikilinks(body):
            if refs.is_speaker(display):
                target_id = refs.owner_id
            else:
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
