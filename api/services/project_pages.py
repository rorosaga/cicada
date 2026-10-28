"""Pages in this project (decision 10, owner 2026-10-28): the pages around a project plus the ones tied by hand.

Three layers, read at request time from what the bank already holds — pure, engine-free, writes nothing:

1. **said** — the automatic layer the detail already computes (``project_timeline._neighbours`` plus event
   participants): a page a claim on the project's tree names, or that takes part in one of its events. Only an
   explicit claim or participant counts, never co-occurrence (G141). The commons guard (R-PJ20) keeps a page that
   sits in a dozen projects out, as before.
2. **user / agent / proposed** — ``entities_added`` on the project page (``project_ownership.tie_page``, its one
   writer): the person's own tie, a trusted agent's, or another agent's proposal waiting for the person.
3. ``entities_removed`` — "Not part of it": the person's word, which wins over both layers above.

The project's own tree (its sub-projects) and the owner page are never listed here: the list shows sub-projects under
their parent and the owner is part of every project.
"""
from __future__ import annotations

from api.services import project_ownership

#: The wire carries at most this many rows (the panel shows 5 and opens the rest as a full view; ``pagesTotal`` is the
#: honest count).
MAX_ROWS = 200
_TIE_ORDER = {"proposed": 0, "user": 1, "agent": 2, "said": 3}


def build(bank, root: str, tree: list[str], around: dict[str, dict], commons: set[str], owner: str | None,
          member_fact) -> tuple[list, int, dict[str, int]]:
    """``(rows, total, counts)`` for the detail wire. ``around`` is the detail's merged neighbours (``{page: {count,
    last, phrases, roles?}}``); ``member_fact`` the cluster's one-fact helper."""
    from api.models.schemas import ProjectPageRow
    from api.services.project_timeline import _neg

    fm = bank.fm(root)
    skip = set(tree) | ({owner} if owner else set())
    removed = {bank.resolve(e) or e for e in project_ownership.pages(fm, project_ownership.PAGES_REMOVED_KEY)}
    rows: dict[str, ProjectPageRow] = {}
    order: dict[str, int] = {}

    def row(eid: str, tie: str, by: str | None, n: int) -> None:
        info = around.get(eid) or {}
        roles = info.get("roles")
        phrases = info.get("phrases")
        phrase = roles.most_common(1)[0][0] if roles else (phrases.most_common(1)[0][0] if phrases else "")
        rows[eid] = ProjectPageRow(id=eid, name=bank.name(eid), type=bank.type_of(eid), role_phrase=phrase,
                                   fact=member_fact(bank, eid), count=int(info.get("count") or 0),
                                   last_seen=info.get("last"), tie=tie, by=by)
        order[eid] = n

    # The hand ties first, newest first: what the person (or an agent) just added is what they look for.
    for n, entry in enumerate(reversed(project_ownership.page_entries(fm, project_ownership.PAGES_ADDED_KEY))):
        raw = entry if isinstance(entry, str) else str(entry.get("entity") or "")
        eid = bank.resolve(raw) or raw
        if eid in rows or eid in skip or eid in removed or not bank.live(eid):
            continue
        if isinstance(entry, str):
            row(eid, "user", "user", n)
        else:
            row(eid, "proposed" if entry.get("proposed") else "agent", str(entry.get("by") or "agent"), n)
    for eid in around:
        if eid in rows or eid in skip or eid in removed or eid in commons or not bank.live(eid):
            continue
        row(eid, "said", None, 0)
    counts = {k: 0 for k in _TIE_ORDER}
    for r in rows.values():
        counts[r.tie] += 1
    ordered = sorted(rows.values(), key=lambda r: (_TIE_ORDER[r.tie], order[r.id] if r.tie != "said" else 0,
                                                    -r.count, "" if r.last_seen is None else _neg(r.last_seen),
                                                    r.name.lower(), r.id))
    return ordered[:MAX_ROWS], len(ordered), {k: v for k, v in counts.items() if v}

