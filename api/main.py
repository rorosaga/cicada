import asyncio
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from api.config import get_settings
from api.routers import (
    ask,
    banks,
    capture,
    claims,
    clarifications,
    connections,
    connectors,
    consumption,
    contributors,
    conversations,
    entities,
    episodes,
    graph,
    inbox,
    local_refs,
    maintenance,
    nudges,
    origins,
    search,
    settings as settings_router,
    sleep,
    sources,
    state,
    status,
    sync,
)
from api.services import bank_registry, sleep_scheduler
from api.services.providers import warm_query_embedder
from api.services.auth import auth_enabled, get_token, require_token
from api.services.bank_migrations import run_bank_migrations

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

# Suppress litellm's print() calls by redirecting verbose mode
import litellm
litellm.suppress_debug_info = True
litellm.set_verbose = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if auth_enabled():
        get_token()  # generate the token file on first boot so clients can read it
    else:
        logger.warning("CICADA_API_AUTH=off — the local API is UNAUTHENTICATED (dev/test only)")

    from api.services.connections import secrets as connection_secrets

    loaded = connection_secrets.load_secrets()
    if loaded:
        logger.info(f"Loaded {len(loaded)} provider key(s) from {connection_secrets.secrets_path()}")

    # Preload the query embedder recorded in the bank's index in the
    # background so the first /search request doesn't pay the model-load
    # cost. Never awaited — must not block startup — and warm_query_embedder
    # swallows its own errors so a slow/missing index can't crash boot.
    asyncio.get_running_loop().run_in_executor(None, warm_query_embedder, settings.memory_path)

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

    # The one-shot per-bank migrations (legacy nudges -> inbox/, duplicate open
    # question collapse, decay-class backfill). Each is marker-guarded and never
    # raises, so boot continues on failure. The SAME set runs from
    # `POST /banks/{name}/activate`, so a bank switched to at runtime is
    # migrated too — see api/services/bank_migrations.py.
    run_bank_migrations(settings.memory_path)

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

    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


app = FastAPI(
    title="Cicada API",
    version="0.1.0",
    lifespan=lifespan,
    dependencies=[Depends(require_token)],
)

# This backend is a LOCAL service: the only legitimate browser origins are the
# companion app's WKWebView and local tooling on loopback (any port). A wildcard
# meant any page the user happened to have open could script requests at
# localhost:8000 — and while every route but /healthz and the Telegram webhook
# needs a bearer token, the provider-key, logout and memory-write routes are not
# doors to leave open. Native clients (URLSession, the MCP server, curl) send no
# Origin at all and are unaffected; the bearer scheme is untouched.
LOCAL_ORIGIN_REGEX = r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$"

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=LOCAL_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(graph.router, tags=["graph"])
app.include_router(search.router, tags=["search"])
app.include_router(ask.router, tags=["ask"])
app.include_router(inbox.router, tags=["inbox"])
app.include_router(status.router, tags=["status"])
app.include_router(nudges.router, tags=["nudges"])
app.include_router(clarifications.router, tags=["clarifications"])
app.include_router(entities.router, tags=["entities"])
app.include_router(claims.router, tags=["claims"])
app.include_router(episodes.router, tags=["episodes"])
app.include_router(contributors.router, tags=["contributors"])
app.include_router(origins.router, tags=["origins"])
app.include_router(sleep.router, tags=["sleep"])
app.include_router(conversations.router, tags=["conversations"])
app.include_router(sources.router, tags=["sources"])
app.include_router(state.router, tags=["state"])
app.include_router(banks.router, tags=["banks"])
app.include_router(settings_router.router, tags=["settings"])
app.include_router(local_refs.router, tags=["local-refs"])
app.include_router(capture.router, tags=["capture"])
app.include_router(connectors.router, tags=["connectors"])
app.include_router(maintenance.router, tags=["maintenance"])
app.include_router(connections.router, tags=["connections"])
app.include_router(sync.router, tags=["sync"])
app.include_router(consumption.router, tags=["consumption"])
