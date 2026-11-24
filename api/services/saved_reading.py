"""How a model reads a saved item: its text is its author's, never the person's (G245, owner 2026-11-24).

A bookmark, a saved link, a saved-list post, a feed item and a tab group hold the page's or the post's own words — its
title, its site, its description — and, only in the sections the person's own words fill (``evidence.PERSON_SECTIONS``
plus a repeat save's ``## Note``), what the person said about it. ``authorship`` already labels every span of such an
episode ``page`` outside those sections. This module is the reading that follows from it, in one place so each
decision is a line to undo:

* **The source note** (:func:`note`): Stage 1 is told it is reading a saved item, whose "I" and "my" are the author's
  and whose "the user" is not the person, that nothing is known of why it was saved beyond the person's own sections,
  and to take at most :data:`MAX_ENTITIES` things from it.
* **The observer** (:func:`observer_for`): a claim whose located evidence is only the item's own words is the
  author's — ``external:<the save's channel, else its site>`` — never Cicada's own reading (``agent``) and never the
  person's. A claim with any span in a section of the person's own is theirs, as everywhere.
* **The owner guard** (:func:`clean`): nothing a post says lands on the owner's page, nor as an alias on a person page,
  unless one of the person's own sections says it.
* **A bound** (:func:`clean`): at most :data:`MAX_ENTITIES` entities are taken from one save, and a save raises no
  question (Stage 1's ``ask_person`` is dropped): nobody talked about it.

Everything is derived from the episode's own record and body on read; nothing is stored. ``applies`` is the one
predicate: a saved item by ``authorship``, never a book's record (``book_marks`` reads those on their own terms), a
watched or listened day, nor an agent's report of a page it read.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from api.services import authorship, evidence

#: At most this many entities are taken from one saved item (invariant 3 of the saves plan).
MAX_ENTITIES = 8
#: Origins of a connector whose saved item IS a post's own text: the text is written as the post's description
#: (``RawItem.preview``), never as a note of the person's (``connectors/x.py``, ``connectors/pinterest.py``).
CONNECTOR_TEXT_ORIGINS = frozenset({"x-bookmarks", "pinterest"})

#: Sources an agent's report or a day's record writes — never a save, whatever door carried it.
_NOT_SAVES = frozenset({"video-watch", "page-read", "profile-read", "web-check", "source-check", "source-refresh",
                        "watch-history", "watch-history-month", "traces", "reading-history", "listening-history"})
_FIELD = re.compile(r"^\*\*(Channel|Site|URL):\*\*[ \t]*(.+?)[ \t]*$", re.MULTILINE)
_HEADING = re.compile(r"^## .*$", re.MULTILINE)
#: The person's own sections: ``evidence.PERSON_SECTIONS`` and a repeat save's ``## Note`` (an agent's behind an
#: ``assistant:`` marker is the agent's, :func:`person_ranges`).
_PERSON_HEADINGS = frozenset((*evidence.PERSON_SECTIONS, "## Note"))


def applies(episode: dict | None) -> bool:
    """Is this episode a saved item the model reads as someone else's words? From the episode's own record."""
    if not isinstance(episode, dict) or episode.get("book"):
        return False
    if str(episode.get("source") or "").strip().lower() in _NOT_SAVES:
        return False
    return authorship.of_episode(episode) == evidence.SAVE_KIND


def person_ranges(content: str) -> list[tuple[int, int]]:
    """``(start, end)`` of each section of the person's own words in a save's body: from just after its heading to the
    next ``## `` heading. By heading only — a line inside the page's description that happens to read like a turn
    marker is never the person's."""
    text = content or ""
    heads = [(m.start(), m.end(), m.group(0).strip()) for m in _HEADING.finditer(text)]
    out: list[tuple[int, int]] = []
    for i, (_start, end, heading) in enumerate(heads):
        if heading not in _PERSON_HEADINGS:
            continue
        stop = heads[i + 1][0] if i + 1 < len(heads) else len(text)
        first = next((ln for ln in text[end:stop].splitlines() if ln.strip()), "")
        if heading == "## Note" and (evidence._marker(first) or ("",))[0] == "assistant":
            continue   # an agent's note on a save: the agent's words, never the person's
        out.append((end, stop))
    return out


def person_text(content: str) -> str:
    """What the person's own sections say, joined; empty when the save holds none."""
    return "\n".join((content or "")[a:b] for a, b in person_ranges(content)).strip()


def _in_person(start, ranges: list[tuple[int, int]]) -> bool:
    return isinstance(start, int) and start >= 0 and any(a <= start < b for a, b in ranges)


def _field(content: str, name: str) -> str | None:
    for m in _FIELD.finditer(content or ""):
        if m.group(1) == name:
            return " ".join(m.group(2).split()) or None
    return None


def author(episode: dict, content: str) -> str | None:
    """Who the item's words are: the save's channel (the post's author, a video's channel), else its site, else its
    link's host, else the door it came through (a tab group names no single site). ``None`` when the record names none."""
    for label in (_field(content, "Channel"), _field(content, "Site")):
        if label:
            return label
    url = _field(content, "URL") or str(episode.get("url") or "").strip()
    host = (urlsplit(url).hostname or "").lower() if url else ""
    return host.removeprefix("www.") or str(episode.get("origin") or "").strip() or None


def author_observer(episode: dict, content: str) -> str | None:
    """``external:<slug>`` for the item's author (:func:`author`), or ``None`` when none is named. Per author, because
    a belief's slot is keyed by its observer: two authors' different claims never share one."""
    from api.services.id_utils import sanitize_id

    name = author(episode, content)
    slug = sanitize_id(name) if name else ""
    return f"external:{slug}" if slug and slug != "unnamed" else None


def note(episode: dict, content: str) -> str | None:
    """The source note put before each chunk of a saved item (:func:`applies`), else ``None``. Cicada's own words,
    never the item's (the model sees the chunk and these notes, never the frontmatter)."""
    if not applies(episode):
        return None
    who = author(episode, content)
    by = f", written by {who}" if who else ""
    own = ""
    if person_ranges(content):
        own = (' The sections headed "## Saved because", "## Why it was saved" and "## User note" (and a "## Note" '
               "that does not start with \"assistant:\") are the person's own words; every other line is the author's.")
    return (f"[Source: an item the person kept or follows (a bookmark, a link, a saved post, a feed entry){by}. Its text is the "
            "page's or the author's words, never the person's: \"I\", \"we\" and \"my\" in it are the author, and "
            f"\"the user\" in it is not the person.{own} Nothing more is known of why the person kept it. Take "
            "only what it is about and what it says about the things it names; say nothing about the person. "
            f"Name at most {MAX_ENTITIES} entities, and ask the person nothing.]\n\n")


def observer_for(item: dict, episode: dict, content: str, ranges: list[tuple[int, int]] | None = None) -> str | None:
    """The observer of a claim from a saved item, or ``None`` for the default reading: the item's author when every
    located span is the item's own text (or the claim has no located span and the person said nothing in it); nothing
    special when any span sits in a section of the person's own words, or in an agent's note."""
    ranges = person_ranges(content) if ranges is None else ranges
    spans = [e for e in item.get("evidence") or [] if isinstance(e, dict) and e.get("kind") != "reasoning"]
    if any(_in_person(e.get("start"), ranges) for e in spans):
        return None
    if spans and any(e.get("kind") != "page" and e.get("kind") != "user" for e in spans):
        return None   # an agent's note backs it: not the item's author alone
    if not spans and ranges:
        return None   # unlocated, and the person did say something in it: Cicada's own reading, as before
    return author_observer(episode, content)


def _names(entity: dict) -> set[str]:
    from api.services.text_fold import fold

    aliases = entity.get("aliases") if isinstance(entity.get("aliases"), list) else []
    return {k for k in (fold(" ".join(str(n or "").split())) for n in (entity.get("name"), *aliases)) if k}


def _is_owner_name(name, owner: str | None) -> bool:
    from api.services.owner_identity import is_self_reference
    from api.services.text_fold import fold

    text = " ".join(str(name or "").split())
    return bool(text) and ((bool(owner) and fold(text) == fold(owner)) or is_self_reference(text))


def _evidence_in_person(item: dict, ranges: list[tuple[int, int]]) -> bool:
    return any(isinstance(e, dict) and e.get("kind") != "reasoning" and _in_person(e.get("start"), ranges)
               for e in item.get("evidence") or [])


def clean(entities: list, relationships: list, values: list, content: str, *, owner: str | None) -> tuple[list, list, list]:
    """The owner guard and the bound, over what Stage 1 returned for one saved item (never mutates the lists it was
    given; entities it keeps are edited in place, as the caller already does).

    * Nothing about the owner unless the person's own section says it: an entity that is the owner (or a
      self-reference) is dropped when the save holds no words of theirs; a relationship or value whose endpoint is
      the owner stays only when its located evidence sits in one of their sections.
    * A person page gains no alias from a post: an alias stays only when the person's own words contain it.
    * ``ask_person`` is dropped (nobody talked about it), and at most :data:`MAX_ENTITIES` distinct names are kept —
      the ones the item's relationships and facts lean on most — with what rests on a dropped name.
    """
    from api.services.text_fold import fold

    ranges = person_ranges(content)
    said = fold(person_text(content))
    kept: list[dict] = []
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        entity.pop("ask_person", None)
        if _is_owner_name(entity.get("name"), owner):
            if not ranges:
                continue
        elif str(entity.get("type") or "") == "person" and isinstance(entity.get("aliases"), list):
            entity["aliases"] = [a for a in entity["aliases"] if fold(str(a or "")) and fold(str(a)) in said]
        kept.append(entity)

    def endpoint_ok(name, item: dict) -> bool:
        return not _is_owner_name(name, owner) or _evidence_in_person(item, ranges)

    rels = [r for r in relationships if isinstance(r, dict)
            and endpoint_ok(r.get("source"), r) and endpoint_ok(r.get("target"), r)]
    vals = [v for v in values if isinstance(v, dict) and endpoint_ok(v.get("entity"), v)]
    return _cap(kept, rels, vals)


def _cap(entities: list[dict], relationships: list[dict], values: list[dict]) -> tuple[list, list, list]:
    """Keep the :data:`MAX_ENTITIES` distinct names the item leans on most (relationships and values naming them, then
    their facts); everything resting on another name goes with it."""
    from api.services.text_fold import fold

    def key(entity: dict) -> str:
        return fold(" ".join(str(entity.get("name") or "").split()))

    distinct = list(dict.fromkeys(k for k in (key(e) for e in entities) if k))
    if len(distinct) <= MAX_ENTITIES:
        return entities, relationships, values
    names = {key(e): _names(e) for e in entities}
    weight = dict.fromkeys(distinct, 0)

    def lean(*labels) -> None:
        for label in labels:
            hit = fold(" ".join(str(label or "").split()))
            for k in distinct:
                if hit and hit in names[k]:
                    weight[k] += 1

    for r in relationships:
        lean(r.get("source"), r.get("target"))
    for v in values:
        lean(v.get("entity"))
    for e in entities:
        facts = e.get("key_facts")
        weight[key(e)] = weight.get(key(e), 0) + (len(facts) if isinstance(facts, list) else 0) / 100
    keep = set(sorted(distinct, key=lambda k: (-weight[k], distinct.index(k)))[:MAX_ENTITIES])
    gone = set().union(*(names[k] for k in distinct if k not in keep)) - set().union(*(names[k] for k in keep))
    entities = [e for e in entities if key(e) in keep]
    relationships = [r for r in relationships
                     if fold(" ".join(str(r.get("source") or "").split())) not in gone
                     and fold(" ".join(str(r.get("target") or "").split())) not in gone]
    values = [v for v in values if fold(" ".join(str(v.get("entity") or "").split())) not in gone]
    return entities, relationships, values


def post_day(episode: dict):
    """The day the item's text was posted (``posted``, else a feed's ``published_at``) as a date, or ``None``. Never the
    day Cicada took it in."""
    from api.services import source_dates

    for key in ("posted", "published_at"):
        day = source_dates.stamp_day(episode.get(key)) if episode.get(key) else None
        if day is not None:
            return day
    return None


__all__ = ["CONNECTOR_TEXT_ORIGINS", "MAX_ENTITIES", "applies", "author", "author_observer", "clean", "note",
           "observer_for", "person_ranges", "person_text", "post_day"]
