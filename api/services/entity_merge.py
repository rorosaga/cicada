# api/services/entity_merge.py
"""Merge two rich entity pages into one (the G21 primitive the inbox lacks).

Unions list frontmatter, section-merges bodies (human-prose-safe), repoints
graph_edges.yaml endpoints loser->winner, deletes the loser. Reversible via git.
"""
from __future__ import annotations
from pathlib import Path
import yaml
from api.services import markdown_parser, entity_body

_LIST_FIELDS = ("source_episodes", "tags", "related", "aliases")


def _union(a, b):
    seen, out = set(), []
    for x in list(a or []) + list(b or []):
        if x not in seen:
            seen.add(x); out.append(x)
    return out


def merge_entities(memory_path: Path, loser_id: str, winner_id: str,
                   *, author: str = "user") -> dict:
    ents = memory_path / "entities"
    lp, wp = ents / f"{loser_id}.md", ents / f"{winner_id}.md"
    if not lp.exists() or not wp.exists():
        raise FileNotFoundError(f"merge needs both pages: {loser_id}, {winner_id}")

    lpar, wpar = markdown_parser.parse(lp), markdown_parser.parse(wp)
    lfm, wfm = dict(lpar.frontmatter), dict(wpar.frontmatter)

    for f in _LIST_FIELDS:
        merged = _union(wfm.get(f), lfm.get(f))
        if merged:
            wfm[f] = merged
    wfm["confidence"] = max(float(wfm.get("confidence", 0) or 0),
                            float(lfm.get("confidence", 0) or 0))

    # Section-merge loser body into winner (human-safe: never drop winner prose).
    # merge_sections_human_safe needs the STRUCTURED new_fields shape, so convert
    # the loser's sections via sections_to_fields (a raw sections dict merges nothing).
    human = bool(wfm.get("human_edited"))
    loser_sections = entity_body.parse_sections(lpar.body)
    loser_fields = entity_body.sections_to_fields(loser_sections)
    merged_sections = entity_body.merge_sections_human_safe(
        entity_body.parse_sections(wpar.body), loser_fields, human_edited=human)
    # Preserve any non-canonical (human-authored) loser sections too — the
    # structured merge only carries the canonical fields.
    for title, content in loser_sections.items():
        if title and title not in entity_body.CANONICAL_SECTIONS and title not in merged_sections:
            merged_sections[title] = content
    new_body = "\n\n".join(f"## {t}\n{c}" if t else c
                           for t, c in merged_sections.items() if c).strip()
    markdown_parser.write(wp, wfm, new_body)

    # Repoint edges.
    edges_file = memory_path / "graph_edges.yaml"
    repointed = 0
    if edges_file.exists():
        data = yaml.safe_load(edges_file.read_text()) or {}
        for e in data.get("edges", []):
            for end in ("source", "target"):
                if e.get(end) == loser_id:
                    e[end] = winner_id; repointed += 1
        edges_file.write_text(yaml.safe_dump(data, sort_keys=False))

    lp.unlink()
    return {"winner": winner_id, "merged_source_episodes": len(wfm.get("source_episodes", [])),
            "repointed_edges": repointed}
