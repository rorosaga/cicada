"""G102 cheap slice — site recon over the OG text ALREADY STORED on a media page.

The G102 ruling: a summary is a nicer card; what makes a saved link part of
the graph is running entity extraction over what the page is about and
routing the mentions through Stage-2 resolution, so a bookmark gets edges to
the concepts, tools, companies and people it concerns. This module is the
zero-new-fetch first slice: the EXISTING Stage-1 prompt over ``title +
## Description`` (OpenGraph at ingest, or a backfill summary), batched
``link_recon_batch_size`` links per call (R4), attributed back to each link
by surface form, matched against existing entities with the EXISTING Stage-2
judgment (``entity_resolver.match_existing``, R5) and written as ``about``
claims on the media page (R6) that Stage 5.7 projects into edges. The target
page is never touched — a blurb mentioning a tool is not the user referencing
it, and bumping ``last_referenced`` would defeat decay ("time as a signal").
Unmatched mentions become pending candidates, never pages.

Reached only from ``link_enrichment.backfill`` (the maintenance endpoint or
the Sleep tail) — never at capture time and never from a read path (G80).
The rulings (R1-R9) are in
``docs/superpowers/plans/2026-09-02-link-summaries-backfill.md``.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Awaitable, Callable

from loguru import logger

# Both are cycle-free at module level: ``engine_errors`` is import-free by
# design and ``markdown_parser`` imports nothing from ``api.services``.
from api.services import engine_errors, evidence, markdown_parser
from api.services.claims import Claim, Evidence

# R4: each card's title+description is clipped so 8 cards (~400 tokens each)
# under the ~1.1k-token extraction prompt stay one small call.
MAX_WORDS_PER_LINK = 300
# R6: only these types are ever related. A ``skill`` is procedural memory
# about the user and a ``directory`` is a path on their machine — neither is
# something a web page can be "about"; ``media``/``deadline`` are excluded by
# the same reasoning as ``PRODUCIBLE_ENTITY_TYPES``.
RELATABLE_TYPES = frozenset({"person", "project", "company", "concept", "tool", "location"})

ExtractFn = Callable[[str, object], Awaitable[list[dict]]]
MatchFn = Callable[[dict, dict, object, dict], Awaitable[str | None]]


@dataclass
class LinkCard:
    media_id: str
    title: str
    url: str
    description: str
    episode: str

    @property
    def text(self) -> str:
        return f"{self.title}\n{self.description}"


def _clip_words(text: str, n: int) -> str:
    words = (text or "").split()
    return " ".join(words[:n]) + (" …" if len(words) > n else "")


def render_batch(cards: list[LinkCard]) -> str:
    """The 'transcript' the Stage-1 prompt is shown: one numbered card per link."""
    parts = [
        "Saved links the user bookmarked. For each one: the page title, its URL, and "
        "the page's own description. Extract the entities these pages are ABOUT."
    ]
    for i, c in enumerate(cards, 1):
        parts.append(f"[{i}] Title: {c.title}\nURL: {c.url}\nDescription: {_clip_words(c.description, MAX_WORDS_PER_LINK)}")
    return "\n\n".join(parts)


_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall((text or "").lower()) if len(t) >= 2]


def _mentions(surface: str, haystack_tokens: set[str], haystack_text: str) -> bool:
    """Whole-token match — never a bare substring: "ROS" must not be found
    inside "prose", nor "Go" inside "Google". A multi-word surface may also
    match as an exact phrase so "knowledge graph" grounds against
    "knowledge-graph"."""
    toks = _tokens(surface)
    if not toks:
        return False
    if len(toks) >= 2 and surface.strip().lower() in haystack_text:
        return True
    return all(t in haystack_tokens for t in toks)


def attribute(entities: list[dict], cards: list[LinkCard]) -> dict[str, list[dict]]:
    """media_id -> entities whose name/alias appears on that card (R4).

    The prompt has no per-link attribution, so grounding is literal: an
    entity is attributed to every card whose ``title + description`` contains
    its name or an alias (case-folded phrase, or every name token present).
    An entity on no card is dropped — that is also the hallucination rail:
    the prompt's "extract every URL / history" instincts produce nothing
    groundable here, and anything not literally on the card cannot be an
    ``about`` edge. ``skill``/``directory`` are never related (R6).
    """
    out: dict[str, list[dict]] = {c.media_id: [] for c in cards}
    prepared = [(c, set(_tokens(c.text)), c.text.lower()) for c in cards]
    for ent in entities:
        if str(ent.get("type") or "").lower() not in RELATABLE_TYPES:
            continue
        surfaces = [str(ent.get("name") or "")] + [str(a) for a in (ent.get("aliases") or [])]
        for card, toks, text in prepared:
            if any(_mentions(s, toks, text) for s in surfaces):
                out[card.media_id].append(ent)
    return out


def scan_recon(memory_path: Path, settings) -> list[LinkCard]:
    """Media pages with a substantive ``## Description`` and no ``recon_attempted``,
    oldest-imported first — its own scan (R2) so a link whose description
    landed in an earlier run is still picked up. Junk (interstitial / login
    wall) and excluded media types are skipped with the same helpers the
    backfill scan uses, so the two scans can never disagree about a page."""
    from api.services.link_enrichment import (
        _excluded_media, _extract_description_section, _is_substantive, _saved_sort_key, classify_page,
    )

    min_len = int(getattr(settings, "link_enrich_min_desc_len", 120) or 120)
    entities_dir = Path(memory_path) / "entities"
    cards: list[tuple[str, LinkCard]] = []
    if not entities_dir.exists():
        return []
    for fp in sorted(entities_dir.glob("media-*.md")):
        try:
            parsed = markdown_parser.parse(fp)
        except Exception:
            continue
        fm = parsed.frontmatter or {}
        if fm.get("type") != "media" or fm.get("recon_attempted") or fm.get("enrichment_status") == "junk":
            continue
        media = fm.get("media") if isinstance(fm.get("media"), dict) else {}
        url = str(media.get("url") or "")
        title = str(fm.get("name") or fp.stem)
        if _excluded_media(url, str(media.get("media_type") or "")) or classify_page(title, url):
            continue
        desc = _extract_description_section(parsed.body)
        if not _is_substantive(desc, min_len):
            continue
        episodes = fm.get("source_episodes") or []
        cards.append((_saved_sort_key(fm), LinkCard(fp.stem, title, url, desc, str(episodes[0]) if episodes else "")))
    cards.sort(key=lambda t: (t[0], t[1].media_id))
    return [c for _, c in cards]


def _build_about_claim(media_id: str, target_id: str, target_name: str, confidence: float,
                       episode: str, today: str, model: str,
                       spans: list[Evidence] | None = None) -> Claim:
    """R6: the claim lives on the MEDIA page, object is the target's node id.
    The id is deterministic in ``(media, target)`` so ``_append_claim``'s
    id-dedupe makes a re-run a no-op; confidence is capped at 0.7 because a
    blurb is weaker evidence than a conversation. ``about`` is not in the
    predicate seed, so the cardinality oracle treats it as multi-valued —
    many ``about`` objects on one link can never raise a conflict item.
    ``spans`` (G118 R12) is the surface-form evidence ``_page_evidence`` found
    — named ``spans`` rather than ``evidence`` so the module import is never
    shadowed inside this function."""
    return Claim(
        id=f"clm_about_{hashlib.sha1(f'{media_id}\x00{target_id}'.encode()).hexdigest()[:8]}",
        text=f"This saved page is about {target_name}.",
        subject=media_id, predicate="about", object=target_id, object_kind="node",
        observer="agent", context="general", epistemic="explicit", source_trust="agent_extracted",
        confidence=round(min(float(confidence or 0.5), 0.7), 2),
        valid_from=today, recorded_at=today,
        source_episodes=[episode] if episode else [],
        authored_by=model or "unknown", origin="sleep/link_recon",
        evidence=list(spans or []),
    )


def _page_evidence(media_id: str, page_text: str, ent: dict) -> list[Evidence]:
    """R12: the surface form recon grounded on, as a ``page`` span into the
    media page's prose — name first, then each alias, whole-word only (the
    whole-token rail ``_mentions`` applies to a single-token name; a
    multi-token surface is bounded the same way here, tighter than the
    phrase match ``attribute()`` accepts). A name present only in the
    frontmatter title, or only as scattered tokens, is ``reasoning``: a span
    must point at text that is actually there (spans, not copies — G118).
    The document hash is kept on the ``reasoning`` entry too, so a viewer can
    still open the page (R6)."""
    surfaces = [str(ent.get("name") or "")] + [str(a) for a in (ent.get("aliases") or [])]
    for surface in surfaces:
        span = evidence.locate(page_text, surface, whole_word=True)
        if span is not None:
            return [Evidence(episode=media_id, start=span[0], end=span[1], kind="page",
                             hash=evidence.body_hash(page_text))]
    return [evidence.reasoning(media_id, hash=evidence.body_hash(page_text))]


async def default_extract(text: str, settings) -> list[dict]:
    """One Stage-1 call over a rendered batch — the SAME prompt, engine seam,
    one-retry policy and telemetry as the cycle's extraction — through the
    per-chunk ``entity_extractor._extract_chunk``, deliberately NOT the public
    ``extract``: ``extract`` catches every engine failure per episode
    (``entity_extractor.extract``), counts it ``failed`` and drops the
    episode from its result, which here would read as "the batch contained
    no entities" and stamp ``recon_attempted`` on eight links that were never
    looked at. ``_extract_chunk`` retries a transient error once and then
    raises, which is what R9 needs. The batch is one chunk by construction
    (8 x 300 words is well under ``CHUNK_SIZE``); ``sanitize_decay_class`` is
    irrelevant here because recon never creates a page.
    """
    from api.services.entity_extractor import _extract_chunk

    parsed = await _extract_chunk("link-recon", text, 0, 1, settings)
    return [e for e in (parsed.get("entities") or []) if isinstance(e, dict)]


async def default_match(entity: dict, existing_by_name: dict, settings, cache: dict) -> str | None:
    from api.services.entity_resolver import match_existing

    return await match_existing(entity, existing_by_name, settings, cache=cache)


def _default_indexer(memory_path: Path):
    """The pending-candidate store, guarded exactly as ``resolve()`` guards
    it: ``None`` when the embedding backend cannot load, and recon then
    simply records no candidates rather than failing the run."""
    try:
        from api.services.vector_index import SqliteVecIndexer

        return SqliteVecIndexer(memory_path)
    except Exception as e:
        logger.debug(f"pending store unavailable for link recon: {e}")
        return None


async def run_recon(memory_path: Path, settings, report, *, limit=None, extract_fn=None, match_fn=None,
                    indexer_factory=None, engine=None, today: date | None = None) -> None:
    """Relate up to ``limit`` links (default ``link_recon_max_per_cycle``);
    mutates ``report`` (extracted/related/llm_calls/judge_calls/remaining_recon/
    engine_aborted, plus the manifest). Never raises.

    R9: an engine failure (``EngineError``, or a litellm auth/not-found error
    via ``_is_engine_failure``) from the extractor or the judge aborts the
    run and leaves every page in the current and later batches UNMARKED —
    they stay candidates. Only a batch that actually came back marks its
    pages. ``judge_calls`` piggybacks on the judge cache growing by one entry
    per LLM verdict (``_find_llm_candidate_match`` writes ``cache[(name, id)]``
    after each call); an injected ``match_fn`` that never touches ``cache``
    reports 0, which is correct.
    """
    from api.services import entity_resolver
    from api.services.link_enrichment import _append_claim
    # ``sleep_cycle`` imports ``link_enrichment`` lazily; importing back into
    # it lazily here keeps that a one-way street at module level.
    from api.services.sleep_cycle import _load_existing_entities

    memory_path = Path(memory_path)
    today = today or date.today()
    cap = int(limit if limit is not None else getattr(settings, "link_recon_max_per_cycle", 40) or 40)
    batch = max(1, int(getattr(settings, "link_recon_batch_size", 8) or 8))
    cards = scan_recon(memory_path, settings)
    report.remaining_recon = max(0, len(cards) - cap)
    cards = cards[:cap]
    if not cards:
        return
    extract_fn = extract_fn or default_extract
    match_fn = match_fn or default_match
    indexer = (indexer_factory or _default_indexer)(memory_path)
    model = str(getattr(settings, "agent_model" if engine == "claude-cli" else "litellm_model", "") or "unknown")
    # Media pages are excluded from the match index: a link is never "about"
    # another link, and the Stage-2 fuzzy matcher would otherwise pair two
    # bookmarks with similar titles.
    existing = entity_resolver.existing_by_name(
        [e for e in _load_existing_entities(memory_path) if (e["frontmatter"] or {}).get("type") != "media"]
    )
    name_of = {e["id"]: str((e["frontmatter"] or {}).get("name") or e["id"]) for e in existing.values()}
    cache: dict = {}
    pending_written = 0
    for start in range(0, len(cards), batch):
        chunk = cards[start:start + batch]
        try:
            entities = await extract_fn(render_batch(chunk), settings)
            # Counted only once the engine ANSWERED (final review M3, the
            # fetch tier's Task 1 review M2 rule): ``_commit_backfill`` keys
            # the ``Cicada-Author:`` / ``Cicada-Engine:`` trailers on this
            # counter, and an R9 abort on the first batch must not stamp a
            # model on a commit whose only writes are the zero-LLM reuse
            # claims (themselves ``authored_by: cicada``) and junk marks.
            report.llm_calls += 1
        except Exception as e:
            if isinstance(e, engine_errors.EngineError) or _looks_like_engine_failure(e):
                report.engine_aborted = type(e).__name__
                logger.warning(f"link recon engine failure — leaving pages unmarked: {type(e).__name__}: {e}")
                report.remaining_recon += len(cards) - start
                return
            # A malformed response still cost a model call — honest in that
            # direction too.
            report.llm_calls += 1
            logger.warning(f"link recon extraction failed for a batch: {type(e).__name__}: {e}")
            entities = []
        report.extracted += len(entities)
        by_card = attribute(entities, chunk)
        for card in chunk:
            related_ids: list[tuple[str, dict]] = []
            for ent in by_card.get(card.media_id, []):
                try:
                    before = len(cache)
                    target = await match_fn(ent, existing, settings, cache)
                    report.judge_calls += len(cache) - before
                except Exception as e:
                    if isinstance(e, engine_errors.EngineError) or _looks_like_engine_failure(e):
                        report.engine_aborted = type(e).__name__
                        logger.warning(f"link recon judge engine failure — leaving pages unmarked: {type(e).__name__}")
                        report.remaining_recon += len(cards) - start
                        return
                    target = None
                if target and target != card.media_id:
                    related_ids.append((target, ent))
                elif indexer is not None:
                    # R5: a first mention is recorded exactly as Stage 2
                    # records one — the promotion model's rung 1 — so a
                    # later conversation mention promotes it with this link
                    # as backfilled context. Never a page.
                    #
                    # Never over an existing entry (final review M2):
                    # ``index_pending_entity`` REPLACES the same-named
                    # entry, and a candidate Stage 2 recorded from a real
                    # conversation carries that conversation's episode,
                    # ``history_entries`` and confidence — provenance
                    # ``resolve()`` merges into the page on promotion. A
                    # blurb's thinner version must not erase it. The
                    # untouched entry counts as neither written nor failed.
                    try:
                        from api.services.vector_index import PendingEntity

                        name = str(ent.get("name") or "")
                        if name and indexer.pending_by_name(name) is not None:
                            continue
                        indexer.index_pending_entity(PendingEntity(
                            name=name, type=str(ent.get("type") or "concept"),
                            description=str(ent.get("summary") or ent.get("description") or card.title),
                            source_episode=card.episode, confidence=float(ent.get("confidence", 0.3) or 0.3),
                            tags=list(ent.get("tags") or []), history_entries=[],
                        ))
                        pending_written += 1
                    except Exception as e:
                        logger.debug(f"pending candidate not recorded: {type(e).__name__}: {e}")
            # G118: evidence is located on the page text BEFORE any claim is
            # appended — R1 makes that text invariant to the append anyway,
            # but reading once per card keeps this one parse.
            page_text = evidence.source_text(memory_path, card.media_id) or ""
            fp = memory_path / "entities" / f"{card.media_id}.md"
            seen: set[str] = set()
            for target, ent in related_ids:
                if target in seen:
                    continue
                seen.add(target)
                claim = _build_about_claim(card.media_id, target, name_of.get(target, target),
                                           ent.get("confidence", 0.5), card.episode, today.isoformat(), model,
                                           spans=_page_evidence(card.media_id, page_text, ent))
                if _append_claim(fp, claim):
                    report.related += 1
            # R6: the media page's ``related:`` list gains the target id so
            # ``/sources``'s ``related_count`` and the card's Related pills
            # reflect the edge; the TARGET page gets nothing.
            parsed = markdown_parser.parse(fp)
            related = [str(r) for r in (parsed.frontmatter.get("related") or [])]
            for target in seen:
                if target not in related:
                    related.append(target)
            parsed.frontmatter["related"] = related
            parsed.frontmatter["recon_attempted"] = today.isoformat()
            parsed.frontmatter["recon_status"] = "ok" if seen else "no_matches"
            markdown_parser.write(fp, parsed.frontmatter, parsed.body)
            # Honest manifest: `related` only when an edge landed; a page that
            # matched nothing is recorded as `recon no_matches` (still a write
            # — the stamp — so it belongs in the commit's file list).
            action = "related" if seen else "recon no_matches"
            report.touched(f"entities/{card.media_id}.md",
                           f"entities/{card.media_id}.md: {action} (source: {card.episode or 'n/a'}, trigger: sleep/link_recon)")
    if indexer is not None and pending_written:
        try:
            indexer.rebuild_pending_index()
        except Exception as e:
            logger.debug(f"pending index rebuild skipped: {e}")
    if report.related:
        # Stage 5.7 owns the projection; calling it here means an endpoint
        # run shows its edges immediately instead of after the next cycle.
        from api.services.graph_builder import regenerate_edges_from_claims

        edges_file = memory_path / "graph_edges.yaml"
        before = edges_file.read_bytes() if edges_file.exists() else b""
        try:
            regenerate_edges_from_claims(memory_path)
        except Exception as e:
            logger.warning(f"claim-edge regeneration after link recon failed: {type(e).__name__}: {e}")
        if edges_file.exists() and edges_file.read_bytes() != before:
            report.touched("graph_edges.yaml", "graph_edges.yaml: updated (trigger: sleep/link_recon)")


def _looks_like_engine_failure(exc: BaseException) -> bool:
    from api.services.link_enrichment import _is_engine_failure

    return _is_engine_failure(exc)
