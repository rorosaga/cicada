import asyncio
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from loguru import logger

from api.config import Settings
from api.services import git_service, markdown_parser


@dataclass
class SleepState:
    status: str = "idle"
    cycle_id: str | None = None
    started_at: str | None = None
    progress: str | None = None
    # Set to a string when the most recent run hit an exception. The benchmark
    # harness reads this to distinguish a real success from a swallowed
    # exception, since ``run`` deliberately catches everything internally so
    # the FastAPI background task doesn't crash the API process.
    error: str | None = None
    # Non-fatal warning surfaced to the Sleep page when the main entity writes
    # + commit succeeded but a post-cycle step (e.g. LEANN index rebuild) did
    # not. Makes "completed but indexes stale" visible instead of reporting it
    # as a clean success.
    index_warning: str | None = None
    # Structured progress metrics for the Sleep dashboard. ``stage`` is the
    # index of the *completed* stage (0 = not started, 5 = all done). Counters
    # are populated at each stage boundary and ticked live into ``/sleep/status``
    # so the UI can animate a real progress bar instead of a text tooltip.
    stage: int = 0
    total_stages: int = 5
    episodes_total: int = 0
    entities_created: int = 0
    entities_updated: int = 0
    relationships_created: int = 0
    skills_detected: int = 0
    # Resumable queue (robust partial runs): how many episodes this cycle
    # actually consolidated vs. how many failed Stage-1 extraction and were
    # left ``processed: false`` for the next trigger to retry. ``requeued`` > 0
    # means "completed, but re-run Sleep to finish the rest".
    episodes_processed: int = 0
    episodes_requeued: int = 0


_state = SleepState()
_lock = asyncio.Lock()


def get_sleep_state() -> SleepState:
    return _state


async def run(settings: Settings, cycle_id: str) -> None:
    """Execute the 5-stage Sleep cycle pipeline."""
    global _state

    _state.status = "running"
    _state.cycle_id = cycle_id
    _state.started_at = datetime.now().isoformat()
    _state.progress = "Starting..."
    _state.error = None
    _state.index_warning = None
    # Reset structured metrics at the top of every run so the Sleep dashboard
    # doesn't show stale counts from a previous cycle.
    _state.stage = 0
    _state.episodes_total = 0
    _state.entities_created = 0
    _state.entities_updated = 0
    _state.relationships_created = 0
    _state.skills_detected = 0
    _state.episodes_processed = 0
    _state.episodes_requeued = 0

    memory_path = settings.memory_path
    logger.info(f"Sleep cycle {cycle_id} started — model: {settings.litellm_model}")

    try:
        # M5e: ensure the runtime predicate-normalization map exists (idempotent,
        # non-clobbering) so Stage 2 predicate folding + Stage 3 cardinality keying
        # have a controlled vocabulary to key on.
        try:
            from api.services import predicates
            predicates.install_predicate_map(memory_path)
        except Exception as e:
            logger.warning(f"predicate map install skipped: {type(e).__name__}: {e}")

        # Collect unprocessed episodes
        episodes = _get_unprocessed_episodes(memory_path)
        if not episodes:
            logger.info("No unprocessed episodes found — skipping")
            _state.progress = "No unprocessed episodes"
            _state.status = "idle"
            return

        logger.info(f"Found {len(episodes)} unprocessed episodes")
        _state.episodes_total = len(episodes)

        # Stage 1: Entity & Relationship Extraction
        _state.progress = f"Stage 1/5: Extracting entities from {len(episodes)} episodes..."
        logger.info(f"Stage 1: Extracting entities from {len(episodes)} episodes")
        from api.services.entity_extractor import extract
        extracted = await extract(episodes, settings)
        total_entities = sum(len(e.get("entities", [])) for e in extracted)
        total_rels = sum(len(e.get("relationships", [])) for e in extracted)
        logger.info(f"Stage 1 complete: {total_entities} entities, {total_rels} relationships extracted")
        _state.stage = 1

        # Resumable queue — hard stop if EVERY episode failed Stage 1 (wrong
        # model id, exhausted credits, total outage). Abort with the queue
        # untouched instead of running the rest of the pipeline on nothing and
        # committing a misleading empty "completed" cycle. Re-running after
        # fixing the cause retries the whole batch.
        if episodes and not extracted:
            msg = (
                "Stage 1 extracted nothing — all episodes failed "
                "(check model id / API credits). Queue left intact for retry."
            )
            logger.error(msg)
            _state.error = msg
            _state.progress = f"Failed: {msg}"
            return

        # Stage 2: Entity Resolution & Deduplication
        _state.progress = "Stage 2/5: Resolving entities..."
        logger.info("Stage 2: Resolving entities against existing graph")
        existing = _load_existing_entities(memory_path)
        from api.services.entity_resolver import resolve
        resolved_result = await resolve(extracted, existing, settings)
        resolved_changes = resolved_result["changes"]
        resolved_edges = resolved_result["relationships"]
        episode_cooccurrences = resolved_result.get("episode_cooccurrences", {})
        creates = sum(1 for r in resolved_changes if r.get("action") == "create")
        updates = sum(1 for r in resolved_changes if r.get("action") == "update")
        logger.info(f"Stage 2 complete: {creates} new entities, {updates} updates, {len(resolved_edges)} relationships")
        _state.entities_created = creates
        _state.entities_updated = updates
        _state.relationships_created = len(resolved_edges)
        _state.stage = 2

        # Stage 3: Conflict Resolution & Pruning
        _state.progress = "Stage 3/5: Resolving conflicts..."
        logger.info("Stage 3: Conflict resolution & temporal decay")
        from api.services.conflict_resolver import resolve_and_prune
        changes = await resolve_and_prune(resolved_changes, existing, settings)
        logger.info(f"Stage 3 complete: {len(changes)} total changes")
        _state.stage = 3

        # Stage 4: Pattern Detection & Skill Extraction
        _state.progress = "Stage 4/5: Extracting skills..."
        logger.info("Stage 4: Pattern detection & skill extraction")
        from api.services.skill_extractor import detect_patterns
        skills = await detect_patterns(
            changes,
            existing,
            settings,
            episode_cooccurrences=episode_cooccurrences,
        )
        logger.info(f"Stage 4 complete: {len(skills)} skills detected")
        _state.skills_detected = len(skills)
        _state.stage = 4

        # Stage 5: Nudge Generation & Versioning
        _state.progress = "Stage 5/5: Writing changes..."
        logger.info("Stage 5: Writing entities, nudges, clarifications, and relationships")
        from api.services.inbox_generator import generate
        await generate(changes, skills, memory_path, relationships=resolved_edges)

        # Stage 5.5: Materialize entity-body wikilinks as `mentions` edges so the
        # graph stops ignoring them. Runs after relationships are written so the
        # `mentions` wave merges into the same graph_edges.yaml. Idempotent.
        try:
            from api.services.wikilink_resolver import materialize_wikilink_edges
            n_mentions = materialize_wikilink_edges(memory_path)
            logger.info(f"Stage 5.5: materialized {n_mentions} wikilink `mentions` edges")
        except Exception as e:
            logger.warning(f"Stage 5.5 wikilink materialization failed: {type(e).__name__}: {e}")

        # Stage 5.55: Wire media entities to the entities resolved this cycle by
        # joining on shared source episodes. Bypasses the promotion gate — a
        # saved bookmark connects to existing entities even when the concepts
        # it mentions never cross the 2-conversation threshold.
        try:
            from api.services.media_ingestor import inject_media_edges
            n_media = inject_media_edges(memory_path, changes)
            logger.info(f"Stage 5.55: injected {n_media} media `about` edges")
        except Exception as e:
            logger.warning(f"Stage 5.55 media edge injection failed: {type(e).__name__}: {e}")

        # Stage 5.56 (M5f): CLAIM LAYER — load-bearing in the live cycle now.
        # Runs AFTER the entity path's Stage-5 page writes (so create-pages exist
        # to host the ```claims block) and 5.55 media edges, but BEFORE the hub /
        # edge-regen / index steps (so they project the freshly-written claims).
        # This is ADDITIVE: the legacy entity extraction + conflict_resolver path
        # above keeps working untouched; claims are emitted (Stage 1 projection),
        # trust-reconciled (Stage 3 — no agent claim can close a human claim), and
        # written into the same editable pages (Stage 5 — human prose preserved).
        try:
            from api.services.claim_pipeline import run_claim_pipeline
            from api.services.inbox_generator import write_claim_nudges
            claim_result = run_claim_pipeline(extracted, existing, memory_path, settings)
            n_nudges = write_claim_nudges(claim_result.get("nudges", []), memory_path)
            logger.info(
                f"Stage 5.56: claim layer wrote {claim_result.get('claims_written', 0)} "
                f"claims across {claim_result.get('subjects_written', 0)} pages "
                f"({claim_result.get('subjects_skipped', 0)} page-less), "
                f"{n_nudges} claim nudges"
            )
        except Exception as e:
            logger.warning(f"Stage 5.56 claim pipeline failed: {type(e).__name__}: {e}")

        # Stage 5.6: Regenerate the hub tier + root _index.md from current entities.
        # Deterministic, no LLM; gives small LLMs a filesystem traversal path.
        try:
            from api.services.hub_builder import regenerate_hubs_and_index
            hub_result = regenerate_hubs_and_index(memory_path, settings)
            logger.info(f"Stage 5.6: regenerated {hub_result['hub_count']} hubs + _index.md")
        except Exception as e:
            logger.warning(f"Stage 5.6 hub generation failed: {type(e).__name__}: {e}")

        # Stage 5.57 (M5f): link-enrichment subagent — when a saved media link
        # (e.g. a website Prof. John recommended) lacks a meaningful description,
        # a bounded subagent fetches + summarizes it and records a `describes`
        # claim + `recommends` claims, with bidirectional ![[…]] transclusion
        # (m5-prep/link-enrichment.md). Offline-safe, LLM-call-capped; any failure
        # logs a warning and continues — the cycle is never hard-blocked.
        try:
            from api.services.link_enrichment import default_summarize, enrich_media_links
            n_enriched = await enrich_media_links(
                memory_path, changes, settings, summarize_fn=default_summarize
            )
            if n_enriched:
                logger.info(f"Stage 5.57: enriched {n_enriched} media link(s)")
        except Exception as e:
            logger.warning(f"Stage 5.57 link enrichment failed: {type(e).__name__}: {e}")

        # Stage 5.7: Regenerate graph_edges.yaml as a valid-only projection of the
        # claims layer (tagged with observer/context/claim_id). No-op on banks
        # with no claims yet, so seeded/legacy edge graphs are not wiped (M5e).
        try:
            from api.services.graph_builder import regenerate_edges_from_claims
            n_edges = regenerate_edges_from_claims(memory_path)
            if n_edges:
                logger.info(f"Stage 5.7: regenerated {n_edges} valid-only claim edges")
        except Exception as e:
            logger.warning(f"Stage 5.7 claim-edge regeneration failed: {type(e).__name__}: {e}")

        # Mark ONLY the episodes that successfully extracted this cycle.
        # Episodes whose Stage-1 extraction errored (e.g. a credit cap hit
        # mid-run) are absent from `extracted` and stay `processed: false`, so
        # re-triggering Sleep resumes exactly where it left off instead of
        # re-spending the whole batch. (Empty-content episodes return a
        # zero-entity result, so they ARE here — done, nothing to retry.)
        extracted_ids = {r["episode_id"] for r in extracted if r.get("episode_id")}
        processed_episodes = [ep for ep in episodes if ep["id"] in extracted_ids]
        requeued = len(episodes) - len(processed_episodes)
        _mark_episodes_processed(processed_episodes)
        _state.episodes_processed = len(processed_episodes)
        _state.episodes_requeued = requeued
        if requeued:
            logger.warning(
                f"Marked {len(processed_episodes)} episodes processed; {requeued} "
                f"failed extraction and remain queued — re-run Sleep to continue"
            )
        else:
            logger.info(f"Marked {len(processed_episodes)} episodes as processed")

        # Rebuild LEANN indexes so Bookworm reflects the post-sleep state.
        # Entity and episode rebuilds are independent and we want to surface
        # partial failures: if only the episode index fails, the cycle still
        # wrote the markdown graph, committed, and should report success
        # *with a warning* — not a silent pass, not a hard failure.
        index_warnings: list[str] = []
        try:
            from api.services.vector_index import SqliteVecIndexer
            indexer = SqliteVecIndexer(memory_path)
        except Exception as e:
            indexer = None
            warning = f"vector indexer init failed: {type(e).__name__}: {e}"
            logger.warning(warning)
            index_warnings.append(warning)

        if indexer is not None:
            try:
                indexer.index_entities()
            except Exception as e:
                warning = f"entity index rebuild failed: {type(e).__name__}: {e}"
                logger.warning(f"vector {warning}")
                index_warnings.append(warning)
            try:
                indexer.index_episodes()
            except Exception as e:
                warning = f"episode index rebuild failed: {type(e).__name__}: {e}"
                logger.warning(f"vector {warning}")
                index_warnings.append(warning)
            # M5e: rebuild the derived claims index from the in-page ```claims
            # blocks so claim-first /ask + get_perspective reflect the post-Sleep
            # belief state. Only currently-valid claims are indexed.
            try:
                indexer.index_claims()
            except Exception as e:
                warning = f"claims index rebuild failed: {type(e).__name__}: {e}"
                logger.warning(f"vector {warning}")
                index_warnings.append(warning)

        if index_warnings:
            _state.index_warning = "; ".join(index_warnings)

        # Commit
        await _finalize(memory_path, cycle_id, changes, settings)
        requeue_note = (
            f" — {_state.episodes_requeued} episode(s) requeued (re-run to continue)"
            if _state.episodes_requeued else ""
        )
        if _state.index_warning:
            _state.progress = f"Completed with warnings: {_state.index_warning}{requeue_note}"
            logger.warning(
                f"Sleep cycle {cycle_id} completed with warnings — "
                f"{len(changes)} changes committed; {_state.index_warning}{requeue_note}"
            )
        else:
            _state.progress = f"Completed{requeue_note}"
            logger.success(
                f"Sleep cycle {cycle_id} completed — {len(changes)} changes committed"
                f"{requeue_note}"
            )
        _state.stage = 5

    except Exception as e:
        _state.progress = f"Failed: {e}"
        _state.error = f"{type(e).__name__}: {e}"
        logger.error(f"Sleep cycle failed: {e}")
        logger.exception("Full traceback:")
    finally:
        _state.status = "idle"


def _get_unprocessed_episodes(memory_path: Path) -> list[dict]:
    """Load all episodes with processed: false, sorted by frontmatter timestamp.

    Sorting by timestamp (not filename) keeps the queue the Sleep dashboard
    shows aligned with the chronology-aware entity writes in
    ``conflict_resolver.apply_changes``, which use earliest/latest source
    episode timestamps to set ``created`` and ``last_referenced``.
    """
    episodes_dir = memory_path / "episodes"
    results: list[dict] = []
    for filepath in episodes_dir.glob("*.md"):
        try:
            parsed = markdown_parser.parse(filepath)
        except Exception as exc:  # noqa: BLE001 - one malformed episode must not abort the cycle
            logger.warning(f"_get_unprocessed_episodes: skipping malformed episode {filepath}: {exc}")
            continue
        if not parsed.frontmatter.get("processed", False):
            source = parsed.frontmatter.get("source", "unknown")
            results.append({
                "id": parsed.frontmatter.get("id", filepath.stem),
                "content": parsed.body,
                "source": source,
                # G9 origin: explicit field if present, else derived from the
                # legacy `source` (origin-and-harness-sync.md §1b). Propagated into
                # extracted claims so each belief records which harness it came from.
                "origin": parsed.frontmatter.get("origin") or _derive_origin(source),
                "timestamp": str(parsed.frontmatter.get("timestamp", "") or ""),
                "filepath": filepath,
            })
    # Fall back on the id (which begins with the date) for episodes missing a
    # timestamp so the sort is stable regardless of filesystem order.
    results.sort(key=lambda r: (r.get("timestamp") or "", r["id"]))
    return results


# Legacy `source` -> G9 `origin` derivation (origin-and-harness-sync.md §1b).
_SOURCE_TO_ORIGIN = {
    "claude": "claude-code",
    "claude_memory": "claude-code",
    "claude_project": "claude-code",
    "mcp": "claude-code",
    "chatgpt-export": "chatgpt-export",
    "claude-export": "claude-export",
    "telegram": "telegram",
    "rss": "rss",
    "bookmark": "bookmark",
}


def _derive_origin(source: str | None) -> str:
    """Map a legacy episode ``source`` to a G9 ``origin`` harness id, else ``unknown``."""
    s = str(source or "").strip().lower()
    if not s:
        return "unknown"
    if s in _SOURCE_TO_ORIGIN:
        return _SOURCE_TO_ORIGIN[s]
    # Already an origin-shaped value (e.g. codex, cursor) passes through.
    return s


def list_all_episodes(memory_path: Path) -> list[dict]:
    """Return every episode (processed + unprocessed), sorted by timestamp.

    Used by ``GET /sleep/episodes`` so the Sleep dashboard can show both the
    queue and recently processed episodes in the same chronology that the
    sleep cycle consumes them in.
    """
    episodes_dir = memory_path / "episodes"
    results: list[dict] = []
    for filepath in episodes_dir.glob("*.md"):
        try:
            parsed = markdown_parser.parse(filepath)
        except Exception as exc:  # noqa: BLE001 - one malformed episode must not abort the cycle
            logger.warning(f"list_all_episodes: skipping malformed episode {filepath}: {exc}")
            continue
        fm = parsed.frontmatter
        results.append({
            "id": fm.get("id", filepath.stem),
            "timestamp": str(fm.get("timestamp", "") or ""),
            "source": fm.get("source", "unknown"),
            "title": fm.get("title"),
            "body": parsed.body or "",
            "processed": bool(fm.get("processed", False)),
            "filepath": filepath,
        })
    results.sort(key=lambda r: (r.get("timestamp") or "", r["id"]))
    return results


def _load_existing_entities(memory_path: Path) -> list[dict]:
    """Load all existing entity data."""
    entities_dir = memory_path / "entities"
    results: list[dict] = []
    for filepath in sorted(entities_dir.glob("*.md")):
        try:
            parsed = markdown_parser.parse(filepath)
        except Exception as exc:  # noqa: BLE001 - one malformed entity must not abort the cycle
            logger.warning(f"_load_existing_entities: skipping malformed entity {filepath}: {exc}")
            continue
        results.append({
            "id": filepath.stem,
            "frontmatter": parsed.frontmatter,
            "body": parsed.body,
            "filepath": filepath,
        })
    return results


def _mark_episodes_processed(episodes: list[dict]) -> None:
    """Mark episodes as processed in their frontmatter."""
    for ep in episodes:
        filepath = ep["filepath"]
        try:
            parsed = markdown_parser.parse(filepath)
        except Exception as exc:  # noqa: BLE001 - one malformed episode must not abort the cycle
            logger.warning(f"_mark_episodes_processed: skipping malformed episode {filepath}: {exc}")
            continue
        parsed.frontmatter["processed"] = True
        markdown_parser.write(filepath, parsed.frontmatter, parsed.body)


async def _finalize(
    memory_path: Path, cycle_id: str, changes: list, settings: Settings | None = None
) -> None:
    """Commit all changes from the sleep cycle with a structured message.

    Entity-level lines from ``changes`` have source + trigger; file-level
    additions (nudges, clarifications, graph_edges, etc.) are inferred from
    ``git status`` so the commit message remains a complete manifest. The
    authoring model(s) for this cycle (main + disambiguation, per ``settings``)
    are recorded as ``Cicada-Author:`` trailers for repo-wide attribution.
    """
    date_str = datetime.now().strftime("%Y-%m-%d")

    # --- Entity lines from structured change data ---
    entity_lines: list[str] = []
    entity_files_covered: set[str] = set()
    for change in changes:
        if not isinstance(change, dict):
            continue
        entity_id = change.get("id", "unknown")
        action = change.get("action", "updated")
        source = change.get("source_episode", "") or "n/a"
        trigger = change.get("trigger", "sleep/extraction")
        path = f"entities/{entity_id}.md"
        entity_files_covered.add(path)
        entity_lines.append(
            f"{path}: {action} (source: {source}, trigger: {trigger})"
        )

    # --- File lines for anything else touched in the working tree ---
    extra_lines: list[str] = []
    # Stage so porcelain reports paths beneath the memory repo's index filter.
    status = await git_service.porcelain_status(memory_path)

    for raw in status.splitlines():
        if not raw.strip():
            continue
        # porcelain format: XY <path>, possibly "XY orig -> new"
        parts = raw[3:].split(" -> ")
        path = parts[-1].strip()
        if path in entity_files_covered:
            continue
        status_code = raw[:2].strip()
        action = _porcelain_action(status_code)
        trigger = _infer_trigger_for_path(path)
        extra_lines.append(f"{path}: {action} (trigger: {trigger})")

    body_lines = entity_lines + extra_lines

    # Author trailers: the models that actually wrote this consolidation. The
    # disambiguation model (Stage 2 judge) is recorded too when distinct.
    authors: list[str] = []
    if settings is not None:
        if settings.litellm_model:
            authors.append(settings.litellm_model)
        disambig = (settings.litellm_disambiguation_model or "").strip()
        if disambig and disambig not in authors:
            authors.append(disambig)

    message = git_service.build_commit_message(
        f"Sleep cycle {date_str}", body_lines, authors=authors
    )
    async with _lock:
        await git_service.commit_changes(memory_path, message)


def _porcelain_action(status_code: str) -> str:
    """Map a git porcelain status code to a human-readable action."""
    if "A" in status_code or status_code == "??":
        return "created"
    if "D" in status_code:
        return "deleted"
    if "R" in status_code:
        return "renamed"
    return "updated"


def _infer_trigger_for_path(path: str) -> str:
    """Infer a trigger type for a non-entity file based on its directory."""
    if path.startswith("inbox/"):
        return "sleep/inbox_generation"
    if path.startswith("nudges/"):
        return "sleep/nudge_generation"
    if path.startswith("clarifications/"):
        return "sleep/extraction"
    if path.startswith("episodes/"):
        return "sleep/extraction"
    if path.startswith("leann/"):
        return "sleep/index_rebuild"
    if path.startswith("hubs/") or path == "_index.md":
        return "sleep/hub_generation"
    if path == "graph_edges.yaml":
        return "sleep/extraction"
    return "sleep/extraction"
