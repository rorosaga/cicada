from fastapi import APIRouter, Depends, Request, Response
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.models.schemas import GraphResponse
from api.services import meaning_neighbors, sync_service
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
#
# C11 (G146, plan R-PE5): "+pictures" — nodes gained `picture`, `pictureSource` (omitted when absent) and
# `lastReferenced`. The ETag's components did not move for the pages that already exist, so the bump is what makes
# every client take one 200.
#
# G61 S3-a: "+source-links" — `links` gained read-time edges from a source's `entity:` link, each `kind: "source"`.
#
# "+previews" (spelled before "+source-links", which a test pins as the tail): a media node's `picture` is now Cicada's
# stored preview (`/entities/{id}/preview?v=…`), no longer the provider's URL — no component moved, so the bump does.
#
# Owner ruling 2026-10-20: "+quiet" (spelled before "+source-links", the pinned tail) — a node gained `quiet` (a page only
# an import made, not yet mentioned; `quiet_pages`). Derived from the entity files the ETag already covers, so no
# component moved: the bump is what makes every client take one 200.
#
# G227 (owner 2026-10-29): "+same-name" (before the pinned tail) — a node whose title another page shares gained
# `qualifier` and `displayName` (`same_name`), derived from the entity files the ETag already covers.
#
# ROR-135 (owner 2026-11-06): "+byline" (before the pinned tail) — a book's node gained `byline`, its authors for the
# graph's hover card, derived from the entity files the ETag already covers: no component moved, so the bump does.
NODE_SHAPE = "aliases+f1-facets+pictures+previews+quiet+same-name+byline+source-links"


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
        # "photos" (G159, review B1): a person's public-profile photo lives outside the bank too; a fetch or a miss
        # aging out changes the node's `picture` and nothing else.
        settings.memory_path, "entities", "edges", "hubs", "inbox", "logos", "photos", extra=extra
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


@router.get("/graph/meaning")
async def get_graph_meaning(request: Request, response: Response, settings: Settings = Depends(get_settings)):
    """ROR-134: each page's nearest pages by meaning, for the graph's off-by-default "closeness by meaning" layout.

    Distance only — a pair is never a link, and the app draws no edge from it (ruling 56). Derived from the local
    vector index; this route is on the local API alone, never the remote connector. ``embedded`` against the entity
    count tells a client how many pages have a vector at all."""
    etag = 'W/"meaning-' + "-".join(str(x) for x in meaning_neighbors.signature(settings.memory_path)) + '"'
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    return await run_in_threadpool(meaning_neighbors.neighbors, settings.memory_path)
