"""What a page keeps from what Sleep heard: repeats, sentences, conversation narration.

Pure and engine-free, shared by every machine writer of a page's prose
(`entity_body`, `entity_resolver`'s same-name fold, `entity_extractor`,
`pending_store`).

**A repeat, never a meaning (owner ruling 2026-10-09).** :func:`restates`
folds one item into another only when they are the SAME text after trivial
normalization: case, accents, whitespace, wikilink brackets and trailing
punctuation. Equality, not containment — two review rounds showed a
"contained in a longer item" rule drops facts whose longer neighbour changes
the meaning ("works at Acme" inside "works at Acme's competitor", "uses
Postgres" inside "uses Postgres or SQLite"). Paraphrases and more specific
restatements are folded only by the opt-in synthesis call, behind its own
guard (`entity_orientation`); with synthesis off they stay. A duplicate is
cheaper than a lost fact.

Nothing here removes text a page already holds: callers drop only an INCOMING
item equal to an item already on the page (or an earlier incoming one).
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


@lru_cache(maxsize=65536)
def normalized(text: str) -> str:
    """The text for equality: wikilinks unwrapped, accents and case folded, whitespace
    collapsed, trailing punctuation dropped. Nothing else."""
    text = _WIKILINK.sub(lambda m: m.group(3) or m.group(1), str(text or ""))
    return " ".join(fold(text).split()).rstrip(" .!?;:,")


def restates(item: str, other: str) -> bool:
    """True when ``item`` and ``other`` are the same text after :func:`normalized`."""
    a = normalized(item)
    return bool(a) and a == normalized(other)


# Words that set when or whether a statement holds. Used only by the synthesis guard
# (`entity_orientation`), never by the rule-based fold.
_STATUS = frozenset("""
is are was were be been being am will would shall should could can may might must has have had do does did
previously formerly former used once still now no longer anymore stopped quit left ex past future
plan plans planned planning intend intends intended considering considered want wants wanted hope hopes hoped
until since before after soon already yet never always sometimes rarely usually
""".split())


def compatible(item: str, other: str) -> bool:
    """``item`` adds no number, no tense or status word and no negation that ``other``
    lacks — the floor under a model's claim that the two say the same."""
    a, a_numbers, a_negated = _profile(item)
    b, b_numbers, b_negated = _profile(other)
    return a_negated == b_negated and a_numbers <= b_numbers and (a & _STATUS) <= (b & _STATUS)


def covered(item: str, kept) -> bool:
    """True when any text in ``kept`` restates ``item``."""
    return any(restates(item, other) for other in kept if other)


def union(existing: list[str], incoming: list[str], *, extend_existing: bool = False) -> tuple[list[str], int]:
    """``existing``, then every incoming item not equal (:func:`normalized`) to one already
    kept, and none that another item says word for word and then more (:func:`extends`):
    the shorter one folds into the longer, which takes its place. ``extend_existing``
    folds ``existing`` items too (a machine page: an existing item may be extended, or fold
    into a later one); without it every existing item stays exactly as it is. Returns the
    items and how many items were repeats."""
    seen = {normalized(e) for e in existing}
    kept: list[str] = []
    folded = 0
    for item in incoming:
        text = str(item).strip()
        if not text:
            continue
        key = normalized(text)
        if key in seen:
            folded += 1
            continue
        seen.add(key)
        kept.append(text)
    if extend_existing:
        items, _ = fold_extensions([], [str(e) for e in existing] + kept)
    else:
        items, _ = fold_extensions(existing, kept, extend_existing=False)
    return items, folded + len(existing) + len(kept) - len(items)


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


# --------------------------------------------------------------------------- standing alone

# A displaced orientation is split into Key Facts, and a Key Fact is read alone: on a page of thousands of bullets
# (the owner's), a sentence that leaned on the one before it ("… is applying to [[Alpha Hackathon]]. As of 2026-10-21
# he had the application form filled in …") joins whatever sits nearest. Engine-free and lossless: a sentence is only
# ever kept together with the one it leans on, never dropped or reworded.
_LEADING_TIME = re.compile(
    r"^(?:as of|on|in|by|since|during|until|from|around|early in|late in|early|mid|late)\s+"
    r"(?:(?:the\s+)?(?:\d{1,2}(?:st|nd|rd|th)?\s+)?[a-z]+\s+)?(?:\d{1,2},?\s+)?\d{4}(?:-\d{2}(?:-\d{2})?)?,?\s+",
    re.IGNORECASE)
_ANAPHORA = frozenset("he she it they this that these those his her its their there them him such both".split())
_DETERMINERS = frozenset("this that these those its their his her".split())
_CALENDAR = frozenset("""
january february march april may june july august september october november december
jan feb mar apr jun jul aug sep sept oct nov dec
monday tuesday wednesday thursday friday saturday sunday i
""".split())
_WORD = re.compile(r"[\w][\w'’.@+-]*")


def _plain(text: str) -> str:
    return " ".join(_WIKILINK.sub(lambda m: m.group(3) or m.group(1), str(text or "")).split())


def _undated(text: str) -> str:
    return _LEADING_TIME.sub("", text, count=1)


def names_of(text: str, names=()) -> set[str]:
    """What ``text`` names other than the page itself (``names``: its name and aliases): its wikilink targets and
    every capitalised word after the first (a month, a weekday and "I" aside), folded."""
    own = {fold(str(n)).strip() for n in names if n}
    own_words = {w for n in own for w in n.split()}
    found = {fold(m.group(1)).strip() for m in _WIKILINK.finditer(str(text or ""))} - own
    for word in _WORD.findall(_undated(_plain(text)))[1:]:
        folded = fold(word).rstrip(".'’")
        for suffix in ("'s", "’s"):
            folded = folded.removesuffix(suffix)
        if word[:1].isupper() and folded not in _CALENDAR and folded not in own_words and folded not in own:
            found.add(folded)
    return found


def _opener(sentence: str) -> str:
    words = _WORD.findall(_undated(_plain(sentence)))
    return fold(words[0]) if words else ""


def _opens_with_page(sentence: str, names=()) -> bool:
    head = fold(_undated(_plain(sentence))).lstrip()
    return any(n and head.startswith(n) for n in (fold(str(x)).strip() for x in names if x))


def leans(sentence: str, names=(), previous: str = "") -> bool:
    """A sentence that does not say by itself what it is about: it names nothing but the page itself ("As of
    2026-10-21 he had the application form filled in"), or — after ``previous``, which is not about the page (it
    does not open with the page's name or a pronoun) — it opens with a pronoun or a demonstrative ("It runs on …",
    "This pass costs …"). A leading date phrase ("As of 2026-10-21", "In March 2026,") is read past."""
    words = _WORD.findall(_undated(_plain(sentence)))
    if not words:
        return False
    if not names_of(sentence, names):
        return True
    first = fold(words[0])
    if first not in _ANAPHORA or (first in _DETERMINERS and len(words) > 1 and words[1][:1].isupper()):
        return False  # "This Friday …", "Their Berlin office …" say what they are about
    return not (_opens_with_page(previous, names) or _opener(previous) in _ANAPHORA)


def standalone(text: str, names=()) -> list[str]:
    """``text`` (one paragraph or several) as facts that each stand alone: its :func:`sentences`, except that a
    sentence which :func:`leans` stays joined to the one before it, in its paragraph, when that one names something
    other than the page (``names``: the page's name and aliases). Every word is kept, in order."""
    out: list[str] = []
    for paragraph in re.split(r"\n\s*\n", str(text or "")):
        beyond = False  # the fact being built names something other than the page
        previous = ""
        for i, sentence in enumerate(sentences(paragraph)):
            if i and beyond and leans(sentence, names, previous):
                out[-1] = f"{out[-1]} {sentence}"
            else:
                out.append(sentence)
                beyond = bool(names_of(sentence, names))
            previous = sentence
    return out


# --------------------------------------------------------------------------- one fact said twice

# The loss-free fold ruling 23 left open ("revisit the fold only with a measured loss-free paraphrase rule"): one item
# folds into another only when every word of it is still there, in order, at the start of the other (after an optional
# leading date phrase), and the other goes on past a clause boundary — "Rolling admissions" inside "Rolling admissions
# with no deadline, …". Never inside a word or a number ("Acme" in "Acme's competitor", "200" in "200,000"), never past
# "or", "but", "than", "until" or "to" (they change what the head says), never a dated item into an undated one.
_CLAUSE = re.compile(r"^(?:[,;:.!?]\s|\s[-–—]\s|\s\(|\s(?:with|which|who|whose|where|including|via|through)\s)")


@lru_cache(maxsize=65536)
def _surface(text: str) -> str:
    return " ".join(fold(_plain(text)).split()).rstrip(" .!?;:,")


_KEY_WORDS = 3


def _prefixes(text: str) -> set[tuple[str, ...]]:
    """Up to the first three words of ``text`` and of ``text`` without its leading date phrase, as every prefix:
    where an item that :func:`extends` ``text`` would be found in :func:`fold_extensions`' index."""
    surface = _surface(text)
    out = set()
    for head in {surface, _undated(surface)}:
        words = tuple(head.split()[:_KEY_WORDS])
        out |= {words[:n] for n in range(1, len(words) + 1)}
    return out


def _key(text: str) -> tuple[str, ...]:
    return tuple(_surface(text).split()[:_KEY_WORDS])


def extends(longer: str, shorter: str) -> bool:
    """True when ``longer`` says ``shorter`` word for word and then more, past a clause boundary."""
    a, b = _surface(shorter), _surface(longer)
    if not a or len(b) <= len(a):
        return False
    heads = [b]
    if _undated(a) == a and _undated(b) != b:
        heads.append(_undated(b))  # "In April 2026, X …" keeps everything an undated "X" said
    return any(head.startswith(a) and _CLAUSE.match(head[len(a):]) for head in heads)


def fold_extensions(existing: list[str], incoming: list[str], *, extend_existing: bool = True
                    ) -> tuple[list[str], dict[str, str]]:
    """``existing`` then ``incoming``, an item that another one :func:`extends` folded into it.

    An incoming item a kept one already says word for word is left out; an incoming item that extends a kept one takes
    its place (the kept one's words survive, verbatim, inside it). ``extend_existing=False`` (a page a person edited)
    never changes an ``existing`` item: an incoming one that extends it is added beside it. Returns the items and
    ``{folded text: the text that now holds it}``, so a caller moves a folded item's sources onto its holder."""
    kept: list[str] = [str(e) for e in existing]
    fixed = 0 if extend_existing else len(kept)
    moved: dict[str, str] = {}
    # Only items that share their first words can extend one another: the owner's page has thousands of bullets.
    longer: dict[tuple, list[int]] = {}   # a prefix of a kept item's head -> the items (as the longer one)
    shorter: dict[tuple, list[int]] = {}  # a kept item's first words -> the items (as the shorter one)

    def _add(i: int) -> None:
        for prefix in _prefixes(kept[i]):
            longer.setdefault(prefix, []).append(i)
        shorter.setdefault(_key(kept[i]), []).append(i)

    for i in range(len(kept)):
        _add(i)
    for item in incoming:
        text = str(item).strip()
        if not text:
            continue
        holder = next((kept[i] for i in sorted(longer.get(_key(text), ()))
                       if kept[i] and extends(kept[i], text)), None)
        if holder is not None:
            moved[text] = holder
            continue
        near = sorted({i for prefix in _prefixes(text) for i in shorter.get(prefix, ()) if kept[i]})
        slots = [i for i in near if i >= fixed and extends(text, kept[i])]
        for i in slots:
            old, kept[i] = kept[i], ""
            moved = {key: (text if value == old else value) for key, value in moved.items()}
            moved[old] = text
        if slots:
            kept[slots[0]] = text
            _add(slots[0])
        else:
            kept.append(text)
            _add(len(kept) - 1)
    return [k for k in kept if k], moved
