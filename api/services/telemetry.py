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

KINDS = (
    "llm_call", "sleep_run", "agentic_write", "ask", "import", "throttle",
    "resolution", "audit", "dedup_verdict", "capture",
)
# G113: grounded-feedback rows — a user's verdict on an inbox item, a reconcile
# supersede/reject, a dedup judgement. Ids/enums/numbers only, never claim text
# or an answer string (the ledger is machine-global and outside the bank).
# Excluded from connection/cost rollups (``consumption_stats.stats``) because
# they carry no spend: a ``resolution`` has ``connection=None`` and would
# otherwise surface as an "unknown" connection.
FEEDBACK_KINDS = ("resolution", "audit", "dedup_verdict")
# G105 R10: a `capture` row (hook-driven transcript capture) is counts only
# and carries no spend or connection; like the feedback kinds it must never
# surface as an "unknown" connection in the cost rollup.
NON_SPEND_KINDS = FEEDBACK_KINDS + ("capture",)


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
        """Total tokens for this unit of work.

        ``input_tokens`` is the **gross** prompt, following litellm's
        ``Usage.prompt_tokens`` semantics (see :func:`usage_from_response`):
        ``cache_read_tokens`` and ``cache_write_tokens`` are a *breakdown of*
        it, not extra tokens beside it. OpenAI/Codex report
        ``prompt_tokens_details.cached_tokens`` as a subset of
        ``prompt_tokens``; litellm folds Anthropic's separate cache counters
        into ``prompt_tokens`` the same way. So adding them here counted the
        same tokens twice on every cached call.
        """
        return self.input_tokens + self.output_tokens

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"), ensure_ascii=False)

    @classmethod
    def from_json(cls, line: str) -> "UsageEvent":
        data = json.loads(line)
        if not isinstance(data, dict):
            # A valid-JSON but non-object line (a bare string, number, or list)
            # is corruption like any other: ``read_events`` counts and skips it.
            # Without this it reached ``.items()`` and raised AttributeError,
            # which nothing catches — one stray line broke every /consumption/*.
            raise ValueError(f"telemetry line is not a JSON object (got {type(data).__name__})")
        known = {f.name for f in fields(cls)}
        event = cls(**{k: v for k, v in data.items() if k in known})
        # A `ts` that isn't a plain ISO string (null, a number, a nested
        # object...) survives dataclass construction with no error, and then
        # crashes ``read_events``'s ``ev.ts[:10]`` slice — OUTSIDE the
        # try/except that guards the parse itself, so one bad line 500s every
        # /consumption/* endpoint instead of being counted+skipped like every
        # other corrupt line. Reject it here, at parse time, same as a
        # malformed numeric counter (a string, null, list, or object where an
        # int belongs) — both are shapes no writer of this ledger ever emits.
        if not isinstance(event.ts, str) or not event.ts:
            raise ValueError(f"telemetry event has a non-string/empty ts: {event.ts!r}")
        for counter in (
            "invocations", "input_tokens", "output_tokens",
            "cache_read_tokens", "cache_write_tokens",
        ):
            value = getattr(event, counter)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"telemetry event field {counter!r} is not numeric: {value!r}")
        if event.duration_ms is not None and (
            isinstance(event.duration_ms, bool) or not isinstance(event.duration_ms, (int, float))
        ):
            raise ValueError(
                f"telemetry event field 'duration_ms' is not numeric: {event.duration_ms!r}"
            )
        return event


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


def record_audit(
    entries, *, subject_hint: str | None, bank: str | None, stage: str = "reconcile"
) -> None:
    """One ``audit`` event per ``reconcile_stage3`` audit entry. Never raises.

    G113: a trust-gated supersede or reject is the reconciler passing judgement
    on an extractor's claim — the same kind of signal as a user's inbox answer,
    just automated — and until now it lived only in a return value nothing
    persisted. ``refs`` carries claim ids and the subject slug only. An entry
    whose ``action`` is neither ``supersede`` nor ``rejected`` is skipped, not
    guessed at.
    """
    for entry in entries or ():
        try:
            action = entry.get("action")
            if action == "supersede":
                refs = {
                    "action": "supersede", "subject": subject_hint,
                    "closed": entry.get("closed"), "by": entry.get("by"),
                }
            elif action == "rejected":
                refs = {
                    "action": "rejected", "subject": subject_hint,
                    "kept": entry.get("kept"), "dropped": entry.get("dropped"),
                }
            else:
                continue
            record(UsageEvent(kind="audit", stage=stage, bank=bank, invocations=0, billing="free", refs=refs))
        except Exception:  # noqa: BLE001 — a ledger failure never blocks a write
            continue


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
                # Everything that touches a per-event field — not just the
                # parse itself — stays inside this boundary: a validated-but-
                # still-unexpected shape (or a future field access added here)
                # must be counted+skipped like any other corrupt line, never
                # propagate out and 500 every /consumption/* endpoint.
                ev = UsageEvent.from_json(line)
                day = ev.ts[:10]
                keep = not ((start and day < start.isoformat()) or (end and day > end.isoformat()))
            except (ValueError, TypeError):
                bad += 1
                continue
            if keep:
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
    """Normalize a provider response's ``usage`` to the ledger's four buckets.

    **The rule: ``input_tokens`` is always GROSS** — the whole prompt, with
    ``cache_read_tokens``/``cache_write_tokens`` recorded as a breakdown *of*
    it, never as tokens beside it. That is litellm's own ``Usage`` contract:
    OpenAI/Codex report ``prompt_tokens_details.cached_tokens`` as a subset of
    ``prompt_tokens``, and litellm's Anthropic transformation adds
    ``cache_read_input_tokens`` + ``cache_creation_input_tokens`` *into*
    ``prompt_tokens`` so both shapes agree. ``pricing.estimate_cost`` depends
    on it too: ``litellm.cost_per_token`` subtracts the cache buckets out of
    ``prompt_tokens`` itself, and handing it a pre-netted prompt yields a
    negative input cost.

    Only a *raw* Anthropic SDK usage object (``input_tokens`` with no
    ``prompt_tokens``) genuinely excludes the cache buckets, so that shape —
    and only that shape — is grossed up here.
    """
    usage = getattr(resp, "usage", None)
    details = _get(usage, "prompt_tokens_details", None)
    hidden = getattr(resp, "_hidden_params", None) or {}
    cost = _get(hidden, "response_cost", None)
    if cost is None:
        cost = _get(usage, "cost", None)
    cache_read = int(_get(details, "cached_tokens", 0) or _get(usage, "cache_read_input_tokens", 0) or 0)
    cache_write = int(_get(usage, "cache_creation_input_tokens", 0) or 0)
    prompt = int(_get(usage, "prompt_tokens", 0) or 0)
    input_tokens = prompt or (int(_get(usage, "input_tokens", 0) or 0) + cache_read + cache_write)
    return {
        "input_tokens": input_tokens,
        "output_tokens": int(_get(usage, "completion_tokens", 0) or _get(usage, "output_tokens", 0) or 0),
        "cache_read_tokens": cache_read,
        "cache_write_tokens": cache_write,
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
