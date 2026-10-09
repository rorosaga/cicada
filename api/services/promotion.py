"""How the promotion rule is measured (CLAUDE.md "Entity promotion").

A page needs **2+ conversations**, OR substantive discussion (**more than 3
exchanges**) in one, OR an **explicit link to an existing high-confidence
page** other than the owner's. Before this module the second and third rungs
were proxies that almost every extraction cleared, so 70% of a clean run's
pages rested on one conversation (owner bank, 2026-10-09):

* "more than 3 exchanges" was never counted. It was guessed from what the model
  wrote: confidence >= 0.75 with a 200-character description, or two history
  entries, or two relationships in the conversation. The extraction prompt
  defines confidence as certainty, not importance, asks for a 3-5 sentence
  summary and for every relationship — so a function in the assistant's code
  example cleared it as easily as the person's own project.
* "an explicit link" was any relationship the model drew to any page at 0.6 —
  which, once a bank has pages, is nearly every name — even one only the
  assistant's answer made.

Now Stage 1 counts, on the conversation it read (:func:`measure`, no model):
how many exchanges name the thing, and whether the person (or another person
in the room) named it in their own words. Stage 2 (`entity_resolver`) promotes
a one-conversation name only on more than :data:`MIN_EXCHANGES` exchanges that
include the person's own words, or on a relationship to an existing page whose
evidence is located in the person's words (:func:`person_said`). Anything
below the bar is not lost: it waits in the pending store with what was said
about it (`pending_store`), and its next conversation promotes it.
"""
from __future__ import annotations

import re
import unicodedata

from api.services import evidence

#: "more than 3 exchanges" — the rule's own number.
MIN_EXCHANGES = 3

#: Whose words make a name the person's: their own turn, or another person's
#: in a meeting (`speaker:<label>:`). Never the model's, a video's or a
#: quoted document's.
PERSON_KINDS = frozenset({"user", "speaker"})
_NOT_AN_EXCHANGE = frozenset({"assistant", "media", "page", evidence.GAP_KIND})
_PARAGRAPH = re.compile(r"\n\s*\n")


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text or "")
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def _names(entity: dict) -> list[str]:
    name = str(entity.get("name") or "").strip()
    out = [name, re.sub(r"\s*\([^)]*\)\s*$", "", name)]
    out += [str(a) for a in entity.get("aliases") or [] if a]
    if str(entity.get("type") or "") == "person":
        first = name.split(" ")[0] if name else ""
        if len(first) >= 3:
            out.append(first)
    seen, names = set(), []
    for n in out:
        folded = _fold(n).strip()
        if len(folded) >= 2 and folded not in seen:
            seen.add(folded)
            names.append(folded)
    return names


def _pattern(names: list[str]) -> re.Pattern | None:
    if not names:
        return None
    alternatives = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    return re.compile(rf"(?<![\w]){alternatives}(?![\w])")


def exchanges(text: str, *, override: str | None = None, gaps=()) -> list[tuple[str, str]]:
    """The conversation as ``(person's words, whole exchange)`` pairs.

    An exchange opens at every turn that is a person's (the owner's, or another
    speaker's in a meeting) and runs through the replies after it. A document
    with no turn markers (a note, a saved text) is the person's own writing:
    each paragraph is one exchange."""
    turns = evidence.turns(text or "", override=override, gaps=gaps)
    if not turns:
        return []
    if len(turns) == 1 and turns[0].marker is None and turns[0].role in PERSON_KINDS:
        return [(p, p) for p in _PARAGRAPH.split(text) if p.strip()]
    out: list[list[str]] = []
    for turn in turns:
        words = text[turn.content_start:turn.end]
        if turn.role in _NOT_AN_EXCHANGE:
            if out:
                out[-1][1] += "\n" + words
            else:
                out.append(["", words])
        else:
            out.append([words, words])
    return [(person, whole) for person, whole in out]


def measure(entity: dict, units: list[tuple[str, str]]) -> tuple[int, bool]:
    """``(exchanges that name it, whether a person named it)`` for one entity."""
    pattern = _pattern(_names(entity))
    if pattern is None:
        return 0, False
    count, named = 0, False
    for person, whole in units:
        if pattern.search(_fold(whole)):
            count += 1
            if person and pattern.search(_fold(person)):
                named = True
    return count, named


def substantive(entity: dict) -> bool:
    """More than :data:`MIN_EXCHANGES` exchanges name it, and a person named it."""
    return int(entity.get("mention_exchanges") or 0) > MIN_EXCHANGES and bool(entity.get("named_by_person"))


def person_said(rel: dict) -> bool:
    """A relationship whose evidence is located in a person's own words."""
    return any(isinstance(ev, dict) and ev.get("kind") in PERSON_KINDS and int(ev.get("start", -1)) >= 0
               for ev in rel.get("evidence") or [])
