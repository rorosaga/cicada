from fastapi import APIRouter, Depends, Request, Response
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.models.schemas import GraphResponse
from api.services import sync_service
from api.services.graph_builder import build_graph

router = APIRouter()


def _split(value: str | None) -> set[str] | None:
    if not value:
        return None
    parts = {p.strip() for p in value.split(",") if p.strip()}
    return parts or None


# G136 S6 (plan R-SU23) — nodes gained `aliases`. The ETag's components did not
# move (aliases already live in the entity files), so an app holding a pre-S6
# `/graph` would 304 into an alias-less cache until some entity changed. The
# node shape rides `extra`: every client pays one 200, once. Bump it whenever a
# node gains a field a client must see; no `VersionVector` change is needed.
#
# F1 final review: "+f1-facets" — the body changed for the same files. `general`
# and non-slug contexts no longer make satellites or colour edges, a facet is
# named for people ("Engineering"), node `contexts` keep real contexts only, and
# `summary` no longer flattens the claims fence into YAML (R-FX1..3, R-FX8). A
# bank neither F1 migration rewrites would otherwise 304 into the junk graph
# forever; the bump costs every client one 200. The node hash folds `contexts`
# and `summary` too (graph_builder), so `GraphDiff` re-pushes those parents.
NODE_SHAPE = "aliases+f1-facets"


@router.get("/graph", response_model=GraphResponse)
async def get_graph(
    request: Request,
    response: Response,
    types: str | None = None,
    statuses: str | None = None,
    min_confidence: float = 0.0,
    tags: str | None = None,
    include_hubs: bool = True,
    hubs_only: bool = False,
    settings: Settings = Depends(get_settings),
):
    extra = f"{types}|{statuses}|{min_confidence}|{tags}|{include_hubs}|{hubs_only}|{NODE_SHAPE}"
    etag = sync_service.etag_for(
        # "logos": `has_logo` rides every node's content_hash but lives in the
        # machine-global logo cache, not in the bank — see sync_service.
        settings.memory_path, "entities", "edges", "hubs", "inbox", "logos", extra=extra
    )
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    return await run_in_threadpool(
        build_graph,
        settings.memory_path,
        types=_split(types),
        statuses=_split(statuses),
        min_confidence=min_confidence,
        tags=_split(tags),
        include_hubs=include_hubs,
        hubs_only=hubs_only,
    )
