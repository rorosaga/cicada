import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from api.config import get_settings
from api.routers import (
    ask,
    banks,
    claims,
    clarifications,
    contributors,
    conversations,
    entities,
    graph,
    inbox,
    nudges,
    search,
    sleep,
    sources,
    status,
)
from api.services import bank_registry, sleep_scheduler
from api.services.inbox_migration import migrate_to_inbox

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

    # One-time idempotent migration of legacy nudges/clarifications into inbox/.
    # Never crashes boot — a failure logs loudly and leaves legacy dirs intact.
    moved = migrate_to_inbox(settings.memory_path)
    if moved:
        logger.info(f"Migrated {moved} legacy items into inbox/")

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


app = FastAPI(title="Cicada API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
app.include_router(contributors.router, tags=["contributors"])
app.include_router(sleep.router, tags=["sleep"])
app.include_router(conversations.router, tags=["conversations"])
app.include_router(sources.router, tags=["sources"])
app.include_router(banks.router, tags=["banks"])
