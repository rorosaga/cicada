"""R-E2/R-E18 — a short-lived, read-only ``codex app-server`` probe.

Why the app-server and not ``auth.json``: Cicada never reads a vendor token
(spec Decision 2, R-E8). ``account/read`` answers the plan and email in
~0.05 s with Codex reading its own file; ``account/rateLimits/read`` answers
"is the limit already reached" in ~0.5 s; ``model/list`` gives the live
roster (never pinned in code — R2 §2.4 saw it drift inside a week). None of
the calls runs inference or spends quota (verified on codex-cli 0.154.0).

The probe spawns ``codex app-server --listen stdio://`` in Cicada's own
Codex home (``base.scrubbed_env("codex")``), speaks newline-delimited
JSON-RPC, and terminates it. Lines without an ``id`` are notifications (the
server interleaves e.g. ``remoteControl/status/changed``) and are skipped.
Any failure degrades to ``None``; callers fall back to ``codex login
status``. A reply is never logged — ``account/read`` carries an email.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

from loguru import logger

from api.services.connections import base

PROBE_TIMEOUT_S = 8.0
SNAPSHOT_TTL_S = 30.0
#: StreamReader's default line limit is 64 KiB and ``readline`` raises
#: ``ValueError`` past it — one ``model/list`` reply is a single line carrying
#: every model's descriptions and effort levels, so a roster that grows would
#: silently turn every probe into "unavailable". 4 MiB is still a bound.
_LINE_LIMIT = 4 * 1024 * 1024
_REQUESTS: tuple[tuple[str, dict | None], ...] = (
    ("account/read", {"refreshToken": False}),
    ("account/rateLimits/read", None),
    ("model/list", {}),
)
Transport = Callable[..., Awaitable[dict]]


@dataclass(frozen=True)
class CodexSnapshot:
    signed_in: bool
    account_type: str | None = None       # "chatgpt" | "apiKey" | "amazonBedrock"
    plan: str | None = None               # PlanType enum value, lower-case
    email: str | None = None
    limit_reached: str | None = None      # RateLimitReachedType, or None
    ordinary_usage_allowed: bool | None = None
    used_percent: int | None = None       # the fullest window's usedPercent
    resets_at: int | None = None          # that window's reset (unix seconds)
    models: tuple[str, ...] = ()          # visible roster, the default first
    default_model: str | None = None


def parse_snapshot(replies: dict) -> CodexSnapshot:
    """``{method: JSON-RPC reply}`` → the snapshot. Pure; tolerant of any
    missing piece (a signed-out home answers ``account: null`` and an error
    for rate limits, yet still lists models)."""
    account = ((replies.get("account/read") or {}).get("result") or {}).get("account")
    signed_in = isinstance(account, dict)
    plan = str(account.get("planType") or "").lower() if signed_in else ""
    limits_result = (replies.get("account/rateLimits/read") or {}).get("result") or {}
    limits = limits_result.get("rateLimits") or {}
    windows = [w for w in (limits.get("primary"), limits.get("secondary")) if isinstance(w, dict)]
    fullest = max(windows, key=lambda w: w.get("usedPercent") or 0, default=None)
    data = ((replies.get("model/list") or {}).get("result") or {}).get("data") or []
    visible = [m for m in data if isinstance(m, dict) and not m.get("hidden") and m.get("model")]
    default = next((m["model"] for m in visible if m.get("isDefault")), None)
    roster = ([default] if default else []) + [m["model"] for m in visible if m["model"] != default]
    used = fullest.get("usedPercent") if fullest else None
    resets = fullest.get("resetsAt") if fullest else None
    return CodexSnapshot(
        signed_in=signed_in,
        account_type=account.get("type") if signed_in else None,
        plan=plan if plan and plan != "unknown" else None,
        email=account.get("email") if signed_in else None,
        limit_reached=limits.get("rateLimitReachedType") or None,
        ordinary_usage_allowed=limits_result.get("ordinaryUsageAllowed"),
        used_percent=used if isinstance(used, int) and not isinstance(used, bool) else None,
        resets_at=resets if isinstance(resets, int) and not isinstance(resets, bool) else None,
        models=tuple(roster),
        default_model=default,
    )


async def _stdio_transport(*, timeout: float) -> dict:
    binary = base.resolve_binary("codex")
    if binary is None:
        raise FileNotFoundError("codex")
    proc = await asyncio.create_subprocess_exec(
        binary, "app-server", "--listen", "stdio://",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL, env=base.scrubbed_env("codex"), cwd=str(base.codex_home()),
        limit=_LINE_LIMIT,
    )
    replies: dict = {}

    async def send(obj: dict) -> None:
        proc.stdin.write((json.dumps(obj) + "\n").encode("utf-8"))
        await proc.stdin.drain()

    async def ask(req_id: int, method: str, params) -> dict:
        await send({"id": req_id, "method": method, "params": params})
        while True:
            line = await proc.stdout.readline()
            if not line:
                raise ConnectionError("codex app-server closed its output")
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if isinstance(obj, dict) and obj.get("id") == req_id:
                return obj

    async def conversation() -> None:
        replies["initialize"] = await ask(1, "initialize", {
            "clientInfo": {"name": "cicada", "title": "Cicada", "version": "1"}})
        await send({"method": "initialized"})
        for req_id, (method, params) in enumerate(_REQUESTS, start=2):
            replies[method] = await ask(req_id, method, params)

    try:
        await asyncio.wait_for(conversation(), timeout=timeout)
        return replies
    finally:
        with contextlib.suppress(ProcessLookupError):
            proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=2)
        except asyncio.TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(proc.wait(), timeout=2)


_CACHE: dict[str, tuple[float, CodexSnapshot | None]] = {}


async def snapshot(*, fresh: bool = False, timeout: float = PROBE_TIMEOUT_S,
                   transport: Transport | None = None) -> CodexSnapshot | None:
    """The cached snapshot (30 s), or a fresh probe. ``None`` = unavailable."""
    key = str(base.codex_home())
    now = time.monotonic()
    hit = _CACHE.get(key)
    if hit is not None and not fresh and now - hit[0] < SNAPSHOT_TTL_S:
        return hit[1]
    try:
        snap: CodexSnapshot | None = parse_snapshot(await (transport or _stdio_transport)(timeout=timeout))
    except Exception as exc:  # R-E18: ANY transport failure degrades to None
        # Broad on purpose: the adapters above this are documented never to
        # raise, and an experimental server can fail in shapes no tuple here
        # would name. The type only — the message can carry a reply (email).
        logger.warning(f"codex app-server probe unavailable: {type(exc).__name__}")
        snap = None
    _CACHE[key] = (now, snap)
    return snap


def invalidate() -> None:
    """Called on sign-in, sign-out and ``Registry.invalidate`` (Task 5)."""
    _CACHE.clear()
