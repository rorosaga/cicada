"""What ties a mention to one candidate inside the sentence the reader copied (ruling 83, `which_one_reader`; review 2026-11-26).

A reader that picked a candidate is believed only when the COPIED sentence itself attaches the mention to something the record holds for
that candidate and for no other. Code only, no model, no I/O. The rules, each one a refusal when it fails ("when in doubt it stays a
question"):

* the copied sentence holds the mention (whole word) and every whole-word occurrence of it is attached to a tell of the pick, by form:

  - **a full name** that holds the mention at that position (a bare "Nick" beside "Nick Vale" is a second, unattached occurrence);
  - **a relation** the record gives the page, directly before the mention after an optional possessive of the speaker ("my brother
    Nick", "mi hermano Nico"; bare only at the start of a clause), or directly after it as an apposition or "is my" ("Nick, my
    brother", "Nick is my brother", "Nico es mi hermano"). A possessive on the relation ("brother's"), a hyphenated compound
    ("brother-in-law"), a capitalised name after it ("my brother Dan") or any other word between them breaks it;
  - **a linked thing** (an employer, a project, a tool, a place) as "<mention> from/at/of <thing>" or "<thing>'s <mention>" (Spanish
    "de" / "en");

* the sentence is not a question, carries no negation or contrast (not, no, never, n't, other, another, else, different, but, instead
  ...; the Spanish ones), and names no tell of another candidate. This is judged over the whole sentence the copied words are in
  (clamped to what the reader was shown), so a reader cannot copy the "not" away;
* a tell is the record's: a relation, a full name, a linked page's title and its multi-word or capitalised aliases. A linked page's
  alias that is one lowercase word ("home") is a common word and never a tell; a single-word tell matches only in its own case.

A tell in another turn, another sentence or unseen text never counts: only the copied words and their own sentence are read.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

#: A letter or digit (Unicode, never an underscore): what a whole word is bounded by.
_L = r"[^\W_]"
_OPEN = "(“\"'‘¿¡"
_END = ".!?…\n"

NEGATIONS = (
    # English
    "not", "no", "never", "nobody", "none", "neither", "nor", "without", "other", "others", "another", "else", "different", "instead",
    "rather", "unlike", "except", "but", "however", "although", "though", "nothing", "nowhere", "cannot",
    # Spanish
    "ni", "nunca", "jamás", "jamas", "tampoco", "nadie", "ningún", "ningun", "ninguno", "ninguna", "otro", "otra", "otros", "otras",
    "distinto", "distinta", "diferente", "sino", "pero", "aunque", "excepto", "salvo", "nada", "además", "ademas",
)
QUESTION_WORDS = ("who", "whom", "whose", "which", "what", "where", "when", "why", "how", "quién", "quien", "quiénes", "quienes",
                  "cuál", "cual", "cuáles", "cuales", "qué", "que", "dónde", "donde", "cuándo", "cuando", "cómo", "como", "cuánto",
                  "cuanto")
_NEG = re.compile(rf"(?<!{_L})(?:{'|'.join(map(re.escape, NEGATIONS))})(?!{_L})|{_L}+n['’]t(?!{_L})", re.I)
_QUESTION_OPENER = re.compile(rf"^\W*(?:{'|'.join(map(re.escape, QUESTION_WORDS))})(?!{_L})", re.I)


@dataclass(frozen=True)
class Tell:
    kind: str       # role | full_name | linked
    words: str


def _phrase(words: str) -> str:
    return r"\s+".join(re.escape(tok) for tok in words.split())


def _whole(words: str, *, exact_case: bool = False) -> re.Pattern[str]:
    return re.compile(rf"(?<!{_L}){_phrase(words)}(?!{_L})", 0 if exact_case else re.I)


def _exact(words: str) -> bool:
    """A single-word thing matches only in its own case: a proper name is capitalised where it is said, a common word is not it."""
    return len(words.split()) == 1


def occurrences(text: str, words: str, *, exact_case: bool = False) -> list[tuple[int, int]]:
    """Every whole-word occurrence of ``words`` in ``text`` (whitespace between its words is flexible)."""
    if not words.strip():
        return []
    return [(m.start(), m.end()) for m in _whole(words, exact_case=exact_case).finditer(text)]


def tell_occurrences(text: str, tell: Tell) -> list[tuple[int, int]]:
    return occurrences(text, tell.words, exact_case=tell.kind == "linked" and _exact(tell.words))


def names_a_tell(text: str, tells: list[Tell]) -> bool:
    return any(tell_occurrences(text, t) for t in tells)


# --------------------------------------------------------------------------- the forms


def _role_before(text: str, s: int, role: str) -> bool:
    pre = text[:s]
    gap = re.search(r"\s+$", pre)
    if gap is None:
        return False
    pre = pre[:gap.start()]
    m = re.search(rf"(?<!{_L}){_phrase(role)}$", pre, re.I)
    if m is None:
        return False
    head = pre[:m.start()]
    if head and not head[-1].isspace() and head[-1] not in _OPEN:
        return False                       # "step-brother", "brother's friend"'s tail, a letter: not the relation word itself
    head = head.rstrip()
    if not head or head[-1] in ",;:.!?—–(" or head[-1] in _OPEN:
        return True                        # a bare relation word only opens a clause
    return re.search(rf"(?<![^\W_'’-])(?:my|mi)$", head, re.I) is not None


def _role_after(text: str, e: int, role: str) -> bool:
    pat = re.compile(
        r"(?:\s*[,(]\s*|\s+(?i:is|was|es|era)\s+|['’]s\s+)(?i:my|mi)\s+(?i:" + _phrase(role) + r")"
        r"(?![\w'’-])(?!\s+[A-ZÀ-ÖØ-Þ])")
    return pat.match(text, e) is not None


def _thing_after(text: str, e: int, thing: str) -> bool:
    pat = re.compile(r"(?:\s*,\s*|\s+)(?i:from|at|of|de|en)\s+(?:(?i:the|el|la|los|las)\s+)?"
                     + (_phrase(thing) if _exact(thing) else r"(?i:" + _phrase(thing) + ")") + rf"(?!{_L})")
    return pat.match(text, e) is not None


def _thing_before(text: str, s: int, thing: str) -> bool:
    pre = text[:s]
    pat = re.compile(rf"(?<!{_L})" + (_phrase(thing) if _exact(thing) else r"(?i:" + _phrase(thing) + ")") + r"['’]s\s+$")
    return pat.search(pre) is not None


def _attached(text: str, s: int, e: int, tells: list[Tell]) -> str | None:
    """The kind of the tell that attaches the mention at ``[s, e)``, or ``None``."""
    for t in tells:
        if t.kind == "full_name":
            if any(a <= s and e <= b for a, b in occurrences(text, t.words)):
                return t.kind
        elif t.kind == "role":
            if _role_before(text, s, t.words) or _role_after(text, e, t.words):
                return t.kind
        elif t.kind == "linked":
            if _thing_after(text, e, t.words) or _thing_before(text, s, t.words):
                return t.kind
    return None


def attach(quote: str, mention: str, tells: list[Tell]) -> list[str]:
    """The kinds of tell that attach EVERY occurrence of ``mention`` in ``quote``, or ``[]``: no occurrence, or one that no tell of
    the pick is attached to."""
    spots = occurrences(quote, mention)
    if not spots or not tells:
        return []
    kinds: list[str] = []
    for s, e in spots:
        kind = _attached(quote, s, e, tells)
        if kind is None:
            return []
        kinds.append(kind)
    return sorted(set(kinds))


# --------------------------------------------------------------------------- what makes a sentence unfit


def enclosing(text: str, start: int, end: int, lo: int, hi: int) -> str:
    """The whole sentence(s) ``text[start:end]`` sits in, cut at ``.``, ``!``, ``?`` and a line end, clamped to ``[lo, hi)`` (what the
    reader was shown). The closing mark is kept: a question is the one that ends in ``?``."""
    a, b = max(lo, start), min(hi, end)
    while a > lo and text[a - 1] not in _END:
        a -= 1
    while b < hi and (b == 0 or text[b - 1] not in _END):
        b += 1
    return text[a:b]


def is_question(sentence: str) -> bool:
    return "?" in sentence or "¿" in sentence or _QUESTION_OPENER.match(sentence) is not None


def has_contrast(sentence: str) -> bool:
    return _NEG.search(sentence) is not None


def tie(mention: str, quote: str, context: str, pick: list[Tell], others: list[list[Tell]]) -> list[str]:
    """The kinds that tie ``mention`` to the pick in ``quote`` (the copied words) given the sentence they are in (``context``), or
    ``[]`` when anything refuses: see the module words."""
    context = context if quote in context else f"{context} {quote}"
    if is_question(context) or has_contrast(context):
        return []
    if any(names_a_tell(context, o) for o in others):
        return []
    return attach(quote, mention, pick)
