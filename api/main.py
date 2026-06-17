import logging
import subprocess
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from api.config import get_settings
from api.routers import (
    ask,
    clarifications,
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
from api.services import sleep_scheduler
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

    # Ensure memory directories exist. ``nudges``/``clarifications`` are still
    # mkdir'd for the shim/migration read path; ``inbox`` is the write target;
    # ``hubs`` holds the regenerated hub tier (Stage 5.6); ``sources`` holds the
    # media URL dedup index.
    for subdir in ("entities", "nudges", "clarifications", "inbox", "episodes", "hubs", "sources"):
        (settings.memory_path / subdir).mkdir(parents=True, exist_ok=True)

    # Ensure memory dir is a git repo
    git_dir = settings.memory_path / ".git"
    if not git_dir.exists():
        subprocess.run(["git", "init"], cwd=str(settings.memory_path), check=True)
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
app.include_router(sleep.router, tags=["sleep"])
app.include_router(conversations.router, tags=["conversations"])
app.include_router(sources.router, tags=["sources"])
