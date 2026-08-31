"""Consumption / traceability dashboard (G51)."""
from __future__ import annotations

import re
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic.alias_generators import to_camel

from api.config import Settings, get_settings
from api.models.schemas import (
    CalendarDay, ConnectionConsumption, ConsumptionCalendar, ConsumptionConnections,
    ConsumptionStats, ConsumptionSummary, HarnessStats,
)
from api.services import consumption_stats, harness_stats, sync_service, telemetry
from api.services.connections.registry import get_registry

router = APIRouter(prefix="/consumption")
_RANGE_OK = re.compile(r"^(all|month|\d{1,4}d)$")


def _camel_rows(rows: list[dict]) -> list[dict]:
    """The by_* breakdowns are ``list[dict]`` (not declared models), so CamelModel
    does not convert their keys — do it here so Swift's ``StatsRow`` decodes them."""
    return [{to_camel(k): v for k, v in row.items()} for row in rows]


def _range(range_: str = Query("30d", alias="range")) -> str:
    if not _RANGE_OK.match(range_):
        raise HTTPException(status_code=422, detail="range must be 'all', 'month' or '<N>d'")
    return range_


def _utc_today() -> date:
    """Today in UTC — the ledger's own clock.

    Every telemetry event is stamped ``datetime.now(timezone.utc)`` and every
    day bucket downstream is that stamp's ``ts[:10]``. Bounding those events
    with the *machine's* local day (``date.today()``) shifted or dropped a
    day's usage for anyone west of UTC (their "today" starts hours after the
    ledger's) and east of it (their "today" ends before the ledger's).
    """
    return datetime.now(timezone.utc).date()


@router.get("/summary", response_model=ConsumptionSummary)
async def summary(
    request: Request,
    response: Response,
    range_: str = Depends(_range),
    settings: Settings = Depends(get_settings),
):
    memory_path = settings.memory_path
    today = _utc_today()
    # The UTC date is part of the answer: a rolling range ("last 30 days"), a
    # streak and a calendar all move at UTC midnight with no new event to bump
    # the "telemetry" component — without it the app 304s into yesterday.
    etag = sync_service.etag_for(memory_path, "telemetry", "git_head", extra=f"{range_}:{today}")
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    return ConsumptionSummary(**await consumption_stats.summary(memory_path, range_=range_, today=today))


@router.get("/calendar", response_model=ConsumptionCalendar)
async def calendar(
    request: Request,
    response: Response,
    weeks: int = Query(53, ge=1, le=106),
    settings: Settings = Depends(get_settings),
):
    memory_path = settings.memory_path
    today = _utc_today()
    etag = sync_service.etag_for(memory_path, "telemetry", "git_head", extra=f"{weeks}:{today}")
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    days = await consumption_stats.calendar(memory_path, weeks=weeks, today=today)
    return ConsumptionCalendar(days=[CalendarDay(**d) for d in days], weeks=weeks)


@router.get("/stats", response_model=ConsumptionStats)
async def stats(
    request: Request,
    response: Response,
    range_: str = Depends(_range),
    settings: Settings = Depends(get_settings),
):
    memory_path = settings.memory_path
    today = _utc_today()
    etag = sync_service.etag_for(memory_path, "telemetry", "git_head", extra=f"{range_}:{today}")
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    data = await consumption_stats.stats(memory_path, range_=range_, today=today)
    for key in ("by_model", "by_stage", "by_connection", "by_bank", "series"):
        data[key] = _camel_rows(data[key])
    return ConsumptionStats(**data)


@router.get("/connections", response_model=ConsumptionConnections)
async def connections(range_: str = Depends(_range), settings: Settings = Depends(get_settings)):
    statuses = [s.model_dump() for s in await get_registry(settings).statuses()]
    today = _utc_today()
    start = consumption_stats.resolve_range(range_, today)
    events = telemetry.read_events(start=start, end=today)
    rows = consumption_stats.per_connection(events, statuses)
    for r in rows:
        r["by_model"] = _camel_rows(r["by_model"])
    return ConsumptionConnections(connections=[ConnectionConsumption(**r) for r in rows], range=range_)


@router.get("/harness", response_model=HarnessStats)
async def harness():
    return HarnessStats(claude_code=harness_stats.claude_code_stats(), codex=harness_stats.codex_rate_limits())
