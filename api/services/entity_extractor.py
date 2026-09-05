"""Stage 1: Entity & Relationship Extraction via litellm."""

import asyncio
import hashlib
import sys
from pathlib import Path
from typing import Callable

import litellm
from loguru import logger
from tqdm import tqdm

from api.config import Settings
from api.services import decay_policy, engine_errors, evidence
from api.services.json_parse import parse_json_object

EXTRACTION_SYSTEM_PROMPT = """You are an entity extraction system for a personal knowledge graph.
Given a conversation transcript, extract meaningful entities and the relationships between them.

Output valid JSON with this exact structure:
{
  "entities": [
    {
      "name": "Entity Name",
      "type": "person|project|company|concept|tool|skill|location|directory",
      "aliases": ["Mongo", "the db"],
      "summary": "1-3 sentence orientation. See SUMMARY LENGTH BY TYPE below.",
      "key_facts": ["atomic fact", "another atomic fact"],
      "history_entries": [
        {"date": "YYYY-MM-DD", "event": "What happened"}
      ],
      "links": [
        {"url": "https://...", "title": "Human title", "note": "what it is / why it came up"}
      ],
      "open_questions": ["unresolved point about this entity"],
      "tags": ["relevant", "tags"],
      "confidence": 0.7,
      "decay_class": "durable|active|volatile",
      "description": "Optional. Same content as summary; kept only for backward compatibility."
    }
  ],
  "relationships": [
    {
      "source": "Entity Name A",
      "target": "Entity Name B",
      "label": "specific relationship verb phrase",
      "evidence_quote": "the exact words from the transcript this relationship rests on (verbatim, at most 240 characters)"
    }
  ]
}

The entity body is rendered as ordered markdown sections: ## Summary, ## Key Facts,
## History, ## Links, ## Open Questions. The fields above map directly onto those
sections. ## Related is generated from `relationships` — do NOT emit a related field.

SUMMARY (## Summary) — the orientation line, "what is this and why does the user care":
- skill: 1-2 sentences. Procedural rule or preference, written as an instruction.
- location: 2-3 sentences. Where the physical place is, why it's relevant to the user.
- directory: 1-2 sentences. What the folder/path holds and why it matters.
- person: 2-4 sentences. Who they are, relationship to user, key context.
- tool: 2-4 sentences. What it is, how the user uses it, why it matters.
- concept: 3-4 sentences. Definition, relevance to user's work.
- project: 3-5 sentences. What it is, user's role, current status, goal.
- company: 3-5 sentences. What they do, user's relationship, relevance.
Do NOT cram every fact into the summary — atomic facts belong in key_facts.

KEY FACTS (## Key Facts) — this is where density lives:
- Emit every concrete, atomic fact stated about the entity: roles, stack components,
  dates-as-facts, identifiers, quantities, prices, versions, capacities, locations,
  affiliations, contact handles.
- One fact per bullet. Do NOT re-narrate the summary.
- Prefer 3-8 facts for project/company/tool; 2-5 for person/concept; 1-3 for
  location/directory. key_facts may be empty ONLY for skill.
- key_facts is REQUIRED (emit when any relevant content exists) for project, company, tool.

HISTORY ENTRIES (## History):
- Include dated events extracted from the conversation, one sentence each.
- Always emit history_entries for project and company when any dated event
  is present. Never silently drop a date you saw.
- For person entities, include key interaction dates when present.
- For concept/tool/skill/location/directory: only when the conversation contains
  specific dated events. Otherwise leave history_entries as an empty array.

LINKS (## Links):
- Extract EVERY URL mentioned in connection with this entity into links[] with a human
  title and a one-line note (what it is / why it came up). Never drop a URL into prose only.
- For tool entities, links is REQUIRED when any URL (docs, repo, homepage) appears.

OPEN QUESTIONS (## Open Questions):
- Capture unresolved points the user or system still needs to settle about this entity
  (an unconfirmed identity, an undecided choice, a missing date). Leave empty if none.

DECAY CLASS (optional, per entity) — how fast this belief should fade if it stops
being mentioned:
- volatile: a fact you expect to change within weeks (a current role, a status, a
  current focus, an in-flight decision).
- durable: a stable preference, a skill, or a long-lived concept that rarely moves.
- active: everything else — the default. Omit the field when unsure.
- NEVER EVERGREEN a belief here: "evergreen" is reserved for ingested artifacts
  (bookmarks, saved media) and the user — an extraction may only propose
  durable|active|volatile.

EXTRACTION GUIDELINES:
- Extract entities that are meaningful to the user's life, work, or goals. Skip trivial mentions.
- Confidence reflects how certain you are about the entity's attributes, not how important it is.
- If an entity is mentioned but you lack context to classify it confidently (e.g., a bare name
  with no role), still extract it but set confidence below 0.5.
- aliases: list any alternate surface forms used for the entity ("Mongo" for MongoDB,
  "the database", a nickname). Leave empty if there is only one name.
- Use wikilinks `[[Entity Name]]` inside summary and key_facts to reference other entities.
  Do NOT fabricate links bullets — those come only from real URLs in the source.
- Entity types must be exactly one of: person, project, company, concept, tool, skill, location, directory.
- DUE-DATES ARE NOT ENTITIES. Do NOT create a standalone entity for a deadline or a bare date.
  When something is due by a date, attach it as a relationship whose source is the thing that is
  due (the project/task), label is "due", and target is the date literal (e.g. "2026-06-30"). You
  may also note the date as a key_fact on that entity. Never emit a `deadline`-typed entity.
- DIRECTORY vs LOCATION. Classify a filesystem PATH — anything that looks like `/Users/...`, a
  `~/...` home-relative path, a repo/folder path, or a drive path — as type `directory`. Classify a
  physical, real-world place (a city, an office, a campus, a venue) as type `location`. When in doubt
  and the string is a slash/tilde path, prefer `directory`.
- Relationships are critical — capture every meaningful connection between entities with a specific
  verb phrase (e.g. "works at", "built with", "supervised by", "depends on", "evaluated against",
  "replaced by", "due"). Use short verb phrases, not full sentences or generic "related to".
- EVIDENCE QUOTE (required on every relationship): copy the shortest passage of the transcript,
  VERBATIM and at most 240 characters, that states this relationship — the sentence the user or
  assistant actually wrote, not your paraphrase. If the relationship is your own inference across
  several passages and no single passage states it, omit evidence_quote entirely. Never invent one:
  a quote that is not in the transcript is discarded and the relationship is recorded as inference."""

# Max concurrent LLM calls — stay under rate limits
MAX_CONCURRENCY = 10

# Chunk size in chars (~3K tokens). Long conversations get split into chunks
# so no information is lost. Each chunk gets its own extraction call. Kept small
# so no single call is enormous — with reasoning disabled (below) GLM 5.2 returns
# a chunk this size in ~5s, so smaller chunks are cheap and bound worst-case
# latency. (Was 24_000, which made big April threads time out at 600s.)
CHUNK_SIZE = 12_000
CHUNK_OVERLAP = 500  # Overlap to avoid splitting mid-sentence

# Hard wall-clock cap per extraction call. A hung/over-long generation fails
# fast and the episode requeues, rather than burning 10-20 min (litellm's 600s
# default let timed-out reasoning generations run to ~1300s).
EXTRACTION_TIMEOUT_S = 300

# Disable provider-side "reasoning"/thinking for extraction. Structured entity
# extraction does not benefit from chain-of-thought, and on GLM 5.2 reasoning
# was the cause of timeouts + empty/non-JSON responses. OpenRouter forwards this
# unified field to the model; passed via litellm's extra_body. Empirically: 21s
# -> 5s, 905 -> 284 completion tokens, JSON still valid. Override with
# ``settings.extraction_extra_body`` is intentionally NOT wired — reasoning-off
# is the right default for all extraction backends (no-op for non-reasoning ones).
EXTRACTION_EXTRA_BODY = {"reasoning": {"enabled": False}}

# Errors worth one retry inside a single chunk call: transient rate limits,
# timeouts, and a malformed/empty response (``_parse_json_lenient`` raises
# ValueError; ``json.JSONDecodeError`` is a ValueError subclass).
#
# G74(a): the tuple was litellm-exception-typed ONLY, so under
# ``llm_mode="agent"`` a CLI failure matched nothing and got zero retries.
# ``engine_errors.RETRYABLE`` adds the three subprocess failures worth one more
# attempt — deliberately NOT ``EngineThrottled`` (the breaker handles it; a
# retry would just spawn again), ``EngineUnavailable``, ``EngineExhausted`` or
# ``EngineModelNotFound``, all of which need a human rather than a retry.
_EXTRACT_RETRYABLE = (
    litellm.exceptions.RateLimitError,
    litellm.exceptions.Timeout,
    ValueError,
    *engine_errors.RETRYABLE,
)


# Historical name: the parser now lives in ``json_parse`` (six other call
# sites needed it). Kept as an alias — ``api/tests/test_extractor_robustness.py``
# and every reader of this module still reach for it here.
_parse_json_lenient = parse_json_object


def sanitize_decay_class(entity: dict) -> None:
    """Stage-1 anti-pollution rail, applied to ONE extracted entity dict.

    The extractor may PROPOSE ``durable|active|volatile``. Anything else — junk,
    a missing key, or ``evergreen`` (reserved for the ingest writers and the
    user) — is removed so the downstream writer falls back to its own default.
    Mutates in place; never raises.
    """
    if "decay_class" not in entity:
        return
    cls = decay_policy.agent_class(entity.pop("decay_class"))
    if cls is not None:
        entity["decay_class"] = cls.value


def _chunk_spans(content: str) -> list[tuple[int, int]]:
    """Chunk boundaries as ``(start, end)`` offsets into ``content``.

    Boundaries are unchanged from the original ``_chunk_content``; exposing
    them is what lets G118's evidence verification prefer a quote's
    occurrence inside the chunk the model actually saw (R11) while recording
    offsets into the WHOLE body — the stored text a viewer will slice.
    """
    if len(content) <= CHUNK_SIZE:
        return [(0, len(content))]
    spans: list[tuple[int, int]] = []
    start = 0
    while start < len(content):
        end = start + CHUNK_SIZE
        # Try to break at a newline near the boundary
        if end < len(content):
            newline_pos = content.rfind("\n", end - 200, end)
            if newline_pos > start:
                end = newline_pos + 1
        spans.append((start, end))
        start = end - CHUNK_OVERLAP
    return spans


def _chunk_content(content: str) -> list[str]:
    """Split long content into overlapping chunks."""
    return [content[s:e] for s, e in _chunk_spans(content)]


async def _extract_chunk(
    ep_id: str,
    chunk: str,
    chunk_idx: int,
    total_chunks: int,
    settings: Settings,
    *,
    _attempt: int = 0,
) -> dict:
    """Extract entities from a single chunk via LLM.

    Reasoning is disabled and a hard timeout is set (see module constants). On a
    transient failure (rate limit / timeout / malformed-or-empty response) the
    call is retried ONCE with a short backoff; a second failure propagates so the
    episode is counted failed and requeued. JSON parsing is lenient to tolerate a
    reasoning model that wraps the object in fences or prose.
    """
    try:
        from api.services.providers import resolve_llm_fn

        llm_fn = resolve_llm_fn(
            settings, model=settings.litellm_model, completion=litellm.acompletion, stage="extraction"
        )
        response = await llm_fn(
            messages=[
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": chunk},
            ],
            response_format={"type": "json_object"},
            extra_body=EXTRACTION_EXTRA_BODY,
            timeout=EXTRACTION_TIMEOUT_S,
        )
        raw = response.choices[0].message.content
        return _parse_json_lenient(raw)
    except _EXTRACT_RETRYABLE as e:
        if _attempt >= 1:
            raise
        # Rate limits need a real cooldown; timeouts/parse failures retry fast.
        slow = isinstance(e, (litellm.exceptions.RateLimitError, engine_errors.EngineTimeout))
        backoff = 10 if slow else 2
        logger.warning(
            f"  {ep_id} chunk {chunk_idx + 1}/{total_chunks} — "
            f"{type(e).__name__}, retrying in {backoff}s..."
        )
        await asyncio.sleep(backoff)
        return await _extract_chunk(
            ep_id, chunk, chunk_idx, total_chunks, settings, _attempt=_attempt + 1
        )


async def extract(
    episodes: list[dict],
    settings: Settings,
    *,
    cancel_check: Callable[[], bool] | None = None,
    progress_callback: Callable[[], None] | None = None,
    on_episode_done: Callable[[dict], None] | None = None,
) -> list[dict]:
    """Extract entities and relationships from unprocessed episodes (parallel).

    ``cancel_check`` (sleep-control): an optional zero-arg predicate polled at
    the natural per-episode checkpoints in this fan-out — before an episode
    even queues for a semaphore slot, and again right after it acquires one
    (it may have waited a while). Once it starts returning ``True``, no
    NEW episode starts any work (no LLM call spent) — its slot in ``results``
    stays ``None``, so it comes back out of ``extract`` exactly like a failed
    episode: absent from the returned list, left ``processed: false`` by the
    caller. Episodes already mid-``_extract_chunk`` when the flag flips are
    NOT interrupted — they finish normally ("let in-flight work finish").
    ``None`` (the default, and every existing call site) means "never
    cancel" — behavior is unchanged.

    ``progress_callback`` (sleep debt, G106 amendment): an optional zero-arg
    callback fired exactly once per episode, the instant that episode is
    fully done with THIS stage — success, failure, empty-content fast path,
    or cancelled-skip all count (mirrors the existing ``tqdm`` bar's own
    ``update(1)``, which fires on every one of those paths already). This is
    what makes ``SleepStatusResponse``'s live "Progress %" during Stage 1
    possible without waiting for the whole fan-out to finish.

    ``on_episode_done`` (G125 R3): an optional one-arg callback fired with
    the episode dict itself, on every one of the same outcomes as
    ``progress_callback`` above (right after it, in ``process_one``'s
    ``finally``) — the study list's per-source countdown needs the
    episode's ``origin`` to know WHICH source just finished, which the
    zero-arg ``progress_callback`` can't carry without breaking its
    existing callers.
    """
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    results: list[dict | None] = [None] * len(episodes)
    success = 0
    failed = 0
    total = len(episodes)

    progress = tqdm(
        total=total,
        desc="Stage 1: extract",
        unit="ep",
        file=sys.stderr,
        bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}{postfix}]",
        leave=True,
    )
    entities_so_far = 0

    async def _do_process(i: int, episode: dict) -> None:
        nonlocal success, failed, entities_so_far
        ep_id = episode["id"]
        content = episode["content"]

        # Sleep-control checkpoint 1: before this episode even queues for a
        # semaphore slot. A cancel requested any time before this task got
        # its turn on the event loop means it never spends a call.
        if cancel_check is not None and cancel_check():
            return

        if not content.strip():
            # No LLM call needed, but record a zero-entity result so the Sleep
            # cycle marks this episode processed (done — nothing to extract)
            # instead of leaving it queued and re-scanning it every run.
            results[i] = {
                "episode_id": ep_id,
                "episode_timestamp": episode.get("timestamp"),
                "origin": episode.get("origin", "unknown"),
                "entities": [],
                "relationships": [],
            }
            success += 1
            return

        spans = _chunk_spans(content)
        chunks = [content[s:e] for s, e in spans]

        async with semaphore:
            # Sleep-control checkpoint 2: this task may have waited a while
            # for a slot to free up — re-check right after acquiring one, so
            # a cancel that arrived during that wait still stops it before
            # its first (real) LLM call.
            if cancel_check is not None and cancel_check():
                return
            try:
                # Extract from all chunks and merge results
                all_entities = []
                all_relationships = []
                for ci, chunk in enumerate(chunks):
                    parsed = await _extract_chunk(ep_id, chunk, ci, len(chunks), settings)
                    all_entities.extend(parsed.get("entities", []))
                    chunk_rels = [r for r in (parsed.get("relationships", []) or []) if isinstance(r, dict)]
                    # G118: verify the cited passage against the body this
                    # chunk came from, preferring the chunk window (R11). The
                    # quote is consumed here — nothing downstream sees it.
                    for rel in chunk_rels:
                        evidence.attach_relationship_evidence(rel, ep_id, content, window=spans[ci])
                    all_relationships.extend(chunk_rels)

                ep_origin = episode.get("origin", "unknown")
                for entity in all_entities:
                    entity["source_episode"] = ep_id
                    entity["source_episode_timestamp"] = episode.get("timestamp")
                    entity["origin"] = ep_origin
                    sanitize_decay_class(entity)
                for rel in all_relationships:
                    rel["source_episode"] = ep_id
                    rel["source_episode_timestamp"] = episode.get("timestamp")
                    rel["origin"] = ep_origin

                results[i] = {
                    "episode_id": ep_id,
                    "episode_timestamp": episode.get("timestamp"),
                    "origin": ep_origin,
                    "entities": all_entities,
                    "relationships": all_relationships,
                }

                success += 1
                entities_so_far += len(all_entities)
                progress.set_postfix_str(
                    f"ok={success} fail={failed} entities={entities_so_far}",
                    refresh=False,
                )

            # NOTE: transient failures (rate limit / timeout / malformed JSON)
            # are already retried once INSIDE _extract_chunk; anything reaching
            # here is a final failure. The episode is left out of `results`
            # (results[i] stays None) so the Sleep cycle requeues it.
            except litellm.exceptions.AuthenticationError as e:
                failed += 1
                logger.error(f"  [{i+1}/{total}] {ep_id} — auth error (check API key): {e}")
            except litellm.exceptions.NotFoundError:
                failed += 1
                logger.error(f"  [{i+1}/{total}] {ep_id} — model not found: {settings.litellm_model}")
            # G74(a): the agent rung's failures are subprocess-shaped. Each one
            # names its own fix so the Sleep page never says "check API credits"
            # for a plan that has no credits to check.
            except engine_errors.EngineThrottled as e:
                failed += 1
                logger.error(f"  [{i+1}/{total}] {ep_id} — Claude plan throttled: {e}")
            except engine_errors.EngineExhausted as e:
                failed += 1
                logger.error(f"  [{i+1}/{total}] {ep_id} — Claude plan budget exhausted: {e}")
            except engine_errors.EngineUnavailable as e:
                failed += 1
                logger.error(f"  [{i+1}/{total}] {ep_id} — Claude Code is signed out or missing: {e}")
            except engine_errors.EngineModelNotFound as e:
                failed += 1
                logger.error(
                    f"  [{i+1}/{total}] {ep_id} — model not accepted by the Claude CLI "
                    f"({settings.agent_model}): {e}"
                )
            except engine_errors.EngineError as e:
                failed += 1
                logger.error(f"  [{i+1}/{total}] {ep_id} — engine failure: {type(e).__name__}: {e}")
            except Exception as e:
                failed += 1
                logger.error(f"  [{i+1}/{total}] {ep_id} — {type(e).__name__}: {e}")

    async def process_one(i: int, episode: dict) -> None:
        try:
            await _do_process(i, episode)
        finally:
            progress.update(1)
            if progress_callback is not None:
                progress_callback()
            if on_episode_done is not None:
                on_episode_done(episode)

    # Fire all tasks with semaphore-controlled concurrency
    try:
        tasks = [process_one(i, ep) for i, ep in enumerate(episodes)]
        await asyncio.gather(*tasks)
    finally:
        progress.close()

    all_extracted = [r for r in results if r is not None]
    logger.info(f"Extraction done: {success} succeeded, {failed} failed out of {total}")
    return all_extracted


# --------------------------------------------------------------------------- #
# M5e Stage-1: claim emission (back-compatible projection of the extract shape)
# --------------------------------------------------------------------------- #
#
# The existing entity/relationship extraction shape is the
# ``observer=agent, context=general, epistemic=explicit, source_trust=
# agent_extracted`` special case (D2 ADDENDUM (4) + sleep-trust §1). Rather than
# rewrite the prompt, we deterministically project the already-extracted
# relationship dicts into perspectival ``Claim`` objects, with ``origin``
# propagated from the episode (origin-and-harness-sync.md). Routine extraction
# defaults to ``observer=agent``; manual-edit / clarification paths set
# ``source_trust=user_stated, origin=manual_edit|clarification`` upstream.


def _claim_date(timestamp: str | None, episode_id: str) -> str:
    """A YYYY-MM-DD date from the episode timestamp, falling back to its id."""
    ts = str(timestamp or "").strip()
    if len(ts) >= 10 and ts[4:5] == "-" and ts[7:8] == "-":
        return ts[:10]
    # episode ids are ep_YYYY-MM-DD_NNN — recover the date head if present.
    import re

    m = re.search(r"(\d{4}-\d{2}-\d{2})", episode_id or "")
    return m.group(1) if m else ""


def _emit_claim_id(subject: str, predicate: str, obj: str, valid_from: str) -> str:
    digest = hashlib.sha1(
        f"{subject}\x00{predicate}\x00{obj}\x00{valid_from}".encode("utf-8")
    ).hexdigest()[:8]
    base = valid_from or "undated"
    return f"clm_{base}_{digest}"


def entities_to_claims(extracted: list[dict], memory_path: Path | None) -> list:
    """Project Stage-1 extraction output into perspectival ``Claim`` objects.

    Each relationship ``{source, target, label}`` becomes one claim
    ``(subject=slug(source), predicate=normalize(label), object=slug(target))``
    with the agent/general/explicit/agent_extracted defaults and the episode's
    ``origin``. The raw label is carried on ``claim.predicate_raw`` so Stage 3 can
    emit the mandatory ``normalization-audit`` nudge when a fold happened.

    ``memory_path`` resolves the predicate normalizer; ``None`` slugifies labels
    deterministically (used by hermetic tests). Deterministic claim ids keep the
    projection idempotent across Sleep cycles.
    """
    from api.services import predicates
    from api.services.claims import Claim, Evidence
    from api.services.id_utils import sanitize_id

    normalize = predicates.load_normalizer(memory_path) if memory_path is not None else None

    claims: list = []
    by_id: dict[str, Claim] = {}
    for extraction in extracted:
        episode_id = str(extraction.get("episode_id", "") or "")
        origin = str(extraction.get("origin") or "unknown")
        for rel in extraction.get("relationships", []) or []:
            source = str(rel.get("source", "") or "").strip()
            target = str(rel.get("target", "") or "").strip()
            raw_label = str(rel.get("label", "") or "").strip() or "relates to"
            if not source or not target:
                continue
            subject = sanitize_id(source)
            obj = sanitize_id(target)
            if subject == obj:
                continue
            if normalize is not None:
                predicate = normalize(raw_label) or "relates-to"
            else:
                predicate = _slug_label(raw_label)
            ep = str(rel.get("source_episode", "") or episode_id)
            valid_from = _claim_date(rel.get("source_episode_timestamp"), ep)
            cid = _emit_claim_id(subject, predicate, obj, valid_from)
            rel_evidence = [
                Evidence.from_dict(e) for e in (rel.get("evidence") or []) if isinstance(e, dict)
            ]
            if cid in by_id:
                # Overlapping chunks re-emit the same triple; the first claim
                # wins and only gains the later chunk's evidence (G118).
                first = by_id[cid]
                for ev in rel_evidence:
                    if ev not in first.evidence:
                        first.evidence.append(ev)
                continue
            claim = Claim(
                id=cid,
                text=f"{source} {raw_label} {target}",
                subject=subject,
                predicate=predicate,
                object=obj,
                object_kind="node",
                observer="agent",
                context="general",
                epistemic="explicit",
                source_trust="agent_extracted",
                confidence=float(rel.get("confidence", 0.6) or 0.6),
                valid_from=valid_from or None,
                source_episodes=[ep] if ep else [],
                origin=origin,
                evidence=rel_evidence,
            )
            # The pre-normalization label (for the Stage-3 normalization audit).
            setattr(claim, "predicate_raw", raw_label)
            by_id[cid] = claim
            claims.append(claim)
    return claims


def _slug_label(label: str) -> str:
    import re

    s = (label or "").strip().lower()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^a-z0-9\-]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "relates-to"
