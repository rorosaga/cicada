"""G182 phase 3 — Settings → Privacy & data (was Memory → Search model until 2026-10-14).

``GET /embeddings`` says which model the active bank's vectors use, which models
this Mac can run, how a download is going and how far the background re-embed is.
``POST /embeddings/choice`` sets the active bank's model and starts the background
re-embed (``embedding_models.start_reindex_if_needed``; search keeps answering from the
old tables meanwhile). ``POST /embeddings/install`` starts a one-time download: with
``model`` = EmbeddingGemma 2 (owner 2026-10-09), the pinned Neural Engine model, no account
and no token — and with ``part: "vision"`` its image encoder (design taste, 2026-10-14: the Looks page's own click,
≈ 309 MB beside the text encoder, which is fetched first when it isn't here); otherwise the larger model's install with the person's own Hugging Face token,
used for that download only and never stored or logged. No ETag: not a Store domain; the app
reads it when the page opens and polls while a download or a re-embed runs.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.models.schemas import CamelModel
from api.services import embedding_models, sleep_cycle, write_admission
from api.services.sleep_refusal import SleepWriting

router = APIRouter()


class EmbeddingModelOption(CamelModel):
    id: str
    label: str
    dimensions: int
    detail: str
    needs_download: bool
    needs_token: bool = False
    available: bool
    download_bytes: int = 0       # what its one-click download fetches (the pinned total), stated before the click


class EmbeddingInstallState(CamelModel):
    state: str
    step: str = ""
    error: str = ""
    part: str = ""                # text | vision | larger: which download, so Settings puts it on the right row
    done: int = 0                 # bytes fetched so far while a pinned download streams
    total: int = 0                # bytes in all (0: not known, or not streaming now)


class EmbeddingReindexState(CamelModel):
    state: str = "idle"           # idle | running | waiting (for Sleep to end) | done | failed
    model: str = ""
    done: int = 0                 # tables re-embedded so far
    total: int = 0
    error: str = ""


class EmbeddingVisionState(CamelModel):
    supported: bool = False       # macOS 15+ on Apple silicon
    installed: bool = False       # the image encoder sits beside the text encoder
    download_bytes: int = 0       # what the one-time download would fetch now
    includes_text: bool = False   # that size includes the text encoder, fetched first when it isn't here


class EmbeddingsStatus(CamelModel):
    model: str
    next_model: str
    recorded: str | None = None   # the model the bank's index records; None = nothing built yet
    choice: str | None = None
    release: bool
    recommended: str | None = None
    models: list[EmbeddingModelOption]
    install: EmbeddingInstallState
    reindex: EmbeddingReindexState = EmbeddingReindexState()
    vision: EmbeddingVisionState = EmbeddingVisionState()


class EmbeddingChoiceRequest(CamelModel):
    model: str | None = None


class EmbeddingInstallRequest(CamelModel):
    hf_token: str = Field(default="", repr=False)
    model: str | None = None
    part: str | None = None       # "vision": EmbeddingGemma 2's image encoder


@router.get("/embeddings", response_model=EmbeddingsStatus)
async def embeddings_status(settings: Settings = Depends(get_settings)):
    payload = await run_in_threadpool(embedding_models.status, settings.memory_path, settings)
    return EmbeddingsStatus.model_validate(payload)


@router.post("/embeddings/choice", response_model=EmbeddingsStatus)
async def choose_model(body: EmbeddingChoiceRequest, settings: Settings = Depends(get_settings)):
    known = {m.id for m in embedding_models.CATALOG}
    if body.model is not None and body.model not in known:
        raise HTTPException(status_code=400, detail="That isn't a version of search Cicada offers.")
    if body.model and not embedding_models.is_available(body.model):
        raise HTTPException(status_code=409, detail="That version isn't on this Mac yet.")
    # Not only while a batch writes: a drain re-syncs the index between its batches, and a model switched
    # mid-drain would re-embed half the bank under one model and half under the other until the next full sync.
    if write_admission.probe() or sleep_cycle.get_sleep_state().status == "running":
        raise SleepWriting("Sleep is running; change how search works when it finishes.")
    await run_in_threadpool(embedding_models.set_bank_choice, settings.memory_path, body.model)
    await run_in_threadpool(embedding_models.start_reindex_if_needed, settings.memory_path, settings)
    payload = await run_in_threadpool(embedding_models.status, settings.memory_path, settings)
    return EmbeddingsStatus.model_validate(payload)


@router.post("/embeddings/install", response_model=EmbeddingsStatus, status_code=202)
async def install_larger_model(body: EmbeddingInstallRequest, settings: Settings = Depends(get_settings)):
    if body.model == embedding_models.PREFERRED_ID and body.part == "vision":
        if not embedding_models.neural_engine_supported():
            raise HTTPException(status_code=409, detail="Understanding images needs macOS 15 or later on a Mac with Apple silicon.")
        if not embedding_models.start_vision_download():
            raise HTTPException(status_code=409, detail="A download is already running.")
        payload = await run_in_threadpool(embedding_models.status, settings.memory_path, settings)
        return EmbeddingsStatus.model_validate(payload)
    if body.part not in (None, ""):
        raise HTTPException(status_code=400, detail="That isn't something Cicada can download.")
    if body.model == embedding_models.PREFERRED_ID:
        if not embedding_models.neural_engine_supported():
            raise HTTPException(status_code=409, detail="The sharper version needs macOS 15 or later on a Mac with Apple silicon.")
        if not embedding_models.start_download(settings.memory_path, settings):
            raise HTTPException(status_code=409, detail="A download is already running.")
        payload = await run_in_threadpool(embedding_models.status, settings.memory_path, settings)
        return EmbeddingsStatus.model_validate(payload)
    if body.model not in (None, embedding_models.LARGE_ID):
        raise HTTPException(status_code=400, detail="That isn't a version of search Cicada offers.")
    token = (body.hf_token or "").strip()
    if not token.startswith("hf_") or len(token) < 20:
        raise HTTPException(status_code=400, detail="That doesn't look like a Hugging Face key (it starts with hf_).")
    if not embedding_models.start_install(token):
        raise HTTPException(status_code=409, detail="A download is already running.")
    payload = await run_in_threadpool(embedding_models.status, settings.memory_path, settings)
    return EmbeddingsStatus.model_validate(payload)
