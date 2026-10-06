"""Which embedding model each bank is built with, and the optional larger one (G182 phase 3).

Owner's decision (2026-10-05): a fresh install embeds with a small, open, ungated
model on a light runtime — the release app bundles ``BAAI/bge-small-en-v1.5`` as ONNX
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

from api.services import onnx_embedder, runtime_layout

SMALL_ID = onnx_embedder.DEFAULT_ID
LARGE_ID = "google/embeddinggemma-300m"
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


CATALOG: tuple[ModelInfo, ...] = (
    ModelInfo(SMALL_ID, "Small", 384, "Built in. Quick, and good for most memories.", False),
    ModelInfo(LARGE_ID, "Larger", 768, "Finds looser matches. A one-time download of about 2 GB.", True),
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
        if recorded and is_available(recorded, environ):
            return recorded
        if recorded == LARGE_ID:
            # A bank built with the larger model keeps it even where it isn't installed yet: its vectors are left as
            # they are (search falls back to words, and Settings offers the install) rather than re-embedded with
            # another model behind the person's back.
            return recorded
    return settings.resolved_embedding_model


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


def status(bank: Path, settings, environ=os.environ) -> dict:
    """What Settings → Memory → Search model shows for the active bank."""
    building = build_model(bank, settings, environ)
    recorded = recorded_model(bank)
    return {
        "model": recorded or building,
        "next_model": building,
        "choice": bank_choice(bank, environ),
        "release": runtime_layout.is_release(environ),
        "models": [
            {"id": m.id, "label": m.label, "dimensions": m.dimensions, "detail": m.detail,
             "needs_download": m.needs_download, "available": is_available(m.id, environ)}
            for m in CATALOG
        ],
        "install": JOB.snapshot(),
    }
