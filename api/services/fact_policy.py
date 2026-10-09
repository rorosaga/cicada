"""What a page keeps from what Sleep heard: restatements, sentences, conversation narration.

Pure and engine-free, shared by every machine writer of a page's prose
(`entity_body`, `entity_resolver`'s same-name fold, `entity_extractor`).

**Restatement, never meaning — and when in doubt, keep.** :func:`restates`
folds one item into another only when the other says it word for word: after
folding case, accents, wikilinks, possessives and a plural ``s``, and leaving
out articles, prepositions and conjunctions, the item's words appear in the
other as one unbroken run, in the same order. Everything that can change what
a fact says stays a word that must match: tense and status ("is"/"was",
"will", "previously", "launched"/"launch" — no tense stemming), modals,
quantifiers, every whole number ("1,200" is one number, never "1" and "200"),
and negation, which must also be equal on both sides. Order covers every
operand, named or not ("tea over coffee" never restates "coffee over tea").
An item needs two content words to be restated at all. A duplicate is cheaper
than a lost fact: synonyms and paraphrases ("CI platform" / "continuous
integration service") are never caught here — only the opt-in synthesis call
can fold those (`entity_orientation`), behind its own guard.

Nothing here removes text a page already holds: callers drop only an INCOMING
item that an item already on the page (or a more specific incoming one)
restates, so the words survive once.
"""
from __future__ import annotations

import re
from functools import lru_cache

from api.services.text_fold import fold

# Words that carry no claim of their own: articles, prepositions, conjunctions,
# demonstratives. Tense, modality, quantity and negation are deliberately absent.
_STOP = frozenset("""
a an the of and or for to in on at by with from as into onto via per
it its it's this that these those there here which who whom whose
""".split())
_NEGATION = frozenset("not no never none nothing nobody nowhere without cannot can't don't doesn't didn't "
                      "isn't aren't wasn't weren't won't wouldn't shouldn't hasn't haven't hadn't ni nunca sin "
                      "neither nor".split())
# A whole number with thousands separators or decimals is one token.
_TOKEN = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|[\w][\w'./@+-]*")
_WIKILINK = re.compile(r"\[\[([^\]|]+)(\|([^\]]+))?\]\]")
_NUMBER = re.compile(r"\d")


def _stem(word: str) -> str:
    word = word.strip(".,;:!?'\"()[]")
    if word.endswith(("'s", "’s")):
        word = word[:-2]
    # A plural "s" only ("tests" → "test", "uses" → "use"); never a tense ending.
    if len(word) >= 4 and word.endswith("s") and not word.endswith("ss") and not _NUMBER.search(word):
        return word[:-1]
    return word


@lru_cache(maxsize=65536)
def _sequence(text: str) -> tuple[str, ...]:
    """The item's significant words, in order (negation words included)."""
    text = _WIKILINK.sub(lambda m: m.group(3) or m.group(1), text or "")
    words = [_stem(w) for w in _TOKEN.findall(fold(text).replace("`", ""))]
    return tuple(w for w in words if w and w not in _STOP)


@lru_cache(maxsize=65536)
def _profile(text: str) -> tuple[frozenset[str], frozenset[str], bool]:
    """(content words, number tokens, negated) of one item."""
    words = _sequence(text)
    numbers = frozenset(w for w in words if _NUMBER.search(w))
    negated = any(w in _NEGATION for w in words)
    content = frozenset(w for w in words if w not in _NEGATION)
    return content, numbers, negated


def _contains_run(run: tuple[str, ...], seq: tuple[str, ...]) -> bool:
    n = len(run)
    return any(seq[i:i + n] == run for i in range(len(seq) - n + 1))


def restates(item: str, other: str) -> bool:
    """True when ``other`` already says ``item`` word for word (see the module doc)."""
    a, b = _sequence(item), _sequence(other)
    a_content, _, a_negated = _profile(item)
    if len(a_content) < 2 or a_negated != _profile(other)[2]:
        return False
    return _contains_run(a, b)


# Words that set when or whether a statement holds. Two items that differ in them say different things.
_STATUS = frozenset("""
is are was were be been being am will would shall should could can may might must has have had do does did
previously formerly former formerly used once still now no longer anymore stopped quit left ex past future
plan plans planned planning intend intends intended considering considered want wants wanted hope hopes hoped
until since before after soon already yet never always sometimes rarely usually
""".split())


def compatible(item: str, other: str) -> bool:
    """``item`` adds no number, no tense or status word and no negation that ``other``
    lacks — the floor under any claim (a model's included) that the two say the same."""
    a, a_numbers, a_negated = _profile(item)
    b, b_numbers, b_negated = _profile(other)
    return a_negated == b_negated and a_numbers <= b_numbers and (a & _STATUS) <= (b & _STATUS)


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


# --------------------------------------------------------------------------- narration

# A fact whose only content is that the thing came up: its subject is the thing
# itself (a name or alias of the page, or a pronoun), and every other word is
# this fixed narration. The page's own sources already say which conversations
# mentioned it. Any other subject ("Moving to Berlin … was discussed …") is a
# fact with content and is never matched.
_NARRATION = re.compile(
    r"^(?P<subject>.+?)\s+(?:was|were|has been|have been|got|is|are)\s+"
    r"(?:(?:briefly|again|only|also)\s+)?"
    r"(?:mentioned|discussed|brought up|referenced|talked about|named|noted)\s+"
    r"(?:(?:briefly|again|once)\s+)?"
    r"(?:in|during|within)\s+(?:a|an|the|this|that|one|an earlier|a previous|a recent)\s+"
    r"(?:conversation|chat|session|discussion|exchange|thread)s?\s*\.?$",
    re.IGNORECASE,
)
_PRONOUNS = frozenset({"it", "this", "they", "he", "she", "this tool", "this project", "this person"})


def about_the_conversation(fact: str, names=()) -> bool:
    """True for a fact that only says the thing came up in a conversation: its subject
    is one of ``names`` (the page's name and aliases, "the " allowed) or a pronoun."""
    m = _NARRATION.match(" ".join(str(fact or "").split()))
    if not m:
        return False
    subject = fold(_WIKILINK.sub(lambda w: w.group(3) or w.group(1), m.group("subject"))).strip()
    if subject.startswith("the "):
        subject = subject[4:]
    allowed = {fold(str(n)).strip() for n in names if n} | _PRONOUNS
    allowed |= {n[4:] for n in allowed if n.startswith("the ")}
    return subject in allowed
