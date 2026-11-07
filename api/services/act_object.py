"""What an act on an application is about: the event, never the place it is held or who runs it (ruling 42, 2026-10-28).

2026-10-28 trace (the synthetic new-user persona): the person said "I signed up for an <event> at the <venue>". Stage 1
wrote two relationships from the person's own sentence — "<person> signed up for <event>" (right) and "<person> signed
up for <venue>" (wrong: nobody signed up for a makerspace) — and the Reader showed both as "You said". The class: an
act on a specific event, program or opening (applied, registered, signed up, enrolled, RSVP'd, submitted) pinned on
its venue or organiser. Ruling 42 already says where each belongs: the event carries the application, the venue or
organiser keeps a link.

So the act's object is read from the sentence its evidence was located in (G118's span, never a guess):

* the act word (:data:`application_page.DONE`) comes before the name;
* between them sits another object — "for **an <event>** at the" — and the name follows a venue or organiser word
  (:data:`MARKER`: at, in, hosted / run / organised by, by, with, from, through, via; Spanish en, con).

"I registered for the <event>" and "I applied to <program>" have nothing between the act and the name: the name is the
object, kept. "<venue> is where I signed up" and a sentence with no act word are not judged. With no located span the
relationship is kept (G118: an unlocatable quote is reasoning, and the claim is still written).

A venue relationship is never silently lost: when the same extraction has the act on the real object (the name sitting
between the act and the marker), it becomes "<event> at / run by / with <venue>" — the link ruling 42 gives the
venue, with the person's span — or is dropped as a duplicate of one already there; otherwise it says what the sentence
says: "<person> signed up for something at <venue>". A label that already names where ("signed up for workshop at"
<venue>, :data:`WHERE_LABEL`, the variant a 2026-10-28 replay wrote 3 times in 5) is true as written and is kept,
except beside the act on an event its own words name ("workshop"), where it folds the same way. The event is only ever
looked for in this act's own clause — from the last act word before the target — so "I applied to <X> and registered
my startup in <place>" never becomes "<X> at <place>". Pure: no I/O, no model.
"""
from __future__ import annotations

import re

from api.services import application_page
from api.services.project_birth import _name_pattern

#: A label that is exactly an act on an application: "signed up for", "registered_for", "applied to", "enrolled in".
#: Never "applied patterns from" (another sense of the word) or "applied for an internship at" (the label already says
#: what the act was on, and its target is the organiser by design).
ACT_LABEL = re.compile(
    r"^\s*(?:applied|registered|signed up|rsvp'?d|enrol(?:l)?ed|submitted|requested to join)"
    r"(?:\s+(?:to|for|in|into|at|on))?\s*$", re.IGNORECASE)

#: A label that already says where: "signed up for workshop at", "registered for a class with". True as written, but
#: when the same extraction holds the act on the event itself it repeats it with the venue as the object.
WHERE_LABEL = re.compile(
    r"^\s*(?:applied|registered|signed up|rsvp'?d|enrol(?:l)?ed|submitted|requested to join)\b.*?\s"
    r"(?P<m>held at|hosted (?:at|by)|run by|organi[sz]ed by|put on by|offered by|at|in|by|with|from|through|via)\s*$",
    re.IGNORECASE)
#: The act at a label's start.
ACT_WORDS = re.compile(r"^\s*(?:applied|registered|signed up|rsvp'?d|enrol(?:l)?ed|submitted|requested to join)",
                       re.IGNORECASE)
#: A venue or organiser word right before the name (an article allowed): the name is where, or by whom, never what.
MARKER = re.compile(
    r"(?<!\w)(?P<m>held at|hosted (?:at|by)|run by|organi[sz]ed by|put on by|offered by|at|in|by|with|from|through|via|"
    r"en|con)\s+(?:(?:the|a|an|el|la|los|las|un|una)\s+)?$", re.IGNORECASE)
#: How the act reaches its object ("for", "up for", "to"), stripped before asking whether another object sits there.
_LEAD = re.compile(r"^\s*(?:up\s+)?(?:for|to|into|onto|on|in|para|a)?\s*(?:(?:the|a|an|el|la|un|una)\s+)?",
                   re.IGNORECASE)
#: The relationship a venue gets from the event, by the marker that named it.
LINK = {"at": "at", "held at": "held at", "hosted at": "held at", "in": "at", "en": "at",
        "with": "with", "con": "with", "by": "run by", "run by": "run by", "hosted by": "hosted by",
        "organised by": "organised by", "organized by": "organized by", "put on by": "put on by",
        "offered by": "offered by", "from": "offered by", "through": "offered by", "via": "offered by"}
_SENTENCE = re.compile(r"[^.!?\n]+[.!?]?")


def _words(label: str) -> str:
    return " ".join(str(label or "").replace("_", " ").replace("-", " ").split())


def is_act(label: str) -> bool:
    return bool(ACT_LABEL.search(_words(label)))


def venue(sentence: str, name: re.Match) -> str | None:
    """The venue or organiser word ``name`` follows in ``sentence`` when an act on another object comes first
    ("signed up for an <event> **at** the <name>"), else ``None`` — the name is the act's object, or not judged."""
    before = sentence[:name.start()]
    acts = list(application_page.DONE.finditer(before))
    if not acts:
        return None
    middle = before[acts[-1].end():]
    marker = MARKER.search(middle)
    if marker is None:
        return None
    between = middle[:marker.start()]
    between = between[_LEAD.match(between).end():]
    return " ".join(marker.group("m").lower().split()) if re.search(r"\w", between) else None


def _sentence_at(body: str, start: int) -> tuple[int, str]:
    for s in _SENTENCE.finditer(body, max(0, body.rfind("\n", 0, start) + 1)):
        if s.start() <= start < s.end():
            return s.start(), s.group(0)
    return start, ""


#: Words a label's middle never names an event by.
_STOP = frozenset({"the", "a", "an", "my", "our", "his", "her", "their", "for", "to", "in", "into", "on", "up", "and",
                   "of", "at", "with", "by", "from"})


def _content(text: str) -> set[str]:
    return {w for w in re.findall(r"\w+", str(text or "").lower()) if len(w) >= 3 and w not in _STOP}


def _clause(sentence: str, name: re.Match) -> str:
    """The words from the last act before ``name`` up to it: the only place the act's own object can be. Another
    act earlier in the sentence ("I applied to <X> and registered my startup in <place>") is a different clause."""
    before = sentence[:name.start()]
    acts = list(application_page.DONE.finditer(before))
    return before[acts[-1].start():] if acts else ""


def _located(rel: dict, body: str, pattern: re.Pattern) -> list[tuple[str, re.Match]] | None:
    """``[(sentence, target match)]`` for every located span, or ``None`` when a span never names the target."""
    out = []
    for ev in rel.get("evidence") or []:
        if not isinstance(ev, dict) or ev.get("kind") == "reasoning":
            continue
        start, end = ev.get("start"), ev.get("end")
        if not (isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(body)):
            continue
        lo, hit = start, None
        while lo < end and hit is None:
            s0, sentence = _sentence_at(body, lo)
            if not sentence:
                break
            name = pattern.search(sentence)
            if name is not None:
                hit = (sentence, name)
            lo = s0 + len(sentence)
        if hit is None:
            return None
        out.append(hit)
    return out


def placed(rel: dict, body: str) -> tuple[str, str, bool, set[str]] | None:
    """``(marker, the act's clause up to the target, labelled, label words)`` when ``rel`` claims an act on its
    target and every located span's sentence names the target as a venue or organiser, or its label already says so
    (``labelled``, with the content words the label names the event by), else ``None``."""
    label = _words(rel.get("label"))
    pattern = _name_pattern({"name": str(rel.get("target") or ""), "aliases": []})
    where = WHERE_LABEL.match(label)
    if where is not None:
        middle = _content(label[:where.start("m")]) - _content(ACT_WORDS.search(label).group(0))
        spans = _located(rel, body, pattern) if pattern is not None else None
        clause = _clause(*spans[0]) if spans else ""
        return " ".join(where.group("m").lower().split()), clause, True, middle
    if not is_act(label) or pattern is None:
        return None
    spans = _located(rel, body, pattern)
    if not spans:
        return None                 # the span never names the target, or none is located: not judged
    found = None
    for sentence, name in spans:
        marker = venue(sentence, name)
        if marker is None:
            return None             # one span where the target is the object keeps it
        found = (marker, _clause(sentence, name), False, set())
    return found


def hold(relationships: list[dict], body: str) -> int:
    """Move every act pinned on a venue or organiser to where it belongs, in place (module docstring). Returns how many
    relationships changed or were dropped."""
    changed, keep = 0, []
    for rel in relationships:
        where = placed(rel, body) if isinstance(rel, dict) else None
        if where is None:
            keep.append(rel)
            continue
        marker, clause, labelled, middle = where
        source = _words(rel.get("source")).lower()
        # The event is another act of the same person on a thing named in THIS act's clause, before the target; a
        # label that already says where must name that thing itself ("workshop" in "signed up for workshop at").
        event = next((r for r in relationships
                      if r is not rel and isinstance(r, dict) and is_act(r.get("label"))
                      and _words(r.get("source")).lower() == source
                      and (p := _name_pattern({"name": str(r.get("target") or ""), "aliases": []})) is not None
                      and p.search(clause)
                      and (not labelled or middle & _content(r.get("target")))), None)
        if event is None:
            if not labelled:            # a label that already says where is true as written
                rel["label"] = f"{_words(rel.get('label'))} something {marker}"
                changed += 1
            keep.append(rel)
            continue
        changed += 1
        link = LINK.get(marker, "held at")
        if any(isinstance(r, dict) and _words(r.get("source")).lower() == _words(event.get("target")).lower()
               and _words(r.get("target")).lower() == _words(rel.get("target")).lower() for r in relationships):
            continue                # the event already links the venue: a duplicate
        rel["source"], rel["label"] = event.get("target"), link
        for day in ("starts", "ends", "at"):
            rel.pop(day, None)
        keep.append(rel)
    relationships[:] = keep
    return changed
