"""Reading with an agent — the app's routes (G166, spec §8.4, §7.2).

Cicada never opens a browser and never signs in: the person's own agent reads
through a queue. These routes are the person's half of it — the switch and its
first-use acknowledgement (``GET|PUT /reading/settings``), "Ask an agent"
(``POST /reading/asks``), the asks and their outcomes (``GET /reading/asks``,
``DELETE /reading/asks/{url_hash}``) and the hand-off prompt
(``GET /reading/prompt``). The agent's half is two MCP tools
(``cicada_reading_queue``, ``cicada_record_read``).

None of it is a Store domain: the app keeps these in memory and revalidates with
the ETag, like provenance. The link's read state itself rides ``GET /sources``
(``MediaSourceItem.read``), which moves on the ``reading`` sync component, so an
agent's ``needs_login`` shows on the link over SSE with no bank write.

* ``GET /reading/sites`` (owner, 2026-09-30) is the permissions page's data: the
  sites Cicada's own reader could not read, with measured counts (hosts and
  numbers only — no URL, title or note), and the person's per-site permission
  (``PUT /reading/settings`` ``sites``). ``GET /reading/sites/{site}/icon`` serves
  a site's favicon from the icon service only, and only for a site that list holds
  — it is never a proxy for an arbitrary name, and the site itself is never asked.
* ``POST /reading/asks`` sits outside the ``/capture/`` and ``/sources/``
  prefixes, so it carries ``refuse_capture_into_demo`` explicitly (it can save a
  page); ``PUT /reading/settings`` writes a machine setting and no bank, and is
  named in the demo lint's handled-elsewhere list.
* Ids, enums and hosts only. A host is a bare, sanitized name; no URL is stored
  outside the bank and none is served here except the person's own prompt.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from api.config import Settings, get_settings
from api.routers.capture import refuse_capture_into_demo
from api.services import (
    logo_service, media_ingestor, reading_asks, reading_hosts, reading_prompt, reading_queue, reading_service,
    reading_settings, sync_service,
)

router = APIRouter()

SHAPE = "reading-2"
_DEMO_GATE = [Depends(refuse_capture_into_demo)]


class SettingsUpdate(BaseModel):
    agentEnabled: bool | None = None
    acknowledge: bool = False
    #: A patch ``{site: bool}``: true lets an agent read that site with the person's browser, false takes it back.
    sites: dict[str, bool] | None = None


class AskRequest(BaseModel):
    url: str


def _settings_body() -> dict:
    return {
        **reading_settings.snapshot(),
        "ackVersion": reading_settings.ACK_VERSION,
        "lastAgentRead": reading_settings.last_agent_read(),
        "shape": SHAPE,
    }


@router.get("/reading/settings")
async def get_reading_settings(request: Request, response: Response):
    body = _settings_body()
    etag = '"' + sync_service._digest(body) + '"'
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    return body


@router.put("/reading/settings")
async def put_reading_settings(update: SettingsUpdate, settings: Settings = Depends(get_settings)):
    """Apply one change. A site grant is refused (422, with a sentence) for a site Cicada has not
    needed the browser for, and needs the master switch and a current acknowledgement (which may
    ride in the same call). Turning a site on — a new grant, or a repeat of one already on — lifts
    its ``needs_login`` pause in this bank, so it means "try again"."""
    memory_path = settings.memory_path
    surfaced = None
    if update.sites and any(update.sites.values()):
        surfaced = {r["site"] for r in await asyncio.to_thread(reading_queue.sites_snapshot, memory_path)}
    try:
        reading_settings.update(
            agent_enabled_=update.agentEnabled, acknowledge=update.acknowledge, sites=update.sites,
            surfaced=surfaced)
    except reading_settings.SettingsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    for site, on in (update.sites or {}).items():
        if on:
            reading_queue.resume_site(memory_path, site)
    return _settings_body()


@router.get("/reading/sites")
def get_reading_sites(request: Request, response: Response, settings: Settings = Depends(get_settings)):
    """The sites Cicada's own reader could not read (a sign-in, a consent wall, a refusal, or a
    host the backend never requests), each with how many saved pages are waiting and whether the
    person let an agent read it with their browser. A plain ``def``: the first scan of a cold
    bank parses pages, so it runs in the threadpool and answers 304 before any scan."""
    memory_path = settings.memory_path
    etag = reading_queue.sites_stamp(memory_path)
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    rows = reading_queue.sites_snapshot(memory_path)
    return {
        "sites": rows,
        "waitingTotal": sum(r["waiting"] for r in rows),
        "waitingNotAllowed": sum(r["waiting"] for r in rows if not r["allowed"]),
        "enabled": reading_settings.agent_enabled(),
        "shape": reading_queue.SITES_SHAPE,
    }


_ICON_SEMAPHORE = asyncio.Semaphore(4)
_ICON_TYPES = {"png": "image/png", "jpg": "image/jpeg", "ico": "image/x-icon", "gif": "image/gif",
               "webp": "image/webp"}


@router.get("/reading/sites/{site}/icon")
async def get_reading_site_icon(site: str, request: Request, settings: Settings = Depends(get_settings)):
    """A site's favicon, from the icon service only (the site is never contacted). 404 means "no
    icon" and the app draws its own mark. Served only for a site the surfaced list holds: anything
    else is a 404 with no lookup, so this is not a proxy for an arbitrary name, and it never
    carries the domain or a page URL in its reply."""
    memory_path = settings.memory_path
    if not reading_hosts.valid_site_key(site):
        raise HTTPException(404, "no icon for this site")
    rows = await asyncio.to_thread(reading_queue.sites_snapshot, memory_path)
    row = next((r for r in rows if r["site"] == site), None)
    domain = (row or {}).get("iconHost")
    if not domain:
        raise HTTPException(404, "no icon for this site")
    bank = logo_service.site_bank(logo_service.bank_name(memory_path))
    path = logo_service.cached_path(bank, site)
    if path is None:
        async with _ICON_SEMAPHORE:
            path = await logo_service.ensure_site_icon(memory_path, site, domain)
    if path is None or not path.exists():
        raise HTTPException(404, "no icon for this site")
    import hashlib

    stat = path.stat()
    etag = '"' + hashlib.sha1(f"{path.name}:{stat.st_mtime_ns}:{stat.st_size}".encode()).hexdigest()[:16] + '"'
    headers = {"ETag": etag, "Cache-Control": "max-age=86400"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return FileResponse(path, media_type=_ICON_TYPES.get(path.suffix.lstrip("."), "application/octet-stream"),
                        headers=headers)


@router.get("/reading/prompt")
async def get_reading_prompt():
    """The generic, URL-free hand-off the person gives their own agent."""
    return {"prompt": reading_prompt.queue_prompt()}


@router.get("/reading/asks")
async def list_reading_asks(request: Request, response: Response, settings: Settings = Depends(get_settings)):
    memory_path = settings.memory_path
    etag = sync_service.etag_for(memory_path, "reading", "entities", "sources", extra=SHAPE)
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    idx = media_ingestor.load_url_index(memory_path)
    try:
        rows = reading_asks.all_rows(memory_path)
    except ValueError:
        rows = []
    asks = []
    for row in rows:
        entry = idx.get(row["url_hash"]) or {}
        asks.append({
            "urlHash": row["url_hash"], "mediaEntityId": entry.get("media_entity_id") or None,
            "host": row.get("host") or None, "hostClass": row.get("host_class"), "state": row["state"],
            "askedAt": row["asked_at"], "outcomeAt": row.get("outcome_at"), "via": row.get("via"),
            "harness": row.get("harness"), "note": row.get("note"), "origin": row.get("origin"),
        })
    counts = {state: 0 for state in reading_asks.STATES}
    for row in rows:
        counts[row["state"]] += 1
    return {"asks": asks, "counts": counts, "expiresAfterDays": reading_asks.EXPIRES_AFTER_DAYS}


@router.post("/reading/asks", dependencies=_DEMO_GATE)
async def post_reading_ask(request: AskRequest, settings: Settings = Depends(get_settings)):
    """"Ask an agent". 409 while agent reading is switched off (there is no per-site
    condition: this ask is the person's own consent for this one page); 422 (with a
    sentence) for a link an agent is never offered. A link that is not
    saved is saved first — without a fetch, as the person's own save — and this
    does not 409 while Sleep runs, like ``POST /sources/save``."""
    try:
        return await reading_service.ask(settings.memory_path, request.url)
    except reading_service.AskRefused as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc


@router.delete("/reading/asks/{url_hash}")
async def delete_reading_ask(url_hash: str, settings: Settings = Depends(get_settings)):
    """Cancel an ask, or clear an outcome. Writes the machine-wide ask store only."""
    try:
        removed = reading_asks.drop(settings.memory_path, url_hash)
    except ValueError:
        removed = False
    return {"removed": removed}
