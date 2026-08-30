"""Consumption ledger (G51) — one JSONL line per unit of LLM/memory work.

Append-only, machine-global (``$CICADA_HOME/telemetry/events-YYYY-MM.jsonl``,
0600), never in a memory bank or git. ``record`` never raises: telemetry must
not be able to break a Sleep cycle. Costs follow the honesty rules in the
spec: ``cost_usd`` is real money (usage-based rungs only), ``equiv_cost_usd``
is the API list-price estimate for whatever tokens are known.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from datetime import date, datetime, timezone
from pathlib import Path

from loguru import logger

from api.services.auth import cicada_home

KINDS = ("llm_call", "sleep_run", "agentic_write", "ask", "import", "throttle")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass
class UsageEvent:
    kind: str
    ts: str = field(default_factory=now_iso)
    stage: str | None = None
    connection: str | None = None
    engine: str | None = None
    model: str | None = None
    bank: str | None = None
    invocations: int = 1
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float | None = None
    equiv_cost_usd: float | None = None
    billing: str = "usage"  # subscription | usage | free
    duration_ms: int | None = None
    refs: dict = field(default_factory=dict)
    throttled: bool = False
    ok: bool = True

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_read_tokens + self.cache_write_tokens

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"), ensure_ascii=False)

    @classmethod
    def from_json(cls, line: str) -> "UsageEvent":
        data = json.loads(line)
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


def enabled() -> bool:
    return os.environ.get("CICADA_TELEMETRY", "on").strip().lower() not in {"off", "0", "false"}


def telemetry_dir() -> Path:
    path = cicada_home() / "telemetry"
    path.mkdir(mode=0o700, exist_ok=True)
    return path


def _file_for(ts: str) -> Path:
    return telemetry_dir() / f"events-{ts[:7]}.jsonl"


def record(event: UsageEvent) -> None:
    if not enabled():
        return
    try:
        line = (event.to_json() + "\n").encode("utf-8")
        fd = os.open(_file_for(event.ts), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)
    except Exception as exc:  # never let telemetry break the caller
        logger.warning(f"telemetry write failed: {type(exc).__name__}: {exc}")


def read_events(start: date | None = None, end: date | None = None) -> list[UsageEvent]:
    out: list[UsageEvent] = []
    if not enabled():
        return out
    for path in sorted(telemetry_dir().glob("events-*.jsonl")):
        month = path.stem.removeprefix("events-")
        if start and month < start.strftime("%Y-%m"):
            continue
        if end and month > end.strftime("%Y-%m"):
            continue
        bad = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                ev = UsageEvent.from_json(line)
            except (ValueError, TypeError):
                bad += 1
                continue
            day = ev.ts[:10]
            if start and day < start.isoformat():
                continue
            if end and day > end.isoformat():
                continue
            out.append(ev)
        if bad:
            logger.warning(f"telemetry: skipped {bad} corrupt line(s) in {path.name}")
    return out


def _get(obj, key: str, default=0):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def usage_from_response(resp) -> dict:
    usage = getattr(resp, "usage", None)
    details = _get(usage, "prompt_tokens_details", None)
    hidden = getattr(resp, "_hidden_params", None) or {}
    cost = _get(hidden, "response_cost", None)
    if cost is None:
        cost = _get(usage, "cost", None)
    return {
        "input_tokens": int(_get(usage, "prompt_tokens", 0) or _get(usage, "input_tokens", 0) or 0),
        "output_tokens": int(_get(usage, "completion_tokens", 0) or _get(usage, "output_tokens", 0) or 0),
        "cache_read_tokens": int(_get(details, "cached_tokens", 0) or _get(usage, "cache_read_input_tokens", 0) or 0),
        "cache_write_tokens": int(_get(usage, "cache_creation_input_tokens", 0) or 0),
        "cost_usd": float(cost) if cost is not None else None,
    }


def connection_for_model(model: str) -> tuple[str, str]:
    m = (model or "").lower()
    if m.startswith("ollama/"):
        return "ollama-local", "free"
    if m.startswith("openrouter/"):
        return "byok-openrouter", "usage"
    if m.startswith("anthropic/") or "claude" in m:
        return "byok-anthropic", "usage"
    if m.startswith("gemini/") or "gemini" in m:
        return "byok-gemini", "usage"
    return "byok-openai", "usage"


def bank_name(settings) -> str:
    try:
        return settings.memory_path.name
    except Exception:
        return "unknown"
