"""G136 — search everywhere, the server half: lexical + semantic retrieval.

What ``GET /search`` runs (in a threadpool — R6 §4.2 found it blocking the
event loop), and what MCP recall reads without re-deriving it (the G136
hand-off, landed with G140 Q-R1: ``lexical_entity_hits`` /
``claim_subject_hits`` are the keyword and claim legs in the exact shape
``mcp_tools.recall`` reads).

Two modes (round-3 design §3.2):

* ``prefix`` — the palette's per-keystroke pass. FTS5 only: it never builds
  a vector indexer, never embeds, never touches ``providers._EMBED_CACHE``
  (R3 P1: a typeahead must not run EmbeddingGemma per character). Budget
  p95 ≤ 50 ms at 2,000 entities / 1,500 episodes, pinned by
  ``test_search_latency.py``.
* ``hybrid`` — the idle pass. The same lexical legs fused by reciprocal rank
  with the stored vectors (ONE query embedding for every kind,
  ``SqliteVecIndexer.search_kinds``), plus claims as a third entity leg
  mapped to their subject (R3 P2). Budget 200 ms (G58).

Ranking inside a kind mirrors the app's ``QuickMatch`` (design §1.2) over the
fields the index holds — whole field > field prefix > word-start prefix, with
weights name 1.0 / alias 0.9 / keyword 0.7 / body 0.4 — so the palette's
local tier and its server tier never disagree about one name (G136 R7).

Rails: engine-free (no LLM anywhere in search); the query is never logged,
stored or sent to telemetry (K9); a missing or broken index degrades to the
``bank_index`` frontmatter cache and says so in ``index_state``, never a 500.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Iterable

from loguru import logger

from api.models.schemas import SearchHit, SearchResponse
from api.services import bank_index, evidence, inbox_questions, inbox_service, search_index, text_fold

KINDS = ("entity", "claim", "episode", "media", "inbox")
_KIND_ALIASES = {
    "entity": "entity", "entities": "entity",
    "claim": "claim", "claims": "claim", "belief": "claim", "beliefs": "claim",
    "episode": "episode", "episodes": "episode", "conversation": "episode", "conversations": "episode",
    "media": "media", "source": "media", "sources": "media", "paper": "media", "papers": "media",
    "inbox": "inbox",
}
MODES = ("prefix", "hybrid")
MAX_PER_KIND = 20
SNIPPET_CHARS = 160
RRF_K = 60
# Candidates read per kind before re-ranking and filtering (the archived
# tier, the media split, fusion), so a filter never starves a group.
CANDIDATE_FACTOR = 4
# Inbox matches read before the visibility filter. An inbox is hundreds of
# items at most, so this is "all of them" in practice — and when it is not,
# the kind's total is omitted rather than guessed.
INBOX_SCAN = 200
_TIERS = 5  # QuickMatch: score = Σ (5 − tier) × weight


def parse_kinds(kinds: str | None, indexes: str | None = None) -> list[str]:
    """``kinds`` csv → canonical kinds, in the fixed group order.

    Accepts plural and palette names (``conversations``, ``beliefs``,
    ``sources``, ``papers``, …). The legacy ``indexes`` parameter — sent by
    ``APIClient.search`` as ``indexes=entities`` and never read before G136 —
    is honoured only when ``kinds`` is absent. Nothing recognised → today's
    behaviour, entities only.
    """
    raw = kinds if kinds is not None and kinds.strip() else (indexes or "")
    wanted = {_KIND_ALIASES.get(part.strip().lower()) for part in raw.split(",")}
    return [k for k in KINDS if k in wanted] or ["entity"]


def rrf_scores(*ranked_lists: list[dict], k: int = RRF_K, key: Callable[[dict], str | None] | None = None):
    """``(scores, first_hit_per_id)`` of reciprocal-rank fusion."""
    key = key or (lambda hit: hit.get("entity_id") or hit.get("id"))
    scores: dict[str, float] = {}
    keep: dict[str, dict] = {}
    for lst in ranked_lists:
        for rank, hit in enumerate(lst):
            hid = key(hit)
            if not hid:
                continue
            scores[hid] = scores.get(hid, 0.0) + 1.0 / (k + rank)
            keep.setdefault(hid, hit)
    return scores, keep


def rrf_fuse(*ranked_lists: list[dict], k: int = RRF_K, key: Callable[[dict], str | None] | None = None) -> list[dict]:
    """Reciprocal-rank fusion: score(id) = Σ 1/(k + rank), first-seen hit kept.

    The one reciprocal-rank fusion: ``/search`` and MCP recall
    (``mcp_tools._rrf_fuse`` is this function, G140 Q-R1).
    """
    scores, keep = rrf_scores(*ranked_lists, k=k, key=key)
    return [keep[h] for h in sorted(scores, key=lambda h: -scores[h])]


def _fuse(*key_lists: list[str]) -> tuple[list[str], dict[str, float]]:
    scores, _ = rrf_scores(*[[{"id": key} for key in keys] for keys in key_lists])
    return sorted(scores, key=lambda h: -scores[h]), scores


def _dedupe(keys: Iterable) -> list:
    seen: set = set()
    out = []
    for key in keys:
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def quick_score(tokens: list[str], fields: Iterable[tuple[str, float, str]]) -> tuple[float, str]:
    """QuickMatch's score over the fields the server holds (design §1.2).

    Per token, the best of: the whole field equals the query (tier 0), the
    field starts with the token (1), a word in the field starts with it (2) —
    the tiers an FTS prefix match can witness. Initials and mid-word
    substrings (QuickMatch tiers 3–4) have no index behind them server-side
    (G136 R7); the app's local tier covers them. A token FTS matched that no
    short field shows was matched in the body, and is credited as a body
    word-start, (5 − 2) × 0.4. Returns the score and the label of the field
    that contributed most.
    """
    folded = [(text_fold.fold(t), w, label) for t, w, label in fields if t]
    whole = " ".join(tokens)
    total, best_pts, best_label = 0.0, -1.0, "body"
    for tok in tokens:
        pts, label = (_TIERS - 2) * 0.4, "body"
        for text, weight, flabel in folded:
            words = text_fold.words(text)
            if text == tok or " ".join(words) == whole:
                tier = 0
            elif text.startswith(tok):
                tier = 1
            elif any(w.startswith(tok) for w in words):
                tier = 2
            else:
                continue
            if (_TIERS - tier) * weight > pts:
                pts, label = (_TIERS - tier) * weight, flabel
        total += pts
        if pts > best_pts:
            best_pts, best_label = pts, label
    return total, best_label


def snippet_window(text: str | None, tokens: list[str], limit: int = SNIPPET_CHARS) -> tuple[str, list[list[int]]]:
    """A ≤ ``limit``-character window of ``text`` (whitespace collapsed)
    around the first match, ``…`` where it was cut, and the match offsets
    INTO THE SNIPPET — the exact string the row renders."""
    flat = " ".join((text or "").split())
    if not flat:
        return "", []
    spans = text_fold.match_offsets(flat, tokens)
    if len(flat) <= limit:
        return flat, spans
    first = spans[0][0] if spans else 0
    start = max(0, first - limit // 3)
    if start > 0:
        space = flat.find(" ", start)
        if 0 <= space < first:
            start = space + 1  # never open mid-word: a cut word would read as a word start
    end = min(len(flat), start + limit)
    if end < len(flat):
        cut = flat.rfind(" ", start, end)
        if cut > first:
            end = cut
    snippet = ("…" if start > 0 else "") + flat[start:end] + ("…" if end < len(flat) else "")
    return snippet, text_fold.match_offsets(snippet, tokens)


# --- per-request context ----------------------------------------------------------


@dataclass
class _Ctx:
    memory_path: Path
    reader: search_index.Reader | None
    q: str
    tokens: list[str]
    kinds: list[str]
    per_kind: int
    mode: str
    legs: dict[str, list[dict]] | None = None

    @property
    def match(self) -> str:
        return search_index.match_expression(self.tokens)

    @property
    def split_media(self) -> bool:
        return "media" in self.kinds

    @property
    def recent_first(self) -> bool:
        return self.mode == "prefix"


def _vector_legs(ctx: _Ctx, embed_fn) -> dict[str, list[dict]] | None:
    """The stored-vector legs, one embed for all of them; ``None`` when no
    vector index answers (then hybrid honestly reports ``mode: lexical``)."""
    want: dict[str, int] = {}
    if "entity" in ctx.kinds or "media" in ctx.kinds:
        want["entities"] = ctx.per_kind * 2
    if "claim" in ctx.kinds:
        want["claims"] = ctx.per_kind * 2
    if "episode" in ctx.kinds:
        want["episodes"] = ctx.per_kind * 2
    try:
        from api.services.vector_index import SqliteVecIndexer

        indexer = SqliteVecIndexer(ctx.memory_path, embed_fn=embed_fn) if embed_fn else SqliteVecIndexer(ctx.memory_path)
        legs = indexer.search_kinds(ctx.q, want)
    except Exception as exc:  # never the query text in a log (K9)
        logger.debug(f"search_service: vector legs unavailable ({type(exc).__name__})")
        return None
    return legs if any(legs.values()) else None


def _stem(row: dict) -> str:
    return Path(str((row.get("metadata") or {}).get("file_path") or "")).stem


def _belongs(is_media: bool, kind: str, split_media: bool) -> bool:
    """Which group a page lands in: media pages are their own group only
    when ``media`` was asked for; otherwise they are entities (the pre-G136
    ``/search`` returned every page as an entity, and ``kinds=entity`` keeps
    doing so). A page is reported once."""
    return is_media if kind == "media" else (not is_media or not split_media)


# --- pages: entities and media ------------------------------------------------------


@dataclass
class _Page:
    doc: search_index.Doc
    score: float
    label: str
    sort: tuple = ()
    reason: str | None = None  # the claim text, when reached through a claim


def _page_fields(meta: dict) -> list[tuple[str, float, str]]:
    return [
        (meta.get("name", ""), 1.0, "name"),
        *[(a, 0.9, "alias") for a in [*meta.get("aliases", []), *meta.get("authors", [])]],
        *[(t, 0.7, "keyword") for t in [*meta.get("tags", []), meta.get("site", ""), meta.get("channel", "")]],
    ]


def _page(doc: search_index.Doc, tokens: list[str], bm: float = 0.0) -> _Page:
    score, label = quick_score(tokens, _page_fields(doc.meta))
    meta = doc.meta
    return _Page(doc, score, label, (meta.get("status") == "archived", -score, bm, str(meta.get("name", "")).casefold()))


def _page_hit(page: _Page, tokens: list[str], score: float, snippet_src: str, kind: str) -> SearchHit:
    meta = page.doc.meta
    snippet, offsets = snippet_window(snippet_src, tokens)
    if meta.get("type") == "media":
        authors = meta.get("authors") or []
        subtitle = (", ".join(authors[:3]) + (" et al." if len(authors) > 3 else "")) if authors else (meta.get("site") or None)
    elif page.reason:
        subtitle = page.reason
    elif page.label == "alias":
        subtitle = next((a for a in meta.get("aliases", []) if text_fold.match_offsets(a, tokens)), None)
    else:
        subtitle = None
    return SearchHit(
        id=page.doc.ref,
        name=meta.get("name") or page.doc.ref,
        type=meta.get("type") or "concept",
        status=meta.get("status") or "active",
        confidence=float(meta.get("confidence") or 0.0),
        score=score,
        snippet=snippet,
        kind=kind,
        subtitle=subtitle,
        snippet_offsets=offsets,
        matched_field=page.label,
        origin=meta.get("origin") or None,
        timestamp=meta.get("saved_at") or None,
    )


def _lexical_pages(ctx: _Ctx, tables: list[str]) -> list[_Page]:
    """Entity or media pages, QuickMatch-ranked, archived last, dropped never
    (``dropped`` = user-dismissed, never resurfaced)."""
    rows: list[tuple[int, float]] = []
    for table in tables:
        rows += ctx.reader.ranked(table, ctx.match, ctx.per_kind * CANDIDATE_FACTOR)
    docs = ctx.reader.docs([d for d, _ in rows])
    pages = [_page(docs[d], ctx.tokens, bm) for d, bm in rows if d in docs and docs[d].meta.get("status") != "dropped"]
    pages.sort(key=lambda p: p.sort)
    return pages


def _pages_kind(ctx: _Ctx, kind: str, lexical: list[_Page], claims: list["_Claim"]) -> list[SearchHit]:
    vec: list[str] = []
    for row in (ctx.legs or {}).get("entities", []):
        meta = row.get("metadata") or {}
        if _belongs(meta.get("type") == "media", kind, ctx.split_media) and meta.get("status") != "dropped":
            vec.append(str(meta.get("entity_id") or ""))
    # The claim leg (R3 P2) is LEXICAL in both modes (G136 R9): current claims
    # whose words match, mapped to the page they are about. A vector leg
    # always returns k neighbours, so a semantic claim leg would give every
    # page with nearby claims a second always-present semantic vote on top of
    # the entity vectors — in a one-claim fixture it put that claim's subject
    # above the only true semantic match. Vector claims still rank the
    # `claim` group itself.
    via_claim: list[str] = []
    reasons: dict[str, str] = {}
    if kind == "entity":
        for c in claims:
            if c.hit.valid_to is None and c.hit.subject_id:
                via_claim.append(c.hit.subject_id)
                reasons.setdefault(c.hit.subject_id, c.hit.name)
        via_claim = _dedupe(via_claim)
    keys = [p.doc.ref for p in lexical]
    if ctx.legs is not None:
        order, scores = _fuse(keys, _dedupe(vec), via_claim)
    else:
        # Prefix mode keeps the exact-name hit on top: lexical order first,
        # pages reached only through one of their claims after it.
        order, scores = _dedupe([*keys, *via_claim]), {p.doc.ref: p.score for p in lexical}
    pages = {p.doc.ref: p for p in lexical}
    missing = [ref for ref in order[: ctx.per_kind * 2] if ref not in pages]
    if missing:
        allowed = tuple(k for k in ("entity", "media") if _belongs(k == "media", kind, ctx.split_media))
        for ref, doc in ctx.reader.docs_by_ref(allowed, missing).items():
            if doc.meta.get("status") != "dropped":
                label = "claim" if ref in reasons else "semantic"
                pages[ref] = _Page(doc, scores.get(ref, 0.0), label, reason=reasons.get(ref))
    # Archived pages rank below every live one in every mode — the fallback
    # tier `search_entities` already gives them (vector_index.py:345-373) —
    # and the tier is applied BEFORE the cut, so an archived neighbour never
    # displaces a live page from the group.
    ranked = [pages[ref] for ref in order if ref in pages]
    ranked.sort(key=lambda p: p.doc.meta.get("status") == "archived")
    chosen = ranked[: ctx.per_kind]
    bodies = {
        **ctx.reader.column("ent", "body", [p.doc.id for p in chosen if p.doc.kind == "entity"]),
        **ctx.reader.column("med", "body", [p.doc.id for p in chosen if p.doc.kind == "media"]),
    }
    hits = []
    for page in chosen:
        src = page.doc.meta.get("summary", "")
        body = bodies.get(page.doc.id, "")
        if not text_fold.match_offsets(src, ctx.tokens) and text_fold.match_offsets(body, ctx.tokens):
            src = body  # the snippet shows where the words are
        hits.append(_page_hit(page, ctx.tokens, scores.get(page.doc.ref, page.score), src, kind))
    return hits


# --- claims ---------------------------------------------------------------------------


@dataclass
class _Claim:
    hit: SearchHit
    sort: tuple = ()


def _claim_hit(subject: search_index.Doc, text: str, payload: dict, tokens: list[str], score: float, label: str) -> SearchHit:
    snippet, offsets = snippet_window(text, tokens)
    ev = payload.get("evidence") or {}
    is_span = ev.get("kind") not in (None, "reasoning") and int(ev.get("start", -1)) >= 0
    return SearchHit(
        id=str(payload.get("id") or ""),
        name=text,
        type=subject.meta.get("type") or "concept",
        status=subject.meta.get("status") or "active",
        confidence=float(payload.get("confidence") or 0.0),
        score=score,
        snippet=snippet,
        kind="claim",
        subtitle=subject.meta.get("name") or subject.ref,
        snippet_offsets=offsets,
        matched_field=label,
        subject_id=subject.ref,
        episode_id=(ev.get("episode") or None) if is_span else None,
        start=int(ev["start"]) if is_span else None,
        end=int(ev["end"]) if is_span else None,
        hash=(ev.get("hash") or None) if is_span else None,
        evidence_kind=ev.get("kind") or None,
        valid_from=payload.get("valid_from") or None,
        valid_to=payload.get("valid_to") or None,
        superseded_by=payload.get("superseded_by") or None,
    )


def _lexical_claims(ctx: _Ctx) -> list[_Claim]:
    """Current claims first, history after (R3 P4: a superseded claim is
    shown, as "was X until <date>", never hidden and never ranked above
    what is true now)."""
    rows = ctx.reader.claims(ctx.match, ctx.per_kind * CANDIDATE_FACTOR)
    subjects = ctx.reader.docs([doc_id for _, doc_id, *_ in rows])
    out: list[_Claim] = []
    for _rowid, doc_id, bm, text, payload in rows:
        subject = subjects.get(doc_id)
        if subject is None or not payload.get("id"):
            continue
        fields = [
            (text, 1.0, "name"),
            (subject.meta.get("name", ""), 0.9, "alias"),
            (f"{payload.get('predicate', '')} {payload.get('object', '')}", 0.7, "keyword"),
        ]
        score, label = quick_score(ctx.tokens, fields)
        out.append(_Claim(_claim_hit(subject, text, payload, ctx.tokens, score, label),
                          (payload.get("valid_to") is not None, -score, bm)))
    out.sort(key=lambda c: c.sort)
    return out


def _claim_order(ctx: _Ctx, lexical: list[_Claim]) -> tuple[list[str], dict[str, float]]:
    keys = [c.hit.id for c in lexical]
    if ctx.legs is None:
        return keys, {c.hit.id: c.hit.score for c in lexical}
    vec = [str((row.get("metadata") or {}).get("claim_id") or "") for row in ctx.legs.get("claims", [])]
    return _fuse(keys, _dedupe(vec))


def _claims_kind(ctx: _Ctx, lexical: list[_Claim], order: list[str], scores: dict[str, float]) -> list[SearchHit]:
    hits = {c.hit.id: c.hit for c in lexical}
    missing = [cid for cid in order[: ctx.per_kind] if cid not in hits]
    if missing:
        rows = ctx.reader.claims_by_id(missing)
        subjects = ctx.reader.docs([doc_id for doc_id, _t, _p in rows.values()])
        for cid, (doc_id, text, payload) in rows.items():
            if doc_id in subjects:
                hits[cid] = _claim_hit(subjects[doc_id], text, payload, ctx.tokens, 0.0, "semantic")
    ranked = [hits[cid] for cid in order if cid in hits]
    # History after every current claim in every mode (G136 R10), applied
    # BEFORE the cut: fusion alone ties a lexical-only superseded claim with
    # the first semantic neighbour, since vector claims are current-only.
    ranked.sort(key=lambda h: h.valid_to is not None)
    chosen = ranked[: ctx.per_kind]
    for hit in chosen:
        hit.score = scores.get(hit.id, hit.score)
    return chosen


# --- episodes ---------------------------------------------------------------------------


@dataclass
class _Episode:
    doc: search_index.Doc
    label: str
    passage: tuple[int, int, int] | None = None  # (rowid, start, end) of the best matching passage


def _lexical_episodes(ctx: _Ctx) -> list[_Episode]:
    """One row per episode: title matches first (the strongest field), then
    passage matches — newest-written first in prefix mode, bm25 in hybrid."""
    limit = ctx.per_kind * CANDIDATE_FACTOR
    heads = ctx.reader.ranked("epi", ctx.match, limit, recent_first=ctx.recent_first)
    passages = ctx.reader.passages(ctx.match, limit * 4, recent_first=ctx.recent_first)
    best: dict[int, tuple[int, int, int]] = {}
    for rowid, doc_id, s, e, _ in passages:
        best.setdefault(doc_id, (rowid, s, e))
    titled = {d for d, _ in heads}
    order = _dedupe([d for d, _ in heads] + [d for _, d, *_ in passages])[:limit]
    docs = ctx.reader.docs(order)
    return [_Episode(docs[d], "name" if d in titled else "body", best.get(d)) for d in order if d in docs]


def _line_span(text: str, s: int, e: int, tokens: list[str]) -> tuple[int, int]:
    """The line of passage ``text[s:e]`` holding the first match, as absolute
    offsets: a tighter highlight than the whole passage, and still a span
    whose ``text[start:end]`` contains the match (design §3.10)."""
    passage = text[s:e]
    spans = text_fold.match_offsets(passage, tokens)
    if not spans:
        return s, e
    at = spans[0][0]
    lo = passage.rfind("\n", 0, at) + 1
    hi = passage.find("\n", at)
    return s + lo, s + (hi if hi != -1 else len(passage))


def _locate_chunk(rows: list[tuple[int, int, int, str]], chunk: str) -> tuple[int, int] | None:
    """The passage holding a vector chunk, found EXACTLY: passages tile the
    body, so the body is their concatenation, and a chunk
    (``vector_index._chunk_episode_body``, a stripped slice of that body) is
    found with ``str.find`` — never fuzzy (G118 R5)."""
    head = (chunk or "").strip()[:200]
    if not head:
        return None
    at = "".join(t for *_, t in rows).find(head)
    if at == -1:
        return None
    return next(((s, e) for _r, s, e, _t in rows if s <= at < e), None)


def _episode_hit(ctx: _Ctx, ep: _Episode, score: float, chunk: str = "") -> SearchHit:
    meta = ep.doc.meta
    lo = ep.doc.id << search_index.ROW_BITS
    start = end = kind = None
    if ep.passage is not None:
        rowid, s, e = ep.passage
        # Passages tile the body from 0, so passages 1..rowid ARE body[:e].
        text = "".join(t for *_, t in ctx.reader.episode_passages(ep.doc.id, until=rowid))
        start, end = _line_span(text, s, e, ctx.tokens)
        src = text[start:end]
    else:
        rows = ctx.reader.episode_passages(ep.doc.id, until=None if chunk else lo | 1)
        text = "".join(t for *_, t in rows)
        span = _locate_chunk(rows, chunk) if chunk else None
        if span is not None:
            start, end = span
        src = text[start:end] if span is not None else text[: SNIPPET_CHARS * 2]
    if start is not None:
        kind = evidence.speaker_kind(text, start)
    snippet, offsets = snippet_window(src, ctx.tokens)
    return SearchHit(
        id=ep.doc.ref,
        name=meta.get("title") or "Untitled",
        type="episode",
        status="active",
        confidence=0.0,
        score=score,
        snippet=snippet,
        kind="episode",
        snippet_offsets=offsets,
        matched_field=ep.label,
        episode_id=ep.doc.ref,
        conversation_id=meta.get("conversation_id") or None,
        harness=meta.get("harness") or None,
        origin=meta.get("origin") or None,
        timestamp=meta.get("timestamp") or None,
        start=start,
        end=end,
        # A span without its hash could not be verified (G118 R2); a hit
        # with no span carries neither.
        hash=(meta.get("hash") or None) if start is not None else None,
        evidence_kind=kind,
    )


def _episodes_kind(ctx: _Ctx, lexical: list[_Episode]) -> list[SearchHit]:
    chunks: dict[str, str] = {}
    vec: list[str] = []
    for row in (ctx.legs or {}).get("episodes", []):
        stem = _stem(row)
        if stem:
            vec.append(stem)
            chunks.setdefault(stem, row.get("text") or "")
    keys = [ep.doc.ref for ep in lexical]
    if ctx.legs is not None:
        order, scores = _fuse(keys, _dedupe(vec))
    else:
        order, scores = keys, {ref: float(len(keys) - i) for i, ref in enumerate(keys)}
    eps = {ep.doc.ref: ep for ep in lexical}
    missing = [ref for ref in order[: ctx.per_kind] if ref not in eps]
    for ref, doc in ctx.reader.docs_by_ref(("episode",), missing).items():
        eps[ref] = _Episode(doc, "semantic")
    return [
        _episode_hit(ctx, eps[ref], scores.get(ref, 0.0), chunks.get(ref, "") if eps[ref].label == "semantic" else "")
        for ref in order[: ctx.per_kind]
        if ref in eps
    ]


# --- inbox ------------------------------------------------------------------------------


def _inbox_kind(ctx: _Ctx) -> tuple[list[SearchHit], int | None]:
    """Inbox questions, filtered exactly as ``GET /inbox`` filters them:
    a deferred item or one whose subject is gone is not served (G98)."""
    rows = ctx.reader.ranked("inb", ctx.match, INBOX_SCAN)
    docs = ctx.reader.docs([d for d, _ in rows])
    today = str(date.today())
    gone: dict[tuple[str, str], bool] = {}
    ranked: list[tuple[tuple, SearchHit]] = []
    for doc_id, bm in rows:
        doc = docs.get(doc_id)
        if doc is None:
            continue
        meta = doc.meta
        if inbox_questions.is_deferred({"remind_after": meta.get("remind_after")}, today):
            continue
        subject = (meta.get("entity_id") or "", meta.get("kind") or "")
        if subject not in gone:
            # A private helper, on purpose: the SAME test load_inbox applies,
            # so the palette can never offer a card /inbox hides (precedent:
            # sources.py reads link_enrichment's private extractor this way).
            gone[subject] = inbox_service._subject_gone(ctx.memory_path, *subject)
        if gone[subject]:
            continue
        fields = [(meta.get("question", ""), 1.0, "name"), (meta.get("entity_name", ""), 0.9, "alias"),
                  (meta.get("kind", ""), 0.7, "keyword")]
        score, label = quick_score(ctx.tokens, fields)
        snippet, offsets = snippet_window(meta.get("question", ""), ctx.tokens)
        hit = SearchHit(
            id=doc.ref, name=meta.get("question") or doc.ref, type=meta.get("kind") or "inbox",
            status=meta.get("status") or "pending", confidence=0.0, score=score, snippet=snippet,
            kind="inbox", subtitle=meta.get("entity_name") or None, snippet_offsets=offsets,
            matched_field=label, subject_id=meta.get("entity_id") or None,
        )
        ranked.append(((-score, -float(meta.get("priority") or 0.0), bm), hit))
    ranked.sort(key=lambda r: r[0])
    total = len(ranked) if len(rows) < INBOX_SCAN else None
    return [hit for _k, hit in ranked][: ctx.per_kind], total


# --- the two paths ------------------------------------------------------------------------


def _search_indexed(ctx: _Ctx) -> tuple[dict[str, list[SearchHit]], dict[str, int]]:
    out: dict[str, list[SearchHit]] = {}
    totals: dict[str, int] = {}
    tokens = bool(ctx.tokens)
    claims = _lexical_claims(ctx) if tokens and ("claim" in ctx.kinds or "entity" in ctx.kinds) else []
    if "entity" in ctx.kinds:
        tables = ["ent"] if ctx.split_media else ["ent", "med"]
        lexical = _lexical_pages(ctx, tables) if tokens else []
        out["entity"] = _pages_kind(ctx, "entity", lexical, claims)
        if tokens:
            totals["entity"] = sum(ctx.reader.count(t, ctx.match) for t in tables)
    if "claim" in ctx.kinds:
        order, scores = _claim_order(ctx, claims)
        out["claim"] = _claims_kind(ctx, claims, order, scores)
        if tokens:
            totals["claim"] = ctx.reader.count("clm", ctx.match)
    if "episode" in ctx.kinds:
        out["episode"] = _episodes_kind(ctx, _lexical_episodes(ctx) if tokens else [])
        if tokens:
            totals["episode"] = ctx.reader.count_episodes(ctx.match)
    if "media" in ctx.kinds:
        out["media"] = _pages_kind(ctx, "media", _lexical_pages(ctx, ["med"]) if tokens else [], [])
        if tokens:
            totals["media"] = ctx.reader.count("med", ctx.match)
    if "inbox" in ctx.kinds and tokens:
        out["inbox"], total = _inbox_kind(ctx)
        if total is not None:
            totals["inbox"] = total
    return out, totals


def _fm_meta(stem: str, fm: dict) -> dict:
    """The index's page meta, rebuilt from frontmatter (the fallback path)."""
    def strs(value):
        return [str(v).strip() for v in value if str(v or "").strip()] if isinstance(value, list) else []

    media = fm.get("media") if isinstance(fm.get("media"), dict) else {}
    paper = fm.get("paper") if isinstance(fm.get("paper"), dict) else {}
    return {
        "name": str(fm.get("name") or stem.replace("-", " ").title()),
        "type": str(fm.get("type", "concept") or "concept"),
        "status": str(fm.get("status", "active") or "active"),
        # The index's own tolerant reader: a hand-edited `confidence: high`
        # must not turn the fallback into a 500 (G136 R12).
        "confidence": search_index._float(fm.get("confidence")),
        "summary": "",
        "aliases": strs(fm.get("aliases"))[:8],
        "tags": strs(fm.get("tags"))[:8],
        "authors": strs(paper.get("authors"))[:6],
        "site": str(media.get("site") or ""),
        "channel": str(media.get("channel") or ""),
        "origin": str(fm.get("origin") or ""),
        "saved_at": str(fm.get("saved_at") or media.get("saved_at") or ""),
    }


def _search_fallback(ctx: _Ctx) -> tuple[dict[str, list[SearchHit]], dict[str, int]]:
    """No usable FTS index yet (building / unavailable): entity and media
    pages from ``bank_index``'s frontmatter cache — names, aliases, tags;
    never a body read and never a parse per request (R6 §4.2) — fused with
    the vector entity leg in hybrid. Claims, conversations and inbox need the
    index and come back empty; ``index_state`` says why."""
    out: dict[str, list[SearchHit]] = {k: [] for k in ctx.kinds}
    totals: dict[str, int] = {}
    docs: dict[str, search_index.Doc] = {}
    lexical: dict[str, list[_Page]] = {"entity": [], "media": []}
    for f in bank_index.files(ctx.memory_path, "entities"):
        meta = _fm_meta(f.stem, f.frontmatter or {})
        if meta["status"] == "dropped":
            continue
        doc = search_index.Doc(0, "media" if meta["type"] == "media" else "entity", f.stem, meta)
        docs[f.stem] = doc
        fields = _page_fields(meta)
        if ctx.tokens and all(any(w.startswith(t) for text, _w, _l in fields for w in text_fold.words(text)) for t in ctx.tokens):
            lexical["media" if ctx.split_media and doc.kind == "media" else "entity"].append(_page(doc, ctx.tokens))
    for kind in ("entity", "media"):
        if kind not in ctx.kinds:
            continue
        pages = sorted(lexical[kind], key=lambda p: p.sort)
        if ctx.tokens:
            totals[kind] = len(pages)
        order, scores = [p.doc.ref for p in pages], {p.doc.ref: p.score for p in pages}
        by_ref = {p.doc.ref: p for p in pages}
        if ctx.legs is not None:
            vec = [str((r.get("metadata") or {}).get("entity_id") or "") for r in ctx.legs.get("entities", [])]
            vec = [ref for ref in vec if ref in docs and _belongs(docs[ref].kind == "media", kind, ctx.split_media)]
            order, scores = _fuse(order, _dedupe(vec))
            for ref in order:
                if ref not in by_ref and ref in docs:
                    by_ref[ref] = _Page(docs[ref], scores.get(ref, 0.0), "semantic")
        chosen = [by_ref[ref] for ref in order if ref in by_ref][: ctx.per_kind]
        out[kind] = [_page_hit(p, ctx.tokens, scores.get(p.doc.ref, p.score), "", kind) for p in chosen]
    return out, totals


def search(
    memory_path: Path,
    q: str,
    *,
    kinds: Iterable[str] = ("entity",),
    mode: str = "hybrid",
    per_kind: int = 8,
    freshness_ttl_s: float | None = None,
    embed_fn=None,
) -> SearchResponse:
    """Search one bank. ``memory_path`` is the caller's ACTIVE bank (the
    router passes ``settings.memory_path``; MCP will pass its own resolved
    path) — this function never resolves a bank (the split-brain rule)."""
    wanted = set(kinds)
    ctx = _Ctx(
        memory_path=Path(memory_path),
        reader=None,
        q=q or "",
        tokens=text_fold.query_tokens(q),
        kinds=[k for k in KINDS if k in wanted] or ["entity"],
        per_kind=max(1, min(int(per_kind or 1), MAX_PER_KIND)),
        mode=mode if mode in MODES else "hybrid",
    )
    semantic = ctx.mode == "hybrid" and len(ctx.q.strip()) >= text_fold.MIN_TOKEN_CHARS
    if not ctx.tokens and not semantic:
        return SearchResponse(results=[], totals={}, mode=ctx.mode, index_state="ready")
    state = search_index.ensure_fresh(ctx.memory_path, max_age_s=freshness_ttl_s)
    if semantic:
        ctx.legs = _vector_legs(ctx, embed_fn)
    grouped = None
    if state in ("ready", "stale"):
        try:
            with search_index.Reader(ctx.memory_path) as reader:
                ctx.reader = reader
                grouped, totals = _search_indexed(ctx)
        except sqlite3.DatabaseError as exc:
            logger.warning(f"search_service: index read failed ({type(exc).__name__}); serving the fallback")
            search_index.invalidate(ctx.memory_path)
            state = "unavailable"
        finally:
            ctx.reader = None
    if grouped is None:
        grouped, totals = _search_fallback(ctx)
    ran = ctx.mode if ctx.mode == "prefix" or ctx.legs is not None else "lexical"
    results = [hit for kind in ctx.kinds for hit in grouped.get(kind, [])]
    return SearchResponse(results=results, totals=totals, mode=ran, index_state=state)


def lexical_entity_hits(memory_path: Path, query: str, top_k: int = 8) -> list[dict]:
    """MCP recall's keyword leg (``mcp_tools._keyword_search_entities``,
    G140 Q-R1): alias-aware and token-level (R3 P1). Pure lexical:
    claim-reached rows are ``claim_subject_hits``' job."""
    resp = search(memory_path, query, kinds=("entity",), mode="prefix", per_kind=min(top_k, MAX_PER_KIND))
    return [{"entity_id": h.id, "source": "keyword", "score": h.score}
            for h in resp.results if h.matched_field != "claim"]


def claim_subject_hits(memory_path: Path, query: str, top_k: int = 8) -> list[dict]:
    """R3 P2's third recall leg: current claims matched lexically, mapped to
    the page they are about, deduplicated, best first."""
    resp = search(memory_path, query, kinds=("claim",), mode="prefix", per_kind=MAX_PER_KIND)
    subjects = _dedupe(h.subject_id for h in resp.results if not h.valid_to)
    return [{"entity_id": ref, "source": "claim", "score": 0.0} for ref in subjects][:top_k]
