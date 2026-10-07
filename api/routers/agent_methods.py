"""How the person's own agent does a job — Settings, How your agent reads (G166; G178 generalises it).

``GET /agent-methods`` lists each job with the person's choice and its options:
"Let my agent choose", the agent's own tools, and every catalog skill that lists
the job (through the same view the Skills page uses, plus per-agent install state
and, for the active bank, the skill's page in the graph). ``PUT /agent-methods``
saves one choice. A choice is an instruction Cicada passes to the person's own
agent, never authority (``agent_methods``): it saves to a machine file and always
succeeds once valid — the page write beside it is best-effort, so a running Sleep
or a demo bank never dead-ends the choice. ``POST /agent-methods/skills/{skill}/page``
is the "Add to your graph" door for an installed skill that has none.

Not a Store domain and no ETag: a few ``isfile()`` calls, like ``/skills/recommended``.
This router is the only importer of ``skill_pages`` (the single-writer gate).
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.config import Settings, get_settings
from api.routers.capture import refuse_capture_into_demo
from api.services import agent_methods, skill_catalog, skill_pages
from api.services.sleep_refusal import SleepWriting

router = APIRouter()

SHAPE = "agent-methods-1"
SLEEP_BUSY = "Sleep is updating your memory — try adding it to your graph again in a moment."


class MethodChoice(BaseModel):
    job: str
    choice: str


def _page_view(memory_path: Path, entry: dict) -> dict | None:
    found = skill_pages.lookup(memory_path, entry) if (entry.get("pageName") or entry.get("invoke")) else None
    return {"id": found.entity_id, "state": found.state} if found is not None else None


def _job_view(job: str, memory_path: Path) -> dict:
    spec = agent_methods.JOBS[job]
    catalog = skill_catalog.load()
    options = agent_methods.options(job, catalog=catalog)
    by_id = {e["id"]: e for e in catalog["skills"]}
    for option in options:
        if option["kind"] == "skill":
            option["page"] = _page_view(memory_path, by_id[option["id"]])
    return {"job": job, "question": spec.question, "chosen": agent_methods.choice(job, catalog), "options": options}


def _all(memory_path: Path) -> dict:
    return {"shape": SHAPE, "jobs": [_job_view(job, memory_path) for job in agent_methods.JOBS]}


@router.get("/agent-methods")
async def get_agent_methods(settings: Settings = Depends(get_settings)):
    return await asyncio.to_thread(_all, settings.memory_path)


@router.put("/agent-methods")
async def put_agent_method(body: MethodChoice, settings: Settings = Depends(get_settings)):
    """Save the choice (422 with a sentence for an unknown job or choice). When it is a skill,
    also try to file its page in the graph: ``write.page`` says ``created``, ``adopted``,
    ``exists``, ``foreign``, ``busy`` (Sleep is writing), ``demo`` or ``none`` — never an error."""
    try:
        chosen = agent_methods.set_choice(body.job, body.choice)
    except agent_methods.MethodError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    page = "none"
    if chosen not in (agent_methods.AUTO, agent_methods.OWN):
        try:
            page = (await skill_pages.ensure(settings.memory_path, chosen)).state
        except Exception:  # noqa: BLE001 — the choice is saved; the page can be added again
            page = "none"
    view = await asyncio.to_thread(_job_view, body.job, settings.memory_path)
    return {**view, "write": {"page": page}}


@router.post("/agent-methods/skills/{skill}/page", dependencies=[Depends(refuse_capture_into_demo)])
async def post_skill_page(skill: str, settings: Settings = Depends(get_settings)):
    """"Add to your graph": the page for an installed skill that has none. 404 for a skill with no
    role, 409 while Sleep is writing."""
    catalog = skill_catalog.load()
    if next((e for e in catalog["skills"] if e.get("id") == skill and e.get("roles")), None) is None:
        raise HTTPException(404, "That skill isn't one your agent can be asked to use.")
    result = await skill_pages.ensure(settings.memory_path, skill, catalog=catalog)
    if result.state == "busy":
        raise SleepWriting(SLEEP_BUSY)
    if result.state == "demo":
        raise HTTPException(409, "This is the demo memory, so nothing is added to it.")
    return {"id": result.entity_id, "state": result.state}
