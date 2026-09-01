import asyncio
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from loguru import logger

from api.config import Settings
from api.services import bank_index, git_service, markdown_parser


@dataclass
class SleepState:
    status: str = "idle"
    cycle_id: str | None = None
    started_at: str | None = None
    # Monotonic start time for this cycle, used to compute the ``sleep_run``
    # telemetry event's ``duration_ms`` without being affected by wall-clock
    # adjustments (NTP, DST). Distinct from ``started_at``, which is the
    # human-readable timestamp shown in the Sleep dashboard.
    started_monotonic: float | None = None
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
    # G60 — open-question re-scoring (Stage 5.56). ``questions_refreshed`` counts
    # items whose options were bumped or escalated; ``organic_resolutions`` counts
    # questions answered by later conversation and closed without the user acting.
    questions_refreshed: int = 0
    organic_resolutions: int = 0
    # G74(a) — which engine this cycle actually ran on ("claude-cli" |
    # "ollama" | "litellm"), and one sentence about its state. The Sleep page
    # showed "check model id / API credits" on a Max plan that has no credits
    # to check; these two make the real answer visible.
    last_engine: str | None = None
    engine_detail: str | None = None
    # Fix round 1, M3: internal-only (never exposed via SleepStatusResponse) —
    # did this cycle reach Stage 5's first real disk write (entity/inbox
    # pages)? Idle cycles, a pre-flight probe abort, and a Stage-1-total-
    # failure abort never write anything, so the tail's connector poll must
    # stay unconditional for them exactly as it always was — only a cycle
    # that started writing and then never reached `_finalize`'s commit is a
    # genuine risk the `_tree_is_clean` check needs to guard.
    write_started: bool = False


_state = SleepState()
_lock = asyncio.Lock()


def get_sleep_state() -> SleepState:
    return _state


async def _warm_logos_safely(memory_path: Path) -> None:
    """G59: warm the logo cache for the busiest company/tool pages so the
    common marks are on disk before the user opens the graph. Bounded,
    keyless, and never fatal — a CDN outage (or a cycle with zero new
    episodes) must not fail a cycle. Called both on the zero-unprocessed-
    episodes early return and at the tail of a full run, so logos still warm
    on an otherwise-empty cycle.
    """
    try:
        from api.services.logo_service import warm_logos

        warmed = await warm_logos(memory_path, limit=50)
        if warmed:
            logger.info(f"Warmed {warmed} entity logo(s)")
    except Exception as e:
        logger.warning(f"Logo warm-up failed: {type(e).__name__}: {e}")


async def _poll_connectors_safely(memory_path: Path) -> None:
    """G71 §2 (+ Task 14): pull new Pinterest pins, Reddit saves, and X
    bookmarks on the nightly cycle.

    Same contract as ``_warm_logos_safely``: bounded, credential-gated,
    never fatal — an expired token or a rate limit must not fail a Sleep
    cycle. This IS the "unattended background call" ``CICADA_ALLOW_CONNECTOR_FETCH``
    exists to gate (opt-OUT, on by default — final-review H2); a poll the gate
    skips is recorded through ``sync_state.record_skip``, distinctly from a
    real failure (``sync_state.record_error``), and surfaces on the Capture
    page either way.

    Called from ``_run_engine_independent_tail`` (``run``'s ``finally``, on
    EVERY exit path) — final-review H1: specifically AFTER ``_finalize`` has
    already committed the cycle's own entity/inbox writes, so a connector
    that ingests reaches ``media_ingestor.ingest_batch`` -> ``_commit_media``
    -> a ``git add -A`` commit that finds a CLEAN tree and sweeps only the
    files it just wrote, instead of also absorbing the Sleep cycle's
    still-uncommitted work into a commit with no session provenance.

    Runs UNCONDITIONALLY on every path that never wrote anything to disk —
    idle, a pre-flight probe abort, a total Stage-1 failure, or an exception
    in Stages 1-4 — exactly as the old idle-only early return always did, so
    anything pulled tonight is consolidated by tomorrow's cycle regardless
    (the same "it joins the graph after the next Sleep cycle" contract every
    other capture path already states). The caller only withholds this call
    (via ``_tree_is_clean``) for the one genuine risk window: Stage 5 started
    writing entity/inbox pages and the cycle never reached ``_finalize``'s
    commit (fix round 1, M3 — this must NOT be the default gate, or a
    completely unrelated dirty file in the bank, e.g. a direct Obsidian
    edit, silently stops connectors from polling on every idle night).
    """
    try:
        from api.services.connectors import ADAPTERS
    except Exception as e:
        logger.warning(f"connector poll unavailable: {type(e).__name__}: {e}")
        return

    for adapter in ADAPTERS.values():
        try:
            result = await adapter.sync(memory_path)
            if result.get("status") == "ok" and result.get("new"):
                logger.info(f"{adapter.LABEL}: pulled {result['new']} new saved item(s)")
        except Exception as e:
            logger.warning(
                f"{adapter.LABEL} poll failed: {type(e).__name__}: {e}"
            )


async def _refresh_questions_safely(memory_path: Path, settings: Settings) -> None:
    """G60 §2.3 on an IDLE cycle: keep open questions honest during quiet weeks.

    Staleness is measured in wall-clock days, not in episodes — a question every
    option of which has gone silent for ``inbox_stale_after_days`` must gain its
    "Neither anymore" escalation whether or not anything new was captured. The
    full cycle runs this inside Stage 5.56 (against the claims it just wrote);
    this is the zero-episode twin, hooked exactly like ``_warm_logos_safely``.

    Deterministic (no LLM), so the resulting inbox writes are committed here as
    system maintenance — author ``cicada`` — rather than left dirty for the next
    real cycle to sweep in under a model's name. Never fatal.
    """
    try:
        from api.services import inbox_questions
        from api.services.claim_pipeline import _load_existing_claims_by_subject

        today = str(datetime.now().date())
        refresh = inbox_questions.refresh_open_questions(
            memory_path,
            _load_existing_claims_by_subject(memory_path),
            today,
            stale_after_days=settings.inbox_stale_after_days,
        )
        _state.questions_refreshed = refresh["bumped"] + refresh["escalated"]
        _state.organic_resolutions = refresh["organic_resolutions"]
        touched = refresh["bumped"] + refresh["escalated"] + refresh["organic_resolutions"]
        if not touched:
            return
        logger.info(
            f"Idle cycle: refreshed {refresh['bumped']} question(s), "
            f"escalated {refresh['escalated']}, "
            f"organically resolved {refresh['organic_resolutions']}"
        )
        resolved = set(refresh.get("resolved_paths") or [])
        rewritten = set(refresh.get("rewritten_paths") or [])
        # Scoped to EXACTLY the files this sweep touched — never the whole
        # `inbox` directory, which would sweep an unrelated dirty file under
        # `inbox/` into this `cicada`-authored commit (mirrors the H2 pattern
        # in `decay_migration._commit_backfill`).
        touched_paths = sorted(resolved | rewritten)
        lines = [f"{p}: resolved (trigger: inbox/organic_resolution)" for p in sorted(resolved)]
        lines += [
            f"{p}: refreshed (trigger: inbox/stale_refresh)"
            for p in sorted(rewritten - resolved)
        ]
        if not lines:
            return
        message = git_service.build_commit_message(
            f"Inbox question refresh {today}", lines, authors=["cicada"]
        )
        try:
            await git_service.commit_paths(memory_path, message, touched_paths)
        except Exception as exc:  # pragma: no cover - non-git workspace
            logger.warning(f"Idle question-refresh commit skipped: {exc}")
    except Exception as e:
        logger.warning(f"Idle question refresh failed: {type(e).__name__}: {e}")


@dataclass
class _StageOutcome:
    """What the LLM-dependent pipeline achieved, for the tail to react to.

    ``committed``: ``_finalize`` ran, so the working tree is clean and the
    connector poll's own ``git add -A`` can safely sweep only its own files.
    ``questions_refreshed``: Stage 5.56 already re-scored the open questions,
    so the tail must not do it a second time.
    """
    committed: bool = False
    questions_refreshed: bool = False


_ENGINE_LABELS = {"agent": "claude-cli", "local": "ollama", "byok": "litellm"}


def _engine_label(settings: Settings) -> str:
    """Which engine a resolved mode means. (Task 7 routes "auto" here too.)

    ``getattr`` rather than a direct attribute read: several hermetic Sleep
    tests pass a ``SimpleNamespace`` stand-in for ``Settings`` that predates
    ``llm_mode`` and never sets it — those must still resolve to the
    "byok"/"litellm" default rather than raising ``AttributeError`` before
    Stage 1 even starts.
    """
    mode = (getattr(settings, "llm_mode", None) or "byok").strip().lower()
    return _ENGINE_LABELS.get(mode, "litellm")


def _stage1_failure_message(engine: str) -> str:
    """The user-visible reason Stage 1 produced nothing — per engine.

    L3 (Task 4 review, handed to Task 5): Stage 1 swallows ``EngineThrottled``
    per-episode so the circuit breaker can fail every remaining call fast
    without spawning — which means the only throttle signal left at THIS
    boundary is ``agent_engine.breaker_reason()``, not the ``engine`` string.
    Keyed on the breaker FIRST: a total failure caused by a throttle gets the
    spec's exact sentence ("Claude plan throttled — stopped cleanly, N
    episodes left queued") instead of the generic per-engine message below,
    which would be true but would bury the one fact that matters — retry
    later, don't reconfigure anything.

    The old single string ("check model id / API credits") is a lie on a Max
    plan: a subscription has no credits to check, and the real fixes are
    completely different per rung.
    """
    from api.services import agent_engine

    breaker = agent_engine.breaker_reason()
    if breaker:
        n = _state.episodes_total
        return (
            f"Claude plan throttled — stopped cleanly, {n} episode(s) left queued. "
            f"({breaker})"
        )
    if engine == "claude-cli":
        return (
            "Stage 1 extracted nothing — every episode failed on the Claude Code engine. "
            "Run `claude auth status` to check the plan is signed in. "
            "The queue is intact; trigger Sleep again once it is."
        )
    if engine == "ollama":
        return (
            "Stage 1 extracted nothing — every episode failed on the local Ollama engine. "
            "Check the Ollama server is running and the model is pulled. "
            "The queue is intact for retry."
        )
    return (
        "Stage 1 extracted nothing — every episode failed on the API engine "
        "(check the model id, and that the key still has credit). "
        "Queue left intact for retry."
    )


async def _probe_engine_cheaply(settings: Settings) -> tuple[bool, str]:
    """Fix round 1, M1: is claude-plan usable, resolved from config/registry
    state FIRST — never a subprocess spawn "just to check availability".

    Ruling 2 was violated by the original implementation, which always
    called ``agent_engine.probe()`` (``claude auth status --json``) with a
    20 s timeout on every agent-mode cycle with a non-empty queue. Fixed by
    consulting ``connections.registry``'s already-cached ``claude-plan``
    status first: ``Registry.cached_statuses()`` NEVER probes — it is a pure
    in-memory read (plus one cheap prefs-file read) of whatever
    ``GET /connections``/``GET /status`` last warmed, on a 30 s TTL. Since
    the companion app polls both routes while open, the common case (the
    user has the app running when Sleep triggers) now costs a Sleep cycle
    nothing at all to pre-flight.

    A spawn is still genuinely unavoidable when the cache is cold — nothing
    has probed Connections/Status recently in this process (a fresh backend
    boot, or a headless/API-only trigger with the app never opened) — the
    registry has no way to answer without one. That case falls back to
    ``agent_engine.probe()`` directly, timeout dropped from 20 s to 5 s since
    it is now a rare fallback rather than the primary path, not the shared,
    cache-populating ``Registry.status()`` (whose own spawn is fixed at a
    15 s default with no way to shorten it from here).
    """
    from api.services import agent_engine
    from api.services.connections import registry as connections_registry

    reg = connections_registry.get_registry(settings)
    for status in reg.cached_statuses():
        if status.id != "claude-plan":
            continue
        if status.connected:
            return True, status.how or "Claude Code signed in on this Mac."
        return False, status.detail or "Claude Code is not connected."
    return await asyncio.to_thread(agent_engine.probe, timeout=5.0)


async def _tree_is_clean(memory_path: Path) -> bool:
    try:
        return not (await git_service.porcelain_status(memory_path)).strip()
    except Exception:  # not a git workspace: there is nothing to protect
        return True


async def _run_engine_independent_tail(
    memory_path: Path, settings: Settings, outcome: _StageOutcome
) -> None:
    """The work that never needed an LLM — on EVERY exit path.

    Spec §1: the abort was upside-down. With a non-empty queue and no engine,
    the Stage-1 abort ``return``ed before the logo warm-up and the connector
    poll, and the question refresh only ever ran in the zero-episode idle
    branch — so capturing more episodes made Sleep do strictly LESS work.

    Fix round 1, M3: the connector poll must stay UNCONDITIONAL for every
    path that never wrote anything — idle, a pre-flight probe abort, a
    total Stage-1 failure, or an exception raised in Stages 1-4 (all
    in-memory, nothing on disk yet) — exactly like the old idle branch did.
    ``_tree_is_clean`` is only consulted once ``_state.write_started`` is
    true and the cycle never committed: THAT is the one genuine risk H1
    exists for (Stage 5 wrote entity/inbox pages, then something failed
    before ``_finalize``). Gating every non-committed path on a clean tree
    — the bug this fixes — silently stopped the idle-cycle poll behind a
    false "the cycle left uncommitted writes" log line on a real bank with
    ANY unrelated dirty file (a direct Obsidian edit, a workflow this repo
    explicitly supports).
    """
    if outcome.committed or not _state.write_started or await _tree_is_clean(memory_path):
        # Final-review H1 is preserved: on the happy path this still runs
        # AFTER ``_finalize``'s commit, so the connectors' ``git add -A``
        # finds a clean tree. On a cycle that started writing and never
        # committed, we only poll when the tree is already clean anyway, so
        # a partial Sleep write can never be swept into a media commit with
        # no session provenance.
        await _poll_connectors_safely(memory_path)
    else:
        logger.warning(
            "connector poll skipped: this cycle wrote entity/inbox changes but "
            "never committed them, and the connectors' own `git add -A` would "
            "absorb those uncommitted writes into a media commit"
        )
    await _warm_logos_safely(memory_path)
    if not outcome.questions_refreshed:
        # Staleness is a function of TIME, not of episodes: a cycle that never
        # reached Stage 5.56 must still escalate questions everyone stopped
        # talking about (and clear ones answered organically).
        await _refresh_questions_safely(memory_path, settings)


async def run(settings: Settings, cycle_id: str) -> None:
    """Execute the 5-stage Sleep cycle pipeline."""
    global _state

    _state.status = "running"
    _state.cycle_id = cycle_id
    _state.started_at = datetime.now().isoformat()
    _state.started_monotonic = time.monotonic()
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
    _state.questions_refreshed = 0
    _state.organic_resolutions = 0
    _state.last_engine = None
    _state.engine_detail = None
    _state.write_started = False

    memory_path = settings.memory_path

    # G74(a) — the throttle breaker and the models-used ledger are
    # process-global (L4, Task 4 review, handed to Task 5). A breaker left
    # tripped by last night's cycle would make this one fail fast for free,
    # for a throttle that has long since cleared.
    from api.services import agent_engine
    agent_engine.reset_breaker()
    agent_engine.reset_models_used()

    outcome = _StageOutcome()
    try:
        outcome = await _run_stages(settings, cycle_id, memory_path)
    except Exception as e:
        _state.progress = f"Failed: {e}"
        _state.error = f"{type(e).__name__}: {e}"
        logger.error(f"Sleep cycle failed: {e}")
        logger.exception("Full traceback:")
    finally:
        # Spec §1: this runs on EVERY exit path — idle, aborted before Stage
        # 1, aborted after Stage 1, raised, or fully completed — so capturing
        # more episodes can never make Sleep do less of the LLM-free work.
        #
        # Fix round 1, L2: `_state.status = "idle"` gets its OWN `finally`
        # rather than sitting after the tail's awaits. The tail's three
        # helpers each swallow their own exceptions, but if the tail itself
        # ever raised (today only a `CancelledError` could reach here), the
        # old ordering would strand `status` at "running" forever — both
        # `POST /sleep/trigger` and the scheduler refuse to start a new cycle
        # while `status == "running"`, so every later cycle would be silently
        # refused with no way to recover short of restarting the process.
        try:
            await _run_engine_independent_tail(memory_path, settings, outcome)
        finally:
            _state.status = "idle"


async def _run_stages(settings: Settings, cycle_id: str, memory_path: Path) -> _StageOutcome:
    """The LLM-dependent pipeline. Returns what it achieved; never runs the tail."""
    _state.last_engine = _engine_label(settings)
    logger.info(
        f"Sleep cycle {cycle_id} started — engine: {_state.last_engine}, "
        f"model: {settings.litellm_model}"
    )

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
        return _StageOutcome()

    logger.info(f"Found {len(episodes)} unprocessed episodes")
    _state.episodes_total = len(episodes)

    # G74(a) pre-flight: ask the engine whether it can work BEFORE spending a
    # spawn per episode discovering it cannot. Only on a cycle with real work,
    # so an idle bank never shells out, and ollama/litellm cycles never touch
    # the CLI at all. Fix round 1, M1: resolved from the connections
    # registry's cache first (`_probe_engine_cheaply`) — genuinely no
    # subprocess in the common case — with a short-timeout spawn only as a
    # cold-cache fallback.
    if _state.last_engine == "claude-cli":
        ok, detail = await _probe_engine_cheaply(settings)
        _state.engine_detail = detail
        if not ok:
            logger.error(f"Sleep cycle {cycle_id} aborted before Stage 1 — {detail}")
            _state.error = detail
            _state.progress = f"Failed: {detail}"
            return _StageOutcome()

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
        msg = _stage1_failure_message(_state.last_engine or "litellm")
        if _state.engine_detail:
            msg = f"{msg} ({_state.engine_detail})"
        logger.error(msg)
        _state.error = msg
        _state.progress = f"Failed: {msg}"
        return _StageOutcome()

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
    # Fix round 1, M3: the FIRST real disk write in the pipeline — everything
    # before this point (Stages 1-4) only computed `changes` in memory. Flip
    # this before the write so a raised exception anywhere from here through
    # `_finalize`'s commit correctly marks the tree as an at-risk one for the
    # tail's connector-poll gate, even though the exception means `_run_stages`
    # never reaches a `return` to report it via `_StageOutcome`.
    _state.write_started = True
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
    # `organic_resolution_paths` is threaded to `_finalize` (below) so those
    # exact deletions get the specific `inbox/organic_resolution` trigger.
    organic_resolution_paths: set[str] = set()
    questions_refreshed = False
    try:
        from api.services.claim_pipeline import run_claim_pipeline
        from api.services.inbox_generator import write_claim_nudges
        claim_result = run_claim_pipeline(extracted, existing, memory_path, settings)
        nudge_result = write_claim_nudges(claim_result.get("nudges", []), memory_path)

        # G60 §2.3 — re-score the OPEN questions against the freshly-written
        # claims (bump/re-order, organic resolution, stale escalation). Runs
        # AFTER write_claim_nudges so this cycle's new competing values are
        # already merged into their open question.
        from api.services import inbox_questions
        from api.services.claim_pipeline import _load_existing_claims_by_subject

        refresh = inbox_questions.refresh_open_questions(
            memory_path,
            _load_existing_claims_by_subject(memory_path),
            str(datetime.now().date()),
            stale_after_days=settings.inbox_stale_after_days,
        )
        _state.questions_refreshed = refresh["bumped"] + refresh["escalated"]
        _state.organic_resolutions = refresh["organic_resolutions"]
        organic_resolution_paths = set(refresh.get("resolved_paths") or [])
        questions_refreshed = True
        logger.info(
            f"Stage 5.56: refreshed {refresh['bumped']} question(s), "
            f"escalated {refresh['escalated']}, "
            f"organically resolved {refresh['organic_resolutions']}"
        )
        logger.info(
            f"Stage 5.56: claim layer wrote {claim_result.get('claims_written', 0)} "
            f"claims across {claim_result.get('subjects_written', 0)} pages "
            f"({claim_result.get('subjects_skipped', 0)} page-less), "
            f"{nudge_result.get('written', 0)} claim nudges written, "
            f"{nudge_result.get('merged', 0)} merged into open items"
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
    await _finalize(
        memory_path,
        cycle_id,
        changes,
        settings,
        organic_resolution_paths=organic_resolution_paths,
        started=_state.started_monotonic,
        sessions=_collect_session_ids(processed_episodes),
        episode_sessions=_episode_session_map(processed_episodes),
    )

    # Logo warm-up and the connector poll (final-review H1: the poll must
    # run AFTER `_finalize`'s commit so its own `git add -A` finds a clean
    # tree instead of sweeping the cycle's own uncommitted entity writes
    # into a session-less media commit) now live in the engine-independent
    # tail (`_run_engine_independent_tail`), which `run` executes in its
    # `finally` block on every exit path — not just this happy one.

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
    return _StageOutcome(committed=True, questions_refreshed=questions_refreshed)


def _get_unprocessed_episodes(memory_path: Path) -> list[dict]:
    """Load all episodes with processed: false, sorted by frontmatter timestamp.

    Sorting by timestamp (not filename) keeps the queue the Sleep dashboard
    shows aligned with the chronology-aware entity writes in
    ``conflict_resolver.apply_changes``, which use earliest/latest source
    episode timestamps to set ``created`` and ``last_referenced``.
    """
    results: list[dict] = []
    for f in bank_index.files(memory_path, "episodes"):
        fm = f.frontmatter
        if fm.get("processed", False):
            continue
        source = fm.get("source", "unknown")
        results.append({
            "id": fm.get("id", f.stem),
            "content": f.body(),
            "source": source,
            # G9 origin: explicit field if present, else derived from the
            # legacy `source` (origin-and-harness-sync.md §1b). Propagated into
            # extracted claims so each belief records which harness it came from.
            "origin": fm.get("origin") or _derive_origin(source),
            "timestamp": str(fm.get("timestamp", "") or ""),
            "filepath": f.path,
            # G48: which conversation produced this episode. `session_id` is
            # stamped by the MCP seam at capture; `source_id` is G20's
            # per-thread export id. `_finalize` turns the distinct set into
            # `Cicada-Session:` trailers.
            "session_id": str(fm.get("session_id") or "") or None,
            "source_id": str(fm.get("source_id") or "") or None,
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


def _collect_session_ids(episodes: list[dict]) -> list[str]:
    """Distinct conversation ids for the episodes consolidated this cycle.

    ``session_id`` (MCP capture, G48) wins over ``source_id`` (G20 export
    thread id); an episode with neither contributes nothing. Sorted so the
    commit message is deterministic, and capped at
    ``git_service.MAX_SESSION_TRAILERS`` so one enormous cycle can't grow the
    message without bound.
    """
    seen: set[str] = set()
    for ep in episodes:
        sid = str(ep.get("session_id") or ep.get("source_id") or "").strip()
        if sid:
            seen.add(sid)
    ids = sorted(seen)
    if len(ids) > git_service.MAX_SESSION_TRAILERS:
        logger.warning(
            f"{len(ids)} conversations in one cycle — recording the first "
            f"{git_service.MAX_SESSION_TRAILERS} as Cicada-Session trailers; "
            "GET /conversations/recent stays complete"
        )
        ids = ids[: git_service.MAX_SESSION_TRAILERS]
    return ids


def _episode_session_map(episodes: list[dict]) -> dict[str, str]:
    """episode id -> its conversation id (``session_id`` wins over
    ``source_id``, same precedence as :func:`_collect_session_ids`).

    PR #20 review fix: the commit-level ``Cicada-Session:`` trailers
    (``_collect_session_ids``) are a flat, cycle-wide set — correct for the
    commit as a whole, but wrong as a per-ENTITY answer when one Sleep run
    batches multiple conversations (every changed entity would otherwise
    claim every conversation). This map lets ``_finalize`` stamp each
    entity's OWN manifest line with only the session(s) of the episode(s)
    that actually touched it.
    """
    mapping: dict[str, str] = {}
    for ep in episodes:
        sid = str(ep.get("session_id") or ep.get("source_id") or "").strip()
        ep_id = str(ep.get("id") or "").strip()
        if sid and ep_id:
            mapping[ep_id] = sid
    return mapping


async def _finalize(
    memory_path: Path,
    cycle_id: str,
    changes: list,
    settings: Settings | None = None,
    *,
    organic_resolution_paths: set[str] | None = None,
    started: float | None = None,
    engine: str = "litellm",
    sessions: list[str] | None = None,
    episode_sessions: dict[str, str] | None = None,
) -> None:
    """Commit all changes from the sleep cycle with a structured message.

    Entity-level lines from ``changes`` have source + trigger; file-level
    additions (nudges, clarifications, graph_edges, etc.) are inferred from
    ``git status`` so the commit message remains a complete manifest. The
    authoring model(s) for this cycle (main + disambiguation, per ``settings``)
    are recorded as ``Cicada-Author:`` trailers for repo-wide attribution.

    ``episode_sessions`` (PR #20 review fix, ``_episode_session_map``): when
    given, each entity manifest line also carries a precise
    ``, sessions: <id>[,<id>...]`` clause derived from THAT entity's own
    ``source_episodes`` — never the whole cycle's session set. Only entities
    whose change carries an episode with a resolvable session gain the
    clause; a decay/archive/conflict change with no episode gets none, and
    ``git_service.get_entity_history`` reports NO sessions (an empty list)
    for those — it never falls back to the commit-level ``Cicada-Session:``
    trailers, which would overclaim every conversation in the batch as that
    entity's own (PR #20 round-2 review fix).

    ``organic_resolution_paths`` (G60 fix round 1): the exact inbox file paths
    ``refresh_open_questions`` deleted this cycle because a later conversation
    answered the question organically. Those paths get the specific
    ``inbox/organic_resolution`` trigger instead of the generic
    ``sleep/inbox_generation`` every other ``inbox/`` write is tagged with.

    ``sessions`` (G48): the distinct conversation ids whose episodes this cycle
    consolidated, recorded as ``Cicada-Session:`` commit-level trailers — this
    IS every conversation the whole cycle touched, and stays as-is (it is
    commit provenance, not entity provenance). User-action commits
    (inbox_service, entities router) stay session-less by design — they are
    ``Cicada-Author: user`` writes with no conversation behind them.
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
        line = f"{path}: {action} (source: {source}, trigger: {trigger}"
        if episode_sessions:
            # entity_resolver accumulates EVERY episode that touched this
            # entity in `source_episodes` (plural); `source_episode`
            # (singular) is only the last one merged. Use the full list so a
            # multi-episode update credits every one of ITS OWN episodes.
            source_eps = change.get("source_episodes") or (
                [change["source_episode"]] if change.get("source_episode") else []
            )
            entity_sessions = sorted({
                episode_sessions[ep] for ep in source_eps if episode_sessions.get(ep)
            })
            if entity_sessions:
                line += f", sessions: {','.join(entity_sessions)}"
        entity_lines.append(line + ")")

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
        if organic_resolution_paths and path in organic_resolution_paths:
            trigger = "inbox/organic_resolution"
        else:
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
        f"Sleep cycle {date_str}", body_lines, authors=authors, sessions=sessions or []
    )
    async with _lock:
        commit = await git_service.commit_changes(memory_path, message)

    from api.services import telemetry

    duration_ms = int((time.monotonic() - started) * 1000) if started is not None else None
    model = authors[0] if authors else None
    connection, billing = telemetry.connection_for_model(model) if model else (None, "free")
    telemetry.record(telemetry.UsageEvent(
        kind="sleep_run", stage="structural", engine=engine,
        connection=connection,
        model=model,
        bank=telemetry.bank_name(settings) if settings is not None else memory_path.name,
        billing=billing,
        invocations=0, duration_ms=duration_ms, ok=True,
        refs={
            "cycle_id": cycle_id,
            "commit": commit,
            "episodes_processed": _state.episodes_processed,
            "episodes_requeued": _state.episodes_requeued,
            "entities_created": _state.entities_created,
            "entities_updated": _state.entities_updated,
            "skills_detected": _state.skills_detected,
            "session_count": len(sessions or []),
        },
    ))


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
