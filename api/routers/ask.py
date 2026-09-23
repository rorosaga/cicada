"""POST /ask — auditable natural-language synthesis over the knowledge graph.

The thesis-novel retrieval front door (decision D3 = BOTH): an answer that
**cites its sources** and **admits what it does not know**. Direct file
traversal (the graph/search endpoints) stays available alongside this.

Thin wrapper over :func:`api.services.ask_service.answer_query` — the service
holds the retrieval + grounded-synthesis + gap-analysis logic and is unit-tested
with injected retrieval/LLM. This router resolves the live defaults (sqlite-vec
+ the engine chosen in Settings → Engines, R-E23) and adapts the service dict
onto the wire schema.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.models.schemas import AskCitation, AskRequest, AskResponse
from api.services import agent_engine, ask_service, engine_select

router = APIRouter()


@router.post("/ask", response_model=AskResponse)
async def ask(
    request: AskRequest,
    settings: Settings = Depends(get_settings),
) -> AskResponse:
    # R-E23: Ask follows the engine chosen in Settings → Engines (or an explicit
    # CICADA_LLM_MODE), resolved like a Sleep you start yourself — a person
    # asking is a person present. The engine is built lazily, on the first
    # prompt: the honest-gap fast path must still spend nothing.
    resolved, _why = await engine_select.resolve_settings(settings, user_triggered=True)

    def llm_fn(prompt: str) -> str:
        # Final review H1: each Ask call runs in its OWN self-purging breaker
        # scope. The shared ``_unscoped`` bucket is never reset, so once R-E23
        # routed Ask onto a plan, one throttle there (Claude, a Codex usage
        # limit) left every later Ask — and the link backfill sharing that
        # bucket — failing fast without spawning until the backend restarted,
        # even after the plan window reset. A throttle seen here still stops
        # THIS call; ``use_scope`` purges the trip on exit.
        with agent_engine.use_scope(f"ask:{uuid.uuid4().hex}"):
            return ask_service._default_llm_fn(resolved)(prompt)

    # answer_query is synchronous (sqlite-vec lookup + a blocking LLM call),
    # so run it off the event loop to avoid stalling other requests.
    result = await run_in_threadpool(
        ask_service.answer_query,
        resolved.memory_path,
        request.query,
        request.top_k,
        llm_fn=llm_fn,
    )
    return AskResponse(
        answer=result["answer"],
        confidence=float(result["confidence"]),
        citations=[AskCitation(**c) for c in result["citations"]],
        gaps=result["gaps"],
        used_entities=result["used_entities"],
    )
