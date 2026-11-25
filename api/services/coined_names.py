"""Is a name something a conversation says? (2026-11-25, G148, ruling 41a, ruling 73)

Stage 1 returns each thing with a ``name`` it wrote itself. Measured on a real bank (real values redacted), of the 185 open
"Is <name> the same as <page>?" questions about a name with no page, 107 named a thing in no text of the conversation they
were raised from — "<Feature> redesign", "<Project> extraction worker", "Daily <thing> PDF": a description the model wrote as
if it were a name (`name_revisit.unsaid`, the check that retires such a question). This module is the one reading of "said":
where in a conversation a name is, by the turn's author, never with a model.

* :func:`located` — one name in one text: exact, whitespace, case-insensitive (`evidence.locate`), and, only to say MORE was said,
  the folded whole-word check of `question_revisit._hits` (a hyphen, an accent or a case never makes a name unsaid). Never fuzzy.
* :func:`said_in` — ``"person"`` (in a turn the person's own, or another person's in a meeting), ``"others"`` (in the text, in an
  assistant's turn, an agent's note, a record's own text, never the person's) or ``"nowhere"``. Over a name and its aliases.
* :func:`words_of` — how many of a name's words the text says: ``"all"`` (recombined: the words are there, the phrase is not),
  ``"some"``, ``"none"`` (a translation, a paraphrase, a description). Measurement only.

Nothing here writes, and nothing here decides what a nameless thing becomes: that is the caller's (`entity_extractor` marks, Stage 2
holds, `coined_tend` moves).
"""
from __future__ import annotations

import re
from typing import Iterable

from api.services import evidence, text_fold

PERSON = "person"
OTHERS = "others"
NOWHERE = "nowhere"

#: Stage 1's mark on an entity whose name is a label (:func:`coined`): computed from the conversation, never the model's, and
#: popped by Stage 2 before anything is written. Same shape as `promotion.LABEL_ONLY`.
COINED = "coined"

#: The types a described thing takes. A company, a place, a tool or a person the model names in other words than the
#: conversation did is the model normalising a real name ("gdocs" to a tool's full name, "Muenchen" to "Munich", a relation
#: to a person): those are no label, and nothing here changes for them. A skill is named by Sleep as an instruction, never by
#: what anyone said.
COINABLE_TYPES = frozenset({"concept", "project"})

_WORD = re.compile(r"[^\W_]+", re.U)


def _clean(names: Iterable) -> list[str]:
    return [n for n in dict.fromkeys(" ".join(str(n or "").split()) for n in names) if n]


def located(text: str, name: str) -> bool:
    """Whether ``name`` is in ``text`` as the evidence spans locate a quote (never fuzzy), or as whole folded words."""
    from api.services import question_revisit as qr

    name = " ".join(str(name or "").split())
    if not name or not text:
        return False
    return evidence.locate(text, name) is not None or qr._hits([name], [], text)[0]


def person_text(text: str, *, override: str | None = None, gaps=(), persons=frozenset({"user", "speaker"})) -> str:
    """The turns of ``text`` whose author counts as the person (`promotion.person_kinds`), joined by newlines.

    A document with no turn marker is the person's own writing, as `promotion.exchanges` reads it; an agent's saved note
    (``override`` is `evidence.AGENT_KIND`) and a saved item's page text are not."""
    turns = evidence.turns(evidence.mask_labels(text or ""), override=override, gaps=gaps)
    masked = evidence.mask_labels(text or "")
    return "\n".join(masked[t.content_start:t.end] for t in turns if t.role in persons)


def said_in(names: Iterable, text: str, *, override: str | None = None, gaps=(),
            persons=frozenset({"user", "speaker"}), extra: str = "") -> str:
    """``"person"`` when any of ``names`` is in a turn of the person's own, else ``"others"`` when any is anywhere else in the
    text (``extra`` is more text that is nobody's turn: a record's title or source), else ``"nowhere"``."""
    names = _clean(names)
    if not names:
        return NOWHERE
    mine = person_text(text, override=override, gaps=gaps, persons=persons)
    if any(located(mine, n) for n in names):
        return PERSON
    if any(located(text, n) or (extra and located(extra, n)) for n in names):
        return OTHERS
    return NOWHERE


def words_of(name: str, text: str) -> str:
    """``"all"``, ``"some"`` or ``"none"`` of ``name``'s words (folded, whole) are words of ``text``."""
    words = [text_fold.fold(w) for w in _WORD.findall(str(name or ""))]
    words = [w for w in words if len(w) >= 2]
    if not words:
        return "none"
    said = {text_fold.fold(w) for w in _WORD.findall(str(text or ""))}
    hit = sum(1 for w in words if w in said)
    return "all" if hit == len(words) else "some" if hit else "none"


def coined(entity: dict, text: str, *, given: str = "", override: str | None = None, gaps=(),
           persons=frozenset({"user", "speaker"})) -> bool:
    """Is this Stage 1 entity's name a label nobody said? True only for a concept or a project (:data:`COINABLE_TYPES`) whose
    name and every alias is in no text of the conversation, ``given`` (what the model was handed besides it: the owner's name
    and the source note, so a harness's or a correspondent's name is said) included. A thing one of whose aliases the
    conversation says is not coined, and neither is an event or application the person acted on (ruling 42) or a book's
    record (ruling 64).

    The caller stamps the answer (:data:`COINED`); nothing is renamed, dropped or moved here: what a label is, is the caller's."""
    if str(entity.get("type") or "").lower() not in COINABLE_TYPES:
        return False
    if entity.get("application") or entity.get("reading_status"):
        return False
    names = _clean([entity.get("name"), *[a for a in entity.get("aliases") or [] if isinstance(a, str)]])
    if not names:
        return False
    return said_in(names, text, override=override, gaps=gaps, persons=persons, extra=given) == NOWHERE
