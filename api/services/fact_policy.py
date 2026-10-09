"""What a page keeps from what Sleep heard: restatements, sentences, conversation narration.

Pure and engine-free, shared by every machine writer of a page's prose
(`entity_body`, `entity_resolver`'s same-name fold, `entity_extractor`).

**Restatement, not meaning.** :func:`restates` decides, from words alone,
whether one item says nothing another does not: after folding (case,
accents, wikilinks, possessives, a light plural/tense stem) and dropping
function words, every content word of the one is in the other. Numbers are
words like any other ("in May 2026" never restates "in June 2026"), and the
two must agree on negation ("uses Docker" never restates "does not use
Docker"), and on the order of the names they share ("Alice reports to Bob"
never restates "Bob reports to Alice"). An item needs two content words to be
restated at all. Synonyms
("CI platform" / "continuous integration service") are not caught here: that
is the opt-in synthesis call's job (`entity_orientation`), never a guess.

Nothing here removes text a page already holds: callers drop only an INCOMING
item that an item already on the page (or a more specific incoming one)
restates, so the words survive once.
"""
from __future__ import annotations

import re
from functools import lru_cache

from api.services.text_fold import fold

# Function words and quantifiers that carry no content of their own. Negation
# words are deliberately absent: they are compared by `_negated`.
_STOP = frozenset("""
a an the of and or for to in on at by with from as into onto over under about via per than then
is are was were be been being am has have had do does did will would can could should might must
it its it's this that these those there here which who whom whose what when where while
each every all any some both either neither such same other another one
also too very just only still already again
""".split())
_NEGATION = frozenset("not no never none nothing nobody nowhere without cannot can't don't doesn't didn't "
                      "isn't aren't wasn't weren't won't wouldn't shouldn't hasn't haven't hadn't ni nunca sin".split())
_TOKEN = re.compile(r"[\w][\w'./@+-]*")
_WIKILINK = re.compile(r"\[\[([^\]|]+)(\|([^\]]+))?\]\]")
_NUMBER = re.compile(r"\d")
_NUMBER_WORDS = frozenset("zero one two three four five six seven eight nine ten eleven twelve twenty thirty forty "
                          "fifty hundred thousand million billion first second third half dozen".split())


def _stem(word: str) -> str:
    word = word.strip(".,;:!?'\"()[]")
    if word.endswith(("'s", "’s")):
        word = word[:-2]
    if len(word) > 4 and not _NUMBER.search(word):
        for suffix in ("ing", "ed", "es", "s"):
            if word.endswith(suffix) and len(word) - len(suffix) >= 3:
                return word[: -len(suffix)]
    return word


@lru_cache(maxsize=65536)
def _profile(text: str) -> tuple[frozenset[str], frozenset[str], bool]:
    """(content words, number tokens, negated) of one item."""
    text = _WIKILINK.sub(lambda m: m.group(3) or m.group(1), text or "")
    words = [_stem(w) for w in _TOKEN.findall(fold(text).replace("`", ""))]
    words = [w for w in words if w]
    numbers = frozenset(w for w in words if _NUMBER.search(w) or w in _NUMBER_WORDS)
    negated = any(w in _NEGATION for w in words)
    content = frozenset(w for w in words if w not in _STOP and w not in _NEGATION)
    return content, numbers, negated


@lru_cache(maxsize=65536)
def _names_in_order(text: str) -> tuple[str, ...]:
    """The folded stems of the capitalized words, in order — the names a relation is between."""
    text = _WIKILINK.sub(lambda m: m.group(3) or m.group(1), text or "")
    return tuple(_stem(fold(w)) for w in _TOKEN.findall(text.replace("`", "")) if w[:1].isupper())


def _same_direction(item: str, other: str) -> bool:
    """The names ``item`` and ``other`` share appear in the same order: "Alice reports to
    Bob" never restates "Bob reports to Alice"."""
    mine, theirs = _names_in_order(item), _names_in_order(other)
    shared = [n for n in dict.fromkeys(mine) if n in theirs]
    return [n for n in dict.fromkeys(theirs) if n in shared] == shared


def restates(item: str, other: str) -> bool:
    """True when ``other`` already says everything ``item`` says (see the module doc).

    Needs at least two content words in ``item``: a one-word item is never
    swallowed by a longer one. The names both mention must come in the same
    order, so a reversed relation is never folded."""
    a, _, a_negated = _profile(item)
    b, _, b_negated = _profile(other)
    if len(a) < 2 or a_negated != b_negated:
        return False
    # numbers are words too: every number of ``item`` must be in ``other``
    return a <= b and _same_direction(item, other)


def covered(item: str, kept) -> bool:
    """True when any text in ``kept`` restates ``item``."""
    return any(restates(item, other) for other in kept if other)


def union(existing: list[str], incoming: list[str]) -> tuple[list[str], int]:
    """``existing`` unchanged, then every incoming item nothing else restates.

    An incoming item a later, more specific incoming item restates gives way to
    it (both are this write's input; neither is on the page yet). Returns the
    items and how many incoming items were folded away."""
    kept_incoming: list[str] = []
    folded = 0
    for item in incoming:
        text = str(item).strip()
        if not text:
            continue
        if covered(text, existing) or covered(text, kept_incoming):
            folded += 1
            continue
        before = len(kept_incoming)
        kept_incoming = [k for k in kept_incoming if not restates(k, text)]
        folded += before - len(kept_incoming)
        kept_incoming.append(text)
    return list(existing) + kept_incoming, folded


# --------------------------------------------------------------------------- sentences

_ABBREVIATIONS = frozenset("e.g i.e etc vs mr mrs ms dr st jr sr inc ltd co no approx dept est fig u.s u.k a.m p.m "
                           "cf al ca jan feb mar apr jun jul aug sep sept oct nov dec".split())
_SENTENCE_END = re.compile(r"[.!?][\"'”’)]*\s+")


def sentences(text: str) -> list[str]:
    """Split one paragraph into sentences at ``.``/``!``/``?`` and a space, never after
    a common abbreviation or a single initial; a version number ("v2.1") has no
    space to split at. A lowercase start still opens a sentence: names here are
    often lowercase ("alpha-project", "iOS"). Whitespace is collapsed."""
    text = " ".join((text or "").split())
    out, start = [], 0
    for m in _SENTENCE_END.finditer(text):
        head = text[start:m.start() + 1]
        last = head.rstrip(".!?\"'”’)").split(" ")[-1].lower().rstrip(".")
        if last in _ABBREVIATIONS or (len(last) == 1 and last.isalpha()):
            continue
        out.append(text[start:m.end()].strip())
        start = m.end()
    tail = text[start:].strip()
    if tail:
        out.append(tail)
    return out


_INTRODUCTION = re.compile(r"(?:is|was|are|were|remains)\s+(?:a|an|the|one of|[^\s]+['’]s)\b")


def introduces(sentence: str, names) -> bool:
    """A sentence that (re)introduces the thing: it opens with one of its names, then
    a copula and what it is — "X is a CI platform.", "X is Alex's oldest friend."
    ("X was on TestFlight" says where it stands, not what it is)."""
    head = fold(_WIKILINK.sub(lambda m: m.group(3) or m.group(1), sentence or "")).lstrip()
    for name in names:
        name = fold(str(name or "")).strip()
        if name and head.startswith(name):
            if _INTRODUCTION.match(head[len(name):].lstrip(" ,")):
                return True
    return False


def said_everywhere(item: str, kept) -> bool:
    """Every content word of ``item`` is somewhere in ``kept`` (and a negated item
    meets a negated one). Only for a displaced (re-)introduction of the thing:
    "X is the CI platform that runs alpha-project's tests" beside "X is a CI
    platform" and "X runs alpha-project's tests" says nothing new. Never used to
    drop a fact: a scattered match is too weak for that."""
    words, _, negated = _profile(item)
    seen, any_negated = set(), False
    for other in kept:
        if other:
            content, _, neg = _profile(other)
            seen |= content
            any_negated = any_negated or neg
    return len(words) >= 2 and words <= seen and (any_negated or not negated)


# --------------------------------------------------------------------------- narration

# A fact whose only content is that the thing came up. The page's own sources
# already say which conversations mentioned it, so the line adds nothing.
_ABOUT_THE_CONVERSATION = re.compile(
    r"^[^.!?]{1,120}?\b(?:was|were|has been|have been|got|is|are)\s+"
    r"(?:mentioned|discussed|brought up|referenced|talked about|raised|named|noted)\s+"
    r"(?:(?:briefly|again|once)\s+)?"
    r"(?:in|during|within)\s+(?:a|an|the|this|that|one|an earlier|a previous|a recent)\s+"
    r"(?:conversation|chat|session|discussion|exchange|thread)s?\s*\.?$",
    re.IGNORECASE,
)


def about_the_conversation(fact: str) -> bool:
    """True for a fact that only says the thing came up in a conversation."""
    return bool(_ABOUT_THE_CONVERSATION.match(" ".join(str(fact or "").split())))
