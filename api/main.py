# The settings file first, before any other import (`api/settings_file.py`): a developer checkout's `api/.env` fills
# the environment (the environment wins), and litellm's own walk-up `.env` load is turned off for good.
from api import settings_file

settings_file.load()

import asyncio  # noqa: E402
import logging  # noqa: E402
import sys  # noqa: E402
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from api.config import get_settings
from api.routers import (
    agent_api,
    agent_methods,
    agents,
    ask,
    backlog,
    banks,
    capture,
    chat_sources,
    claims,
    clarifications,
    connections,
    connectors,
    consumption,
    contributors,
    conversations,
    design,
    devices,
    diagnostics,
    embeddings,
    explore,
    files,
    entities,
    episodes,
    graph,
    inbox,
    intake,
    local_sources,
    maintenance,
    memory,
    nudges,
    origins,
    page_joins,
    projects,
    reading,
    remote,
    search,
    settings as settings_router,
    skills,
    videos,
    sleep,
    sources,
    state,
    status,
    sync,
    tools,
    traces,
)
from api.services import bank_binding, bank_registry, response_compression, search_index, sleep_refusal, sleep_scheduler
from api.services.providers import warm_query_embedder
from api.services.auth import auth_enabled, get_token, require_token
from api.services.bank_migrations import run_bank_migrations
from api.version import __version__

# --- Logging setup ---
# Remove loguru default handler and add our own format
logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | <cyan>{name}</cyan> — <level>{message}</level>",
    level="INFO",
)

# Suppress litellm's verbose output and "Provider List" spam
logging.getLogger("LiteLLM").setLevel(logging.ERROR)
logging.getLogger("LiteLLM Proxy").setLevel(logging.ERROR)
logging.getLogger("LiteLLM Router").setLevel(logging.ERROR)
logging.getLogger("litellm").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)


# G136 / K9: the person's search words are never logged. uvicorn's access log
# writes every request line WITH its query string (to `logs/backend.*.log`
# under launchd, and both the plist and the app's spawn leave it on), and
# `/search?q=` fires on every keystroke of the palette; `/conversations/recent`
# carries a title filter the same way. Strip the query string of those paths
# at the logger, so the rail holds whatever flags uvicorn was started with.
# uvicorn configures its loggers before it imports this module, so the
# filter attached here is never replaced.
_QUERY_PATHS = frozenset({"/search", "/conversations/recent"})
#: source-page-v3 review (#561): the class, not a list of paths — ANY request whose query names a parameter that
#: carries the person's words (`q`/`query`: a search, a source page's search; `focus`: the Reader's quote to land on)
#: or a credential (`code`: an OAuth landing's authorization code) is logged with its query cut, whatever route took
#: it. A new route that takes a person's words names its parameter one of these (`test_main_access_log`'s gate walks
#: every route's query parameters and refuses another word-like name).
_REDACTED_PARAMS = frozenset({"q", "query", "focus", "code"})


def _redacts(path: str, query: str) -> bool:
    """Whether an access-log line's query string is cut: a word or credential parameter anywhere in it, a search
    path, or an OAuth landing."""
    names = {part.split("=", 1)[0].strip().lower() for part in query.split("&") if part}
    return bool(names & _REDACTED_PARAMS) or path in _QUERY_PATHS or _is_callback(path)


def _is_callback(path: str) -> bool:
    """An OAuth sign-in's landing (``/sources/connectors/<id>/callback``, ``/connections/<id>/callback/<nonce>``): its
    query carries the authorization code, a credential — never logged (the credentials rail)."""
    parts = path.split("/")
    return (len(parts) == 5 and parts[1] == "sources" and parts[2] == "connectors" and parts[4] == "callback") or \
        (len(parts) == 5 and parts[1] == "connections" and parts[3] == "callback")


class _RedactQueryString(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        # uvicorn's access record: (client, method, path?query, http_version, status)
        if isinstance(args, tuple) and len(args) == 5 and isinstance(args[2], str):
            path, sep, query = args[2].partition("?")
            if sep and _redacts(path, query):
                record.args = (args[0], args[1], f"{path}?…", args[3], args[4])
        return True


logging.getLogger("uvicorn.access").addFilter(_RedactQueryString())

# Suppress litellm's print() calls by redirecting verbose mode
import litellm
litellm.suppress_debug_info = True
litellm.set_verbose = False
from api.services import price_supplement  # noqa: E402 — G50/G215: rows the pinned table lacks, each with its basis

price_supplement.apply(litellm)


#: How long shutdown waits for admitted writes still in flight (G183).
SHUTDOWN_DRAIN_S = 30.0


@asynccontextmanager
async def _replica_lifespan(app: FastAPI, settings):
    """A replica's start and stop (G132 phase 1 B): the follower (first copy, then fast-forwards) and nothing that
    writes a bank. ``app.state.scheduler`` stays None: a replica never schedules Sleep (ruling 4 runs at the home)."""
    from api.services import replica

    logger.info("This computer keeps a copy of a memory held elsewhere (replica mode)")
    app.state.scheduler = None
    asyncio.get_running_loop().run_in_executor(None, warm_query_embedder, settings.memory_path)
    search_index.warm_in_background(settings.memory_path)
    replica.start()
    try:
        yield
    finally:
        await asyncio.to_thread(replica.stop)
        from api.services import bank_watch

        bank_watch.stop_all()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings_file.log_summary()
    if auth_enabled():
        get_token()  # generate the token file on first boot so clients can read it
    else:
        logger.warning("CICADA_API_AUTH=off — the local API is UNAUTHENTICATED (dev/test only)")

    from api.services.connections import secrets as connection_secrets

    loaded = connection_secrets.load_secrets()
    if loaded:
        logger.info(f"Loaded {len(loaded)} provider key(s) from {connection_secrets.secrets_path()}")

    from api.services import replica_guard, runtime_layout

    # G132 phase 2: a hand-off cut short is finished (or a move that never committed its record undone) before this
    # backend reads which part it plays — the home or a replica — so it never starts half one and half the other.
    from api.services import home_move

    home_move.finish_at_start()
    if runtime_layout.mode_conflict():
        logger.warning(runtime_layout.mode_conflict())
    # The mode this backend runs in is the one it started in: `replica_of` written or removed while it runs changes
    # nothing until it starts again (review of #567 — never a half-switched backend).
    if replica_guard.freeze():
        # G132 phase 1 B (ruling 51e2): this computer keeps a read-only copy. No scaffold, migration, seed, schedule,
        # catch-up, poll, listener or reindex job — only the follower, the words index and the query embedder.
        try:
            async with _replica_lifespan(app, settings):
                yield
        finally:
            replica_guard.thaw()
        return
    # Not a copy (any more): a copy left active from when it was one is never opened here (review of #567) — this
    # computer's own memory is active again before anything is scaffolded, scheduled or captured.
    from api.services import replica as _replica

    _replica.leave_copy(settings.memory_root)

    # Preload the query embedder recorded in the bank's index in the
    # background so the first /search request doesn't pay the model-load
    # cost. Never awaited — must not block startup — and warm_query_embedder
    # swallows its own errors so a slow/missing index can't crash boot.
    asyncio.get_running_loop().run_in_executor(None, warm_query_embedder, settings.memory_path)
    # A search-model change that hasn't reached every table yet (a download that landed while the backend was
    # down, an interrupted re-embed) resumes in the background; it never runs while Sleep does.
    from api.services import embedding_models

    asyncio.get_running_loop().run_in_executor(
        None, embedding_models.start_reindex_if_needed, settings.memory_path, settings)
    # Pictures already on this Mac that the meaning index lacks (vision item 3): in the background, a little after
    # the start, only where the person installed the image encoder, never while Sleep runs.
    from api.services import image_index

    image_index.start_refresh(settings.memory_path, delay_s=image_index.SETTLE_S)

    logger.info(f"Memory path: {settings.memory_path}")
    logger.info(f"LLM model: {settings.litellm_model}")

    # Ensure the active bank's memory directories + seed files + git repo exist.
    # ``scaffold_bank`` is the single shared scaffolder used by both this lifespan
    # (legacy/default bank, in place at the root) and ``bank_registry.create_bank``
    # so every bank — including the legacy one — has identical structure:
    # ``nudges``/``clarifications`` for the shim/migration read path; ``inbox`` as
    # the write target; ``hubs`` for the regenerated hub tier (Stage 5.6);
    # ``sources`` for the media URL dedup index; ``candidates``/``_procedures``
    # for the M5 claim-layer milestones; plus the human-authored
    # ``_predicates.yaml`` / ``_preferences.md`` seeds (created if missing,
    # never clobbered).
    git_existed = (settings.memory_path / ".git").exists()
    bank_registry.scaffold_bank(settings.memory_path)
    if not git_existed and (settings.memory_path / ".git").exists():
        logger.info("Initialized git repo in memory directory")

    # G181 phase 2: every bank gets its identity in banks.yaml (what a client on another machine compares, never a
    # path). Resolution is unchanged; never raises into boot. After the scaffold, so a legacy root's fresh git repo
    # already exists to keep banks.yaml out of the bank's history.
    bank_registry.ensure_bank_ids(settings.memory_root)

    # The one-shot per-bank migrations (legacy nudges -> inbox/, duplicate open
    # question collapse, decay-class backfill). Each is marker-guarded and never
    # raises, so boot continues on failure. The SAME set runs from
    # `POST /banks/{name}/activate`, so a bank switched to at runtime is
    # migrated too — see api/services/bank_migrations.py.
    run_bank_migrations(settings.memory_path)

    # The first-boot default bank is scaffolded here, never through ``create_bank``,
    # so it gets the owner page every new bank starts with. The app's first-run gate
    # and empty states read an owner-only graph as empty, so this does not hide the
    # Welcome. Never raises.
    from api.services import owner_identity

    seeded = owner_identity.seed_owner_if_brand_new(settings.memory_path)
    # Owner 2026-10-22: a new install consolidates nightly by default; an existing bank keeps whatever it had (a bank
    # with no schedule file still reads as `manual`). Only a bank this boot just seeded is new.
    if seeded is not None:
        sleep_scheduler.seed_new_bank_schedule(settings.memory_path)
    # Ruling 36 D1, once per install: Auto loses its local rung; a person reading through one keeps it as a choice.
    from api.services import engine_select
    from api.services.connections.registry import get_registry

    # A bank seeded this boot is a new install of this build: it never had a local rung, so it is only recorded.
    asyncio.get_running_loop().create_task(engine_select.retire_auto_local_rung(
        settings, get_registry(settings), new_install=seeded is not None))

    # G136: build or catch up the derived search index in the background, so
    # the first keystroke after launch finds it warm. Never blocks startup,
    # never raises (a cold build takes a few seconds; until it lands, /search
    # serves the frontmatter fallback and says `indexState: building`).
    search_index.warm_in_background(settings.memory_path)

    entities_count = len(list((settings.memory_path / "entities").glob("*.md")))
    episodes_count = len(list((settings.memory_path / "episodes").glob("*.md")))
    logger.info(f"Loaded {entities_count} entities, {episodes_count} unprocessed episodes")

    # Start the in-process scheduler and register the persisted sleep job if
    # the user has enabled one. The scheduler is stashed on app.state so the
    # /sleep/schedule endpoint can re-register when the user updates it.
    scheduler = AsyncIOScheduler()
    scheduler.start()
    cfg = sleep_scheduler.load_schedule(settings.memory_path)
    sleep_scheduler.register_job(scheduler, settings, cfg)
    app.state.scheduler = scheduler
    # G218 — activity traces' retention (30 days for the timeline, 7 for screenshots) holds even while traces are off
    # and nothing syncs: once now, then hourly. Creates nothing when traces were never on; never raises.
    from api.services import trace_store

    asyncio.get_running_loop().run_in_executor(None, trace_store.sweep_if_present)
    scheduler.add_job(trace_store.sweep_if_present, "interval", hours=1, id="traces-sweep", replace_existing=True)
    # Ruling 47 tier 2: the connected official-API sources (Readwise, Notion) sync on their own, every few hours —
    # behind CICADA_ALLOW_CONNECTOR_FETCH, never while Sleep holds the pages, nothing at all until one is connected.
    from api.services.connectors import tier2

    scheduler.add_job(tier2.scheduled_sync, "interval", hours=tier2.SCHEDULE_HOURS, id="connectors-tier2",
                      replace_existing=True)
    # Sleep page v5: the opt-in continue-after-reset (TODO ruling 15) needs the scheduler, and a
    # paused run that had armed it re-arms after a restart (its sidecar says when).
    from api.services import sleep_autocontinue

    sleep_autocontinue.bind(scheduler)
    sleep_autocontinue.rearm_after_restart(settings.memory_path)

    # G135 — the remote connector's own listener (127.0.0.1:8765), started only
    # when the person turned "From anywhere" on. Never raises into boot (R-R21).
    from api.remote import listener as remote_listener

    await remote_listener.start_if_enabled()

    # Ruling 47a: a Telegram session the person connected resumes listening; with none kept, nothing at all happens
    # (no import of the client, no socket). Never raises into boot.
    from api.services import telegram_account

    asyncio.get_running_loop().create_task(telegram_account.ACCOUNT.resume())

    # Speed 2026-10-29: everything start-up made lives as long as the process; freeze it out of the cyclic collector
    # once, so a full collection in a request never walks the app itself (`gc_tuning`).
    # G132 phase 2: a home that shares its memory asks the group, at its start and every minute, whether another device
    # took over while it was away; a home closed by a move it already recorded goes on handing off. Nothing at all
    # while it shares nothing.
    await asyncio.to_thread(home_move.at_start, settings.memory_path)

    from api.services import gc_tuning

    gc_tuning.freeze_after_start()

    try:
        yield
    finally:
        home_move.stop_peer_watch()
        replica_guard.thaw()
        await remote_listener.LISTENER.stop()
        await telegram_account.ACCOUNT.stop()
        scheduler.shutdown(wait=False)
        from api.services import bank_watch

        bank_watch.stop_all()   # the SSE tick's file-change watchers
        # G183: an admitted write still in flight finishes (its workers and its commit) before the process goes.
        from api.services import write_admission

        if not await asyncio.to_thread(write_admission.drain, SHUTDOWN_DRAIN_S):
            logger.warning("shutdown: an admitted write was still running after the drain")


app = FastAPI(
    title="Cicada API",
    version=__version__,
    lifespan=lifespan,
    # G183(d): a write the app made in one bank never lands in another (`bank_binding`).
    dependencies=[Depends(require_token), Depends(bank_binding.require_same_bank)],
)

# This backend is a LOCAL service: the only legitimate browser origins are the
# companion app's WKWebView and local tooling on loopback (any port). A wildcard
# meant any page the user happened to have open could script requests at
# localhost:8000 — and while every route but /healthz and the Telegram webhook
# needs a bearer token, the provider-key, logout and memory-write routes are not
# doors to leave open. Native clients (URLSession, the MCP server, curl) send no
# Origin at all and are unaffected; the bearer scheme is untouched.
LOCAL_ORIGIN_REGEX = r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$"

# G177 — every "Sleep holds the pages" refusal carries a stable `code` beside its sentence (`sleep_refusal`).
app.add_exception_handler(sleep_refusal.SleepWriting, sleep_refusal.handler)
app.add_exception_handler(bank_binding.BankMismatch, bank_binding.handler)

# Backend hunt (2026-10-16): a path segment longer than any file name is a 404, and the two routes that took a whole
# body before bounding it refuse one past their ceiling as it arrives (`request_limits`).
from api.services.request_limits import RequestLimits  # noqa: E402

app.add_middleware(RequestLimits)

# G132 phase 1 B: a replica's route table (forward / capture / refuse / local) and a publishing home's `X-Cicada-Seq`
# on its writes; inert otherwise (`replica_forward`).
from api.services.replica_forward import ReplicaRouting  # noqa: E402

app.add_middleware(ReplicaRouting)

# Speed 2026-10-29: count this process's writes, the gate on an ETag reusing the SSE tick's listings (`local_writes`).
from api.services.local_writes import CountWrites  # noqa: E402

app.add_middleware(CountWrites)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=LOCAL_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# 2026-10-16 perf: gzip level 1 for a client on another machine only (a headless server's client); loopback is
# answered exactly as before (`response_compression`).
app.add_middleware(response_compression.RemoteGZipMiddleware)

app.include_router(graph.router, tags=["graph"])
app.include_router(search.router, tags=["search"])
app.include_router(ask.router, tags=["ask"])
app.include_router(inbox.router, tags=["inbox"])
app.include_router(status.router, tags=["status"])
app.include_router(nudges.router, tags=["nudges"])
app.include_router(clarifications.router, tags=["clarifications"])
app.include_router(entities.router, tags=["entities"])
app.include_router(page_joins.router, tags=["entities"])
app.include_router(claims.router, tags=["claims"])
app.include_router(projects.router, tags=["projects"])
app.include_router(backlog.router, tags=["backlog"])
app.include_router(design.router, tags=["design"])
app.include_router(files.router, tags=["files"])
app.include_router(episodes.router, tags=["episodes"])
app.include_router(contributors.router, tags=["contributors"])
app.include_router(origins.router, tags=["origins"])
app.include_router(sleep.router, tags=["sleep"])
app.include_router(conversations.router, tags=["conversations"])
app.include_router(intake.router, tags=["intake"])
app.include_router(agents.router, tags=["agents"])
app.include_router(agent_methods.router, tags=["agent-methods"])
app.include_router(sources.router, tags=["sources"])
app.include_router(state.router, tags=["state"])
app.include_router(banks.router, tags=["banks"])
app.include_router(settings_router.router, tags=["settings"])
app.include_router(local_sources.router, tags=["local-sources"])
app.include_router(chat_sources.router, tags=["chat-sources"])
app.include_router(traces.router, tags=["traces"])
app.include_router(capture.router, tags=["capture"])
app.include_router(connectors.router, tags=["connectors"])
app.include_router(maintenance.router, tags=["maintenance"])
app.include_router(memory.router, tags=["memory"])
app.include_router(connections.router, tags=["connections"])
app.include_router(sync.router, tags=["sync"])
app.include_router(consumption.router, tags=["consumption"])
app.include_router(reading.router, tags=["reading"])
app.include_router(remote.router, tags=["remote"])
app.include_router(skills.router, tags=["skills"])
app.include_router(videos.router, tags=["videos"])
app.include_router(explore.router, tags=["explore"])
app.include_router(embeddings.router, tags=["embeddings"])
app.include_router(devices.router, tags=["devices"])
app.include_router(diagnostics.router, tags=["diagnostics"])
app.include_router(tools.router, tags=["tools"])
app.include_router(agent_api.router, tags=["agent-api"])
