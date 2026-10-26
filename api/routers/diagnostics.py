"""``GET /diagnostics/report`` — the backend half of *Report a problem…* (tester readiness, 2026-10-26).

Request/response, not a sync domain: no ETag, nothing cached or persisted, nothing sent anywhere. The app shows the
text to the person before they copy, save or send it. See ``api/services/diagnostics.py`` for what it holds and what
it never holds."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.services import agent_wiring, bank_registry, channel_registry, diagnostics, feed_registry
from api.services.auth import cicada_home
from api.version import __version__

router = APIRouter()


def _report(settings: Settings, lines: int) -> str:
    try:
        banks = [b["name"] for b in bank_registry.list_banks(settings.memory_root)["banks"]]
    except Exception:   # a broken registry still yields a report — the report is how that gets found
        banks = []
    try:
        from api.services.connectors import ADAPTERS

        channels = channel_registry.build_channels(
            settings.memory_path, telegram_enabled=settings.telegram_enabled,
            connectors_connected={cid: adapter.is_connected() for cid, adapter in ADAPTERS.items()},
            feed_fetch_allowed=feed_registry.fetch_allowed())
        on = [c["id"] for c in channels if c.get("connected")]
    except Exception:
        on = []
    return diagnostics.build(
        version=__version__, engine_mode=str(settings.llm_mode or ""), sources_on=on, bank_count=len(banks),
        bank_names=banks,
        home=Path.home(), dirs=diagnostics.log_dirs(cicada_home(), agent_wiring.REPO_ROOT), lines=lines)


@router.get("/diagnostics/report", response_class=PlainTextResponse)
async def report(lines: int = Query(diagnostics.DEFAULT_LINES, ge=1, le=diagnostics.MAX_LINES),
                 settings: Settings = Depends(get_settings)) -> PlainTextResponse:
    text = await run_in_threadpool(_report, settings, lines)
    return PlainTextResponse(text, headers={"Cache-Control": "no-store"})
