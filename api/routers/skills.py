"""The Skills page's routes (owner 2026-10-15; G138's catalog, G112's agent-made skills).

The backend owns the logic and the app is one client: these routes, the stdio MCP tools (``mcp_tools.skills``,
``propose_skill``, ``create_skill``) and the ``cicada skills …`` commands share one set of bodies
(``skill_inventory`` reads, ``skill_actions`` decides, ``skill_store`` writes). Nothing here touches a bank:
skills live in the agents' own folders and ``$CICADA_HOME/skills`` — the only bank read is the "noticed by Sleep"
list.

**Who may call what.** A route that installs or updates third-party code is the person's: the app's click, or a
person-only CLI command (``cli_app.require_person``). No MCP tool reaches one. Every install is pinned (a previewed
commit, or a catalog tool's commit), and the fetch behind a preview or a check is the person's click or the open
page — ``POST /skills/check`` with ``auto`` re-checks only when the last check is over an hour old.

No ETag: not a Store domain; the page loads it when shown and after each action (a read of a few folders).
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.models.schemas import CamelModel
from api.models.skill_schemas import RecommendedSkillsResponse
from api.services import (skill_actions, skill_catalog, skill_inventory, skill_jobs, skill_sources, skill_store)

router = APIRouter()


@router.get("/skills/recommended", response_model=RecommendedSkillsResponse)
async def recommended_skills() -> RecommendedSkillsResponse:
    payload = await run_in_threadpool(skill_catalog.recommended)
    return RecommendedSkillsResponse.model_validate(payload)


def _refuse(exc: Exception) -> HTTPException:
    if isinstance(exc, skill_sources.SourceError):
        return HTTPException(400, detail=str(exc))
    return HTTPException(409, detail=str(exc))


@router.get("/skills")
async def skills_page(settings: Settings = Depends(get_settings)) -> dict:
    payload = await skill_inventory.snapshot(bank=settings.memory_path)
    payload["jobs"] = skill_jobs.recent()
    return payload


class CheckBody(CamelModel):
    auto: bool = False


def _age_s(stamp: str | None) -> float | None:
    if not stamp:
        return None
    try:
        return time.time() - datetime.fromisoformat(stamp).astimezone(timezone.utc).timestamp()
    except ValueError:
        return None


@router.post("/skills/check")
async def check(body: CheckBody | None = None) -> dict:
    """Ask upstream for updates. ``auto`` (the page opening) checks only past an hour; a click past a minute."""
    age = _age_s(skill_store.updates().get("checkedAt"))
    floor = skill_inventory.AUTO_CHECK_AFTER_S if (body and body.auto) else skill_inventory.CLICK_CHECK_MIN_S
    if age is not None and age < floor:
        return {**skill_store.updates(), "skipped": True}
    return await skill_inventory.check_updates()


class PreviewBody(CamelModel):
    source: str
    choose: str | None = None


@router.post("/skills/preview")
async def preview(body: PreviewBody) -> dict:
    try:
        return await skill_actions.preview(body.source, body.choose)
    except (skill_sources.SourceError, skill_store.StoreError) as exc:
        raise _refuse(exc) from None


class InstallBody(CamelModel):
    plan_id: str | None = None
    suggestion: str | None = None
    agents: list[str] = Field(default_factory=list)
    request_id: str | None = None


def _close(request_id: str | None) -> None:
    if request_id:
        skill_store.close_request(request_id)


@router.post("/skills/install")
async def install(body: InstallBody) -> dict:
    """A previewed skill (``planId``), or a suggestion from the catalog (``suggestion``) — a tool's install is a job."""
    try:
        if body.plan_id:
            result = await run_in_threadpool(skill_store.install_plan, body.plan_id, body.agents)
            _close(body.request_id)
            return result
        if body.suggestion:
            entry_id = body.suggestion
            if entry_id not in skill_store.OWN_BUNDLES and \
                    skill_inventory.install_method(skill_actions.catalog_entry(entry_id)) == "tool":
                agents = list(body.agents)
                job = skill_jobs.start("install", entry_id,
                                       lambda job: skill_actions.install_suggested(entry_id, agents))
                _close(body.request_id)
                return {"job": job}
            result = await skill_actions.install_suggested(entry_id, body.agents)
            _close(body.request_id)
            return result
    except (skill_sources.SourceError, skill_store.StoreError) as exc:
        raise _refuse(exc) from None
    raise HTTPException(400, detail="Say what to install: a preview's planId or a suggestion.")


class NameBody(CamelModel):
    request_id: str | None = None


@router.post("/skills/{name}/update")
async def update(name: str, body: NameBody | None = None) -> dict:
    job = skill_jobs.start("update", name, lambda job: skill_actions.update(name))
    _close(body.request_id if body else None)
    return {"job": job}


@router.post("/skills/update-all")
async def update_all() -> dict:
    return {"job": skill_jobs.start("update-all", "every update", lambda job: skill_actions.update_all(job))}


class ToggleBody(CamelModel):
    on: bool
    request_id: str | None = None


@router.put("/skills/{name}/agents/{agent}")
async def toggle(name: str, agent: str, body: ToggleBody) -> dict:
    try:
        work = skill_store.turn_on if body.on else skill_store.turn_off
        await run_in_threadpool(work, name, agent)
    except skill_store.StoreError as exc:
        raise _refuse(exc) from None
    _close(body.request_id)
    return {"name": name, "agent": agent, "on": body.on}


@router.post("/skills/{name}/refresh")
async def refresh(name: str, body: NameBody | None = None) -> dict:
    try:
        result = await skill_actions.refresh(name)
    except skill_store.StoreError as exc:
        raise _refuse(exc) from None
    _close(body.request_id if body else None)
    return result


@router.delete("/skills/{name}")
async def remove(name: str) -> dict:
    try:
        return {"name": name, "removedFrom": await run_in_threadpool(skill_store.remove, name)}
    except skill_store.StoreError as exc:
        raise _refuse(exc) from None


class PublishBody(CamelModel):
    agents: list[str] = Field(default_factory=list)


@router.post("/skills/drafts/{name}/publish")
async def publish(name: str, body: PublishBody) -> dict:
    try:
        return {"name": name, "agents": await run_in_threadpool(skill_store.publish_draft, name, body.agents)}
    except skill_store.StoreError as exc:
        raise _refuse(exc) from None


@router.delete("/skills/drafts/{name}")
async def discard(name: str) -> dict:
    try:
        await run_in_threadpool(skill_store.discard_draft, name)
    except skill_store.StoreError as exc:
        raise _refuse(exc) from None
    return {"name": name, "discarded": True}


class KindBody(CamelModel):
    key: str
    kind: str | None = None


@router.put("/skills/kinds")
async def set_kind(body: KindBody) -> dict:
    """The person flips a skill's kind (TODO ruling 35 §5): ``about-you``, ``generic`` or ``unknown``; ``null`` clears
    it back to Cicada's rule. The key is the row's ``kindKey``. Written outside every bank (``skill_store``)."""
    try:
        await run_in_threadpool(skill_store.set_kind, body.key, body.kind)
    except skill_store.StoreError as exc:
        raise _refuse(exc) from None
    return {"key": body.key, "kind": body.kind}


@router.post("/skills/requests/{request_id}/dismiss")
async def dismiss(request_id: str) -> dict:
    return {"id": request_id, "dismissed": skill_store.close_request(request_id)}


@router.get("/skills/onboarding")
async def onboarding() -> dict:
    return await run_in_threadpool(skill_actions.onboarding_offer)


class OnboardingBody(CamelModel):
    install: list[str] = Field(default_factory=list)
    agents: list[str] = Field(default_factory=list)


@router.post("/skills/onboarding")
async def onboarding_answer(body: OnboardingBody) -> dict:
    """The person continued past the skills step: that is the consent. An empty list is "No thanks", recorded so
    nothing asks again; the rest install in the background."""
    offered = set(skill_actions.ONBOARDING_IDS)
    chosen = [i for i in dict.fromkeys(body.install) if i in offered]
    answer = skill_store.save_onboarding(chosen, [i for i in offered if i not in chosen])
    if not chosen:
        return {"answer": answer, "job": None}
    agents = list(body.agents)
    job = skill_jobs.start("onboarding", "suggested skills",
                           lambda job: skill_actions.onboarding_install(chosen, agents, job))
    return {"answer": answer, "job": job}


@router.get("/skills/jobs/{job_id}")
async def job(job_id: str) -> dict:
    found = skill_jobs.get(job_id)
    if found is None:
        raise HTTPException(404, detail="No such job (the backend may have restarted).")
    return found
