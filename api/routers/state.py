"""``GET /state`` — the live state dictionary as an object (G53) — and
``GET /handshake``, the generated primer built on it (G75).

The on-disk frontmatter of ``<bank>/_state.md`` is the wire shape, verbatim
and snake_case: one documented schema, read the same way by the API, the MCP
server and any harness that ``cat``s the file. Three things are added per
request and never persisted: ``resumable`` on each conversation (G48 — a
transcript can be retention-cleaned behind our back, so it is an ``isfile``
per request through the same seam ``/conversations/recent`` uses),
``sleep.next_at`` (a clock, not a belief — in the file it advanced daily and
made every idle night commit, breaking R1; computed here on the local clock
the schedule is expressed in, exactly as ``/status`` does) and ``stale``
(the file's ``inputs_version`` no longer matches the bank).

Reads regenerate lazily (R4): an inbox resolution or an agentic write
changed an input, so the first read afterwards rebuilds — cheaply, carrying
the previous repo blocks over. ``?refresh=true`` forces a rebuild with live
repo probes (bounded, ``state_dictionary.REPO_BUDGET_S``). A read that
rewrote the file COMMITS it, alone, as ``cicada`` — through the same
``state_dictionary.refresh_and_commit`` Sleep's tail uses (final review,
2026-09-03: a projection left dirty was reproduced riding in the next
``git add -A`` writer's commit — an inbox resolution under
``Cicada-Author: user`` — which is the G85-class smear R2/R3 exist to
prevent). A read that wrote nothing commits nothing, so a 304-shaped read
stays free. ``_finalize`` still splits a dirty projection out of any model
commit (R3) for the failed-commit case.

ETag (R9): the same components the file is built from plus the file's own
mtime, so a 304 is exactly "nothing you would see has changed". Bearer-gated
like every route outside ``auth._OPEN_PATHS``.

``GET /handshake`` carries no ETag — ≤ 7 KB and self-describing (its
``as of`` line is the state's ``generated_at``), the same reasoning as
G118's span endpoint — and, unlike ``/state``, never refreshes the file
(R4): the primer is what the MCP ``initialize`` response would carry right
now, stale or not.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.services import sleep_scheduler, state_dictionary, sync_service
from api.services.repo_context import resolve_repo_context

router = APIRouter()

# Injectable seam (tests): the live git prober behind `?refresh=true`.
repo_resolver = resolve_repo_context


def _state_mtime_ns(settings: Settings) -> int:
    try:
        return state_dictionary.state_path(settings.memory_path).stat().st_mtime_ns
    except OSError:
        return 0


@router.get("/state")
async def get_state(
    request: Request,
    response: Response,
    refresh: bool = Query(False),
    settings: Settings = Depends(get_settings),
):
    memory_path = settings.memory_path
    # `connected` is filled by `refresh` from the registry's cache (R7) —
    # the same helper Sleep's tail uses, so a read never rewrites the file
    # just because the two writers named different connection lists. The
    # helper commits only when it wrote, and never raises on a normal bank.
    await state_dictionary.refresh_and_commit(
        memory_path, settings,
        force=refresh, probe_repos=refresh, repo_resolver=repo_resolver if refresh else None,
    )
    etag = sync_service.etag_for(
        memory_path, "entities", "inbox", "episodes", "git_head", extra=f"state={_state_mtime_ns(settings)}"
    )
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    state = await run_in_threadpool(state_dictionary.read_state, memory_path)
    if state is None:
        raise HTTPException(404, "this bank has no _state.md yet and it could not be generated")

    from api.routers import conversations as conv
    from api.services import session_stats

    # `session_stats._group` is the private grouper the resume endpoint reads
    # `project_dir` from; it only ever feeds the `isfile` probe here and is
    # never serialised (R5 — `resumable` is per request, `project_dir` is
    # not part of the projection).
    project_dirs = {
        cid: group.get("project_dir")
        for cid, group in (await run_in_threadpool(session_stats._group, memory_path)).items()
    } if state.get("conversations") else {}
    for row in state.get("conversations", []) or []:
        row["resumable"] = bool(conv.transcript_exists(project_dirs.get(row["id"]), row["id"]))
    # Per request, local clock — never in the file (see the module docstring).
    # Disclosed gap (G125 TODO.md): no `last_cycle_at`/`newest_unprocessed_at`
    # is threaded through here, unlike `GET /status`'s calibrated call — so
    # `interval` reads "N hours from now" and `after_import` always reads
    # `null`. Feeds the MCP handshake's now-view, not the app's own "Next
    # run" text, so a brief primer imprecision right after a schedule-mode
    # change was judged not worth a second `sleep_debt.compute` scan on this
    # engine-free read path.
    state.setdefault("sleep", {})["next_at"] = sleep_scheduler.next_run_at(memory_path)
    state["stale"] = state.get("inputs_version") != state_dictionary.inputs_version(memory_path)
    state.pop("body", None)
    return state


@router.get("/handshake")
async def get_handshake(
    client: str | None = Query(None, max_length=64),
    settings: Settings = Depends(get_settings),
):
    """The same primer the MCP `initialize` response carries (G75), for the
    app and for AGENTS.md / SessionStart-hook pointers. `client` picks the
    per-harness prelude (R11); the contract never varies. Every delivery is
    one `handshake` ledger row (R14) so "did any agent ever receive the
    primer" is answerable the way G105 asked it of capture."""
    from api.services import handshake

    text, meta = await run_in_threadpool(handshake.load_or_build, settings.memory_path, client)
    handshake.record("http", meta, bank=settings.memory_path.name, client_name=client)
    return {
        "text": text,
        "variant": meta["variant"],
        "state_present": meta["state_present"],
        "hook_pointer": handshake.HOOK_POINTER,
    }
