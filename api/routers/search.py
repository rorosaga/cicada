"""GET /search — find anything in memory: entities, beliefs, conversations,
sources and inbox questions (G136; round-3 design §3.9).

The work is ``search_service.search`` (lexical FTS5 + stored vectors, fused);
this router only parses parameters and moves that work OFF the event loop.
It used to be ``async def`` doing a blocking embed + KNN + a parse of every
entity file inline (R6 §4.2), so one slow search stalled every other request,
``/sync/events`` included. ``run_in_threadpool`` is the same move ``/ask``
made (``routers/ask.py``).

The pre-G136 call shape (``?q=&top_k=&indexes=entities``) stays valid and
returns entities only. No ETag: a per-keystroke query is never a Store
domain (K10), and the query is never logged (K9).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.models.schemas import SearchResponse
from api.services import search_service

router = APIRouter()


@router.get("/search", response_model=SearchResponse)
async def search(
    q: str = Query(..., max_length=200),
    top_k: int = Query(8, ge=1, le=50),
    indexes: str | None = Query(None, max_length=200),
    kinds: str | None = Query(None, max_length=200),
    mode: str = Query("hybrid", pattern="^(prefix|hybrid)$"),
    per_kind: int | None = Query(None, ge=1, le=search_service.MAX_PER_KIND),
    settings: Settings = Depends(get_settings),
):
    return await run_in_threadpool(
        search_service.search,
        settings.memory_path,
        q,
        kinds=search_service.parse_kinds(kinds, indexes),
        mode=mode,
        per_kind=per_kind or min(top_k, search_service.MAX_PER_KIND),
    )
