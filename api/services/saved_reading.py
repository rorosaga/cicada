"""How a model reads a saved item: its text is its author's, never the person's (G245, owner 2026-11-24).

A bookmark, a saved link, a saved-list post, a feed item and a tab group hold the page's or the post's own words — its
title, its site, its description — and, only in the sections the person's own words fill (``evidence.PERSON_SECTIONS``
plus a repeat save's ``## Note``), what the person said about it. ``authorship`` already labels every span of such an
episode ``page`` outside those sections. This module is the reading that follows from it, in one place so each
decision is a line to undo:

* **The source note** (:func:`note`): Stage 1 is told it is reading a saved item, whose "I" and "my" are the author's
  and whose "the user" is not the person, that nothing is known of why it was saved beyond the person's own sections,
  and to take at most :data:`MAX_ENTITIES` things from it.
* **The observer** (:func:`observer_for`): a claim whose located evidence is only the item's own words — or whose
  quote could not be located at all — is the author's, ``external:<the save's channel, else its site>``, never Cicada's
  own reading (``agent``) and never the person's. A claim with any span in a section of the person's own is theirs, as
  everywhere.
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


def no_words_of_his(episode: dict | None) -> bool:
    """A saved item the person said nothing about (G245, ruling 80): no reason, no why-answer, no note of theirs, no folder
    reason (the frontmatter marks ``history_index.PERSON_KEYS`` — the one definition of "this save carries their own
    words" that already decides whether a save is read as theirs). Read from the record alone, never the body, so the
    bank-wide readers of time (``episode_time``, one frontmatter pass) and the writers of Sleep and the 2+ rule
    (``promotion.conversation_keys``) all agree. A feed item is its publisher's and keeps ruling 39's own rule; a
    conversation about the save (``read_asked``) is a conversation of its own, never words in the save.

    Such a save is one source for the 2+ rule however many there are, and no mention: it starts no page's clock and
    refreshes none (:func:`episode_time.counts_as_activity`)."""
    from api.services import episode_time, history_index

    if not applies(episode) or episode_time.is_feed_item(episode):
        return False
    return not any((episode or {}).get(key) for key in history_index.PERSON_KEYS)


def holds_no_words(body: str | None) -> bool:
    """Does a saved link's body hold nothing but its record fields — a title, a link, a site, a day? Any section (the
    page's ``## Description``, a reason, a note) is words; a saved link with none has nothing for a model to read."""
    return _HEADING.search(body or "") is None


def nothing_to_read(episode: dict | None) -> bool:
    """A saved link Sleep has nothing to read in (ruling 80, G246): it applies, holds no section at all, carries no mark of
    the person's own words (a folder's reason is theirs, kept in the folder's own record) and is no tab group (whose body
    is its tabs). Stage 1 sends such an episode to no model: it is filed with no entities — a restated title would be
    all a call could write (ruling 62 measured it) — and what a public page says is read by the page read
    (``link_enrichment``), not here."""
    from api.services import episode_time, history_index

    if not applies(episode) or episode_time.is_feed_item(episode):
        return False
    ep = episode or {}
    if ep.get("source") in history_index.SAVE_SOURCES or not ep.get("url"):
        return False
    if any(ep.get(key) for key in history_index.PERSON_KEYS):
        return False
    return holds_no_words(str(ep.get("content") or ""))


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
    """The observer of a claim from a saved item, or ``None`` for the default reading: the item's author, unless a
    located span sits in a section of the person's own words (theirs, as everywhere) or in an agent's note (not the
    author alone). **A quote that cannot be located is the author's too** (ruling 80, G246): in a save that holds none
    of the person's words every fact is the post's, located or not; in one that holds a reason, a fact whose words the
    model could not point at is still far more likely the post's (the post is the bulk of the text), and the two ways to
    be wrong are not alike — labelled the author's, a belief of the person's is under-credited (and what they said in
    their own section lands as theirs whenever its quote is exact); labelled Cicada's or the person's, a stranger's
    words become a belief held in the person's memory. The safe side is the author's."""
    ranges = person_ranges(content) if ranges is None else ranges
    spans = [e for e in item.get("evidence") or [] if isinstance(e, dict) and e.get("kind") != "reasoning"]
    if any(_in_person(e.get("start"), ranges) for e in spans):
        return None
    if spans and any(e.get("kind") != "page" and e.get("kind") != "user" for e in spans):
        return None   # an agent's note backs it: not the item's author alone
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


#: What a model may write on an entity beyond its name: free text nothing locates in the save, so on the owner's entity
#: none of it can be told from the post's own words (:func:`_bind_owner`).
_OWNER_FREE_TEXT = ("summary", "description", "history_entries", "links", "open_questions", "tags", "application")


def holds(said: str, text) -> bool:
    """Does the person's folded text contain ``text`` as whole words (an alias "al" is not in "alpha")?"""
    from api.services.text_fold import fold

    key = fold(" ".join(str(text or "").split()))
    return bool(key) and re.search(r"(?<!\w)" + re.escape(key) + r"(?!\w)", said) is not None


def _bind_owner(entity: dict, said: str) -> None:
    """The owner's entity out of a save that holds some words of theirs: it carries only what those words contain.
    Their reason is not the post, but a model reads both and writes one summary and one list of facts — so a fact, an
    alias or a status quote stays only when the person's own text holds it (folded, whole); the free text that nothing
    locates (summary, history, links, open questions, tags, application) goes. What the person's words say still
    lands, as claims, through relationships and values whose located evidence sits in their section."""
    def held(text) -> bool:
        return holds(said, text)

    for field in _OWNER_FREE_TEXT:
        entity.pop(field, None)
    if isinstance(entity.get("key_facts"), list):
        entity["key_facts"] = [f for f in entity["key_facts"] if held(f)]
    if isinstance(entity.get("aliases"), list):
        entity["aliases"] = [a for a in entity["aliases"] if held(a)]
    status = entity.get("reading_status")
    if isinstance(status, dict) and not held(status.get("quote")):
        entity.pop("reading_status", None)


def _evidence_in_person(item: dict, ranges: list[tuple[int, int]]) -> bool:
    return any(isinstance(e, dict) and e.get("kind") != "reasoning" and _in_person(e.get("start"), ranges)
               for e in item.get("evidence") or [])


def clean(entities: list, relationships: list, values: list, content: str, *, owner: str | None) -> tuple[list, list, list]:
    """The owner guard and the bound, over what Stage 1 returned for one saved item (never mutates the lists it was
    given; entities it keeps are edited in place, as the caller already does).

    * Nothing about the owner unless the person's own section says it: an entity that is the owner (or a
      self-reference) is dropped when the save holds no words of theirs, and kept with only what their words contain
      (:func:`_bind_owner`) when it does; a relationship or value whose endpoint is
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
            _bind_owner(entity, said)
        elif str(entity.get("type") or "") == "person" and isinstance(entity.get("aliases"), list):
            entity["aliases"] = [a for a in entity["aliases"] if holds(said, a)]
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


#: A save's page at most this many links to other pages (ruling 80 (e)): the ones its text names in full.
MAX_LINKS = 5
#: The lines of a save's body that are the record's own fields, never its words (a link's address, a type, a day).
_RECORD_LINES = re.compile(r"^\*\*(URL|Source|Saved|Originally saved):\*\*.*$", re.MULTILINE)
#: A page name shorter than this is no name a text can state in full ("Go", "AI").
_MIN_NAME = 3


def named_in_full(content: str, pages: dict[str, tuple[str, list[str]]]) -> list[str]:
    """Which of ``pages`` (``{id: (name, aliases)}``) a saved item's text states in full: the page's exact title or one
    of its aliases, as whole words, folded for case and accents — never a first name, a part of a name or a co-mention.
    In the order the text names them, at most :data:`MAX_LINKS`; the record's own field lines (the link's address)
    are not text."""
    from api.services.text_fold import fold

    text = fold(_RECORD_LINES.sub("", content or ""))
    found: list[tuple[int, str]] = []
    for page_id, (name, aliases) in pages.items():
        best = None
        for label in (name, *aliases):
            key = fold(" ".join(str(label or "").split()))
            if len(key) < _MIN_NAME:
                continue
            m = re.search(r"(?<!\w)" + re.escape(key) + r"(?!\w)", text)
            if m is not None and (best is None or m.start() < best):
                best = m.start()
        if best is not None:
            found.append((best, page_id))
    return [page_id for _at, page_id in sorted(found)[:MAX_LINKS]]


def post_day(episode: dict):
    """The day the item's text was posted (``posted``, else a feed's ``published_at``) as a date, or ``None``. Never the
    day Cicada took it in."""
    from api.services import source_dates

    for key in ("posted", "published_at"):
        day = source_dates.stamp_day(episode.get(key)) if episode.get(key) else None
        if day is not None:
            return day
    return None


__all__ = ["CONNECTOR_TEXT_ORIGINS", "MAX_ENTITIES", "MAX_LINKS", "applies", "author", "author_observer", "clean",
           "holds_no_words", "named_in_full", "no_words_of_his", "nothing_to_read", "note", "observer_for", "person_ranges", "person_text", "post_day", "holds"]
