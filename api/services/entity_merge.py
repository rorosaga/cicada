# api/services/entity_merge.py
"""Merge two rich entity pages into one (the G21 primitive the inbox lacks).

Unions list frontmatter, section-merges bodies (human-prose-safe), repoints
graph_edges.yaml endpoints loser->winner, deletes the loser. Reversible via git.
"""
from __future__ import annotations
from pathlib import Path
import yaml
from api.services import markdown_parser, entity_body
from api.services.claims import parse_claims, write_claims, strip_claims_block

_LIST_FIELDS = ("source_episodes", "tags", "related", "aliases")


def _union(a, b):
    seen, out = set(), []
    for x in list(a or []) + list(b or []):
        if x not in seen:
            seen.add(x); out.append(x)
    return out


def merge_entities(memory_path: Path, loser_id: str, winner_id: str,
                   *, author: str = "user") -> dict:
    if loser_id == winner_id:
        raise ValueError(f"cannot merge an entity into itself: {winner_id}")
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
    # Preserve the winner's ```claims block verbatim across the merge — capture it
    # before merging, then merge on claims-stripped bodies so the fence can never
    # end up mid-section. (The loser body is also stripped so a loser claims
    # fence doesn't leak in as prose; unioning the loser's claims into the winner
    # is a deliberate follow-up, not attempted here.)
    winner_claims = parse_claims(wpar.body)
    human = bool(wfm.get("human_edited"))
    loser_sections = entity_body.parse_sections(strip_claims_block(lpar.body))
    loser_fields = entity_body.sections_to_fields(loser_sections)
    merged_sections = entity_body.merge_sections_human_safe(
        entity_body.parse_sections(strip_claims_block(wpar.body)), loser_fields, human_edited=human)
    # Preserve any non-canonical (human-authored) loser sections too — the
    # structured merge only carries the canonical fields. If the winner
    # already has a same-titled custom section with different content,
    # append rather than silently dropping the loser's content.
    for title, content in loser_sections.items():
        if not title or title in entity_body.CANONICAL_SECTIONS:
            continue
        content = (content or "").strip()
        if not content:
            continue
        existing = (merged_sections.get(title) or "").strip()
        if not existing:
            merged_sections[title] = content
        elif content not in existing:
            merged_sections[title] = existing + "\n\n" + content
        # identical content: keep winner's, no dup
    new_body = "\n\n".join(f"## {t}\n{c}" if t else c
                           for t, c in merged_sections.items() if c).strip()
    if winner_claims:
        new_body = write_claims(new_body, winner_claims)
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
        # Repointing can create self-loops (loser->winner edges both ends now
        # winner) or duplicates (winner already had the same edge). Drop both.
        seen = set()
        cleaned = []
        for e in data.get("edges", []):
            if e.get("source") == e.get("target"):
                continue  # drop self-loop created by repointing
            key = (e.get("source"), e.get("target"), e.get("label"))
            if key in seen:
                continue  # drop duplicate
            seen.add(key)
            cleaned.append(e)
        data["edges"] = cleaned
        edges_file.write_text(yaml.safe_dump(data, sort_keys=False))

    lp.unlink()
    return {"winner": winner_id, "merged_source_episodes": len(wfm.get("source_episodes", [])),
            "repointed_edges": repointed}
