"""The standard sections every project page shares (G141, TODO ruling 36 D4).

Owner 2026-10-22: "timeline, what has been done, what is expected and sections that can be standard throughout projects
in general. People that somehow can be involved to projects will be linked to them." Every project, software or not,
reads as the same six sections, in this order. Each is drawn on read from what its writers already keep — nothing here
writes a page, and no section is a second copy of another's data:

==========  =====================================================================  ==================================
section     what it shows                                                          who writes it
==========  =====================================================================  ==================================
overview    the page's Summary prose                                               Sleep; ``cicada_edit_page``
timeline    every dated thing on the project's timeline (ids into ``items``)       ``progress`` (events) + derived
done        done happenings and done milestones                                    ``progress`` (the only event writer)
expected    planned milestones, then the open backlog items                        ``progress``; ``backlog`` (G150)
design      the page's own ``## Design`` markdown, then its ``## Looks`` lines     the person / ``cicada_edit_page``;
                                                                                   ``design_refs`` (Looks only)
people      every person page linked to the project, by claims or events           Sleep's claims; ``progress``
==========  =====================================================================  ==================================
"""
from __future__ import annotations

import re
from pathlib import Path

from api.models.schemas import (MilestoneRow, ProjectPerson, ProjectSection, ProjectSectionEntry,
                                TimelineItem)
from api.services import backlog, entity_body
from api.services.claims import strip_claims_block

#: ``(key, title, written_by)`` in the order every project shows them.
SECTIONS = (
    ("overview", "Overview", ("sleep", "cicada_edit_page")),
    ("timeline", "Timeline", ("progress", "derived")),
    ("done", "Done", ("progress",)),
    ("expected", "Expected", ("progress", "backlog")),
    ("design", "Design", ("person", "cicada_edit_page", "design_refs")),
    ("people", "People involved", ("sleep", "progress")),
)
DESIGN_SECTION = "Design"
#: The entries one section carries; ``more`` counts the rest (the app opens the full list from ``items``/backlog).
ENTRY_CAP = 40
_LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)")


def _capped(entries: list[ProjectSectionEntry]) -> tuple[list[ProjectSectionEntry], int]:
    return entries[:ENTRY_CAP], max(0, len(entries) - ENTRY_CAP)


def _looks(markdown: str) -> list[ProjectSectionEntry]:
    out = []
    for line in (markdown or "").splitlines():
        m = _LINK.search(line)
        if m:
            out.append(ProjectSectionEntry(kind="look", ref=m.group(2), text=m.group(1).strip()))
    return out


def people(around: dict[str, dict], type_of, name_of, *, owner: str | None) -> list[ProjectPerson]:
    """Every person page around the project (claims and event participants, `project_timeline._merge_members`),
    most involved first; the owner is the project's own subject, never listed."""
    rows = []
    for eid, row in around.items():
        if eid == owner or type_of(eid) != "person":
            continue
        roles, phrases = row.get("roles"), row.get("phrases")
        role = roles.most_common(1)[0][0] if roles else (phrases.most_common(1)[0][0] if phrases else "")
        rows.append(ProjectPerson(id=eid, name=name_of(eid), role=role, count=int(row.get("count") or 0),
                                  last_seen=row.get("last")))
    rows.sort(key=lambda p: p.name)
    rows.sort(key=lambda p: p.last_seen or "", reverse=True)
    rows.sort(key=lambda p: -p.count)
    return rows


def build(memory_path: Path, stem: str, body: str, *, items: list[TimelineItem], milestones: list[MilestoneRow],
          persons: list[ProjectPerson]) -> list[ProjectSection]:
    sections = entity_body.parse_sections(strip_claims_block(body or ""))
    by_key: dict[str, ProjectSection] = {}

    summary = (sections.get("Summary") or sections.get("") or "").strip()
    by_key["overview"] = ProjectSection(key="overview", title="", markdown=summary or None)

    dated = [ProjectSectionEntry(kind="item", ref=i.id, text=i.text, day=i.day, status=i.state)
             for i in items if i.kind != "created"]
    by_key["timeline"] = ProjectSection(key="timeline", title="")
    by_key["timeline"].entries, by_key["timeline"].more = _capped(dated)

    done = [ProjectSectionEntry(kind="item", ref=i.id, text=i.text, day=i.day, status="done")
            for i in items if i.kind == "happening" and i.state == "done"]
    done += [ProjectSectionEntry(kind="milestone", ref=m.slug, text=m.name, day=m.done_on, status="done")
             for m in milestones if m.status == "done"]
    done.sort(key=lambda e: e.day or "", reverse=True)
    by_key["done"] = ProjectSection(key="done", title="")
    by_key["done"].entries, by_key["done"].more = _capped(done)

    expected = [ProjectSectionEntry(kind="milestone", ref=m.slug, text=m.name, day=m.target, status=m.status)
                for m in sorted((m for m in milestones if m.status == "planned"), key=lambda m: m.target or "~")]
    expected += [ProjectSectionEntry(kind="backlog", ref=i.id, text=i.title, day=i.updated[:10] or None,
                                     status=i.status)
                 for i in backlog.list_items(memory_path, stem) if i.status in backlog.OPEN_STATUSES]
    by_key["expected"] = ProjectSection(key="expected", title="")
    by_key["expected"].entries, by_key["expected"].more = _capped(expected)

    design = (sections.get(DESIGN_SECTION) or "").strip()
    by_key["design"] = ProjectSection(key="design", title="", markdown=design or None)
    by_key["design"].entries, by_key["design"].more = _capped(_looks(sections.get("Looks") or ""))

    by_key["people"] = ProjectSection(key="people", title="")
    by_key["people"].entries, by_key["people"].more = _capped(
        [ProjectSectionEntry(kind="person", ref=p.id, text=p.name, day=p.last_seen, status=p.role or None)
         for p in persons])

    out = []
    for key, title, writers in SECTIONS:
        section = by_key[key]
        section.title, section.written_by = title, list(writers)
        out.append(section)
    return out
