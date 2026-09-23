"""G118 slice 2 (server half) — reading provenance back out of the bank.

Slice 1 made every new claim point at the words it came from (``evidence``
spans, ``api/services/evidence.py``); nothing could yet show them. This module
builds the read payloads the viewer needs, and nothing else:

* :func:`episode_document` — ``GET /episodes/{id}/text``: the whole evidence
  text with its turns, so the Reader can scroll to a span and highlight it
  (design §4.4 / §4.8.1).
* :func:`entity_provenance` — ``GET /entities/{id}/provenance`` (§4.5 / §4.8.4).
* :func:`episode_citations` — ``GET /episodes/{id}/citations`` (§4.8.3, G106).

Rails, enforced here rather than documented:

* **Engine-free, bank text only** (G80, G48). No LLM, no vector index, and
  never a transcript under ``~/.claude`` — every document is a bank file
  resolved by ``evidence.source_path``. ``test_the_provenance_module_is_engine_free``
  pins the import list.
* **Spans, not copies; computed at read, never stored.** Excerpts and derived
  offsets are recomputed per call, and nothing here writes a file.
* **Never fuzzy; stale never highlights** (§4.9). An asserted span is the
  stored offsets judged by ``evidence.span_status``; a ``derived`` span is a
  name match (``inbox_context.locate_mention``), labelled and never written
  back (R-PB9); a stale span travels WITHOUT wash offsets (R-PB2).
"""

from __future__ import annotations

import os
from collections import Counter
from dataclasses import asdict, replace
from pathlib import Path

from api.models.schemas import (
    EntityProvenance,
    EpisodeCitation,
    EpisodeCitationEntity,
    EpisodeCitations,
    EpisodeFocus,
    EpisodeText,
    EpisodeTurn,
    EvidenceModel,
    ProvenanceContributor,
    ProvenanceConversation,
    ProvenancePage,
    ProvenanceSpan,
    ProvenanceTotals,
)
from api.services import bank_index, episode_ids, evidence, git_service, inbox_context, markdown_parser
from api.services.claims import Claim, Evidence, parse_claims
from api.services.id_utils import resolve_entity_file

# The Reader's cap (R-PB5). A Stop-hook episode is already capped at 100,000
# chars (`transcript_extract.SESSION_CAP_CHARS`); an import is not, and one
# pasted log in a chat export must not become a multi-megabyte response.
# Characters, not bytes: offsets index code points and the cut must land on one.
MAX_TEXT_CHARS = 400_000


class SpanOutOfRange(ValueError):
    """A caller-supplied ``[start, end)`` that is not inside the document."""


def _opt(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _asserted_focus(doc_id: str, text: str, start: int, end: int, hash: str | None, *,  # noqa: A002
                    is_episode: bool, override: str | None = None) -> EpisodeFocus:
    status = evidence.span_status(text, end=end, hash=hash, appendable=is_episode)
    # R-LS7: the one kind decision — a folder file's declared authorship wins
    # over markers, exactly as the stored span's kind was minted.
    kind = evidence.kind_for(doc_id, text, start, override)
    if status == evidence.SPAN_STALE:
        return EpisodeFocus(kind=kind, stale=True)  # R-PB2: no offsets to wash
    return EpisodeFocus(start=start, end=end, kind=kind, grown=status == evidence.SPAN_GROWN)


def _derived_focus(memory_path: Path, text: str, entity_ref: str) -> EpisodeFocus | None:
    page = resolve_entity_file(memory_path, entity_ref)
    # `focus` is a free query string and `resolve_entity_file` joins it onto
    # `entities/` as given, so `../<name>` would reach a file the bank never
    # stored as a page. Only a page that lives in `entities/` may name the
    # mention — the `evidence.source_path` rail, applied to the hint too.
    if page is None or page.resolve().parent != (Path(memory_path) / "entities").resolve():
        return None
    try:
        name = str(markdown_parser.parse(page).frontmatter.get("name") or page.stem)
    except Exception:
        name = page.stem
    hit = inbox_context.locate_mention(text, name, page.stem)
    if hit is None:
        return None
    return EpisodeFocus(start=hit[0], end=hit[1], kind="derived", derived=True)


def episode_document(
    memory_path: Path,
    doc_id: str,
    *,
    start: int | None = None,
    end: int | None = None,
    hash: str | None = None,  # noqa: A002 - the field's own name
    focus: str | None = None,
) -> EpisodeText | None:
    """The whole evidence text of ``doc_id`` with its turns, or ``None``.

    ``start``/``end`` (both or neither) ask for an asserted focus, judged by
    ``evidence.span_status`` against ``hash``; ``focus`` names an entity whose
    first mention becomes a derived focus. Raises :class:`SpanOutOfRange` for
    a half or out-of-range pair. Reads one file; writes nothing.
    """
    doc = evidence.source_document(memory_path, doc_id)
    if doc is None:
        return None
    fm, text = doc
    is_episode = evidence.is_episode_id(doc_id)
    length = len(text)
    if (start is None) != (end is None):
        raise SpanOutOfRange("start and end go together")
    if start is not None and not (0 <= start < end <= length):
        raise SpanOutOfRange(f"span [{start}, {end}) is outside the document (length {length})")

    stamps = evidence.turn_stamps(fm) if is_episode else {}
    override = (str(fm.get("evidence_kind") or "") or None) if is_episode else None
    spans = evidence.turns(text, page=not is_episode, stamps=stamps, override=override)
    truncated = length > MAX_TEXT_CHARS
    if truncated:
        spans = [
            replace(t, content_start=min(t.content_start, MAX_TEXT_CHARS), end=min(t.end, MAX_TEXT_CHARS))
            for t in spans if t.start < MAX_TEXT_CHARS
        ]

    focus_model: EpisodeFocus | None = None
    if start is not None:
        focus_model = _asserted_focus(doc_id, text, start, end, hash, is_episode=is_episode,
                                      override=override)
    elif focus:
        focus_model = _derived_focus(memory_path, text, focus)

    return EpisodeText(
        episode=doc_id,
        kind="episode" if is_episode else "page",
        text=text[:MAX_TEXT_CHARS],
        length=length,
        hash=evidence.body_hash(text),
        truncated=truncated,
        title=_opt(fm.get("title") if is_episode else fm.get("name")) or doc_id,
        timestamp=_opt(fm.get("timestamp")),
        harness=_opt(fm.get("harness")),
        origin=_opt(fm.get("origin")) or _opt(fm.get("source")),
        conversation_id=_opt(fm.get("session_id")) or _opt(fm.get("source_id")),
        capture_kind=_opt(fm.get("capture_kind")),
        turns=[EpisodeTurn(**asdict(t)) for t in spans],
        focus=focus_model,
    )


# How many conversation rows one provenance payload carries (R-PB7). The card
# shows five and "+N more"; `totals.conversations` is the honest total, and
# `best` is computed only for the rows that ship, so body reads stay bounded
# by what is shown.
MAX_PROVENANCE_CONVERSATIONS = 50


class _Episodes:
    """Episode frontmatter from ``bank_index`` (one scandir, cached parses)
    and bodies read lazily, at most once each — the G97 budget rule, so an
    entity citing twenty conversations costs twenty body reads, not a bank
    scan (``test_fifty_claims_across_twenty_episodes_stay_in_budget``)."""

    def __init__(self, memory_path: Path):
        self._memory_path = memory_path
        self._index: dict[str, bank_index.IndexedFile] | None = None
        self._bodies: dict[str, str | None] = {}

    def meta(self, ep_id: str) -> bank_index.IndexedFile | None:
        if self._index is None:
            self._index = {f.stem: f for f in bank_index.files(self._memory_path, "episodes")}
        return self._index.get(ep_id)

    def body(self, ep_id: str) -> str | None:
        if ep_id not in self._bodies:
            indexed = self.meta(ep_id)
            try:
                self._bodies[ep_id] = indexed.body() if indexed is not None else None
            except Exception:
                self._bodies[ep_id] = None
        return self._bodies[ep_id]


def _current(claim: Claim) -> bool:
    return claim.valid_to is None and not claim.superseded_by


def _recency(claim: Claim) -> str:
    return str(claim.recorded_at or claim.valid_from or "")


def _span_model(text: str, episode: str, start: int, end: int, *, hash: str, kind: str,  # noqa: A002
                grown: bool = False, derived: bool = False) -> ProvenanceSpan:
    ex = inbox_context.excerpt_around(text, (start, end))
    return ProvenanceSpan(episode=episode, start=start, end=end, hash=hash, kind=kind,
                          excerpt=ex.excerpt, excerpt_start=ex.start or 0,
                          mention_offsets=ex.mention_offsets, grown=grown, derived=derived)


def _stale_model(text: str, ev: Evidence) -> ProvenanceSpan:
    """A stale span still shows its neighbourhood — "the words may have
    moved" (§4.2) — but carries no offsets to wash (R-PB2)."""
    anchor = (ev.start, min(ev.end, len(text))) if 0 <= ev.start < len(text) else None
    ex = inbox_context.excerpt_around(text, anchor)
    return ProvenanceSpan(episode=ev.episode, hash=ev.hash, kind=ev.kind, excerpt=ex.excerpt,
                          excerpt_start=ex.start or 0, stale=True)


def _best_span(docs: _Episodes, episode_ids: list[str],
               spans_by_episode: dict[str, list[tuple[Claim, Evidence]]],
               name: str, entity_id: str) -> ProvenanceSpan | None:
    """R-PB8: an asserted span that still holds (newest claim first) → a
    derived name match in the newest readable episode → a stale span → none."""
    candidates = [pair for ep in episode_ids for pair in spans_by_episode.get(ep, [])]
    candidates.sort(key=lambda pair: _recency(pair[0]), reverse=True)
    stale: tuple[str, Evidence] | None = None
    for _claim, ev in candidates:
        text = docs.body(ev.episode)
        if text is None:
            continue
        status = evidence.span_status(text, end=ev.end, hash=ev.hash)
        if status == evidence.SPAN_STALE or ev.end > len(text):
            stale = stale or (text, ev)
            continue
        return _span_model(text, ev.episode, ev.start, ev.end, hash=ev.hash, kind=ev.kind,
                           grown=status == evidence.SPAN_GROWN)
    for ep in reversed(episode_ids):
        text = docs.body(ep)
        if not text:
            continue
        hit = inbox_context.locate_mention(text, name, entity_id)
        if hit is not None:
            return _span_model(text, ep, hit[0], hit[1], hash=evidence.body_hash(text),
                               kind="derived", derived=True)
    if stale is not None:
        return _stale_model(*stale)
    return None


def entity_provenance(
    memory_path: Path,
    page: Path,
    *,
    commit_authors: dict[str, int] | None = None,
    commits_truncated: bool = False,
) -> EntityProvenance:
    """Where ``page``'s current beliefs came from and who wrote them (R-PB6…8).

    One page parse, cached episode frontmatter, at most one body read per
    shown conversation; ``commit_authors`` is the router's single
    ``git_service.entity_commit_authors`` call (kept outside so this stays a
    pure, thread-pool-safe function). Writes nothing.
    """
    memory_path = Path(memory_path)
    # A page hand-edited into invalid YAML (Obsidian is a supported editor)
    # reads as an empty page, not a 500 — the entity card opens this route, and
    # `claims._load_subject_claims` already degrades the same way (final review).
    try:
        parsed = markdown_parser.parse(page)
    except Exception:
        parsed = markdown_parser.ParsedMarkdown()
    fm = parsed.frontmatter or {}
    entity_id = page.stem
    name = str(fm.get("name") or entity_id)
    current = [c for c in parse_claims(parsed.body) if _current(c)]
    commit_authors = commit_authors or {}
    docs = _Episodes(memory_path)

    claim_authors = Counter((c.authored_by or git_service.UNKNOWN_AUTHOR) for c in current)
    contributors: list[ProvenanceContributor] = []
    for author in set(claim_authors) | set(commit_authors):
        kind, provider = git_service.author_identity(author)
        contributors.append(ProvenanceContributor(
            author=author, kind=kind, provider=provider,
            claims=claim_authors.get(author, 0), commits=commit_authors.get(author, 0),
        ))
    contributors.sort(key=lambda c: (-(c.claims + c.commits), c.author))

    cited: dict[str, set[str]] = {}
    spans_by_episode: dict[str, list[tuple[Claim, Evidence]]] = {}
    page_claims: dict[str, set[str]] = {}
    with_span = inferred = legacy = 0
    for claim in current:
        episodes = {e for e in claim.source_episodes if evidence.is_episode_id(e)}
        for ev in claim.evidence:
            if not evidence.is_episode_id(ev.episode):
                if ev.is_span():
                    page_claims.setdefault(ev.episode, set()).add(claim.id)
                continue
            episodes.add(ev.episode)
            if ev.is_span():
                spans_by_episode.setdefault(ev.episode, []).append((claim, ev))
        cited[claim.id] = episodes
        if any(ev.is_span() for ev in claim.evidence):
            with_span += 1
        elif claim.evidence:
            inferred += 1
        else:
            legacy += 1

    fed_by = [str(e) for e in (fm.get("source_episodes") or []) if evidence.is_episode_id(str(e))]
    ordered = list(dict.fromkeys(fed_by + sorted({e for eps in cited.values() for e in eps})))

    groups: dict[str, dict] = {}
    for ep_id in ordered:
        indexed = docs.meta(ep_id)
        efm = indexed.frontmatter if indexed is not None else {}
        conversation_id = _opt(efm.get("session_id")) or _opt(efm.get("source_id"))
        group = groups.setdefault(conversation_id or ep_id, {"id": conversation_id, "episodes": []})
        group["episodes"].append((str(efm.get("timestamp") or ""), ep_id, efm, indexed is not None))

    rows: list[ProvenanceConversation] = []
    for group in groups.values():
        # By instant, never by string (G114 R2): a bank holds naive, `Z` and
        # `+00:00` stamps side by side, and lexical order across them is wrong.
        group["episodes"].sort(key=lambda e: (episode_ids.timestamp_sort_key(e[0]), e[1]))
        ep_ids = [e[1] for e in group["episodes"]]
        first, last = group["episodes"][0], group["episodes"][-1]
        members = set(ep_ids)
        rows.append(ProvenanceConversation(
            conversation_id=group["id"],
            episode_id=last[1],
            episode_ids=ep_ids,
            title=str(first[2].get("title") or ""),
            harness=next((_opt(e[2].get("harness")) for e in group["episodes"] if _opt(e[2].get("harness"))), None),
            origin=_opt(last[2].get("origin")) or _opt(last[2].get("source")),
            timestamp=last[0] or None,
            claim_count=sum(1 for eps in cited.values() if eps & members),
            available=any(e[3] for e in group["episodes"]),
        ))
    rows.sort(key=lambda r: (r.claim_count, episode_ids.timestamp_sort_key(r.timestamp)), reverse=True)
    shown = rows[:MAX_PROVENANCE_CONVERSATIONS]
    for row in shown:
        row.best = _best_span(docs, row.episode_ids, spans_by_episode, name, entity_id)

    pages: list[ProvenancePage] = []
    for doc_id, claim_ids in sorted(page_claims.items()):
        pdoc = evidence.source_document(memory_path, doc_id)
        pname = str((pdoc[0] if pdoc else {}).get("name") or doc_id)
        pages.append(ProvenancePage(entity_id=doc_id, name=pname, claim_count=len(claim_ids)))

    return EntityProvenance(
        entity_id=entity_id,
        entity_name=name,
        entity_type=str(fm.get("type") or ""),
        contributors=contributors,
        conversations=shown,
        pages=pages,
        inferred_count=inferred,
        totals=ProvenanceTotals(claims=len(current), with_span=with_span, legacy=legacy,
                                conversations=len(rows)),
        commits_truncated=commits_truncated,
    )


# The most entity pages one citations call parses (R-PB10). A page is parsed
# only when its raw text names the document, so this bounds the pathological
# case — a conversation cited by hundreds of pages — and `partial` says so.
MAX_CITATION_PAGES = 200


def _candidate_pages(memory_path: Path, doc_id: str) -> tuple[list[Path], bool]:
    """Entity pages whose raw text contains ``doc_id``, in filename order,
    capped. A substring test before any YAML parse: a page can only cite a
    document whose id is written in it (a claim's ``evidence`` or
    ``source_episodes``, or the frontmatter's), and an ``ep_YYYY-MM-DD_nnn``
    id is distinctive, so a false positive costs one parse and a miss is
    impossible. This is the "cold" path the design names (§4.8.3): the pages'
    own claims blocks — not the vector claims index, whose metadata carries no
    evidence (``vector_index.index_claims``), and not Track S's FTS table,
    which this track does not depend on."""
    entities_dir = Path(memory_path) / "entities"
    try:
        with os.scandir(entities_dir) as it:
            names = sorted(e.name for e in it if e.is_file() and e.name.endswith(".md"))
    except FileNotFoundError:
        return [], False
    out: list[Path] = []
    for fname in names:
        path = entities_dir / fname
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if doc_id not in raw:
            continue
        if len(out) >= MAX_CITATION_PAGES:
            return out, True
        out.append(path)
    return out, False


def episode_citations(memory_path: Path, doc_id: str) -> EpisodeCitations | None:
    """Every belief ``doc_id`` contributed (G106 (ii) at claim precision), or
    ``None`` for an unknown / non-bare id. Engine-free; writes nothing.

    Per claim: one row per span into the document (freshness from
    ``span_status``; stale rows carry no offsets, R-PB2); else one
    ``reasoning`` row when the contributor inferred it from here; else — a
    legacy claim that only lists the document in ``source_episodes`` — one
    ``derived`` row located by the subject's name (R-PB9), with offsets only
    when the name is found.
    """
    doc = evidence.source_document(memory_path, doc_id)
    if doc is None:
        return None
    _fm, text = doc
    is_episode = evidence.is_episode_id(doc_id)
    pages, partial = _candidate_pages(memory_path, doc_id)
    rows: list[EpisodeCitation] = []
    entities: list[EpisodeCitationEntity] = []
    for path in pages:
        try:
            parsed = markdown_parser.parse(path)
        except Exception:
            continue
        pfm = parsed.frontmatter or {}
        subject_id = path.stem
        subject_name = str(pfm.get("name") or subject_id)
        subject_type = str(pfm.get("type") or "")
        if doc_id in [str(e) for e in (pfm.get("source_episodes") or [])]:
            entities.append(EpisodeCitationEntity(entity_id=subject_id, name=subject_name, type=subject_type))
        for claim in parse_claims(parsed.body):
            base = {
                "claim_id": claim.id, "subject_id": subject_id, "subject_name": subject_name,
                "subject_type": subject_type, "text": claim.text, "current": _current(claim),
                "authored_by": claim.authored_by or git_service.UNKNOWN_AUTHOR, "observer": claim.observer,
            }
            mine = [ev for ev in claim.evidence if ev.episode == doc_id]
            spans = [ev for ev in mine if ev.is_span()]
            for ev in spans:
                status = evidence.span_status(text, end=ev.end, hash=ev.hash, appendable=is_episode)
                stale = status == evidence.SPAN_STALE or ev.end > len(text)
                rows.append(EpisodeCitation(
                    **base, evidence=EvidenceModel(**ev.to_dict()), kind=ev.kind,
                    start=None if stale else ev.start, end=None if stale else ev.end,
                    stale=stale, grown=not stale and status == evidence.SPAN_GROWN,
                ))
            if spans:
                continue
            if mine:
                rows.append(EpisodeCitation(**base, evidence=EvidenceModel(**mine[0].to_dict()), kind="reasoning"))
            elif doc_id in claim.source_episodes:
                hit = inbox_context.locate_mention(text, subject_name, subject_id)
                rows.append(EpisodeCitation(**base, kind="derived", derived=True,
                                            start=hit[0] if hit else None, end=hit[1] if hit else None))
    rows.sort(key=lambda r: (r.start is None, r.start if r.start is not None else 0, r.subject_name, r.claim_id))
    return EpisodeCitations(episode=doc_id, citations=rows, entities=entities, partial=partial)
