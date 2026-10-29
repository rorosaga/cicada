"""Merge two pages, split one, undo either — the person's own door (G227 follow-up, owner 2026-10-29).

The same bodies as ``cicada_merge_pages`` / ``cicada_split_page`` (``page_join``), applied at once and committed alone
under the person (``Cicada-Author: user``, trigger ``user/companion_app``). Each route is one admitted transaction
(``write_admission.route``: 409 while Sleep holds the pages), takes the page lock for its write and commit, and runs
off the event loop. The split plan's suggestions are ``same_name_split``'s judge, run only when the person asks for
them (``?suggest=true``) on the engine they chose — a person-started read, never Auto's metered rung (ruling 31).
"""
from __future__ import annotations

import asyncio
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.models.schemas import CamelModel
from api.services import git_service, page_join, page_lock, write_admission
from api.services.sleep_refusal import SleepWriting

router = APIRouter()

BUSY = "Sleep is updating your memory — try again in a moment."


class MergeRequest(CamelModel):
    """``into``: the page that stays; this page folds into it."""
    into: str
    reason: Optional[str] = None


class SplitRequest(CamelModel):
    sentences: list[int] = []
    claims: list[str] = []
    sources: list[str] = []
    episodes: list[str] = []
    references: dict[str, Literal["new", "stay"]] = {}
    name: Optional[str] = None
    type: Optional[str] = None
    reason: Optional[str] = None


class JoinResult(CamelModel):
    kind: str
    entity_id: str
    other_id: Optional[str] = None
    commit: Optional[str] = None
    restored: list[str] = []
    removed: list[str] = []
    repointed: list[str] = []


def _run(memory_path, fn):
    """``fn(before)`` under the page lock with the bank's dirty pages snapshotted first, so an edit already there is
    committed apart, never as the person's join; a :class:`page_join.JoinError` is its status and sentence."""
    with page_lock.page_lock(memory_path):
        before = git_service.snapshot_dirty_sync(memory_path)
        try:
            return fn(before)
        except page_join.JoinError as exc:
            raise HTTPException(exc.status, str(exc)) from exc


@router.post("/entities/{entity_id}/merge", response_model=JoinResult)
@write_admission.route(refuse=lambda: SleepWriting(BUSY))
async def merge_page(entity_id: str, request: MergeRequest, settings: Settings = Depends(get_settings)):
    """Fold this page into ``into`` (``page_join.merge``): its beliefs, sources, aliases, links, pictures and history
    move by id, its id keeps resolving to ``into``, and any "different" answer or split between them is cleared.
    404: no such page; 400: the page itself; 409: a page whose beliefs cannot be read."""
    out = await run_in_threadpool(_run, settings.memory_path, lambda before: page_join.merge(
        settings.memory_path, entity_id, request.into, reason=request.reason, before=before))
    return JoinResult(kind="merge", entity_id=out["winner"], other_id=out["loser"], commit=out["commit"])


@router.get("/entities/{entity_id}/split-plan")
async def split_plan(entity_id: str, suggest: bool = False, settings: Settings = Depends(get_settings)):
    """What the split sheet shows (``page_join.split_plan``). ``suggest=true`` pre-ticks the sentences
    ``same_name_split``'s judge says are about a different thing with the same name — suggestions the person
    confirms, never applied here."""
    moves = []
    if suggest:
        moves = await _suggestions(settings, entity_id)
    try:
        plan = await run_in_threadpool(page_join.split_plan, settings.memory_path, entity_id, moves)
    except page_join.JoinError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    plan["suggested"] = bool(suggest)
    return _camel(plan)


def _camel(value):
    """The plan's keys as every other route serves them (camelCase); values — page ids, sentences — untouched."""
    from pydantic.alias_generators import to_camel

    if isinstance(value, dict):
        return {to_camel(k) if isinstance(k, str) else k: _camel(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_camel(v) for v in value]
    return value


async def _suggestions(settings: Settings, entity_id: str) -> list:
    """The judge's moves for this one page, on the person's chosen engine; ``[]`` when it cannot run (no engine, an
    error) — the sheet then opens with nothing ticked and says so."""
    from api.services import agent_engine, engine_select, inbox_tend, same_name_split

    try:
        resolved, _why = await engine_select.resolve_settings(settings, user_triggered=True)
        llm_fn = inbox_tend.default_llm_fn(resolved)

        async def judge(prompt: str) -> dict:
            answer, _model = await inbox_tend._ask(llm_fn, prompt)
            return answer

        targets = dict(await asyncio.to_thread(same_name_split.targets, settings.memory_path, [entity_id]))
        with agent_engine.use_scope(f"split-plan:{settings.memory_path.name}"):
            return await same_name_split.plan_page(settings.memory_path, entity_id, targets.get(entity_id, []), judge)
    except Exception as exc:  # noqa: BLE001 — suggestions are optional; the class, never the message
        logger.warning(f"split plan: suggestions unavailable ({type(exc).__name__})")
        return []


@router.post("/entities/{entity_id}/split", response_model=JoinResult)
@write_admission.route(refuse=lambda: SleepWriting(BUSY))
async def split_page(entity_id: str, request: SplitRequest, settings: Settings = Depends(get_settings)):
    """Move what the person picked to a new page (``page_join.split``): a clean title, a distinct id, the pair kept
    apart from now on. 400: nothing picked or a type outside the set; 409: the page changed since the plan."""
    out = await run_in_threadpool(_run, settings.memory_path, lambda before: page_join.split(
        settings.memory_path, entity_id, sentences=request.sentences, claims=request.claims,
        sources=request.sources, episodes=request.episodes, references=request.references, name=request.name,
        entity_type=request.type, reason=request.reason, before=before))
    return JoinResult(kind="split", entity_id=out["entity_id"], other_id=out["new_id"], commit=out["commit"],
                      repointed=out["repointed"])


@router.post("/entities/{entity_id}/history/{commit_hash}/undo", response_model=JoinResult)
@write_admission.route(refuse=lambda: SleepWriting(BUSY))
async def undo_join(entity_id: str, commit_hash: str, settings: Settings = Depends(get_settings)):
    """Take a merge or a split back (``page_join.undo``), from the page's History. 404: not a join; 409: already
    undone, or something since changed the same place (nothing written; the sentence says what to do instead)."""
    out = await run_in_threadpool(_run, settings.memory_path, lambda before: page_join.undo(
        settings.memory_path, commit_hash, before=before))
    return JoinResult(kind="undo", entity_id=entity_id, commit=out["commit"], restored=out["restored"],
                      removed=out["removed"])
