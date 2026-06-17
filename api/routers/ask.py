"""POST /ask — auditable natural-language synthesis over the knowledge graph.

The thesis-novel retrieval front door (decision D3 = BOTH): an answer that
**cites its sources** and **admits what it does not know**. Direct file
traversal (the graph/search endpoints) stays available alongside this.

Thin wrapper over :func:`api.services.ask_service.answer_query` — the service
holds the retrieval + grounded-synthesis + gap-analysis logic and is unit-tested
with injected retrieval/LLM. This router resolves the live defaults (sqlite-vec
+ litellm) from Settings and adapts the service dict onto the wire schema.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.models.schemas import AskCitation, AskRequest, AskResponse
from api.services import ask_service

router = APIRouter()


@router.post("/ask", response_model=AskResponse)
async def ask(
    request: AskRequest,
    settings: Settings = Depends(get_settings),
) -> AskResponse:
    # answer_query is synchronous (sqlite-vec lookup + a blocking litellm call),
    # so run it off the event loop to avoid stalling other requests.
    result = await run_in_threadpool(
        ask_service.answer_query,
        settings.memory_path,
        request.query,
        request.top_k,
    )
    return AskResponse(
        answer=result["answer"],
        confidence=float(result["confidence"]),
        citations=[AskCitation(**c) for c in result["citations"]],
        gaps=result["gaps"],
        used_entities=result["used_entities"],
    )
