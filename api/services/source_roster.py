"""G61 (owner 2026-10-26) — every page's *where to check*, in one list: the sources the person added and the ones
their agents added, across the bank, for the Sources page's "Reading in your browser" area.

The owner: "the ones that are reading in my browser — I should be able to quickly add more, like manually add a link.
An agent can also do this ('add this source'); I told the agent and they added it here, and we can check there."

Read-only and engine-free: it walks the cached entity headers (``bank_index``), never fetches, never writes. The
writers stay where they are — ``fact_sources.add_source`` behind ``POST /entities/{id}/sources`` (the person) and
``cicada_add_source`` (an agent), ``fact_sources.change_source`` behind ``POST /entities/{id}/sources/change`` (a
removal leaves its ``sources_removed`` mark) — so one store keeps one writer.

Who counts: the person (``added_by: user``) and an agent named by a harness Cicada knows
(``source_overview.HARNESS_LABELS``). Cicada's own finds (``cicada``), a Sleep model's citation (a model id), the
engine-free where-to-check step (``agent``, which the inbox's grouped review already asks about) and a Contacts card
(``addressbook://``) are not listed here: they are on each page, and this list is what someone *added*.
"""
from __future__ import annotations

from pathlib import Path

from api.services import bank_index, fact_sources
from api.services.source_overview import HARNESS_LABELS, UNKNOWN

#: Bumped when a row's shape changes, so a client's ETag never serves an old shape.
SHAPE = "source-roster-1"
#: At most this many rows are served (newest first); ``total`` says how many there are.
LIMIT = 500

YOU = "you"
AGENT = "agent"


def who_of(source: dict) -> tuple[str, str | None] | None:
    """``("you", None)``, ``("agent", "<harness name>")``, or None for an entry this list leaves out."""
    if str(source.get("ref") or "").startswith("addressbook://"):
        return None
    by = str(source.get("added_by") or fact_sources.USER).strip() or fact_sources.USER
    if by == fact_sources.USER:
        return YOU, None
    if by != UNKNOWN and by in HARNESS_LABELS:
        return AGENT, HARNESS_LABELS[by]
    return None


def roster(memory_path: Path) -> list[dict]:
    """``[{entity_id, entity_name, entity_type, who, agent, added_by, ref, kind, predicate, added_at, proposed}]``,
    newest first. Only live pages (an archived or dropped page's sources are not offered for checking)."""
    rows: list[dict] = []
    for entry in bank_index.files(memory_path, "entities"):
        if not entry.path.name.endswith(".md"):
            continue
        fm = entry.frontmatter or {}
        if str(fm.get("status") or "").strip().lower() in ("archived", "dropped"):
            continue
        for source in fact_sources.as_sources(fm.get("sources")):
            who = who_of(source)
            if who is None:
                continue
            rows.append({
                "entity_id": entry.stem,
                "entity_name": str(fm.get("name") or entry.stem),
                "entity_type": str(fm.get("type") or ""),
                "who": who[0],
                "agent": who[1],
                "added_by": str(source.get("added_by") or fact_sources.USER),
                "ref": str(source.get("ref") or "").strip(),
                "kind": str(source.get("kind") or fact_sources.infer_kind(str(source.get("ref") or ""))),
                "predicate": source.get("predicate") or None,
                "added_at": str(source.get("added_at") or ""),
                "proposed": fact_sources.is_proposed(source),
            })
    rows.sort(key=lambda r: (r["added_at"], r["entity_id"], r["ref"]), reverse=True)
    return rows
