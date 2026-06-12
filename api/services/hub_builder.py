"""Stage 5.6 — regenerate the hub tier (`hubs/*.md`) and root `_index.md`.

Hubs are *persisted markdown files*, not render-time virtual nodes, so a small
LLM can ``cat`` them while traversing the filesystem without the API (see
docs/design/hubs-and-traversal.md). Two hub kinds:

- type hubs   — one per non-empty entity type (people, projects, tools, ...).
- tag hubs    — one per tag shared by >= ``hub_tag_min_members`` active entities.

Each hub carries its member list TWICE: a structured ``members:`` list in the
frontmatter (for API-side consumers using real pyyaml) and a wikilinked bullet
list in the BODY (the MCP flat parser cannot read nested YAML, so it returns the
body verbatim). Generation is fully deterministic — no LLM calls — so it is
free to run every sleep cycle.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from api.config import Settings
from api.services import markdown_parser

# type -> (hub file stem, friendly display name). Order drives _index.md listing.
TYPE_HUBS: list[tuple[str, str, str]] = [
    ("person", "people", "People & Contacts"),
    ("project", "projects", "Projects"),
    ("company", "companies", "Companies"),
    ("concept", "concepts", "Concepts"),
    ("tool", "tools", "Tools"),
    ("deadline", "deadlines", "Deadlines"),
    ("skill", "skills", "Skills"),
    ("location", "places", "Places"),
    ("media", "media", "Media"),
]

_ARCHIVED_STATUSES = {"archived", "dropped"}


def _one_line_summary(body: str, limit: int = 140) -> str:
    """Derive a one-line blurb from an entity body without an LLM call.

    Unwraps wikilinks, strips markdown noise, collapses whitespace, takes the
    first sentence, and truncates to ``limit`` chars.
    """
    text = re.sub(r"\[\[([^\]|]+)(\|[^\]]+)?\]\]", r"\1", body or "")
    text = re.sub(r"[#>*`_-]", " ", text)
    text = " ".join(text.split())
    if not text:
        return ""
    first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    return (first[:limit] + "…") if len(first) > limit else first


def _load_active_entities(entities_dir: Path) -> tuple[list[dict], int]:
    """Return (member-eligible entities, total entity count incl. archived).

    Each eligible entity dict carries id/name/type/confidence/tags/summary.
    Archived/dropped entities are excluded from membership but still counted.
    """
    members: list[dict] = []
    total = 0
    if not entities_dir.exists():
        return members, total
    for filepath in sorted(entities_dir.glob("*.md")):
        try:
            parsed = markdown_parser.parse(filepath)
        except Exception:
            continue
        total += 1
        fm = parsed.frontmatter or {}
        status = str(fm.get("status", "active") or "active").lower()
        if status in _ARCHIVED_STATUSES:
            continue
        members.append({
            "id": filepath.stem,
            "name": str(fm.get("name", filepath.stem.replace("-", " ").title())),
            "type": str(fm.get("type", "concept") or "concept"),
            "confidence": float(fm.get("confidence", 0.5) or 0.0),
            "tags": [str(t) for t in (fm.get("tags", []) or []) if t],
            "summary": _one_line_summary(parsed.body),
        })
    return members, total


def _hub_body(name: str, blurb: str, members: list[dict], cap: int, generated: str) -> str:
    """Render the hub body: wikilinked member bullets + a generation footer."""
    shown = members[:cap]
    lines = [f"## {name}", "", blurb, ""]
    for m in shown:
        summary = m["summary"]
        suffix = f" — {summary}" if summary else ""
        lines.append(f"- [[{m['name']}]] ({m['type']}, {m['confidence']:.2f}){suffix}")
    lines.append("")
    overflow = len(members) - len(shown)
    if overflow > 0:
        lines.append(
            f"> {len(shown)} of {len(members)} members shown "
            f"(highest-confidence first); {overflow} more lower-confidence "
            f"members exist — query `cicada_recall` to find them. "
            f"Generated {generated} by sleep cycle."
        )
    else:
        lines.append(
            f"> {len(shown)} members shown of {len(members)}. "
            f"Generated {generated} by sleep cycle."
        )
    return "\n".join(lines)


def _existing_version(filepath: Path) -> int:
    """Read the prior hub version (+1 on rewrite) or 0 if the file is new."""
    if not filepath.exists():
        return 0
    try:
        fm = markdown_parser.parse(filepath).frontmatter or {}
        return int(fm.get("version", 0) or 0)
    except Exception:
        return 0


def _write_hub(
    hubs_dir: Path,
    stem: str,
    name: str,
    hub_kind: str,
    members: list[dict],
    cap: int,
    generated: str,
    *,
    source_type: str | None = None,
    source_tag: str | None = None,
) -> str:
    """Write one hub file. Returns the filename written (e.g. ``people.md``)."""
    filepath = hubs_dir / f"{stem}.md"
    version = _existing_version(filepath) + 1
    capped = members[:cap]
    # All scalar identity keys MUST precede the nested ``members`` list. The
    # MCP server's pyyaml-free flat parser stops reading at ``members:`` (it
    # cannot parse nested dicts), so any key placed after ``members`` would be
    # invisible to MCP-side hub matching (see docs/design/hubs-and-traversal.md
    # critic fix). ``version`` is intentionally placed before ``members`` too.
    frontmatter: dict = {
        "type": "hub",
        "hub_kind": hub_kind,
        "status": "active",
        "generated": generated,
        "name": name,
        "member_count": len(members),
        "version": version,
    }
    if source_type is not None:
        frontmatter["source_type"] = source_type
    if source_tag is not None:
        frontmatter["source_tag"] = source_tag
    frontmatter["members"] = [
        {
            "id": m["id"],
            "name": m["name"],
            "type": m["type"],
            "confidence": round(m["confidence"], 4),
            "summary": m["summary"],
        }
        for m in capped
    ]

    if hub_kind == "type":
        blurb = (
            f"{len(members)} {name.lower()} Cicada is tracking. Highest-confidence "
            f"first. Click a name to open the entity page, or read "
            f"`memory/entities/<id>.md` directly."
        )
    else:
        blurb = (
            f"{len(members)} entities tagged '{source_tag}', spanning types. "
            f"Highest-confidence first. A cross-cutting topic anchor."
        )
    body = _hub_body(name, blurb, members, cap, generated)
    markdown_parser.write(filepath, frontmatter, body)
    return filepath.name


def _write_index(
    memory_path: Path,
    type_hubs: list[dict],
    tag_hubs: list[dict],
    *,
    entity_count: int,
    active_entity_count: int,
    episode_count: int,
    edge_count: int,
    hub_count: int,
    pending_inbox_count: int,
    generated: str,
) -> None:
    """Write the root map-of-content ``_index.md``."""
    frontmatter = {
        "type": "index",
        "generated": generated,
        "entity_count": entity_count,
        "active_entity_count": active_entity_count,
        "episode_count": episode_count,
        "edge_count": edge_count,
        "hub_count": hub_count,
        "pending_inbox_count": pending_inbox_count,
    }
    lines = [
        "# Cicada Memory — Map of Content",
        "",
        "This is a personal knowledge graph. To find something:",
        "1. Skim the hubs below and pick the most relevant topic.",
        "2. Read that hub file in `memory/hubs/`. It lists member entities with one-line summaries.",
        "3. Open the member entity at `memory/entities/<id>.md`.",
        "4. Follow its wikilinks, `related`, or `source_episodes` for more depth.",
        "For fuzzy/semantic search, call the `cicada_recall` MCP tool instead of scanning.",
        "",
        "## Type hubs",
    ]
    for h in type_hubs:
        lines.append(
            f"- [[{h['name']}]] — `hubs/{h['stem']}.md` ({h['member_count']} members)"
        )
    if tag_hubs:
        lines.append("")
        lines.append("## Topic hubs (cross-cutting)")
        for h in tag_hubs:
            lines.append(
                f"- [[{h['name']}]] — `hubs/{h['stem']}.md` ({h['member_count']} members)"
            )
    lines += [
        "",
        "## Stats",
        f"- {entity_count} entities ({active_entity_count} active), "
        f"{episode_count} episodes, {edge_count} edges, {hub_count} hubs.",
        f"- Last sleep cycle: {generated}.",
    ]
    markdown_parser.write(memory_path / "_index.md", frontmatter, "\n".join(lines))


def _count_edges(memory_path: Path) -> int:
    edges_file = memory_path / "graph_edges.yaml"
    if not edges_file.exists():
        return 0
    try:
        import yaml

        data = yaml.safe_load(edges_file.read_text(encoding="utf-8")) or {}
        return len(data.get("edges", []) or [])
    except Exception:
        return 0


def _count_pending_inbox(memory_path: Path) -> int:
    """Count pending items in inbox/, falling back to legacy nudges/+clarifications/."""
    inbox = memory_path / "inbox"
    if inbox.exists():
        return sum(1 for _ in inbox.glob("inbox-*.md"))
    total = 0
    for sub in ("nudges", "clarifications"):
        d = memory_path / sub
        if d.exists():
            total += sum(1 for _ in d.glob("*.md"))
    return total


def regenerate_hubs_and_index(memory_path: Path, settings: Settings) -> dict:
    """Rewrite ``memory/hubs/*.md`` and ``memory/_index.md`` from entity files.

    Returns ``{"hub_files": [...], "index_file": "_index.md", "hub_count": N}``.
    Fully deterministic, no LLM calls. Idempotent.
    """
    memory_path = Path(memory_path)
    entities_dir = memory_path / "entities"
    hubs_dir = memory_path / "hubs"
    hubs_dir.mkdir(parents=True, exist_ok=True)

    cap = settings.hub_member_cap
    tag_min = settings.hub_tag_min_members
    tag_max = settings.hub_tag_max_hubs
    generated = str(date.today())

    members, total_entities = _load_active_entities(entities_dir)
    active_count = len(members)

    written: list[str] = []
    written_stems: set[str] = set()
    type_index: list[dict] = []
    tag_index: list[dict] = []

    # --- Type hubs ---
    by_type: dict[str, list[dict]] = {}
    for m in members:
        by_type.setdefault(m["type"], []).append(m)

    from api.services.id_utils import sanitize_id

    for etype, stem, friendly in TYPE_HUBS:
        group = by_type.get(etype, [])
        if not group:
            continue
        group_sorted = sorted(group, key=lambda m: -m["confidence"])
        filename = _write_hub(
            hubs_dir, stem, friendly, "type", group_sorted, cap, generated,
            source_type=etype,
        )
        written.append(filename)
        written_stems.add(stem)
        type_index.append({"stem": stem, "name": friendly, "member_count": len(group_sorted)})

    # --- Tag hubs ---
    tag_groups: dict[str, list[dict]] = {}
    for m in members:
        for tag in m["tags"]:
            tag_groups.setdefault(str(tag), []).append(m)

    eligible = [(tag, grp) for tag, grp in tag_groups.items() if len(grp) >= tag_min]
    eligible.sort(key=lambda x: -len(x[1]))
    for tag, grp in eligible[:tag_max]:
        stem = f"topic-{sanitize_id(tag)}"
        friendly = tag.title()
        group_sorted = sorted(grp, key=lambda m: -m["confidence"])
        filename = _write_hub(
            hubs_dir, stem, friendly, "tag", group_sorted, cap, generated,
            source_tag=tag,
        )
        written.append(filename)
        written_stems.add(stem)
        tag_index.append({"stem": stem, "name": friendly, "member_count": len(group_sorted)})

    # --- Stale hub cleanup (only delete hubs/ files whose type == "hub") ---
    for filepath in hubs_dir.glob("*.md"):
        if filepath.stem in written_stems:
            continue
        try:
            fm = markdown_parser.parse(filepath).frontmatter or {}
        except Exception:
            continue
        if fm.get("type") == "hub":
            filepath.unlink()

    hub_count = len(written)

    # --- _index.md ---
    episode_count = (
        sum(1 for _ in (memory_path / "episodes").glob("*.md"))
        if (memory_path / "episodes").exists()
        else 0
    )
    _write_index(
        memory_path,
        type_index,
        tag_index,
        entity_count=total_entities,
        active_entity_count=active_count,
        episode_count=episode_count,
        edge_count=_count_edges(memory_path),
        hub_count=hub_count,
        pending_inbox_count=_count_pending_inbox(memory_path),
        generated=generated,
    )

    return {"hub_files": written, "index_file": "_index.md", "hub_count": hub_count}
