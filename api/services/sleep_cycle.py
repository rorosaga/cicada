import asyncio
import inspect
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from loguru import logger

from api.config import Settings
from api.services import bank_index, episode_ids, git_service, markdown_parser, sleep_drain, sleep_reserve


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
    # G141 PJ-0 (R-CS3): claims Stage 5.56 could neither write nor hold (PJ-0b)
    # because their subject has no page, and how many page-less subjects there
    # were. Counts only — G141's M3 measure, carried into the `sleep_run`
    # ledger row; never on `/sleep/status`.
    claims_page_less: int = 0
    subjects_page_less: int = 0
    # G141 PJ-0b (R-HP12): the hold, per cycle — claims newly held for a
    # pending name, held claims released onto their page, claims the per-name
    # cap refused, and what still waits in the store after the cycle. Counts
    # only, internal, never on `/sleep/status`.
    claims_held: int = 0
    claims_released: int = 0
    claims_hold_capped: int = 0
    claims_waiting: int = 0
    # Decay inbox items (Stage 5): the cycle's cap on NEW "Still tracking X?"
    # questions turned this many entities away (they raise again next cycle),
    # and this many open ones were refreshed instead of duplicated. Counts
    # only, internal, carried into the `sleep_run` ledger row.
    decay_nudges_deferred: int = 0
    decay_nudges_refreshed: int = 0
    # G74(a) — which engine this cycle actually ran on ("claude-cli" |
    # "codex-cli" | "ollama" | "litellm"), and one sentence about its state. The Sleep page
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
    # Devin PR #27 round 1, finding 3: the monotonic timestamp `cancelled`
    # was set `True` at (by `_cycle_cancelled()`). `cancelled` alone used to
    # stay `True` forever once set — nothing ever cleared it, so every
    # `GET /sleep/status` kept reporting it indefinitely and the Sleep
    # page's cancelled banner never went away. Paired with this timestamp,
    # `cancelled_is_visible()` computes a bounded-time-windowed answer
    # instead — see that function's docstring for why a true read-and-clear
    # would race across concurrent readers instead.
    cancelled_at_monotonic: float | None = None
    # Settings-driven episode cap for this cycle (`Settings.
    # sleep_max_episodes_per_cycle`) and the FULL unprocessed count found
    # before capping — see `SleepStatusResponse` for the field contract.
    episode_cap: int = 0
    episodes_queued: int = 0
    # Sleep debt (G106 amendment) — LIVE Stage-1 progress. Ticks up by one
    # every time `entity_extractor.extract`'s fan-out finishes an episode
    # (success, failure, empty-content fast path, or cancelled-skip all
    # count — mirrors its own tqdm bar). This is the ONLY stage with a
    # natural per-episode unit of work, so "Progress %" is deliberately
    # scoped to it — see `progress_pct()` below — rather than inventing a
    # blended cross-stage metric stages 2-5 have no honest way to report.
    stage1_progress: int = 0
    # G125 (the study desk) — the same per-episode unit as `stage1_progress`,
    # split by source so the Sleep page's study list can count each source
    # down while Stage 1 reads (R3). `queue_by_origin` is this cycle's
    # SELECTED episodes (after the cap slice) grouped by `origin`;
    # `read_by_origin` ticks per finished episode. Both reset with every
    # other per-cycle counter at the top of `run()`.
    queue_by_origin: dict[str, int] = field(default_factory=dict)
    read_by_origin: dict[str, int] = field(default_factory=dict)
    # "Consolidate reads everything" (owner, 2026-09-29) — see `sleep_drain`.
    # A person-started run drains the queue that was waiting when it started, in
    # batches of `episode_cap`; every field above except the origin dicts,
    # `episodes_queued` and `episode_cap` is then BATCH-LOCAL (each batch's own
    # `sleep_run` ledger row carries its own numbers) and the status route adds
    # the finished batches back in (`sleep_drain.merged`). `batch_total` is the
    # running batch's own episode count — Stage 1's denominator; `drain` is the
    # run's state (None for a plain cycle); `drain_run` is true for the whole of
    # a person-started run, reservation to idle, tail included, so the routes
    # that must not move the bank mid-run can ask one question.
    batch_total: int = 0
    batch_started_monotonic: float | None = None
    drain: "sleep_drain.DrainState | None" = None
    drain_run: bool = False
    # A drain's write window (`is_writing`): true from a batch's Stage 2 (which
    # loads the pages Stage 5 rewrites) through its commit, and through the run's
    # start and tail. False while a batch is only reading episodes and calling the
    # engine, and between batches — the app's and an agent's writes are safe then.
    writing: bool = False
    # Only the engine-free tail is running (the schedule's upkeep while a run is paused):
    # the paused record stays on the wire, and no episode is read.
    tail_only: bool = False


_state = SleepState()
_lock = asyncio.Lock()

# Default episode cap when `settings` doesn't carry
# `sleep_max_episodes_per_cycle` (e.g. a `SimpleNamespace` stand-in in an
# older test). Review fix (L5): reflected off `Settings`'s own field default
# rather than a THIRD hardcoded `25` (the other two: `Settings.
# sleep_max_episodes_per_cycle` itself in api/config.py, and `sleep_debt.
# DEFAULT_VOLUME_REFERENCE`, the same fallback for the same reason) — one
# literal, defined once, so changing the real cap can never silently desync
# a fallback used elsewhere from it. See api/config.py for the rationale.
DEFAULT_EPISODE_CAP: int = Settings.model_fields["sleep_max_episodes_per_cycle"].default


def configured_batch_size(settings) -> int:
    """The batch size a cycle would use — what a scheduled run reads and a drain's batch holds."""
    return max(1, int(getattr(settings, "sleep_max_episodes_per_cycle", DEFAULT_EPISODE_CAP) or DEFAULT_EPISODE_CAP))

# Devin PR #27 round 1, finding 3: how long `cancelled` reads `True` after a
# cycle stops because of one, before `cancelled_is_visible()` starts
# reporting it as cleared. Generous — long enough that walking away from the
# app for a few minutes and coming back still shows the confirmation — but
# bounded, so it can never stick around indefinitely the way the un-cleared
# flag used to.
CANCELLED_DISPLAY_WINDOW_SECONDS = 300.0


def get_sleep_state() -> SleepState:
    return _state


def cancelled_is_visible(state: SleepState | None = None, *, now: float | None = None) -> bool:
    """Whether ``cancelled`` should currently read ``True`` to a caller.

    Devin PR #27 round 1, finding 3: ``SleepState.cancelled`` is set once by
    ``_cycle_cancelled()`` and was documented as "true on the FIRST status
    read after a cycle actually stopped early" — but nothing ever cleared
    it, so every ``GET /sleep/status`` kept reporting ``True`` indefinitely
    once a single cycle had ever been cancelled, and the Sleep page's
    cancelled banner never went away.

    A true read-and-clear was rejected: it would race across every
    concurrent reader of the SAME ``_state`` (this endpoint polled from
    more than one client, a future SSE exposure, …) — whichever read lands
    first "uses up" the one display and every other reader never sees it at
    all. This instead computes a bounded TIME window fresh on every call
    from the same stored timestamp (``cancelled_at_monotonic``): every
    reader agrees on the same answer, there is no mutation-on-read and
    therefore no race, and the flag still genuinely clears rather than
    sticking forever — see ``CANCELLED_DISPLAY_WINDOW_SECONDS``.
    """
    s = state or _state
    if not s.cancelled or s.cancelled_at_monotonic is None:
        return False
    elapsed = (now if now is not None else time.monotonic()) - s.cancelled_at_monotonic
    return elapsed < CANCELLED_DISPLAY_WINDOW_SECONDS


def progress_pct(state: SleepState | None = None) -> int | None:
    """Live "episodes processed / episodes in this cycle" — G106 amendment's
    literal Progress % definition, scoped to Stage 1 (the only stage with a
    natural per-episode unit; see `SleepState.stage1_progress`).

    ``None`` — not 0, not a stale leftover — whenever there is no honest
    live number to show: idle, or Stage 1 has already finished (``stage``
    already advanced past 0) and stages 2-5 don't have a per-episode count
    to report. The Sleep page falls back to the coarse ``stage``/``progress``
    text in that gap rather than a placeholder.
    """
    s = state or _state
    # A drain's batch is Stage 1's unit: 3 of this batch's 25, not 3 of 287.
    denominator = s.batch_total if (s.drain is not None and s.batch_total) else s.episodes_total
    if s.status != "running" or s.stage != 0 or denominator <= 0:
        return None
    return round(100 * min(1.0, s.stage1_progress / denominator))


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


def reserve_cycle(cycle_id: str, *, drain: bool = False) -> None:
    """Synchronously claim `_state` for `cycle_id` — called by ``POST
    /sleep/trigger`` BEFORE it schedules ``run`` as a FastAPI background
    task (Devin PR #27 round 1, finding 2).

    A ``BackgroundTasks`` task only starts running after the HTTP response
    is sent — there is a real window, between "the trigger response left
    the process" and "``run()`` actually begins executing", during which
    ``_state.status`` was still ``"idle"``. A ``POST /sleep/cancel`` landing
    in that window used to see nothing running and report ``"not_running"``,
    silently losing a cancel the user believed they'd just sent — the user
    presses Run, immediately thinks better of it, and the long cycle
    proceeds unstoppably anyway.

    Reserving the slot here closes that window: from the instant this
    returns, ``_state.status == "running"`` and ``request_cancel()`` works
    correctly even though ``run()`` itself hasn't started a single line of
    work yet. ``run()`` detects its own reservation (matching ``cycle_id``
    + ``status == "running"``) and PRESERVES whatever ``cancel_requested``
    this window accepted, instead of wiping it the way every other
    per-cycle field gets a fresh reset — see ``run``'s own comment.
    """
    _state.status = "running"
    _state.cycle_id = cycle_id
    _state.cancel_requested = False
    _state.cancelled = False
    _state.cancelled_at_monotonic = None
    _state.drain = None
    _state.drain_run = drain
    _state.tail_only = False
    _state.writing = True   # until `_drain` is reading episodes (a plain cycle ignores it)


def is_writing() -> bool:
    """Is Sleep holding the bank's pages right now? The one predicate every
    "Sleep is running" refusal shares (G177), and what ``GET /sleep/status``
    reports as ``writing`` for the MCP probe.

    A plain or scheduled cycle holds the bank for its whole run, exactly as
    before. A person-started drain runs for hours on a first import, but only a
    batch's Stage 2 through its commit (plus the run's start and its tail) reads
    pages it will rewrite or commits with ``git add -A`` — Stage 1's engine calls
    and the gaps between batches touch no page, so the app's writes and an
    agent's claim commit alone under their own author there, never swept into a
    batch commit under the Sleep model's."""
    return writing_of(get_sleep_state())   # through the accessor: the route guards' tests substitute it


def writing_of(state) -> bool:
    """``is_writing`` for a state already in hand — the sync version and the SSE tick read the one they were given,
    so ``/status``, the `sleep` component and the event never disagree with the refusals (G177)."""
    return state.status == "running" and (not getattr(state, "drain_run", False) or getattr(state, "writing", False))


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
    _state.cancelled_at_monotonic = time.monotonic()
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


async def _poll_feeds_and_calendars_safely(memory_path: Path) -> None:
    """G114 R5: refresh the subscribed RSS feeds and ICS calendars on the
    nightly cycle.

    Before this slot existed, ``feed_registry.poll_feeds`` and
    ``calendar_registry.poll_calendars`` were only ever reached through the
    two user-initiated routes (``POST /sources/poll-feeds`` /
    ``POST /sources/poll-calendars``) — an installed backend's subscriptions
    never refreshed unless someone pressed the button, which makes a
    "subscription" a lie by construction.

    Same contract as ``_poll_connectors_safely``: bounded, never fatal — a
    dead feed host must not fail a Sleep cycle — and each registry runs in
    its own ``try/except`` so a raising feed poll never stops the calendar
    poll (or vice versa). With zero subscriptions in a registry the slot
    logs nothing at all, so a bank with no feeds sees no noise.

    Network gate: the EXISTING opt-in ``CICADA_ALLOW_FEED_FETCH=1`` — the
    registries consult it themselves and answer ``skipped_no_network`` when
    it is closed. Opt-IN, unlike the connectors' opt-OUT
    ``CICADA_ALLOW_CONNECTOR_FETCH``: its semantics are deliberately left
    unchanged (the test suite never sets it, so the gate stays closed there;
    ``install.sh``'s LaunchAgent plist sets it, so an installed backend's
    nightly refresh actually happens). A gate-closed poll is logged as a skip
    rather than silently reported as "0 new", so the log never pretends a
    subscription was refreshed when nothing was fetched.

    MUST run in the same guarded branch as ``_poll_connectors_safely`` and
    never on a tree with uncommitted Sleep writes: both registries commit
    their ingest through ``_commit_poll`` -> ``git_service.commit_changes``,
    which is ``git add -A`` — the exact sweep final-review H1 exists to keep
    away from a half-written cycle.
    """
    try:
        from api.services import calendar_registry, feed_registry
    except Exception as e:
        logger.warning(f"feed/calendar poll unavailable: {type(e).__name__}: {e}")
        return

    slots = (
        ("Feed", "feed", "item", feed_registry.list_feeds, feed_registry.poll_feeds),
        (
            "Calendar", "calendar", "event",
            calendar_registry.list_calendars, calendar_registry.poll_calendars,
        ),
    )
    for label, noun, unit, list_fn, poll_fn in slots:
        try:
            if not list_fn(memory_path):
                continue
            result = await poll_fn(memory_path)
            if result.get("skipped_no_network"):
                logger.info(f'{label} poll skipped: CICADA_ALLOW_FEED_FETCH is not "1"')
                continue
            logger.info(
                f"{label} poll: {result.get('new', 0)} new {unit}(s) "
                f"from {result.get('polled', 0)} {noun}(s)"
            )
        except Exception as e:
            logger.warning(f"{label} poll failed: {type(e).__name__}: {e}")


def _link_summarizer():
    """Stage 5.57's page summarizer, or ``None`` when Sleep may not read pages.

    G61 phase 2 S0 (spec §2, plan R-AC18): the in-cycle pass read a web page on
    every cycle with no gate at all, while its tail twin
    (``_backfill_links_safely``) has been behind ``CICADA_ALLOW_CONNECTOR_FETCH``
    since G102. Same gate, same reason — a fetch Cicada starts on its own — and
    regardless of ``user_triggered``, exactly like the tail; the person's way to
    read pages on demand is ``POST /maintenance/enrich-links``, never gated.
    With ``None`` the pass still runs its zero-network §2a reuse; a thin page is
    stamped ``no_description`` as in any hermetic run, which retires nothing:
    ``scan_backfill`` never reads ``enrichment_attempted``.
    """
    from api.services.connectors.base import network_allowed
    from api.services.link_enrichment import default_summarize

    if network_allowed():
        return default_summarize
    logger.info("Stage 5.57: page read skipped — CICADA_ALLOW_CONNECTOR_FETCH is off (reuse still runs)")
    return None


async def _backfill_links_safely(memory_path: Path, settings: Settings, *, user_triggered: bool) -> None:
    """G102 cheap slice: describe + relate ``link_enrich_backfill_per_cycle``
    saved links a night, oldest-imported first, until the bank is drained.

    Lives on the engine-independent tail — idle nights included — because
    the in-cycle Stage 5.57 pass (``enrich_media_links``, above in
    ``_run_stages``) only runs after Stage 5 on a night with episodes and
    takes the 20 MOST RECENT pages, which is why a bulk-imported bank had
    hundreds of media pages and zero ``describes`` claims (2026-09-02).
    Same contract as its neighbours: bounded, never fatal; and it MUST sit in
    the clean-tree-guarded branch — its own commit is scoped
    (``commit_paths``), but its writes on a half-written cycle would still be
    swept by the next ``_finalize``'s ``git add -A`` under that cycle's model.

    Engine (R10 + TODO.md ruling 4): the scan runs first; when it finds only
    zero-LLM work (§2a reuse, junk) nothing is resolved and the run is
    authored ``cicada`` (fix round 1, M1: an idle cycle must not touch the
    connections registry for nothing). Only with a fetch or recon candidate
    is ``engine_select.resolve_settings`` consulted — a scheduled cycle gets
    byok before the registry is touched; a user-triggered one may probe
    cache-first. ``CICADA_ALLOW_CONNECTOR_FETCH`` gates ONLY this unattended
    step's default fetch (opt-out, the connector contract — G71 final review
    H2); reuse and recon are never gated; the maintenance endpoint is never
    gated at all.
    """
    try:
        from api.services import agent_engine, engine_select, link_enrichment
        from api.services.connectors.base import network_allowed
        from api.services.link_recon import scan_recon

        if not bool(getattr(settings, "link_enrich_enabled", True)):
            return
        per_cycle = int(getattr(settings, "link_enrich_backfill_per_cycle", 20) or 0)
        if per_cycle <= 0:
            return
        scan = link_enrichment.scan_backfill(memory_path, settings)
        recon_cards = scan_recon(memory_path, settings)
        if not (scan.junk or scan.reuse or scan.fetch or recon_cards):
            # Nothing owed: no write, no commit, and — deliberately — no
            # progress marker. `conftest.py` isolates the fetch/telemetry
            # gates but NOT `CICADA_HOME`, and several existing tail tests
            # run this step with a stand-in Settings that predates
            # `link_enrich_enabled`; on their empty tmp banks this return is
            # what keeps a `$CICADA_HOME/link_enrich/<bank>.json` from being
            # written into the developer's real ~/.cicada.
            return
        needs_llm = bool(scan.fetch) or bool(recon_cards)
        resolved, engine = settings, None
        if needs_llm:
            resolved, why = await engine_select.resolve_settings(settings, user_triggered=user_triggered)
            engine = engine_select.engine_label(resolved)
            logger.info(f"Link backfill engine: {engine} ({why})")
        # `network_allowed()` with no argument reads CICADA_ALLOW_CONNECTOR_FETCH
        # exactly as the connector poll does — this is the same unattended
        # transport the gate exists for.
        fetch_ok = needs_llm and network_allowed()
        if needs_llm and not fetch_ok:
            logger.info(
                "Link backfill: page fetch skipped — CICADA_ALLOW_CONNECTOR_FETCH is off "
                "(reuse + recon still run)"
            )
        # Final review H1: the tail runs after the cycle's own `sleep:<id>`
        # scope has closed, so without this it would share the never-reset
        # ``_unscoped`` bucket with Ask — one throttle there would block every
        # later backfill until a restart. Its own scope purges on exit.
        with agent_engine.use_scope(f"links:{uuid.uuid4().hex}"):
            report = await link_enrichment.backfill(
                memory_path, resolved, limit=per_cycle,
                summarize_fn=link_enrichment._summarize_excerpt if fetch_ok else None,
                fetch_fn=link_enrichment.default_fetch if fetch_ok else None,
                engine=engine,
            )
        if report.selected or report.related or report.skipped:
            logger.info(
                f"Link backfill: {report.reused} reused, {report.summarized} summarized, "
                f"{report.related} related, {report.failed} failed, {report.remaining} remaining"
            )
    except Exception as e:
        logger.warning(f"Link backfill failed: {type(e).__name__}: {e}")


async def _resolve_papers_safely(memory_path: Path) -> None:
    """G133: finish the paper parses a running cycle deferred (R-LS17), then fetch
    paper details from the arXiv and Crossref APIs (R-LS18).

    Same contract as its neighbours: bounded (``TAIL_ARXIV_IDS`` /
    ``TAIL_CROSSREF_DOIS`` per cycle), never fatal, and in the clean-tree-guarded
    branch — both halves write entity pages, and on a half-written cycle those
    would ride the next ``git add -A``. The deterministic half runs regardless of
    the network gate; the fetch is the "unattended background call"
    ``CICADA_ALLOW_CONNECTOR_FETCH`` exists to gate, and a gated skip is recorded
    (``record_skip``) so it never reads as "nothing to fetch". No LLM, so no
    engine is resolved (TODO.md ruling 4 is untouched)."""
    try:
        from api.services import folder_source, paper_metadata, papers, sync_state
        from api.services.connectors.base import network_allowed

        deferred = await asyncio.to_thread(papers.reconcile_pending, memory_path)
        if deferred["folders"]:
            await folder_source.commit_paths_for(memory_path, deferred["paths"], subject="Folder papers",
                                                 trigger="folder/papers", author="cicada",
                                                 channel="papers")
        if not await asyncio.to_thread(paper_metadata.has_pending, memory_path):
            return
        if not network_allowed():
            sync_state.record_skip(memory_path, "papers", "network fetch disabled")
            logger.info("Paper details skipped: CICADA_ALLOW_CONNECTOR_FETCH is off")
            return
        report = await paper_metadata.run_locked(
            memory_path, max_arxiv=paper_metadata.TAIL_ARXIV_IDS, max_crossref=paper_metadata.TAIL_CROSSREF_DOIS)
        if report:
            logger.info(f"Paper details: {report['resolved']} resolved, {report['failed']} not found, "
                        f"{report['remaining']} remaining")
    except Exception as e:
        logger.warning(f"Paper details failed: {type(e).__name__}: {e}")


async def _replay_wispr_todos_safely(memory_path: Path) -> None:
    """G134: write the Wispr Flow to-do claims a sync deferred because this cycle
    was running (L final review, finding 5 — the owner's page is Stage 5's to
    rewrite). Deterministic, no LLM; its commit is scoped to what it wrote, in
    the clean-tree-guarded branch for the same reason as the paper step. The
    claims are Wispr Flow's, not the cycle model's, so the author is
    ``cicada``. Never fatal."""
    try:
        from api.services import folder_source, wispr_flow

        report = await asyncio.to_thread(wispr_flow.replay_pending_todos, memory_path)
        if report["paths"]:
            await folder_source.commit_paths_for(memory_path, report["paths"], subject="Wispr Flow to-dos",
                                                 trigger="wispr-flow/todos", author="cicada",
                                                 channel=wispr_flow.CHANNEL_ID)
    except Exception as e:
        logger.warning(f"Wispr Flow to-dos failed: {type(e).__name__}: {e}")


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
    # A drain's batch (`sleep_drain`): why it ended early, if it did; the
    # exception that escaped it; the plan breaker its scope had tripped (read
    # before the scope's exit purges it — a batch can commit AND have tripped
    # the plan limit, which stops the drain one batch sooner than discovering it
    # again); and whether the tail should skip the link backfill (it would meet
    # the same limit). A plain cycle never sets any of these.
    stop: "sleep_drain.DrainStop | None" = None
    raised: BaseException | None = None
    breaker: str | None = None
    breaker_resets_at: int | None = None
    breaker_kind: str | None = None
    skip_links: bool = False
    # Sleep page v5 — what happened to each conversation of a drain's batch.
    # ``filed_ids``: marked processed by this batch's commit. ``unread``: failed for
    # their own reasons (id -> reason enum) — they get one more try, then park.
    # ``pause_class``: some conversation failed because of the ENGINE (signed out,
    # throttled): the batch commits what it read, then the run stops and nothing is
    # counted against those conversations. ``pause_sentence``: the engine's words.
    filed_ids: set = field(default_factory=set)
    unread: dict = field(default_factory=dict)
    pause_class: bool = False
    pause_sentence: str | None = None


@dataclass
class BatchPlan:
    """What makes ``_run_stages`` one batch of a drain rather than a whole cycle.

    ``only_ids``: the frozen ids this batch reads. ``resolved``: the engine
    settings and its reason, resolved ONCE for the drain ("Auto" must not flip to
    another, paid, engine at batch 9). ``decay`` / ``links``: the once-per-drain
    work, true only for the batch that empties the queue. ``keep_cancel``: a
    cancel that arrives after this batch began writing survives it, so the drain
    loop sees it. ``label``: the ``Batch k of n · `` prefix of the progress
    sentence. ``decay_only``: no episodes at all — the fallback pass when the
    last planned batch's ids were all read elsewhere first.
    """
    only_ids: list[str]
    resolved: tuple
    decay: bool = False
    links: bool = False
    keep_cancel: bool = True
    label: str = ""
    index: int = 1
    of: int = 1
    drain_id: str = ""
    decay_only: bool = False
    #: The drain this batch belongs to (its live counters, attempts and reserve guard).
    ds: "sleep_drain.DrainState | None" = None


def _accepting(fn, **kw) -> dict:
    """The optional keyword arguments ``fn`` accepts. Tests stub the pipeline's
    seams with fixed signatures; a new progress or stop hook is offered only to a
    callable that can take it, so no stub has to learn about it."""
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return {}
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return kw
    return {k: v for k, v in kw.items() if k in params}


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


def _requeue_note(requeued: int, breaker: str | None) -> str:
    """R-E12: when a plan stop is why episodes stayed queued, the completion
    sentence says so in the plan's own words — "re-run to continue" was true
    but hid the one fact that mattered (wait for the reset)."""
    if not requeued:
        return ""
    return f" — {requeued} episode(s) requeued ({breaker or 're-run to continue'})"


def _stage1_failure_message(engine: str, engine_detail: str | None = None) -> str:
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
    from api.services import agent_engine, engine_select

    breaker = agent_engine.breaker_reason()
    if breaker:
        n = _state.episodes_total
        # R-E22: name the plan that actually ran — the breaker is shared by
        # both plan engines (R-E19).
        plan = engine_select.PLAN_NAMES.get(engine, "Claude plan")
        return f"{plan} throttled — stopped cleanly, {n} episode(s) left queued. ({breaker})"
    if engine == "claude-cli":
        return (
            "Stage 1 extracted nothing — every episode failed on the Claude Code engine. "
            "Run `claude auth status` to check the plan is signed in. "
            "The queue is intact; trigger Sleep again once it is."
        )
    if engine == "codex-cli":
        return (
            "Stage 1 extracted nothing — every episode failed on the ChatGPT plan engine. "
            "Check ChatGPT is still signed in on Settings → Plans & keys. "
            "The queue is intact; trigger Sleep again once it is."
        )
    if engine == "ollama":
        return (
            "Stage 1 extracted nothing — every episode failed on the local Ollama engine. "
            "Check the Ollama server is running and the model is pulled. "
            "The queue is intact for retry."
        )
    # G117 — a plain byok install that never chose an engine (rung 4's
    # "nobody chose" default) gets an honest reason instead of a diagnosis
    # of a key that was never entered. `engine_detail` already carries this
    # exact signal (engine_select.py:246,271) — reuse it rather than adding
    # a second "was anything configured" probe (R8). This branch must sit
    # AFTER the claude-cli/ollama checks above (unaffected by it) and BEFORE
    # the generic byok return below (the one it replaces for this one case).
    if engine_detail and "no sleep engine chosen" in engine_detail.lower():
        return "Stage 1 extracted nothing — no engine chosen — pick one in Settings → Engines."
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


async def _refresh_state_safely(memory_path: Path, settings: Settings) -> None:
    """G53 — regenerate `_state.md` and commit it alone as `cicada`.

    FIRST step of the engine-independent tail, on every exit path — an idle
    night, a cancelled cycle and an engine outage all still get a fresh
    now-view. Runs BEFORE the connector/feed/calendar polls: their commits
    are `git add -A`, so a projection left dirty for any reason (a failed
    read-side commit, an older build) would otherwise be swept into a
    `Sources ingest` / `Feed poll` commit under the wrong trigger and author
    (R2 — the H1 guard does not cover this: it only consults the tree once
    `_state.write_started` is set). `force=True`: Sleep always rebuilds, picking up
    the app's latest repo observations (``repo_observations`` — never a git
    run in a declared folder). The write+commit is
    `state_dictionary.refresh_and_commit` — the same helper `GET /state` and
    an inbox resolution use, so every regeneration lands in the same
    `State snapshot` / `Cicada-Author: cicada` shape via `commit_paths`,
    never `git add -A`; on a half-written cycle only the projection lands
    here and the dirty entity pages stay untouched. No engine trailer — no
    LLM ran — exactly like the G85 decay commit. Unchanged content writes
    nothing and commits nothing (R1); the helper never raises.
    """
    from api.services import state_dictionary

    try:
        result = await state_dictionary.refresh_and_commit(memory_path, settings, lock=_lock, force=True)
    except Exception as exc:
        logger.warning(f"State snapshot failed: {type(exc).__name__}: {exc}")
        return
    if result.get("committed"):
        logger.info("State snapshot: _state.md regenerated and committed")
    else:
        logger.info(f"State snapshot: {result.get('reason', 'unchanged')}")


async def _dirty_paths(memory_path: Path) -> frozenset[str]:
    """Every path `git status` reports as changed or untracked (`git_service.dirty_paths`)."""
    return await git_service.dirty_paths(memory_path)


async def _expire_claims_safely(memory_path: Path) -> None:
    """G140 Q-R7 (R3 P8) — close facts whose stated end has passed, in one
    `cicada` commit. Time-driven, not episode-driven, so it lives on the tail
    and runs on idle nights too. Only in the guarded branch: `commit_paths`
    stages whole files, and on a half-written cycle it would take Sleep's
    uncommitted hunks on the same page. A failed commit restores the pages
    (see `claim_expiry.restore`). Never raises.

    Pages already dirty before expiry are skipped (Task 4 review round 1): the
    guarded branch also runs on an idle night with a dirty tree, so a page can
    carry an uncommitted Obsidian or app edit. Rewriting it would let
    `restore`'s `git checkout` delete that edit on a failed commit (the stdio
    MCP process commits outside `_lock`, so index.lock contention is real), or
    commit it as `cicada` on a good one. If the tree cannot be read, nothing
    is expired tonight — an end is re-derived, a lost edit is not."""
    from api.services import claim_expiry

    today = date.today()
    skip: frozenset[str] = frozenset()
    if (memory_path / ".git").exists():
        try:
            skip = await _dirty_paths(memory_path)
        except Exception as exc:
            logger.warning(f"Claim expiry skipped: tree status unreadable ({type(exc).__name__})")
            return
    try:
        report = await asyncio.to_thread(claim_expiry.expire, memory_path, today, skip=skip)
    except Exception as exc:
        logger.warning(f"Claim expiry failed: {type(exc).__name__}: {exc}")
        return
    if not report.paths:
        return
    if not (memory_path / ".git").exists():
        logger.info(f"Claim expiry: {len(report.claims)} fact(s) closed (no git — not committed)")
        return
    try:
        async with _lock:
            await git_service.commit_paths(memory_path, claim_expiry.commit_message(report, today), report.paths)
        logger.info(f"Claim expiry: {len(report.claims)} fact(s) reached their stated end")
    except Exception as exc:
        logger.warning(f"Claim expiry commit failed — restoring {len(report.paths)} page(s): "
                       f"{type(exc).__name__}: {exc}")
        await asyncio.to_thread(claim_expiry.restore, memory_path, report.paths)


async def _propose_followups_safely(memory_path: Path) -> None:
    """G141 PJ-6 — the engine-free follow-up proposer, in its own `cicada`
    commit (R-PJB23). Same rules as expiry: pages dirty before it ran are
    skipped (a person's uncommitted edit is never asked about or smeared), an
    unreadable tree means nothing tonight, a failed commit undoes what it wrote.
    Never raises."""
    from api.services import followups

    today = date.today()
    skip: frozenset[str] = frozenset()
    if (memory_path / ".git").exists():
        try:
            skip = await _dirty_paths(memory_path)
        except Exception as exc:
            logger.warning(f"Follow-ups skipped: tree status unreadable ({type(exc).__name__})")
            return
    try:
        report = await asyncio.to_thread(followups.propose, memory_path, today, skip=skip)
    except Exception as exc:
        logger.warning(f"Follow-ups failed: {type(exc).__name__}: {exc}")
        return
    paths = report.written + report.removed
    if not paths or not (memory_path / ".git").exists():
        return
    try:
        async with _lock:
            await git_service.commit_paths(memory_path, followups.commit_message(report, today), paths)
        logger.info(f"Follow-ups: {len(report.written)} asked, {len(report.removed)} cleared")
    except Exception as exc:
        logger.warning(f"Follow-ups commit failed — undoing: {type(exc).__name__}: {exc}")
        await asyncio.to_thread(followups.restore, memory_path, report)


async def _link_sources_safely(memory_path: Path) -> None:
    """G61 S3-a (D8) — link a source to its own memory node when it is EXACTLY that node (a saved page's URL, a
    directory page's path). Engine-free, in its own `cicada` commit; same rules as follow-ups: pages dirty before
    it ran are skipped, an unreadable tree means nothing tonight, a failed commit undoes what it wrote. Never raises."""
    from api.services import source_links

    skip: frozenset[str] = frozenset()
    if (memory_path / ".git").exists():
        try:
            skip = await _dirty_paths(memory_path)
        except Exception as exc:
            logger.warning(f"Source links skipped: tree status unreadable ({type(exc).__name__})")
            return
    try:
        report = await asyncio.to_thread(source_links.backfill, memory_path, skip)
    except Exception as exc:
        logger.warning(f"Source links failed: {type(exc).__name__}: {exc}")
        return
    if not report.paths or not (memory_path / ".git").exists():
        return
    try:
        async with _lock:
            await git_service.commit_paths(
                memory_path, source_links.commit_message(report, date.today()), report.paths)
        logger.info(f"Source links: {report.linked} source(s) linked to their own page")
    except Exception as exc:
        logger.warning(f"Source links commit failed — undoing: {type(exc).__name__}: {exc}")
        await asyncio.to_thread(source_links.restore, memory_path, report)


async def _site_sources_safely(memory_path: Path) -> None:
    """G61 S3-b — propose an official site from what a page already says (its `website` claim, a `## Links` host that
    is its own name) and confirm proposed sites on Cicada's OWN rail (`link_enrichment.fetch_identity`): at most
    `site_sources.TAIL_BUDGET` fetches a night, one per site, never a walled or platform host. Behind
    `CICADA_ALLOW_CONNECTOR_FETCH` (the unattended-fetch gate; a skipped night writes nothing and asks nothing). One
    path-scoped `cicada` commit (`Site check <date>`, trigger `sleep/site-check`, no engine trailer); pages dirty
    before it ran are skipped and a failed commit restores them. Never raises."""
    from api.services import site_sources
    from api.services.connectors.base import network_allowed

    if not network_allowed():
        logger.info("site check skipped: unattended fetches are off (CICADA_ALLOW_CONNECTOR_FETCH)")
        return
    skip: frozenset[str] = frozenset()
    if (memory_path / ".git").exists():
        try:
            skip = await _dirty_paths(memory_path)
        except Exception as exc:
            logger.warning(f"Site check skipped: tree status unreadable ({type(exc).__name__})")
            return
    report = site_sources.Report()   # built first and handed to both steps, so a page written before a failure is on it
    try:
        await asyncio.to_thread(site_sources.propose, memory_path, skip, report)
        await site_sources.verify(memory_path, budget=site_sources.TAIL_BUDGET, skip=skip, report=report)
    except Exception as exc:
        # A page written before the failure must not ride the next `git add -A` writer's commit (the G85 smear).
        logger.warning(f"Site check failed — undoing {len(report.paths)} page(s): {type(exc).__name__}: {exc}")
        await asyncio.to_thread(site_sources.restore, memory_path, report)
        return
    logger.info(f"Site check: {report.counts}")   # counts only — never a host, a page or a reason
    if not report.paths or not (memory_path / ".git").exists():
        return
    try:
        async with _lock:
            await git_service.commit_paths(
                memory_path, site_sources.commit_message(report, date.today()), report.paths)
    except Exception as exc:
        logger.warning(f"Site check commit failed — undoing: {type(exc).__name__}: {exc}")
        await asyncio.to_thread(site_sources.restore, memory_path, report)


async def _run_engine_independent_tail(
    memory_path: Path, settings: Settings, outcome: _StageOutcome, *, user_triggered: bool = True,
    skip_links: bool = False,
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

    G114 R5: the feed + calendar poll (``_poll_feeds_and_calendars_safely``)
    shares the connector poll's guarded branch — never the ``else`` — for
    the same reason the guard exists at all: ``feed_registry._commit_poll``
    and ``calendar_registry._commit_poll`` both commit through
    ``git_service.commit_changes``, i.e. ``git add -A``, so a poll that
    ingests on a half-written cycle would sweep the Sleep cycle's own
    uncommitted entity pages into a ``Feed poll`` / ``Calendar poll`` commit
    with no session provenance.

    G102: the link backfill (``_backfill_links_safely``) shares this branch
    for the same reason as the feed poll. Its own commit is scoped
    (``git_service.commit_paths``, never ``git add -A``), so it is not the
    sweeper — but it writes media pages, and on a half-written cycle those
    writes would sit on the dirty tree the NEXT ``_finalize`` sweeps under
    that cycle's model. ``user_triggered`` is threaded through only for the
    backfill's lazy engine resolution (R10): a scheduled cycle must resolve
    byok without ever probing the plan — TODO.md ruling 4.

    G133: ``_resolve_papers_safely`` shares this branch — it writes paper pages
    (scoped commits), and the fetch half is gated by
    ``CICADA_ALLOW_CONNECTOR_FETCH``. G134's ``_replay_wispr_todos_safely``
    does too: it writes the owner's page.

    G53: ``_refresh_state_safely`` runs FIRST and unconditionally — it
    commits only ``_state.md`` via ``commit_paths``, so it is safe on a dirty
    tree, and running it before the polls means their ``git add -A`` can
    never sweep a projection left dirty (a failed read-side commit, an older
    build) into a poll commit. Anything the polls or the question refresh
    change afterwards leaves the file one read behind (R2, disclosed) — the
    next ``GET /state`` regenerates and commits it as ``cicada``.

    G140: expiry (_expire_claims_safely) shares this branch — its commit is
    scoped, but on a half-written cycle it would stage Sleep's hunks on the
    same page.

    G141 PJ-6: the follow-up proposer (_propose_followups_safely) runs right
    after expiry — tonight's closed dues are then visible to it — and before
    any poll, whose `git add -A` would otherwise sweep its inbox files into a
    poll commit; its own commit is scoped and `cicada`-authored.

    G141 capture-side track (R-CS16): on a demo bank the outside-world steps
    are skipped; expiry, the follow-up proposer, the state refresh, logos and
    the question refresh still run.
    """
    await _refresh_state_safely(memory_path, settings)
    if outcome.committed or not _state.write_started or await _tree_is_clean(memory_path):
        # Final-review H1 is preserved: on the happy path this still runs
        # AFTER ``_finalize``'s commit, so the connectors' (and the feed /
        # calendar registries') ``git add -A`` finds a clean tree. On a cycle
        # that started writing and never committed, we only poll when the
        # tree is already clean anyway, so a partial Sleep write can never be
        # swept into a media/feed/calendar commit with no session provenance.
        # G140 Q-R7: expiry commits itself via commit_paths; first, so no poll's git add -A can sweep it.
        await _expire_claims_safely(memory_path)
        # G141 PJ-6: after expiry (the night's ends are visible), before any poll's `git add -A`.
        await _propose_followups_safely(memory_path)
        # G61 S3-a (D8): exact-match source -> its own page links, before any poll's `git add -A`.
        await _link_sources_safely(memory_path)
        from api.services import demo_guard

        if demo_guard.is_demo(memory_path):
            # G141 capture-side track (R-CS16): a demo bank's Sleep consolidates
            # its own made-up episodes but never takes in the outside world —
            # the connector credentials are machine-global, so a poll here would
            # pull the person's real saves into the demo.
            logger.info("demo bank: connector, feed/calendar, link-backfill, paper and Wispr to-do steps skipped")
        else:
            # G61 S3-b: before any poll's `git add -A`, so it cannot sweep this step's pages.
            await _site_sources_safely(memory_path)
            await _poll_connectors_safely(memory_path)
            await _poll_feeds_and_calendars_safely(memory_path)
            if skip_links:
                # A drain that stopped on the plan's limit: the backfill would meet the same one.
                logger.info("link backfill skipped: the run stopped at the plan's limit")
            else:
                await _backfill_links_safely(memory_path, settings, user_triggered=user_triggered)
            await _resolve_papers_safely(memory_path)
            await _replay_wispr_todos_safely(memory_path)
    else:
        logger.warning(
            "claim expiry, follow-ups, connector, feed/calendar, link-backfill, paper details and Wispr "
            "to-do steps skipped: this cycle "
            "wrote entity/inbox changes but never committed them, and the polls' "
            "own `git add -A` would absorb those uncommitted writes into a "
            "media/feed/calendar commit"
        )
    await _warm_logos_safely(memory_path)
    if not outcome.questions_refreshed:
        # Staleness is a function of TIME, not of episodes: a cycle that never
        # reached Stage 5.56 must still escalate questions everyone stopped
        # talking about (and clear ones answered organically).
        await _refresh_questions_safely(memory_path, settings)


async def _flush_pending_commits_safely(memory_path: Path) -> None:
    """F2-back R-B5: land the folder, paper and Wispr commits git refused, under
    their own authors, BEFORE any stage writes — `_finalize`'s `git add -A` is
    the writer that would otherwise sweep them under this cycle's model (the
    G85 smear). Deterministic; never fatal."""
    try:
        from api.services import folder_source

        landed = await folder_source.flush_pending_commits(memory_path)
        if landed:
            logger.info(f"Landed {landed} kept commit(s) before the cycle")
    except Exception as e:
        logger.warning(f"Kept commits not landed: {type(e).__name__}: {e}")


async def run(settings: Settings, cycle_id: str, *, user_triggered: bool = True, drain: bool = False,
              continue_from: dict | None = None, only_ids: list[str] | None = None,
              tail_only: bool = False) -> None:
    """Execute the 5-stage Sleep cycle pipeline.

    ``tail_only`` (the scheduler, while a run is paused): read nothing — the paused run is
    the person's to continue or end — but still run the engine-free tail (the state refresh,
    claim expiry, follow-ups, the polls, the link backfill), so a pause never stops them.
    The paused run's in-memory state (``_state.drain``) is left as it was.

    ``continue_from`` (Sleep page v5): a paused run's record (``sleep_paused``) — the
    drain resumes it under the same run id with its counters carried. ``only_ids``:
    the drain's frozen list is exactly these ids (Retry on parked conversations).
    Only ``routers/sleep.py`` (a person's Continue) and ``sleep_autocontinue`` (the
    opt-in switch, TODO ruling 15) may pass ``continue_from``.

    ``drain`` ("Consolidate reads everything", owner 2026-09-29): the run
    freezes the ids waiting now and reads them all, in batches of
    ``sleep_max_episodes_per_cycle``, each filed and committed before the next
    (``_drain``). ``True`` for every person-started path (``POST /sleep/trigger``,
    Continue, Retry), for the opt-in auto-continue (TODO ruling 15) and for both
    scheduler entry points (TODO ruling 16) — scheduled runs are kept off plans by
    ``user_triggered=False``, not by one batch; the one exception, an explicit
    ``CICADA_LLM_MODE=agent|codex`` pin, makes the scheduler pass ``False``
    (``engine_select.scheduled_plan_pin``). ``False`` (the default) is the
    one-batch cycle as it always was.

    ``user_triggered`` (fix round 1, H1/H2): ``True`` for ``POST
    /sleep/trigger`` (a human pressing Run — the default, so every existing
    call site, test included, is unaffected), ``False`` for the nightly cron
    (``sleep_scheduler._run_if_idle``). Threaded down to
    ``engine_select.resolve_llm_mode`` so a scheduled cycle can never select
    the agent rung even with the Claude card's "Use for Sleep" toggle on —
    spec §7's trigger scope, and what `Copy.sleepEngineExplainer` promises.
    """
    global _state

    # Sleep control (Devin PR #27 round 1, finding 2): if `reserve_cycle`
    # already claimed this EXACT cycle_id (the synchronous trigger-time
    # reservation that closes the "background task hasn't started yet"
    # cancel-miss window — see that function's own docstring), a cancel
    # accepted during that window must survive into this run. Every OTHER
    # caller — the cron scheduler, a test calling `run()` directly with no
    # prior reservation — never reserved anything for this cycle_id, so
    # `cancel_requested` still gets the clean reset every other per-cycle
    # field below gets; only a matching, already-reserved cycle_id is
    # preserved, so a stray flag left over from some unrelated cycle can
    # never leak into a fresh one that never asked for it.
    reserved_here = _state.cycle_id == cycle_id and _state.status == "running"
    preserved_cancel_requested = _state.cancel_requested if reserved_here else False

    _state.status = "running"
    _state.cycle_id = cycle_id
    _state.started_at = datetime.now().isoformat()
    _state.started_monotonic = time.monotonic()
    _state.progress = "Starting..."
    _state.error = None
    _state.index_warning = None
    # Reset structured metrics at the top of every run so the Sleep dashboard
    # doesn't show stale counts from a previous cycle.
    _reset_batch_counters()
    _state.episodes_total = 0
    _state.last_engine = None
    _state.engine_detail = None
    if not tail_only:
        _state.drain = None
    _state.drain_run = drain and not tail_only
    _state.tail_only = tail_only
    _state.writing = True   # the run's start flushes pending commits; `_drain` opens the window per batch
    # Sleep control: `cancelled` (the OUTPUT flag) always starts fresh — we
    # haven't finished anything yet. `cancel_requested` (the INPUT flag)
    # restores whatever `reserve_cycle` accepted for THIS cycle_id above,
    # rather than the unconditional False every other per-cycle field gets.
    # `episode_cap`/`episodes_queued` are set for real once `_run_stages`
    # loads the queue; zeroed here so a request racing the very start of a
    # cycle never reads stale numbers from the previous one.
    _state.cancel_requested = preserved_cancel_requested
    _state.cancelled = False
    _state.cancelled_at_monotonic = None
    _state.episode_cap = 0
    _state.episodes_queued = 0
    _state.queue_by_origin = {}
    _state.read_by_origin = {}

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
        await _flush_pending_commits_safely(memory_path)
        if tail_only:
            _state.progress = "Tidying up while your run is paused"
        elif drain:
            outcome = await _drain(settings, cycle_id, memory_path, user_triggered=user_triggered,
                                   continue_from=continue_from, only_ids=only_ids)
        else:
            outcome = await _run_batch(settings, cycle_id, memory_path, user_triggered=user_triggered)
    except Exception as e:
        _state.progress = f"Failed: {e}"
        _state.error = f"{type(e).__name__}: {e}"
        if not tail_only and _state.drain is not None and _state.drain.stop is None:
            _state.drain.stop = sleep_drain.DrainStop("error", _state.error)
            # An unexpected raise outside a batch is a failed run, not a paused one: nothing to continue.
            try:
                from api.services import sleep_paused

                sleep_paused.clear(memory_path)
                _record_leg(_state.drain, memory_path, "failed", stop=_state.drain.stop)
            except Exception:  # noqa: BLE001
                pass
        logger.error(f"Sleep cycle failed: {e}")
        logger.exception("Full traceback:")
    finally:
        from api.services import cycle_usage
        cycle_usage.discard(cycle_id)  # bounded: a cycle that never finalized frees its windows
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
            _state.writing = True   # the tail's commits sweep with `git add -A`: a hold, like a plain cycle
            await _run_engine_independent_tail(
                memory_path, settings, outcome, user_triggered=user_triggered,
                # Only a drain stopped at the plan's limit passes this; the call
                # stays the plain one otherwise, exactly as before.
                **({"skip_links": True} if outcome.skip_links else {}),
            )
        finally:
            _state.status = "idle"
            _state.writing = False
            _state.tail_only = False
            # The run is over whichever way it ended (a raise outside a batch
            # included): release the bank guard and close the drain's own flag.
            _state.drain_run = False
            if _state.drain is not None:
                _state.drain.active = False
                if _state.drain.ended_mono is None:
                    _state.drain.ended_mono = time.monotonic()


def _reset_batch_counters() -> None:
    """Zero the counters ONE batch (a plain cycle is one) owns — everything a
    ``sleep_run`` ledger row carries plus the live Stage-1 tick and the
    write-started flag. Left alone on purpose: the cancel flags, the origin
    dicts, ``error`` and the engine fields, which belong to the whole run."""
    _state.stage = 0
    _state.batch_total = 0
    _state.stage1_progress = 0
    _state.entities_created = 0
    _state.entities_updated = 0
    _state.relationships_created = 0
    _state.skills_detected = 0
    _state.episodes_processed = 0
    _state.episodes_requeued = 0
    _state.questions_refreshed = 0
    _state.organic_resolutions = 0
    _state.claims_page_less = 0
    _state.subjects_page_less = 0
    _state.claims_held = 0
    _state.claims_released = 0
    _state.claims_hold_capped = 0
    _state.claims_waiting = 0
    _state.decay_nudges_deferred = 0
    _state.decay_nudges_refreshed = 0
    _state.write_started = False


async def _run_batch(
    settings: Settings, batch_cycle_id: str, memory_path: Path, *, user_triggered: bool,
    batch: BatchPlan | None = None,
) -> _StageOutcome:
    """One pass of the pipeline in its own breaker scope: a whole plain cycle
    (``batch is None``, exceptions propagate to ``run`` exactly as before) or one
    batch of a drain.

    A batch is a cycle in every way the ledger cares about: its own id (so
    ``cycle_usage`` brackets and attributes exactly its calls), its own breaker
    scope (a throttle in batch 2 is not a stale trip in batch 3), its own models
    ledger (its commit's ``Cicada-Author`` names the models IT used), its own
    clock. A drain's batch never raises: an exception is classified into a stop
    the loop reads, with the plan breaker and its reset time captured before the
    scope's exit purges them.
    """
    from api.services import agent_engine, cycle_usage

    _state.batch_started_monotonic = time.monotonic()
    if batch is not None:
        agent_engine.reset_models_used()
        if batch.ds is not None:
            sleep_drain.register_batch(batch_cycle_id, batch.ds)   # its calls count toward the drain
    try:
        with agent_engine.use_scope(f"sleep:{batch_cycle_id}"):
            try:
                outcome = await _run_stages(
                    settings, batch_cycle_id, memory_path, user_triggered=user_triggered,
                    **({} if batch is None else {"batch": batch}),
                )
            except Exception as exc:
                if batch is None:
                    raise
                stop = sleep_drain.classify(
                    exc, agent_engine.breaker_reason(), agent_engine.breaker_resets_at(),
                    agent_engine.breaker_kind())
                if stop.reason != "plan_limit":
                    logger.error(f"Sleep batch {batch_cycle_id} failed: {exc}")
                    logger.exception("Full traceback:")
                return _StageOutcome(raised=exc, stop=stop)
            if batch is not None:
                if outcome.stop is None and _state.cancelled and not outcome.committed:
                    outcome.stop = sleep_drain.DrainStop("cancelled")   # `_cycle_cancelled` raised the flag
                outcome.breaker = agent_engine.breaker_reason()
                outcome.breaker_resets_at = agent_engine.breaker_resets_at()
                outcome.breaker_kind = agent_engine.breaker_kind()
            return outcome
    finally:
        if batch is not None:
            cycle_usage.discard(batch_cycle_id)  # bounded: a batch that never finalized frees its windows
            sleep_drain.unregister_batch(batch_cycle_id)


def _apply_drain_stop(ds: "sleep_drain.DrainState", stop: "sleep_drain.DrainStop") -> None:
    """Turn a stop into what the status route shows. A plan limit, the reserve line
    and a cancel are pauses, not failures (no ``error``); an unusable engine, a moved
    bank and anything unexpected fail the run exactly like a failed cycle does."""
    ds.stop = stop
    ds.finished = False
    where = (f"Stopped after batch {ds.committed_batches} of {ds.batches} — "
             if ds.committed_batches else "")
    if stop.reason in ("plan_limit", "reserve"):
        _state.error = None
        _state.engine_detail = stop.sentence or _state.engine_detail
        _state.progress = f"{where}{stop.sentence}".strip() or "Stopped at the plan's limit"
        _state.cancel_requested = False
    elif stop.reason == "cancelled":
        _state.error = None
        _state.cancelled = True
        _state.cancelled_at_monotonic = time.monotonic()
        _state.cancel_requested = False
        _state.progress = (
            f"Cancelled — {ds.filed} of {ds.frozen} filed; the rest stay queued for the next Consolidate"
        )
    else:
        message = stop.sentence or "Sleep stopped"
        _state.error = _state.error or message
        _state.progress = f"Failed: {message}"


def _sample_owner(ds: "sleep_drain.DrainState", memory_path: Path, key: str | None = None) -> None:
    """The owner page's current belief count, sampled at a run's start, after its first
    batch and at its end (engine-free, frontmatter and one page). ``None`` when the
    bank has no owner page — a run never creates one."""
    from api.services import sleep_progress

    try:
        n = sleep_progress.owner_beliefs(memory_path)
    except Exception:  # a count for a sentence, never worth failing a run
        return
    if n is None:
        return
    cur = dict(ds.owner_beliefs or {"beliefs": n, "at_start": None, "after_first_batch": None})
    cur["beliefs"] = n
    if key:
        cur[key] = n
    ds.owner_beliefs = cur


def _write_run_record(ds: "sleep_drain.DrainState", memory_path: Path, *, phase: str,
                      stop: "sleep_drain.DrainStop | None" = None, engine_label: str | None = None,
                      auto_continue: dict | None = None) -> dict | None:
    """The sidecar (``sleep_paused``): written at the start of a run, after every batch
    commit and at each stop. Never raises — bookkeeping must not fail a run."""
    from api.services import sleep_paused

    try:
        rec = sleep_paused.build(ds, phase=phase, stop=stop, engine_label=engine_label,
                                 auto_continue=auto_continue)
        rec["can_continue"] = True
        sleep_paused.save(memory_path, rec)
        return rec
    except Exception as e:  # noqa: BLE001
        logger.warning(f"run record not written: {type(e).__name__}: {e}")
        return None


async def _drain(
    settings: Settings, cycle_id: str, memory_path: Path, *, user_triggered: bool,
    continue_from: dict | None = None, only_ids: list[str] | None = None,
) -> _StageOutcome:
    """A run that reads everything that was waiting when it began (owner,
    2026-09-29 — "it's just progress that cicada has to go through"; scheduled runs too
    since 2026-09-30, TODO ruling 16).

    Freeze the waiting ids, resolve the engine once, then loop: pick the next
    batch of still-waiting frozen ids, run the whole pipeline on them and let Stage 5
    file and commit them, so a cancel or a plan stop loses at most the batch in
    progress and Continue resumes with what is left. Episodes that arrive mid-run wait
    for the next run; an id another writer marked processed meanwhile is counted as
    skipped. A conversation that fails for its own reasons gets one more try in the
    very next batch and is then parked (``sleep_parked``); a failure that is the
    ENGINE's (signed out, throttled) stops the run and is never counted against it.

    ``continue_from`` resumes a paused run (same run id, counters carried);
    ``only_ids`` freezes exactly those ids (Retry on parked conversations).

    Once per drain, in the batch that empties the queue: temporal decay (both
    engines — TODO ruling 1: charged once, not once per batch) and Stage 5.57's
    page reads. Once per run, in ``run``'s tail: everything engine-independent.
    The returned outcome is the LAST ATTEMPTED batch's, so the tail's guard
    (``committed`` / ``write_started`` / ``questions_refreshed``) reads what the
    tree is really like now and never an earlier batch's clean commit.
    """
    from api.services import agent_engine, engine_select, sleep_debt, sleep_paused, sleep_parked
    from api.services import sleep_progress, sleep_run_prefs

    try:
        from api.services.connections.registry import get_registry

        registry = get_registry(settings)
    except Exception:  # noqa: BLE001 - a settings stand-in with no registry reads the defaults
        registry = None
    opts = sleep_run_prefs.load(registry) if registry is not None else sleep_run_prefs.RunOptions()
    size = sleep_run_prefs.effective_batch_size(opts, settings)

    parked_map = sleep_parked.valid(memory_path)
    parked_now = set(parked_map)
    waiting_map = sleep_progress.unprocessed_ids(memory_path)
    queue = [e["id"] for e in _get_unprocessed_episodes(memory_path, with_body=False)]
    if continue_from:
        ids = [str(i) for i in continue_from.get("frozen_ids") or []]
        remaining = [i for i in ids if i in waiting_map and i not in parked_now]
    elif only_ids is not None:
        want = set(only_ids)
        ids = [i for i in queue if i in want]
        remaining = ids
    else:
        ids = [i for i in queue if i not in parked_now]
        remaining = ids
    if user_triggered and not continue_from:
        # A fresh run replaces any paused one (no-body trigger); the replaced run is ended in
        # Past nights too, its open pause closed, never left 'paused' forever.
        _drop_paused_record(memory_path)
    if not remaining:
        if continue_from:
            _drop_paused_record(memory_path)   # a Continue with nothing left ends the run
        logger.info("No unprocessed episodes found — skipping")
        _state.progress = "No unprocessed episodes"
        return _StageOutcome()

    ds = sleep_drain.DrainState(
        drain_id=(str(continue_from["run_id"]) if continue_from else cycle_id),
        frozen_ids=ids, batch_size=size,
        started_by="user" if user_triggered else "schedule",
        continue_after_reset=bool(opts.continue_after_reset and user_triggered),
        reserve_pct=opts.reserve_pct,
    )
    ds.memory_path = memory_path
    ds.origin_of = sleep_progress.origin_of_ids(memory_path, ids)
    ds.parked = {i: str((parked_map.get(i) or {}).get("reason") or "other") for i in ids if i in parked_now}
    ds.settled = set(ds.parked)
    if continue_from:
        now_wall = time.time()
        ds.resumed = True
        ds.first_run = bool(continue_from.get("first_run"))
        ds.committed_batches = int(continue_from.get("committed_batches") or 0)
        # A batch that was discarded (a pause before it filed) is read again as its own number:
        # numbering continues from what was committed, so no `(drain_id, batch)` repeats in the ledger.
        ds.batch = ds.committed_batches
        ds.filed = int(continue_from.get("filed") or 0)
        ds.calls = int(continue_from.get("calls") or 0)
        ds.requeued_ids = {str(i) for i in continue_from.get("requeued_ids") or []}
        ds.requeued = int(continue_from.get("requeued") or len(ds.requeued_ids))
        ds.skipped = int(continue_from.get("skipped") or 0)
        ds.decay_ran = bool(continue_from.get("decay_ran"))
        ds.attempts = {str(k): int(v) for k, v in (continue_from.get("attempts") or {}).items()}
        ds.totals.update({k: int(v) for k, v in (continue_from.get("totals") or {}).items()
                          if k in sleep_drain.CUMULATIVE_COUNTERS})
        ds.owner_beliefs = continue_from.get("owner_beliefs")
        pause_span_ms = max(0, int((now_wall - float(continue_from.get("paused_at_ts") or now_wall)) * 1000))
        ds.paused_ms = int(continue_from.get("paused_ms") or 0) + pause_span_ms
        ds.started_mono = time.monotonic() - int(continue_from.get("elapsed_ms") or 0) / 1000.0
        # Settled is never persisted: whatever is processed now is filed (a stale record can
        # only make ``filed`` low, never re-read filed work).
        ds.filed_ids = {i for i in ids if i not in waiting_map and i not in parked_now}
        ds.settled |= ds.filed_ids
        ds.filed = max(ds.filed, len(ds.filed_ids))
    else:
        try:
            ds.first_run = (await sleep_debt._last_cycle_at(memory_path)) is None
        except Exception:  # noqa: BLE001
            ds.first_run = False
        _sample_owner(ds, memory_path, "at_start")
    ds.batches = ds.batch + sleep_drain.batches_for(len(remaining), size)
    ds.new_since = sleep_progress.new_since_by_origin(
        {i: o for i, o in waiting_map.items() if i not in parked_now}, set(ids))
    ds.arrived_since = sum(ds.new_since.values())
    _state.drain = ds
    _state.episodes_queued = len(ids)
    _state.episode_cap = size
    by_origin: dict[str, int] = {}
    read_origin: dict[str, int] = {}
    for i in ids:
        o = ds.origin_of.get(i, "unknown")
        by_origin[o] = by_origin.get(o, 0) + 1
        if i in ds.filed_ids:
            read_origin[o] = read_origin.get(o, 0) + 1
    _state.queue_by_origin = by_origin
    _state.read_by_origin = read_origin
    logger.info(f"Drain {ds.drain_id}: {len(ids)} episodes frozen ({len(remaining)} to read), "
                f"{ds.batches} batch(es) of up to {size}")

    # Resolved ONCE and pinned: "Auto" must not flip to another (paid) engine at batch 9.
    resolved = await engine_select.resolve_settings(settings, user_triggered=user_triggered)
    pinned = memory_path
    engine_lbl = _engine_label(resolved[0])
    ds.engine_label = engine_lbl
    try:
        ds.engine_model = engine_select.author_model(resolved[0])
    except Exception:  # noqa: BLE001 - a settings stand-in names no model
        ds.engine_model = None
    if continue_from:
        ds.auto_used = sleep_paused.auto_used(continue_from)
    if ds.reserve_pct and engine_lbl in engine_select.PLAN_ENGINES:
        ds.guard = sleep_reserve.ReserveGuard(ds.reserve_pct, engine=engine_lbl)
        if engine_lbl == "claude-cli" and hasattr(resolved[0], "model_copy"):
            # With a reserve set, the reserve is the line: R-E12's own 90% stop would pre-empt a 5% one.
            resolved = (resolved[0].model_copy(update={"agent_stop_utilization": 1.0}), resolved[1])
        if engine_lbl == "claude-cli":
            # Only the Claude plan's own last window seeds its guard: a ChatGPT-plan run must never
            # pause (or arm an automatic continue) on another plan's usage.
            try:
                from api.services import cycle_usage, telemetry

                last = cycle_usage.last_cycles(bank=telemetry.bank_name(settings)).get("claude-plan") or {}
                ds.guard.seed_last_known(last.get("window"), last.get("used_fraction"), last.get("resets_at"))
            except Exception:  # noqa: BLE001 - a seed for the first batch, never worth failing a run
                pass
    else:
        ds.reserve_pct = None
    _write_run_record(ds, memory_path, phase="running", engine_label=engine_lbl)
    _record_leg(ds, memory_path, "running")
    try:
        inbox_at_start = {f.stem for f in bank_index.files(memory_path, "inbox")}
    except Exception:  # noqa: BLE001
        inbox_at_start = None

    last = _StageOutcome()
    stop: "sleep_drain.DrainStop | None" = None

    def _park(i: str, reason: str) -> None:
        ds.parked[i] = reason
        ds.settled.add(i)
        ds.unread.pop(i, None)
        try:
            sleep_parked.park(memory_path, i, reason, ds.attempts.get(i, 2))
        except Exception as e:  # noqa: BLE001
            logger.warning(f"parking {i} failed: {type(e).__name__}: {e}")

    def _fold(outcome: _StageOutcome, batch_ids: list[str], *, decays: bool, links: bool) -> None:
        """Count a finished batch, or let a discarded one leave no trace."""
        if outcome.committed:
            ds.committed_batches += 1
            ds.filed += _state.episodes_processed
            for name in sleep_drain.CUMULATIVE_COUNTERS:
                if name != "episodes_requeued":   # distinct ids below: a retried id is one, not two
                    ds.totals[name] = ds.totals.get(name, 0) + int(getattr(_state, name, 0) or 0)
            ds.filed_ids |= outcome.filed_ids
            ds.settled |= outcome.filed_ids
            for i in outcome.filed_ids:
                ds.unread.pop(i, None)
            ds.requeued_ids |= set(outcome.unread) | ds.live.engine_failed | ds.live.skipped
            ds.requeued = len(ds.requeued_ids - ds.filed_ids)
            ds.totals["episodes_requeued"] = ds.requeued
            if decays:
                ds.decay_ran = True
            if links:
                ds.links_ran = True
        # A conversation that failed for its own reasons: one more try, then parked. The
        # engine's trouble (pause class) is never counted — it stops the run instead.
        for i, reason in outcome.unread.items():
            n = ds.attempts.get(i, 0) + 1
            ds.attempts[i] = n
            if n >= sleep_drain.MAX_ATTEMPTS:
                _park(i, reason)
            else:
                ds.unread[i] = reason
        ds.batch_counted = True

    while True:
        # Between batches, and while the next one only reads episodes and calls the
        # engine, no page is held (`is_writing`); Stage 2 of the batch opens the window.
        _state.writing = False
        if getattr(settings, "memory_path", pinned) != pinned:
            stop = sleep_drain.DrainStop(
                "bank_switched",
                f"The memory bank changed — stopped after batch {ds.committed_batches} of {ds.batches}; "
                "what was already filed stays filed.")
            break
        waiting_map = sleep_progress.unprocessed_ids(memory_path)
        waiting = set(waiting_map)
        parked_all = sleep_parked.ids(memory_path)
        ds.new_since = sleep_progress.new_since_by_origin(
            {i: o for i, o in waiting_map.items() if i not in parked_all}, set(ids))
        gone = {i for i in ids if i not in ds.settled and i not in waiting}
        ds.skipped += len(gone)
        ds.skipped_ids |= gone
        ds.settled |= gone
        batch_ids, more = sleep_drain.next_batch_retrying(ids, waiting, ds.settled, size, ds.attempts)
        if not batch_ids:
            ds.finished = True   # a cancel that came too late has nothing left to stop
            break
        if _state.cancel_requested:
            stop = sleep_drain.DrainStop("cancelled")
            break
        if ds.guard is not None and ds.guard.is_reached():
            resets, kind = ds.guard.stop_values()
            stop = sleep_drain.DrainStop("reserve", sleep_reserve.SENTENCE, resets, kind)
            break

        ds.batch += 1
        ds.batches = ds.batch + sleep_drain.batches_for(more, size)
        is_last = more == 0
        before_read, before_total = dict(_state.read_by_origin), _state.episodes_total
        _reset_batch_counters()
        ds.batch_counted = False
        ds.live = sleep_drain.BatchLive(index=ds.batch, total=len(batch_ids), ids=list(batch_ids))
        _state.episodes_total = min(ds.frozen, ds.filed + ds.requeued + ds.skipped + len(batch_ids))
        plan = BatchPlan(
            # The once-per-drain work runs in the batch that empties the queue — and only once,
            # even when a retry batch follows a last batch that had failures.
            only_ids=batch_ids, resolved=resolved, decay=is_last and not ds.decay_ran,
            links=is_last and not ds.links_ran,
            keep_cancel=not is_last,
            label=f"Batch {ds.batch} of {ds.batches} · " if ds.batches > 1 else "",
            index=ds.batch, of=ds.batches, drain_id=ds.drain_id, ds=ds,
        )
        last = await _run_batch(
            settings, f"{cycle_id}_b{ds.batch:03d}", memory_path, user_triggered=user_triggered, batch=plan)
        if not last.committed:
            _state.read_by_origin, _state.episodes_total = before_read, before_total
        _fold(last, batch_ids, decays=plan.decay, links=plan.links)
        if last.committed and ds.owner_beliefs is not None and ds.owner_beliefs.get("after_first_batch") is None:
            _sample_owner(ds, memory_path, "after_first_batch")
        if last.committed:
            _write_run_record(ds, memory_path, phase="running", engine_label=engine_lbl)

        if last.stop is not None:
            stop = last.stop
            if stop.reason == "reserve" and not any(
                    i not in ds.settled and i in waiting for i in ids if i not in last.filed_ids):
                stop = None      # the line was reached with nothing left to read: a finished run
            else:
                break
        if last.committed and (last.breaker or last.pause_class):
            # Stage 1 swallows a throttle (or a sign-out) per episode, so some of the batch was
            # read and filed; the breaker and the classified failures are the only signal left.
            # Stop here rather than start a batch that spawns, fails again and stops one batch
            # late — but only when frozen ids are still waiting beyond this batch. A last batch
            # is a finished run: what it could not read stays queued for the next one, the note
            # is logged, and the tail's link backfill still runs.
            left = set(sleep_progress.unprocessed_ids(memory_path))
            own = set(batch_ids)
            if not is_last and any(i not in ds.settled and i in left and i not in own for i in ids):
                if last.breaker:
                    stop = sleep_drain.DrainStop("plan_limit", last.breaker, last.breaker_resets_at,
                                                 last.breaker_kind or "unknown")
                else:
                    stop = sleep_drain.DrainStop(
                        "engine", last.pause_sentence or "The engine stopped answering; what was read is filed.")
                break
            ds.settled |= set(ds.live.engine_failed)   # requeued for the next run, as a plain cycle does
            logger.info(f"Drain {ds.drain_id}: engine note after the last batch (nothing left waiting): "
                        f"{last.breaker or last.pause_sentence}")
        if not last.committed and not last.unread:
            # Nothing filed and nothing wrong: every id was read elsewhere between the
            # scan and the load. Settled, counted, never re-read.
            ds.skipped += len(batch_ids)
            ds.skipped_ids |= set(batch_ids)
            ds.settled |= set(batch_ids)

    if stop is None and ds.committed_batches and not ds.decay_ran:
        # The batch planned as last read nothing (its ids were read elsewhere
        # mid-run), so decay and the page reads have not run: one pass without
        # episodes gives them their once.
        before_read, before_total = dict(_state.read_by_origin), _state.episodes_total
        _reset_batch_counters()
        ds.batch_counted = False
        ds.live = sleep_drain.BatchLive(index=ds.batch, total=0)
        plan = BatchPlan(
            only_ids=[], resolved=resolved, decay=True, links=True, keep_cancel=False,
            label="Finishing · ", index=ds.batch, of=ds.batches, drain_id=ds.drain_id, decay_only=True, ds=ds,
        )
        last = await _run_batch(
            settings, f"{cycle_id}_decay", memory_path, user_triggered=user_triggered, batch=plan)
        if not last.committed:
            _state.read_by_origin, _state.episodes_total = before_read, before_total
        _fold(last, [], decays=True, links=True)
        stop = last.stop

    try:
        now_waiting = sleep_progress.unprocessed_ids(memory_path)
        ds.arrived_since = len({i for i, _ in now_waiting.items()} - set(ids) - set(sleep_parked.ids(memory_path)))
    except Exception:  # a count for the sentence, never worth failing a run
        ds.arrived_since = None
    _sample_owner(ds, memory_path)

    if stop is not None:
        _apply_drain_stop(ds, stop)
    elif not ds.committed_batches:
        _state.progress = "No unprocessed episodes" if not ds.parked else (
            f"Could not read {len(ds.parked)} conversation(s)")
        _state.cancel_requested = False
    else:
        _state.cancel_requested = False
        requeue_note = _requeue_note(ds.requeued, None)
        warn = f" (with warnings: {_state.index_warning})" if _state.index_warning else ""
        _state.progress = (
            f"Completed — {ds.filed} episode(s) filed in {ds.committed_batches} batch(es)"
            f"{requeue_note}{warn}"
        )
        logger.success(f"Drain {ds.drain_id} completed — {ds.filed} episodes filed in {ds.committed_batches} batch(es)")
    ds.active = False
    ds.ended_mono = time.monotonic()
    _settle_run_record(ds, memory_path, stop, engine_lbl, settings)
    questions_leg = None
    if inbox_at_start is not None:
        try:
            questions_leg = len({f.stem for f in bank_index.files(memory_path, "inbox")} - inbox_at_start)
        except Exception:  # noqa: BLE001
            questions_leg = None
    _record_leg(ds, memory_path, _run_state(ds, stop), stop=stop, questions_leg=questions_leg)
    return _StageOutcome(
        committed=last.committed, questions_refreshed=last.questions_refreshed,
        skip_links=bool(stop is not None and stop.reason in ("plan_limit", "reserve")),
    )


def _drop_paused_record(memory_path: Path) -> None:
    """Forget the paused record without continuing it, and end that run's summary
    (``sleep_runs.close_open_pause``). Never raises past its own guard."""
    from api.services import sleep_paused, sleep_runs

    old = sleep_paused.load(memory_path)
    sleep_paused.clear(memory_path)
    if old and old.get("run_id"):
        try:
            sleep_runs.close_open_pause(memory_path, str(old["run_id"]))
        except Exception as e:  # noqa: BLE001 - a summary for Past nights, never worth failing a run
            logger.warning(f"run summary not closed: {type(e).__name__}: {e}")


def _run_state(ds: "sleep_drain.DrainState", stop: "sleep_drain.DrainStop | None") -> str:
    from api.services import sleep_paused

    if stop is None:
        return "finished"
    if sleep_paused.reason_for(stop) is None:
        return "failed"
    still = [i for i in ds.frozen_ids if i not in ds.filed_ids and i not in ds.skipped_ids and i not in ds.parked]
    return "paused" if still else "finished"


def _record_leg(ds: "sleep_drain.DrainState", memory_path: Path, state: str, *, stop=None,
                questions_leg: int | None = None) -> None:
    from api.services import sleep_paused, sleep_runs

    try:
        sleep_runs.record_leg(memory_path, ds, state=state, stop=stop,
                              reason=sleep_paused.reason_for(stop) if stop is not None else None,
                              questions_leg=questions_leg)
    except Exception as e:  # noqa: BLE001 - a summary for Past nights, never worth failing a run
        logger.warning(f"run summary not written: {type(e).__name__}: {e}")


def _settle_run_record(ds: "sleep_drain.DrainState", memory_path: Path,
                       stop: "sleep_drain.DrainStop | None", engine_lbl: str | None, settings) -> None:
    """Leave the sidecar as the run ended: gone when it finished (or failed), a paused
    record when a pause reason stopped it with conversations still waiting — and the
    opt-in continue-after-reset armed when its guards allow (TODO ruling 15)."""
    from api.services import sleep_autocontinue, sleep_paused

    try:
        reason = sleep_paused.reason_for(stop) if stop is not None else None
        if reason is None:
            sleep_paused.clear(memory_path)
            return
        still = [i for i in ds.frozen_ids if i not in ds.filed_ids and i not in ds.skipped_ids
                 and i not in ds.parked]
        if not still:
            sleep_paused.clear(memory_path)
            return
        rec = sleep_paused.build(ds, phase="paused", stop=stop, engine_label=engine_lbl)
        rec["can_continue"] = True
        rec["auto_continue"] = sleep_autocontinue.arm(settings, memory_path, rec, ds)
        sleep_paused.save(memory_path, rec)
    except Exception as e:  # noqa: BLE001 - bookkeeping must not fail a run
        logger.warning(f"paused record not written: {type(e).__name__}: {e}")


def _sync_vector_indexes(memory_path: Path) -> list[str]:
    """Sync the entity, episode and claims vector indexes; blocking, so the
    cycle calls it through ``asyncio.to_thread``. Returns one warning per
    failed step — never raises."""
    warnings: list[str] = []
    try:
        from api.services.vector_index import SqliteVecIndexer
        indexer = SqliteVecIndexer(memory_path)
    except Exception as e:
        warning = f"vector indexer init failed: {type(e).__name__}: {e}"
        logger.warning(warning)
        return [warning]

    # M5e: the claims index is derived from the in-page ```claims blocks so
    # claim-first /ask + get_perspective reflect the post-Sleep belief state.
    # Only currently-valid claims are indexed.
    for label, step in (
        ("entity", indexer.index_entities),
        ("episode", indexer.index_episodes),
        ("claims", indexer.index_claims),
    ):
        try:
            step()
        except Exception as e:
            warning = f"{label} index rebuild failed: {type(e).__name__}: {e}"
            logger.warning(f"vector {warning}")
            warnings.append(warning)
    return warnings


def _ae_breaker() -> str | None:
    from api.services import agent_engine

    return agent_engine.breaker_reason()


def _batch_hooks(live: "sleep_drain.BatchLive", guard) -> dict:
    """Stage 1's per-conversation hooks for a drain's batch: what started, what was
    read, what failed and whether that was the conversation's or the engine's, what
    the reserve line stopped from starting."""
    def started(ep: dict) -> None:
        live.started.add(ep["id"])

    def read(ep: dict) -> None:
        live.read.add(ep["id"])

    def failed(ep: dict, exc: BaseException) -> None:
        kind, reason = sleep_drain.classify_episode(exc)
        if kind == "pause":
            live.engine_failed.add(ep["id"])
            live.pause_class = True
            live.pause_sentence = live.pause_sentence or str(exc).strip()[:300]
        else:
            live.failed[ep["id"]] = reason or "other"

    def skipped(ep: dict) -> None:
        live.skipped.add(ep["id"])

    hooks = {"on_episode_started": started, "on_episode_read": read,
             "on_episode_failed": failed, "on_episode_skipped": skipped}
    if guard is not None:
        hooks["stop_check"] = guard.is_reached
    return hooks


def _sort_progress(live: "sleep_drain.BatchLive"):
    def cb(done: int, total: int) -> None:
        live.sort_done, live.sort_total = int(done), int(total)
    return cb


def _decide_progress(live: "sleep_drain.BatchLive"):
    def cb(done: int, total: int) -> None:
        live.decide_done, live.decide_total = int(done), int(total)
    return cb


async def _run_stages(
    settings: Settings, cycle_id: str, memory_path: Path, *, user_triggered: bool = True,
    batch: BatchPlan | None = None,
) -> _StageOutcome:
    """The LLM-dependent pipeline. Returns what it achieved; never runs the tail.

    ``batch`` (a drain's batch, ``_drain``): reads only ``batch.only_ids`` with
    the engine the drain resolved once, skips the cap (the drain owns the queue's
    counters), runs the once-per-drain work (decay, Stage 5.57's page reads) only
    when the plan says so, and prefixes its progress sentence. Everything else —
    every stage, Stage 5's write, the commit — is the cycle as it always was.
    """
    label = batch.label if batch is not None else ""
    ds = batch.ds if batch is not None else None
    live = ds.live if ds is not None else None
    guard = getattr(ds, "guard", None) if ds is not None else None
    decay_only = bool(batch is not None and batch.decay_only)
    # Only ever a kwarg when False: tests stub these seams with fixed signatures.
    decay_kw = {} if (batch is None or batch.decay) else {"decay": False}

    def _say(text: str) -> None:
        _state.progress = f"{label}{text}"

    # M5e: ensure the runtime predicate-normalization map exists (idempotent,
    # non-clobbering) so Stage 2 predicate folding + Stage 3 cardinality keying
    # have a controlled vocabulary to key on.
    try:
        from api.services import predicates
        predicates.install_predicate_map(memory_path)
    except Exception as e:
        logger.warning(f"predicate map install skipped: {type(e).__name__}: {e}")

    # Collect unprocessed episodes
    if batch is None:
        episodes = _get_unprocessed_episodes(memory_path)
    elif decay_only:
        episodes = []
    else:
        episodes = _get_unprocessed_episodes(memory_path, only_ids=set(batch.only_ids))
    if not episodes and not decay_only:
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
    if batch is None:
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

        # G125: what this cycle will read, by source — set once, from the capped
        # slice, so the study list's denominators never move mid-cycle.
        by_origin: dict[str, int] = {}
        for ep in episodes:
            by_origin[str(ep.get("origin") or "unknown")] = by_origin.get(str(ep.get("origin") or "unknown"), 0) + 1
        _state.queue_by_origin = by_origin
    _state.batch_total = len(episodes)

    # Fix round 1, M1 (part 2): resolution moved to AFTER the idle-episode
    # return above — an idle cycle must never touch the connections registry
    # at all, not even the bounded cache-first probe. "auto" (and a default
    # install with the Use-for-Sleep toggle on) can shell out to vendor CLIs
    # on a cold cache, so it is resolved ONCE here, only on a cycle with real
    # work, and the concrete mode travels down as a copy for the rest of this
    # pipeline. The caller's Settings is never mutated: get_settings() is
    # lru_cached and shared with every request handler.
    from api.services import engine_select
    if batch is None:
        settings, engine_why = await engine_select.resolve_settings(
            settings, user_triggered=user_triggered,
        )
    else:
        # A drain resolves once and pins the pair: "Auto" must not land on
        # another (paid) engine at batch 9.
        settings, engine_why = batch.resolved
    _state.last_engine = _engine_label(settings)
    _state.engine_detail = engine_why
    if _state.last_engine == "codex-cli" and not decay_only:
        # The ChatGPT plan reports no per-call usage: bracket the cycle with two
        # snapshots so the ledger can say how far its window moved.
        from api.services import cycle_usage
        await cycle_usage.begin_codex(cycle_id)
    logger.info(
        f"Sleep cycle {cycle_id} started — engine: {_state.last_engine}, "
        f"model: {engine_select.author_model(settings)}"
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
    if decay_only:
        pass   # no episode is read, so no engine is asked
    elif _state.last_engine == "claude-cli":
        ok, detail = await _probe_engine_cheaply(settings)
        _state.engine_detail = detail
        if not ok:
            logger.error(f"Sleep cycle {cycle_id} aborted before Stage 1 — {detail}")
            _state.error = detail
            _state.progress = f"Failed: {detail}"
            return _StageOutcome(stop=sleep_drain.DrainStop("engine", detail))
    elif _state.last_engine == "codex-cli":
        # R-E18: one read-only `codex app-server` probe (≈0.5 s, no quota)
        # answers signed-in, plan-vs-API-key and "limit already reached"
        # BEFORE the first spawn, and names the plan's current default model
        # when the person never picked one (R-E17) — every call this cycle
        # then passes an explicit `-m`, and the Cicada-Author trailer is a
        # real id that came from model/list, never from this file.
        from api.services import codex_engine

        ok, detail, default_model = await codex_engine.preflight()
        _state.engine_detail = detail
        if not ok:
            logger.error(f"Sleep cycle {cycle_id} aborted before Stage 1 — {detail}")
            _state.error = detail
            _state.progress = f"Failed: {detail}"
            from api.services import plan_limits

            # A used-up plan is a pause the person waits out; a sign-out is not. The
            # snapshot's own reset time rides along so the app can lift the pause when it passes.
            if detail.startswith(plan_limits.CODEX_LIMIT_LEAD):
                return _StageOutcome(stop=sleep_drain.DrainStop(
                    "plan_limit", detail, codex_engine.last_limit_resets_at()))
            return _StageOutcome(stop=sleep_drain.DrainStop("engine", detail))
        if default_model and not (getattr(settings, "codex_model", "") or "").strip():
            settings = settings.model_copy(update={"codex_model": default_model})
            # The "started" line above logged before this was known.
            logger.info(f"Sleep cycle {cycle_id} — ChatGPT plan default model: {default_model}")
        if guard is not None:
            # The reserve line, read from the snapshot this pre-flight already took (no second probe).
            guard.observe_snapshot(codex_engine.last_snapshot())

    # Stage 1: Entity & Relationship Extraction
    _say(f"Stage 1/5: Extracting entities from {len(episodes)} episodes...")
    logger.info(f"Stage 1: Extracting entities from {len(episodes)} episodes")
    from api.services.entity_extractor import extract

    def _tick_stage1() -> None:
        _state.stage1_progress += 1

    def _on_episode_done(ep: dict) -> None:
        origin = str(ep.get("origin") or "unknown")
        _state.read_by_origin[origin] = _state.read_by_origin.get(origin, 0) + 1

    reserve_stop = None
    if guard is not None and guard.is_reached() and not decay_only:
        # Still past the line before a single paid read (a Continue into a window that is
        # still full, or the ChatGPT snapshot the pre-flight just took): pause at once.
        resets, kind = guard.stop_values()
        return _StageOutcome(stop=sleep_drain.DrainStop("reserve", sleep_reserve.SENTENCE, resets, kind))

    if decay_only:
        extracted = []
    else:
        hooks: dict = {}
        if live is not None:
            hooks = _batch_hooks(live, guard)
        extracted = await extract(
            episodes, settings, cancel_check=_cancel_requested,
            progress_callback=_tick_stage1, on_episode_done=_on_episode_done,
            **(_accepting(extract, **hooks) if hooks else {}),
        )
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

    # A drain's per-conversation outcomes (Sleep page v5): who could not be read and why,
    # and whether the ENGINE is what failed (never counted against a conversation).
    unread_content: dict[str, str] = {}
    pause_class = False
    pause_sentence: str | None = None
    if live is not None and not decay_only:
        got = {r["episode_id"] for r in extracted if r.get("episode_id")}
        for ep in episodes:
            i = ep["id"]
            if i in got or i in live.skipped or i in live.engine_failed:
                continue
            if i not in live.failed and _ae_breaker():
                # No hook named it, but the plan's breaker tripped in this batch: the engine's trouble.
                live.engine_failed.add(i)
                live.pause_class = True
                live.pause_sentence = live.pause_sentence or _ae_breaker()
                continue
            unread_content[i] = live.failed.get(i, "other")   # no hook fired (a stub): unknown, content-class
        pause_class, pause_sentence = live.pause_class, live.pause_sentence
    if guard is not None and guard.is_reached() and not decay_only:
        resets, kind = guard.stop_values()
        reserve_stop = sleep_drain.DrainStop("reserve", sleep_reserve.SENTENCE, resets, kind)

    # Resumable queue — hard stop if EVERY episode failed Stage 1 (wrong
    # model id, exhausted credits, total outage). Abort with the queue
    # untouched instead of running the rest of the pipeline on nothing and
    # committing a misleading empty "completed" cycle. Re-running after
    # fixing the cause retries the whole batch.
    if episodes and not extracted and reserve_stop is not None and not pause_class and not _ae_breaker():
        # Nothing was read because the reserve line said stop, not because anything failed.
        return _StageOutcome(stop=reserve_stop, unread={
            i: r for i, r in unread_content.items() if i in live.failed} if live is not None else {})
    if (episodes and not extracted and live is not None and not pause_class and not _ae_breaker()
            and unread_content and all(i in live.failed for i in unread_content)
            # An unrecognised failure on EVERY conversation is far likelier the engine's (an
            # outage, a bad model parameter) than each conversation's: that falls through to the
            # engine stop below — nothing parked, no attempt counted, the queue left as it was.
            and "other" not in unread_content.values()):
        # Every conversation failed for ITS OWN reasons (empty answers, timeouts): not an
        # engine failure — nothing to commit, no error, each one gets its retry or is parked.
        _state.progress = f"{label}Could not read {len(unread_content)} conversation(s)"
        return _StageOutcome(unread=unread_content)
    if episodes and not extracted:
        msg = _stage1_failure_message(_state.last_engine or "litellm", _state.engine_detail)
        # Fix round 1, L2: `engine_detail` is now set on EVERY resolved
        # cycle (Task 7), not just an agent-rung pre-flight abort — a plain
        # byok install's `engine_detail` is just "why we're on byok"
        # ("no Sleep engine chosen…"), not a diagnosis of a Stage-1 API
        # failure, so appending it here read as confusing noise on an
        # install that never chose an engine at all. Only the claude-cli
        # rung's detail (the pre-flight probe's own sentence, e.g. "signed
        # out — run `claude auth login`") is actually diagnostic.
        if _state.last_engine in engine_select.PLAN_ENGINES and _state.engine_detail:
            msg = f"{msg} ({_state.engine_detail})"
        logger.error(msg)
        _state.error = msg
        _state.progress = f"Failed: {msg}"
        from api.services import agent_engine as _ae

        breaker = _ae.breaker_reason()
        return _StageOutcome(stop=(
            sleep_drain.DrainStop("plan_limit", breaker, _ae.breaker_resets_at(), _ae.breaker_kind()) if breaker
            else sleep_drain.DrainStop("engine", msg)))

    # Stage 2: Entity Resolution & Deduplication
    _say("Stage 2/5: Resolving entities...")
    logger.info("Stage 2: Resolving entities against existing graph")
    if batch is not None:
        _state.writing = True   # the pages Stage 5 rewrites are read from here (see `is_writing`)
    existing = _load_existing_entities(memory_path)
    from api.services.entity_resolver import resolve
    if decay_only:
        resolved_result = {"changes": [], "relationships": [], "episode_cooccurrences": {}, "name_to_id": {}}
    else:
        resolved_result = await resolve(
            extracted, existing, settings, cancel_check=_cancel_requested,
            **(_accepting(resolve, progress_callback=_sort_progress(live)) if live is not None else {}))
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
    _say("Stage 3/5: Resolving conflicts...")
    logger.info("Stage 3: Conflict resolution & temporal decay")
    from api.services.conflict_resolver import resolve_and_prune
    changes = await resolve_and_prune(
        resolved_changes, existing, settings, **decay_kw,
        # A pause must be able to land between pages (each is a paid call), and the strip counts them.
        **(_accepting(resolve_and_prune, cancel_check=_cancel_requested,
                      progress_callback=_decide_progress(live)) if live is not None else {}))
    logger.info(f"Stage 3 complete: {len(changes)} total changes")
    _state.stage = 3

    # Sleep control — safe point: Stage 3 makes an engine call or two per page it
    # updates (and stops between pages on a cancel) but writes nothing — still nothing on disk.
    if _state.cancel_requested:
        return _cycle_cancelled()

    # Stage 4: Pattern Detection & Skill Extraction
    _say("Stage 4/5: Extracting skills...")
    logger.info("Stage 4: Pattern detection & skill extraction")
    from api.services.skill_extractor import detect_patterns
    if decay_only:
        skills = []
    else:
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
    _say("Stage 5/5: Writing changes...")
    logger.info("Stage 5: Writing entities, nudges, clarifications, and relationships")
    # Fix round 1, M3: the FIRST real disk write in the pipeline — everything
    # before this point (Stages 1-4) only computed `changes` in memory. Flip
    # this before the write so a raised exception anywhere from here through
    # `_finalize`'s commit correctly marks the tree as an at-risk one for the
    # tail's connector-poll gate, even though the exception means `_run_stages`
    # never reaches a `return` to report it via `_StageOutcome`.
    _state.write_started = True
    from api.services.inbox_generator import DecayBudget, generate
    # One allowance of NEW decay questions for the whole cycle, drawn on by the
    # entity path here and the claim path in Stage 5.56 (the cap is a setting).
    decay_budget = DecayBudget(getattr(settings, "decay_inbox_cap_per_cycle", 10))
    await generate(changes, skills, memory_path, relationships=resolved_edges,
                   decay_budget=decay_budget)

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
        claim_result = run_claim_pipeline(
            extracted, existing, memory_path, settings,
            # G141 PJ-0: Stage 2's own map, so a claim lands where its edge did.
            name_to_id=resolved_result.get("name_to_id"),
            **decay_kw,
        )
        _state.claims_page_less = int(claim_result.get("claims_page_less", 0) or 0)
        _state.subjects_page_less = int(claim_result.get("subjects_skipped", 0) or 0)
        _state.claims_held = int(claim_result.get("claims_held", 0) or 0)
        _state.claims_released = int(claim_result.get("claims_released", 0) or 0)
        _state.claims_hold_capped = int(claim_result.get("claims_hold_capped", 0) or 0)
        _state.claims_waiting = int(claim_result.get("claims_waiting", 0) or 0)
        nudge_result = write_claim_nudges(
            claim_result.get("nudges", []), memory_path, decay_budget=decay_budget
        )

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
            f"({claim_result.get('claims_page_less', 0)} claim(s) on "
            f"{claim_result.get('subjects_skipped', 0)} page-less subject(s) neither written nor held; "
            f"{claim_result.get('claims_held', 0)} held for a pending name, "
            f"{claim_result.get('claims_released', 0)} released onto their page), "
            f"{nudge_result.get('written', 0)} claim nudges written, "
            f"{nudge_result.get('merged', 0)} merged into open items"
        )
    except Exception as e:
        logger.warning(f"Stage 5.56 claim pipeline failed: {type(e).__name__}: {e}")

    # The decay questions this cycle opened, refreshed or turned away — the cap
    # never drops one silently: a deferred page is still below its threshold and
    # raises again next cycle (see `DecayBudget`).
    _state.decay_nudges_deferred = len(decay_budget.deferred)
    _state.decay_nudges_refreshed = decay_budget.refreshed
    if decay_budget.deferred or decay_budget.refreshed:
        logger.info(
            f"Stage 5: decay questions — {decay_budget.written} opened, "
            f"{decay_budget.refreshed} refreshed (already open), "
            f"{len(decay_budget.deferred)} deferred by the cap of {decay_budget.cap}"
        )

    # Stage 5.6: Regenerate the hub tier + root _index.md from current entities.
    # Deterministic, no LLM; gives small LLMs a filesystem traversal path.
    try:
        from api.services.hub_builder import regenerate_hubs_and_index
        hub_result = regenerate_hubs_and_index(memory_path, settings)
        logger.info(f"Stage 5.6: regenerated {hub_result['hub_count']} hubs + _index.md")
    except Exception as e:
        logger.warning(f"Stage 5.6 hub generation failed: {type(e).__name__}: {e}")

    # Stage 5.57 (M5f): link-enrichment subagent — when a saved media link
    # (e.g. a website a person recommended) lacks a meaningful description,
    # a bounded subagent reads + summarizes it and records a `describes`
    # claim + `recommends` claims, with bidirectional ![[…]] transclusion
    # (m5-prep/link-enrichment.md). The page read is the rail's
    # (`default_fetch`) and only behind CICADA_ALLOW_CONNECTOR_FETCH
    # (G61 phase 2 S0, `_link_summarizer`). Offline-safe, LLM-call-capped;
    # any failure logs a warning and continues — the cycle is never hard-blocked.
    #
    # A drain reads pages once, in its last batch: the pass picks its candidates
    # by scanning the bank (never from `changes`), so nothing an earlier batch
    # saved is missed — only the `recommends` person credit, which reads THIS
    # batch's changes, covers just the last batch's episodes (disclosed).
    if batch is None or batch.links:
        try:
            from api.services.link_enrichment import enrich_media_links
            n_enriched = await enrich_media_links(
                memory_path, changes, settings, summarize_fn=_link_summarizer()
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
    _state.episodes_processed = _mark_episodes_processed(processed_episodes)
    _state.episodes_requeued = requeued
    if requeued:
        logger.warning(
            f"Marked {_state.episodes_processed} episodes processed; {requeued} "
            f"failed extraction and remain queued — re-run Sleep to continue"
        )
    else:
        logger.info(f"Marked {_state.episodes_processed} episodes as processed")

    # Sync the vector indexes so Bookworm reflects the post-sleep state.
    # Entity, episode and claims syncs are independent and we want to surface
    # partial failures: if only the episode index fails, the cycle still
    # wrote the markdown graph, committed, and should report success
    # *with a warning* — not a silent pass, not a hard failure.
    #
    # Off the event loop: embedding is synchronous CPU (and, on a hosted
    # embedder, network) work, and inline it froze every other request for its
    # whole duration. Incremental by content hash — a night embeds what it
    # touched, not the whole history (`SqliteVecIndexer._sync_kind`).
    index_warnings: list[str] = await asyncio.to_thread(_sync_vector_indexes, memory_path)

    # G136: the lexical index, brought up to date beside the vectors —
    # independent of the vector indexer, so a missing embedding model never
    # leaves search's FTS half stale. Incremental: `search_index.refresh` diffs
    # the files' (mtime, size) stamps and re-indexes only what moved (a full
    # build only when the file is missing, damaged or of another schema — it is
    # derived and disposable). Off the event loop; /search keeps answering from
    # the previous snapshot (WAL). Same contract as the vector syncs: a failure
    # is a warning on a cycle that still commits.
    try:
        from api.services import search_index

        await asyncio.to_thread(search_index.refresh, memory_path)
    except Exception as e:
        warning = f"search index refresh failed: {type(e).__name__}: {e}"
        logger.warning(warning)
        index_warnings.append(warning)

    if index_warnings:
        _state.index_warning = "; ".join(index_warnings)

    # Commit
    from api.services import agent_engine, engine_select

    engine = _state.last_engine or "litellm"
    engine_models = agent_engine.models_used()
    plan = engine_select.PLAN_ENGINES.get(engine)
    await _finalize(
        memory_path,
        cycle_id,
        changes,
        settings,
        organic_resolution_paths=organic_resolution_paths,
        # This batch's own clock (`_run_batch`); a plain cycle's is its run's.
        started=_state.batch_started_monotonic or _state.started_monotonic,
        engine=engine,
        # A plan cycle belongs to its plan's card and is billed against the
        # subscription, not as money (PLAN_ENGINES, R-E22).
        connection=plan[0] if plan else None,
        billing=plan[1] if plan else None,
        # The models the engine ACTUALLY used this cycle — the CLI may
        # route an internal side-call to a different model than the one we
        # asked for (V1d), and the trailer should say so.
        authors=engine_models or None,
        sessions=_collect_session_ids(processed_episodes),
        episode_sessions=_episode_session_map(processed_episodes),
        **({} if batch is None else {
            "drain": (batch.drain_id, batch.index, batch.of),
            "subject_suffix": (" (finishing)" if decay_only else
                               f" (batch {batch.index} of {batch.of})" if batch.of > 1 else ""),
        }),
    )

    # Logo warm-up and the connector poll (final-review H1: the poll must
    # run AFTER `_finalize`'s commit so its own `git add -A` finds a clean
    # tree instead of sweeping the cycle's own uncommitted entity writes
    # into a session-less media commit) now live in the engine-independent
    # tail (`_run_engine_independent_tail`), which `run` executes in its
    # `finally` block on every exit path — not just this happy one.

    # R-E12: a plan stop tripped mid-cycle is the cycle's engine detail and
    # the reason in its requeue note — the plan's own sentence and reset time.
    breaker = agent_engine.breaker_reason()
    if breaker:
        _state.engine_detail = breaker
    requeue_note = _requeue_note(_state.episodes_requeued, breaker)
    # Episode cap: `episodes_queued` (the FULL unprocessed count found before
    # capping) > `episodes_total` (what this cycle actually attempted) means
    # the cap truncated this cycle. Surfaced in the progress sentence — same
    # convention `requeue_note` above already uses — so a capped cycle never
    # reads as a complete pass over the whole queue.
    cap_note = (
        f" — episode cap reached: {_state.episodes_total} of "
        f"{_state.episodes_queued} processed, "
        f"{_state.episodes_queued - _state.episodes_total} more queued for the next cycle"
        if batch is None and _state.episodes_queued > _state.episodes_total else ""
    )
    # Sleep control: a cancel that arrived AFTER Stage 5 started writing is
    # too late to stop THIS cycle — by design (see the last safe-point check
    # above) it finishes and commits normally rather than risking a
    # half-written bank. Still worth being honest about in the progress
    # sentence rather than silently swallowing the request.
    cancel_note = ""
    if _state.cancel_requested:
        if batch is None:
            cancel_note = " — cancel requested after writes began; this cycle finished its commit safely"
            _state.cancel_requested = False
        elif not batch.keep_cancel:
            # The drain's last batch: nothing is left to stop.
            _state.cancel_requested = False
        # Any other batch keeps the flag: the drain loop reads it next and stops.
    if _state.index_warning:
        _say(f"Completed with warnings: {_state.index_warning}{requeue_note}{cap_note}{cancel_note}")
        logger.warning(
            f"Sleep cycle {cycle_id} completed with warnings — "
            f"{len(changes)} changes committed; {_state.index_warning}{requeue_note}{cap_note}{cancel_note}"
        )
    else:
        _say(f"Completed{requeue_note}{cap_note}{cancel_note}")
        logger.success(
            f"Sleep cycle {cycle_id} completed — {len(changes)} changes committed"
            f"{requeue_note}{cap_note}{cancel_note}"
        )
    _state.stage = 5
    return _StageOutcome(
        committed=True, questions_refreshed=questions_refreshed,
        filed_ids={ep["id"] for ep in processed_episodes},
        unread=unread_content, pause_class=pause_class, pause_sentence=pause_sentence,
        stop=reserve_stop,
    )


def _get_unprocessed_episodes(
    memory_path: Path, *, only_ids: set[str] | None = None, with_body: bool = True,
) -> list[dict]:
    """Load all episodes with processed: false, sorted by frontmatter timestamp.

    ``only_ids`` keeps just those ids and ``with_body=False`` skips reading each
    body — both filter BEFORE ``f.body()``, so a drain's freeze and its per-batch
    re-scans read frontmatter only and 48 batches never read every waiting body
    48 times.

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
        if only_ids is not None and str(fm.get("id", f.stem)) not in only_ids:
            continue
        content = f.body() if with_body else ""
        results.append({
            "id": fm.get("id", f.stem),
            "content": content,
            # Audit A01: the revision of exactly the text handed to extraction,
            # so retirement never flips a newer capture of the same episode.
            "revision": episode_ids.body_revision(content) if with_body else None,
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
            # R-F2 / R-LS7: whose words a folder file holds, for Stage-1 evidence.
            "evidence_kind": str(fm.get("evidence_kind") or "") or None,
        })
    # Order by INSTANT, not by string (G114 R2): a bank holds legacy
    # naive-local stamps beside `Z` and `+00:00` UTC ones, and a lexical sort
    # across those is off by the machine's offset. Fall back on the id (which
    # begins with the date) for episodes missing a parseable timestamp so the
    # sort is stable regardless of filesystem order.
    results.sort(key=_episode_sort_key)
    return results


def _episode_sort_key(r: dict) -> tuple[str, str]:
    return (episode_ids.timestamp_sort_key(r.get("timestamp")), r["id"])


# Legacy `source` -> G9 `origin` derivation (origin-and-harness-sync.md §1b).
# Track I (D4): `claude`, `claude_memory`, `claude_project`, `chatgpt` and
# `gemini_export` are written ONLY by the chat importer (conversations.py), so
# they derive to the export — not to `claude-code`, which credited a claude.ai
# export's claims to the Claude Code harness. `export_origin_migration` stamps
# the files themselves; this keeps a not-yet-migrated bank right meanwhile.
_SOURCE_TO_ORIGIN = {
    "claude": "claude-export",
    "claude_memory": "claude-export",
    "claude_project": "claude-export",
    "chatgpt": "chatgpt-export",
    "gemini_export": "gemini-export",
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
        source = fm.get("source", "unknown")
        results.append({
            "id": fm.get("id", filepath.stem),
            "timestamp": str(fm.get("timestamp", "") or ""),
            "source": source,
            # G9 origin, same derivation as `_get_unprocessed_episodes` — an
            # explicit `origin:` field if present, else derived from the
            # legacy `source`. Lets the Sleep debt breakdown (and any other
            # consumer of this endpoint) group by the harness-normalized id.
            "origin": fm.get("origin") or _derive_origin(source),
            "title": fm.get("title"),
            "body": parsed.body or "",
            "processed": bool(fm.get("processed", False)),
            # G114 R6: who marked it — "sleep" or an agent/harness name. None
            # for every queued episode and every pre-G114 processed one.
            "processed_by": (str(fm.get("processed_by")) if fm.get("processed_by") else None),
            "filepath": filepath,
            # What a click on the row copies and the day it shows (`episode_copy`, owner 2026-10-05).
            "frontmatter": fm,
        })
    results.sort(key=_episode_sort_key)  # by instant, same key as the cycle's queue (G114 R2)
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


def _mark_episodes_processed(episodes: list[dict]) -> int:
    """Mark episodes as processed in their frontmatter; returns how many.

    Stamps ``processed_by: sleep`` beside the flag (G114 R6) so a
    Sleep-consolidated episode is distinguishable from one an agent marked via
    ``cicada_mark_processed`` (``processed_by: agent`` / the harness name) —
    the two mean different things for what the graph actually received.

    Audit A01: capture keeps running during Sleep, and a resumed session or a
    source-keyed edit rewrites the same episode with ``processed: false``.
    Each file is re-read under ``episode_ids.episode_lock`` — the critical
    section every capture writer holds for its own read-modify-write — and
    retired only when its body is still the revision Sleep selected. A newer
    revision stays ``processed: false`` for the NEXT run: the drain in progress
    counts the id settled (its earlier revision was filed), so a conversation
    that keeps growing can never keep one drain re-reading it. A dict without
    a ``revision`` (a caller that built it by hand) retires as before.
    """
    retired = 0
    for ep in episodes:
        filepath = ep["filepath"]
        with episode_ids.episode_lock(Path(filepath).parent):
            try:
                parsed = markdown_parser.parse(filepath)
            except Exception as exc:  # noqa: BLE001 - one malformed episode must not abort the cycle
                logger.warning(f"_mark_episodes_processed: skipping malformed episode {filepath}: {exc}")
                continue
            selected = ep.get("revision")
            if selected is not None and episode_ids.body_revision(parsed.body) != selected:
                logger.info(f"_mark_episodes_processed: {ep['id']} changed while Sleep read it — left queued")
                continue
            parsed.frontmatter["processed"] = True
            parsed.frontmatter["processed_by"] = "sleep"
            markdown_parser.write(filepath, parsed.frontmatter, parsed.body)
            retired += 1
    return retired


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
    drain: tuple[str, int, int] | None = None,
    subject_suffix: str = "",
) -> None:
    """Commit all changes from the sleep cycle with a structured message.

    ``drain`` / ``subject_suffix`` (a drain's batch, ``sleep_drain``): ``(drain
    id, batch, batches)`` becomes three ids-only refs on the ``sleep_run`` row so
    the batches of one run can be told apart from separate cycles, and the suffix
    (`` (batch 2 of 12)``) ends the main commit's subject. ``_cycle_kind`` reads a
    trailing ``(decay)`` only, so a batch commit is still a ``sleep`` cycle. The
    G85 ``(decay)`` commit is unchanged — and appears only in the batch that ran
    decay.

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

    # G53 (R3) — the live state dictionary is a projection, regenerated by
    # the tail and authored `cicada`. Every regeneration commits itself
    # (`state_dictionary.refresh_and_commit`), but a failed commit or an
    # older build can still leave it dirty here; without this split the main
    # commit's `git add -A` would stamp a model's name on arithmetic it never
    # touched — the exact G85 smear, on a different file. Same degrade
    # contract as the decay split: if this fails the file rides in the main
    # commit under the honest `sleep/state` trigger from
    # `_infer_trigger_for_path`.
    from api.services import state_dictionary

    if (memory_path / state_dictionary.STATE_FILENAME).exists():
        try:
            porcelain = await git_service.porcelain_status(memory_path)
            if any(line[3:].strip() == state_dictionary.STATE_FILENAME for line in porcelain.splitlines()):
                async with _lock:
                    await git_service.commit_paths(
                        memory_path, state_dictionary.commit_message(), [state_dictionary.STATE_FILENAME]
                    )
        except Exception as exc:
            logger.warning(
                f"G53 state split failed — folding _state.md into the main commit: "
                f"{type(exc).__name__}: {exc}"
            )

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
        f"Sleep cycle {date_str}{subject_suffix}", body_lines, authors=resolved_authors,
        sessions=sessions or [], engine=engine,
    )
    async with _lock:
        commit = await git_service.commit_changes(memory_path, message)

    from api.services import cycle_usage, telemetry

    plan_block = await cycle_usage.finish(cycle_id, engine)
    cycle_usage.reset_cache()  # the engine menu's "last cycle" is now stale

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
            # Calls of this cycle carry `refs.cycle_id`; without this marker an
            # empty call set reads as "not recorded" rather than "no calls".
            cycle_usage.TAGGED_REF: True,
            **({"plan": plan_block} if plan_block else {}),
            **({"drain_id": drain[0], "batch": drain[1], "batches": drain[2]} if drain else {}),
            "episodes_processed": _state.episodes_processed,
            "episodes_requeued": _state.episodes_requeued,
            "entities_created": _state.entities_created,
            "entities_updated": _state.entities_updated,
            "skills_detected": _state.skills_detected,
            "session_count": len(sessions or []),
            # G141 PJ-0 (R-CS3): M3's per-cycle page-less count — integers only.
            "claims_page_less": _state.claims_page_less,
            "subjects_page_less": _state.subjects_page_less,
            # G141 PJ-0b (R-HP12): the hold — integers only, never a name.
            "claims_held": _state.claims_held,
            "claims_released": _state.claims_released,
            "claims_hold_capped": _state.claims_hold_capped,
            "claims_waiting": _state.claims_waiting,
            # Decay inbox questions (Stage 5): counts only.
            "decay_nudges_deferred": _state.decay_nudges_deferred,
            "decay_nudges_refreshed": _state.decay_nudges_refreshed,
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
    if path == "_state.md":
        # G53 (R3): the projection normally lands in its own `cicada`
        # commit; when that split fails it rides here under its honest name.
        return "sleep/state"
    if path.startswith("hubs/") or path == "_index.md":
        return "sleep/hub_generation"
    if path == "graph_edges.yaml":
        return "sleep/extraction"
    return "sleep/extraction"
