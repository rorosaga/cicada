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
    # Sleep control (cancel + episode cap). ``cancel_requested`` is the INPUT
    # flag ``request_cancel()`` sets and every safe-point check in
    # `_run_stages` reads; ``cancelled`` is the OUTPUT flag set true only
    # when a cycle actually stopped early because of it (never when a cancel
    # arrived too late — after Stage 5 started writing — in which case the
    # cycle finishes and commits normally; see ``_cycle_cancelled`` and the
    # end-of-cycle handling in `_run_stages`). Both reset at the top of
    # every `run()`, exactly like every other per-cycle counter here.
    cancel_requested: bool = False
    cancelled: bool = False
    # Settings-driven episode cap for this cycle (`Settings.
    # sleep_max_episodes_per_cycle`) and the FULL unprocessed count found
    # before capping — see `SleepStatusResponse` for the field contract.
    episode_cap: int = 0
    episodes_queued: int = 0


_state = SleepState()
_lock = asyncio.Lock()

# Default episode cap when `settings` doesn't carry
# `sleep_max_episodes_per_cycle` (e.g. a `SimpleNamespace` stand-in in an
# older test). Mirrors `Settings.sleep_max_episodes_per_cycle`'s own default
# and rationale — see api/config.py.
DEFAULT_EPISODE_CAP = 25


def get_sleep_state() -> SleepState:
    return _state


def request_cancel() -> tuple[bool, str | None]:
    """Cooperative-cancel whatever cycle is currently running, if any.

    Idempotent: calling this while a cancel is already pending, or while
    nothing is running, is always safe and returns the same shape — it never
    raises and never wedges ``_state.status``. The flag is only ever read at
    the SAFE POINTS `_run_stages` checks (between stages, plus the internal
    checks inside Stage 1's fan-out and Stage 2's per-name judging loop) —
    never mid-write, mid-commit, or between a file write and its commit — so
    a requested cancel takes effect either "nothing has been written to disk
    yet" (the common case: abort clean, queue untouched) or, once Stage 5 has
    started writing, not at all for THIS cycle — it finishes its own commit
    first, exactly like an uninterrupted run, so the bank is never left dirty.

    Returns ``(was_running, cycle_id)``. ``was_running`` is False when there
    was nothing to cancel — mirrors ``/sleep/trigger``'s own "already_running"
    200-body convention (no 404/409) rather than treating "nothing running"
    as an error.
    """
    if _state.status != "running":
        return False, None
    _state.cancel_requested = True
    return True, _state.cycle_id


def _cancel_requested() -> bool:
    """Cooperative-cancel predicate threaded into `entity_extractor.extract`
    and `entity_resolver.resolve` as `cancel_check` — kept as a bare module
    function (not a bound method / closure over `_state`) so those modules
    never need to import `sleep_cycle` back."""
    return _state.cancel_requested


def _cycle_cancelled() -> "_StageOutcome":
    """The cancel abort point: reached with `_state.write_started` still
    False (a stage boundary in Stages 1-4, or an early exit from Stage 1's
    fan-out / Stage 2's per-name loop) — so NOTHING has been written to disk
    this cycle. Nothing to commit, nothing to clean up: the queue is
    untouched (no episode is marked processed until Stage 5), so this costs
    the user only the time already spent on the in-memory Stage 1-4 work
    discarded here. The next trigger resumes the exact same queue.
    """
    _state.cancelled = True
    _state.cancel_requested = False
    _state.progress = (
        f"Cancelled — stopped cleanly before any writes; "
        f"{_state.episodes_queued} episode(s) remain queued for the next cycle"
    )
    logger.info(
        f"Sleep cycle {_state.cycle_id} cancelled before Stage 5 — "
        f"nothing written, queue untouched"
    )
    return _StageOutcome()


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


def _engine_label(settings: Settings) -> str:
    """Which engine a resolved mode means. (Task 7 routes "auto" here too.)

    Delegates to ``engine_select.engine_label`` — kept as a thin wrapper so
    every other call site in this module doesn't need the import. That
    function itself ``getattr``s rather than reading the attribute directly:
    several hermetic Sleep tests pass a ``SimpleNamespace`` stand-in for
    ``Settings`` that predates ``llm_mode`` and never sets it — those must
    still resolve to the "byok"/"litellm" default rather than raising
    ``AttributeError`` before Stage 1 even starts.
    """
    from api.services import engine_select

    return engine_select.engine_label(settings)


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
    20 s timeout on every agent-mode cycle with a non-empty queue. Delegates
    to ``engine_select.probe_claude_cheaply`` (Task 7 fix round 1, M1 round
    2) — the cache-first + bounded-fallback pattern this docstring
    describes now lives in exactly one place, shared with
    ``engine_select.resolve_llm_mode``'s own Claude-plan probe, rather than
    two copies that could drift apart again.
    """
    from api.services import engine_select
    from api.services.connections import registry as connections_registry

    reg = connections_registry.get_registry(settings)
    return await engine_select.probe_claude_cheaply(reg)


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


async def run(settings: Settings, cycle_id: str, *, user_triggered: bool = True) -> None:
    """Execute the 5-stage Sleep cycle pipeline.

    ``user_triggered`` (fix round 1, H1/H2): ``True`` for ``POST
    /sleep/trigger`` (a human pressing Run — the default, so every existing
    call site, test included, is unaffected), ``False`` for the nightly cron
    (``sleep_scheduler._run_if_idle``). Threaded down to
    ``engine_select.resolve_llm_mode`` so a scheduled cycle can never select
    the agent rung even with the Claude card's "Use for Sleep" toggle on —
    spec §7's trigger scope, and what `Copy.sleepEngineExplainer` promises.
    """
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
    # Sleep control: a fresh cycle starts with no cancel pending and no
    # leftover "was this cancelled" flag from whatever ran before it — those
    # are reset here for the same reason every other per-cycle field above
    # is. `episode_cap`/`episodes_queued` are set for real once `_run_stages`
    # loads the queue; zeroed here so a request racing the very start of a
    # cycle never reads stale numbers from the previous one.
    _state.cancel_requested = False
    _state.cancelled = False
    _state.episode_cap = 0
    _state.episodes_queued = 0

    memory_path = settings.memory_path

    # G74(a) — the models-used ledger is process-global still (L4, Task 4
    # review, handed to Task 5 — a disclosed, accepted same-alias limitation,
    # see agent_engine._MODELS_USED). The throttle breaker is NOT: Devin PR
    # #25 round 1, finding 1 — a concurrent Ask/MCP call that also routes
    # through the agent rung used to trip the SAME process-global breaker
    # Sleep's Stage 1 checked, aborting an unrelated cycle for a throttle it
    # never itself hit. This cycle now runs inside its own breaker scope
    # (`agent_engine.use_scope`), keyed by ``cycle_id`` — a value nothing else
    # in the process can ever collide with — so a throttle discovered inside
    # this cycle can only ever stop THIS cycle, and a throttle discovered by
    # a concurrent Ask/MCP call (which never enters this scope) can never
    # abort it. No explicit `reset_breaker()` needed at cycle start any more:
    # a fresh `cycle_id` means a fresh, never-tripped scope, and `use_scope`
    # purges its own scope's entry on exit regardless.
    from api.services import agent_engine
    agent_engine.reset_models_used()

    outcome = _StageOutcome()
    try:
        with agent_engine.use_scope(f"sleep:{cycle_id}"):
            outcome = await _run_stages(
                settings, cycle_id, memory_path, user_triggered=user_triggered
            )
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


async def _run_stages(
    settings: Settings, cycle_id: str, memory_path: Path, *, user_triggered: bool = True,
) -> _StageOutcome:
    """The LLM-dependent pipeline. Returns what it achieved; never runs the tail."""
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

    # Episode cap (sleep-control) — bound one cycle's worst-case wall-clock
    # instead of letting it scale with however large the queue is (spec: a
    # first-run queue on the live bank has ~1,200 episodes of history, and
    # the agent rung's own timing measurement is ~200-350 subprocess calls
    # PER 20 episodes, ~90% serialized). Episodes beyond the cap are simply
    # never handed to Stage 1 — they stay `processed: false` on disk exactly
    # as they already were, so this is a slice, not a mutation, and the next
    # trigger picks up right where this one left off.
    total_unprocessed = len(episodes)
    cap = max(1, int(
        getattr(settings, "sleep_max_episodes_per_cycle", DEFAULT_EPISODE_CAP)
        or DEFAULT_EPISODE_CAP
    ))
    _state.episodes_queued = total_unprocessed
    _state.episode_cap = cap
    if total_unprocessed > cap:
        episodes = episodes[:cap]
        logger.warning(
            f"Episode cap reached: processing {cap} of {total_unprocessed} "
            f"queued episodes this cycle — the remaining "
            f"{total_unprocessed - cap} stay queued for the next cycle"
        )
    else:
        logger.info(f"Found {total_unprocessed} unprocessed episodes")
    _state.episodes_total = len(episodes)

    # Fix round 1, M1 (part 2): resolution moved to AFTER the idle-episode
    # return above — an idle cycle must never touch the connections registry
    # at all, not even the bounded cache-first probe. "auto" (and a default
    # install with the Use-for-Sleep toggle on) can shell out to vendor CLIs
    # on a cold cache, so it is resolved ONCE here, only on a cycle with real
    # work, and the concrete mode travels down as a copy for the rest of this
    # pipeline. The caller's Settings is never mutated: get_settings() is
    # lru_cached and shared with every request handler.
    from api.services import engine_select
    settings, engine_why = await engine_select.resolve_settings(
        settings, user_triggered=user_triggered,
    )
    _state.last_engine = _engine_label(settings)
    _state.engine_detail = engine_why
    logger.info(
        f"Sleep cycle {cycle_id} started — engine: {_state.last_engine}, "
        f"model: {settings.litellm_model}"
    )

    # Sleep control — safe point: nothing has touched disk or spawned a
    # subprocess yet, so a cancel requested any time before this (including
    # while `resolve_settings` above was resolving the engine) aborts clean.
    if _state.cancel_requested:
        return _cycle_cancelled()

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
    extracted = await extract(episodes, settings, cancel_check=_cancel_requested)
    total_entities = sum(len(e.get("entities", [])) for e in extracted)
    total_rels = sum(len(e.get("relationships", [])) for e in extracted)
    logger.info(f"Stage 1 complete: {total_entities} entities, {total_rels} relationships extracted")
    _state.stage = 1

    # Sleep control — safe point: Stage 1 only ever computed `extracted` in
    # memory (no disk write, `write_started` is still False), so a cancel
    # requested during the fan-out (which itself stopped scheduling new
    # episodes the moment it saw the flag — see `entity_extractor.extract`)
    # aborts clean here, discarding whatever partial extraction completed.
    # Checked BEFORE the total-Stage-1-failure check below: a cancelled
    # cycle is not a failure and must not be reported as one.
    if _state.cancel_requested:
        return _cycle_cancelled()

    # Resumable queue — hard stop if EVERY episode failed Stage 1 (wrong
    # model id, exhausted credits, total outage). Abort with the queue
    # untouched instead of running the rest of the pipeline on nothing and
    # committing a misleading empty "completed" cycle. Re-running after
    # fixing the cause retries the whole batch.
    if episodes and not extracted:
        msg = _stage1_failure_message(_state.last_engine or "litellm")
        # Fix round 1, L2: `engine_detail` is now set on EVERY resolved
        # cycle (Task 7), not just an agent-rung pre-flight abort — a plain
        # byok install's `engine_detail` is just "why we're on byok"
        # ("no Sleep engine chosen…"), not a diagnosis of a Stage-1 API
        # failure, so appending it here read as confusing noise on an
        # install that never chose an engine at all. Only the claude-cli
        # rung's detail (the pre-flight probe's own sentence, e.g. "signed
        # out — run `claude auth login`") is actually diagnostic.
        if _state.last_engine == "claude-cli" and _state.engine_detail:
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
    resolved_result = await resolve(extracted, existing, settings, cancel_check=_cancel_requested)
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

    # Sleep control — safe point: still nothing on disk. Stage 2's own
    # per-name judging loop already stopped early on the same flag (see
    # `entity_resolver.resolve`), so this catches a cancel that arrived
    # after the loop's last iteration but before Stage 3 starts.
    if _state.cancel_requested:
        return _cycle_cancelled()

    # Stage 3: Conflict Resolution & Pruning
    _state.progress = "Stage 3/5: Resolving conflicts..."
    logger.info("Stage 3: Conflict resolution & temporal decay")
    from api.services.conflict_resolver import resolve_and_prune
    changes = await resolve_and_prune(resolved_changes, existing, settings)
    logger.info(f"Stage 3 complete: {len(changes)} total changes")
    _state.stage = 3

    # Sleep control — safe point: Stage 3 is pure in-memory arithmetic (no
    # LLM call, no write) — still nothing on disk.
    if _state.cancel_requested:
        return _cycle_cancelled()

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

    # Sleep control — the LAST safe point: one more check before Stage 5
    # flips `write_started` and starts putting bytes on disk. Once that
    # happens this cycle no longer checks the flag again — Stage 5 through
    # `_finalize`'s commit runs to completion uninterrupted, so the bank is
    # never left half-written (see the end-of-cycle handling below, which
    # still reports honestly if a cancel arrived after this point).
    if _state.cancel_requested:
        return _cycle_cancelled()

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
    from api.services import agent_engine

    engine = _state.last_engine or "litellm"
    engine_models = agent_engine.models_used()
    await _finalize(
        memory_path,
        cycle_id,
        changes,
        settings,
        organic_resolution_paths=organic_resolution_paths,
        started=_state.started_monotonic,
        engine=engine,
        # A plan cycle belongs to the claude-plan card and is billed
        # against the subscription, not as money.
        connection="claude-plan" if engine == "claude-cli" else None,
        billing="subscription" if engine == "claude-cli" else None,
        # The models the engine ACTUALLY used this cycle — the CLI may
        # route an internal side-call to a different model than the one we
        # asked for (V1d), and the trailer should say so.
        authors=engine_models or None,
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
    # Episode cap: `episodes_queued` (the FULL unprocessed count found before
    # capping) > `episodes_total` (what this cycle actually attempted) means
    # the cap truncated this cycle. Surfaced in the progress sentence — same
    # convention `requeue_note` above already uses — so a capped cycle never
    # reads as a complete pass over the whole queue.
    cap_note = (
        f" — episode cap reached: {_state.episodes_total} of "
        f"{_state.episodes_queued} processed, "
        f"{_state.episodes_queued - _state.episodes_total} more queued for the next cycle"
        if _state.episodes_queued > _state.episodes_total else ""
    )
    # Sleep control: a cancel that arrived AFTER Stage 5 started writing is
    # too late to stop THIS cycle — by design (see the last safe-point check
    # above) it finishes and commits normally rather than risking a
    # half-written bank. Still worth being honest about in the progress
    # sentence rather than silently swallowing the request.
    cancel_note = ""
    if _state.cancel_requested:
        cancel_note = " — cancel requested after writes began; this cycle finished its commit safely"
        _state.cancel_requested = False
    if _state.index_warning:
        _state.progress = (
            f"Completed with warnings: {_state.index_warning}{requeue_note}{cap_note}{cancel_note}"
        )
        logger.warning(
            f"Sleep cycle {cycle_id} completed with warnings — "
            f"{len(changes)} changes committed; {_state.index_warning}{requeue_note}{cap_note}{cancel_note}"
        )
    else:
        _state.progress = f"Completed{requeue_note}{cap_note}{cancel_note}"
        logger.success(
            f"Sleep cycle {cycle_id} completed — {len(changes)} changes committed"
            f"{requeue_note}{cap_note}{cancel_note}"
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
    connection: str | None = None,
    billing: str | None = None,
    authors: list[str] | None = None,
    sessions: list[str] | None = None,
    episode_sessions: dict[str, str] | None = None,
) -> None:
    """Commit all changes from the sleep cycle with a structured message.

    Entity-level lines from ``changes`` have source + trigger; file-level
    additions (nudges, clarifications, graph_edges, etc.) are inferred from
    ``git status`` so the commit message remains a complete manifest.

    ``engine`` / ``connection`` / ``billing`` / ``authors`` (G74(a) Task 6):
    what actually ran. Left to their defaults these reproduce the old
    behaviour exactly — engine ``"litellm"``, connection derived from the
    model via ``telemetry.connection_for_model``, authors derived from
    ``settings`` (main + Stage-2 disambiguation model, when distinct). The
    agent rung passes all four, because ``connection_for_model`` maps any
    model containing "claude" to ``("byok-anthropic", "usage")``: left
    alone, every plan cycle would be attributed to the *disconnected* BYOK
    API-key card and billed as real money. ``authors``, when given, is what
    the engine REPORTED using (``agent_engine.models_used()``) rather than
    what ``settings`` merely CONFIGURED — the Claude CLI can route an
    internal side-call to a different model than the one requested (V1d),
    and the ``Cicada-Author:`` trailers should say so. When ``authors`` comes
    back empty, the settings-derived fallback (``litellm_model`` +
    disambiguation model) applies ONLY when ``engine == "litellm"`` (L2,
    Task 6 review fix round 1) — on any other rung ``settings.litellm_model``
    never ran, so a cycle whose engine failed to record a model gets NO
    author trailer at all rather than a confidently wrong one. ``engine`` is
    also stamped as a single ``Cicada-Engine:`` trailer on the main commit,
    so ``GET /sleep/history`` can report which engine drove each cycle
    instead of leaving the field unextended forever (Ruling 4).

    G85 — the decay-authorship bug: entity changes whose ``trigger`` is
    ``"sleep/decay"`` are purely arithmetic (``conflict_resolver``'s decay
    math runs over EXISTING entities this cycle never referenced — no LLM
    call, no source episode) yet used to be folded into the same commit as
    everything else and stamped with whichever model happened to run
    Stage 1/2 that cycle, inflating that model's ``GET /contributors``
    counts for arithmetic it never touched. They are split into their OWN
    commit FIRST, authored the literal ``"cicada"`` (system maintenance —
    the same literal the inbox-dedup migration already uses), touching only
    the entity files those changes wrote and carrying no engine/session
    trailer (no engine ran). Everything else a decay change indirectly
    causes — e.g. a ``decay_nudge``'s own new inbox item — stays in the
    main commit; only the entity-frontmatter line itself moves. A change
    that fails to split out for any reason (a stem-derived path with no file
    on disk, or the split commit itself failing) degrades — folds back into
    the main commit exactly as before this fix — rather than aborting the
    cycle; see the inline comment at the split for the full contract.

    L1 (Task 6 review, disclosed, not fixed): the split is PATH-granular,
    not hunk-granular — ``commit_paths`` stages the whole entity file.
    Stage 5.56's claim write-back (``claim_pipeline.py``) reaches subjects
    independently of ``referenced_ids`` (via claim-level decay, or a claim
    extracted this cycle for a subject entity_resolver didn't consider
    "referenced"), so on the rare cycle where the SAME entity file picks up
    both a `sleep/decay` entity-level change AND a genuinely LLM-authored
    claim write, the whole file — claim content included — lands in the
    `cicada` commit. This is the inverse of the bug this task fixes (an
    arithmetic change wrongly credited to a model); accepted rather than
    fixed because doing better needs hunk-level (not file-level) staging,
    which git's plumbing here doesn't give for free. Narrow in practice: it
    only fires when a subject is BOTH decay-eligible (unreferenced by
    Stage 2) AND claim-touched (Stage 5.56) in the same cycle.

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

    # --- G85: split purely-arithmetic decay changes into their own commit,
    # authored `cicada`, committed FIRST so the main commit's `git status`
    # (below) never sees their entity files as dirty.
    #
    # M2 (Task 6 review, fix round 1): this must NEVER be able to take the
    # WHOLE cycle down. `commit_paths` -> `git add -- <path>` exits 128 on a
    # path that doesn't resolve to a real file, and an unguarded `GitError`
    # here would propagate out of `_finalize` before the main commit even
    # runs — nothing commits this cycle, and the NEXT cycle's `git add -A`
    # would then sweep up (and re-attribute to whatever model runs next
    # time) this cycle's ENTIRE batch: the exact G85 smear, but worse, and
    # spread across two cycles. `resolve_and_prune` only ever proposes a
    # decay change for an entity it just loaded from disk (conflict_resolver.py:139),
    # so a missing file should never happen — this is a defensive rail
    # against a stem-derived path being wrong for some other reason, not an
    # expected path. Two layers: (1) only stage a decay change whose entity
    # file exists; (2) wrap the commit itself in try/except. Either way,
    # whatever couldn't be split out this cycle DEGRADES — it folds back into
    # `other_changes` and rides in the main commit exactly as every decay
    # change did before this fix (same `trigger: sleep/decay` manifest line,
    # just authored like the rest of that commit rather than `cicada`) —
    # never silently dropped, never fatal.
    decay_changes: list[dict] = []
    other_changes: list = []
    for change in changes:
        if isinstance(change, dict) and change.get("trigger") == "sleep/decay":
            decay_changes.append(change)
        else:
            other_changes.append(change)

    if decay_changes:
        stageable: list[dict] = []
        unfolded: list[dict] = []
        for change in decay_changes:
            path = f"entities/{change.get('id', 'unknown')}.md"
            (stageable if (memory_path / path).exists() else unfolded).append(change)

        committed = False
        if stageable:
            decay_paths = [f"entities/{c.get('id', 'unknown')}.md" for c in stageable]
            decay_lines = [
                f"{p}: {c.get('action', 'updated')} (source: n/a, trigger: sleep/decay)"
                for c, p in zip(stageable, decay_paths)
            ]
            decay_message = git_service.build_commit_message(
                f"Sleep cycle {date_str} (decay)", decay_lines, authors=["cicada"]
            )
            try:
                async with _lock:
                    await git_service.commit_paths(memory_path, decay_message, decay_paths)
                committed = True
            except Exception as exc:
                logger.warning(
                    f"G85 decay-only commit failed — folding its {len(stageable)} "
                    f"change(s) into the main commit instead of losing the whole "
                    f"cycle: {type(exc).__name__}: {exc}"
                )

        if not committed:
            unfolded = stageable + unfolded
        other_changes = unfolded + other_changes

    # --- Entity lines from structured change data (decay changes excluded —
    # already committed above) ---
    entity_lines: list[str] = []
    entity_files_covered: set[str] = set()
    for change in other_changes:
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

    # Author trailers: the models that actually wrote this consolidation.
    # `authors` (G74(a)) is what the engine REPORTED using; without it we
    # fall back to what settings CONFIGURED (main + Stage-2 judge when
    # distinct) — but ONLY on the litellm/byok rung (L2, Task 6 review fix
    # round 1). `settings.litellm_model` is meaningless on any other rung:
    # the agent rung has its own model pair (`agent_model`/
    # `agent_disambiguation_model`) and never touches `litellm_model` at
    # all, so falling back to it when `authors` came back empty (e.g. every
    # call this cycle failed before recording a model) would invent a BYOK
    # model that never ran — for a `claude-cli` cycle, under
    # `connection="claude-plan"`, which is precisely the mis-attribution
    # this task exists to end. Omit the author entirely instead — an honest
    # "unknown" beats a confident lie.
    resolved_authors: list[str] = [a for a in (authors or []) if a]
    if not resolved_authors and settings is not None and engine == "litellm":
        if settings.litellm_model:
            resolved_authors.append(settings.litellm_model)
        disambig = (settings.litellm_disambiguation_model or "").strip()
        if disambig and disambig not in resolved_authors:
            resolved_authors.append(disambig)

    message = git_service.build_commit_message(
        f"Sleep cycle {date_str}", body_lines, authors=resolved_authors,
        sessions=sessions or [], engine=engine,
    )
    async with _lock:
        commit = await git_service.commit_changes(memory_path, message)

    from api.services import telemetry

    duration_ms = int((time.monotonic() - started) * 1000) if started is not None else None
    model = resolved_authors[0] if resolved_authors else None
    if connection is not None:
        event_connection, event_billing = connection, (billing or "subscription")
    elif model:
        event_connection, event_billing = telemetry.connection_for_model(model)
    else:
        event_connection, event_billing = None, "free"
    telemetry.record(telemetry.UsageEvent(
        kind="sleep_run", stage="structural", engine=engine,
        connection=event_connection,
        model=model,
        bank=telemetry.bank_name(settings) if settings is not None else memory_path.name,
        billing=event_billing,
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
