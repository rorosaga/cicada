"""The words around a mention, cut so they read as what they were (owner 2026-11-24, question card).

``inbox_context`` used to cut ±240 characters around a mention on word boundaries. In a chat that glued several turns
into one paragraph with nobody's name on it, started in the middle of a sentence and ended in the middle of another.
Two cuts replace it, both engine-free, pure over the stored text and never written back:

* :func:`sentences` — a note, an article, a transcript line: the sentence the mention is in, grown by whole sentences
  (never across a blank line) to about :data:`TARGET` characters. A sentence longer than :data:`CAP` is cut at a word,
  and the cut is said (``cut_before`` / ``cut_after``) so a client draws an ellipsis instead of a quote that stops
  without saying so.
* :func:`chat` — a conversation (the episode has turns a marker wrote): the turn the mention is in, with the turn
  before and the turn after, whole; a turn longer than its cap is cut at a sentence, the mention's own turn around the
  mention, a neighbour toward the mention. The result says where each turn begins, who speaks and which edge was cut,
  as offsets into its own ``text`` — the same turn shape ``GET /episodes/{id}/text`` serves, so the app draws it with
  the Reader's own chat rows.

The mention itself is located by the caller (a G118 span or a name match) and is never moved: every cut includes it
whole, every offset here is rebased from the stored text, and nothing is fuzzy (G118). Text that overlaps what
``source_spans`` holds back as a secret (G235) is never included: a neighbouring turn that does is left out, and a
mention that does is no quote at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: The shape of what this module puts on the inbox wire (`InboxCause.turns`, the cuts); it joins `GET /inbox`'s ETag.
SHAPE = "cause2"

#: How long a quote of whole sentences grows to, and the most it grows to when the next sentence would fit.
TARGET = 300
CAP = 520
#: How far from the mention a sentence boundary is looked for before the sentence is cut at a word instead.
REACH = 420
#: The part of a sentence kept on each side of the mention when the sentence is too long to keep whole.
LONG_SIDE = 170
#: A turn's room in a conversation window: the mention's own, and a neighbour's.
MENTION_TURN_CAP = 640
NEIGHBOUR_TURN_CAP = 360
#: Stop adding neighbours past this many characters / turns.
CHAT_TARGET = 560
CHAT_MAX_TURNS = 5

_TERM = re.compile(r"([.!?…]+)([\"'”’)\]»]*)([ \t]+)")
_LINE = re.compile(r"\n[ \t]*(?=\S)")
_BLANK = re.compile(r"\n[ \t]*\n")
#: A full stop after one of these ends no sentence ("Dr. Smith", "e.g. this").
_ABBREVIATIONS = frozenset({
    "mr", "mrs", "ms", "dr", "sr", "sra", "srta", "jr", "st", "vs", "etc", "prof", "inc", "fig", "approx", "dept",
    "gen", "lic", "ing", "e.g", "i.e", "cf", "no", "nº", "pág", "pag", "tel", "av",
})
_CONVERSATION_MARKERS = frozenset({"user", "human", "assistant", "ai"})
#: A conversation by origin is never a feed item or a calendar entry (``ReaderChat.isChat``).
_NOT_CHATS = frozenset({"rss", "calendar", "calendar-local"})


@dataclass
class Turn:
    """One turn of the window, as offsets into :attr:`Quote.text` (``EpisodeTurn``'s shape, with the two cuts)."""

    index: int
    start: int
    content_start: int
    end: int
    role: str
    marker: str | None = None
    speaker: str | None = None
    ts: str | None = None
    speaker_kind: str | None = None
    cut_before: bool = False
    cut_after: bool = False


@dataclass
class Quote:
    text: str
    #: Highlighted ranges, relative to ``text``: the located mention first, then the same words and the other side's
    #: names where they appear in the window.
    offsets: list[list[int]] = field(default_factory=list)
    #: Where ``text`` begins in the stored text, for a plain quote; ``None`` for a conversation (it is pieces).
    start: int | None = None
    cut_before: bool = False
    cut_after: bool = False
    turns: list[Turn] = field(default_factory=list)


# ---------- sentences ----------


def _starts(text: str, lo: int, hi: int) -> list[int]:
    """Where a sentence begins strictly inside ``(lo, hi)``: after a closing ``.?!…`` and its spaces, and after a line
    break. A full stop followed by a lower-case letter or a digit ("Nov. 12", "e.g. this"), after one letter ("J.
    Smith") or after a known abbreviation ends nothing."""
    seg = text[lo:hi]
    found: set[int] = set()
    for m in _TERM.finditer(seg):
        at = lo + m.end()
        if at >= hi:
            continue
        stops = m.group(1)
        if stops[0] == ".":
            nxt = text[at]
            if nxt.islower() or nxt.isdigit():
                continue
            before = seg[:m.start()]
            word = re.search(r"([\w.ºª]+)$", before)
            token = (word.group(1) if word else "").lower().rstrip(".")
            if len(token) == 1 and token.isalpha() or token in _ABBREVIATIONS:
                continue
        found.add(at)
    for m in _LINE.finditer(seg):
        found.add(lo + m.end())
    return sorted(s for s in found if lo < s < hi)


def _word_edge(text: str, pos: int, lo: int, hi: int, *, forward: bool) -> int:
    """``pos`` moved to the nearest space inward, so a cut never splits a word."""
    pos = max(lo, min(hi, pos))
    if pos in (lo, hi):
        return pos
    if text[pos].isspace() or text[pos - 1].isspace():
        return pos
    if forward:
        nxt = text.find(" ", pos, hi)
        return nxt if nxt >= 0 else hi
    prev = text.rfind(" ", lo, pos)
    return prev + 1 if prev >= 0 else lo


def _trim(text: str, a: int, b: int) -> tuple[int, int]:
    while a < b and text[a].isspace():
        a += 1
    while b > a and text[b - 1].isspace():
        b -= 1
    return a, b


def _blank_before(text: str, pos: int) -> bool:
    """Whether a blank line (a paragraph break) lies in the whitespace just before ``pos``."""
    return bool(_BLANK.search(text[len(text[:pos].rstrip()):pos]))


def around(text: str, s: int, e: int, lo: int, hi: int, *, target: int = TARGET, cap: int = CAP) -> tuple[int, int]:
    """The whole sentences of ``text[lo:hi]`` around ``[s, e)``: ``(a, b)`` with ``lo <= a <= s`` and ``e <= b <= hi``.

    The mention's own sentence(s) first; then neighbours, the one before and the one after in turn, while the whole
    stays within ``cap`` and below ``target`` and does not cross a blank line. A sentence that does not end within
    :data:`REACH` of the mention (or begin) is cut at a word, :data:`LONG_SIDE` characters from it."""
    s, e = max(lo, s), min(hi, max(e, s + 1))
    rlo, rhi = max(lo, s - REACH), min(hi, e + REACH)
    starts = _starts(text, rlo, rhi)
    if rlo == lo:
        starts = [lo] + starts
    complete_right = rhi == hi
    # The sentences known whole: starts[i] .. starts[i+1]; the last one ends at ``hi`` only when the region reached it.
    ends = starts[1:] + ([hi] if complete_right else [None])
    i0 = max((i for i, st in enumerate(starts) if st <= s), default=None)
    i1 = max((i for i, st in enumerate(starts) if st <= e - 1), default=None)
    if i0 is None:
        a = _word_edge(text, s - LONG_SIDE, lo, hi, forward=True)
        lead = None
    else:
        a, lead = starts[i0], i0
    if i1 is None or ends[i1] is None:
        b = _word_edge(text, e + LONG_SIDE, lo, hi, forward=False)
        tail = None
    else:
        b, tail = ends[i1], i1
    a, b = min(a, s), max(b, e)
    if lead is not None and tail is not None:
        while b - a < target:
            grew = False
            if lead > 0 and b - starts[lead - 1] <= cap and not _blank_before(text, a):
                lead -= 1
                a = starts[lead]
                grew = True
            if b - a < target and tail + 1 < len(starts) and ends[tail + 1] is not None \
                    and ends[tail + 1] - a <= cap and not _blank_before(text, b):
                tail += 1
                b = ends[tail]
                grew = True
            if not grew:
                break
    a, b = _trim(text, a, b)
    return min(a, s), max(b, e)


def head(text: str, lo: int, hi: int, cap: int) -> tuple[int, int]:
    """The first whole sentences of ``text[lo:hi]`` that fit ``cap``; the first sentence cut at a word when it alone is longer."""
    lo, hi = _trim(text, lo, hi)
    if hi - lo <= cap:
        return lo, hi
    region = min(hi, lo + cap + REACH)
    starts = [s for s in _starts(text, lo, region) if s - lo <= cap]
    cut = max(starts) if starts else _word_edge(text, lo + cap, lo, hi, forward=False)
    a, b = _trim(text, lo, cut)
    return (a, b) if b > a else (lo, _word_edge(text, lo + cap, lo, hi, forward=False))


def tail(text: str, lo: int, hi: int, cap: int) -> tuple[int, int]:
    """The last whole sentences of ``text[lo:hi]`` that fit ``cap``; the last sentence cut at a word when it alone is longer."""
    lo, hi = _trim(text, lo, hi)
    if hi - lo <= cap:
        return lo, hi
    region = max(lo, hi - cap - REACH)
    starts = [s for s in _starts(text, region, hi) if hi - s <= cap]
    cut = min(starts) if starts else _word_edge(text, hi - cap, lo, hi, forward=True)
    a, b = _trim(text, cut, hi)
    return (a, b) if b > a else (_word_edge(text, hi - cap, lo, hi, forward=True), hi)


def _before(text: str, lo: int, a: int) -> bool:
    """Whether words remain in ``text[lo:a]``, before the quote."""
    return bool(text[lo:a].strip())


def _after(text: str, b: int, hi: int) -> bool:
    """Whether words remain in ``text[b:hi]``, after the quote."""
    return bool(text[b:hi].strip())


def _highlights(text: str, base: list[tuple[int, int]], names: list[str]) -> list[list[int]]:
    """The located mention first, then every other place the same words are said and every place one of ``names``
    is said, as whole words, case-insensitively — best effort (a name spelled with accents the fold dropped is not
    found, and that costs a highlight, never a wrong one)."""
    out: list[tuple[int, int]] = [r for r in base if r[1] > r[0]]
    if not out:
        return []
    words = {text[s:e].strip() for s, e in out[:1]} | {n for n in names if len(n) >= 3}
    for word in sorted((w for w in words if len(w) >= 3), key=len, reverse=True):
        for m in re.finditer(rf"(?<!\w){re.escape(word)}(?!\w)", text, re.IGNORECASE):
            span = (m.start(), m.end())
            if not any(span[0] < o[1] and o[0] < span[1] for o in out):
                out.append(span)
    head_, rest = out[0], sorted(out[1:])
    return [list(head_)] + [list(r) for r in rest]


def sentences(text: str, span: tuple[int, int] | None, *, lo: int = 0, hi: int | None = None,
              names: list[str] | None = None) -> Quote:
    """``span`` and the whole sentences around it — or, with no ``span``, the document's first sentences."""
    hi = len(text) if hi is None else hi
    if span is None:
        a, b = head(text, lo, hi, CAP)
        return Quote(text=text[a:b], start=a, cut_before=False, cut_after=_after(text, b, hi))
    a, b = around(text, span[0], span[1], lo, hi)
    window = text[a:b]
    base = [(span[0] - a, span[1] - a)]
    return Quote(text=window, offsets=_highlights(window, base, names or []), start=a,
                 cut_before=_before(text, lo, a), cut_after=_after(text, b, hi))


# ---------- conversations ----------


def conversation(turns, fm: dict | None) -> bool:
    """The episode reads as a chat (``ReaderChat.isChat``): not a page, a feed item, a calendar entry or an agent's
    report from a page, and at least one turn a conversation marker wrote."""
    fm = fm or {}
    if str(fm.get("origin") or fm.get("source") or "") in _NOT_CHATS or str(fm.get("source") or "") in ("page-read",):
        return False
    return any(_written(t.marker) for t in turns)


def _written(marker: str | None) -> bool:
    m = (marker or "").lower()
    return m in _CONVERSATION_MARKERS or m.startswith("speaker") or m.startswith("relayed")


def chat(text: str, turns, span: tuple[int, int], *, held: tuple = (), names: list[str] | None = None,
         display=None) -> Quote | None:
    """The turn holding ``span`` with its neighbours, whole where they fit. ``None`` when the mention's turn cannot be
    shown (it overlaps a held secret, or it is Cicada's own gap line); the caller then falls back to a plain quote.

    ``display(turn)`` gives ``(speaker, speaker_kind)`` for a turn (a meeting's speaker names, ROR-142); it is read
    only for the turns that are shown."""
    from api.services import source_spans

    s, e = span
    live = [t for t in turns if t.role != "gap" and t.end > t.content_start]
    inside = [i for i, t in enumerate(live) if t.start < e and s < max(t.end, t.start + 1)]
    if not inside:
        return None
    first, last = inside[0], inside[-1]

    def blocked(a: int, b: int) -> bool:
        return source_spans.overlaps_held(a, b, held)

    pieces: dict[int, tuple[int, int]] = {}
    for i in range(first, last + 1):
        t = live[i]
        lo, hi = t.content_start, t.end
        a, b = _trim(text, lo, hi)
        if b - a > MENTION_TURN_CAP:
            ms, me = max(s, lo), min(e, hi)
            if me <= ms:
                a, b = head(text, lo, hi, MENTION_TURN_CAP)
            else:
                a, b = around(text, ms, me, lo, hi, cap=MENTION_TURN_CAP)
        if blocked(a, b):
            return None
        pieces[i] = (a, b)

    def room() -> int:
        return sum(b - a for a, b in pieces.values())

    def neighbour(i: int, *, before: bool) -> bool:
        if not 0 <= i < len(live) or i in pieces:
            return False
        t = live[i]
        lo, hi = t.content_start, t.end
        a, b = tail(text, lo, hi, NEIGHBOUR_TURN_CAP) if before else head(text, lo, hi, NEIGHBOUR_TURN_CAP)
        if b <= a or blocked(a, b):
            return False
        pieces[i] = (a, b)
        return True

    lo_i, hi_i = first, last
    for ring in (0, 1):
        # One turn each side, whole where they fit; a second ring only while the quote is still thin.
        if len(pieces) >= CHAT_MAX_TURNS or room() >= (CHAT_TARGET if ring == 0 else CHAT_TARGET // 4):
            break
        if neighbour(lo_i - 1, before=True):
            lo_i -= 1
        if len(pieces) < CHAT_MAX_TURNS and room() < CHAT_TARGET and neighbour(hi_i + 1, before=False):
            hi_i += 1
    order = sorted(pieces)
    composed: list[str] = []
    out_turns: list[Turn] = []
    base: list[tuple[int, int]] = []
    pos = 0
    for i in order:
        t = live[i]
        a, b = pieces[i]
        if composed:
            pos += 1  # the "\n" between two pieces
        if not base and s < b and a < e:
            base.append((pos + max(a, s) - a, pos + min(b, e) - a))
        speaker, kind = display(t) if display is not None else (t.speaker, None)
        out_turns.append(Turn(index=t.index, start=pos, content_start=pos, end=pos + (b - a), role=t.role,
                              marker=t.marker, speaker=speaker, ts=t.ts, speaker_kind=kind,
                              cut_before=_before(text, t.content_start, a), cut_after=_after(text, b, t.end)))
        composed.append(text[a:b])
        pos += b - a
    window = "\n".join(composed)
    return Quote(text=window, offsets=_highlights(window, base, names or []), turns=out_turns,
                 cut_before=out_turns[0].cut_before, cut_after=out_turns[-1].cut_after)
