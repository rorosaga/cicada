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

from api.services import authorship, evidence

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


#: G179 groups (2026-10-28): in a group chat only the person's own lines are "the person's own words" — five other
#: members naming a thing in a busy group is their talk, not the person's, and must never promote it on its own.
OWNER_ONLY = frozenset({"user"})


def person_kinds(episode: dict | None) -> frozenset[str]:
    """Whose turns open an exchange and count as a person naming something, for this episode's record."""
    return OWNER_ONLY if (episode or {}).get("group") else PERSON_KINDS


def exchanges(text: str, *, override: str | None = None, gaps=(),
              persons: frozenset[str] = PERSON_KINDS) -> list[tuple[str, str]]:
    """The conversation as ``(person's words, whole exchange)`` pairs.

    An exchange opens at every turn that is a person's (the owner's, or another
    speaker's in a meeting) and runs through the replies after it. A document
    with no turn markers (a note, a shared text) is the person's own writing:
    each paragraph is one exchange. A saved item is not (``override`` is
    ``evidence.SAVE_KIND``, from ``authorship.of``): its title, site and
    fetched description are the page's, and only its reason or note sections
    are an exchange of the person's. ``persons`` (:func:`person_kinds`) narrows whose
    turns open one: in a group chat only the person's own. A record's filing labels (a folder, a list, a calendar —
    `evidence.label_ranges`) are blanked first: a label is never an exchange (owner 2026-10-29)."""
    text = evidence.mask_labels(text or "")
    turns = evidence.turns(text, override=override, gaps=gaps)
    if not turns:
        return []
    if len(turns) == 1 and turns[0].marker is None and turns[0].role in PERSON_KINDS:
        return [(p, p) for p in _PARAGRAPH.split(text) if p.strip()]
    out: list[list[str]] = []
    for turn in turns:
        words = text[turn.content_start:turn.end]
        if turn.role in _NOT_AN_EXCHANGE or turn.role not in persons:
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


#: Stage 1's mark on an entity this conversation names only in a filing label (:func:`label_only`): no mention at
#: all — Stage 2 drops it before anything counts a conversation (owner 2026-10-29).
LABEL_ONLY = "label_only"


def label_only(entity: dict, text: str) -> bool:
    """The conversation names ``entity`` only in its record's filing labels (`evidence.label_ranges`) — a bookmark's or
    a note's folder, a reminder's list, an event's calendar: a label the person filed things under, never their words
    and never a conversation for the 2+ rule (owner 2026-10-29)."""
    pattern = _pattern(_names(entity))
    if pattern is None or not evidence.label_ranges(text or ""):
        return False
    return bool(pattern.search(_fold(text))) and not pattern.search(_fold(evidence.mask_labels(text)))


def substantive(entity: dict) -> bool:
    """More than :data:`MIN_EXCHANGES` exchanges name it, and a person named it."""
    return int(entity.get("mention_exchanges") or 0) > MIN_EXCHANGES and bool(entity.get("named_by_person"))


def person_said(rel: dict) -> bool:
    """A relationship whose evidence is located in a person's own words — never one Stage 1 gave to someone else
    (``external:<name>``: a texted agent's, a group member's)."""
    if str(rel.get("observer") or "").startswith("external:"):
        return False
    return any(isinstance(ev, dict) and ev.get("kind") in PERSON_KINDS and int(ev.get("start", -1)) >= 0
               for ev in rel.get("evidence") or [])


def claim_cites_person(claim, *, located: bool = True) -> bool:
    """A stored claim (``claims.Claim``) whose evidence sits in a person's own words — never one whose observer is
    someone else (``external:<name>``: a texted agent's, a group member's, a one-to-one correspondent's), so another
    person's line in a group never reads as the person's (#499 review). ``located`` also asks for a real offset."""
    if str(getattr(claim, "observer", "") or "").startswith("external:"):
        return False
    for ev in getattr(claim, "evidence", None) or []:
        start = getattr(ev, "start", None)
        if getattr(ev, "kind", None) in PERSON_KINDS and (not located or (isinstance(start, int) and start >= 0)):
            return True
    return False


#: Ruling 43: an agent's own memory note (`agent_memory_notes`) is no conversation of its own for the 2+ rung.
AGENT_MEMORY_SOURCE = "agent-memory"


def conversation_keys(episode_ids, memory_path=None) -> set[str]:
    """The distinct conversations among ``episode_ids``, for the "2+ conversations" rung.

    A captured harness session counts as ``session:<id>``; an agent's memory note counts as the session that wrote it
    (``session:<origin_session_id>``, else its ``origin_episode``'s key) — so a session and its notes, two notes of one
    session, or a note and its project's index never make two — and a note with no session counts as nothing. An
    agent's saved note (ruling 50, ``authorship.agent_saved``) is the same: its session's key, else nothing — three
    notes one agent saved in one session are one conversation, never three. Every other id is its own conversation,
    as before; an id with no readable episode (an older pending line's) too."""
    from pathlib import Path

    from api.services import bank_index

    def header(eid: str) -> dict | None:
        if memory_path is None or not eid.startswith("ep_"):
            return None
        try:
            f = bank_index.file(Path(memory_path), "episodes", f"{eid}.md")
        except Exception:  # noqa: BLE001 — an unreadable header counts as the id itself
            return None
        return (f.frontmatter or {}) if f is not None else None

    def key(eid: str, depth: int = 0) -> str | None:
        fm = header(eid)
        if fm is None:
            return eid
        if str(fm.get("source") or "") == AGENT_MEMORY_SOURCE:
            sid = str(fm.get("origin_session_id") or "").strip()
            if sid:
                return f"session:{sid}"
            origin = str(fm.get("origin_episode") or "").strip()
            return key(origin, depth + 1) if origin and depth == 0 else None
        sid = str(fm.get("session_id") or "").strip()
        if sid and fm.get("capture_kind") == "transcript":
            return f"session:{sid}"
        if authorship.agent_saved(fm):
            return f"session:{sid}" if sid else None
        return eid

    out: set[str] = set()
    for eid in episode_ids:
        k = key(str(eid))
        if k:
            out.add(k)
    return out
