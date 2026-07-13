"""Promote relationship targets that have no page but are the object of an edge
(e.g. 'reports to Diego Albano'), so name-search can resolve them. Creates a
backfilled stub with the relationships that name it.

Promotion is conservative: targets that look like dates, numbers, or trivial /
very-common words are never promoted, and a target is only ever promoted as
`type: person` when at least one incoming edge carries a person-indicating
label (e.g. "reports-to", "works-with"). Targets with no person signal are
skipped entirely rather than mislabeled — leaving something un-promoted is
better than polluting the graph with a wrongly-typed stub.
"""
from __future__ import annotations
import re
from pathlib import Path
import yaml
from api.services import markdown_parser

# Dates like "2026-09-01", "2026-09", or "2026" — never real named entities.
_DATE_RE = re.compile(r"^\d{4}(-\d{2}){0,2}$")
_DATE_SUBSTR_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

# Single generic words that show up constantly as edge targets but are never
# themselves promotable named entities.
_COMMON_WORDS = {
    "claude", "cicada", "user", "team", "project", "company", "meeting",
    "email", "call", "today", "yesterday", "tomorrow", "app", "system",
    "data", "vision", "the", "a", "an", "it", "this", "that",
}

# Substrings checked against a lowercased edge label to decide whether an
# edge is "person-ish" enough to justify promoting its target as a person.
_PERSON_LABEL_SIGNALS = (
    "reports-to", "reports to", "manager", "managed-by", "works-with",
    "colleague", "co-worker", "knows", "met", "mentor", "supervisor",
    "advisor", "friend", "collaborat", "hired", "recruit", "interview",
    "contact", "founder", "led-by", "led by",
)


def _titleize(slug: str) -> str:
    return " ".join(w.capitalize() for w in slug.replace("-", " ").split())


def _looks_promotable(target_id: str) -> bool:
    """Reject date-like, numeric, and trivial target ids before promotion."""
    if not target_id:
        return False
    if _DATE_RE.match(target_id) or _DATE_SUBSTR_RE.search(target_id):
        return False
    if target_id.replace("-", "").isdigit():
        return False
    if len(target_id) < 3:
        return False
    if "-" not in target_id and target_id.lower() in _COMMON_WORDS:
        return False
    return True


def _has_person_signal(edge_list: list) -> bool:
    """True if any incoming edge's label suggests the target is a person."""
    for e in edge_list:
        label = (e.get("label") or "").lower()
        if any(signal in label for signal in _PERSON_LABEL_SIGNALS):
            return True
    return False


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
        if not _looks_promotable(tgt):
            continue
        if not _has_person_signal(edge_list):
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
