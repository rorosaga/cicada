import subprocess
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import get_settings
from api.routers import clarifications, conversations, entities, graph, nudges, sleep


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    # Ensure memory directories exist
    for subdir in ("entities", "nudges", "clarifications", "episodes"):
        (settings.memory_path / subdir).mkdir(parents=True, exist_ok=True)

    # Ensure memory dir is a git repo
    git_dir = settings.memory_path / ".git"
    if not git_dir.exists():
        subprocess.run(["git", "init"], cwd=str(settings.memory_path), check=True)

    yield


app = FastAPI(title="Cicada API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(graph.router, tags=["graph"])
app.include_router(nudges.router, tags=["nudges"])
app.include_router(clarifications.router, tags=["clarifications"])
app.include_router(entities.router, tags=["entities"])
app.include_router(sleep.router, tags=["sleep"])
app.include_router(conversations.router, tags=["conversations"])
