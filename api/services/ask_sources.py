"""What was said — the source conversations' own words behind what ``cicada_ask`` shows (G118, G148).

Sleep keeps the skeleton of a conversation (a claim, a page line) and the conversation itself stays in the bank as
an episode. Every claim points at the exact passage it rests on (G118 evidence spans) and every page line at the
conversations it came from (``section_provenance``). Ask used to stop at the skeleton, so the detail around it — what
a necklace stands for, why that agency, how long married — never reached the answering model although the claim
pointed straight at it (LoCoMo conv-26: 17 of 19 wrong answers said memory lacked the detail; 2026-10-17 note).

This module follows those pointers at answer time and nothing else:

* **Spans, not copies.** The words are read from the episode file on every call and handed to the model; nothing is
  written back, stored on a claim, indexed or logged — the question included.
* **Only where the graph points.** The episodes read are the ones the shown claims' evidence and the shown page
  lines' provenance cite, ranked by how many of the question's words the pointing claim or line shares, at most
  :data:`MAX_EPISODES`. Inside them a turn is kept when it holds a pointed span or shares the question's words.
  Never a scan of the bank's conversations, and never by confidence.
* **Whose words.** Every excerpt says who spoke — the person, the agent, or the other person in a message
  conversation — from the episode's own turn markers (``evidence.turns``), and Cicada's own gap line is never one.
  A stale span (the conversation was rewritten) points at its episode only; it never highlights other words.
* **Bounded.** At most :data:`MAX_EXCERPTS` excerpts and :data:`TOTAL_CHARS` characters, each turn clipped around
  the span or the first matching word.

Only bank files are opened (``evidence.source_document``); transcripts under ``~/.claude`` never are.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from api.services import evidence, text_fold

MAX_EPISODES = 8
MAX_EXCERPTS = 10
EXCERPT_CHARS = 600
TOTAL_CHARS = 6000
#: A reply this short is shown with the turn it answers ("Yes, Sweden!" means nothing alone).
SHORT_REPLY_CHARS = 160
CONTEXT_CHARS = 240
_EP_DAY = re.compile(r"^ep_(\d{4}-\d{2}-\d{2})_")
#: A question's scaffolding that :data:`text_fold.SUBJECT_STOPWORDS` keeps ("how LONG", "would she LIKELY"): a turn
#: sharing only these with the question is not about it ("Long time no talk!").
QUESTION_WORDS = frozenset(text_fold.stem(w) for w in
                           "long many much often ago kind type sort likely consider considered think".split())


@dataclass
class Pointer:
    """One place the graph says a shown claim or line came from: an episode, and the span when one was asserted."""

    episode: str
    weight: int
    start: int | None = None
    end: int | None = None
    hash: str = ""
    terms: set[str] = field(default_factory=set)


def pointers(evidence_rows, weight: int, terms: set[str] | None = None) -> list[Pointer]:
    """Pointers from a claim's ``evidence`` (or a page line's provenance rows): a span when it has one, else the
    episode alone. Only episodes — a page citing a page is already in front of the model."""
    out: list[Pointer] = []
    for ev in evidence_rows or []:
        doc = str(getattr(ev, "episode", "") or "")
        if not evidence.is_episode_id(doc):
            continue
        span = getattr(ev, "kind", "reasoning") != "reasoning" and int(getattr(ev, "start", -1)) >= 0
        out.append(Pointer(episode=doc, weight=weight, start=ev.start if span else None,
                           end=ev.end if span else None, hash=str(getattr(ev, "hash", "") or ""),
                           terms=set(terms or ())))
    return out


def episode_day(episode_id: str) -> str:
    m = _EP_DAY.match(episode_id or "")
    return m.group(1) if m else ""


@dataclass
class Excerpt:
    episode: str
    day: str
    who: str
    text: str
    order: tuple
    #: ``(who, words)`` of the turn a short reply answers, and of the reply to a question.
    before: tuple[str, str] | None = None
    after: tuple[str, str] | None = None
    #: Indexes of the context turns shown beside it (``before``/``after``).
    shown: list[int] = field(default_factory=list)
    #: The conversation's title, as its episode names it.
    title: str = ""


def _clip_around(text: str, at: int | None, limit: int) -> str:
    """``text`` whole when it fits, else a window of ``limit`` characters around ``at``, cut on spaces."""
    text = text.strip()
    if len(text) <= limit:
        return text
    at = max(0, min(at or 0, len(text)))
    lo = max(0, at - limit // 3)
    hi = min(len(text), lo + limit)
    lo = max(0, hi - limit)
    if lo:
        space = text.find(" ", lo)
        lo = space + 1 if 0 <= space < lo + 40 else lo
    if hi < len(text):
        space = text.rfind(" ", lo, hi)
        hi = space if space > lo + limit // 2 else hi
    return ("…" if lo else "") + text[lo:hi].strip() + ("…" if hi < len(text) else "")


def _clip(text: str, at: int | None, limit: int) -> str:
    """:func:`_clip_around`, its whitespace runs folded to one space (a quote in a prompt line, not a layout)."""
    return " ".join(_clip_around(text, at, limit).split())


#: Episodes an agent wrote through a tool door (``mcp_tools`` stamps ``source``): a block with no turn marker is the
#: agent's note, not the person speaking — ``evidence`` reads an unmarked block as the person's (R4), Ask may not.
AGENT_SOURCES = frozenset({"mcp", "mcp-remote", "cli"})


def _who(turn, fm: dict, owner_name: str | None) -> str:
    if _speaker(turn, fm) == AGENT_NOTE:
        return "an agent's saved note (not the person's own words)"
    if turn.role == "user":
        return f"{owner_name} (the person this memory belongs to)" if owner_name else "the person this memory belongs to"
    if turn.role == "assistant":
        return "the assistant (an AI agent, not the person)"
    if turn.role == "speaker":
        label = (turn.marker or "").split(":", 1)[-1].strip() or "someone else"
        corr = fm.get("correspondent") if isinstance(fm.get("correspondent"), dict) else {}
        name = str(corr.get("name") or "").strip()
        if name and text_fold.words(name) and "-".join(text_fold.words(name)) == "-".join(text_fold.words(label)):
            label = name
        return f"{label} (another person, not the person this memory belongs to)"
    if turn.role == "media":
        return "the media item (not the person's words)"
    return "unattributed"


def _first_match(text: str, terms: set[str]) -> int | None:
    """Where the first word holding one of ``terms`` starts: the word itself, or a longer form of it (as the word
    index matches a prefix)."""
    for m in re.finditer(r"\w+", text):
        word = text_fold.fold(m.group(0))
        if text_fold.stem(word) in terms or any(len(t) >= 4 and word.startswith(t) for t in terms):
            return m.start()
    return None


def gather(memory_path: Path, question: str, found: list[Pointer], *, owner_name: str | None = None,
           terms: set[str] | None = None, max_episodes: int = MAX_EPISODES, max_excerpts: int = MAX_EXCERPTS,
           total_chars: int = TOTAL_CHARS) -> list[Excerpt]:
    """The excerpts for ``question`` from the episodes ``found`` points at, oldest first (see the module doc).
    ``terms``: the question's words to rank turns by (default: all of its subject words)."""
    terms = set(terms) if terms else text_fold.subject_terms(question)
    terms = (terms - QUESTION_WORDS) or terms
    by_episode: dict[str, dict] = {}
    for p in found:
        if p.weight <= 0:
            continue
        row = by_episode.setdefault(p.episode, {"weight": 0, "n": 0, "spans": [], "terms": set()})
        row["weight"] = max(row["weight"], p.weight)
        row["n"] += 1
        row["terms"] |= p.terms
        if p.start is not None and p.end is not None:
            row["spans"].append(p)
    ranked = sorted(by_episode, key=lambda ep: (-by_episode[ep]["weight"], -by_episode[ep]["n"], ep))[:max_episodes]

    candidates: list[tuple] = []
    docs: dict[str, tuple] = {}
    for rank, ep in enumerate(ranked):
        doc = evidence.source_document(memory_path, ep)
        if doc is None:
            continue
        fm, text = doc
        gaps = evidence.gap_ranges(fm, text)
        spans = [p for p in by_episode[ep]["spans"]
                 if 0 <= p.start < p.end <= len(text)
                 and evidence.span_status(text, end=p.end, hash=p.hash) != evidence.SPAN_STALE]
        turns = [t for t in evidence.turns(text, stamps=evidence.turn_stamps(fm), override=fm.get("evidence_kind"),
                                           gaps=gaps) if t.role != evidence.GAP_KIND]
        docs[ep] = (fm, text, turns)
        extra = by_episode[ep]["terms"] - terms
        for i, turn in enumerate(turns):
            body = text[turn.content_start:turn.end]
            words = text_fold.subject_terms(body)
            overlap = len(terms & words)
            span = next((p for p in spans if turn.start <= p.start < turn.end), None)
            if not overlap and span is None:
                continue
            score = 2 * overlap + min(len(extra & words), 3) + (3 if span is not None else 0)
            candidates.append((score, rank, i, ep, turn, span))

    candidates.sort(key=lambda c: (-c[0], c[1], c[2]))
    return _take(candidates, docs, terms, owner_name, max_excerpts=max_excerpts, total_chars=total_chars)


def _take(candidates: list[tuple], docs: dict[str, tuple], terms: set[str], owner_name: str | None, *,
          max_excerpts: int, total_chars: int, taken: set[tuple[str, int]] | None = None,
          excerpt_chars: int = EXCERPT_CHARS, context: bool = True) -> list[Excerpt]:
    """The excerpts for ``candidates`` (``(score, rank, turn index, episode, turn, span)``, best first) within the
    budget, oldest first. ``taken``: ``(episode, turn index)`` already shown elsewhere in the prompt — never twice."""
    chosen: list[Excerpt] = []
    taken = set(taken or ())
    used = 0
    with_context = context
    for score, rank, i, ep, turn, span in candidates:
        if len(chosen) >= max_excerpts or used >= total_chars:
            break
        if (ep, i) in taken:
            continue
        fm, text, turns = docs[ep]
        body = text[turn.content_start:turn.end]
        at = (span.start - turn.content_start) if span is not None else _first_match(body, terms)
        clipped = _clip(body, at, min(excerpt_chars, total_chars - used))
        if len(clipped) < 20 and len(body.strip()) >= 20:
            break
        day = (turn.ts or str(fm.get("timestamp") or "") or episode_day(ep))[:10]
        excerpt = Excerpt(episode=ep, day=day, who=_who(turn, fm, owner_name), text=clipped,
                          order=(day, ep, i), title=str(fm.get("title") or "").strip())
        taken.add((ep, i))
        used += len(clipped)

        def context(j: int) -> tuple[str, str] | None:
            nonlocal used
            if not 0 <= j < len(turns) or (ep, j) in taken:
                return None
            taken.add((ep, j))
            words = _clip(text[turns[j].content_start:turns[j].end], None, CONTEXT_CHARS)
            used += len(words)
            return _who(turns[j], fm, owner_name), words

        if with_context and len(body.strip()) < SHORT_REPLY_CHARS:
            excerpt.before = context(i - 1)
            if excerpt.before is not None:
                excerpt.shown.append(i - 1)
        if with_context and body.rstrip().endswith("?"):
            excerpt.after = context(i + 1)
            if excerpt.after is not None:
                excerpt.shown.append(i + 1)
        chosen.append(excerpt)
    chosen.sort(key=lambda e: e.order)
    return chosen


def shown_turns(excerpts: list[Excerpt]) -> set[tuple[str, int]]:
    """``(episode, turn index)`` of every turn ``excerpts`` put in front of the model, context turns included."""
    return {(e.episode, i) for e in excerpts for i in (e.order[2], *e.shown)}


# --------------------------------------------------------------------------------------------------------------- #
# The search leg: what was said where no page points (2026-10-19), and which of it is current (2026-10-19, depth)
# --------------------------------------------------------------------------------------------------------------- #

#: The conversations the search leg reads, and what it may show from them: its own budget, after the page leg's.
SEARCH_EPISODES = 4
SEARCH_EXCERPTS = 6
SEARCH_CHARS = 3000
#: A count or a list ("how many times …", "which … have I …") needs every conversation that holds it, not the best
#: four (LongMemEval multi-session 0/2, LoCoMo's list questions): past the plain leg's four, up to this many
#: conversations in all, each one short dated line, inside a budget of its own — still bounded, still no model. The
#: plain leg's four are read exactly as for any question, so a value question the gate mistakes for a count ("how
#: many stars do I need") loses nothing.
ENUM_EPISODES = 10
ENUM_EXCERPT_CHARS = 300
ENUM_CHARS = 1800
#: Episode chunks read from the vector index before fusing (a chunk is a window of a conversation, so a few
#: conversations can fill them).
SEARCH_CHUNKS = 16
ENUM_CHUNKS = 32
#: A word said in more than this share of the bank's conversations ranks nothing (the person's own name, a name on
#: every line of a two-person chat, "plan"); the rarer a word, the more a turn holding it counts. A question made only
#: of such words cannot tell one conversation from another, and the leg shows nothing for it.
COMMON_SHARE = 0.5
#: Rows counted per word for its share: past this the word is common in any bank that has them.
DF_CAP = 20000
#: A conversation is on the question's subject when it holds at least this share of the weight of the question's
#: words the best conversation holds, two of them when that one holds two or more, and ranks among the first
#: :data:`SUBJECT_RANKS`. Several such conversations on different days are one subject told over time:
#: the latest carries its current state.
SUBJECT_SHARE = 0.5
#: How far down the fused ranking a conversation on the subject may sit (a count or a list reads them all from here).
SUBJECT_RANKS = 20
#: Conversations kept in the leg for their day: the newest on the subject (one for a plain question, two when the
#: question asks for an outcome or a current value), and a day the question names.
LATEST_SLOTS = {"lookup": 1, "latest": 2}
NAMED_SLOTS = 2
_RRF_K = 60

#: What a question asks for, read from its own words — no model (:func:`question_shape`).
SHAPE_LOOKUP = "lookup"          # one fact: the best conversations, and the newest on the subject
SHAPE_LATEST = "latest"          # an outcome or a current value: the newest on the subject weigh more
SHAPE_ENUMERATE = "enumerate"    # a count or a list: every conversation that holds it, one line each
SHAPE_ANCHORED = "anchored"      # one past occasion (a day it names, the first time): never a later one instead

_ENUMERATE = re.compile(
    r"\b(?:how many|how often|number of|in total|total (?:number|amount|count|cost|time)|"
    r"list (?:all|every|each|the|my)|what are all|name (?:all|every|each)|every (?:time|one)|each time|"
    r"all (?:the|of the|of my|my) \w+)\b"
    r"|\b(?:what|which) (?:\w+ ){0,2}\w+s (?:has|have|did|does|do)\b"
    # Spanish (the owner writes both): cuántos/cuántas, cuántas veces, cuáles, lista de, enumera, todos los/todas las.
    r"|(?<!\w)(?:cu[aá]nt[oa]s|cu[aá]les|cada vez|en total|n[uú]mero de|lista(?:me)? (?:de|todos|todas|los|las)|"
    r"enumera(?:me)?|nombra (?:todos|todas)|tod[oa]s (?:los|las|mis) \w+)(?!\w)")
_LATEST = re.compile(
    r"\b(?:final|finally|end(?:ed)? up|eventually|in the end|outcome|result(?:ed)?|turn(?:ed)? out|"
    r"current(?:ly)?|now|still|latest|most recent(?:ly)?|these days|any ?more|so far|agreed|settled on|"
    r"at the moment|right now|nowadays)\b")
_ANCHORED = re.compile(
    r"\b(?:first|originally|initially|at first|used to|back (?:in|then|when)|previously|earlier|"
    r"before (?:i|we|he|she|they|the)|the (?:conversation|chat|session|time|day) (?:where|when|about|that|we|i))\b")
#: The question's own scaffolding for an outcome or the first time: words the answering conversation rarely repeats
#: ("the final price" is said as "we settled at …"), never a search word.
TENSE_WORDS = frozenset(text_fold.stem(w) for w in (
    "final finally eventually outcome result resulted latest recent recently currently nowadays originally "
    "initially previously first").split())
_MONTHS = {m: i for i, m in enumerate(
    "january february march april may june july august september october november december".split(), start=1)}
_MON = r"(january|february|march|april|may|june|july|august|september|october|november|december|" \
       r"jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)"
_ISO_DAY = re.compile(r"\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b")
_DAY_MONTH = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?(?: of)? " + _MON + r"\b(?:,? (\d{4}))?")
_MONTH_DAY = re.compile(r"\b" + _MON + r" (\d{1,2})(?:st|nd|rd|th)?\b(?:,? (\d{4}))?")
_MONTH_YEAR = re.compile(r"\b" + _MON + r",? (\d{4})\b")
_DAYS_AGO = re.compile(r"\b(\d+|a|one|two|three|four|five|six|seven) days? ago\b")
_SMALL = {"a": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7}


def _month(name: str) -> int:
    return next(v for k, v in _MONTHS.items() if k.startswith(name[:3]))


def named_days(question: str, today=None) -> list[str]:
    """The days (``YYYY-MM-DD``), month-days (``-MM-DD``, any year) and months (``YYYY-MM``) the question names in its
    own words, or relative to ``today`` ("yesterday", "three days ago"). Prefixes of an episode's day: a conversation
    from a named day is the one the question is about."""
    from datetime import timedelta

    q = (question or "").lower()
    out: list[str] = []
    for y, m, d in _ISO_DAY.findall(q):
        out.append(f"{int(y):04d}-{int(m):02d}-{int(d):02d}")
    for d, mon, y in _DAY_MONTH.findall(q):
        if 1 <= int(d) <= 31:
            out.append(f"{int(y):04d}-{_month(mon):02d}-{int(d):02d}" if y else f"-{_month(mon):02d}-{int(d):02d}")
    for mon, d, y in _MONTH_DAY.findall(q):
        if 1 <= int(d) <= 31:
            out.append(f"{int(y):04d}-{_month(mon):02d}-{int(d):02d}" if y else f"-{_month(mon):02d}-{int(d):02d}")
    for mon, y in _MONTH_YEAR.findall(q):
        month = f"{int(y):04d}-{_month(mon):02d}"
        if not any(day.startswith(month) for day in out):   # "9 April 2025" names the day, not all of April
            out.append(month)
    if re.search(r"\b(yesterday|days? ago)\b", q):
        if today is None:
            from api.services.claims import current_day   # the answer's own "today" (a frozen clock in benchmarks)

            today = current_day()
        if re.search(r"\byesterday\b", q):
            out.append((today - timedelta(days=1)).isoformat())
        for n in _DAYS_AGO.findall(q):
            days = min(int(_SMALL.get(n, n)), 36500)   # "99999999 days ago" names no day a bank holds; never a raise
            try:
                out.append((today - timedelta(days=days)).isoformat())
            except OverflowError:
                continue
    return list(dict.fromkeys(out))


def _on_day(day: str, named: list[str]) -> bool:
    return bool(day) and any(day.startswith(n) if not n.startswith("-") else day[4:].startswith(n) for n in named)


def question_shape(question: str) -> str:
    """What ``question`` asks for, from its own words (no model): a count or list (:data:`SHAPE_ENUMERATE`), one past
    occasion (:data:`SHAPE_ANCHORED` — a day it names, "the first time"), an outcome or a current value
    (:data:`SHAPE_LATEST`), else one fact (:data:`SHAPE_LOOKUP`)."""
    q = " ".join((question or "").lower().split())
    if _ENUMERATE.search(q):
        return SHAPE_ENUMERATE
    if named_days(q) or _ANCHORED.search(q):
        return SHAPE_ANCHORED
    if _LATEST.search(q):
        return SHAPE_LATEST
    return SHAPE_LOOKUP


@dataclass
class Searched:
    """The conversations the question's words find, best first, and how much each of its words counts."""

    episodes: list[str]
    weights: dict[str, float]
    shape: str = SHAPE_LOOKUP
    #: Conversations kept for their day: ``latest`` (the newest on the question's subject), ``named`` (a day the
    #: question names).
    kept: dict[str, str] = field(default_factory=dict)
    #: A count or a list: the other conversations on the subject, best first, read one line each.
    more: list[str] = field(default_factory=list)


def search_terms(question: str) -> set[str]:
    """The question's subject words less its scaffolding — names kept: across conversations a name is what tells
    one from another, and a name said everywhere is weighed down by :data:`COMMON_SHARE`, not dropped by hand."""
    terms = text_fold.subject_terms(question)
    return (terms - QUESTION_WORDS - TENSE_WORDS) or terms


def _lexical(memory_path: Path, terms: set[str]) -> tuple[dict[str, float], list[str], dict[str, set[str]]]:
    """``(weights, ranked, held)`` from the word index alone. Every count is over the conversations the leg can show
    — an index-only episode (a watched day, a list save: ruling 30) is neither counted nor ranked, so thousands of
    watched days can't make a word look common or fill the ranking. A word's weight is its rarity across
    conversations; a passage scores the weights of the words it holds; a conversation ranks by its best passage (the
    middle of a long export counts as much as its head), then by the weight of all the words it holds. ``held``: the
    weighted words each ranked conversation holds anywhere."""
    import math

    from api.services import search_index

    # Never the reason an index is built: a bank with no word index yet (a fresh install) has this leg off.
    state = search_index.ensure_fresh(memory_path) if search_index.db_path(memory_path).exists() else ""
    if not terms or state not in ("ready", "stale"):
        return {}, [], {}
    bits = search_index.ROW_BITS
    with search_index.Reader(memory_path) as reader:
        conn = reader.conn
        refs: dict[int, str] = {}
        for doc_id, ref, meta in conn.execute("SELECT id, ref, meta FROM docs WHERE kind = 'episode'"):
            if '"index_only": true' not in (meta or ""):
                refs[int(doc_id)] = str(ref)
        n = len(refs)
        rows_by_term: dict[str, set[int]] = {}
        weights: dict[str, float] = {}
        for t in sorted(terms):
            rows = {int(r) for (r,) in conn.execute(
                f"SELECT rowid FROM pas WHERE pas MATCH ? LIMIT {DF_CAP}", (f'"{t}"*',)) if (int(r) >> bits) in refs}
            df = len({r >> bits for r in rows})
            if df and df <= COMMON_SHARE * n:
                weights[t] = math.log((n + 1) / (df + 0.5))
                rows_by_term[t] = rows
    passage: dict[int, float] = {}
    held: dict[str, set[str]] = {}
    for t, rows in rows_by_term.items():
        for r in rows:
            passage[r] = passage.get(r, 0.0) + weights[t]
            held.setdefault(refs[r >> bits], set()).add(t)
    best: dict[str, float] = {}
    for r, score in passage.items():
        ep = refs[r >> bits]
        best[ep] = max(best.get(ep, 0.0), score)
    ranked = sorted(best, key=lambda ep: (-best[ep], -sum(weights[t] for t in held[ep]), ep))
    return weights, ranked, held


def _reserve(order: list[str], kept: list[str], window: int) -> list[str]:
    """``order`` with ``kept`` inside its first ``window`` places: the best of the rest fill what is left, in order."""
    kept = [ep for ep in dict.fromkeys(kept) if ep in order][:window]
    head = [ep for ep in order if ep not in kept][: window - len(kept)]
    top = [ep for ep in order if ep in head or ep in kept]   # their own relative order
    return top + [ep for ep in order if ep not in top]


def search(memory_path: Path, question: str, *, terms: set[str] | None = None, embed_fn=None,
           indexer=None, today=None) -> Searched:
    """The conversations most likely to hold what ``question`` asks, read from the derived indexes only — never a
    model, never a write, never the question in a log. Two legs, fused by rank: the word index (:func:`_lexical`) and
    the vector index's episode chunks (the question's vector is the page leg's: one embed per Ask, through the
    indexer's per-model query cache — measured, 2026-10-19).

    Then the question's shape (:func:`question_shape`) decides what else stays in the window: the newest
    conversation on the question's subject (one subject told on several days: the later one settled it — the
    outcome after the plan, the agreed price after the listing), a day the question names (never pushed out by a
    later one), or, for a count or a list, every conversation on the subject before any other. Index-only episodes
    (a watched day, a list save) are dropped when their words are read (:func:`gather_search`)."""
    terms = set(terms) if terms is not None else search_terms(question)
    shape = question_shape(question)
    weights: dict[str, float] = {}
    lexical: list[str] = []
    held: dict[str, set[str]] = {}
    try:
        weights, lexical, held = _lexical(memory_path, terms)
    except Exception as exc:  # noqa: BLE001 — the leg is context; its absence never fails an answer (no query logged)
        logger.debug(f"ask search leg: word index unavailable ({type(exc).__name__})")
    semantic: list[str] = []
    try:
        if indexer is None:
            from api.services.vector_index import SqliteVecIndexer

            indexer = SqliteVecIndexer(memory_path, embed_fn=embed_fn) if embed_fn else SqliteVecIndexer(memory_path)
        k = ENUM_CHUNKS if shape == SHAPE_ENUMERATE else SEARCH_CHUNKS
        rows = indexer.search_kinds(question, {"episodes": k}).get("episodes", [])
        semantic = list(dict.fromkeys(Path(str((r.get("metadata") or {}).get("file_path") or "")).stem
                                      for r in rows))
        semantic = [ep for ep in semantic if evidence.is_episode_id(ep)]
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"ask search leg: vector index unavailable ({type(exc).__name__})")
    # With no word to weigh (no word index yet, or only common words) no turn can be told apart: nothing is shown.
    if not weights:
        return Searched(episodes=[], weights={}, shape=shape)
    scores: dict[str, float] = {}
    for ranked_list in (lexical, semantic):
        for rank, ep in enumerate(ranked_list):
            scores[ep] = scores.get(ep, 0.0) + 1.0 / (_RRF_K + rank)
    order = sorted(scores, key=lambda ep: (-scores[ep], ep))
    if not order:
        return Searched(episodes=[], weights=weights, shape=shape)

    # The subject: what the best conversation holds of the question's words, by weight. A conversation is on it when
    # it holds at least half of that weight — the thing without the attribute ("the gravel bike" said again without
    # "price" when it was agreed) is still the subject; one shared common-ish word is not.
    def weight(ep: str) -> float:
        return sum(weights[t] for t in held.get(ep, ()))

    top = next((ep for ep in order if held.get(ep)), order[0])
    floor = SUBJECT_SHARE * (weight(top) or sum(weights.values()))
    # Two of its words when the best conversation holds two or more ("family trip": a chat about any trip is not
    # it), and found by both legs' ranking among the first SUBJECT_RANKS — a word count alone is not a subject.
    need = min(2, len(held.get(top, ())) or 1)
    on_subject = [ep for ep in order[:SUBJECT_RANKS] if len(held.get(ep, ())) >= need and weight(ep) >= floor]

    kept: dict[str, str] = {}
    named = named_days(question, today)
    if named:
        for ep in [ep for ep in order if held.get(ep) and _on_day(episode_day(ep), named)][:NAMED_SLOTS]:
            kept[ep] = "named"
    if shape in LATEST_SLOTS:
        newest = sorted(on_subject, key=lambda ep: (episode_day(ep), ep), reverse=True)
        for ep in newest[: LATEST_SLOTS[shape]]:
            kept.setdefault(ep, "latest")
    if kept:
        order = _reserve(order, [order[0], *kept] if shape != SHAPE_ANCHORED else list(kept), SEARCH_EPISODES)
    more: list[str] = []
    if shape == SHAPE_ENUMERATE:
        # Every other conversation on the subject, best first, one line each (the window shows them oldest first).
        window = set(order[:SEARCH_EPISODES])
        more = [ep for ep in on_subject if ep not in window][: ENUM_EPISODES - SEARCH_EPISODES]
    return Searched(episodes=order, weights=weights, shape=shape, kept=kept, more=more)


def gather_search(memory_path: Path, question: str, found: Searched, *, owner_name: str | None = None,
                  taken: set[tuple[str, int]] | None = None, max_episodes: int = SEARCH_EPISODES,
                  max_excerpts: int = SEARCH_EXCERPTS, total_chars: int = SEARCH_CHARS) -> list[Excerpt]:
    """The turns of the best :func:`search` conversations that hold the question's words, scored as answers
    (:func:`answer_score`: the rarer words counting more, the sentence that states a value, the speaker the question
    is about), oldest first. A conversation kept for its day (the newest on the subject, a day the question names)
    shows its best turn before the others fill the budget by score, so the one that settled the subject is never
    crowded out. A count or a list gives each conversation of the window its own line first — its speaker's own
    statement when they made one — then adds one short line from each further conversation on the subject
    (``found.more``) in a budget of its own. A turn holding only common words is never one. ``taken``: turns the
    page leg already showed.
    Same who-spoke labels, clipping and bounds as :func:`gather`; index-only episodes are skipped (ruling 30)."""
    weights = found.weights
    if not weights or not found.episodes:
        return []
    terms = set(weights)
    # A turn holds a word as the word index found it: at a word's start, any ending ("decid" meets "decided" and
    # "deciding", as `"decid"*` did) — one pattern over the turn's folded text, longest first.
    pattern = re.compile(r"\b(" + "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True)) + ")")
    taken = set(taken or ())
    docs: dict[str, tuple] = {}
    prefs = answer_prefs(question)
    candidates = _scored_turns(memory_path, found.episodes, pattern, weights, docs, max_episodes, prefs)
    candidates.sort(key=lambda c: (-c[0], c[1], c[2]))
    lead: list[tuple] = []
    # A count or a list needs each conversation's own line before any conversation's second one: one rich
    # conversation could otherwise fill the budget while another holding a counted event shows nothing.
    # Its line is the speaker's own statement when they made one — a count of what the person did rests on what they
    # said, not on the agent's reply repeating the question's words (the agent's, for "what did you suggest").
    enumerate_ = found.shape == SHAPE_ENUMERATE
    for ep in dict.fromkeys(list(found.kept) + (list(docs) if enumerate_ else [])):
        best = _first_line(candidates, ep, taken, prefs if enumerate_ else None, docs)
        if best is not None:
            lead.append(best)
    led = {id(c) for c in lead}
    chosen = _take(lead + [c for c in candidates if id(c) not in led], docs, terms, owner_name,
                   max_excerpts=max_excerpts, total_chars=total_chars, taken=taken)
    if found.shape == SHAPE_ENUMERATE:
        taken |= shown_turns(chosen)
        # The window's conversations the budget left without a line, then the further ones on the subject.
        shown_eps = {e.episode for e in chosen}
        rest = [ep for ep in docs if ep not in shown_eps] + [ep for ep in found.more if ep not in docs]
        extra_docs: dict[str, tuple] = {}
        extra = _scored_turns(memory_path, rest, pattern, weights, extra_docs, len(rest), prefs)
        extra.sort(key=lambda c: (-c[0], c[1], c[2]))
        firsts: dict[str, tuple] = {}
        for ep in dict.fromkeys(c[3] for c in extra):
            best = _first_line(extra, ep, taken, prefs, extra_docs)
            if best is not None:
                firsts[ep] = best
        chosen += _take(sorted(firsts.values(), key=lambda c: c[1]), extra_docs, terms, owner_name,
                        max_excerpts=len(firsts), total_chars=ENUM_CHARS, taken=taken,
                        excerpt_chars=ENUM_EXCERPT_CHARS, context=False)
        chosen.sort(key=lambda e: e.order)
    return chosen


#: A question about what the agent said ("the hotel you recommended", "what did you suggest"): the answer is in the
#: agent's turns, not the person's.
_ASKS_AGENT = re.compile(
    r"\byou(?:'ve| have| had)? (?:said|told|mentioned|recommended|suggested|gave|provided|listed|shared|wrote|"
    r"explained|described|named|offered|proposed|came up with)\b|\b(?:did|do|would|could) you (?:say|tell|mention|"
    r"recommend|suggest|give|provide|list|share|write|explain|describe|name|offer|propose)\b|\byour "
    r"(?:recommendation|suggestion|advice|list|answer|reply)s?\b"
    # Spanish: "lo que me dijiste", "el hotel que recomendaste", "tu sugerencia".
    r"|(?<!\w)(?:me |nos )?(?:dijiste|recomendaste|sugeriste|mencionaste|propusiste|diste|explicaste|nombraste|"
    r"contaste|escribiste|listaste|ofreciste|aconsejaste)(?!\w)"
    r"|(?<!\w)tus? (?:recomendaci[oó]n|recomendaciones|sugerencias?|consejos?|respuestas?|lista)(?!\w)")
#: One sentence of a turn (a line break ends one too): where an answer is stated, and where its excerpt is clipped.
_SENTENCE = re.compile(r"[^.!?\n]+(?:[.!?]+|\n|$)")
_NUMBER_WORDS = frozenset(
    "two three four five six seven eight nine ten eleven twelve fifteen twenty thirty forty fifty hundred thousand "
    "dozen half twice dos tres cuatro cinco seis siete ocho nueve diez".split())
_CAPITAL = re.compile(r"(?<![.!?]\s)(?<!^)\b[A-Z][\w'’-]+")
#: How much more a turn counts when it reads like the answer (:func:`answer_score`): the speaker the question is
#: about stating it, a value beside the words (a number, an amount, a name the question does not say), the
#: question's own "recent" / "first" said there; a sentence that only asks counts less than one that states.
PERSON_BONUS = 1.5
BREADTH_SHARE = 0.5
VALUE_BONUS = 1.5
TENSE_BONUS = 1.25
ASKING_FACTOR = 0.5


@dataclass
class Prefs:
    """What the question says about where its answer is (:func:`answer_prefs`) — read from its own words."""

    #: The question asks what the agent said: the agent's turns, else the people's.
    agent: bool = False
    #: The question's own folded words: a capitalized word among them is not a new value.
    said: frozenset = frozenset()
    #: The question's tense words ("recent", "first") as their folded stems: said beside the subject, they mark the
    #: sentence the question is about ("my recent family trip").
    tense: frozenset = frozenset()


def answer_prefs(question: str) -> Prefs:
    q = question or ""
    return Prefs(agent=bool(_ASKS_AGENT.search(q.lower())), said=frozenset(text_fold.words(q)),
                 tense=frozenset(text_fold.stem(w) for w in text_fold.words(q)) & TENSE_WORDS)


_ASKING_START = frozenset(
    "can could would will should shall do does did is are was were am have has had what which who whom whose where when "
    "why how any anything "
    "que como cual cuales cuando donde adonde quien quienes cuanto cuanta cuantos cuantas por puedes podrias puede "
    "podria sabes tienes hay me nos".split())


def _asks(sentence: str) -> bool:
    """The sentence is a question — it ends with "?" and opens like one ("Can you …", "What …"). A statement with a
    tag ("The play I attended was X, have you heard of it?") states its value and is not one."""
    if sentence.lstrip().startswith("¿"):   # Spanish opens its questions; a tag ("…, ¿sabes?") does not
        return True
    if not sentence.rstrip().endswith("?"):
        return False
    first = next(iter(text_fold.words(sentence)), "")
    return first in _ASKING_START


def _has_value(sentence: str, said: frozenset) -> bool:
    """The sentence states a value the question does not: a number, an amount, a number word, or a capitalized
    name that is not the sentence's first word and not one of the question's own words."""
    if any(ch.isdigit() for ch in sentence):
        return True
    if any(w in _NUMBER_WORDS for w in text_fold.words(sentence)):
        return True
    for m in _CAPITAL.finditer(sentence.strip()):
        word = text_fold.fold(m.group(0)).strip("'’-")
        if word not in said and word != "i" and not word.startswith("i'"):
            return True
    return False


def answer_score(body: str, pattern, weights: dict[str, float], role: str, prefs: Prefs) -> tuple[float, int]:
    """``(score, where)`` for one turn: its best sentence's weight of the question's words — more when it states a
    value or says the question's "recent" / "first", less when it only asks — plus half the weight the whole turn
    holds, the sum more when the speaker is the one the question is about (a person, or the agent for "what did you
    suggest"). ``where``: the best sentence's offset in ``body``, where its excerpt is clipped. No model: the words,
    the speaker and the punctuation.

    Why: the best-matching turn of a conversation is often the person's request ("I'm planning a family trip …")
    or the agent's long reply that repeats every word, while the answer is the person's own statement with the value
    ("my recent family trip to Paris", "I'll have four bikes"), which shares fewer of the question's words."""
    held = set(pattern.findall(text_fold.fold(body)))
    base = sum(weights[t] for t in held)
    if base <= 0:
        return 0.0, 0
    best, where = 0.0, 0
    for m in _SENTENCE.finditer(body):
        sentence = m.group(0)
        words = set(pattern.findall(text_fold.fold(sentence)))   # folded per sentence: offsets stay the body's
        if not words:
            continue
        score = sum(weights[t] for t in words)
        if _has_value(sentence, prefs.said):
            score *= VALUE_BONUS
        if prefs.tense and prefs.tense & {text_fold.stem(w) for w in text_fold.words(sentence)}:
            score *= TENSE_BONUS
        if _asks(sentence):
            score *= ASKING_FACTOR
        if score > best:
            best, where = score, m.start() + len(sentence) - len(sentence.lstrip())
    # The best sentence leads; the rest of the turn's words count half, so a long reply that repeats every word of
    # the question does not outrank the short statement that answers it.
    score = best + BREADTH_SHARE * base
    if _speaks(role, prefs):
        score *= PERSON_BONUS
    return score, where


#: An unmarked block of an episode an agent saved through a tool door (:data:`AGENT_SOURCES`): the agent's note,
#: never a person's statement (as :func:`_who` labels it).
AGENT_NOTE = "agent-note"


def _speaker(turn, fm: dict) -> str:
    """Who spoke the turn, for :func:`_speaks`: its role, or :data:`AGENT_NOTE` for an agent's saved note."""
    if turn.role == "user" and turn.marker is None and str(fm.get("source") or "") in AGENT_SOURCES:
        return AGENT_NOTE
    return turn.role


def _speaks(role: str, prefs: Prefs) -> bool:
    """The speaker is the one the question is about: the agent for "what did you suggest", else a person (the owner
    or another speaker in a message conversation)."""
    return role == "assistant" if prefs.agent else role in ("user", "speaker")


def _first_line(candidates: list[tuple], ep: str, taken: set, prefs: Prefs | None, docs: dict) -> tuple | None:
    """The best not-yet-shown candidate of ``ep`` (``candidates`` best first): with ``prefs``, the best one whose
    speaker the question is about, when there is one (an agent's saved note never is a person)."""
    own = [c for c in candidates if c[3] == ep and (ep, c[2]) not in taken]
    if prefs is not None:
        fm = docs[ep][0] if ep in docs else {}
        return next((c for c in own if _speaks(_speaker(c[4], fm), prefs)), own[0] if own else None)
    return own[0] if own else None


def _scored_turns(memory_path: Path, episodes: list[str], pattern, weights: dict[str, float], docs: dict,
                  max_episodes: int, prefs: Prefs | None = None) -> list[tuple]:
    """``(score, rank, turn index, episode, turn, anchor)`` for every turn of the first ``max_episodes`` readable
    conversations of ``episodes`` that holds a weighted word, scored by :func:`answer_score`; ``anchor`` points at
    its best sentence. ``docs`` receives what was read."""
    from api.services import history_index

    prefs = prefs or Prefs()
    candidates: list[tuple] = []
    for ep in episodes:
        if len(docs) >= max_episodes:
            break
        doc = evidence.source_document(memory_path, ep)
        if doc is None:
            continue
        fm, text = doc
        if history_index.is_index_only(fm):
            continue
        gaps = evidence.gap_ranges(fm, text)
        turns = [t for t in evidence.turns(text, stamps=evidence.turn_stamps(fm), override=fm.get("evidence_kind"),
                                           gaps=gaps) if t.role != evidence.GAP_KIND]
        rank = len(docs)
        docs[ep] = (fm, text, turns)
        for i, turn in enumerate(turns):
            body = text[turn.content_start:turn.end]
            score, where = answer_score(body, pattern, weights, _speaker(turn, fm), prefs)
            if score > 0:
                # The excerpt is clipped around the stated answer, not the first word that matched.
                at = turn.content_start + where
                candidates.append((score, rank, i, ep, turn, Pointer(episode=ep, weight=0, start=at, end=at)))
    return candidates


def render(excerpts: list[Excerpt], *, with_episode: bool = False) -> str:
    """The prompt section: one line per excerpt, dated, with who said it; the turn it answers above a short reply.
    ``with_episode`` names each line's conversation (``[ep_…]``) — the search leg's lines, which no page cites."""
    lines: list[str] = []
    for e in excerpts:
        at = f"{e.day} [{e.episode}]" if with_episode else e.day
        if e.before:
            lines.append(f"- {at}, {e.before[0]} (the turn before): \"{e.before[1]}\"")
        lines.append(f"- {at}, {e.who}: \"{e.text}\"")
        if e.after:
            lines.append(f"- {at}, {e.after[0]} (the reply): \"{e.after[1]}\"")
    return "\n".join(lines)
