"""One folding rule for every server-side text match (G136).

The app's ``QuickMatch`` (round-3 design §1.2) folds both sides with
``.caseInsensitive`` + ``.diacriticInsensitive`` so "Zurich" finds "Zürich".
The server has three matchers that must agree with it and with each other —
the FTS5 index (``unicode61 remove_diacritics 2`` folds the indexed side),
the query tokens that drive it, and the ``/conversations/recent?q=`` title
filter — so the query side is folded here, once, the same way: NFD, drop
combining marks, ``lower``.

Why NFD + ``lower`` and not NFKD + ``casefold`` (S-back final review): the
query side has to be the index side's twin, and ``unicode61`` only lowercases
and strips diacritics — it never applies a compatibility mapping or a full
case fold. NFKD turned the "ﬁ" ligature into "fi" and full-width letters into
ASCII, ``casefold`` turned "ß" into "ss", while the index kept "ﬁ", "ｆ" and
"ß" as written; so typing the exact stored text ("Hauptstraße", "ﬁle") found
nothing on the indexed path while the ``bank_index`` fallback, folding both
sides itself, did — two tiers disagreeing about one bank. NFD + ``lower``
matches ``unicode61`` for all of those and still folds "Zürich", "İstanbul"
and Greek capitals. The ASCII fast path in :func:`fold_with_map` was already
``lower()``, so it is unchanged.

Known residual (probed 2026-09-23, not fixed here): ``unicode61``'s diacritic
table does not cover Greek tonos, so "Αθήνα" is indexed as "αθήνα" while this
fold strips the accent; on the indexed tier that word is found only by a
prefix that stops before the accent ("αθ"). Closing it means handing FTS the
unstripped token and folding only for highlights — a change to how
``search_service`` carries tokens, not to this rule.

``match_offsets`` returns spans in **code points** (Python ``str`` indices),
which are Unicode scalars — the unit the app's ``ScalarSlice`` slices by
(design §4.10), so a bold range lands on the same characters on both sides.
Pure and engine-free: nothing here reads a file.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

# FTS5's unicode61 treats letters, numbers and private-use code points as
# token characters and everything else (including "_") as a separator; the
# query tokenizer splits the same way so a query token is always a whole
# index token prefix.
_SEPARATOR_RE = re.compile(r"[\W_]+", re.UNICODE)

# A one-character prefix matches a large share of the index and has no
# prefix index behind it; the palette never sends one (design §3.2: queries
# under 2 characters make no request), and the server does not search on one.
MIN_TOKEN_CHARS = 2
MAX_TOKENS = 8


def fold(text: str | None) -> str:
    """NFD, combining marks dropped, ``lower`` — "Zürich" → "zurich", and
    "Hauptstraße" stays "hauptstraße", as ``unicode61`` indexes it."""
    decomposed = unicodedata.normalize("NFD", text or "")
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


@lru_cache(maxsize=4096)
def _fold_char(ch: str) -> str:
    return fold(ch)


def fold_with_map(text: str) -> tuple[str, "list[int] | range"]:
    """``fold(text)`` plus, for every folded character, the index of the
    source character it came from — so a match found in folded space maps
    back to exact offsets in the original (a decomposed "u" + U+0308 folds to
    one "u" but spans two source code points).

    ASCII — most of a bank — folds to ``lower()`` one-to-one, so the map is
    the identity ``range`` and costs nothing; everything else goes through a
    per-character cache (an 8,000-character page took ~2 ms per call before
    either, measured 2026-09-23, and a result row may fold two of them)."""
    text = text or ""
    if text.isascii():
        return text.lower(), range(len(text))
    out: list[str] = []
    back: list[int] = []
    for i, ch in enumerate(text):
        for c in _fold_char(ch):
            out.append(c)
            back.append(i)
    return "".join(out), back


def query_tokens(q: str | None) -> list[str]:
    """Folded, deduplicated tokens of a query, in order, at most ``MAX_TOKENS``.

    Tokens shorter than ``MIN_TOKEN_CHARS`` are dropped; a query made only of
    them yields ``[]`` (no lexical search), never a one-letter prefix scan.
    """
    seen: set[str] = set()
    out: list[str] = []
    for tok in _SEPARATOR_RE.split(fold(q)):
        if len(tok) < MIN_TOKEN_CHARS or tok in seen:
            continue
        seen.add(tok)
        out.append(tok)
        if len(out) == MAX_TOKENS:
            break
    return out


def words(text: str | None) -> list[str]:
    """The folded index tokens of ``text``, in order (unicode61's split)."""
    return [w for w in _SEPARATOR_RE.split(fold(text)) if w]


def contains_all(text: str | None, q: str | None) -> bool:
    """Every whitespace-separated word of ``q`` is a folded SUBSTRING of
    ``text`` (AND). The title filter's rule: a title is short, so "contains"
    — QuickMatch's loosest tier — is the right strength; an empty ``q``
    matches everything."""
    words = fold(q).split()
    if not words:
        return True
    hay = fold(text)
    return all(w in hay for w in words)


def _is_word_start(folded: str, p: int) -> bool:
    return p == 0 or not folded[p - 1].isalnum()


def match_offsets(text: str | None, tokens: list[str]) -> list[list[int]]:
    """``[[start, end], …]`` of every word-start prefix match of any token in
    ``text``, merged and sorted, in code points of the ORIGINAL text.

    Word-start prefix is exactly what an FTS5 prefix query matched, so a
    highlight never claims a match the index did not make (and never invents
    a substring hit inside a word).
    """
    text = text or ""
    if not text or not tokens:
        return []
    folded, back = fold_with_map(text)
    spans: list[tuple[int, int]] = []
    for tok in tokens:
        start = folded.find(tok)
        while start != -1:
            if _is_word_start(folded, start):
                end = start + len(tok) - 1
                spans.append((back[start], back[end] + 1))
            start = folded.find(tok, start + 1)
    if not spans:
        return []
    spans.sort()
    merged: list[list[int]] = [list(spans[0])]
    for s, e in spans[1:]:
        if s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return merged
