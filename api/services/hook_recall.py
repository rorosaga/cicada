"""Implicit recall through the harnesses' own hooks (G149).

G105 took capture away from the chatting model: the harness's Stop hook saves
every session whether or not a model calls ``cicada_save_episode``. Recall
never got the same treatment. ``cicada_recall``, ``cicada_ask`` and the rest
reach a model only when it chooses to call them, and a skipped call is silent
(G149; G105's own measurement was zero MCP invocations in 12 days). This
module is what the SessionStart and UserPromptSubmit hooks
(``api/hooks/recall.py`` → ``POST /capture/hook-context``) put in front of the
model instead:

* SessionStart → the connection primer (G75, ``handshake.load_or_build``)
  under a "From Cicada" header. This is G76(b)(iv)'s unshipped half, and it
  replaces ``HOOK_POINTER``'s request that the model call a tool (R-H8).
* UserPromptSubmit → at most three pages the message NAMES (R-H2), each with
  its one-line summary and at most two current claims with their dates, plus
  at most one open inbox question about them. The note is ≤ 400 tokens, or
  nothing (R-H5).

Rails:
* Engine-free: FTS reads from the derived index (G136), plus one query
  embedding only when the on-device embedder is already loaded (R-H4).
* Read-only: nothing here writes a bank.
* The prompt is never logged, stored or sent to telemetry (G136 K9, R-H10),
  so nothing on this path calls ``logger.exception``. Loguru's ``diagnose``
  would print the prompt from a frame's locals.
* A miss injects nothing.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

from loguru import logger

from api.services import (
    bank_registry, continuity, continuity_sessions, episode_ids, handshake, mcp_tools, recall_text, search_index,
    state_dictionary, telemetry, text_fold,
)

# Budgets (R-H5, R-H6).
PROMPT_BUDGET_S = 0.300
PRIMER_BUDGET_S = 0.800
HYBRID_RESERVE_S = 0.150
MAX_TOKENS = 400
MAX_PAGES = 3
MAX_CLAIMS_PER_PAGE = 2
NAME_CHARS = 80
SUMMARY_CHARS = 140
CLAIM_CHARS = 140
QUESTION_CHARS = 120
# The prompt window (R-H5); PROMPT_MAX_CHARS is the route's hard limit (a 422 past it).
PROMPT_MAX_CHARS = 20_000
HEAD_CHARS = 6_000
TAIL_CHARS = 2_000
MAX_TERMS = 48
# The candidate cut (G149 final review). Eligibility is applied in SQL before
# it, but eligible pages that can never count as named — one-word concepts and
# skills — still compete on bm25, and short titles win: at 40 a prompt naming
# 45 of them crowded out the person it also named. `docs()` is one IN query and
# `mention_strength` a dict lookup per row, so 400 keeps the p95 (latency test).
CANDIDATES = 400
MAX_NAME_WORDS = 8
MIN_WORD_CHARS = 3
# The floor (R-H2).
SINGLE_WORD_TYPES = frozenset({"person", "project", "company", "tool", "location"})
SKIP_TYPES = frozenset({"media", "directory", "deadline"})
LIVE_STATUSES = frozenset({"active", "decaying"})
# Freshness and memory (R-H7).
FRESHNESS_S = 30.0
RECENT_TURNS = 2
MAX_SESSIONS = 512
MODEL_TTL_S = 60.0
SEMANTIC_K = 30
SEMANTIC_CHARS = 2_000

REASONS = ("injected", "primer", "no_terms", "no_match", "recently_shown", "index_not_ready", "no_bank",
           "timeout", "error", "reading")
# G110 slice 1a (plan C4): where the last session in this folder stopped.
#: SessionStart sources that get a continuity block; resume/compact/fork carry their
#: own history, and a missing or unknown source is treated as unknown — no block
#: (fail closed: an older hook that never sends it must not inject into a resume).
CONTINUITY_SOURCES = ("startup", "clear")
SESSION_SOURCES = ("startup", "resume", "clear", "compact", "fork")
#: Tokens the primer leaves free when a block will ride beside it.
CONTINUITY_RESERVE = 300
#: The registry's slice of a request's deadline; the time kept after assembly
#: for composition; the least left for the post-assembly `continues` write.
REGISTRY_SLICE_S = 0.05
ASSEMBLY_RESERVE_S = 0.12
CONTINUES_MIN_S = 0.03
CONTINUITY_STATES = ("latest", "explicit", "ambiguous", "none", "skipped_source", "no_room", "deadline", "error")
REGISTRY_STATES = ("ok", "busy", "skipped", "error", "unavailable", "none")

#: Folded words that name nothing (R-H2, R-H3): English and Spanish function
#: words plus the verbs and nouns every coding prompt uses. A name made only of
#: them is never a mention; a term that is one never becomes an FTS candidate.
STOPWORDS = frozenset("""
a about above after again all also am an and any are as at be because been before being below between both but by
can cannot could did do does doing done down during each else ever every few for from further get gets getting give
go goes going gone got had has have having he her here hers him his how however i if in into is it its just let lets
like made make makes many may me might more most much must my need needs no nor not now of off ok okay on once only
or other our ours out over own please quite rather really same see seem she should so some still such sure than
thank thanks that the their theirs them then there these they thing things this those though through thus to too
under until up upon us use used using very via want wants was way we well were what whatever when where whether which
while who whom whose why will with within without would yes yet you your yours yourself
add check fix help look show tell write run try new old one two first last next today tomorrow yesterday time file
files code change changes update work working
al algo alguna algun como con contra cual cuando del desde donde ella ellas ellos entre era esa ese eso esta estas
este esto estos fue hay las les los mas muy nada nos otra otro para pero poco por porque que quien sea ser sin sobre
son sus tambien tengo una uno unos gracias hola hacer puedes quiero
""".split())


@dataclass(frozen=True)
class Injection:
    """What one hook firing gets: the note (or ``None``), the pages it shows
    (what the session window remembers), and why, as an enum from ``REASONS``
    that the ledger and ``recall.log`` carry instead of text."""

    text: str | None
    injected: tuple[str, ...] = ()
    reason: str = "no_match"
    inbox_id: str | None = None
    # G110: enums for the ledger, request-scoped (never a shared counter).
    continuity: str = "none"
    rendering: str = "none"
    registry: str = "none"

    @property
    def tokens(self) -> int:
        """The chars/4 proxy the handshake uses (its R10): no tokenizer offline."""
        return len(self.text) // 4 if self.text else 0

    @classmethod
    def none(cls, reason: str) -> "Injection":
        return cls(None, (), reason)


@dataclass(frozen=True)
class PageNote:
    """One page as a note shows it."""

    id: str
    name: str
    type: str
    summary: str
    claims: tuple[tuple[str, str | None], ...] = ()


def prompt_window(prompt: str) -> str:
    """The part of a prompt the hook reads (R-H5): all of it up to 8,000
    characters, else the first 6,000 and the last 2,000. A question typed after
    a pasted log sits at the end, and a 1 MB paste must not cost the budget."""
    prompt = prompt or ""
    if len(prompt) <= HEAD_CHARS + TAIL_CHARS:
        return prompt
    return prompt[:HEAD_CHARS] + "\n" + prompt[-TAIL_CHARS:]


def prompt_terms(prompt: str) -> tuple[list[str], list[str]]:
    """``(words, terms)``: the window's folded words in order (phrase matching)
    and its distinct content terms for the FTS candidate read (R-H3), taken from
    the END backwards, because the question usually closes the message."""
    words = text_fold.words(prompt_window(prompt))
    terms: list[str] = []
    seen: set[str] = set()
    for w in reversed(words):
        if len(w) < MIN_WORD_CHARS or w in STOPWORDS or w.isdigit() or w in seen:
            continue
        seen.add(w)
        terms.append(w)
        if len(terms) == MAX_TERMS:
            break
    return words, terms


def clip(text: str, limit: int) -> str:
    """Whitespace collapsed, cut on a word boundary with "…" past ``limit``."""
    flat = " ".join(str(text or "").split())
    if len(flat) <= limit:
        return flat
    cut = flat.rfind(" ", 0, limit - 1)
    return flat[: cut if cut > limit // 2 else limit - 1].rstrip() + "…"


def _says(words: list[str], positions: dict[str, list[int]], phrase: list[str]) -> bool:
    n = len(phrase)
    return any(words[i:i + n] == phrase for i in positions.get(phrase[0], ()))


def mention_strength(words: list[str], positions: dict[str, list[int]], meta: dict) -> int:
    """How many words of this page's name, or its best alias, the message says
    in a row. 0 when nothing it says passes the floor (R-H2).

    A name is matched whole, folded the way the index folds it, anywhere in the
    prompt window. A name of two words or more needs at least one real word
    (≥ 3 characters, not a stopword, not a number), so "The One" is not named
    by every "the one". A one-word name counts only for the types one word
    names (a person, a project, a company, a tool, a place): a concept called
    "Memory" is not named by "a memory leak"."""
    etype = str(meta.get("type") or "concept")
    best = 0
    for label in [meta.get("name") or "", *(meta.get("aliases") or [])]:
        phrase = text_fold.words(str(label))
        if not phrase or len(phrase) > MAX_NAME_WORDS or len(phrase) <= best:
            continue
        if not any(len(w) >= MIN_WORD_CHARS and w not in STOPWORDS and not w.isdigit() for w in phrase):
            continue
        if len(phrase) == 1 and etype not in SINGLE_WORD_TYPES:
            continue
        if _says(words, positions, phrase):
            best = len(phrase)
    return best


def _eligible(doc: search_index.Doc, owner: str | None) -> bool:
    meta = doc.meta
    return (doc.kind == "entity" and doc.ref != owner
            and str(meta.get("status") or "active") in LIVE_STATUSES
            and str(meta.get("type") or "concept") not in SKIP_TYPES)


def _rank_key(meta: dict, strength: int, bm25: float) -> tuple:
    """The longer name said first, then a one-word-nameable type, then the
    page's confidence, then FTS's own bm25 (lower is better)."""
    return (-strength, 0 if meta.get("type") in SINGLE_WORD_TYPES else 1,
            -float(meta.get("confidence") or 0.0), bm25)


def current_claims(rows: list[tuple[str, dict]]) -> list[tuple[str, str | None]]:
    """At most two CURRENT claims, newest first, each with the day it became
    true (R-H5). Closed and superseded claims are history, not recall, and a
    done happening is born closed (G141), so it drops out with them."""
    live = [(text, p) for text, p in rows
            if text.strip() and isinstance(p, dict) and not p.get("valid_to") and not p.get("superseded_by")]
    live.sort(key=lambda r: (str(r[1].get("valid_from") or ""), float(r[1].get("confidence") or 0.0)),
              reverse=True)
    return [(clip(text, CLAIM_CHARS), str(p.get("valid_from") or "")[:10] or None)
            for text, p in live[:MAX_CLAIMS_PER_PAGE]]


def _page_note(doc: search_index.Doc, claim_rows: list[tuple[str, dict]]) -> PageNote | None:
    meta = doc.meta
    claims = tuple(current_claims(claim_rows))
    summary = clip(str(meta.get("summary") or ""), SUMMARY_CHARS)
    if not claims and not summary:
        return None
    return PageNote(doc.ref, clip(str(meta.get("name") or doc.ref), NAME_CHARS),
                    str(meta.get("type") or "concept"), summary, claims)


def compose(pages: list[PageNote], question: str | None) -> str:
    lines = [recall_text.RECALL_HEADER]
    for p in pages:
        lines.append(f"- {p.name} ({p.type}, `{p.id}`)" + (f": {p.summary}" if p.summary else ""))
        lines += [f"  · {text}" + (f" (since {since})" if since else "") for text, since in p.claims]
    if question:
        lines.append(question)
    lines.append(recall_text.RECALL_FOOTER)
    return "\n".join(lines)


def fit(pages: list[PageNote], question: str | None) -> tuple[str, list[PageNote], str | None]:
    """The note within ``MAX_TOKENS`` (R-H5). Cuts, in this order, until it
    fits: each page's second claim (the last page first), the inbox line, every
    page after the first, the summaries to 60 characters, the claims. Returns
    the text and what survived, so the ledger and the session window record
    only what the model was shown. ``("", [], None)`` if even a header, one
    name line and the footer cannot fit (a pathological page id)."""
    pages = list(pages)

    def over() -> bool:
        return len(compose(pages, question)) // 4 > MAX_TOKENS

    for i in reversed(range(len(pages))):
        if not over():
            break
        if len(pages[i].claims) > 1:
            pages[i] = replace(pages[i], claims=pages[i].claims[:1])
    if over():
        question = None
    while over() and len(pages) > 1:
        pages.pop()
    if over():
        pages = [replace(p, summary=clip(p.summary, 60)) for p in pages]
    if over():
        pages = [replace(p, claims=()) for p in pages]
    if over():
        return "", [], None
    return compose(pages, question), pages, question


def _open_question(reader: search_index.Reader, pages: list[PageNote], today: str) -> tuple[str | None, str | None]:
    """At most one open inbox item about the pages shown (R-H5), chosen by the
    SAME filter ``cicada_check_nudges(entity_ids=…)`` applies
    (``mcp_tools.nudge_visible``) over the index's inbox rows. A pointer to
    the card, never the card. A follow-up's question is synthesised at read
    (G141 PJ-6) and is not in the index, so it reads "(a follow-up)"."""
    names = {p.id: p.name for p in pages}
    items = [d for d in reader.inbox_docs()
             if mcp_tools.nudge_visible(d.meta, wanted=frozenset(names), today=today)]
    if not items:
        return None, None
    items.sort(key=lambda d: (-float(d.meta.get("priority") or 0.0), d.ref))
    item = items[0]
    entity_id = str(item.meta.get("entity_id") or "")
    words = "" if item.meta.get("kind") == "followup" else clip(str(item.meta.get("question") or ""), QUESTION_CHARS)
    return recall_text.question_line(names[entity_id], item.ref, entity_id, words), item.ref


def _owner_id(memory_path: Path) -> str | None:
    """The person's own page (G117, via ``_state.md``'s cursor). The primer
    carries it already, and "I" would otherwise name it in every message."""
    state = state_dictionary.read_state(memory_path) or {}
    return str(state.get("owner_id") or "").strip() or None


_MODELS: dict[str, tuple[float, str | None]] = {}
_MODELS_LOCK = threading.Lock()


def _recorded_model(memory_path: Path) -> str | None:
    """The embedding model this bank's vectors were built with (``index_meta``),
    re-read at most once a minute, because opening the vector db loads an
    extension."""
    key, now = str(memory_path), time.monotonic()
    with _MODELS_LOCK:
        hit = _MODELS.get(key)
    if hit and now - hit[0] < MODEL_TTL_S:
        return hit[1]
    from api.services.vector_index import SqliteVecIndexer

    try:
        # The ENTITY table's model — the one the hook queries (audit 2026-10-05 P2-4).
        model = SqliteVecIndexer(memory_path).kind_model("entities")
    except Exception:  # noqa: BLE001 — no vectors is an ordinary state
        model = None
    with _MODELS_LOCK:
        _MODELS[key] = (now, model)
    return model


def _semantic_ranks(memory_path: Path, prompt: str) -> dict[str, int] | None:
    """Each page's rank by the stored vectors, or ``None`` unless the bank's
    embedder runs on this Mac and is already loaded (R-H4)."""
    from api.services import providers

    model = _recorded_model(memory_path)
    embed = providers.warm_local_embed_fn(model)
    if embed is None:
        return None
    from api.services.vector_index import SqliteVecIndexer

    try:
        rows = SqliteVecIndexer(memory_path, embed_fn=embed, model_name=model).search_kinds(
            prompt_window(prompt)[:SEMANTIC_CHARS], {"entities": SEMANTIC_K}).get("entities", [])
    except Exception:  # noqa: BLE001 — the lexical order stands
        return None
    return {Path(str((r.get("metadata") or {}).get("file_path") or "")).stem: i for i, r in enumerate(rows)}


def prompt_context(memory_path: Path, prompt: str, *, recent: frozenset[str] = frozenset(),
                   deadline: float | None = None, clock=time.monotonic) -> Injection:
    """The UserPromptSubmit note for one message, or ``Injection.none(reason)``.

    ``recent`` is the session's window (R-H7): pages named again within it step
    aside. ``deadline`` is a ``clock()`` value, the end of the route's budget:
    the stored-vector re-rank starts only with ``HYBRID_RESERVE_S`` left."""
    memory_path = Path(memory_path)
    words, terms = prompt_terms(prompt)
    if not terms:
        return Injection.none("no_terms")
    if search_index.ensure_fresh(memory_path, max_age_s=FRESHNESS_S) not in ("ready", "stale"):
        return Injection.none("index_not_ready")
    owner = _owner_id(memory_path)
    positions: dict[str, list[int]] = {}
    for i, w in enumerate(words):
        positions.setdefault(w, []).append(i)
    with search_index.Reader(memory_path) as reader:
        rows = reader.name_candidates(terms, CANDIDATES, statuses=LIVE_STATUSES, skip_types=SKIP_TYPES,
                                       exclude_ref=owner)
        docs = reader.docs([d for d, _ in rows])
        ranked: list[tuple[tuple, int, search_index.Doc]] = []
        for doc_id, bm25 in rows:
            doc = docs.get(doc_id)
            if doc is None or not _eligible(doc, owner):
                continue
            strength = mention_strength(words, positions, doc.meta)
            if strength:
                ranked.append((_rank_key(doc.meta, strength, bm25), strength, doc))
        if not ranked:
            return Injection.none("no_match")
        ranked.sort(key=lambda r: r[0])
        fresh = [(strength, doc) for _key, strength, doc in ranked if doc.ref not in recent]
        if not fresh:
            return Injection.none("recently_shown")
        if len(fresh) > MAX_PAGES and deadline is not None and deadline - clock() >= HYBRID_RESERVE_S:
            ranks = _semantic_ranks(memory_path, prompt)
            if ranks:
                # R-H4: the vectors order pages the message named equally
                # loudly; they never add one it did not name.
                fresh.sort(key=lambda r: (-r[0], ranks.get(r[1].ref, len(ranks))))
        notes: list[PageNote] = []
        for _strength, doc in fresh:
            note = _page_note(doc, reader.claims_of(doc.id))
            if note is not None:
                notes.append(note)
            if len(notes) == MAX_PAGES:
                break
        if not notes:
            return Injection.none("no_match")
        question, inbox_id = _open_question(reader, notes, date.today().isoformat())
    text, shown, kept = fit(notes, question)
    if not text:
        return Injection.none("no_match")
    return Injection(text, tuple(p.id for p in shown), "injected", inbox_id if kept else None)


def session_primer(memory_path: Path, harness: str) -> Injection:
    """The SessionStart note: the connection primer (G75) under the "From
    Cicada" header. It is the text MCP ``initialize`` sends, cached the same way
    (``handshake.load_or_build``), because Claude Code truncates an MCP server's
    instructions (R-H8) and a harness that never asks for ``cicada_handshake``
    should still start informed. The handshake's ≤ 1,800-token budget keeps it
    inside both harnesses' caps. ``handshake.record`` is not called: its row
    lands in the events file and would tick the app's consumption domain."""
    variant = harness if harness in handshake.VARIANTS else "generic"
    text, _meta = handshake.load_or_build(Path(memory_path), variant=variant)
    return Injection(f"{recall_text.PRIMER_HEADER}\n\n{text}", (), "primer")


class RecentPages:
    """Per-session memory of what the last ``turns`` prompt firings showed
    (R-H7). Process-local, bounded to ``sessions`` (least recently used out)
    and thread-safe: the route reads it on the loop and ``respond`` resets it
    in a worker thread."""

    def __init__(self, turns: int = RECENT_TURNS, sessions: int = MAX_SESSIONS):
        self._turns = turns
        self._sessions = sessions
        self._lock = threading.Lock()
        self._data: OrderedDict[str, deque] = OrderedDict()

    def recent(self, session_id: str) -> frozenset[str]:
        with self._lock:
            window = self._data.get(session_id)
            return frozenset().union(*window) if window else frozenset()

    def remember(self, session_id: str, ids) -> None:
        with self._lock:
            window = self._data.pop(session_id, None) or deque(maxlen=self._turns)
            window.append(frozenset(ids))
            self._data[session_id] = window
            while len(self._data) > self._sessions:
                self._data.popitem(last=False)

    def reset(self, session_id: str) -> None:
        with self._lock:
            self._data.pop(session_id, None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


RECENT = RecentPages()


class _ReadingSeen:
    """Per-session memory of how many waiting links the hook last mentioned (G166).

    The waiting count is per request and never written to ``_state.md`` (it is
    machine-wide state outside the bank); this only keeps the sentence from
    repeating every turn. A session hears it again when MORE of the person's own
    asks are waiting than it was last told about, or when pages of allowed sites
    grew by ``REPEAT_STEP`` or more (a long-lived session is not re-told for every
    save). Process-local, bounded, thread-safe."""

    #: How much the derived (allowed-site) count must grow before a running session hears it again.
    REPEAT_STEP = 10

    def __init__(self, sessions: int = MAX_SESSIONS):
        self._sessions = sessions
        self._lock = threading.Lock()
        self._data: OrderedDict[str, tuple[int, int]] = OrderedDict()

    def told(self, session_id: str) -> int:
        with self._lock:
            return self._data.get(session_id, (0, 0))[0]

    def told_asks(self, session_id: str) -> int:
        with self._lock:
            return self._data.get(session_id, (0, 0))[1]

    def remember(self, session_id: str, waiting: int, asks: int | None = None) -> None:
        with self._lock:
            held = self._data.pop(session_id, (0, 0))
            self._data[session_id] = (waiting, held[1] if asks is None else asks)
            while len(self._data) > self._sessions:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


READING_SEEN = _ReadingSeen()
#: The slice of the route's budget the reading count leaves free, so a count that runs late
#: gives up (unknown) rather than costing the page note its answer.
READING_RESERVE_S = 0.04


def waiting_links(memory_path: Path, *, include_words_origin: bool = True) -> int:
    """How many links are waiting for an agent to read — 0 unless agent reading is
    on. The person's asks, plus saved pages of sites they allowed that Cicada's own
    reader could not read (``reading_queue``). Engine-free, and inside the hook's
    budget: the derived part is counted only when the bank's page cache is warm (a
    cold cache counts the asks and warms in the background, so the next prompt
    counts the rest)."""
    from api.services import reading_queue

    return reading_queue.count_waiting(memory_path, warm_only=True, include_words_origin=include_words_origin)


def with_reading_note(inj: Injection, memory_path: Path, session_id: str, *, event: str,
                      deadline: float | None = None) -> Injection:
    """G166: append one sentence — "N links are waiting in Cicada's reading queue for
    an agent to read" — to the note (or make it the whole note), only while agent
    reading is on and more links wait than this session was last told (see
    ``_ReadingSeen``). Per request, never stored, never in ``_state.md``. It rides
    beside the page note rather than inside its 400-token budget: it is one
    sentence, and it is what makes the person's "Ask an agent" reach an agent that
    was never told to look."""
    line, seen = reading_line_for(memory_path, session_id, event=event, deadline=deadline)
    if line is None:
        return inj
    READING_SEEN.remember(session_id, *seen)
    if inj.text:
        return replace(inj, text=f"{inj.text}\n\n{line}")
    return replace(inj, text=f"{recall_text.READING_HEADER}\n{line}", reason="reading")


def reading_line_for(memory_path: Path, session_id: str, *, event: str,
                     deadline: float | None = None) -> tuple[str | None, tuple[int, int] | None]:
    """The reading sentence this request would carry, and the ``(waiting,
    asks)`` to remember IF it is sent — the caller remembers only what it
    actually returns (G110: the SessionStart compositor may drop it, and then
    the first prompt must still hear it)."""
    from api.services import reading_queue

    asks, derived = reading_queue.counts(memory_path, warm_only=True,
                                         deadline=None if deadline is None else deadline - READING_RESERVE_S)
    known = derived is not None  # a cold cache leaves the derived part unknown, never zero
    waiting = asks + (derived or 0)
    told = READING_SEEN.told(session_id)
    told_asks = READING_SEEN.told_asks(session_id)
    if known and waiting < told:
        # The queue drained since this session was told: forget the higher count,
        # so the next ask counts as new instead of hiding behind it.
        READING_SEEN.remember(session_id, waiting, asks)
        told, told_asks = waiting, asks
    elif not known and asks < told_asks:
        READING_SEEN.remember(session_id, told, asks)
        told_asks = asks
    if waiting <= 0:
        return None, None
    if event == "user_prompt_submit" and told > 0:
        new_ask = asks > told_asks
        grew = known and waiting - told >= READING_SEEN.REPEAT_STEP
        if not (new_ask or grew):
            return None, None
    return recall_text.reading_line(waiting), (waiting, asks)


def _slice(deadline: float, seconds: float) -> float:
    return min(deadline, time.monotonic() + seconds)


def session_start_note(memory_path: Path, *, harness: str, session_id: str, cwd: str | None, source: str | None,
                       bank_paths, deadline: float) -> Injection:
    """The whole SessionStart note (G110 slice 1a, plan C4): the primer, where
    the last session in this folder stopped, and the reading sentence — one
    compositor, measured as the final string, inside ``handshake.MAX_TOKENS``.

    The block is assembled only for ``startup``/``clear`` (never for a missing
    or unknown ``source``) and a ``cwd``; it reads the pinned ``memory_path`` only. When a block is
    sent for one session (not a question) and time remains, the registry
    records ``continues`` for this session (first write wins)."""
    ctx, state = None, "skipped_source"
    if source in CONTINUITY_SOURCES and cwd:
        try:
            ctx = continuity.assemble(memory_path, bank_paths=bank_paths, harness=harness, session_id=session_id,
                                      cwd=cwd, deadline=deadline - ASSEMBLY_RESERVE_S)
            state = "none"
        except Exception as exc:  # noqa: BLE001 — K9: the class, never the message
            logger.warning(f"hook-context: continuity failed ({type(exc).__name__})")
            state = "error"
    has_block = ctx is not None and (ctx.chosen is not None or ctx.selection.kind == "ambiguous")
    variant = harness if harness in handshake.VARIANTS else "generic"
    primer, _meta = handshake.load_or_build(Path(memory_path), variant=variant,
                                            reserve=CONTINUITY_RESERVE if has_block else 0)
    line, seen = reading_line_for(memory_path, session_id, event="session_start", deadline=deadline)
    block_for = (lambda room: continuity.startup_block(ctx, max_chars=room)) if has_block else None
    text, rendering, reading_kept = recall_text.compose_note(recall_text.PRIMER_HEADER, primer, block_for=block_for,
                                                             reading=line, max_tokens=handshake.MAX_TOKENS)
    if reading_kept and seen:
        READING_SEEN.remember(session_id, *seen)
    if has_block:
        if rendering == "none":
            state = "no_room"
        else:
            state = ctx.selection.kind
    elif ctx is not None and not ctx.complete:
        state = "deadline"
    if rendering not in ("none", "ambiguous") and ctx is not None and ctx.chosen is not None \
            and deadline - time.monotonic() >= CONTINUES_MIN_S:
        # Its own slice, short of the deadline: a held lock never costs the note.
        continuity_sessions.apply(memory_path, bank_paths=bank_paths, harness=harness, session_id=session_id,
                                  events={"continues": ctx.chosen.episode_id},
                                  deadline=_slice(deadline - CONTINUES_MIN_S / 2, REGISTRY_SLICE_S))
    return Injection(text, (), "primer", continuity=state, rendering=rendering)


def respond(root: Path, *, event: str, harness: str, session_id: str, prompt: str,
            deadline: float, cwd: str | None = None, source: str | None = None,
            start: str | None = None) -> tuple[Injection, str | None]:
    """The route's one worker call: the bank a capture would write into
    (``bank_registry.capture_bank``, R-H16) — resolved ONCE and pinned for the
    whole request — then the primer or the note. SessionStart resets the
    session's window (R-H7): after compact or clear the earlier notes are gone
    from the model's context.

    G110 slice 1a: before any assembly, one bounded registry transaction records
    the session start (``started_at``, the cwd's hash) or the prompt's arrival
    (``last_prompt_at``) — ``start`` is the request's arrival time — inside a
    slice of the deadline; a busy or slow registry never costs the answer."""
    root = Path(root)
    target = bank_registry.capture_bank(root)
    if target is None:
        return Injection.none("no_bank"), None
    bank_paths = continuity_sessions.bank_paths_for(root)
    start = start or episode_ids.utc_now_iso()
    if event == "session_start":
        RECENT.reset(session_id)
        READING_SEEN.remember(session_id, 0, 0)
        events = {"started_at": start}
        if cwd:
            events["cwd_hash"] = continuity_sessions.cwd_hash(cwd)
        registry = continuity_sessions.apply(target.path, bank_paths=bank_paths, harness=harness,
                                             session_id=session_id, events=events,
                                             deadline=_slice(deadline, REGISTRY_SLICE_S))
        note = session_start_note(target.path, harness=harness, session_id=session_id, cwd=cwd,
                                  source=source if source in SESSION_SOURCES else None, bank_paths=bank_paths,
                                  deadline=deadline)
        return replace(note, registry=registry), target.name
    registry = continuity_sessions.apply(target.path, bank_paths=bank_paths, harness=harness, session_id=session_id,
                                         events={"last_prompt_at": start}, deadline=_slice(deadline, REGISTRY_SLICE_S))
    note = prompt_context(target.path, prompt, recent=RECENT.recent(session_id), deadline=deadline)
    note = with_reading_note(note, target.path, session_id, event=event, deadline=deadline)
    return replace(note, registry=registry), target.name


LATENCY_BUCKETS = ((50, "<50"), (100, "50-100"), (200, "100-200"), (300, "200-300"))
TOKEN_BUCKETS = ((0, "0"), (100, "1-100"), (200, "101-200"), (300, "201-300"), (400, "301-400"))


def _bucket(value: int, buckets, top: str) -> str:
    return next((label for limit, label in buckets if value <= limit), top)


def _model_id(model: str | None) -> str | None:
    """A model id as the harness sent it, only when it is id-shaped (D7)."""
    m = str(model or "").strip()
    return m if m and len(m) <= 80 and all(c.isalnum() or c in "._:/-[]" for c in m) else None


def record(event: str, harness: str, result: Injection, *, latency_ms: int, model: str | None,
           bank: str | None) -> None:
    """One ``hook_recall`` ledger row (R-H9): ids, enums and buckets only,
    filed beside ``read``. Never raises: the ledger never costs a prompt."""
    try:
        telemetry.record(telemetry.UsageEvent(
            kind=telemetry.HOOK_RECALL_KIND, stage="hook_recall", bank=bank, invocations=0, billing="free",
            refs={"harness": harness, "event": event, "reason": result.reason,
                  "injected": len(result.injected), "entity_ids": list(result.injected),
                  "inbox": result.inbox_id is not None,
                  "tokens": _bucket(result.tokens, TOKEN_BUCKETS, ">400"),
                  "latency": _bucket(latency_ms, LATENCY_BUCKETS, ">300"),
                  "model": _model_id(model),
                  # G110: request-scoped enums only.
                  "continuity": result.continuity if result.continuity in CONTINUITY_STATES else "none",
                  "rendering": result.rendering if result.rendering in ("full", "compact", "pointer", "ambiguous",
                                                                          "none") else "none",
                  "registry": result.registry if result.registry in REGISTRY_STATES else "none"}))
    except Exception:  # noqa: BLE001
        pass


def reset() -> None:
    """Forget every session window and cached model id (tests)."""
    RECENT.clear()
    READING_SEEN.clear()
    with _MODELS_LOCK:
        _MODELS.clear()
