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
          max_excerpts: int, total_chars: int, taken: set[tuple[str, int]] | None = None) -> list[Excerpt]:
    """The excerpts for ``candidates`` (``(score, rank, turn index, episode, turn, span)``, best first) within the
    budget, oldest first. ``taken``: ``(episode, turn index)`` already shown elsewhere in the prompt — never twice."""
    chosen: list[Excerpt] = []
    taken = set(taken or ())
    used = 0
    for score, rank, i, ep, turn, span in candidates:
        if len(chosen) >= max_excerpts or used >= total_chars:
            break
        if (ep, i) in taken:
            continue
        fm, text, turns = docs[ep]
        body = text[turn.content_start:turn.end]
        at = (span.start - turn.content_start) if span is not None else _first_match(body, terms)
        clipped = _clip(body, at, min(EXCERPT_CHARS, total_chars - used))
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

        if len(body.strip()) < SHORT_REPLY_CHARS:
            excerpt.before = context(i - 1)
            if excerpt.before is not None:
                excerpt.shown.append(i - 1)
        if body.rstrip().endswith("?"):
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
# The search leg: what was said where no page points (2026-10-19)
# --------------------------------------------------------------------------------------------------------------- #

#: The conversations the search leg reads, and what it may show from them: its own budget, after the page leg's.
SEARCH_EPISODES = 4
SEARCH_EXCERPTS = 6
SEARCH_CHARS = 3000
#: Matching passages read from the word index, and episode chunks from the vector index, before fusing.
SEARCH_PASSAGES = 150
SEARCH_CHUNKS = 12
#: A word said in more than this share of the bank's conversations ranks nothing (the person's own name, a name on
#: every line of a two-person chat, "plan"); the rarer a word, the more a turn holding it counts. A question made only
#: of such words cannot tell one conversation from another, and the leg shows nothing for it.
COMMON_SHARE = 0.5
#: Rows counted per word for its share: past this the word is common in any bank that has them.
DF_CAP = 20000
_RRF_K = 60


@dataclass
class Searched:
    """The conversations the question's words find, best first, and how much each of its words counts."""

    episodes: list[str]
    weights: dict[str, float]


def search_terms(question: str) -> set[str]:
    """The question's subject words less its scaffolding — names kept: across conversations a name is what tells
    one from another, and a name said everywhere is weighed down by :data:`COMMON_SHARE`, not dropped by hand."""
    terms = text_fold.subject_terms(question)
    return (terms - QUESTION_WORDS) or terms


def search(memory_path: Path, question: str, *, terms: set[str] | None = None, embed_fn=None) -> Searched:
    """The conversations most likely to hold what ``question`` asks, read from the derived indexes only — never a
    model, never a write, never the question in a log. Two legs, fused by rank: the word index's passages that hold
    any of the question's words (bm25 over the whole text, so the middle of a long export is as findable as its
    head), and the vector index's episode chunks. Index-only episodes (a watched day, a list save) are dropped when
    their words are read (:func:`gather_search`)."""
    import math

    from api.services import search_index

    terms = set(terms) if terms is not None else search_terms(question)
    weights: dict[str, float] = {}
    lexical: list[str] = []
    try:
        # Never the reason an index is built: a bank with no word index yet (a fresh install) has this leg off.
        state = search_index.ensure_fresh(memory_path) if search_index.db_path(memory_path).exists() else ""
        if terms and state in ("ready", "stale"):
            with search_index.Reader(memory_path) as reader:
                n = int(reader.conn.execute("SELECT count(*) FROM docs WHERE kind = 'episode'").fetchone()[0])
                for t in sorted(terms):
                    df = int(reader.conn.execute(
                        f"SELECT count(DISTINCT r >> {search_index.ROW_BITS}) FROM "
                        f"(SELECT rowid AS r FROM pas WHERE pas MATCH ? LIMIT {DF_CAP})", (f'"{t}"*',)).fetchone()[0])
                    if df and df <= COMMON_SHARE * n:
                        weights[t] = math.log((n + 1) / (df + 0.5))
                ranked = sorted(weights)
                if ranked:
                    match = " OR ".join(f'"{t}"*' for t in ranked)
                    rows = reader.passages(match, SEARCH_PASSAGES, recent_first=False)
                    docs = reader.docs(list(dict.fromkeys(d for _r, d, *_ in rows)))
                    lexical = list(dict.fromkeys(docs[d].ref for _r, d, *_ in rows
                                                 if d in docs and docs[d].kind == "episode"))
    except Exception as exc:  # noqa: BLE001 — the leg is context; its absence never fails an answer (no query logged)
        logger.debug(f"ask search leg: word index unavailable ({type(exc).__name__})")
    semantic: list[str] = []
    try:
        from api.services.vector_index import SqliteVecIndexer

        indexer = SqliteVecIndexer(memory_path, embed_fn=embed_fn) if embed_fn else SqliteVecIndexer(memory_path)
        rows = indexer.search_kinds(question, {"episodes": SEARCH_CHUNKS}).get("episodes", [])
        semantic = list(dict.fromkeys(Path(str((r.get("metadata") or {}).get("file_path") or "")).stem
                                      for r in rows))
        semantic = [ep for ep in semantic if evidence.is_episode_id(ep)]
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"ask search leg: vector index unavailable ({type(exc).__name__})")
    scores: dict[str, float] = {}
    for ranked_list in (lexical, semantic):
        for rank, ep in enumerate(ranked_list):
            scores[ep] = scores.get(ep, 0.0) + 1.0 / (_RRF_K + rank)
    order = sorted(scores, key=lambda ep: (-scores[ep], ep))
    # With no word to weigh (no word index yet, or only common words) no turn can be told apart: nothing is shown.
    return Searched(episodes=order if weights else [], weights=weights)


def gather_search(memory_path: Path, question: str, found: Searched, *, owner_name: str | None = None,
                  taken: set[tuple[str, int]] | None = None, max_episodes: int = SEARCH_EPISODES,
                  max_excerpts: int = SEARCH_EXCERPTS, total_chars: int = SEARCH_CHARS) -> list[Excerpt]:
    """The turns of the best :func:`search` conversations that hold the question's words, the rarer words counting
    more, oldest first. A turn holding only common words is never one. ``taken``: turns the page leg already showed.
    Same who-spoke labels, clipping and bounds as :func:`gather`; index-only episodes are skipped (ruling 30)."""
    from api.services import history_index

    weights = found.weights
    if not weights or not found.episodes:
        return []
    terms = set(weights)
    # A turn holds a word as the word index found it: at a word's start, any ending ("decid" meets "decided" and
    # "deciding", as `"decid"*` did) — one pattern over the turn's folded text, longest first.
    pattern = re.compile(r"\b(" + "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True)) + ")")
    candidates: list[tuple] = []
    docs: dict[str, tuple] = {}
    for ep in found.episodes:
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
    candidates.sort(key=lambda c: (-c[0], c[1], c[2]))
    return _take(candidates, docs, terms, owner_name, max_excerpts=max_excerpts, total_chars=total_chars,
                 taken=taken)


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
