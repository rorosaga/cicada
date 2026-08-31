"""Memory-bank management + chat-history import (M6 + M7).

Banks are switchable, self-contained memory directories (see
``api/services/bank_registry.py`` and
``docs/goals/m5-prep/m6m7-banks-import-design.md``). All bank-mutating ops
operate on ``settings.memory_root`` (the raw container field) so they can see
and manage *every* bank, not just the resolved active one.
"""

from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile
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
)
from api.routers.conversations import _stage_episodes, parse_export_bytes
from api.services import bank_index, bank_registry, sync_service
from api.services.bank_migrations import run_bank_migrations
from api.services.graph_builder import file_mtime

router = APIRouter()


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
    parts = [str(registry_mtime)]
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
    run_bank_migrations(bank_registry.bank_dir(settings.memory_root, name))
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


@router.post("/banks/{name}/import", response_model=BankImportResponse)
async def import_into_bank(
    name: str,
    file: UploadFile,
    settings: Settings = Depends(get_settings),
) -> BankImportResponse:
    """Stage a chat-export file as DATED episodes into bank ``{name}``.

    Additive only: parses + content-hash-dedups against the target bank's
    ``episodes/`` and writes backdated episodes. Does NOT run consolidation or
    rewrite git. Format is auto-detected (Claude / ChatGPT / Gemini / zip).
    """
    root = settings.memory_root
    registry = bank_registry.load_registry(root)
    if name not in (registry.get("banks", {}) or {}):
        raise HTTPException(404, f"Unknown bank '{name}'")

    target_dir = bank_registry.bank_dir(root, name)
    # The bank may have been created empty; ensure its episodes dir exists.
    bank_registry.scaffold_bank(target_dir, git_init=False)

    content = await file.read()
    filename = file.filename or ""
    logger.info(f"Import into bank '{name}': {filename} ({len(content)} bytes)")

    episodes, fmt = parse_export_bytes(content, filename)

    # dateRange = min/max original conversation date across parsed episodes
    # (computed pre-staging so it reflects the export's true span, including any
    # that dedup later skips).
    dates = sorted(d for d in (e.get("original_date") for e in episodes) if d)
    date_range = BankImportDateRange(
        **{"from": dates[0] if dates else None, "to": dates[-1] if dates else None}
    )

    created, updated, skipped = _stage_episodes(episodes, target_dir / "episodes")
    logger.info(
        f"  Staged {created} new, {updated} updated, {skipped} unchanged ({fmt})"
    )

    return BankImportResponse(
        episodes_staged=created,
        episodes_updated=updated,
        duplicates_skipped=skipped,
        date_range=date_range,
        format=fmt,
    )
