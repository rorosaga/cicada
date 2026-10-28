"""Ruling 47, tier 2 — one framework for an official API the person connects for a high-value source.

Tier 1 (the person's own browser and Mac) is the default way in; tier 2 is for a source whose official API gives what
the harness cannot — the whole history, its metadata, a reliable read. The first two built on this module are
Readwise (``readwise.py``) and Notion (``notion.py``); Telegram (47a) has its own client. Each adapter is a module in
``ADAPTERS`` like the saved-content connectors (so the Sources row, the credential routes, Disconnect and Refresh are
the existing ones), and declares ``TIER = 2``; what differs is everything after the fetch:

* **The normal capture path.** An adapter returns :class:`Batch` — :class:`~api.services.episode_staging.EpisodeDraft`
  s, one per natural unit, keyed by the service's own id — and this module stages them through ``episode_staging``
  (scrubbed, hashed, an edit rewrites in place and re-queues, a deletion is tombstoned and kept), then commits exactly
  the paths it wrote under ``user`` (``folder_source.commit_paths_for``). No model runs here. A demo bank takes in
  nothing.
* **It yields to Sleep (G177/G183).** The fetch runs first, holding nothing. The staging and its commit then run as one
  admitted transaction (``write_admission.run_admitted``): while Sleep holds the bank's pages the transaction is
  refused before it writes, nothing is staged, the service's cursor does not move, and the next sync fetches the same
  items again. A scheduled sync does not even start its fetch while Sleep is writing. Sleep's own tail never runs a
  tier-2 sync (``sleep_cycle._poll_connectors_safely`` skips ``TIER == 2``): they run on their own schedule
  (:func:`scheduled_sync`), so a sync is never part of a Sleep run.
* **Gates.** A sync the person started (Refresh, ``cicada connector sync``) is their click and is never gated. A
  scheduled one is a fetch Cicada starts on its own: behind ``CICADA_ALLOW_CONNECTOR_FETCH`` (``base.network_allowed``,
  opt-out like every connector), recorded as a skip, never silently.
* **Credentials** are the person's own token, in ``$CICADA_HOME/secrets.env`` (0600) through ``connections.secrets``:
  never in a bank, a log, an error line or a response. A token is checked against the service before it is saved
  (:func:`check_before_save`, the person's Save). Disconnect forgets every name the adapter declares. A connector
  token is stripped from every engine child (``connections.base.SCRUBBED_ENV_KEYS``).
* **Errors in words.** :class:`Refused` carries the sentence the person reads (what happened, what to do); anything
  else is recorded as the service's name and an HTTP status — never a URL, a body or a token
  (``sync_state.json`` lives in the bank and is committed).
* **Only the service's own host.** :class:`Client` refuses any URL off the adapter's ``API_BASE``, follows no redirect,
  sends no cookie, and honours a 429's ``Retry-After`` once (at most ``MAX_RETRY_AFTER_S``) before giving up in words.
  Nothing a request sends names a person: the adapters ask for the person's own account data only (ruling 44's guard).
* **The cursor lives outside the bank** (``$CICADA_HOME/connectors/``, keyed by the bank's resolved path): ids and
  times only. A bank that holds none of the connector's episodes reads its cursor as empty, so a new or reset bank
  gets the full history again rather than nothing.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Awaitable, Callable

from loguru import logger

from api.services import episode_staging
from api.services.connectors import base

TIER = 2
#: How often the scheduled sync runs (the backend's scheduler, ``api/main.py``).
SCHEDULE_HOURS = 6
TIMEOUT_SECONDS = 15.0
MAX_RETRY_AFTER_S = 60.0
#: What the person reads when a sync waited for Sleep.
WAITED_FOR_SLEEP = "Sleep was reading your memory, so nothing was saved this time; the next sync picks it up."
#: What a scheduled sync records when the connector gate is closed.
GATE_CLOSED = "network fetch disabled"


class Refused(base.ConnectorError):
    """A failure the person can act on, already in their words (a refused token, a rate limit, no network)."""

    def __init__(self, words: str, *, kind: str = "other"):
        super().__init__(words)
        self.words = words
        self.kind = kind


@dataclass
class Response:
    status: int
    body: Any = None
    headers: dict = field(default_factory=dict)


#: ``transport(method, url, *, headers, params=None, json=None) -> Response`` (sync or async). Tests inject a fake;
#: :func:`http_transport` is the only code path that reaches a network.
Transport = Callable[..., Any]


async def http_transport(method: str, url: str, *, headers: dict, params: dict | None = None,
                         json: dict | None = None) -> Response:
    """The live transport: a fresh client per call (no cookie jar survives), no redirects, the module timeout."""
    import httpx

    async with httpx.AsyncClient(follow_redirects=False, timeout=TIMEOUT_SECONDS) as client:
        resp = await client.request(method, url, headers=headers, params=params, json=json)
    body: Any = None
    if resp.content:
        try:
            body = resp.json()
        except ValueError:
            body = None
    return Response(resp.status_code, body, {k.lower(): v for k, v in resp.headers.items()})


class Client:
    """One sync's requests to one service: its host only, its auth header, a request count, one wait on a 429."""

    def __init__(self, adapter: ModuleType, token: str, transport: Transport | None = None, *,
                 sleep: Callable[[float], Awaitable[None]] | None = None):
        self.adapter = adapter
        self._token = token
        self._transport = transport or http_transport
        self._sleep = sleep
        self.requests = 0

    async def request(self, method: str, path: str, *, params: dict | None = None, json: dict | None = None) -> Any:
        base_url = self.adapter.API_BASE
        url = path if path.startswith("https://") else base_url + path
        if not url.startswith(base_url):
            raise base.ConnectorError(f"{self.adapter.LABEL}: a request off its own host was refused")
        headers = dict(self.adapter.auth_headers(self._token))
        for attempt in (1, 2):
            self.requests += 1
            resp = self._transport(method, url, headers=headers, params=params, json=json)
            if inspect.isawaitable(resp):
                resp = await resp
            if resp.status == 429 and attempt == 1:
                await (self._sleep or wait)(_retry_after(resp.headers))
                continue
            return _answer(self.adapter, resp)
        raise AssertionError("unreachable")

    async def get(self, path: str, **params) -> Any:
        return await self.request("GET", path, params={k: v for k, v in params.items() if v is not None} or None)

    async def post(self, path: str, body: dict) -> Any:
        return await self.request("POST", path, json=body)


async def wait(seconds: float) -> None:
    """A 429's wait (module-level, so the suite stands in for it)."""
    await asyncio.sleep(seconds)


def _retry_after(headers: dict) -> float:
    try:
        wait = float((headers or {}).get("retry-after") or 1)
    except (TypeError, ValueError):
        wait = 1.0
    return max(0.0, min(wait, MAX_RETRY_AFTER_S))


def _answer(adapter: ModuleType, resp: Response) -> Any:
    if resp.status in (401, 403):
        raise Refused(adapter.REFUSED_WORDS, kind="sign-in")
    if resp.status == 429:
        raise Refused(f"{adapter.LABEL} asked Cicada to slow down; the next sync carries on from here.", kind="rate")
    if resp.status >= 400:
        raise base.ConnectorError(f"{adapter.LABEL} answered HTTP {resp.status}")
    return resp.body


# --- what an adapter hands back ------------------------------------------------------------------------------------


@dataclass
class Batch:
    """One fetch's result, before anything is written.

    ``drafts`` are the units to stage. ``replaced`` are group prefixes (a Readwise book, a Notion page) whose every
    unit is in ``drafts``: any stored unit of that group not among them is gone at the service and is tombstoned.
    ``deleted`` are groups the service says were deleted outright. ``cursor`` is saved only once the staging
    committed. ``words`` is an optional line for the Sources row (a cap reached, a shared workspace)."""

    drafts: list[episode_staging.EpisodeDraft] = field(default_factory=list)
    replaced: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    cursor: dict = field(default_factory=dict)
    seen: int = 0
    words: str | None = None


def in_group(source_id: str, prefix: str) -> bool:
    """A unit of ``prefix``'s group: the prefix itself, or the prefix followed by ``:`` or ``#`` (so ``readwise:12``
    never claims ``readwise:123:…``)."""
    return source_id == prefix or (source_id.startswith(prefix) and source_id[len(prefix)] in ":#")


# --- the cursor, outside the bank ----------------------------------------------------------------------------------


def _cursor_path(channel: str, memory_path: Path) -> Path:
    from api.services.auth import cicada_home

    key = hashlib.sha256(str(Path(memory_path).resolve()).encode()).hexdigest()[:12]
    return cicada_home() / "connectors" / f"{channel}-{key}.json"


def read_cursor(channel: str, memory_path: Path) -> dict:
    try:
        data = json.loads(_cursor_path(channel, memory_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_cursor(channel: str, memory_path: Path, cursor: dict) -> None:
    path = _cursor_path(channel, memory_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".cursor-", text=True)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(cursor, fh, sort_keys=True)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def forget_cursor(channel: str, memory_path: Path) -> None:
    try:
        _cursor_path(channel, memory_path).unlink()
    except OSError:
        pass


# --- connect, disconnect, status -----------------------------------------------------------------------------------


def token(adapter: ModuleType) -> str:
    from api.services.connections import secrets

    return (secrets.load_secrets().get(adapter.TOKEN_ENV) or os.environ.get(adapter.TOKEN_ENV) or "").strip()


def is_connected(adapter: ModuleType) -> bool:
    from api.services.connections import secrets

    return secrets.has_secret(adapter.TOKEN_ENV)


def credential_fields(adapter: ModuleType) -> list[dict]:
    from api.services.connections import secrets

    return [{**f, "present": secrets.has_secret(f["name"])} for f in adapter.FIELDS]


async def check_before_save(adapter: ModuleType, fields: dict[str, str], *,
                            transport: Transport | None = None) -> None:
    """The person's Save: one read-only request to the service's own host with the token they pasted. Raises
    :class:`Refused` (words) when the service refuses it; nothing is saved then. Network trouble is a Refused too: a
    token that was never checked is not saved (the person can try again)."""
    value = (fields.get(adapter.TOKEN_ENV) or "").strip()
    if not value:
        raise Refused(f"Paste your {adapter.LABEL} token first.")
    client = Client(adapter, value, transport)
    try:
        await adapter.check(client)
    except Refused:
        raise
    except Exception as exc:  # noqa: BLE001 — the class only, never the message (it can carry a URL)
        logger.warning(f"{adapter.CHANNEL_ID}: token check failed: {type(exc).__name__}")
        raise Refused(f"Cicada could not reach {adapter.LABEL} to check the token. Nothing was saved; try again.",
                      kind="network")


def forget(adapter: ModuleType) -> None:
    """Disconnect: every credential the adapter declares, and its cursors in every bank — a later connect (perhaps
    another account) starts from the whole history, never from the last account's place."""
    from api.services.auth import cicada_home

    base.forget(adapter.SECRET_NAMES)
    for path in (cicada_home() / "connectors").glob(f"{adapter.CHANNEL_ID}-*.json"):
        try:
            path.unlink()
        except OSError:
            pass


# --- one sync ------------------------------------------------------------------------------------------------------


def _empty(status: str, reason: str | None = None, error: str | None = None) -> dict:
    return {"status": status, "reason": reason, "new": 0, "seen": 0, "error": error, "resources_read": 0}


def _live_units(index: dict, channel: str) -> set[str]:
    return {sid for sid, entry in index.items()
            if entry.fm.get("connector") == channel and not entry.fm.get("source_deleted_at")}


def _stage(adapter: ModuleType, memory_path: Path, batch: Batch, bank: str | None) -> dict:
    episodes_dir = Path(memory_path) / "episodes"
    episodes_dir.mkdir(parents=True, exist_ok=True)
    for draft in batch.drafts:
        draft.extra = {**(draft.extra or {}), "connector": adapter.CHANNEL_ID}
    wanted = {d.source_id for d in batch.drafts if d.source_id}
    with episode_staging.STAGE_LOCK:
        index, _ = episode_staging.scan(episodes_dir)
        live = _live_units(index, adapter.CHANNEL_ID)
        groups = [*batch.replaced, *batch.deleted]
        gone = sorted(sid for sid, entry in index.items()
                      if not entry.fm.get("source_deleted_at") and sid not in wanted
                      and any(in_group(sid, g) for g in groups))
        result = episode_staging.stage(batch.drafts, episodes_dir, deleted_source_ids=gone, bank=bank)
    live = (live | wanted) - set(gone)
    return {"created": result.created, "updated": result.updated, "tombstoned": result.tombstoned,
            "paths": list(result.paths), "live": len(live)}


async def run(adapter: ModuleType, memory_path: Path, *, http_fn: Transport | None = None,
              allow_fetch: bool | None = None, scheduled: bool = False) -> dict:
    """One sync of ``adapter`` into ``memory_path``. Never raises: every outcome is a result dict (the connectors'
    canonical shape, ``resources_read`` = requests made) and a line on the Sources row (``sync_state``)."""
    from api.services import demo_guard, folder_source, sync_state, write_admission

    memory_path = Path(memory_path)
    channel = adapter.CHANNEL_ID
    if not adapter.is_connected():
        return _empty("skipped", "not connected")
    if demo_guard.is_demo(memory_path):
        return _empty("skipped", "the demo memory is open")
    if scheduled:
        if http_fn is None and not base.network_allowed(allow_fetch):
            sync_state.record_skip(memory_path, channel, GATE_CLOSED)
            return _empty("skipped", "network disabled")
        if write_admission.probe():
            sync_state.record_skip(memory_path, channel, WAITED_FOR_SLEEP)
            return _empty("skipped", WAITED_FOR_SLEEP)

    async with base._sync_lock:
        cursor = read_cursor(channel, memory_path)
        if cursor and not (sync_state.read_sync_state(memory_path).get(channel) or {}).get("count"):
            cursor = {}     # a new or reset bank: the whole history again, never nothing
        client = Client(adapter, token(adapter), http_fn)
        started = time.perf_counter()
        try:
            batch: Batch = await adapter.fetch(client, cursor, memory_path)
        except Refused as exc:
            sync_state.record_error(memory_path, channel, exc.words)
            return {**_empty("error", error=exc.words), "resources_read": client.requests}
        except Exception as exc:  # noqa: BLE001
            message = base._sanitize_error(exc) if isinstance(exc, base.ConnectorError) else \
                f"{adapter.LABEL}: the sync stopped ({type(exc).__name__})"
            logger.warning(f"{channel} sync failed: {type(exc).__name__}")
            sync_state.record_error(memory_path, channel, message)
            return {**_empty("error", error=message), "resources_read": client.requests}
        fetched_s = time.perf_counter() - started

        async def transaction() -> dict:
            out = await asyncio.to_thread(_stage, adapter, memory_path, batch, memory_path.name)
            await folder_source.commit_paths_for(memory_path, out["paths"], subject=f"{adapter.LABEL} sync",
                                                 trigger=f"capture/{channel}", channel=channel)
            return out

        try:
            out = await write_admission.run_admitted(memory_path, transaction, refuse=write_admission.SleepHolding)
        except write_admission.SleepHolding:
            sync_state.record_skip(memory_path, channel, WAITED_FOR_SLEEP)
            return {**_empty("skipped", WAITED_FOR_SLEEP), "seen": batch.seen, "resources_read": client.requests}
        except Exception as exc:  # noqa: BLE001
            message = f"{adapter.LABEL}: saving what came in failed ({type(exc).__name__})"
            logger.warning(f"{channel} staging failed: {type(exc).__name__}")
            sync_state.record_error(memory_path, channel, message)
            return {**_empty("error", error=message), "seen": batch.seen, "resources_read": client.requests}

        write_cursor(channel, memory_path, batch.cursor)
        extra = {"words": batch.words} if batch.words else None
        sync_state.record_sync(memory_path, channel, count=out["live"], extra=extra)
        units = len(batch.drafts)
        logger.info(f"{channel}: {units} unit(s) read, {out['created']} new, {out['updated']} changed, "
                    f"{out['tombstoned']} removed; {client.requests} request(s), fetch {fetched_s:.2f} s")
        return {"status": "ok", "reason": None, "new": out["created"], "seen": batch.seen, "error": None,
                "resources_read": client.requests, "updated": out["updated"], "removed": out["tombstoned"]}


def adapters() -> list[ModuleType]:
    from api.services.connectors import ADAPTERS

    return [a for a in ADAPTERS.values() if getattr(a, "TIER", 1) == TIER]


async def scheduled_sync(memory_path: Path | None = None) -> list[dict]:
    """The backend scheduler's job (every ``SCHEDULE_HOURS``): every connected tier-2 connector, one at a time, on the
    active bank. Gated, yields to Sleep, never raises."""
    if memory_path is None:
        from api.config import get_settings

        memory_path = get_settings().memory_path
    results = []
    for adapter in adapters():
        try:
            if adapter.is_connected():
                results.append(await run(adapter, memory_path, scheduled=True))
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"{adapter.CHANNEL_ID} scheduled sync failed: {type(exc).__name__}")
    return results
