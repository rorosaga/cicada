"""R-E1 — reading ``claude -p --output-format stream-json``.

Why the stream, not the single ``json`` envelope ``agent_engine`` read until
2026-09-23: the envelope carries the answer but none of the CLI's structured
throttle signals. ``rate_limit_event`` (status, window, utilization, reset
time, overage — CLI ≥ 2.1.45, R1 §2.7) and ``system/api_retry`` (why the CLI
itself retried) exist ONLY on the stream, and they are what lets Sleep stop
before a plan window is spent instead of guessing from prose
(``agent_engine._RATE_LIMIT_MARKERS`` stays as the fallback — an event fires
on *transitions*, so a call may carry none).

Pure and stdlib-only: no subprocess, no settings, and it never logs content.
The final ``type == "result"`` line has exactly the shape of the old json
envelope, so ``parse_envelope``/``response_shim``/``model_from_envelope`` are
reused unchanged; a stdout that is ONE JSON object (json mode, or a CLI that
ignored the flag) is still accepted as the envelope (R-E9).

The live 2.1.280 shape differs from the SDK's parser tests in one way that
matters: the utilization fraction lives under ``unifiedWindows`` — see
``_rate_limits``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RateLimitSignal:
    """One ``rate_limit_event.rate_limit_info``, as the CLI reported it."""

    status: str                        # allowed | allowed_warning | rejected
    limit_type: str | None = None      # five_hour | seven_day | seven_day_opus | seven_day_sonnet | overage
    utilization: float | None = None   # 0.0–1.0
    resets_at: int | None = None       # unix seconds — the CLI's own, never estimated
    using_overage: bool = False


@dataclass(frozen=True)
class RetrySignal:
    """One ``system/api_retry``: why the CLI retried a request itself."""

    error: str | None = None           # rate_limit | overloaded | billing_error | authentication_failed | …
    status: int | None = None


@dataclass
class StreamResult:
    envelope: dict | None = None
    rate_limits: list[RateLimitSignal] = field(default_factory=list)
    retries: list[RetrySignal] = field(default_factory=list)
    api_key_source: str | None = None
    json_lines: int = 0


def _number(raw) -> float | None:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    return float(raw)


def _utilization(raw) -> float | None:
    value = _number(raw)
    if value is None:
        return None
    # The SDK documents a 0.0–1.0 fraction; a CLI that ever reports a
    # percentage must not read as 92x over the limit.
    return value / 100.0 if value > 1.0 else value


def _window(windows, name: str | None) -> dict:
    entry = windows.get(name) if isinstance(windows, dict) and name else None
    return entry if isinstance(entry, dict) else {}


def _rate_limits(info) -> list[RateLimitSignal]:
    """One ``rate_limit_info`` → its signals, the reported window LAST.

    Recorded live on ``claude`` 2.1.280 (Task 2 Step 6,
    ``fixtures/claude_stream_live.jsonl``): the event carries NO top-level
    ``utilization`` — each window's fraction and reset sit under
    ``unifiedWindows.<window>``. Reading the SDK-documented top-level key
    alone would leave the R-E12 90 % rule blind on every real stream, so:

    * the reported window's utilization falls back to its own
      ``unifiedWindows`` entry (top-level still wins when a CLI sends it);
    * every OTHER listed window becomes a signal of its own, status
      ``allowed`` — it is by construction not the window the CLI flagged, so
      it can never carry a rejection or an overage, only the fraction the
      5-hour rule reads (a weekly event must not hide a 93 % 5-hour window).

    The reported window stays last so ``providers._throttle_refs`` (which
    reads the last signal) names the one the CLI flagged.
    """
    if not isinstance(info, dict) or not isinstance(info.get("status"), str):
        return []
    limit_type = info.get("rateLimitType")
    limit_type = limit_type if isinstance(limit_type, str) else None
    windows = info.get("unifiedWindows")
    own = _window(windows, limit_type)
    utilization = _utilization(info.get("utilization"))
    if utilization is None:
        utilization = _utilization(own.get("utilization"))
    resets = _number(info.get("resetsAt"))
    if resets is None:
        resets = _number(own.get("resetsAt"))
    out: list[RateLimitSignal] = []
    if isinstance(windows, dict):
        for name in windows:
            if name == limit_type or not isinstance(name, str):
                continue
            entry = _window(windows, name)
            fraction = _utilization(entry.get("utilization"))
            if fraction is None:
                continue
            at = _number(entry.get("resetsAt"))
            out.append(RateLimitSignal(status="allowed", limit_type=name, utilization=fraction,
                                       resets_at=int(at) if at is not None else None))
    out.append(RateLimitSignal(
        status=info["status"],
        limit_type=limit_type,
        utilization=utilization,
        resets_at=int(resets) if resets is not None else None,
        using_overage=info.get("isUsingOverage") is True or limit_type == "overage",
    ))
    return out


def _objects(text: str) -> list[dict]:
    try:
        whole = json.loads(text)
    except ValueError:
        whole = None
    if isinstance(whole, dict):
        return [whole]
    out: list[dict] = []
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except ValueError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def parse_stream(stdout: str | None) -> StreamResult:
    """NDJSON (or one json-mode object) → the envelope plus every signal."""
    out = StreamResult()
    text = (stdout or "").strip()
    if not text:
        return out
    objects = _objects(text)
    out.json_lines = len(objects)
    for obj in objects:
        kind = obj.get("type")
        if kind == "result" or (kind is None and len(objects) == 1):
            out.envelope = obj
        elif kind == "rate_limit_event":
            out.rate_limits.extend(_rate_limits(obj.get("rate_limit_info")))
        elif kind == "system" and obj.get("subtype") == "api_retry":
            error = obj.get("error")
            status = _number(obj.get("error_status"))
            out.retries.append(RetrySignal(
                error=error if isinstance(error, str) else None,
                status=int(status) if status is not None else None,
            ))
        elif kind == "system" and obj.get("subtype") == "init":
            source = obj.get("apiKeySource")
            out.api_key_source = source if isinstance(source, str) else None
    return out
