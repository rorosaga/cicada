"""Memory-bank management + chat-history import (M6 + M7).

Banks are switchable, self-contained memory directories (see
``api/services/bank_registry.py`` and
``docs/goals/m5-prep/m6m7-banks-import-design.md``). All bank-mutating ops
operate on ``settings.memory_root`` (the raw container field) so they can see
and manage *every* bank, not just the resolved active one.
"""

from __future__ import annotations

import hashlib

from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from loguru import logger

from api.config import Settings, get_settings
from api.models.schemas import (
    BankCreateRequest,
    BankDuplicateRequest,
    BankImportDateRange,
    BankImportResponse,
    BankInfo,
    BankListResponse,
    BankRenameRequest,
    BankTrashResponse,
)
from api.routers import intake
from api.services import bank_index, bank_registry, search_index, sync_service
from api.services.bank_migrations import run_bank_migrations
from api.services.graph_builder import file_mtime

router = APIRouter()

#: Bumped when a `/banks` row gains a field (G139: `legacy`). The ETag's inputs
#: (registry mtime + per-bank stamps) are unchanged, so no `VersionVector`
#: mapping moves; the tag only makes an ETag minted before the field existed
#: miss once. Without it the app keeps the body it cached under that ETag on
#: every 304, and a pre-`legacy` body offers the memory folder itself for
#: deletion until some capture happens to move a stamp.
_BANKS_BODY_SHAPE = "2"


@router.get("/banks", response_model=BankListResponse)
async def list_banks(
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
) -> BankListResponse:
    root = settings.memory_root
    registry_mtime = file_mtime(root / "banks.yaml")
    registry = bank_registry.load_registry(root)
    # The listing's body includes each bank's live entity_count/episode_count
    # (bank_registry.list_banks -> _count(bank_dir(...), "entities"/"episodes")),
    # so the ETag must cover those per-bank counts too -- not just banks.yaml's
    # own mtime -- or a 304 would hide a changed count.
    parts = [_BANKS_BODY_SHAPE, str(registry_mtime)]
    for name in sorted((registry.get("banks", {}) or {}).keys()):
        bank_path = bank_registry.bank_dir(root, name)
        entities_stamp = bank_index.dir_stamp(bank_path, "entities")
        episodes_stamp = bank_index.dir_stamp(bank_path, "episodes")
        parts.append(f"{name}:{entities_stamp}:{episodes_stamp}")
    etag = '"' + hashlib.sha1("|".join(parts).encode()).hexdigest()[:16] + '"'
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    data = bank_registry.list_banks(root)
    return BankListResponse(
        banks=[BankInfo(**b) for b in data["banks"]],
        active=data["active"],
    )


@router.post("/banks", response_model=BankListResponse)
async def create_bank(
    req: BankCreateRequest,
    settings: Settings = Depends(get_settings),
) -> BankListResponse:
    if not (req.name or "").strip():
        raise HTTPException(400, "Bank name is required")
    try:
        slug = bank_registry.create_bank(
            settings.memory_root, req.name, req.description or ""
        )
    except ValueError as e:
        raise HTTPException(409, str(e))
    logger.info(f"Created bank '{slug}'")
    data = bank_registry.list_banks(settings.memory_root)
    return BankListResponse(
        banks=[BankInfo(**b) for b in data["banks"]],
        active=data["active"],
    )


@router.post("/banks/{name}/activate", response_model=BankListResponse)
async def activate_bank(
    name: str,
    settings: Settings = Depends(get_settings),
) -> BankListResponse:
    try:
        bank_registry.activate_bank(settings.memory_root, name)
    except ValueError as e:
        raise HTTPException(404, str(e))
    logger.info(f"Activated bank '{name}'")
    # A bank switched to at runtime gets the SAME one-shot migrations the
    # boot-time bank gets in `main.lifespan` — otherwise its pages stay
    # unclassed (and the Feed / decay engines disagree about them) until the
    # next API restart. Every migration is marker-guarded and never raises, so
    # this is a few `stat`s on an already-migrated bank and can't fail the
    # switch.
    # A first activate of a big bank rewrites hundreds of pages + git — keep it
    # off the event loop like every other blocking route in this codebase.
    await run_in_threadpool(run_bank_migrations, bank_registry.bank_dir(settings.memory_root, name))
    # G136: warm the newly active bank's search index off the request — the
    # switch returns at once; /search serves the fallback until it lands.
    search_index.warm_in_background(bank_registry.bank_dir(settings.memory_root, name))
    data = bank_registry.list_banks(settings.memory_root)
    return BankListResponse(
        banks=[BankInfo(**b) for b in data["banks"]],
        active=data["active"],
    )


@router.post("/banks/{name}/duplicate", response_model=BankListResponse)
async def duplicate_bank(
    name: str,
    req: BankDuplicateRequest,
    settings: Settings = Depends(get_settings),
) -> BankListResponse:
    if not (req.new_name or "").strip():
        raise HTTPException(400, "newName is required")
    try:
        slug = bank_registry.duplicate_bank(settings.memory_root, name, req.new_name)
    except ValueError as e:
        # Unknown source -> 404; name collision -> 409.
        code = 404 if "Unknown bank" in str(e) else 409
        raise HTTPException(code, str(e))
    logger.info(f"Duplicated bank '{name}' -> '{slug}'")
    data = bank_registry.list_banks(settings.memory_root)
    return BankListResponse(
        banks=[BankInfo(**b) for b in data["banks"]],
        active=data["active"],
    )


@router.post("/banks/{name}/rename", response_model=BankListResponse)
async def rename_bank(
    name: str,
    req: BankRenameRequest,
    settings: Settings = Depends(get_settings),
) -> BankListResponse:
    if not (req.new_name or "").strip():
        raise HTTPException(400, "newName is required")
    try:
        slug = bank_registry.rename_bank(settings.memory_root, name, req.new_name)
    except ValueError as e:
        # Unknown source -> 404; name collision -> 409; blank -> 400.
        msg = str(e)
        if "Unknown bank" in msg:
            code = 404
        elif "already exists" in msg:
            code = 409
        else:
            code = 400
        raise HTTPException(code, msg)
    logger.info(f"Renamed bank '{name}' -> '{slug}'")
    data = bank_registry.list_banks(settings.memory_root)
    return BankListResponse(
        banks=[BankInfo(**b) for b in data["banks"]],
        active=data["active"],
    )


@router.delete("/banks/{name}", response_model=BankTrashResponse)
async def delete_bank(name: str, settings: Settings = Depends(get_settings)) -> BankTrashResponse:
    """Move a bank to `<root>/.trash/` (G139, R-O18/R-O19) — reversible by
    hand, nothing erased. The active bank and the in-place legacy bank are
    refused in plain words the app shows as they are.

    409 while a Sleep cycle runs, the same guard export uses (final review):
    a cycle resolves its bank path once at start and `/activate` is not
    guarded, so switching away and trashing the cycle's bank would rename the
    folder out from under its writes and strand half-written pages there."""
    from api.services import sleep_cycle

    if sleep_cycle.get_sleep_state().status == "running":
        raise HTTPException(409, "A Sleep cycle is running — delete when it finishes.")
    root = settings.memory_root
    try:
        dst = await run_in_threadpool(bank_registry.trash_bank, root, name)
    except bank_registry.UnknownBank as exc:
        raise HTTPException(404, str(exc))
    except bank_registry.BankInUse:
        raise HTTPException(409, "Switch to another bank first — the one you're using can't be moved.")
    except bank_registry.LegacyBankInPlace:
        raise HTTPException(409, "This bank is your memory folder itself, so it can't be moved to the trash from here.")
    except ValueError as exc:
        # The same bank already sits in the trash under this second's stamp.
        raise HTTPException(409, str(exc))
    logger.info(f"Moved bank '{name}' to the trash")
    data = bank_registry.list_banks(root)
    return BankTrashResponse(
        banks=[BankInfo(**b) for b in data["banks"]],
        active=data["active"],
        trashed_to=dst.relative_to(root).as_posix(),
    )


@router.get("/banks/{name}/export")
async def export_bank(name: str, settings: Settings = Depends(get_settings)):
    """Zip a bank for the person to keep (G139, R-O20). 409 while a Sleep cycle
    runs: a copy taken mid-cycle could hold a half-written page. The archive
    lives in `$CICADA_HOME/exports/` only for the length of the response."""
    from api.services import sleep_cycle
    from api.services.auth import cicada_home

    if sleep_cycle.get_sleep_state().status == "running":
        raise HTTPException(409, "A Sleep cycle is running — export when it finishes.")
    try:
        path = await run_in_threadpool(
            bank_registry.export_zip, settings.memory_root, name, cicada_home() / "exports"
        )
    except bank_registry.UnknownBank as exc:
        raise HTTPException(404, str(exc))
    return FileResponse(
        path,
        media_type="application/zip",
        filename=path.name,
        background=BackgroundTask(path.unlink, missing_ok=True),
    )


@router.post("/banks/demo", response_model=BankListResponse)
async def create_demo_bank(settings: Settings = Depends(get_settings)) -> BankListResponse:
    """G117 — one click, a populated bank (`api/services/demo_bank.py`), for
    the first-run sheet's "try it on a demo bank first" button. `409` if a
    `demo` bank already exists (mirrors `create_bank`'s own collision
    handling) rather than silently re-populating someone's edited copy —
    the same reasoning `create_bank` names for a plain name collision.

    Registered ahead of `create_bank` (whose slug is caller-supplied, so a
    plain `POST /banks` could never collide with this literal route) but
    placed as its own function rather than folded into it: the population
    step below is demo-specific and unrelated to the general "make an empty
    bank" contract `create_bank` gives every other caller.
    """
    root = settings.memory_root
    try:
        slug = bank_registry.create_bank(root, "demo", "Synthetic demo bank — try Cicada risk-free.")
    except ValueError as e:
        raise HTTPException(409, str(e))
    # Deferred: `demo_bank` pulls in `agentic_write` (fuzzy matching, claim
    # reconciliation) for a handful of literal `write_claim` calls this ONE
    # route makes — no other route in this module needs any of that, so
    # every other request pays nothing for it.
    from api.services import demo_bank

    await run_in_threadpool(demo_bank.populate, bank_registry.bank_dir(root, slug))
    bank_registry.activate_bank(root, slug)
    await run_in_threadpool(run_bank_migrations, bank_registry.bank_dir(root, slug))
    data = bank_registry.list_banks(root)
    return BankListResponse(
        banks=[BankInfo(**b) for b in data["banks"]],
        active=data["active"],
    )


@router.post("/banks/{name}/import", response_model=BankImportResponse)
async def import_into_bank(
    name: str,
    file: UploadFile,
    settings: Settings = Depends(get_settings),
) -> BankImportResponse:
    """Stage a chat export as DATED episodes into bank ``{name}`` (M7).

    Track I T2 (R-IA10): a shim over ``intake.import_bytes`` — the one pipeline,
    so this route gains every zip member, named skips and the Gemini split — kept
    for external callers with its shape, plus ``vendor``/``origin``. G87: the
    ``active`` flag still says when the target is not the bank Sleep reads."""
    content = await file.read()
    logger.info(f"Import into bank '{name}': {file.filename or ''} ({len(content)} bytes)")
    result = await run_in_threadpool(intake.import_bytes, content, file.filename or "", settings, bank=name)
    return BankImportResponse(
        episodes_staged=result.created,
        episodes_updated=result.updated,
        duplicates_skipped=result.skipped,
        date_range=BankImportDateRange(**{"from": result.date_from, "to": result.date_to}),
        format=result.parsed.format,
        active=result.active,
        vendor=result.parsed.vendor,
        origin=result.parsed.origin,
    )
