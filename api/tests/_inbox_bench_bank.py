"""A synthetic bank at the owner's inbox scale (2026-10-17 inbox lag): ~4,700 entity pages and ~900 inbox files with
the measured kind mix (661 merge suggestions, 70 conflicts, 69 clarifications, 63 decay, 46 normalization, 4 removal),
most of them about a subject that is gone (merged away, renamed, archived) — the case that made ``load_inbox`` list
``entities/`` once per item. Never collected by pytest (underscore prefix). Placeholder names only; nothing reads a
real bank, ``~/.cicada`` or the network."""
from __future__ import annotations

from pathlib import Path

from api.services import markdown_parser, predicates

KINDS = (["merge_suggestion"] * 661 + ["conflict"] * 70 + ["clarification"] * 69 + ["decay"] * 63
         + ["normalization"] * 46 + ["removal"] * 4)


def _page(memory: Path, eid: str, *, status: str = "active", etype: str = "concept") -> None:
    body = (f"## Summary\n{eid.replace('-', ' ').title()} is a synthetic fixture page. " * 6
            + "\n\n## Notes\n" + "- a placeholder note about the fixture\n" * 12)
    markdown_parser.write(memory / "entities" / f"{eid}.md", {
        "name": eid.replace("-", " ").title(), "type": etype, "status": status, "confidence": 0.6,
        "created": "2026-01-01", "last_referenced": "2026-09-01", "decay_rate": 0.05,
        "source_episodes": [f"ep_2026-09-01_{n:03d}" for n in range(1, 4)], "tags": ["fixture"],
        "related": [f"thing-{(hash(eid) + k) % 4000:04d}" for k in range(3)], "version": 3,
    }, body)


def build(memory: Path, *, pages: int = 4700, items: int | None = None) -> Path:
    """Write the bank under ``memory`` and return it. ``items`` truncates the kind mix (default: all 913)."""
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True, exist_ok=True)
    predicates.install_predicate_map(memory)
    for n in range(pages):
        _page(memory, f"thing-{n:04d}", status="archived" if n % 37 == 0 else "active",
              etype=("person", "project", "concept", "tool")[n % 4])
    kinds = KINDS[: items or len(KINDS)]
    for i, kind in enumerate(kinds):
        n = (i * 13) % pages
        # Roughly two in three items name a subject with no page by any spelling (a merge took it, a rename moved
        # it): the miss that used to scan the directory. The rest name a live page by slug or by display name, and
        # every 37th of those an archived one.
        if i % 3:
            entity_id = f"Gone Subject {i:04d}" if i % 2 else f"gone-subject-{i:04d}"
        else:
            entity_id = f"thing-{n:04d}" if i % 2 else f"Thing {n:04d}"
        fm = {"kind": kind, "status": "pending", "priority": round(0.3 + (i % 7) / 10, 2),
              "entity_id": entity_id, "entity_name": entity_id.replace("-", " ").title(),
              "title": f"Question {i:04d} about {entity_id}", "created_date": f"2026-09-{1 + i % 28:02d}"}
        if kind == "merge_suggestion":
            fm["merge_target_hint"] = f"thing-{(n + 1) % pages:04d}"
            fm["suggested_confidence"] = 0.7
        elif kind == "normalization":
            fm["claim_id"] = f"c-{i:04d}"
            fm["covered_claims"] = [{"entity_id": f"gone-subject-{i + 1:04d}", "claim_id": f"c-{i + 1:04d}"},
                                    {"entity_id": f"thing-{(n + 2) % pages:04d}", "claim_id": f"c-{i + 2:04d}"}]
        elif kind == "clarification" and i % 5 == 0:
            fm["asks"] = "name"
        if kind in ("merge_suggestion", "conflict", "clarification", "removal"):
            # The served payload averages ~2 KB an item: a few described options and a paragraph of context.
            fm["options"] = [{"key": key, "label": f"Option {key} for question {i:04d}",
                              "description": "A placeholder description of what this answer would change. " * 3}
                             for key in ("a", "b", "c")]
            fm["source_episode"] = f"ep_2026-09-{1 + i % 28:02d}_001"
        body = f"Context for question {i:04d}. " + "A placeholder sentence of context for the card. " * 20
        markdown_parser.write(memory / "inbox" / f"inbox-{i + 1:04d}.md", fm, body)
    return memory
