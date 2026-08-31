"""Injectable HTTP seam + network gate shared by every connector."""

from __future__ import annotations

import inspect
import os
from pathlib import Path
from typing import Any, Awaitable, Callable

from loguru import logger

# Called as ``http_fn(method, url, *, headers=None, params=None, data=None,
# auth=None) -> dict``. May be sync or async: tests inject plain functions, the
# real default is async.
HttpFn = Callable[..., Any]

# ``fetch(fn) -> (items, extra)``: the one per-platform coroutine `run_sync`
# wraps. `items` is the list of `RawItem`s to ingest; `extra` is whatever
# `sync_state.record_sync` should persist alongside the count (a cursor dict,
# e.g. ``{"last_seen_id": ...}``) or `None`.
FetchFn = Callable[[HttpFn], Awaitable[tuple[list, dict | None]]]

GATE_ENV = "CICADA_ALLOW_CONNECTOR_FETCH"
TIMEOUT_SECONDS = 15.0


class ConnectorError(RuntimeError):
    """A sync could not complete — recorded, never raised past ``sync()``."""


def network_allowed(allow_fetch: bool | None = None) -> bool:
    """Whether the DEFAULT transport may run. An injected ``http_fn`` bypasses
    this entirely — the caller has supplied the mechanism, so there is nothing
    left to gate."""
    if allow_fetch is not None:
        return bool(allow_fetch)
    return os.environ.get(GATE_ENV) == "1"


async def default_http(
    method: str,
    url: str,
    *,
    headers: dict | None = None,
    params: dict | None = None,
    data: dict | None = None,
    auth: tuple[str, str] | None = None,
) -> dict:
    """The gated live-HTTP transport. Only ever invoked when the gate is open."""
    import httpx

    async with httpx.AsyncClient(follow_redirects=True) as client:
        resp = await client.request(
            method, url, headers=headers, params=params, data=data,
            auth=auth, timeout=TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return resp.json()


async def call_http(http_fn: HttpFn, method: str, url: str, **kwargs) -> dict:
    """Call ``http_fn`` and await it if it returned a coroutine."""
    result = http_fn(method, url, **kwargs)
    if inspect.isawaitable(result):
        result = await result
    return result


async def run_sync(
    channel_id: str,
    memory_path: Path,
    fetch: FetchFn,
    *,
    http_fn: HttpFn | None = None,
    allow_fetch: bool | None = None,
    is_connected: Callable[[], bool],
) -> dict:
    """The ``sync()`` skeleton every connector shares (Task 15 §2).

    ``fetch(fn) -> (items, extra)`` is the ONLY per-platform coroutine a
    connector still writes by hand — everything else (the not-connected
    skip, the network-gate skip, the try/except that turns any exception
    into a recorded, never-raised error, the ingest + ``record_sync`` on
    success) lives here exactly once instead of duplicated three times.

    Canonical return: ``{"status": "ok"|"skipped"|"error", "reason",
    "new", "seen", "error"}``. No platform-specific counters (a
    ``boards``/``pages`` count) ride this dict — a connector that wants to
    surface one logs it at the ``fetch`` call site instead; a caller that
    wants an ADDITIONAL field (X's ``resources_read``, billed-read honesty)
    adds it to the dict this returns after calling in.
    """
    from api.services import media_ingestor, sync_state

    empty = {"new": 0, "seen": 0, "error": None}
    if not is_connected():
        return {"status": "skipped", "reason": "not connected", **empty}
    if http_fn is None and not network_allowed(allow_fetch):
        return {"status": "skipped", "reason": "network disabled", **empty}

    fn = http_fn or default_http
    try:
        items, extra = await fetch(fn)
    except Exception as e:
        message = f"{type(e).__name__}: {e}"
        logger.warning(f"{channel_id} sync failed: {message}")
        sync_state.record_error(memory_path, channel_id, message)
        return {"status": "error", "reason": None, **empty, "error": message}

    created, _ = await media_ingestor.ingest_batch(
        items[: media_ingestor.MAX_BATCH], memory_path, from_bookmark_file=False
    )
    sync_state.record_sync(memory_path, channel_id, count=len(items), extra=extra)
    return {"status": "ok", "reason": None, "new": created, "seen": len(items), "error": None}


def forget(secret_names: tuple[str, ...]) -> None:
    """Remove every credential an adapter declares (Task 15 §4).

    Shared by every adapter's ``forget()`` so a FIELDS-vs-what's-actually-
    stored drift (a derived token an adapter forgot to list separately from
    FIELDS) can't leave an orphaned secret behind after a disconnect — the
    single ``SECRET_NAMES`` tuple each adapter declares is both "what
    ``forget()`` deletes" and "what the registry completeness test checks",
    so the two can never drift apart.
    """
    from api.services.connections import secrets

    for name in secret_names:
        secrets.remove_secret(name)
