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

* ``POST /reading/asks`` sits outside the ``/capture/`` and ``/sources/``
  prefixes, so it carries ``refuse_capture_into_demo`` explicitly (it can save a
  page); ``PUT /reading/settings`` writes a machine setting and no bank, and is
  named in the demo lint's handled-elsewhere list.
* Ids, enums and hosts only. A host is a bare, sanitized name; no URL is stored
  outside the bank and none is served here except the person's own prompt.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from api.config import Settings, get_settings
from api.routers.capture import refuse_capture_into_demo
from api.services import (
    media_ingestor, reading_asks, reading_hosts, reading_prompt, reading_service, reading_settings, sync_service,
)

router = APIRouter()

SHAPE = "reading-1"
_DEMO_GATE = [Depends(refuse_capture_into_demo)]


class SettingsUpdate(BaseModel):
    agentEnabled: bool | None = None
    agentHosts: list[str] | None = None
    acknowledge: bool = False


class AskRequest(BaseModel):
    url: str


def _settings_body() -> dict:
    snap = reading_settings.snapshot()
    return {
        **snap,
        "ackVersion": reading_settings.ACK_VERSION,
        "hostSwitches": [
            {"key": key, "label": reading_hosts.HOST_LABELS[key],
             "domains": list(reading_hosts.WALLED_DOMAINS[key]), "note": reading_hosts.HOST_NOTES.get(key)}
            for key in reading_hosts.AGENT_HOST_KEYS
        ],
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
async def put_reading_settings(update: SettingsUpdate):
    try:
        reading_settings.update(
            agent_enabled_=update.agentEnabled, agent_hosts=update.agentHosts, acknowledge=update.acknowledge)
    except reading_settings.SettingsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _settings_body()


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
            "harness": row.get("harness"), "note": row.get("note"),
        })
    counts = {state: 0 for state in reading_asks.STATES}
    for row in rows:
        counts[row["state"]] += 1
    return {"asks": asks, "counts": counts, "expiresAfterDays": reading_asks.EXPIRES_AFTER_DAYS}


@router.post("/reading/asks", dependencies=_DEMO_GATE)
async def post_reading_ask(request: AskRequest, settings: Settings = Depends(get_settings)):
    """"Ask an agent". 409 while agent reading, or the link's site, is switched off;
    422 (with a sentence) for a link an agent is never offered. A link that is not
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
