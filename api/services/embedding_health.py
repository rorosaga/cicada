"""Whether search's embedder is working, per bank, in words the person reads.

A hosted embedder that runs out of credits used to fail every index step of a whole
consolidation run with a raw HTTP error that lived only in memory, while recall quietly
answered on words alone. This module turns such a failure into one plain sentence,
remembers it per bank in ``$CICADA_HOME/embedding-health.json`` — outside every bank and
every git repo, ids and enums only (the bank's path, the model id, a kind, a time) — and
forgets it at the next sync that brings the index up to date.

Readers: Sleep's index step (``sleep_cycle._sync_vector_indexes``) records and clears;
search records a failed query embed; ``/sleep/status`` shows the sentence as its
``indexWarning`` after a restart; ``/healthz`` carries the kind for doctor.

The copy is provider-neutral (owner, 2026-09-30): it describes the step, never names
who runs it.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from api.services import runtime_layout

FILE_NAME = "embedding-health.json"

KINDS = ("credits", "rate_limited", "auth", "unreachable", "unavailable", "model_missing")

_LEAD = "Search by meaning wasn't updated"
_TAIL = "Search still finds exact words."
_SENTENCES = {
    "credits": f"{_LEAD}: the embedding service says the account is out of credits. {_TAIL} "
               "Add credits, or switch search to run on this Mac.",
    "rate_limited": f"{_LEAD}: the embedding service is limiting requests. {_TAIL} "
                    "The next Sleep tries again.",
    "auth": f"{_LEAD}: the embedding service didn't accept the key. {_TAIL} "
            "Check the key, or switch search to run on this Mac.",
    "unreachable": f"{_LEAD}: the embedding service couldn't be reached. {_TAIL} "
                   "The next Sleep tries again.",
    "unavailable": f"{_LEAD}: the embedding service is down for now. {_TAIL} The next Sleep tries again.",
    "model_missing": f"{_LEAD}: the search model isn't installed on this Mac. {_TAIL} "
                     "Run `make embedding-model` in a developer checkout, or pick a model in Settings.",
}

_CREDIT_WORDS = ("insufficient_quota", "exceeded your current quota", "credit", "payment required",
                 "billing", "insufficient funds", "out of quota")
_lock = threading.Lock()


def sentence(kind: str) -> str:
    return _SENTENCES[kind]


def _status_code(exc: BaseException) -> int | None:
    for candidate in (getattr(exc, "status_code", None),
                      getattr(getattr(exc, "response", None), "status_code", None)):
        try:
            if candidate is not None:
                return int(candidate)
        except (TypeError, ValueError):
            continue
    return None


def _body(exc: BaseException) -> str:
    text = str(exc)
    response = getattr(exc, "response", None)
    try:
        text += " " + (response.text or "")
    except Exception:  # noqa: BLE001 — a response without a body is just the message
        pass
    return text.lower()


def classify(exc: BaseException) -> str | None:
    """The kind of an embedding failure, or None when it is not recognisably the embedder's
    (a locked index, a bug) — those keep their raw warning and are never recorded."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:   # an SDK may wrap the transport's error
        seen.add(id(current))
        kind = _classify_one(current)
        if kind:
            return kind
        current = current.__cause__ or current.__context__
    return None


def _classify_one(exc: BaseException) -> str | None:
    status = _status_code(exc)
    if status == 402:
        return "credits"
    if status == 429:
        return "credits" if any(w in _body(exc) for w in _CREDIT_WORDS) else "rate_limited"
    if status in (401, 403):
        return "auth"
    if status is not None and 500 <= status < 600:
        return "unavailable"
    if isinstance(exc, ImportError):
        return "model_missing"
    name = type(exc).__name__
    if name in ("GatedRepoError", "RepositoryNotFoundError", "LocalEntryNotFoundError"):
        return "model_missing"
    if isinstance(exc, (ConnectionError, TimeoutError)) or name in (
            "ConnectionError", "Timeout", "ConnectTimeout", "ReadTimeout", "APIConnectionError", "APITimeoutError"):
        return "unreachable"
    return None


def _path(environ=os.environ) -> Path:
    return runtime_layout.cicada_home(environ) / FILE_NAME


def _key(bank: Path) -> str:
    return str(Path(bank).expanduser().resolve())


def _read(environ=os.environ) -> dict:
    try:
        data = json.loads(_path(environ).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(data: dict, environ=os.environ) -> None:
    path = _path(environ)
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


def record(bank: Path, model: str | None, kind: str, environ=os.environ) -> None:
    """Remember that ``bank``'s embedder failed with ``kind``; a write only when something changed."""
    if kind not in KINDS:
        return
    with _lock:
        data = _read(environ)
        key = _key(bank)
        entry = data.get(key) or {}
        model = model or entry.get("model")  # a query-side failure may not know the model; keep the known one
        if entry.get("kind") == kind and entry.get("model") == (model or None):
            return
        data[key] = {"kind": kind, "model": model or None,
                     "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        try:
            _write(data, environ)
        except OSError:
            pass  # a status file must never be why indexing or search fails


def clear(bank: Path, environ=os.environ) -> None:
    with _lock:
        data = _read(environ)
        if data.pop(_key(bank), None) is None:
            return
        try:
            _write(data, environ)
        except OSError:
            pass


def problem(bank: Path, environ=os.environ) -> dict | None:
    """``{"kind", "model", "at"}`` for ``bank``'s last unresolved embedding failure, else None."""
    entry = _read(environ).get(_key(bank))
    if not isinstance(entry, dict) or entry.get("kind") not in KINDS:
        return None
    return entry
