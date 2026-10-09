"""Which embedding model each bank is built with, the downloads, and the background re-embed (G182 phase 3).

Owner's decision (2026-10-05): a fresh install embeds with a small, open, ungated
model on a light runtime — the release app bundles ``intfloat/multilingual-e5-small`` as ONNX
(``onnx_embedder``) — and EmbeddingGemma (torch + sentence-transformers, gated on
Hugging Face) becomes an optional download for whoever wants it. Each bank keeps the
model it was built with: queries already use the recorded model
(``providers.resolve_embed_fn_for_model``); this module makes the BUILD side do the
same, so a bank is never silently re-embedded with another model because the app's
default changed.

The model a bank's vectors are built with, first hit wins:

1. the person's choice for that bank (Settings → Memory → Search model), kept in
   ``$CICADA_HOME/embedding-models.json`` — outside every bank and every git repo;
2. the model the bank's index already records, when this machine can run it and the
   embedding settings were not set explicitly (an explicit ``CICADA_EMBEDDING_*``
   keeps its old meaning: switch every bank);
3. the configured default (``Settings.resolved_embedding_model``): the bundled model
   in a release app, EmbeddingGemma in a developer checkout.

**EmbeddingGemma 2 is the model wherever it runs** (owner 2026-10-09: "cant we just run everything with
embedding gemma 2?"). On Apple silicon with macOS 15 or later it runs on the Neural Engine through Core ML
(``coreml_embedder``), downloaded once into ``$CICADA_HOME/models`` (``model_fetch``, one click in Settings or
``make embedding-model-gemma2``). Once it is here it is the configured default, and a bank whose index records
one of Cicada's own former defaults (``FORMER_DEFAULTS``: the small model, or EmbeddingGemma-300M in a checkout
that never chose it) moves to it; a model the person picked, or set explicitly, is kept. Where it can't run
(macOS 14, not downloaded yet, a failed load) the small bundled model answers as before and search never errors.

**A model change is a background re-embed, never Sleep's** (``start_reindex_if_needed``): each table is
re-embedded in full with the new model from this process's background thread — the embed first (in a child
process, ``embed_worker``: Core ML holds the GIL), then one transaction swaps the table, so recall keeps
answering from the old table (queried with the old model it records) until the new one is written. It starts after a choice, an install, the backend's start and the end
of every Sleep run, never while Sleep runs, and gives way within one chunk of 64 texts when Sleep starts
(Sleep's own syncs keep each table's recorded model meanwhile: ``SqliteVecIndexer(defer_model_switch=True)``).

The larger model's download installs ``sentence-transformers`` (and torch) into
``$CICADA_HOME/extras/site-packages`` with the bundled interpreter's pip — never into
the signed app — and fetches the model once with the person's own Hugging Face token,
which is used for that request only and never stored. The model's files are then
loaded from their local folder (``$CICADA_HOME/models.json``), so no token is needed
afterwards. A developer checkout already has both in its own environment.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from api.services import coreml_embedder, onnx_embedder, runtime_layout

SMALL_ID = onnx_embedder.DEFAULT_ID
LARGE_ID = "google/embeddinggemma-300m"
#: EmbeddingGemma 2 on the Neural Engine at 768 dimensions — the width is part of the id, so a table records
#: exactly which vector space it holds (768: best or tied on every set the spike ran; 21,500 vectors are 66 MB).
PREFERRED_ID = onnx_embedder.PREFERRED_ID
#: Models Cicada picked as its own default before 2026-10-09. A bank that records one of them — and that nobody
#: chose for it — moves to ``PREFERRED_ID`` once this Mac runs it.
FORMER_DEFAULTS = (SMALL_ID, LARGE_ID)
#: What the extras install puts beside the bundled packages: sentence-transformers and
#: what it needs beyond the bundled set, at the developer lock's versions, hashed
#: (``scripts/release/lock-requirements.sh`` writes it; it ships inside ``api/data/``).
EXTRAS_LOCK = Path(__file__).resolve().parents[1] / "data" / "extras-requirements.lock"
INSTALL_TIMEOUT_S = 60 * 60


@dataclass(frozen=True)
class ModelInfo:
    id: str
    label: str
    dimensions: int
    detail: str
    needs_download: bool
    needs_token: bool = False


CATALOG: tuple[ModelInfo, ...] = (
    ModelInfo(PREFERRED_ID, "Neural Engine", 768,
              "Runs on this Mac's Neural Engine. Finds looser matches, across languages. "
              "A one-time download of about 585 MB.", True),
    ModelInfo(SMALL_ID, "Small", 384, "Built in. Quick, reads about 100 languages, good for most memories.", False),
    ModelInfo(LARGE_ID, "Larger", 768, "Finds looser matches. A one-time download of about 2 GB.", True, True),
)


def _home(environ=os.environ) -> Path:
    return runtime_layout.cicada_home(environ)


def choices_path(environ=os.environ) -> Path:
    return _home(environ) / "embedding-models.json"


def models_path(environ=os.environ) -> Path:
    return _home(environ) / "models.json"


def extras_site(environ=os.environ) -> Path:
    return _home(environ) / "extras" / "site-packages"


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _bank_key(bank: Path) -> str:
    return str(Path(bank).expanduser().resolve())


def bank_choice(bank: Path, environ=os.environ) -> str | None:
    value = _read_json(choices_path(environ)).get(_bank_key(bank))
    return value if isinstance(value, str) and value else None


def set_bank_choice(bank: Path, model_id: str | None, environ=os.environ) -> None:
    data = _read_json(choices_path(environ))
    if model_id:
        data[_bank_key(bank)] = model_id
    else:
        data.pop(_bank_key(bank), None)
    _write_json(choices_path(environ), data)


def local_model_path(model_id: str, environ=os.environ) -> str | None:
    """The folder a downloaded model was saved to, when it is still there."""
    value = _read_json(models_path(environ)).get(model_id)
    return value if isinstance(value, str) and Path(value).is_dir() else None


def sentence_transformers_available() -> bool:
    importlib.invalidate_caches()
    return importlib.util.find_spec("sentence_transformers") is not None


def is_available(model_id: str, environ=os.environ) -> bool:
    """Whether this machine can embed with ``model_id`` right now, without asking anyone."""
    from api.services import providers

    mid = (model_id or "").strip()
    if not mid:
        return False
    if onnx_embedder.find(mid, environ) is not None:
        return True
    if is_neural_engine_model(mid):
        return False  # only ever its downloaded Core ML folder (above), on a Mac that runs it
    if providers._model_is_openai(mid):
        return bool((environ.get("OPENAI_API_KEY") or "").strip())
    if providers._model_is_openrouter(mid):
        return bool((environ.get("OPENROUTER_API_KEY") or "").strip())
    if mid == SMALL_ID:
        return False  # only ever the bundled ONNX copy (above) — never a download through sentence-transformers
    if not sentence_transformers_available():
        return False
    if mid == LARGE_ID:
        # Gated: loadable only from the folder the download saved, or a copy already in the Hugging Face cache.
        return local_model_path(mid, environ) is not None or (
            not runtime_layout.is_release(environ) and _in_hf_cache(mid))
    return True


def is_neural_engine_model(model_id: str | None) -> bool:
    return onnx_embedder.base_id(model_id or "").lower() == onnx_embedder.PREFERRED_BASE


def neural_engine_supported() -> bool:
    return coreml_embedder.supported()


def _in_hf_cache(model_id: str) -> bool:
    try:
        from huggingface_hub import try_to_load_from_cache

        return isinstance(try_to_load_from_cache(model_id, "config.json"), str)
    except Exception:  # noqa: BLE001 — no hub, no cache: not available
        return False


def recorded_model(bank: Path) -> str | None:
    try:
        from api.services.vector_index import SqliteVecIndexer

        model = (SqliteVecIndexer(Path(bank)).index_info() or {}).get("model")
    except Exception as exc:  # noqa: BLE001 — a missing or locked index is "nothing recorded"
        logger.debug(f"embedding_models: no recorded model for {bank}: {exc}")
        return None
    return model if model and model != "unknown" else None


def _explicitly_configured(settings) -> bool:
    fields = getattr(settings, "model_fields_set", set())
    return bool({"embedding_mode", "embedding_model", "embedding_model_local", "embedding_model_openrouter"} & fields)


def build_model(bank: Path, settings, environ=os.environ) -> str:
    """The model ``bank``'s vectors are built with (see the module docstring)."""
    choice = bank_choice(bank, environ)
    if choice and is_available(choice, environ):
        return choice
    if not _explicitly_configured(settings):
        recorded = recorded_model(bank)
        default = settings.resolved_embedding_model
        if recorded and is_available(recorded, environ):
            if recorded in FORMER_DEFAULTS and default == PREFERRED_ID and recorded != default:
                return default   # Cicada's own old default gives way to the better model once it runs here
            return recorded
        if recorded == LARGE_ID or is_neural_engine_model(recorded):
            # A bank built with a downloaded model keeps it even where it isn't here (yet): its vectors are left
            # as they are (search falls back to words, and Settings offers the download) rather than re-embedded
            # with another model behind the person's back.
            return recorded
    return settings.resolved_embedding_model


def pending_switch(bank: Path, settings, environ=os.environ) -> tuple[str, list[str]] | None:
    """``(model, kinds)`` when some vector table holds another model than the one ``bank`` is built with and
    that model runs here — what the background re-embed would do — else None."""
    from api.services.vector_index import SqliteVecIndexer

    target = build_model(bank, settings, environ)
    if not is_available(target, environ):
        return None
    stale = [kind for kind, model in SqliteVecIndexer(Path(bank)).table_models().items() if model != target]
    return (target, stale) if stale else None


# --------------------------------------------------------------------------- #
# The optional larger model: one install at a time, in the background
# --------------------------------------------------------------------------- #

@dataclass
class InstallJob:
    state: str = "idle"            # idle | installing | done | failed
    step: str = ""                 # what it is doing now, in words
    error: str = ""
    started_at: float | None = None
    finished_at: float | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def snapshot(self) -> dict:
        with self._lock:
            return {"state": self.state, "step": self.step, "error": self.error}

    def _set(self, **kw) -> None:
        with self._lock:
            for k, v in kw.items():
                setattr(self, k, v)


JOB = InstallJob()


def _pip_install(target: Path, environ) -> None:
    """sentence-transformers (with torch) into ``target`` with the running interpreter's pip: exactly the
    hashed packages in ``EXTRAS_LOCK`` and nothing else (``--no-deps``) — the bundled packages it shares are
    already present and resolve first, so nothing installed here shadows one with another version."""
    env = {k: v for k, v in environ.items() if not k.startswith("PIP_")}
    env["PYTHONNOUSERSITE"] = "1"
    try:
        done = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-input", "--no-cache-dir",
             "--only-binary", ":all:", "--require-hashes", "--no-deps", "--target", str(target),
             "-r", str(EXTRAS_LOCK)],
            capture_output=True, text=True, timeout=INSTALL_TIMEOUT_S, env=env)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("The install took over an hour and was stopped. Check your connection and try again.") from exc
    if done.returncode != 0:
        tail = (done.stderr or done.stdout).strip().splitlines()[-1:] or [""]
        logger.warning(f"embedding_models: pip failed: {tail[0][:300]}")
        raise RuntimeError("Couldn't install the larger model's runtime. Check your connection and free space, "
                           "then try again.")


def _download_model(token: str, environ) -> str:
    """The gated model's files, fetched once with the person's own token (never stored)."""
    from huggingface_hub import snapshot_download
    from huggingface_hub.utils import GatedRepoError, HfHubHTTPError

    dest = _home(environ) / "models" / LARGE_ID.replace("/", "--")
    try:
        path = snapshot_download(LARGE_ID, token=token, local_dir=str(dest))
    except GatedRepoError as exc:
        raise RuntimeError("Your Hugging Face account hasn't accepted this model's license yet — accept it on the "
                           "model's page, then try again.") from exc
    except HfHubHTTPError as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (401, 403):
            raise RuntimeError("Hugging Face didn't accept that token. Check it has read access and try again.") from exc
        raise RuntimeError("The download stopped. Check your connection and try again.") from exc
    except OSError as exc:
        raise RuntimeError("The download couldn't be saved. Check the free space on this Mac and try again.") from exc
    return str(path)


def _run_install(token: str, environ) -> None:
    JOB._set(state="installing", step="Preparing", error="", started_at=time.time(), finished_at=None)
    staging = extras_site(environ).with_name("site-packages.partial")
    try:
        if not sentence_transformers_available():
            site = extras_site(environ)
            shutil.rmtree(staging, ignore_errors=True)
            JOB._set(step="Installing the model's runtime (about 1 GB)")
            _pip_install(staging, environ)
            shutil.rmtree(site, ignore_errors=True)
            staging.rename(site)
            import site as site_module

            site_module.addsitedir(str(site))
            if not sentence_transformers_available():
                raise RuntimeError("The runtime installed but can't be loaded; open Cicada again and retry.")
        JOB._set(step="Downloading the model (about 1.2 GB)")
        path = _download_model(token, environ)
        data = _read_json(models_path(environ))
        data[LARGE_ID] = path
        _write_json(models_path(environ), data)
        JOB._set(state="done", step="", finished_at=time.time())
        logger.info("embedding_models: the larger model is installed")
    except Exception as exc:  # noqa: BLE001 — every failure becomes a sentence the person reads
        message = str(exc) if isinstance(exc, RuntimeError) else "The install stopped unexpectedly. Try again."
        shutil.rmtree(staging, ignore_errors=True)  # never leave a half-installed gigabyte behind
        JOB._set(state="failed", step="", error=message, finished_at=time.time())
        logger.warning(f"embedding_models: install failed: {type(exc).__name__}")


def start_install(token: str, environ=os.environ) -> bool:
    """Start the larger model's install in the background; False when one is already running."""
    with JOB._lock:
        if JOB.state == "installing":
            return False
        JOB.state = "installing"
    threading.Thread(target=_run_install, args=(token, environ), name="cicada-embedding-install", daemon=True).start()
    return True


# --------------------------------------------------------------------------- #
# EmbeddingGemma 2: the one-click download (no account, no token)
# --------------------------------------------------------------------------- #

def _run_download(bank: Path | None, settings, environ) -> None:
    from api.services import model_fetch

    JOB._set(state="installing", step="Preparing", error="", started_at=time.time(), finished_at=None)

    def progress(phase: str, done: int, total: int) -> None:
        if phase == "download":
            JOB._set(step=f"Downloading the search model ({done / 1e6:.0f} of {total / 1e6:.0f} MB)")
        elif phase == "prepare":
            JOB._set(step="Checking and preparing the search model")
        elif phase == "warm":
            JOB._set(step="Getting the search model ready on this Mac (about a minute and a half, once)")

    try:
        model_fetch.install(_home(environ) / "models", progress=progress)
        JOB._set(state="done", step="", finished_at=time.time())
        logger.info("embedding_models: the Neural Engine search model is installed")
    except Exception as exc:  # noqa: BLE001 — every failure becomes a sentence the person reads
        message = str(exc) if isinstance(exc, model_fetch.FetchError) else "The download stopped unexpectedly. Try again."
        JOB._set(state="failed", step="", error=message, finished_at=time.time())
        logger.warning(f"embedding_models: download failed: {type(exc).__name__}")
        return
    if bank is not None and settings is not None:
        start_reindex_if_needed(bank, settings, environ)


def start_download(bank: Path | None = None, settings=None, environ=os.environ) -> bool:
    """Start EmbeddingGemma 2's download in the background; False when an install is already running."""
    with JOB._lock:
        if JOB.state == "installing":
            return False
        JOB.state = "installing"
    threading.Thread(target=_run_download, args=(bank, settings, environ), name="cicada-embedding-download",
                     daemon=True).start()
    return True


# --------------------------------------------------------------------------- #
# The background re-embed after a model change
# --------------------------------------------------------------------------- #

#: The kinds in the order the re-embed rebuilds them: pages first (what recall leans on most), passages last
#: (the bulk: about 4 minutes of the owner-sized bank's 5).
REINDEX_ORDER = ("entities", "claims", "pending", "episodes")


@dataclass
class ReindexJob:
    state: str = "idle"            # idle | running | waiting | done | failed
    bank: str = ""
    model: str = ""
    done: int = 0                  # tables re-embedded so far
    total: int = 0
    error: str = ""
    started_at: float | None = None
    finished_at: float | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def snapshot(self, bank: Path | None = None) -> dict:
        with self._lock:
            if bank is not None and self.bank and self.bank != _bank_key(bank):
                return {"state": "idle", "model": "", "done": 0, "total": 0, "error": ""}
            return {"state": self.state, "model": self.model, "done": self.done, "total": self.total,
                    "error": self.error}

    def _set(self, **kw) -> None:
        with self._lock:
            for k, v in kw.items():
                setattr(self, k, v)


REINDEX = ReindexJob()


REINDEX_ENV = "CICADA_BACKGROUND_REINDEX"


def background_reindex_enabled(environ=os.environ) -> bool:
    """``CICADA_BACKGROUND_REINDEX=off`` turns the background re-embed off: a model change then happens inside the
    next Sleep's index step, as it did before (the suite runs with it off; its own tests turn it on)."""
    return (environ.get(REINDEX_ENV) or "").strip().lower() not in ("off", "0", "false", "no")


def reindexes_in_background(model_id: str | None, environ=os.environ) -> bool:
    """Whether a switch TO ``model_id`` is the background job's: an on-device model folder (the bundled small
    model, EmbeddingGemma 2) that runs here, with the job on. A switch to anything else (a hosted model, a
    sentence-transformers id) still happens in Sleep's index step."""
    return bool(model_id) and background_reindex_enabled(environ) and onnx_embedder.find(model_id, environ) is not None


def _sleep_running() -> bool:
    from api.services import sleep_cycle

    return sleep_cycle.get_sleep_state().status == "running"


def start_reindex_if_needed(bank: Path, settings, environ=os.environ) -> bool:
    """Start the background re-embed when a table holds another model than the bank's (``pending_switch``).
    Never while Sleep runs: then it waits, and the end of the run starts it. Never raises."""
    try:
        pending = pending_switch(Path(bank), settings, environ)
    except Exception as exc:  # noqa: BLE001 — a locked or unreadable index: try at the next trigger
        logger.debug(f"embedding_models: no re-embed check: {type(exc).__name__}")
        return False
    if pending is None:
        return False
    target, kinds = pending
    if not reindexes_in_background(target, environ):
        return False
    with REINDEX._lock:
        if REINDEX.state == "running":
            return False
        if _sleep_running():
            REINDEX.state, REINDEX.bank, REINDEX.model = "waiting", _bank_key(bank), target
            REINDEX.done, REINDEX.total, REINDEX.error = 0, len(kinds), ""
            return False
        REINDEX.state, REINDEX.bank, REINDEX.model = "running", _bank_key(bank), target
        REINDEX.done, REINDEX.total, REINDEX.error = 0, len(kinds), ""
        REINDEX.started_at, REINDEX.finished_at = time.time(), None
    threading.Thread(target=_run_reindex, args=(Path(bank), settings, kinds), name="cicada-reindex",
                     daemon=True).start()
    return True


def _run_reindex(bank: Path, settings, kinds: list[str]) -> None:
    from api.services import embedding_health
    from api.services.vector_index import IndexSyncStopped, SqliteVecIndexer

    started = time.monotonic()
    indexer = SqliteVecIndexer(bank, should_stop=_sleep_running)
    steps = {"entities": indexer.index_entities, "claims": indexer.index_claims,
             "pending": indexer.rebuild_pending_index, "episodes": indexer.index_episodes}
    try:
        for kind in (k for k in REINDEX_ORDER if k in kinds):
            if _sleep_running():
                raise IndexSyncStopped("Sleep started")
            steps[kind]()
            REINDEX._set(done=REINDEX.done + 1)
        REINDEX._set(state="done", finished_at=time.time())
        embedding_health.clear(bank)
        logger.info(f"embedding_models: search re-embedded with {indexer.model_name} in "
                    f"{time.monotonic() - started:.0f}s")
    except IndexSyncStopped:
        REINDEX._set(state="waiting")
        logger.info("embedding_models: re-embed paused for Sleep; it resumes when the run ends")
    except Exception as exc:  # noqa: BLE001 — the old tables stay as they were; said in words
        kind = embedding_health.classify(exc)
        REINDEX._set(state="failed", finished_at=time.time(),
                     error=embedding_health.sentence(kind) if kind else
                     "Search couldn't move to the new model; it keeps the one it had. The next Sleep tries again.")
        logger.warning(f"embedding_models: re-embed failed: {type(exc).__name__}")
        return
    # The person may have picked another model while this ran: one more look — only for a model other than the
    # one just built, so a table that cannot move never loops the job.
    try:
        again = pending_switch(bank, settings)
    except Exception:  # noqa: BLE001
        again = None
    if again is not None and again[0] != indexer.model_name:
        start_reindex_if_needed(bank, settings)


def status(bank: Path, settings, environ=os.environ) -> dict:
    """What Settings → Memory → Search model shows for the active bank."""
    building = build_model(bank, settings, environ)
    recorded = recorded_model(bank)
    choice = bank_choice(bank, environ)
    supported = neural_engine_supported()
    keep = {recorded, choice, building}
    offered = [m for m in CATALOG
               if not (m.id == PREFERRED_ID and not supported and m.id not in keep)
               and not (m.id == LARGE_ID and supported and m.id not in keep and not is_available(m.id, environ))]
    return {
        "model": recorded or building,
        "next_model": building,
        "choice": choice,
        "release": runtime_layout.is_release(environ),
        "recommended": PREFERRED_ID if supported and not is_available(PREFERRED_ID, environ) else None,
        "models": [
            {"id": m.id, "label": m.label, "dimensions": m.dimensions, "detail": m.detail,
             "needs_download": m.needs_download, "needs_token": m.needs_token,
             "available": is_available(m.id, environ)}
            for m in offered
        ],
        "install": JOB.snapshot(),
        "reindex": REINDEX.snapshot(bank),
    }
