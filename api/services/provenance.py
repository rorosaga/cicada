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
    EpisodeAgent,
    EpisodeAttachment,
    EpisodeCitation,
    EpisodeCitationEntity,
    EpisodeCitations,
    EpisodeFocus,
    EpisodeText,
    EpisodeTurn,
    EpisodeReaction,
    EpisodeRelay,
    EpisodeTurnExtras,
    EpisodeUnsent,
    EpisodeWatch,
    EvidenceModel,
    ProvenanceContributor,
    ProvenanceConversation,
    ProvenanceModel,
    ProvenancePage,
    ProvenanceSpan,
    ProvenanceTotals,
    SectionEvidence,
    SectionProvenance,
    SectionProvenanceItem,
)
from api.services import (
    agent_turns,
    authorship,
    bank_index,
    episode_ids,
    episode_time,
    evidence,
    git_service,
    inbox_context,
    markdown_parser,
    media_pages,
    section_provenance,
    source_dates,
    source_spans,
    turn_authorship,
    turn_extras,
    video_state,
)
from api.services.claims import Claim, Evidence, is_current, is_event, is_record, parse_claims, served_prose
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


def _asserted_focus(source: source_spans.Source, start: int, end: int, hash: str | None) -> EpisodeFocus:  # noqa: A002
    # R-LS7: the one kind decision — a folder file's declared authorship wins
    # over markers, exactly as the stored span's kind was minted.
    kind = evidence.kind_for(source.id, source.text, start, source.override, source.gaps)
    span = source.span(start, end, hash, kind)
    if kind == evidence.GAP_KIND:
        span = source.nothing(kind)   # gate B2: Cicada's gap line is nobody's words — never highlighted
    if span.at is None:
        # R-PB2: no offsets to wash; ROR-16: a held span has none either, and no word says why.
        return EpisodeFocus(kind=kind, stale=span.status == source_spans.STALE, span=span)
    return EpisodeFocus(start=start, end=end, kind=kind, grown=span.status == source_spans.GROWN, span=span)


def _derived_focus(memory_path: Path, source: source_spans.Source, entity_ref: str) -> EpisodeFocus | None:
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
    hit = inbox_context.locate_mention(source.text, name, page.stem)
    if hit is None:
        return None
    span = source.derived(hit[0], hit[1])
    if span.at is None:
        return EpisodeFocus(kind="derived", span=span)
    return EpisodeFocus(start=hit[0], end=hit[1], kind="derived", derived=True, span=span)


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
    override = authorship.of(fm) if is_episode else None
    # Gate B2: the episode's own gap record, never the body's words.
    gaps = evidence.gap_ranges(fm, text) if is_episode else ()
    spans = evidence.turns(text, page=not is_episode, stamps=stamps, override=override, gaps=gaps)
    # Round 4 C4: an agent turn's model/effort is its sidecar entry at exactly
    # the turn's start (the entry the capture wrote); never on a person's turn.
    agents = {s.offset: s for s in agent_turns.stamps(fm) if s.speaker == "assistant"} if is_episode else {}
    for i, t in enumerate(spans):
        if t.role == "assistant" and t.marker is None and i >= 2 and spans[i - 1].role == evidence.GAP_KIND:
            # A recorded reply gap splits one agent turn into Reader blocks.
            # Its resumed tail inherits the actual head's stamp, never a guess.
            head = agents.get(spans[i - 2].start)
            if head is not None:
                agents[t.start] = head
    # R4B-15: `agent` is the most recent agent turn's — of the WHOLE document,
    # read before the Reader's cut — and null when that turn names neither; an
    # older turn's model never stands in for it (D1: never guessed).
    last = next((t for t in reversed(spans) if t.role == "assistant"), None)
    stamp = agents.get(last.start) if last is not None else None
    agent = EpisodeAgent(model=stamp.model, effort=stamp.effort) if stamp and (stamp.model or stamp.effort) else None
    truncated = length > MAX_TEXT_CHARS
    if truncated:
        spans = [
            replace(t, content_start=min(t.content_start, MAX_TEXT_CHARS), end=min(t.end, MAX_TEXT_CHARS))
            for t in spans if t.start < MAX_TEXT_CHARS
        ]

    focus_model: EpisodeFocus | None = None
    if start is not None or focus:
        source = source_spans.Source.of(doc_id, fm, text)
        focus_model = (_asserted_focus(source, start, end, hash) if start is not None
                       else _derived_focus(memory_path, source, focus))

    watch = _watch(memory_path, doc_id, fm) if is_episode else None
    index_at = {t.start: t.index for t in spans}
    extras_at = turn_extras.by_offset(fm) if is_episode else {}
    turn_models: list[EpisodeTurn] = []
    for t in spans:
        s = agents.get(t.start) if t.role == "assistant" else None
        turn_models.append(EpisodeTurn(**asdict(t), model=s.model if s else None, effort=s.effort if s else None,
                                       fidelity=watch.fidelity if watch is not None and t.role == "media" else None,
                                       extras=_extras(extras_at.get(t.start), index_at)))

    return EpisodeText(
        episode=doc_id,
        kind="episode" if is_episode else "page",
        source_kind=source_spans.kind_of(doc_id, fm),
        text=text[:MAX_TEXT_CHARS],
        length=length,
        hash=evidence.body_hash(text),
        truncated=truncated,
        title=_opt(fm.get("title") if is_episode else fm.get("name")) or doc_id,
        timestamp=_opt(fm.get("timestamp")),
        received_at=episode_time.received_shown(fm) if is_episode else None,
        harness=_opt(fm.get("harness")),
        origin=_opt(fm.get("origin")) or _opt(fm.get("source")),
        source=_opt(fm.get("source")),
        conversation_id=_opt(fm.get("session_id")) or _opt(fm.get("source_id")),
        capture_kind=_opt(fm.get("capture_kind")),
        correspondent=_opt(_correspondent(fm).get("name")) if is_episode else None,
        correspondent_kind=_opt(_correspondent(fm).get("kind")) if is_episode else None,
        device=_opt(fm.get("device")) if is_episode else None,
        site=_saved_site(fm) if is_episode else None,
        note_id=_opt(fm.get("note_id")) if is_episode and fm.get("source") == "apple-notes" else None,
        turns=turn_models,
        focus=focus_model,
        agent=agent,
        watch=watch,
        relay=_relay(fm) if is_episode else None,
        unsent=_unsent(fm, spans) if is_episode else [],
    )


def _saved_site(fm: dict) -> str | None:
    """Owner 2026-10-20: the site key a saved link's Reader header is marked with (the Waiting row's own rule)."""
    from api.services import channel_items, reading_hosts

    url = channel_items.saved_episode_url(fm)
    return reading_hosts.mark_key(url) if url else None


def _extras(stored: dict | None, index_at: dict[int, int]) -> EpisodeTurnExtras | None:
    """A turn's stored extras on the wire: a reply's target offset becomes the target turn's index (a target that is
    no turn start here, or a ``{ref}``, reads as a reply to a message elsewhere). Tolerant: a malformed value is
    dropped, never raised."""
    if not stored:
        return None
    reply = stored.get("reply_to")
    reply_to = index_at.get(reply) if isinstance(reply, int) and not isinstance(reply, bool) else None
    runs = stored.get("code_runs")
    out = EpisodeTurnExtras(
        reactions=[EpisodeReaction(**r) for r in turn_extras.clean_reactions(stored.get("reactions"))],
        reply_to=reply_to,
        reply_elsewhere=reply is not None and reply_to is None,
        attachments=[EpisodeAttachment(**a) for a in turn_extras.clean_attachments(stored.get("attachments"))],
        edited=stored.get("edited") is True,
        forwarded_from=_opt(stored.get("forwarded_from")),
        code_runs=runs if isinstance(runs, int) and not isinstance(runs, bool) and runs > 0 else None,
    )
    return out if out != EpisodeTurnExtras() else None


def _unsent(fm: dict, spans) -> list[EpisodeUnsent]:
    out = []
    for entry in turn_extras.unsent(fm):
        at = int(entry["at"])
        before = next((t.index for t in spans if t.start >= at), spans[-1].index + 1 if spans else 1)
        out.append(EpisodeUnsent(before=before, speaker=str(entry["speaker"]), ts=_opt(entry.get("ts"))))
    return out


def _relay(fm: dict) -> EpisodeRelay | None:
    """Ruling 32: the relay record of an episode an export has not upgraded yet, or ``None``. An upgraded episode
    holds the export's words — the person's own — so it is no longer a relay to the Reader."""
    from api.services.turn_capture import RELAY_KEY

    record = (fm or {}).get(RELAY_KEY)
    if not isinstance(record, dict) or record.get("upgraded_at"):
        return None
    app = _opt(record.get("app"))
    label = None
    if app:
        from api.remote.catalog import APPS

        known = APPS.get(app)
        label = known.label if known is not None and app != "other" else None
    return EpisodeRelay(app=app, label=label)


def _correspondent(fm: dict) -> dict:
    """G179: a message conversation's ``correspondent`` record, or ``{}``."""
    value = fm.get("correspondent")
    return value if isinstance(value, dict) else {}


def _watch(memory_path: Path, doc_id: str, fm: dict) -> EpisodeWatch | None:
    """G162: the ``watch`` block of a video-watch episode, or ``None`` for any other.

    ``basis`` / ``engine`` come from the episode's frontmatter (the agent's word),
    ``fidelity`` is derived. The model that wrote it is joined here, per request, from
    the ``describes`` claim whose evidence cites this episode — the same
    ``TurnAuthorship`` join every claim uses — because nothing on a watch episode
    records one. A write with no captured turn (Codex, a remote app) has no join and
    stays null: the app says the model was not shared, never a guess."""
    if (fm or {}).get("source") != video_state.WATCH_SOURCE:
        return None
    engine = video_state.clean_engine(fm.get("watch_engine"))
    model = effort = None
    entity_id = str(fm.get("media_entity_id") or "").strip()
    page = Path(memory_path) / "entities" / f"{entity_id}.md" if entity_id and "/" not in entity_id else None
    if page is not None and page.is_file():
        try:
            for claim in parse_claims(markdown_parser.parse(page).body):
                if claim.predicate != "describes" or not any(ev.episode == doc_id for ev in claim.evidence):
                    continue
                kind = git_service.author_identity(claim.authored_by)[0]
                model, effort = turn_authorship.TurnAuthorship(memory_path).for_claim(claim, kind)
                if model or effort:
                    break
        except Exception:  # noqa: BLE001 — a join never fails the read
            model = effort = None
    return EpisodeWatch(basis=video_state.clean_basis(fm.get("watch_basis")), engine=engine,
                        fidelity=video_state.fidelity(engine), author_model=model, author_effort=effort)


# How many conversation rows one provenance payload carries (R-PB7). The card
# shows five and "+N more"; `totals.conversations` is the honest total, and
# `best` is computed only for the rows that ship, so body reads stay bounded
# by what is shown.
MAX_PROVENANCE_CONVERSATIONS = 50
MAX_SECTION_RESPONSE_BYTES = 128 * 1024


class _Episodes:
    """Episode frontmatter from ``bank_index`` (one scandir, cached parses)
    and bodies read lazily, at most once each — the G97 budget rule, so an
    entity citing twenty conversations costs twenty body reads, not a bank
    scan (``test_fifty_claims_across_twenty_episodes_stay_in_budget``)."""

    def __init__(self, memory_path: Path):
        self._memory_path = memory_path
        self._index: dict[str, bank_index.IndexedFile] | None = None
        self._bodies: dict[str, str | None] = {}
        self._held: dict[str, tuple] = {}

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

    def held(self, ep_id: str) -> tuple:
        """Where this document holds what may not be drawn (G235, ROR-16); `source_spans` keeps it per body."""
        if ep_id not in self._held:
            indexed = self.meta(ep_id)
            text = self._bodies.get(ep_id)
            if indexed is None or text is None:
                return ()
            self._held[ep_id] = source_spans.Source.of(ep_id, indexed.frontmatter or {}, text).held
        return self._held[ep_id]


def _said(timestamp: str, ep_id: str) -> str | None:
    """When an episode was said: its ``timestamp``, else the day in its id — ``source_dates.episode_day``'s rule
    (G194), so the card and Sleep's prompts date a conversation the same way. ``None`` when neither is known."""
    if timestamp:
        return timestamp
    day = source_dates.parse_day(ep_id)
    return day.isoformat() if day else None


def _current(claim: Claim) -> bool:
    return is_current(claim)


def _recency(claim: Claim) -> str:
    return str(claim.recorded_at or claim.valid_from or "")


def _held_excerpt(excerpt: str, at: int, held: tuple) -> bool:
    """A secret in the excerpt's neighbourhood holds the whole excerpt (G235, ROR-16): the words around a value are no
    place to show it."""
    return bool(excerpt) and source_spans.overlaps_held(at, at + len(excerpt), held)


def _span_model(text: str, episode: str, start: int, end: int, *, hash: str, kind: str,  # noqa: A002
                grown: bool = False, derived: bool = False, held: tuple = ()) -> ProvenanceSpan:
    if source_spans.overlaps_held(start, end, held):
        return ProvenanceSpan(episode=episode, hash=hash, kind=kind, held=True)
    ex = inbox_context.excerpt_around(text, (start, end))
    if _held_excerpt(ex.excerpt, ex.start or 0, held):
        return ProvenanceSpan(episode=episode, start=start, end=end, hash=hash, kind=kind, grown=grown, derived=derived)
    return ProvenanceSpan(episode=episode, start=start, end=end, hash=hash, kind=kind,
                          excerpt=ex.excerpt, excerpt_start=ex.start or 0,
                          mention_offsets=ex.mention_offsets, grown=grown, derived=derived)


def _stale_model(text: str, ev: Evidence, held: tuple = ()) -> ProvenanceSpan:
    """A stale span still shows its neighbourhood — "the words may have
    moved" (§4.2) — but carries no offsets to wash (R-PB2)."""
    anchor = (ev.start, min(ev.end, len(text))) if 0 <= ev.start < len(text) else None
    ex = inbox_context.excerpt_around(text, anchor)
    if _held_excerpt(ex.excerpt, ex.start or 0, held):
        return ProvenanceSpan(episode=ev.episode, hash=ev.hash, kind=ev.kind, stale=True)
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
                           grown=status == evidence.SPAN_GROWN, held=docs.held(ev.episode))
    for ep in reversed(episode_ids):
        text = docs.body(ep)
        if not text:
            continue
        hit = inbox_context.locate_mention(text, name, entity_id)
        if hit is not None:
            return _span_model(text, ep, hit[0], hit[1], hash=evidence.body_hash(text),
                               kind="derived", derived=True, held=docs.held(ep))
    if stale is not None:
        return _stale_model(*stale, held=docs.held(stale[1].episode))
    return None


def cited_episodes(claim: Claim) -> set[str]:
    """The conversations a belief cites: its ``source_episodes`` and its evidence's episodes (never a page)."""
    episodes = {e for e in claim.source_episodes if evidence.is_episode_id(e)}
    episodes.update(ev.episode for ev in claim.evidence if evidence.is_episode_id(ev.episode))
    return episodes


def conversation_groups(docs: _Episodes, episode_ids_in_order) -> list[dict]:
    """Episodes grouped into conversations — one session id (a hook's turns), else one source id (an import's
    conversation), else the episode alone — the one grouping ``/provenance`` and the card's page-sources overview
    share, so both count the same conversations. Each group is ``{id, episodes, said}``: ``episodes`` sorted by
    instant as ``(timestamp, episode id, frontmatter, exists)``; ``said`` the ``(first, last)`` time it was said,
    or ``None`` when no episode is a dated mention (#242: a memory export entry is facts, not activity)."""
    groups: dict[str, dict] = {}
    for ep_id in episode_ids_in_order:
        indexed = docs.meta(ep_id)
        efm = indexed.frontmatter if indexed is not None else {}
        conversation_id = _opt(efm.get("session_id")) or _opt(efm.get("source_id"))
        group = groups.setdefault(conversation_id or ep_id, {"id": conversation_id, "episodes": []})
        group["episodes"].append((str(efm.get("timestamp") or ""), ep_id, efm, indexed is not None))
    for group in groups.values():
        # By instant, never by string (G114 R2): a bank holds naive, `Z` and
        # `+00:00` stamps side by side, and lexical order across them is wrong.
        group["episodes"].sort(key=lambda e: (episode_ids.timestamp_sort_key(e[0]), e[1]))
        stamps = [stamp for e in group["episodes"]
                  if episode_time.counts_as_activity(e[2]) and (stamp := _said(e[0], e[1]))]
        group["said"] = ((min(stamps, key=episode_ids.timestamp_sort_key),
                          max(stamps, key=episode_ids.timestamp_sort_key)) if stamps else None)
    return list(groups.values())


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
    # Round 4 C4: a harness contributor's models, joined per current claim
    # (R4B-6); a Sleep author is a model already and is never joined.
    turns = turn_authorship.TurnAuthorship(memory_path, text=docs.body)
    models: dict[str, Counter] = {}
    for c in current:
        author = git_service.canonical_author(c.authored_by)
        model, effort = turns.for_claim(c, git_service.author_identity(author)[0])
        if model:
            models.setdefault(author, Counter())[(model, effort)] += 1

    claim_authors = Counter(git_service.canonical_author(c.authored_by) for c in current)
    contributors: list[ProvenanceContributor] = []
    for author in set(claim_authors) | set(commit_authors):
        kind, provider = git_service.author_identity(author)
        contributors.append(ProvenanceContributor(
            author=author, kind=kind, provider=provider,
            claims=claim_authors.get(author, 0), commits=commit_authors.get(author, 0),
            models=[ProvenanceModel(model=m, effort=e, beliefs=n) for (m, e), n in
                    sorted((models.get(author) or Counter()).items(), key=lambda kv: (-kv[1], kv[0][0], kv[0][1] or ""))],
        ))
    contributors.sort(key=lambda c: (-(c.claims + c.commits), c.author))
    # ROR-117 (owner 2026-11-05): the model that made a recording's words is named on the page of that recording — from
    # the page's own record (`media.transcribed_by`), the words themselves staying outside the bank. Said only when a
    # transcript and a name exist; the same face a model gets everywhere else.
    if (by := media_pages.transcriber(fm)) and media_pages.is_file_page(fm) and all(c.author != by for c in contributors):
        kind, provider = git_service.author_identity(by)
        contributors.append(ProvenanceContributor(author=by, kind=kind, provider=provider, role="transcribed"))
    # ROR-117 / ruling 68: and the model that read those words for the page's Summary, beside the transcriber. It
    # committed that note, so it is usually listed already; the role says what for.
    if (read_by := media_pages.reader(fm)) and media_pages.is_file_page(fm):
        read_by = git_service.canonical_author(read_by)
        match = next((c for c in contributors if c.author == read_by), None)
        if match is None:
            kind, provider = git_service.author_identity(read_by)
            contributors.append(ProvenanceContributor(author=read_by, kind=kind, provider=provider, role="summarized"))
        elif match.role is None:
            match.role = "summarized"

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

    rows: list[ProvenanceConversation] = []
    said: dict[int, tuple[str, str]] = {}   # id(row) -> (first, last) said, over every conversation
    for group in conversation_groups(docs, ordered):
        ep_ids = [e[1] for e in group["episodes"]]
        first, last = group["episodes"][0], group["episodes"][-1]
        members = set(ep_ids)
        row = ProvenanceConversation(
            conversation_id=group["id"],
            episode_id=last[1],
            episode_ids=ep_ids,
            title=str(first[2].get("title") or ""),
            harness=next((_opt(e[2].get("harness")) for e in group["episodes"] if _opt(e[2].get("harness"))), None),
            origin=_opt(last[2].get("origin")) or _opt(last[2].get("source")),
            source=_opt(last[2].get("source")),
            correspondent=_opt(_correspondent(last[2]).get("name")),
            device=next((_opt(e[2].get("device")) for e in reversed(group["episodes"]) if _opt(e[2].get("device"))),
                        None),
            timestamp=last[0] or None,
            claim_count=sum(1 for eps in cited.values() if eps & members),
            available=any(e[3] for e in group["episodes"]),
        )
        rows.append(row)
        if group["said"]:
            said[id(row)] = group["said"]
    dated = [r for r in rows if id(r) in said]
    first = min(dated, key=lambda r: episode_ids.timestamp_sort_key(said[id(r)][0]), default=None)
    last = max(dated, key=lambda r: episode_ids.timestamp_sort_key(said[id(r)][1]), default=None)
    rows.sort(key=lambda r: (r.claim_count, episode_ids.timestamp_sort_key(r.timestamp)), reverse=True)
    shown = rows[:MAX_PROVENANCE_CONVERSATIONS]
    for row in shown:
        row.best = _best_span(docs, row.episode_ids, spans_by_episode, name, entity_id)

    pages: list[ProvenancePage] = []
    for doc_id, claim_ids in sorted(page_claims.items()):
        pdoc = evidence.source_document(memory_path, doc_id)
        pname = str((pdoc[0] if pdoc else {}).get("name") or doc_id)
        pages.append(ProvenancePage(entity_id=doc_id, name=pname, claim_count=len(claim_ids)))

    # F4: `/entities` serves the prose without the claims fence; the hash and the section ranges describe that text.
    served, to_served = served_prose(parsed.body)
    sections, sections_partial = _sections(parsed, docs, shown, to_served)
    return EntityProvenance(
        entity_id=entity_id,
        entity_name=name,
        entity_type=str(fm.get("type") or ""),
        contributors=contributors,
        conversations=shown,
        pages=pages,
        inferred_count=inferred,
        totals=ProvenanceTotals(claims=len(current), with_span=with_span, legacy=legacy,
                                conversations=len(rows),
                                first_said=said[id(first)][0] if first else None,
                                last_said=said[id(last)][1] if last else None),
        first_conversation=first.model_copy(update={"best": None}) if first else None,
        last_conversation=last.model_copy(update={"best": None}) if last else None,
        commits_truncated=commits_truncated,
        page_body_hash=evidence.body_hash(served),
        sections=sections,
        sections_partial=sections_partial,
    )


def _section_evidence(ev: Evidence, docs: _Episodes, allowed: set[str]) -> SectionEvidence:
    """Share page provenance reads; unchecked coordinates never become a wash."""
    memory_path = docs._memory_path
    path = evidence.source_path(memory_path, ev.episode)
    is_episode = evidence.is_episode_id(ev.episode)
    directory = memory_path / ('episodes' if is_episode else 'entities')
    safe = path is not None and path.resolve().parent == directory.resolve()
    indexed = docs.meta(ev.episode) if safe and is_episode else None
    fm = indexed.frontmatter if indexed is not None else {}
    row = SectionEvidence(
        evidence=EvidenceModel(**ev.to_dict()),
        source_available=safe,
        source_title=str(fm.get('title') or ev.episode),
        conversation_id=_opt(fm.get('session_id')) or _opt(fm.get('source_id')),
        status='not_checked' if safe else 'missing',
    )
    if not safe:
        return row
    # Read only episodes in the shown conversation set, with a shared cap on
    # unique document bodies. Existing cache hits cost no new read. Page spans
    # are supported too, but share that same cap rather than escaping it.
    if is_episode and ev.episode not in allowed:
        return row
    if ev.episode not in docs._bodies and len(docs._bodies) >= MAX_PROVENANCE_CONVERSATIONS:
        return row
    if is_episode:
        text = docs.body(ev.episode)
    else:
        if ev.episode not in docs._bodies:
            doc = evidence.source_document(memory_path, ev.episode)
            docs._bodies[ev.episode] = doc[1] if doc else None
        text = docs._bodies[ev.episode]
    if text is None:
        row.status = 'unavailable'
        row.source_available = False
        return row
    row.status = evidence.span_status(text, end=ev.end, hash=ev.hash, appendable=is_episode)
    if not ev.is_span():
        return row  # reasoning opens a source without asserting a quotation
    gaps = evidence.gap_ranges(fm, text) if is_episode else ()
    if evidence.touches_gap(ev.start, ev.end, gaps):
        row.status = 'gap'
    elif row.status == evidence.SPAN_STALE or ev.end > len(text):
        row.status = evidence.SPAN_STALE
        row.span = _stale_model(text, ev, held=docs.held(ev.episode))
    else:
        row.span = _span_model(text, ev.episode, ev.start, ev.end, hash=ev.hash, kind=ev.kind,
                               grown=row.status == evidence.SPAN_GROWN, held=docs.held(ev.episode))
    return row


def _sections(parsed, docs: _Episodes, shown: list[ProvenanceConversation],
              to_served=lambda offset: offset) -> tuple[list[SectionProvenance], bool]:
    sp = section_provenance
    raw = parsed.frontmatter.get(sp.FIELD)
    records = sp.decode(raw)
    matched = sp.matched(parsed.frontmatter, parsed.body)
    unavailable = sp.unavailable_sections(parsed.body, records or {})
    allowed = {ep for conversation in shown for ep in conversation.episode_ids}
    sections = []
    used = 0
    partial = False
    current_sections = sp.scan(parsed.body)
    for key, stored in (records or {}).items():
        if stored:
            current_sections.setdefault(key, [])
    for key, items in current_sections.items():
        links = matched.get(key, {})
        if (raw is not None and records is None) or key in unavailable:
            status = 'metadata_unavailable'
            links = {}
        else:
            status = ('tracked' if len(links) == len(items) and links else 'partial' if links else 'not_tracked')
        spans = sum(ev.is_span() for _, evs in links.values() for ev in evs)
        reasoning = sum(ev.kind == 'reasoning' for _, evs in links.values() for ev in evs)
        section = SectionProvenance(key=key, title=sp.TITLES[key], status=status, item_count=len(items),
            recorded_items=len(links), span_count=spans, reasoning_count=reasoning,
            unmatched_records=len((records or {}).get(key, {})) - len(links))
        for item in items:
            evs = links.get(item.key, ('', []))[1] if not item.ambiguous else []
            row = SectionProvenanceItem(identity=f'{key}:{item.key}:{item.text_hash}:{item.ranges[0][0]}', text=item.text,
                body_ranges=_served_ranges(item.ranges, to_served), ambiguous=item.ambiguous,
                evidence=[_section_evidence(ev, docs, allowed) for ev in evs])
            size = len(row.model_dump_json(by_alias=True).encode('utf-8'))
            if used + size > MAX_SECTION_RESPONSE_BYTES:
                section.partial = partial = True
                continue
            used += size
            section.items.append(row)
        sections.append(section)
    return sections, partial


def _served_ranges(ranges, to_served) -> list[list[int]]:
    """An item's ranges in the served prose. A range that would not keep its length there — it touches or crosses a
    removed claims block — cannot describe the item's text honestly, so the item's ranges are withheld (empty: not
    locatable in the served body) rather than shortened (review r2 B1)."""
    out = []
    for start, end in ranges:
        a, b = to_served(start), to_served(end)
        if a is None or b is None or b - a != end - start:
            return []
        out.append([a, b])
    return out


# The most entity pages one citations call parses (R-PB10). A page is parsed
# only when its raw text names the document, so this bounds the pathological
# case — a conversation cited by hundreds of pages — and `partial` says so.
MAX_CITATION_PAGES = 200


def _candidate_pages(memory_path: Path, doc_id: str) -> tuple[list[Path], bool]:
    """Entity pages that name ``doc_id``, in filename order, capped: ``source_spans``' index, which sees a page's ledger
    too (a page past 64k characters keeps its claims there, so scanning the page's own text missed them, ROR-16)."""
    entities_dir = Path(memory_path) / "entities"
    names = source_spans.pages_citing(memory_path, doc_id)
    return [entities_dir / n for n in names[:MAX_CITATION_PAGES]], len(names) > MAX_CITATION_PAGES


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
    fm, text = doc
    source = source_spans.Source.of(doc_id, fm, text)
    pages, partial = _candidate_pages(memory_path, doc_id)
    # Round 4 C3 (R4B-7): every span on this route points into `doc_id`, whose
    # frontmatter and text are already read above — the join reuses both, never
    # a second body read nor a scan of every episode's frontmatter.
    turns = turn_authorship.TurnAuthorship(memory_path, text=lambda ep: text if ep == doc_id else None,
                                           frontmatter=lambda ep: (fm or {}) if ep == doc_id else None)
    rows: list[EpisodeCitation] = []
    entities: list[EpisodeCitationEntity] = []
    # G162: how faithful this document's video words are, for every `media` row.
    media_fidelity = (video_state.fidelity(fm.get("watch_engine"))
                      if (fm or {}).get("source") == video_state.WATCH_SOURCE else "approximate")
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
            # A withdrawal record (G140 Q-R5) cites the conversation it was
            # written in, but it is bookkeeping, not a belief: listed, the
            # reader showed the agent's reason struck through as a "No longer
            # current" belief (final review).
            if is_record(claim):
                continue
            base = {
                "claim_id": claim.id, "subject_id": subject_id, "subject_name": subject_name,
                "subject_type": subject_type, "text": claim.text, "current": _current(claim),
                "authored_by": git_service.canonical_author(claim.authored_by), "observer": claim.observer,
            }
            if is_event(claim):
                # G141: a dated happening is not an obsolete belief. Only
                # a successor makes its citation an earlier event state.
                base.update(current=not bool(claim.superseded_by), event_status=claim.status,
                            event_day=claim.valid_from)
            mine = [ev for ev in claim.evidence if ev.episode == doc_id]
            spans = [ev for ev in mine if ev.is_span()]
            for ev in spans:
                span = source.span(ev.start, ev.end, ev.hash, ev.kind, claim_id=claim.id, current=base["current"])
                rows.append(EpisodeCitation(
                    **base, evidence=turn_authorship.evidence_model(ev, turns), kind=ev.kind,
                    start=span.at.start if span.at else None, end=span.at.end if span.at else None,
                    stale=span.status == source_spans.STALE, grown=span.status == source_spans.GROWN,
                    fidelity=media_fidelity if ev.kind == "media" else None, span=span,
                ))
            if spans:
                continue
            if mine:
                rows.append(EpisodeCitation(**base, evidence=EvidenceModel(**mine[0].to_dict()), kind="reasoning",
                                            span=source.nothing(claim_id=claim.id, current=base["current"])))
            elif doc_id in claim.source_episodes:
                hit = inbox_context.locate_mention(text, subject_name, subject_id)
                span = source.derived(hit[0], hit[1]) if hit else source.nothing("derived")
                rows.append(EpisodeCitation(**base, kind="derived", derived=True,
                                            start=span.at.start if span.at else None,
                                            end=span.at.end if span.at else None, span=span))
    rows.sort(key=lambda r: (r.start is None, r.start if r.start is not None else 0, r.subject_name, r.claim_id))
    return EpisodeCitations(episode=doc_id, citations=rows, entities=entities, partial=partial)
