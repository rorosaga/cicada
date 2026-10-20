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
from typing import Callable
from pathlib import Path

from loguru import logger

from api.services import evidence, text_fold

MAX_EPISODES = 8
MAX_EXCERPTS = 10
EXCERPT_CHARS = 600
TOTAL_CHARS = 6000
#: A count's or a list's breadth (:func:`gather` ``breadth``): one line of at most this many characters from each of
#: up to :data:`ENUM_EPISODES` conversations, then second lines, inside :data:`BREADTH_EXCERPTS` and
#: :data:`BREADTH_CHARS` — a conversation that told two of the things keeps both.
BREADTH_EXCERPT_CHARS = 300
BREADTH_EXCERPTS = 24
BREADTH_CHARS = 7200
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
    #: The turn's own stamp (else the episode's), as stored: :func:`local_day` reads the day it was said, locally.
    stamp: str = ""


def local_day(raw):
    """A stored stamp of any shape (naive local, ``Z``, ``+00:00``, a bare day, a YAML ``datetime``) as the LOCAL
    calendar day it was said — the day ``claims.current_day`` counts in (a turn at 01:30 in Madrid is stored on the
    previous UTC day). ``None`` when unreadable."""
    from datetime import date, datetime

    from api.services import episode_ids

    if isinstance(raw, datetime):
        dt = raw
    else:
        text = str(raw or "").strip()
        if len(text) == 10:
            try:
                return date.fromisoformat(text)
            except ValueError:
                return None
        key = episode_ids.timestamp_sort_key(text or None)
        if not key:
            return None
        try:
            dt = datetime.fromisoformat(key)
        except ValueError:
            return None
    try:
        return dt.astimezone().date()
    except (ValueError, OverflowError, OSError):
        return None


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
    if turn.role == "user" and turn.marker is None and str(fm.get("source") or "") in AGENT_SOURCES:
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
           total_chars: int = TOTAL_CHARS, breadth: bool = False) -> list[Excerpt]:
    """The excerpts for ``question`` from the episodes ``found`` points at, oldest first (see the module doc).
    ``terms``: the question's words to rank turns by (default: all of its subject words). ``breadth`` (a count or
    a list): each episode's best turn first, in rank order, each at most :data:`BREADTH_EXCERPT_CHARS` — one line from
    every conversation the shown items came from before a second from any — then the rest by score."""
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
            # A count or a list follows a shown line to the turn that told it by the line's own words (two of them,
            # or its only one): "went camping at the beach" shares nothing with "what activities …".
            told = breadth and bool(extra) and len(extra & words) >= min(2, len(extra))
            if not overlap and span is None and not told:
                continue
            score = 2 * overlap + min(len(extra & words), 3) + (3 if span is not None else 0)
            candidates.append((score, rank, i, ep, turn, span))

    candidates.sort(key=lambda c: (-c[0], c[1], c[2]))
    if breadth:
        firsts: dict[str, tuple] = {}
        for c in candidates:
            firsts.setdefault(c[3], c)
        lead = sorted(firsts.values(), key=lambda c: c[1])
        led = {id(c) for c in lead}
        candidates = lead + [c for c in candidates if id(c) not in led]
        return _take(candidates, docs, terms, owner_name, max_excerpts=max_excerpts, total_chars=total_chars,
                     excerpt_chars=BREADTH_EXCERPT_CHARS)
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
                          order=(day, ep, i), title=str(fm.get("title") or "").strip(),
                          stamp=str(turn.ts or fm.get("timestamp") or "") or day)
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
#: plain leg's four are read as for any question but for whose turn counts (:data:`OTHER_SPEAKER_SHARE`), so a value
#: question the gate mistakes for a count ("how many stars do I need") keeps its own turns. 2026-10-20: ten → sixteen
#: conversations (the broad sample: LoCoMo multi-hop 147 of 322 answer turns shown, LongMemEval_S multi-session 28 of
#: 71; a LoCoMo bank holds 19–32 conversations).
ENUM_EPISODES = 16
ENUM_EXCERPT_CHARS = 300
ENUM_CHARS = 3600
#: A count or a list about one speaker ("how many … have I …", "what books has <name> read"): another speaker's turn
#: counts this share of its words' weight — the other side of a chat repeats the words ("did you enjoy the wedding?")
#: but never did the thing.
OTHER_SPEAKER_SHARE = 0.5
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
    r"all (?:the|of the|of my|my) \w+)\b")
#: Spanish counts (2026-10-20): "¿cuántas veces …?", "¿cuántos libros …?", "en total", "todas las veces".
#: Not "¿cuántos años tiene …?" (an age) nor "todos los días" (a habit: "¿a qué hora me levanto todos los días?").
_ES_ENUMERATE = re.compile(
    r"\bcu[aá]nt[oa]s\b(?! a[nñ]os\b)|\ben total\b"
    r"|\btod[oa]s (?:las|los|mis) (?!d[ií]as\b|semanas\b|ma[nñ]anas\b|tardes\b|noches\b|meses\b|a[nñ]os\b)\w+")
#: A list asked as a plain question ("where has <name> camped?", "what are <name>'s hobbies?", "which of my friends
#: …", "what kind of indoor activities has …") — read as a count or a list only when nothing else in the question
#: (a named day, an outcome) says what it is (2026-10-20: 15 of LoCoMo's 100 multi-hop list questions were read as
#: one fact).
#: "Which books have I read", "what activities does <name> do" — a list, unless a superlative asks for one of them.
_PLURAL_ASK = re.compile(r"\b(?:what|which) (?:\w+ ){0,2}\w+s (?:has|have|did|does|do)\b")
#: A superlative asks for one thing ("what type of movies does <name> enjoy the most"), never a list.
_ONE_OF = re.compile(r"\b(?:most|favou?rite|best|least|worst)\b")
#: Plural nouns that name one thing about a subject, never items to list ("what are Bob's thoughts on the move",
#: "the chances that it rains", "¿cuáles son tus planes?"), and a choice among several ("which of my laptops is
#: faster") — review of #381. Only the plain-question list forms (:data:`_LIST`) read them.
_ONE_THING = re.compile(
    r"\b(?:thoughts|opinions|views|feelings|reasons|chances|odds|details|plans|intentions|"
    r"pensamientos|opiniones|razones|planes|sentimientos|detalles|intenciones|posibilidades)\b"
    r"|\bwhich of [\w' ]+? (?:is|was)\b")
_LIST = re.compile(
    r"\b(?:what|which) (?:\w+ ){0,3}\w+s (?:has|have|did|does|do|were|are|give|gave)\b"
    r"|\bwhat (?:are|were) (?:the \w+s of )?(?:\w+'s )+\w+s\b"
    r"|\bwhat (?:are|were) the \w+s (?:of|that)\b"
    r"|\bwhere (?:has|have) (?!you\b)[\w-]+ (?:been|\w+ed|made|gone|lived|worked)\b"
    r"|\bwhich of (?:\w+'s|my|his|her|their)\b"
    r"|\bqu[eé] (?:\w+ ){0,2}(?!m[aá]s\b|menos\b)\w+s (?:he|has|ha|hemos|han|hice|hizo|hicimos)\b"
    r"|\bcu[aá]les (?:son|fueron|han sido) (?:(?:los|las|mis|tus|sus|nuestr[oa]s) )?\w+[sz]\b")
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
#: Spanish dates (2026-10-20, the owner's hard set: "entre octubre de 2024 y abril de 2025", "el 5 de marzo").
_ES_MONTHS = {m: i for i, m in enumerate(
    "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split(), start=1)}
_ES_MON = r"(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)"
_ES_DAY_MONTH = re.compile(r"\b(\d{1,2}) de " + _ES_MON + r"\b(?: (?:de|del) (\d{4}))?")
_ES_MONTH_YEAR = re.compile(r"\b" + _ES_MON + r" (?:de |del )?(\d{4})\b")
_SMALL = {"a": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7}


def _month(name: str) -> int:
    if name == "setiembre":
        return 9
    if name in _ES_MONTHS:
        return _ES_MONTHS[name]
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
    for d, mon, y in _ES_DAY_MONTH.findall(q):
        if 1 <= int(d) <= 31:
            out.append(f"{int(y):04d}-{_month(mon):02d}-{int(d):02d}" if y else f"-{_month(mon):02d}-{int(d):02d}")
    for mon, y in _MONTH_YEAR.findall(q) + _ES_MONTH_YEAR.findall(q):
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


# --------------------------------------------------------------------------------------------------------------- #
# Two ends (2026-10-20): a question about two moments needs both in front of the model
# --------------------------------------------------------------------------------------------------------------- #
#
# The owner's hard set: 0 of 7 temporal questions right. "When I first asked about X … and how had it changed by the
# time I later said Y?" found the first conversation and not the later one; "between <date> and <date>" got one end
# right and an adjacent day for the other; the gap came back as a guessed range. One search over the whole question
# ranks the conversation that holds most of its words first, and that is one end. Each end is now searched for on its
# own words (the question split where it names the two moments, each half with what the question says around it),
# the best conversation for each end is kept in the window (on the end's own named month or day), and the prompt
# carries the days and the gap between them computed here — still the derived indexes only, never a model.

SHAPE_TWO_ENDS = "two_ends"      # two moments (first … later, between … and …, which came first): each end its own

#: At most this many ends ("the order of the three events: 'a', 'b' and 'c'").
MAX_ENDS = 3
#: Each end's conversation leads with up to this many of its best turns, by the end's own words.
END_TURNS = 2
#: What a two-ends question adds to the leg's budget: the ends' turns lead, the best of the rest still fit.
ENDS_EXTRA_EXCERPTS = 2
ENDS_EXTRA_CHARS = 1000

_SMALL_NUMBERS = {"a": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
                  "nine": 9, "ten": 10, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7}
_UNIT_DAYS = {"day": 1, "week": 7, "month": 30, "year": 365, "dia": 1, "semana": 7, "mes": 30, "ano": 365}
#: A duration asked for: "how many days", "how long ago", "cuántos días", "cuánto tiempo" (folded: no accents).
_DURATION = re.compile(
    r"\bhow (?:many|much|long)(?: \w+)?(?: of)? (?:days?|weeks?|months?|years?|hours?|time)\b|\bhow long\b"
    r"|\b(?:days?|weeks?|months?|years?) ago\b|\bcuant[oa]s? (?:dias|semanas|meses|anos|horas|tiempo)\b"
    r"|\bhace cuant")
_TIME_CUE = re.compile(
    r"\b(?:days?|weeks?|months?|years?|time|long|passed|elapsed|apart|chang\w*|evolv\w*|shift\w*|first|earlier|"
    r"later|dias|semanas|meses|anos|tiempo|paso|pasaron|transcurri\w*|cambi\w*|evoluciono|primero|despues)\b")
_STOP_AT = r"(?=[,;?!]|\band (?:how|what|when|which|why|did|was|is)\b|\by (?:cuant|como|que|cual|por)|$)"
#: Forms that name the two moments in the question's own words, in the order tried. Each yields ``a`` and ``b``.
_FROM_TO = (
    re.compile(r"\bde ser (?P<a>.+?) a ser (?P<b>.+?)" + _STOP_AT),
    re.compile(r"\b(?:paso|cambio|evoluciono) de (?P<a>.+?) a (?P<b>.+?)" + _STOP_AT),
    re.compile(r"\b(?:go|goes|went|gone|chang\w*|mov\w*|shift\w*|evolv\w*|turn\w*|switch\w*) from (?P<a>.+?) "
               r"(?:to|into) (?P<b>.+?)" + _STOP_AT),
)
_BETWEEN = re.compile(r"\b(?:between|entre) (?P<a>.+?) (?:and|y|e) (?P<b>.+?)" + _STOP_AT)
#: "Which happened first, A or B" asks about the past: a past verb before "first", and "first" closing its clause —
#: never "what should I do first, A or B" (advice) or "which did I prefer, the first draft or the second".
_WHICH_FIRST = (
    re.compile(r"\b(?:which|what)\b[^?]*?\b(?:did|happened|came|was|were|had|occurred)\b[^?]*?\b(?:first|earlier)"
               r"[,:] ?(?P<a>.+?),? or (?P<b>.+?)(?=[?!]|$)"),
    re.compile(r"\b(?:did|was|were|had) (?:i|we) (?P<a>.+?),? or (?P<b>.+?) (?<!\bat )(?:first|earlier)\b"),
    re.compile(r"(?P<a>[^,?]+?) (?:before or after|after or before) (?P<b>.+?)(?=[?!]|$)"),
    re.compile(r"\bque (?:fue|paso|hice|ocurrio|vino) (?:primero|antes)[,:]? (?P<a>.+?),? o (?P<b>.+?)(?=[?!]|$)"),
    re.compile(r"(?P<a>[^,?]+?) antes o despues de (?P<b>.+?)(?=[?!]|$)"),
)
#: "How many days had passed since A when B", "how many days before A did I B".
_SINCE_WHEN = re.compile(r"\b(?:before|after|since|until|antes de|despues de|desde)\b (?P<a>.+?) "
                         r"\b(?:when|did|was|were|had|cuando)\b (?P<b>.+?)(?=[?!]|$)")
#: "First" as the first of two moments — never "first and foremost", "first of all", "primero que nada", or a
#: "First, …" / "Primero, …" that only opens the question.
_FIRST_CUE = re.compile(r"(?<!^)\b(?:first|originally|initially|at first|at the start|in the beginning|al principio|"
                        r"primero|la primera vez|por primera vez|inicialmente|originalmente|en un principio)\b"
                        r"(?! and foremost| of all| off\b| que nada)")
_LATER_CUE = re.compile(r"\b(?:later|by the time|afterwards?|after that|eventually|subsequently|the next time|"
                        r"the second time|when i (?:came|went|got) back|when i returned|cuando volvi|despues|luego|"
                        r"mas tarde|al final|la segunda vez|la siguiente vez)\b")
#: What makes "from A to B", "between A and B" or two named months two moments rather than a route, a pair or a
#: range: a change, a duration or an order said OUTSIDE the matched words ("switching from vim to emacs" is no
#: change cue by its own verb; "the time difference between Madrid and Lima" is no duration).
_ENDS_CUE = re.compile(
    r"\b(?:chang\w*|evolv\w*|shift\w*|cambi\w*|evoluciono|evolucion\w*|how long (?:did|had|has|was|were)\b|"
    r"how (?:many|much) (?:days|weeks|months|years|time)\b(?! ago)|cuanto tiempo|cuant[oa]s (?:dias|semanas|meses|"
    r"anos)\b|passed|elapsed|pasaron|paso|transcurri\w*|apart|first|before|after|earlier|later|again|order|"
    r"primero|antes|despues|luego|orden|de nuevo|otra vez)\b")
#: A Spanish count ("¿cuántas veces…?", "¿cuántos libros…?") is a count, never two ends; "cuántos días" is a duration.
_ES_COUNT = re.compile(r"\bcuant[oa]s (?!dias\b|semanas\b|meses\b|anos\b|horas\b|minutos\b)\w+")
_RETURN_CUE = re.compile(r"\bcuando volvi\b")
_ORDER_CUE = re.compile(r"\b(?:order|first|earliest|latest|before|after|orden|primero|antes|despues)\b")
_QUOTED = re.compile(r"(?:^|(?<=[\s:(]))['\"‘“]([^'\"’”]{3,}?)['\"’”](?=[\s,.;:?!)]|$)")
_THE_DAY = re.compile(r",? (?:and )?the day ")
_APART = re.compile(r"\b(\d+|a|one|two|three|four|five|six|seven|eight|nine|ten) (days?|weeks?|months?|years?) "
                    r"apart\b|\b(\d+|dos|tres|cuatro|cinco|seis|siete) (dias|semanas|meses|anos) (?:de diferencia|"
                    r"de distancia|aparte|entre)")
_PAIR = re.compile(r"\b(?:two|both|dos|ambas|las dos) (?:separate |different |distintas )?"
                   r"(?:conversations?|chats?|sessions?|conversaciones|charlas)\b")
#: A month named alone, as one end's time ("in March", "late July", "en marzo", "a finales de julio").
_EN_MONTH_ALONE = re.compile(r"\b(?:in|during|by|until|since|early|late|mid|end of|beginning of|start of) "
                             r"(january|february|march|april|may|june|july|august|september|october|november|"
                             r"december)\b")
_ES_MONTH_ALONE = re.compile(r"\b" + _ES_MON + r"\b")
#: A two-ends question's own scaffolding: never a word to search an end by.
ENDS_WORDS = frozenset(text_fold.stem(w) for w in (
    "day days week weeks month months year years time times passed pass apart between change changed changing "
    "later earlier earliest latest conversation conversations event events happened happen order late "
    "early mid end beginning each tell told thinking thought approach "
    "january february march april may june july august september october november december "
    "enero febrero marzo abril mayo junio julio agosto septiembre setiembre octubre noviembre diciembre "
    "dias semanas meses anos tiempo paso pasaron pasado cambio cambiado cambiar cambiaron como cuantos cuantas "
    "cuanto cuanta entre cuando volvi vez despues luego tarde final finales principio principios "
    "mediados conversacion conversaciones charla esas esos estas estos dos ser habia fue era sobre hace mas pero "
    "porque donde quien cual cuales forma manera dijeron dije dijo").split())


@dataclass
class End:
    """One moment a question asks about: its own words (``text``), the days or months it names (``days``)."""

    text: str
    days: list[str] = field(default_factory=list)


@dataclass
class Ends:
    """The moments a two-ends question names (two or three, in the question's order), and the context words they
    share. ``pair``: the question names no split, only "two conversations" (``apart_days``: "47 days apart")."""

    ends: list[End]
    shared: str = ""
    pair: bool = False
    apart_days: int | None = None


def _end_terms_strict(text: str) -> set[str]:
    return text_fold.subject_terms(text) - QUESTION_WORDS - ENDS_WORDS


def _end_days(text: str) -> list[str]:
    """The days and months one end names: :func:`named_days` (no relative days) plus a month named alone."""
    out = [d for d in named_days(text, today=None) if d] if not re.search(r"\b(yesterday|days? ago)\b", text) else []
    months = {f"-{_month(m):02d}" for m in _EN_MONTH_ALONE.findall(text) + _ES_MONTH_ALONE.findall(text)}
    for m in sorted(months):
        if not any(d.startswith(m) or d[4:].startswith(m) for d in out):
            out.append(m)
    return out


def _date_spans(q: str) -> list[tuple[int, int]]:
    """Where ``q`` names a day or a month, in order (overlapping mentions merged)."""
    spans: list[tuple[int, int]] = []
    for rx in (_ISO_DAY, _DAY_MONTH, _MONTH_DAY, _MONTH_YEAR, _ES_DAY_MONTH, _ES_MONTH_YEAR, _EN_MONTH_ALONE,
               _ES_MONTH_ALONE):
        spans += [m.span() for m in rx.finditer(q)]
    merged: list[list[int]] = []
    for lo, hi in sorted(spans):
        if merged and lo <= merged[-1][1] + 4:   # "5 de marzo de 2025", "march 3, 2025": one mention
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    return [(lo, hi) for lo, hi in merged]


def _clean(half: str) -> str:
    half = re.sub(r"^(?:[,;:¿¡]|\b(?:and|y|or|o|the day|el dia)\b|\s)+", "", half.strip())
    return re.sub(r"[\s,;:?.!]+$", "", half)


def _split(q: str, at: int, *, shared: str = "") -> Ends | None:
    a, b = _clean(q[:at]), _clean(q[at:])
    if not (_end_terms_strict(a) or _end_days(a)) or not (_end_terms_strict(b) or _end_days(b)):
        return None
    return Ends(ends=[End(a, _end_days(a)), End(b, _end_days(b))], shared=shared)


def two_ends(question: str) -> Ends | None:
    """The moments ``question`` asks about when it asks about two (or three) of them — "first … later", "between A
    and B", "which came first, A or B", "how many days since A when B", "de ser A a ser B", a named month or day for
    each, "two conversations 47 days apart" — else ``None``. Its own words only, no model. A count that is not a
    duration ("how many times between March and July") is a count, never two ends."""
    q = " ".join(text_fold.fold(question or "").split())
    if not q:
        return None
    if ((_ENUMERATE.search(q) or _PLURAL_ASK.search(q)) and not _DURATION.search(q)) or _ES_COUNT.search(q):
        return None

    def cued(m) -> bool:
        return bool(_ENDS_CUE.search(f"{q[:m.start()]} {q[m.end():]}"))

    def matched(m) -> Ends | None:
        a, b = _clean(m.group("a")), _clean(m.group("b"))
        shared = _clean(f"{q[:m.start()]} {q[m.end():]}")
        if not _end_terms_strict(a) and not _end_days(a):
            return None
        if not _end_terms_strict(b) and not _end_days(b):
            return None
        return Ends(ends=[End(a, _end_days(a)), End(b, _end_days(b))], shared=shared)

    for rx in _FROM_TO:
        if (m := rx.search(q)) and cued(m) and (found := matched(m)):
            return found
    if (m := _BETWEEN.search(q)) and (cued(m) or (_end_days(m.group("a")) and _end_days(m.group("b")))):
        if found := matched(m):
            return found
    if _ORDER_CUE.search(q):
        quoted = [x for x in _QUOTED.findall(q) if text_fold.subject_terms(x)]
        if 2 <= len(quoted) <= MAX_ENDS:
            return Ends(ends=[End(x, _end_days(x)) for x in quoted], shared="")
        days = [_clean(x) for x in _THE_DAY.split(q.split(":", 1)[1] if ":" in q else q)[1:]]
        if 2 <= len(days) <= MAX_ENDS and all(text_fold.subject_terms(x) for x in days):
            return Ends(ends=[End(x, _end_days(x)) for x in days], shared="")
    for rx in _WHICH_FIRST:
        if (m := rx.search(q)) and (found := matched(m)):
            return found
    if _DURATION.search(q) and (m := _SINCE_WHEN.search(q)) and (found := matched(m)):
        return found
    first = _FIRST_CUE.search(q)
    later = _LATER_CUE.search(q, first.end()) if first else _RETURN_CUE.search(q)
    if later and (found := _split(q, later.start())):
        if first:   # the cue is the question's, not the moment's words
            head = found.ends[0]
            head.text = " ".join(_clean(head.text.replace(first.group(0), " ", 1)).split())
        return found
    spans = _date_spans(q)
    if len(spans) >= 2 and len({tuple(_end_days(q[lo:hi])) for lo, hi in spans}) >= 2 and _ENDS_CUE.search(q):
        (_, end0), (lo1, _) = spans[0], spans[1]
        cut = max((m.start() for m in re.finditer(r",|\b(?:and|y)\b", q[end0:lo1])), default=None)
        if found := _split(q, end0 + cut if cut is not None else lo1):
            return found
    if m := _APART.search(q):
        n, unit = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        count = int(n) if n.isdigit() else _SMALL_NUMBERS.get(n, 1)
        return Ends(ends=[], shared=q, pair=True, apart_days=count * _UNIT_DAYS.get(unit.rstrip("s"), 1))
    if _PAIR.search(q) and _TIME_CUE.search(q):
        return Ends(ends=[], shared=q, pair=True)
    return None


#: Time elapsed from a moment: "ago", "since", "passed", "how long before" — not a length ("how long is my commute",
#: "how many days did I spend").
_ELAPSED = re.compile(r"\b(?:ago|since|passed|elapsed|how long (?:ago|before|after|since|until))\b"
                      r"|\bhace cuant|\b(?:pasaron|paso|transcurri\w*)\b")


def asks_elapsed(question: str) -> bool:
    """The question asks how much time passed ("how many days ago", "how many months have passed since", "how long
    ago", "¿hace cuántos días…?", "¿cuántos días pasaron…?")."""
    q = " ".join(text_fold.fold(question or "").split())
    return bool(re.search(r"\bhow (?:many|much|long)\b|\bcuant[oa]s?\b", q) and _DURATION.search(q)
                and _ELAPSED.search(q))


def question_shape(question: str) -> str:
    """What ``question`` asks for, from its own words (no model): two moments (:data:`SHAPE_TWO_ENDS`,
    :func:`two_ends`), a count or list (:data:`SHAPE_ENUMERATE`), one past occasion (:data:`SHAPE_ANCHORED` — a day
    it names, "the first time"), an outcome or a current value (:data:`SHAPE_LATEST`), else one fact
    (:data:`SHAPE_LOOKUP`)."""
    q = " ".join((question or "").lower().split())
    if two_ends(q) is not None:
        return SHAPE_TWO_ENDS
    if _ENUMERATE.search(q) or _ES_ENUMERATE.search(q) or (_PLURAL_ASK.search(q) and not _ONE_OF.search(q)):
        return SHAPE_ENUMERATE
    if named_days(q) or _ANCHORED.search(q):
        return SHAPE_ANCHORED
    if _LATEST.search(q):
        return SHAPE_LATEST
    plain = q.replace("`", "'").replace("\u2019", "'")
    if _LIST.search(plain) and not _ONE_OF.search(plain) and not _ONE_THING.search(plain):
        return SHAPE_ENUMERATE
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
    #: Two ends: the best conversation for each moment the question names, in the question's order.
    ends: list["EndPick"] = field(default_factory=list)
    #: A count or a list: how near each of some texts is to the question, by the search model the conversations
    #: were indexed with (:func:`_similarity`) — the page leg ranks a page's items with it. ``None`` without an index.
    similar: "Callable[[list[str]], list[float]] | None" = None


@dataclass
class EndPick:
    """One end of a two-ends question and the conversation kept for it (``None``: nothing holds its words on its day),
    with the weights of the end's own words — the turns it leads with are the ones holding them."""

    label: str
    episode: str | None
    weights: dict[str, float]
    days: list[str] = field(default_factory=list)
    #: The stamp of the end's own best turn in its conversation (set when its turns are read): a session that ran
    #: over several days is dated by the turn that speaks of this moment, not by its first day.
    stamp: str = ""


def search_terms(question: str) -> set[str]:
    """The question's subject words less its scaffolding — names kept: across conversations a name is what tells
    one from another, and a name said everywhere is weighed down by :data:`COMMON_SHARE`, not dropped by hand."""
    terms = text_fold.subject_terms(question)
    return (terms - QUESTION_WORDS - TENSE_WORDS) or terms


def _lexical(memory_path: Path, terms: set[str], *,
             common_share: float = COMMON_SHARE) -> tuple[dict[str, float], list[str], dict[str, set[str]]]:
    """``(weights, ranked, held)`` from the word index alone. Every count is over the conversations the leg can show
    — an index-only episode (a watched day, a list save: ruling 30) is neither counted nor ranked, so thousands of
    watched days can't make a word look common or fill the ranking. A word's weight is its rarity across
    conversations; a passage scores the weights of the words it holds; a conversation ranks by its best passage (the
    middle of a long export counts as much as its head), then by the weight of all the words it holds. ``held``: the
    weighted words each ranked conversation holds anywhere. ``common_share``: the share past which a word ranks
    nothing (:data:`COMMON_SHARE`)."""
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
            if df and df <= common_share * n:
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


def _semantic(indexer, text: str, k: int) -> list[str]:
    """The conversations whose chunks the vector index finds nearest ``text``, best first (``[]`` on any failure)."""
    try:
        rows = indexer.search_kinds(text, {"episodes": k}).get("episodes", [])
    except Exception as exc:  # noqa: BLE001 — the leg is context; its absence never fails an answer
        logger.debug(f"ask search leg: vector index unavailable ({type(exc).__name__})")
        return []
    found = list(dict.fromkeys(Path(str((r.get("metadata") or {}).get("file_path") or "")).stem for r in rows))
    return [ep for ep in found if evidence.is_episode_id(ep)]


#: The most texts :func:`_similarity` embeds for ONE question, across every page it ranks — one allowance, not one
#: per page — each clipped to :data:`SIMILAR_CHARS` (an item's head says what it is about; short texts share the
#: on-device model's packed calls). Measured on EmbeddingGemma 2, warm: 120 texts of 240 characters ≈ 0.3 s
#: (600 characters: 0.74 s; whole long items: ~4 s — review of #381).
SIMILAR_TEXTS = 120
SIMILAR_CHARS = 240


def _similarity(indexer, question: str):
    """``texts -> scores``: each text's cosine nearness to ``question``, embedded as a passage by the model the
    conversations' table was built with (never another space; only a model that runs on this machine —
    :meth:`SqliteVecIndexer.similarity`), each clipped to :data:`SIMILAR_CHARS`, at most :data:`SIMILAR_TEXTS` in
    all for the question — past the allowance a text scores 0. Nothing is stored and nothing is logged; on any
    failure every score is 0, and no later call embeds."""
    left = {"n": SIMILAR_TEXTS, "off": False}

    def similar(texts: list[str]) -> list[float]:
        take = 0 if left["off"] else min(left["n"], len(texts))
        if not take:
            return [0.0] * len(texts)
        head = [" ".join(str(t or "").split())[:SIMILAR_CHARS] for t in texts[:take]]
        left["n"] -= take
        try:
            got = [float(x) for x in indexer.similarity(question, head, kind="episodes")]
            if len(got) != len(head):
                raise ValueError("one score per text")
        except Exception as exc:  # noqa: BLE001 — a ranking aid; its absence never fails an answer
            logger.debug(f"ask similarity skipped ({type(exc).__name__})")
            left["off"] = True
            got = [0.0] * len(head)
        return got + [0.0] * (len(texts) - len(head))

    return similar


def _fuse(*ranked_lists: list[str]) -> tuple[list[str], dict[str, float]]:
    """Reciprocal-rank fusion: the order, and each conversation's fused score."""
    scores: dict[str, float] = {}
    for ranked_list in ranked_lists:
        for rank, ep in enumerate(ranked_list):
            scores[ep] = scores.get(ep, 0.0) + 1.0 / (_RRF_K + rank)
    return sorted(scores, key=lambda ep: (-scores[ep], ep)), scores


def _end_terms(text: str) -> set[str]:
    """An end's own words: its subject words less the question's and the two-ends scaffolding — an ordinal kept
    ("the first class", "la primera clase" is the event's own name; the "first … later" cue is cut from the half)."""
    terms = text_fold.subject_terms(text)
    return (terms - QUESTION_WORDS - ENDS_WORDS) or (terms - QUESTION_WORDS)


#: How many of an end's best conversations :func:`_whole_words_first` reorders.
_REORDER = 3


def _whole_words_first(memory_path: Path, cands: list[str], own: set[str]) -> list[str]:
    """The end's first few conversations, the one whose best turn holds most of the end's words as whole words first
    (the index matches a word's start: "start" also finds "starter", so "making a sourdough starter" ties with
    "started the sourdough starter"); the rest unchanged."""
    head = cands[:_REORDER]
    if len(head) < 2 or not own:
        return cands

    def whole(ep: str) -> int:
        doc = evidence.source_document(memory_path, ep)
        if doc is None:
            return 0
        fm, text = doc
        turns = evidence.turns(text, stamps=evidence.turn_stamps(fm), override=fm.get("evidence_kind"),
                               gaps=evidence.gap_ranges(fm, text))
        return max((len(own & text_fold.subject_terms(text[t.content_start:t.end])) for t in turns
                    if t.role != evidence.GAP_KIND), default=0)

    hits = {ep: whole(ep) for ep in head}
    return sorted(head, key=lambda ep: (-hits[ep], head.index(ep))) + cands[_REORDER:]


def _pick_ends(memory_path: Path, ends: Ends, terms: set[str], weights: dict[str, float], order: list[str],
               held: dict[str, set[str]], on_subject: list[str], indexer) -> list[EndPick]:
    """The best conversation for each end: searched on the end's own words (with the words the question says around
    it; an end that names a day, or has fewer than two words of its own, also carries the whole question's), from the
    end's named day or month when it names one. Two ends never share a conversation while the second has another that
    holds at least half as much of its words — the end surest of its best keeps it. ``ends.pair`` ("two conversations
    47 days apart"): the two conversations on the subject whose days are that far apart (else the two best on
    different days)."""
    if ends.pair:
        on = [ep for ep in on_subject if episode_day(ep)][:SUBJECT_RANKS]
        pairs = [(a, b) for i, a in enumerate(on) for b in on[i + 1:] if episode_day(a) != episode_day(b)]
        if not pairs:
            return []
        if ends.apart_days is not None:
            from datetime import date

            def gap(p) -> int:
                d0, d1 = (date.fromisoformat(episode_day(x)) for x in p)
                return abs(abs((d1 - d0).days) - ends.apart_days)

            best = min(pairs, key=lambda p: (gap(p), on.index(p[0]) + on.index(p[1])))
        else:
            best = pairs[0]
        best = tuple(sorted(best, key=lambda ep: (episode_day(ep), ep)))
        return [EndPick(label=f"conversation {i + 1}", episode=ep, weights=weights) for i, ep in enumerate(best)]

    shared = _end_terms(ends.shared)
    ranked: list[tuple[End, dict[str, float], list[str], dict[str, float], dict[str, set[str]]]] = []
    for end in ends.ends[:MAX_ENDS]:
        own = _end_terms(end.text) | shared
        if end.days or len(own) < 2:
            own |= terms
        try:
            w, lexical, held_e = _lexical(memory_path, own)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"ask two ends: word index unavailable ({type(exc).__name__})")
            w, lexical, held_e = {}, [], {}
        semantic = _semantic(indexer, f"{end.text} {ends.shared}".strip(), SEARCH_CHUNKS) if indexer is not None \
            else []
        fused, scores = _fuse(lexical, semantic)
        cands = [ep for ep in fused if held_e.get(ep)]
        if end.days:
            cands = [ep for ep in cands if _on_day(episode_day(ep), end.days)] or \
                [ep for ep in order if held.get(ep) and _on_day(episode_day(ep), end.days)]
        cands = _whole_words_first(memory_path, cands, own)
        ranked.append((end, w, cands, scores, held_e))

    def strength(i: int, ep: str) -> float:
        _, w, _, _, held_e = ranked[i]
        return sum(w.get(t, 0.0) for t in held_e.get(ep, ()))

    def margin(i: int) -> float:
        _, _, cands, scores, _ = ranked[i]
        if not cands:
            return -1.0
        return scores.get(cands[0], 0.0) - (scores.get(cands[1], 0.0) if len(cands) > 1 else 0.0)

    def best_turn(i: int, ep: str) -> int | None:
        w = ranked[i][1]
        if not w:
            return None
        pattern = re.compile(r"\b(" + "|".join(re.escape(t) for t in sorted(w, key=len, reverse=True)) + ")")
        found = _scored_turns(memory_path, [ep], pattern, w, {}, 1)
        return min(found, key=lambda c: (-c[0], c[2]))[2] if found else None

    chosen: dict[int, str | None] = {}
    for i in sorted(range(len(ranked)), key=lambda i: -margin(i)):
        cands = ranked[i][2]
        first = cands[0] if cands else None
        pick = first
        holders = [j for j, ep in chosen.items() if ep is not None and ep == first]
        if holders:
            # One conversation can hold both moments (a session resumed days later): share it when this end's best
            # turn there is another turn than the holder's; else take the next conversation that holds at least
            # half as much of this end's words.
            mine = best_turn(i, first)
            if mine is None or any(best_turn(j, first) == mine for j in holders):
                taken = set(v for v in chosen.values() if v)
                alt = next((ep for ep in cands if ep not in taken), None)
                if alt is not None and strength(i, alt) >= 0.5 * strength(i, first):
                    pick = alt
        chosen[i] = pick
    return [EndPick(label=end.text, episode=chosen[i], weights=w or weights, days=list(end.days))
            for i, (end, w, _, _, _) in enumerate(ranked)]


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
    ends = two_ends(question) if shape == SHAPE_TWO_ENDS else None
    if ends is not None:
        terms = (terms - ENDS_WORDS) or terms
    weights: dict[str, float] = {}
    lexical: list[str] = []
    held: dict[str, set[str]] = {}
    try:
        weights, lexical, held = _lexical(memory_path, terms)
        if not weights and shape == SHAPE_ENUMERATE:
            # A list over a subject the conversations keep coming back to ("what books has <name> read" in a chat
            # about books): its words are common because the thing is everywhere — they still tell a turn that holds
            # them from one that doesn't, at the low weight their rarity gives.
            weights, lexical, held = _lexical(memory_path, terms, common_share=1.0)
    except Exception as exc:  # noqa: BLE001 — the leg is context; its absence never fails an answer (no query logged)
        logger.debug(f"ask search leg: word index unavailable ({type(exc).__name__})")
    semantic: list[str] = []
    try:
        if indexer is None:
            from api.services.vector_index import SqliteVecIndexer

            indexer = SqliteVecIndexer(memory_path, embed_fn=embed_fn) if embed_fn else SqliteVecIndexer(memory_path)
        k = ENUM_CHUNKS if shape == SHAPE_ENUMERATE else SEARCH_CHUNKS
        semantic = _semantic(indexer, question, k)
    except Exception as exc:  # noqa: BLE001
        indexer = None
        logger.debug(f"ask search leg: vector index unavailable ({type(exc).__name__})")
    # With no word to weigh (no word index yet, or only common words) no turn can be told apart: nothing is shown.
    similar = _similarity(indexer, question) if shape == SHAPE_ENUMERATE and indexer is not None else None
    if not weights:
        return Searched(episodes=[], weights={}, shape=shape, similar=similar)
    order, _ = _fuse(lexical, semantic)
    if not order:
        return Searched(episodes=[], weights=weights, shape=shape, similar=similar)

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
    picks: list[EndPick] = []
    if ends is not None:
        # Each end its own conversation, inside the window beside the best of the whole question.
        picks = _pick_ends(memory_path, ends, terms, weights, order, held, on_subject, indexer)
        for i, pick in enumerate(picks):
            if pick.episode is not None:
                kept.setdefault(pick.episode, f"end {i + 1}")
                if pick.episode not in order:
                    order.append(pick.episode)
                for t, w in pick.weights.items():
                    weights.setdefault(t, w)
    named = named_days(question, today)
    if ends is not None:
        # A day the question names outside every end ("on March 5, how had it changed from …") is still that day's
        # conversation; an outcome or a current value still keeps the newest on the subject.
        end_days = {d for e in ends.ends for d in e.days}
        named = [d for d in named if d not in end_days and not any(d.startswith(e) or e.startswith(d)
                                                                   for e in end_days)]
    if named:
        for ep in [ep for ep in order if held.get(ep) and _on_day(episode_day(ep), named)][:NAMED_SLOTS]:
            kept.setdefault(ep, "named")
    if ends is not None:
        if _LATEST.search(" ".join((question or "").lower().split())):
            newest = sorted(on_subject, key=lambda ep: (episode_day(ep), ep), reverse=True)
            for ep in newest[:1]:
                kept.setdefault(ep, "latest")
        order = _reserve(order, [*kept, order[0]], max(SEARCH_EPISODES, len(kept) + 1))
        return Searched(episodes=order, weights=weights, shape=shape, kept=kept, ends=picks)
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
    return Searched(episodes=order, weights=weights, shape=shape, kept=kept, more=more, similar=similar)


def gather_search(memory_path: Path, question: str, found: Searched, *, owner_name: str | None = None,
                  taken: set[tuple[str, int]] | None = None, max_episodes: int = SEARCH_EPISODES,
                  max_excerpts: int = SEARCH_EXCERPTS, total_chars: int = SEARCH_CHARS) -> list[Excerpt]:
    """The turns of the best :func:`search` conversations that hold the question's words, the rarer words counting
    more, oldest first. A conversation kept for its day (the newest on the subject, a day the question names) shows
    its best turn before the others fill the budget by score, so the one that settled the subject is never crowded out.
    A count or a list then adds one short line from each further conversation on the subject (``found.more``) in a
    budget of its own. A turn holding only common words is never one. ``taken``: turns the page leg already showed.
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
    if found.ends:
        # Every kept conversation (each end, a named day, the newest) is read, beside the best of the question.
        max_episodes = max(max_episodes, len(found.kept) + 1)
    candidates = _scored_turns(memory_path, found.episodes, pattern, weights, docs, max_episodes)
    candidates.sort(key=lambda c: (-c[0], c[1], c[2]))
    lead: list[tuple] = []
    if found.ends:
        # Two ends: each end's conversation leads with its best turns by the end's OWN words — the turn that says
        # the later thing, not the one that repeats the earlier — so both moments reach the model.
        max_excerpts += ENDS_EXTRA_EXCERPTS
        total_chars += ENDS_EXTRA_CHARS
        led_turns: set[tuple[str, int]] = set()
        per_end: list[list[tuple]] = []
        for pick in found.ends:
            if pick.episode is None or not pick.weights:
                continue
            own = re.compile(r"\b(" + "|".join(re.escape(t) for t in sorted(pick.weights, key=len, reverse=True))
                             + ")")
            mine: dict[str, tuple] = {}
            turns_e = _scored_turns(memory_path, [pick.episode], own, pick.weights, mine, 1)
            docs.update({k: v for k, v in mine.items() if k not in docs})
            turns_e.sort(key=lambda c: (-c[0], c[2]))
            if turns_e:   # the end is dated by its own best turn, whether or not another end shows it
                fm_e = docs[turns_e[0][3]][0]
                pick.stamp = str(turns_e[0][4].ts or fm_e.get("timestamp") or "")
            mine_lead: list[tuple] = []
            for c in [c for c in turns_e if (c[3], c[2]) not in taken and (c[3], c[2]) not in led_turns][:END_TURNS]:
                body = docs[c[3]][1][c[4].content_start:c[4].end]
                at = _first_match(body, set(pick.weights))
                span = Pointer(episode=c[3], weight=0, start=c[4].content_start + at) if at is not None else None
                mine_lead.append((c[0], -1, c[2], c[3], c[4], span))
                led_turns.add((c[3], c[2]))
            per_end.append(mine_lead)
        # Each end's best turn first, then each end's second: a tight budget still shows every end.
        for k in range(END_TURNS):
            lead += [turns[k] for turns in per_end if len(turns) > k]
        lead_keys = {(c[3], c[2]) for c in lead}
        candidates = [c for c in candidates if (c[3], c[2]) not in lead_keys]
    end_eps = {p.episode for p in found.ends}
    for ep in found.kept:
        if ep in end_eps:
            continue
        best = next((c for c in candidates if c[3] == ep and (ep, c[2]) not in taken), None)
        if best is not None:
            lead.append(best)
    enumerate_ = found.shape == SHAPE_ENUMERATE
    if enumerate_:
        # A count or a list: the turns of whoever it is about first — the other side of a chat repeats the
        # question's words but never did the thing. The window is otherwise read as for any question (a value
        # question the gate takes for a count — "how many stars do I need" — keeps its own turns); the breadth below
        # gives every other conversation its line.
        asked = asked_about(question, owner_name)
        candidates = _about_first(candidates, docs, asked, weights, owner_name)
    led = {id(c) for c in lead}
    chosen = _take(lead + [c for c in candidates if id(c) not in led], docs, terms, owner_name,
                   max_excerpts=max_excerpts, total_chars=total_chars, taken=taken)
    if enumerate_:
        taken |= shown_turns(chosen)
        # The window's conversations the budget left without a line, then the further ones on the subject.
        shown_eps = {e.episode for e in chosen}
        rest = [ep for ep in docs if ep not in shown_eps] + [ep for ep in found.more if ep not in docs]
        extra_docs: dict[str, tuple] = {}
        extra = _about_first(_scored_turns(memory_path, rest, pattern, weights, extra_docs, len(rest)), extra_docs,
                             asked, weights, owner_name)
        firsts: dict[str, tuple] = {}
        for c in extra:
            if c[3] not in firsts and (c[3], c[2]) not in taken:
                firsts[c[3]] = c
        chosen += _take(sorted(firsts.values(), key=lambda c: c[1]), extra_docs, terms, owner_name,
                        max_excerpts=len(firsts), total_chars=ENUM_CHARS, taken=taken,
                        excerpt_chars=ENUM_EXCERPT_CHARS, context=False)
        chosen.sort(key=lambda e: e.order)
    return chosen


#: First-person words: a question in them is about the person this memory belongs to ("how many … have I …").
_FIRST_PERSON = frozenset("i me my mine myself i'm i've i'd i'll im ive yo mi mis me conmigo".split())
#: The person named the way an agent speaks of them ("what did the user decide").
_SELF_PHRASES = re.compile(r"\b(?:the user|the owner|el usuario|la usuaria|el dueno|la duena)\b")
#: Spanish says the first person in the verb, not a pronoun: "¿qué libros he leído?", "¿cuántas veces fui…?",
#: "¿qué compré?" — the perfect with "he/hemos", the common irregular preterites, and a preterite's stressed "-é"/
#: "-í" ending (read on the question as written, accents kept), less the words that end so without being one.
_ES_FIRST_PERSON = re.compile(
    r"\b(?:he|hemos) \w+(?:ado|[ií]do|to|cho|so)\b"
    r"|\b(?:fui|fuimos|hice|hicimos|tuve|estuve|vi|di|puse|dije|supe|quise|pude|vine|traje|anduve)\b"
    r"|\b\w{2,}(?:é|í)\b")
_NOT_A_VERB = frozenset("qué porqué café bebé josé puré sé té fué aquí allí ahí así sí mí rubí esquí maniquí "
                        "jabalí colibrí israelí marroquí iraní paquistaní".split())
#: Words that ask about the agent's side of a chat ("what did you recommend").
_SECOND_PERSON = frozenset("you your yours yourself assistant".split())


@dataclass(frozen=True)
class Asked:
    """Who a question is about, from its own words: the person (first person, or their name), the agent (second
    person), and the folded words it holds — another speaker is asked about when the question names them."""

    words: frozenset[str]
    person: bool
    agent: bool


def asked_about(question: str, owner_name: str | None = None) -> Asked:
    words = frozenset(text_fold.words(question))
    low = " ".join((question or "").lower().split())
    spanish = any(m.group(0) not in _NOT_A_VERB for m in _ES_FIRST_PERSON.finditer(low))
    person = (bool(words & _FIRST_PERSON) or _names(owner_name or "", words) or bool(_SELF_PHRASES.search(low))
              or spanish)
    return Asked(words=words, person=person, agent=bool(words & _SECOND_PERSON))


def _names(name: str, words: frozenset[str]) -> bool:
    """Whether ``words`` name ``name``: all of it, or its first word — "Bob" names "Bob Example"; a surname two people
    share names neither."""
    own = text_fold.words(name)
    return bool(own) and (set(own) <= words or own[0] in words)


def _turn_asked(turn, fm: dict, asked: Asked) -> bool:
    """Whether ``turn`` is said by someone ``asked`` names. An agent's saved note is nobody's."""
    if turn.role == "user":
        return asked.person and not (turn.marker is None and str(fm.get("source") or "") in AGENT_SOURCES)
    if turn.role == "assistant":
        return asked.agent
    if turn.role == "speaker":
        label = (turn.marker or "").split(":", 1)[-1]
        corr = fm.get("correspondent") if isinstance(fm.get("correspondent"), dict) else {}
        return _names(label, asked.words) or _names(str(corr.get("name") or ""), asked.words)
    return False


def _about_first(candidates: list[tuple], docs: dict, asked: Asked, weights: dict[str, float],
                 owner_name: str | None = None) -> list[tuple]:
    """``candidates`` (:func:`_scored_turns`' rows) best first, where the question asks about some of a
    conversation's speakers and not all of them: a turn by someone else is weighed at :data:`OTHER_SPEAKER_SHARE`,
    less the weight of the asked speakers' names it holds — said by someone else a name addresses them ("Bob, which
    sports do you play?") and tells nothing; a turn holding nothing more is dropped. Else unchanged."""
    by_ep: dict[str, list[tuple]] = {}
    for c in candidates:
        by_ep.setdefault(c[3], []).append(c)
    out: list[tuple] = []
    for ep, rows in by_ep.items():
        fm, text, turns = docs[ep]
        spoken = [t for t in turns if t.role in ("user", "assistant", "speaker")]
        said = {(t.role, t.marker) for t in spoken}
        on = {(t.role, t.marker) for t in spoken if _turn_asked(t, fm, asked)}
        if not on or on == said:
            out += rows
            continue
        names: set[str] = set()
        for t in spoken:
            if (t.role, t.marker) in on:
                names |= _name_terms(t, fm, owner_name)
        names &= set(weights)
        for c in rows:
            score = c[0]
            if (c[4].role, c[4].marker) not in on:
                if names:
                    body = text_fold.fold(text[c[4].content_start:c[4].end])
                    score -= sum(weights[n] for n in names if re.search(r"\b" + re.escape(n), body))
                score *= OTHER_SPEAKER_SHARE
            if score > 1e-9:
                out.append((score, *c[1:]))
    out.sort(key=lambda c: (-c[0], c[1], c[2]))
    return out


def _name_terms(turn, fm: dict, owner_name: str | None) -> set[str]:
    """The search words of the name of whoever said ``turn``."""
    if turn.role == "user":
        return text_fold.subject_terms(owner_name or "")
    if turn.role == "speaker":
        corr = fm.get("correspondent") if isinstance(fm.get("correspondent"), dict) else {}
        return (text_fold.subject_terms((turn.marker or "").split(":", 1)[-1].replace("-", " "))
                | text_fold.subject_terms(str(corr.get("name") or "")))
    return set()


def _scored_turns(memory_path: Path, episodes: list[str], pattern, weights: dict[str, float], docs: dict,
                  max_episodes: int) -> list[tuple]:
    """``(score, rank, turn index, episode, turn, None)`` for every turn of the first ``max_episodes`` readable
    conversations of ``episodes`` that holds a weighted word; ``docs`` receives what was read."""
    from api.services import history_index

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
            held = set(pattern.findall(text_fold.fold(text[turn.content_start:turn.end])))
            score = sum(weights[t] for t in held)
            if score > 0:
                candidates.append((score, rank, i, ep, turn, None))
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
