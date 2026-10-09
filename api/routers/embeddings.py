"""G182 phase 3 — Settings → Memory → Search model.

``GET /embeddings`` says which model the active bank's vectors use, which models
this Mac can run, how a download is going and how far the background re-embed is.
``POST /embeddings/choice`` sets the active bank's model and starts the background
re-embed (``embedding_models.start_reindex_if_needed``; search keeps answering from the
old tables meanwhile). ``POST /embeddings/install`` starts a one-time download: with
``model`` = EmbeddingGemma 2 (owner 2026-10-09), the pinned Neural Engine model, no account
and no token; otherwise the larger model's install with the person's own Hugging Face token,
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


class EmbeddingInstallState(CamelModel):
    state: str
    step: str = ""
    error: str = ""


class EmbeddingReindexState(CamelModel):
    state: str = "idle"           # idle | running | waiting (for Sleep to end) | done | failed
    model: str = ""
    done: int = 0                 # tables re-embedded so far
    total: int = 0
    error: str = ""


class EmbeddingsStatus(CamelModel):
    model: str
    next_model: str
    choice: str | None = None
    release: bool
    recommended: str | None = None
    models: list[EmbeddingModelOption]
    install: EmbeddingInstallState
    reindex: EmbeddingReindexState = EmbeddingReindexState()


class EmbeddingChoiceRequest(CamelModel):
    model: str | None = None


class EmbeddingInstallRequest(CamelModel):
    hf_token: str = Field(default="", repr=False)
    model: str | None = None


@router.get("/embeddings", response_model=EmbeddingsStatus)
async def embeddings_status(settings: Settings = Depends(get_settings)):
    payload = await run_in_threadpool(embedding_models.status, settings.memory_path, settings)
    return EmbeddingsStatus.model_validate(payload)


@router.post("/embeddings/choice", response_model=EmbeddingsStatus)
async def choose_model(body: EmbeddingChoiceRequest, settings: Settings = Depends(get_settings)):
    known = {m.id for m in embedding_models.CATALOG}
    if body.model is not None and body.model not in known:
        raise HTTPException(status_code=400, detail="That isn't one of the search models Cicada offers.")
    if body.model and not embedding_models.is_available(body.model):
        raise HTTPException(status_code=409, detail="That model isn't installed on this Mac yet.")
    # Not only while a batch writes: a drain re-syncs the index between its batches, and a model switched
    # mid-drain would re-embed half the bank under one model and half under the other until the next full sync.
    if write_admission.probe() or sleep_cycle.get_sleep_state().status == "running":
        raise SleepWriting("Sleep is running; change the search model when it finishes.")
    await run_in_threadpool(embedding_models.set_bank_choice, settings.memory_path, body.model)
    await run_in_threadpool(embedding_models.start_reindex_if_needed, settings.memory_path, settings)
    payload = await run_in_threadpool(embedding_models.status, settings.memory_path, settings)
    return EmbeddingsStatus.model_validate(payload)


@router.post("/embeddings/install", response_model=EmbeddingsStatus, status_code=202)
async def install_larger_model(body: EmbeddingInstallRequest, settings: Settings = Depends(get_settings)):
    if body.model == embedding_models.PREFERRED_ID:
        if not embedding_models.neural_engine_supported():
            raise HTTPException(status_code=409, detail="This search model needs macOS 15 or later on Apple silicon.")
        if not embedding_models.start_download(settings.memory_path, settings):
            raise HTTPException(status_code=409, detail="A search model is already being installed.")
        payload = await run_in_threadpool(embedding_models.status, settings.memory_path, settings)
        return EmbeddingsStatus.model_validate(payload)
    if body.model not in (None, embedding_models.LARGE_ID):
        raise HTTPException(status_code=400, detail="That isn't one of the search models Cicada offers.")
    token = (body.hf_token or "").strip()
    if not token.startswith("hf_") or len(token) < 20:
        raise HTTPException(status_code=400, detail="That doesn't look like a Hugging Face access token (it starts with hf_).")
    if not embedding_models.start_install(token):
        raise HTTPException(status_code=409, detail="The larger model is already being installed.")
    payload = await run_in_threadpool(embedding_models.status, settings.memory_path, settings)
    return EmbeddingsStatus.model_validate(payload)
