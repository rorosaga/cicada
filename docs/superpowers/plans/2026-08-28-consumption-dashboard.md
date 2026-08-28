# Consumption / Traceability Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show — honestly, per billing kind — what Cicada consumed: which connection/engine/model did which memory work, when, how much (invocations, tokens) and at what price, in a minimal view (stat tiles + GitHub-style calendar) and an advanced view (Claude-Code-`/stats`-style breakdowns and charts).

**Architecture:** An append-only JSONL telemetry ledger under `~/.cicada/telemetry/` fed from one interception point (`providers.resolve_llm_fn`, which the four remaining direct-litellm callsites are rerouted through), plus `sleep_run` and `agentic_write` events; an aggregation service that merges the ledger with the memory repo's `Cicada-Author` git history; five `/consumption/*` endpoints; a SwiftUI Usage page with a hand-built heatmap grid and Swift Charts for the advanced view.

**Tech Stack:** Python 3.12 / FastAPI / litellm (`cost_per_token`) / git; SwiftUI + Swift Charts (macOS 14); pytest; new `CicadaAppTests` SwiftPM test target.

**Spec:** `docs/superpowers/specs/2026-08-28-connections-and-consumption-dashboard-design.md` (§3.6–3.10, §6, §7, §8)

## Global Constraints

- Subscription connections never show a dollar figure as "spent": flat `$<price>/mo` plus "≈ $X at API list price — estimate, not billed" (spec §6.6). No rate-limit percentages for Claude (no compliant source).
- Ledger lives at `$CICADA_HOME/telemetry/events-YYYY-MM.jsonl`, mode 0600, never inside a memory bank, never in git (spec §6.1). `CICADA_TELEMETRY=off` disables writes (the test suite sets it).
- `resolve_llm_fn` stays byte-identical for existing callers when no `stage`/`sink` is passed except that a call is now timed and (when telemetry is on) recorded.
- All wire keys camelCase (`CamelModel`); Swift decoding tolerant.
- Tests: `api/.venv/bin/python -m pytest api/tests/<file> -v` from the repo root; `cd app/CicadaApp && swift build && swift test`.
- Depends on the connections plan for `api/services/auth.cicada_home`, `api/services/pricing.py`, `api/tests/conftest.py`, and `GET /connections` (Task 6 reads it). Task 1 here only needs `cicada_home`.

---

## File structure

| File | Responsibility |
|---|---|
| `api/services/telemetry.py` (new) | `UsageEvent`, `record`, `read_events`, `usage_from_response`, `connection_for_model`, `bank_name` |
| `api/services/pricing.py` (modify) | `estimate_cost` (usage-based list price via litellm) |
| `api/services/providers.py` (modify) | `resolve_llm_fn(..., stage=, sink=, bank=)` timing + usage capture |
| `api/services/entity_extractor.py`, `entity_resolver.py`, `link_enrichment.py`, `ask_service.py` (modify) | route through the seam with a `stage` tag |
| `api/services/git_service.py` (modify) | `commit_changes` returns the new commit hash |
| `api/services/sleep_cycle.py` (modify) | `sleep_run` event in `_finalize`; run duration |
| `mcp/server.py` (modify) | `agentic_write` event in `handle_write_claim` |
| `api/services/consumption_stats.py` (new) | summary / calendar / stats / per-connection aggregation |
| `api/services/harness_stats.py` (new) | tolerant readers for `~/.claude/stats-cache.json` and Codex rate-limit snapshots |
| `api/models/schemas.py` (modify) | response models |
| `api/routers/consumption.py` (new), `api/main.py` (modify) | `/consumption/*` |
| `app/CicadaApp/Package.swift` (modify) | `CicadaAppTests` target |
| `app/…/Models/Consumption.swift` (new) | Swift models |
| `app/…/Services/APIClient.swift` (modify) | five fetches |
| `app/…/Utilities/UsageFormat.swift`, `app/…/Utilities/CalendarLayout.swift` (new) | pure formatting/layout logic (unit-tested) |
| `app/…/ViewModels/UsageViewModel.swift` (new) | state |
| `app/…/Views/Usage/UsageView.swift`, `HeatmapView.swift`, `UsageAdvancedView.swift` (new) | UI |
| `app/…/Theme/CicadaTheme.swift` (modify) | `heatRamp(level:)` |
| `app/…/Views/Sidebar/SidebarView.swift`, `ContentView.swift` (modify) | `usage` tab |

---

### Task 1: Telemetry ledger

**Files:**
- Create: `api/services/telemetry.py`
- Create: `api/tests/test_telemetry.py`
- Modify: `api/tests/conftest.py` (add `monkeypatch.setenv("CICADA_TELEMETRY", "off")` to the autouse fixture)

**Interfaces:**
- Produces: `UsageEvent` dataclass (fields per spec §6.1: `ts, kind, stage, connection, engine, model, bank, invocations, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, cost_usd, equiv_cost_usd, billing, duration_ms, refs, throttled, ok`), `record(event) -> None`, `read_events(start: date | None = None, end: date | None = None) -> list[UsageEvent]`, `enabled() -> bool`, `telemetry_dir() -> Path`, `usage_from_response(resp) -> dict` (keys `input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, cost_usd`), `connection_for_model(model: str) -> tuple[str, str]`, `bank_name(settings) -> str`, `now_iso() -> str`.

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_telemetry.py
from __future__ import annotations

import json
import stat
from datetime import date

import pytest

from api.services import telemetry as tm


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path))
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    return tmp_path


def _ev(ts: str, **kw) -> tm.UsageEvent:
    base = dict(kind="llm_call", stage="extraction", model="gpt-5.4-mini", input_tokens=10, output_tokens=5)
    base.update(kw)
    return tm.UsageEvent(ts=ts, **base)


def test_record_appends_monthly_file_0600(home):
    tm.record(_ev("2026-08-28T03:00:00.000Z"))
    tm.record(_ev("2026-08-29T03:00:00.000Z", output_tokens=7))
    path = home / "telemetry" / "events-2026-08.jsonl"
    lines = path.read_text().splitlines()
    assert len(lines) == 2 and json.loads(lines[1])["output_tokens"] == 7
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_read_events_by_range_and_skips_bad_lines(home):
    tm.record(_ev("2026-07-31T23:00:00.000Z"))
    tm.record(_ev("2026-08-01T00:00:00.000Z"))
    tm.record(_ev("2026-08-15T00:00:00.000Z"))
    with open(home / "telemetry" / "events-2026-08.jsonl", "a") as fh:
        fh.write("{not json\n")
    assert len(tm.read_events()) == 3
    aug = tm.read_events(start=date(2026, 8, 1), end=date(2026, 8, 31))
    assert [e.ts[:10] for e in aug] == ["2026-08-01", "2026-08-15"]


def test_disabled_writes_nothing(home, monkeypatch):
    monkeypatch.setenv("CICADA_TELEMETRY", "off")
    tm.record(_ev("2026-08-28T03:00:00.000Z"))
    assert not (home / "telemetry").exists() or not list((home / "telemetry").glob("*.jsonl"))


def test_usage_from_response_dict_and_object():
    class _Resp:
        class usage:  # noqa: N801 — mimics litellm's object attr style
            prompt_tokens = 100
            completion_tokens = 20

            class prompt_tokens_details:  # noqa: N801
                cached_tokens = 40

        _hidden_params = {"response_cost": 0.0021}

    got = tm.usage_from_response(_Resp())
    assert got == {"input_tokens": 100, "output_tokens": 20, "cache_read_tokens": 40, "cache_write_tokens": 0, "cost_usd": 0.0021}

    class _DictResp:
        usage = {"prompt_tokens": 3, "completion_tokens": 4, "cost": 0.5}

    assert tm.usage_from_response(_DictResp()) == {"input_tokens": 3, "output_tokens": 4, "cache_read_tokens": 0, "cache_write_tokens": 0, "cost_usd": 0.5}
    assert tm.usage_from_response(object())["input_tokens"] == 0


@pytest.mark.parametrize("model,expected", [
    ("ollama/qwen3:8b", ("ollama-local", "free")),
    ("openrouter/z-ai/glm-5.2", ("byok-openrouter", "usage")),
    ("anthropic/claude-sonnet-5", ("byok-anthropic", "usage")),
    ("gemini/gemini-2.5-flash", ("byok-gemini", "usage")),
    ("gpt-5.4-mini", ("byok-openai", "usage")),
])
def test_connection_for_model(model, expected):
    assert tm.connection_for_model(model) == expected


def test_roundtrip_ignores_unknown_fields():
    ev = tm.UsageEvent.from_json('{"ts":"2026-08-28T00:00:00Z","kind":"ask","future_field":1}')
    assert ev.kind == "ask" and ev.invocations == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `api/.venv/bin/python -m pytest api/tests/test_telemetry.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `telemetry.py` and the conftest line**

```python
# api/services/telemetry.py
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
```

`api/tests/conftest.py` — extend the autouse fixture body with `monkeypatch.setenv("CICADA_TELEMETRY", "off")`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `api/.venv/bin/python -m pytest api/tests/test_telemetry.py -v`
Expected: 10 PASS

- [ ] **Step 5: Commit**

```bash
git add api/services/telemetry.py api/tests/test_telemetry.py api/tests/conftest.py
git commit -m "feat(telemetry): append-only consumption ledger under ~/.cicada/telemetry"
```

---

### Task 2: Usage capture at the LLM seam + list-price estimation

**Files:**
- Modify: `api/services/pricing.py` (append `estimate_cost`)
- Modify: `api/services/providers.py:52-105` (`resolve_llm_fn`)
- Create: `api/tests/test_seam_telemetry.py`
- Modify: `api/tests/test_pricing.py` (append)

**Interfaces:**
- Produces: `pricing.estimate_cost(model, input_tokens, output_tokens, cache_read_tokens=0, cache_write_tokens=0, *, cost_fn=None) -> float | None`; `providers.resolve_llm_fn(settings, *, model=None, completion=None, stage=None, sink=None, bank=None)` — `sink: Callable[[UsageEvent], None]` defaults to `telemetry.record`.

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_seam_telemetry.py
"""Every LLM call through resolve_llm_fn produces one UsageEvent."""
from __future__ import annotations

import asyncio

from api.config import Settings
from api.services import providers
from api.services.telemetry import UsageEvent


class _Resp:
    def __init__(self, cost=0.002):
        class _Msg:
            content = "{}"

        class _Choice:
            message = _Msg()

        self.choices = [_Choice()]
        self.usage = {"prompt_tokens": 120, "completion_tokens": 30}
        self._hidden_params = {"response_cost": cost}


def test_sync_call_records_event():
    events: list[UsageEvent] = []
    fn = providers.resolve_llm_fn(Settings(litellm_model="gpt-5.4-mini"), completion=lambda **kw: _Resp(),
                                  stage="ask", sink=events.append, bank="lab")
    fn(messages=[{"role": "user", "content": "hi"}])
    assert len(events) == 1
    ev = events[0]
    assert ev.kind == "llm_call" and ev.stage == "ask" and ev.bank == "lab"
    assert ev.model == "gpt-5.4-mini" and ev.connection == "byok-openai" and ev.billing == "usage"
    assert (ev.input_tokens, ev.output_tokens) == (120, 30)
    assert ev.cost_usd == 0.002 and ev.equiv_cost_usd == 0.002
    assert ev.duration_ms is not None and ev.ok


def test_async_call_records_event_after_await():
    events: list[UsageEvent] = []

    async def acompletion(**kw):
        return _Resp(cost=0.1)

    fn = providers.resolve_llm_fn(Settings(), completion=acompletion, stage="extraction", sink=events.append)
    resp = asyncio.run(fn(messages=[]))
    assert isinstance(resp, _Resp) and events[0].cost_usd == 0.1


def test_failed_call_records_not_ok_and_reraises():
    events: list[UsageEvent] = []

    def boom(**kw):
        raise RuntimeError("provider down")

    fn = providers.resolve_llm_fn(Settings(), completion=boom, stage="synthesis", sink=events.append)
    try:
        fn(messages=[])
    except RuntimeError:
        pass
    assert events and events[0].ok is False and events[0].input_tokens == 0


def test_local_mode_is_free():
    events: list[UsageEvent] = []
    fn = providers.resolve_llm_fn(Settings(llm_mode="local", ollama_model="qwen3:8b"),
                                  completion=lambda **kw: _Resp(cost=None), stage="extraction", sink=events.append)
    fn(messages=[])
    assert events[0].connection == "ollama-local" and events[0].billing == "free" and events[0].cost_usd is None


def test_no_stage_still_records_unknown_stage():
    events: list[UsageEvent] = []
    fn = providers.resolve_llm_fn(Settings(), completion=lambda **kw: _Resp(), sink=events.append)
    fn(messages=[])
    assert events[0].stage == "unknown"
```

Append to `api/tests/test_pricing.py`:

```python
def test_estimate_cost_uses_cost_fn_and_strips_prefix_on_retry():
    calls = []

    def cost_fn(**kw):
        calls.append(kw["model"])
        if kw["model"].startswith("openrouter/"):
            raise ValueError("unknown model")
        return (0.001, 0.0005)

    usd = pricing.estimate_cost("openrouter/z-ai/glm-5.2", 1000, 100, cost_fn=cost_fn)
    assert usd == 0.0015 and calls == ["openrouter/z-ai/glm-5.2", "z-ai/glm-5.2"]


def test_estimate_cost_unknown_model_is_none():
    def cost_fn(**kw):
        raise ValueError("nope")

    assert pricing.estimate_cost("mystery", 10, 10, cost_fn=cost_fn) is None
    assert pricing.estimate_cost("gpt-5.4-mini", 0, 0, cost_fn=cost_fn) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `api/.venv/bin/python -m pytest api/tests/test_seam_telemetry.py api/tests/test_pricing.py -v`
Expected: `test_seam_telemetry` fails with `TypeError: resolve_llm_fn() got an unexpected keyword argument 'stage'`; pricing tests fail with `AttributeError: estimate_cost`

- [ ] **Step 3: Implement**

Append to `api/services/pricing.py`:

```python
def estimate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    *,
    cost_fn=None,
) -> float | None:
    """API list-price estimate via litellm's bundled price table (offline).

    Tries the model id as given, then with its provider prefix stripped
    (``openrouter/x/y`` -> ``x/y``). ``None`` when the model is unknown or no
    tokens were reported — the UI shows "n/a", never a made-up number.
    """
    if not model or (input_tokens + output_tokens + cache_read_tokens + cache_write_tokens) == 0:
        return None
    if cost_fn is None:
        import litellm

        cost_fn = litellm.cost_per_token
    candidates = [model]
    if "/" in model:
        candidates.append(model.split("/", 1)[1])
    for candidate in candidates:
        try:
            try:
                prompt_cost, completion_cost = cost_fn(
                    model=candidate, prompt_tokens=input_tokens, completion_tokens=output_tokens,
                    cache_read_input_tokens=cache_read_tokens, cache_creation_input_tokens=cache_write_tokens,
                )
            except TypeError:  # older litellm without cache kwargs
                prompt_cost, completion_cost = cost_fn(
                    model=candidate, prompt_tokens=input_tokens + cache_read_tokens + cache_write_tokens,
                    completion_tokens=output_tokens,
                )
            return round(float(prompt_cost) + float(completion_cost), 6)
        except Exception:
            continue
    return None
```

In `providers.py`, add imports `import inspect`, `import time`, `from api.services import pricing, telemetry` and change `resolve_llm_fn`:

```python
def resolve_llm_fn(
    settings: Settings,
    *,
    model: str | None = None,
    completion: LlmFn | None = None,
    stage: str | None = None,
    sink: Callable[[telemetry.UsageEvent], None] | None = None,
    bank: str | None = None,
) -> LlmFn:
    """(existing docstring, plus:) Every call is timed and reported as one
    ``UsageEvent`` to ``sink`` (default: the telemetry ledger) tagged with
    ``stage`` — the single interception point for the consumption dashboard."""
    resolved_model = (model or settings.litellm_model).strip()
    if completion is None:
        import litellm

        completion = litellm.completion
    if sink is None:
        sink = telemetry.record
    bank_label = bank or telemetry.bank_name(settings)

    is_local = settings.llm_mode == "local" or resolved_model.startswith("ollama/")
    if is_local and not resolved_model.startswith("ollama/"):
        resolved_model = f"ollama/{settings.ollama_model}"

    is_openrouter = resolved_model.startswith("openrouter/")
    headers = _openrouter_headers(settings) if is_openrouter else None
    connection, billing = telemetry.connection_for_model(resolved_model)

    def _emit(resp, started: float, ok: bool) -> None:
        usage = telemetry.usage_from_response(resp) if ok else telemetry.usage_from_response(None)
        cost = None if billing == "free" else usage["cost_usd"]
        equiv = pricing.estimate_cost(resolved_model, usage["input_tokens"], usage["output_tokens"],
                                      usage["cache_read_tokens"], usage["cache_write_tokens"])
        try:
            sink(telemetry.UsageEvent(
                kind="llm_call", stage=stage or "unknown", connection=connection, engine="litellm",
                model=resolved_model, bank=bank_label, billing=billing,
                input_tokens=usage["input_tokens"], output_tokens=usage["output_tokens"],
                cache_read_tokens=usage["cache_read_tokens"], cache_write_tokens=usage["cache_write_tokens"],
                cost_usd=cost, equiv_cost_usd=equiv if equiv is not None else cost,
                duration_ms=int((time.perf_counter() - started) * 1000), ok=ok,
            ))
        except Exception as exc:  # a sink must never break an LLM call
            logger.warning(f"telemetry sink failed: {exc}")

    def _call(*, messages, response_format=None, **kw):
        call_kw: dict[str, Any] = {"model": resolved_model, "messages": messages, **kw}
        if response_format is not None:
            call_kw["response_format"] = response_format
        if headers is not None and "extra_headers" not in call_kw:
            call_kw["extra_headers"] = headers
        if is_local and "api_base" not in call_kw:
            call_kw["api_base"] = settings.ollama_base_url
        started = time.perf_counter()
        try:
            result = completion(**call_kw)
        except Exception:
            _emit(None, started, ok=False)
            raise
        if inspect.isawaitable(result):
            async def _awaited():
                try:
                    resp = await result
                except Exception:
                    _emit(None, started, ok=False)
                    raise
                _emit(resp, started, ok=True)
                return resp

            return _awaited()
        _emit(result, started, ok=True)
        return result

    return _call
```

- [ ] **Step 4: Run tests to verify they pass, then the whole suite**

Run: `api/.venv/bin/python -m pytest api/tests/test_seam_telemetry.py api/tests/test_pricing.py api/tests/test_providers.py api/tests/test_local_llm.py api/tests/test_llm_seam_adoption.py -v`
Expected: all PASS (the older seam tests still pass — the async shape is preserved)
Run: `api/.venv/bin/python -m pytest api/tests -q`
Expected: all green

- [ ] **Step 5: Commit**

```bash
git add api/services/pricing.py api/services/providers.py api/tests/test_seam_telemetry.py api/tests/test_pricing.py
git commit -m "feat(telemetry): capture usage/cost/duration for every call through resolve_llm_fn"
```

---

### Task 3: Seam completion — route the four direct callsites through the factory (G49 P4 pulled forward)

**Files:**
- Modify: `api/services/entity_extractor.py:234-243` (`_extract_chunk`)
- Modify: `api/services/entity_resolver.py:689-700` (`_llm_judge_same_entity`)
- Modify: `api/services/link_enrichment.py:242-258` (`default_summarize`)
- Modify: `api/services/ask_service.py:251-268` (`_default_llm_fn`)
- Modify: `api/tests/test_llm_seam_adoption.py` (append four tests)

**Interfaces:**
- Consumes: `providers.resolve_llm_fn(settings, model=, completion=, stage=)`
- Stage tags: `extraction`, `disambiguation`, `enrichment`, `ask`

- [ ] **Step 1: Write the failing tests** (append to `test_llm_seam_adoption.py`)

```python
# --------------------------------------------------------------------------- #
# G51: the four remaining direct callsites now route through the factory.
# --------------------------------------------------------------------------- #

import litellm as _litellm

from api.services import ask_service, entity_extractor, entity_resolver, link_enrichment


def test_entity_extractor_respects_local_llm_mode(monkeypatch):
    captured: dict = {}

    async def fake(**kw):
        captured.update(kw)
        return _FakeResp(json.dumps({"entities": [], "relationships": []}))

    monkeypatch.setattr(entity_extractor.litellm, "acompletion", fake)
    settings = Settings(llm_mode="local", ollama_model="qwen3:8b", ollama_base_url="http://127.0.0.1:11434")
    asyncio.run(entity_extractor._extract_chunk("ep1", "hello", 0, 1, settings))
    assert captured["model"] == "ollama/qwen3:8b" and captured["api_base"] == "http://127.0.0.1:11434"
    assert captured["response_format"] == {"type": "json_object"}


def test_entity_resolver_judge_respects_local_llm_mode(monkeypatch):
    captured: dict = {}

    async def fake(**kw):
        captured.update(kw)
        return _FakeResp(json.dumps({"decision": "same"}))

    monkeypatch.setattr(entity_resolver.litellm, "acompletion", fake)
    settings = Settings(llm_mode="local", ollama_model="qwen3:8b", litellm_disambiguation_model="gpt-5.4-nano")
    out = asyncio.run(entity_resolver._llm_judge_same_entity("A", "person", "d", "A.", "person", "b", settings))
    assert out == "same" and captured["model"] == "ollama/qwen3:8b"


def test_link_enrichment_summarizer_routes_through_factory(monkeypatch):
    captured: dict = {}

    async def fake(**kw):
        captured.update(kw)
        return _FakeResp("A page about knots.")

    monkeypatch.setattr(_litellm, "acompletion", fake)
    settings = Settings(litellm_model="gpt-5.4-mini")
    out = asyncio.run(link_enrichment._summarize_excerpt("Knots", "Long excerpt " * 20, "https://x", settings))
    assert out == "A page about knots." and captured["model"] == "gpt-5.4-mini" and captured["max_tokens"] == 100


def test_ask_default_llm_fn_routes_through_factory(monkeypatch):
    captured: dict = {}

    def fake(**kw):
        captured.update(kw)
        return _FakeResp(json.dumps({"answer": "x"}))

    monkeypatch.setattr(_litellm, "completion", fake)
    monkeypatch.setenv("CICADA_LLM_MODE", "local")
    monkeypatch.setenv("CICADA_OLLAMA_MODEL", "qwen3:8b")
    from api import config
    config.get_settings.cache_clear()
    try:
        fn = ask_service._default_llm_fn()
        assert fn("prompt") == json.dumps({"answer": "x"})
        assert captured["model"] == "ollama/qwen3:8b"
    finally:
        config.get_settings.cache_clear()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `api/.venv/bin/python -m pytest api/tests/test_llm_seam_adoption.py -v`
Expected: the four new tests FAIL (`api_base`/`model` assertions; `_summarize_excerpt` missing)

- [ ] **Step 3: Reroute each callsite**

`entity_extractor.py` — replace the `response = await litellm.acompletion(...)` block with:

```python
        from api.services.providers import resolve_llm_fn

        llm_fn = resolve_llm_fn(
            settings, model=settings.litellm_model, completion=litellm.acompletion, stage="extraction"
        )
        response = await llm_fn(
            messages=[
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": chunk},
            ],
            response_format={"type": "json_object"},
            extra_body=EXTRACTION_EXTRA_BODY,
            timeout=EXTRACTION_TIMEOUT_S,
        )
```

`entity_resolver.py` — same shape inside `_llm_judge_same_entity`:

```python
        from api.services.providers import resolve_llm_fn

        llm_fn = resolve_llm_fn(
            settings, model=disambig_model, completion=litellm.acompletion, stage="disambiguation"
        )
        response = await llm_fn(
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            extra_body={"reasoning": {"enabled": False}},
            timeout=120,
        )
```

`link_enrichment.py` — split the LLM half of `default_summarize` into a testable helper and call it:

```python
async def _summarize_excerpt(title: str, excerpt: str, url: str, settings) -> str | None:
    """One bounded mini-model call over an already-fetched excerpt."""
    try:
        import litellm

        from api.services.providers import resolve_llm_fn

        prompt = (
            "You are summarizing a web page for a personal memory system.\n"
            "Given the page title and a text excerpt, write a 1-2 sentence "
            "description of what this site or page is about. Be specific about the "
            'topic. Be concise. Do not start with "This site" or "This page".\n\n'
            f"Title: {title}\nExcerpt:\n{excerpt}\n\nDescription (1-2 sentences):"
        )
        llm_fn = resolve_llm_fn(
            settings,
            model=getattr(settings, "litellm_model", "") or "gpt-5.4-mini",
            completion=litellm.acompletion,
            stage="enrichment",
        )
        response = await llm_fn(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100,
            temperature=0,
        )
        text = (response.choices[0].message.content or "").strip()
        return text or None
    except Exception as e:
        logger.warning(f"link summarize LLM failed for {url}: {type(e).__name__}: {e}")
        return None
```

and in `default_summarize` replace everything from the second `try:` (the one wrapping `import litellm`) to the end of the function with `return await _summarize_excerpt(title, excerpt, url, settings)`.

`ask_service.py` — `_default_llm_fn`:

```python
def _default_llm_fn() -> LlmFn:
    """Production LLM call: litellm JSON-mode per Settings, via the provider seam."""
    import litellm

    from api.config import get_settings
    from api.services.providers import resolve_llm_fn

    settings = get_settings()
    llm_fn = resolve_llm_fn(settings, model=settings.litellm_model, completion=litellm.completion, stage="ask")

    def _call(prompt: str) -> str:
        response = llm_fn(
            messages=[
                {"role": "system", "content": ASK_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content or ""

    return _call
```

`Settings` must accept `CICADA_LLM_MODE` / `CICADA_OLLAMA_MODEL` from the env — it already does (`env_prefix="CICADA_"`).

- [ ] **Step 4: Run the seam tests + the modules' existing tests**

Run: `api/.venv/bin/python -m pytest api/tests/test_llm_seam_adoption.py api/tests/test_extractor_robustness.py api/tests/test_ask_service.py -v`
Expected: all PASS (`test_extractor_robustness` still monkeypatches `entity_extractor.litellm.acompletion`, which the seam receives as `completion=` at call time)
Run: `api/.venv/bin/python -m pytest api/tests -q`
Expected: all green

- [ ] **Step 5: Commit**

```bash
git add api/services/entity_extractor.py api/services/entity_resolver.py api/services/link_enrichment.py \
  api/services/ask_service.py api/tests/test_llm_seam_adoption.py
git commit -m "refactor(llm): route extraction, disambiguation, enrichment and /ask through resolve_llm_fn (seam complete)"
```

---

### Task 4: `sleep_run` and `agentic_write` events

**Files:**
- Modify: `api/services/git_service.py:508-515` (`commit_changes` returns the hash)
- Modify: `api/services/sleep_cycle.py` (`run` records `started` time; `_finalize` emits the event)
- Modify: `mcp/server.py:894-935` (`handle_write_claim`)
- Create: `api/tests/test_run_events.py`

**Interfaces:**
- `git_service.commit_changes(memory_path, message) -> str | None` (hash or None when nothing to commit)
- `sleep_cycle._finalize(memory_path, cycle_id, changes, settings=None, *, started: float | None = None, engine: str = "litellm") -> None`
- `sleep_cycle.run` stores `_state.started_monotonic` (new `SleepState` field `started_monotonic: float | None = None`)

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_run_events.py
from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from api.config import Settings
from api.services import git_service, sleep_cycle, telemetry


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    mem = tmp_path / "memory"
    (mem / "entities").mkdir(parents=True)
    _git(mem, "init", "-q")
    _git(mem, "config", "user.email", "t@t")
    _git(mem, "config", "user.name", "t")
    return mem


def test_commit_changes_returns_hash(repo):
    (repo / "entities" / "a.md").write_text("---\ntype: concept\n---\n")
    sha = asyncio.run(git_service.commit_changes(repo, "first"))
    assert sha and sha == _git(repo, "rev-parse", "HEAD").strip()
    assert asyncio.run(git_service.commit_changes(repo, "nothing")) is None


def test_finalize_records_sleep_run_event(repo):
    (repo / "entities" / "a.md").write_text("---\ntype: concept\n---\n")
    settings = Settings(memory_root=repo, litellm_model="gpt-5.4-mini")
    sleep_cycle._state.episodes_processed = 3
    sleep_cycle._state.entities_created = 1
    changes = [{"id": "a", "action": "created", "source_episode": "ep1", "trigger": "sleep/extraction"}]
    asyncio.run(sleep_cycle._finalize(repo, "sleep_test", changes, settings, started=0.0))
    events = [e for e in telemetry.read_events() if e.kind == "sleep_run"]
    assert len(events) == 1
    ev = events[0]
    assert ev.stage == "structural" and ev.model == "gpt-5.4-mini" and ev.bank == "memory"
    assert ev.refs["cycle_id"] == "sleep_test" and ev.refs["episodes_processed"] == 3
    assert ev.refs["commit"] == _git(repo, "rev-parse", "HEAD").strip()
    assert ev.duration_ms is not None and ev.duration_ms > 0


def test_agentic_write_event(repo, monkeypatch):
    from mcp import server

    monkeypatch.setattr(server, "get_memory_path", lambda: repo)
    monkeypatch.setattr(server.agentic_write, "write_claim",
                        lambda *a, **k: {"action": "written", "entity_id": "a", "claim_id": "c1", "subject": "a", "observer": "agent"},
                        raising=False)
    server.handle_write_claim("a", "uses", "b", None, None, None, "ep1")
    events = [e for e in telemetry.read_events() if e.kind == "agentic_write"]
    assert len(events) == 1
    assert events[0].connection == "session" and events[0].engine == "mcp-client"
    assert events[0].refs == {"entity_id": "a", "claim_id": "c1", "episode_id": "ep1", "action": "written"}
    assert events[0].cost_usd is None and events[0].billing == "subscription"
```

If `mcp/server.py` imports `agentic_write` lazily inside `handle_write_claim`, hoist `from api.services import agentic_write` to module level so the monkeypatch target exists (it is only a name binding; the function body keeps calling `agentic_write.write_claim`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `api/.venv/bin/python -m pytest api/tests/test_run_events.py -v`
Expected: FAIL (`commit_changes` returns None; `_finalize` has no `started` kwarg; no agentic events)

- [ ] **Step 3: Implement**

`git_service.commit_changes`:

```python
async def commit_changes(memory_path: Path, message: str) -> str | None:
    """Stage all changes and commit. Returns the new commit hash, or None when
    there was nothing to commit."""
    await _run_git(memory_path, "add", "-A")
    status = await _run_git(memory_path, "status", "--porcelain")
    if not status.strip():
        return None
    await _run_git(memory_path, "commit", "-m", message)
    return (await _run_git(memory_path, "rev-parse", "HEAD")).strip()
```

`sleep_cycle.py` — add `started_monotonic: float | None = None` to `SleepState`; in `run()` set `_state.started_monotonic = time.monotonic()` next to `started_at` (add `import time`); change the call at line 311 to `await _finalize(memory_path, cycle_id, changes, settings, started=_state.started_monotonic)`; change `_finalize` signature to `async def _finalize(memory_path, cycle_id, changes, settings=None, *, started: float | None = None, engine: str = "litellm") -> None` and replace its last four lines with:

```python
    message = git_service.build_commit_message(
        f"Sleep cycle {date_str}", body_lines, authors=authors
    )
    async with _lock:
        commit = await git_service.commit_changes(memory_path, message)

    from api.services import telemetry

    duration_ms = int((time.monotonic() - started) * 1000) if started is not None else None
    telemetry.record(telemetry.UsageEvent(
        kind="sleep_run", stage="structural", engine=engine,
        connection=telemetry.connection_for_model(authors[0])[0] if authors else None,
        model=authors[0] if authors else None,
        bank=telemetry.bank_name(settings) if settings is not None else memory_path.name,
        billing=telemetry.connection_for_model(authors[0])[1] if authors else "free",
        invocations=0, duration_ms=duration_ms, ok=True,
        refs={
            "cycle_id": cycle_id,
            "commit": commit,
            "episodes_processed": _state.episodes_processed,
            "episodes_requeued": _state.episodes_requeued,
            "entities_created": _state.entities_created,
            "entities_updated": _state.entities_updated,
            "skills_detected": _state.skills_detected,
        },
    ))
```

(`duration_ms` in the test is computed against `started=0.0`, hence `> 0`.)

`mcp/server.py` — at the end of `handle_write_claim`, just before building the human-readable `verb` reply, add:

```python
    from api.services import telemetry

    telemetry.record(telemetry.UsageEvent(
        kind="agentic_write", stage="driver", connection="session", engine="mcp-client",
        model=None, bank=get_memory_path().name, billing="subscription", invocations=1,
        refs={
            "entity_id": result.get("entity_id"),
            "claim_id": result.get("claim_id"),
            "episode_id": source_episode,
            "action": result.get("action"),
        },
    ))
```

placed after the `ambiguous_subject` / `error` early returns so only real writes count.

- [ ] **Step 4: Run tests**

Run: `api/.venv/bin/python -m pytest api/tests/test_run_events.py api/tests/test_contributors.py api/tests/test_sleep_resumable.py -v`
Expected: all PASS
Run: `api/.venv/bin/python -m pytest api/tests -q`
Expected: all green

- [ ] **Step 5: Commit**

```bash
git add api/services/git_service.py api/services/sleep_cycle.py mcp/server.py api/tests/test_run_events.py
git commit -m "feat(telemetry): sleep_run + agentic_write events; commit_changes returns the hash"
```

---

### Task 5: Aggregation service

**Files:**
- Create: `api/services/consumption_stats.py`
- Create: `api/tests/test_consumption_stats.py`

**Interfaces:**
- Consumes: `telemetry.read_events`, `git_service._run_git`, `git_service._parse_authors`, `pricing.price_for`
- Produces (all plain dicts, camelCased by the router models later):
  - `summary(memory_path, *, range_: str, today: date) -> dict` keys `cost_usd, equiv_cost_usd, invocations, tokens, memory_writes, sleep_runs, agentic_writes, streak_current, streak_best, range, since`
  - `calendar(memory_path, *, weeks: int, today: date) -> list[dict]` keys `date, memory_writes, events, tokens, cost_usd, equiv_cost_usd, level`
  - `stats(memory_path, *, range_: str, today: date) -> dict` keys `by_model, by_stage, by_connection, by_bank, hour_histogram, peak_day, longest_sleep_run, favorite_model, lifetime_tokens, first_event, series`
  - `per_connection(events, connection_statuses: list[dict]) -> list[dict]` keys `id, label, billing, price_usd_month, cost_usd, equiv_cost_usd, invocations, tokens, by_model`
  - `resolve_range(range_: str, today: date) -> date | None` (`"30d"|"month"|"all"|"<N>d"`)
  - `async memory_write_days(memory_path) -> dict[str, int]` (ISO day → number of `Cicada-Author`-trailered commits)
  - `streaks(active_days: set[str], today: date) -> tuple[int, int]`

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_consumption_stats.py
from __future__ import annotations

import asyncio
import subprocess
from datetime import date, timedelta
from pathlib import Path

import pytest

from api.services import consumption_stats as cs
from api.services import telemetry as tm

TODAY = date(2026, 8, 28)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    repo = tmp_path / "memory"
    (repo / "entities").mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    # two attributed commits on 2026-08-27, one legacy commit on 2026-08-20
    for day, msg in [("2026-08-20T03:00:00", "legacy\n"),
                     ("2026-08-27T03:00:00", "Sleep cycle 2026-08-27\n\nx\n\nCicada-Author: gpt-5.4-mini\n"),
                     ("2026-08-27T04:00:00", "Inbox resolution\n\nx\n\nCicada-Author: user\n")]:
        (repo / "entities" / f"{day[:10]}-{len(msg)}.md").write_text(msg)
        _git(repo, "add", "-A")
        subprocess.run(["git", "commit", "-q", "-m", msg], cwd=repo, check=True,
                       env={**__import__("os").environ, "GIT_AUTHOR_DATE": day, "GIT_COMMITTER_DATE": day})
    # ledger
    tm.record(tm.UsageEvent(ts="2026-08-27T03:10:00.000Z", kind="llm_call", stage="extraction", model="gpt-5.4-mini",
                            connection="byok-openai", input_tokens=1000, output_tokens=100, cost_usd=0.01, equiv_cost_usd=0.01))
    tm.record(tm.UsageEvent(ts="2026-08-27T03:11:00.000Z", kind="llm_call", stage="disambiguation", model="gpt-5.4-nano",
                            connection="byok-openai", input_tokens=500, output_tokens=50, cost_usd=0.002, equiv_cost_usd=0.002))
    tm.record(tm.UsageEvent(ts="2026-08-28T02:00:00.000Z", kind="llm_call", stage="driver", model="claude-sonnet-5",
                            connection="claude-plan", billing="subscription", engine="claude-cli",
                            input_tokens=20000, output_tokens=2000, cost_usd=None, equiv_cost_usd=0.4))
    tm.record(tm.UsageEvent(ts="2026-08-28T02:30:00.000Z", kind="sleep_run", stage="structural", model="claude-sonnet-5",
                            connection="claude-plan", billing="subscription", invocations=0, duration_ms=90000,
                            refs={"cycle_id": "sleep_x", "episodes_processed": 4}))
    tm.record(tm.UsageEvent(ts="2026-08-28T09:00:00.000Z", kind="agentic_write", stage="driver", connection="session",
                            engine="mcp-client", billing="subscription", refs={"entity_id": "a"}))
    tm.record(tm.UsageEvent(ts="2026-06-01T09:00:00.000Z", kind="llm_call", stage="ask", model="gpt-5.4-mini",
                            connection="byok-openai", input_tokens=10, output_tokens=10, cost_usd=0.5, equiv_cost_usd=0.5))
    return repo


def test_resolve_range():
    assert cs.resolve_range("30d", TODAY) == TODAY - timedelta(days=29)
    assert cs.resolve_range("month", TODAY) == date(2026, 8, 1)
    assert cs.resolve_range("all", TODAY) is None
    assert cs.resolve_range("7d", TODAY) == TODAY - timedelta(days=6)


def test_memory_write_days_counts_attributed_commits_only(env):
    days = asyncio.run(cs.memory_write_days(env))
    assert days == {"2026-08-27": 2}


def test_streaks():
    active = {"2026-08-28", "2026-08-27", "2026-08-25", "2026-08-24", "2026-08-23"}
    assert cs.streaks(active, TODAY) == (2, 3)
    assert cs.streaks({"2026-08-27"}, TODAY) == (1, 1)  # yesterday keeps the streak alive
    assert cs.streaks(set(), TODAY) == (0, 0)


def test_summary_month(env):
    s = asyncio.run(cs.summary(env, range_="month", today=TODAY))
    assert s["cost_usd"] == pytest.approx(0.012)
    assert s["equiv_cost_usd"] == pytest.approx(0.412)
    assert s["invocations"] == 3 and s["tokens"] == 23650
    assert s["memory_writes"] == 2 and s["sleep_runs"] == 1 and s["agentic_writes"] == 1
    assert (s["streak_current"], s["streak_best"]) == (2, 2)


def test_calendar_levels_and_merge(env):
    cal = asyncio.run(cs.calendar(env, weeks=2, today=TODAY))
    assert len(cal) == 14 and cal[-1]["date"] == "2026-08-28" and cal[0]["date"] == "2026-08-15"
    d27 = next(d for d in cal if d["date"] == "2026-08-27")
    d28 = next(d for d in cal if d["date"] == "2026-08-28")
    assert d27["memory_writes"] == 2 and d27["events"] == 2 and d27["cost_usd"] == pytest.approx(0.012)
    assert d28["memory_writes"] == 0 and d28["events"] == 3 and d28["tokens"] == 22000
    assert d28["level"] == 4 and d27["level"] >= 1
    assert all(d["level"] == 0 for d in cal if d["date"] not in ("2026-08-27", "2026-08-28"))


def test_stats_breakdowns(env):
    st = asyncio.run(cs.stats(env, range_="all", today=TODAY))
    models = {m["model"]: m for m in st["by_model"]}
    assert models["claude-sonnet-5"]["tokens"] == 22000 and models["claude-sonnet-5"]["cost_usd"] is None
    assert models["gpt-5.4-mini"]["cost_usd"] == pytest.approx(0.51)
    assert {s["stage"] for s in st["by_stage"]} >= {"extraction", "disambiguation", "driver", "ask"}
    assert st["favorite_model"] == "claude-sonnet-5" and st["lifetime_tokens"] == 23670
    assert st["hour_histogram"][2] == 2 and st["hour_histogram"][3] == 2 and len(st["hour_histogram"]) == 24
    assert st["peak_day"]["date"] == "2026-08-28"
    assert st["longest_sleep_run"]["duration_ms"] == 90000 and st["longest_sleep_run"]["cycle_id"] == "sleep_x"
    assert st["first_event"] == "2026-06-01"
    assert st["series"][-1]["date"] == "2026-08-28"


def test_per_connection_pricing(env):
    events = tm.read_events()
    statuses = [
        {"id": "claude-plan", "label": "Claude plan", "billing": "subscription", "priceUsdMonth": 200.0, "connected": True},
        {"id": "byok-openai", "label": "OpenAI API key", "billing": "usage", "priceUsdMonth": None, "connected": True},
    ]
    rows = {r["id"]: r for r in cs.per_connection(events, statuses)}
    assert rows["claude-plan"]["price_usd_month"] == 200.0 and rows["claude-plan"]["cost_usd"] is None
    assert rows["claude-plan"]["equiv_cost_usd"] == pytest.approx(0.4)
    assert rows["byok-openai"]["cost_usd"] == pytest.approx(0.512)
    assert {m["model"] for m in rows["byok-openai"]["by_model"]} == {"gpt-5.4-mini", "gpt-5.4-nano"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `api/.venv/bin/python -m pytest api/tests/test_consumption_stats.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `consumption_stats.py`**

```python
# api/services/consumption_stats.py
"""Aggregations for the Usage page (G51).

Two sources: the telemetry ledger (LLM calls, sleep runs, agentic writes) and
the memory repo's git log (``Cicada-Author``-trailered commits = memory
writes), so the calendar shows history from before the ledger existed.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

from api.services import git_service, telemetry
from api.services.telemetry import UsageEvent

_RANGE_RE = re.compile(r"^(\d+)d$")


def resolve_range(range_: str, today: date) -> date | None:
    if range_ == "all":
        return None
    if range_ == "month":
        return today.replace(day=1)
    m = _RANGE_RE.match(range_ or "30d")
    days = int(m.group(1)) if m else 30
    return today - timedelta(days=days - 1)


async def memory_write_days(memory_path: Path) -> dict[str, int]:
    if not (memory_path / ".git").exists():
        return {}
    sep, rec = "\x1f", "\x1e"
    try:
        out = await git_service._run_git(memory_path, "log", f"--format=%ad{sep}%b{rec}", "--date=short")
    except git_service.GitError:
        return {}
    days: Counter[str] = Counter()
    for record in out.split(rec):
        if sep not in record:
            continue
        day, body = record.strip("\n").split(sep, 1)
        if git_service._parse_authors(body):
            days[day.strip()] += 1
    return dict(days)


def streaks(active_days: set[str], today: date) -> tuple[int, int]:
    if not active_days:
        return 0, 0
    days = sorted(date.fromisoformat(d) for d in active_days)
    best = run = 1
    for prev, cur in zip(days, days[1:]):
        run = run + 1 if (cur - prev).days == 1 else 1
        best = max(best, run)
    cursor = today if today.isoformat() in active_days else today - timedelta(days=1)
    current = 0
    while cursor.isoformat() in active_days:
        current += 1
        cursor -= timedelta(days=1)
    return current, best


def _events_in(range_: str, today: date) -> list[UsageEvent]:
    start = resolve_range(range_, today)
    return telemetry.read_events(start=start, end=today)


def _sum_cost(events: list[UsageEvent], attr: str) -> float | None:
    vals = [getattr(e, attr) for e in events if getattr(e, attr) is not None]
    return round(sum(vals), 6) if vals else None


async def summary(memory_path: Path, *, range_: str, today: date) -> dict:
    events = _events_in(range_, today)
    start = resolve_range(range_, today)
    writes = {d: n for d, n in (await memory_write_days(memory_path)).items()
              if start is None or d >= start.isoformat()}
    active = set(writes) | {e.ts[:10] for e in events}
    cur, best = streaks(active, today)
    return {
        "cost_usd": _sum_cost(events, "cost_usd") or 0.0,
        "equiv_cost_usd": _sum_cost(events, "equiv_cost_usd") or 0.0,
        "invocations": sum(e.invocations for e in events if e.kind in ("llm_call", "ask")),
        "tokens": sum(e.tokens for e in events),
        "memory_writes": sum(writes.values()),
        "sleep_runs": sum(1 for e in events if e.kind == "sleep_run"),
        "agentic_writes": sum(1 for e in events if e.kind == "agentic_write"),
        "streak_current": cur,
        "streak_best": best,
        "range": range_,
        "since": start.isoformat() if start else None,
    }


def _levels(values: dict[str, float]) -> dict[str, int]:
    nonzero = sorted(v for v in values.values() if v > 0)
    if not nonzero:
        return {d: 0 for d in values}
    def q(p: float) -> float:
        return nonzero[min(len(nonzero) - 1, int(p * len(nonzero)))]
    cuts = (q(0.25), q(0.5), q(0.75))
    out = {}
    for d, v in values.items():
        out[d] = 0 if v <= 0 else 1 + sum(1 for c in cuts if v > c)
    return out


async def calendar(memory_path: Path, *, weeks: int, today: date) -> list[dict]:
    start = today - timedelta(days=weeks * 7 - 1)
    events = telemetry.read_events(start=start, end=today)
    writes = await memory_write_days(memory_path)
    per_day: dict[str, dict] = {}
    for i in range(weeks * 7):
        d = (start + timedelta(days=i)).isoformat()
        per_day[d] = {"date": d, "memory_writes": writes.get(d, 0), "events": 0, "tokens": 0,
                      "cost_usd": 0.0, "equiv_cost_usd": 0.0}
    for e in events:
        row = per_day.get(e.ts[:10])
        if row is None:
            continue
        row["events"] += 1
        row["tokens"] += e.tokens
        row["cost_usd"] += e.cost_usd or 0.0
        row["equiv_cost_usd"] += e.equiv_cost_usd or 0.0
    # Activity score for the colour level: memory writes weigh most, then events, then tokens.
    score = {d: r["memory_writes"] * 3 + r["events"] + r["tokens"] / 10000 for d, r in per_day.items()}
    levels = _levels(score)
    for d, r in per_day.items():
        r["level"] = levels[d]
        r["cost_usd"] = round(r["cost_usd"], 6)
        r["equiv_cost_usd"] = round(r["equiv_cost_usd"], 6)
    return list(per_day.values())


def _group(events: list[UsageEvent], key: str, label: str) -> list[dict]:
    groups: dict[str, list[UsageEvent]] = defaultdict(list)
    for e in events:
        groups[getattr(e, key) or "unknown"].append(e)
    rows = []
    for name, evs in groups.items():
        rows.append({
            label: name,
            "invocations": sum(e.invocations for e in evs),
            "input_tokens": sum(e.input_tokens for e in evs),
            "output_tokens": sum(e.output_tokens for e in evs),
            "cache_read_tokens": sum(e.cache_read_tokens for e in evs),
            "cache_write_tokens": sum(e.cache_write_tokens for e in evs),
            "tokens": sum(e.tokens for e in evs),
            "cost_usd": _sum_cost(evs, "cost_usd"),
            "equiv_cost_usd": _sum_cost(evs, "equiv_cost_usd"),
        })
    rows.sort(key=lambda r: -r["tokens"])
    return rows


async def stats(memory_path: Path, *, range_: str, today: date) -> dict:
    events = _events_in(range_, today)
    calls = [e for e in events if e.kind in ("llm_call", "ask")]
    hours = [0] * 24
    for e in events:
        try:
            hours[int(e.ts[11:13])] += 1
        except ValueError:
            pass
    by_day: dict[str, dict] = defaultdict(lambda: {"tokens": 0, "cost_usd": 0.0, "equiv_cost_usd": 0.0, "events": 0})
    for e in events:
        d = by_day[e.ts[:10]]
        d["tokens"] += e.tokens
        d["cost_usd"] += e.cost_usd or 0.0
        d["equiv_cost_usd"] += e.equiv_cost_usd or 0.0
        d["events"] += 1
    series = [{"date": d, **{k: (round(v, 6) if isinstance(v, float) else v) for k, v in row.items()}}
              for d, row in sorted(by_day.items())]
    peak = max(series, key=lambda r: r["tokens"], default=None)
    runs = [e for e in events if e.kind == "sleep_run" and e.duration_ms is not None]
    longest = max(runs, key=lambda e: e.duration_ms, default=None)
    by_model = _group(calls, "model", "model")
    all_events = telemetry.read_events()
    return {
        "by_model": by_model,
        "by_stage": _group(events, "stage", "stage"),
        "by_connection": _group(events, "connection", "connection"),
        "by_bank": _group(events, "bank", "bank"),
        "hour_histogram": hours,
        "peak_day": {"date": peak["date"], "tokens": peak["tokens"]} if peak else None,
        "longest_sleep_run": (
            {"cycle_id": longest.refs.get("cycle_id"), "duration_ms": longest.duration_ms,
             "episodes_processed": longest.refs.get("episodes_processed"), "date": longest.ts[:10]}
            if longest else None
        ),
        "favorite_model": by_model[0]["model"] if by_model else None,
        "lifetime_tokens": sum(e.tokens for e in all_events),
        "first_event": min((e.ts[:10] for e in all_events), default=None),
        "series": series,
        "range": range_,
    }


def per_connection(events: list[UsageEvent], connection_statuses: list[dict]) -> list[dict]:
    by_conn: dict[str, list[UsageEvent]] = defaultdict(list)
    for e in events:
        by_conn[e.connection or "unknown"].append(e)
    rows = []
    for st in connection_statuses:
        evs = by_conn.get(st["id"], [])
        billing = st.get("billing", "usage")
        rows.append({
            "id": st["id"],
            "label": st.get("label", st["id"]),
            "billing": billing,
            "connected": bool(st.get("connected")),
            "price_usd_month": st.get("priceUsdMonth") if billing == "subscription" else None,
            "cost_usd": _sum_cost(evs, "cost_usd") if billing == "usage" else None,
            "equiv_cost_usd": _sum_cost(evs, "equiv_cost_usd"),
            "invocations": sum(e.invocations for e in evs),
            "tokens": sum(e.tokens for e in evs),
            "throttle_events": sum(1 for e in evs if e.throttled or e.kind == "throttle"),
            "by_model": _group([e for e in evs if e.kind in ("llm_call", "ask")], "model", "model"),
        })
    return rows
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `api/.venv/bin/python -m pytest api/tests/test_consumption_stats.py -v`
Expected: 8 PASS

- [ ] **Step 5: Commit**

```bash
git add api/services/consumption_stats.py api/tests/test_consumption_stats.py
git commit -m "feat(consumption): summary/calendar/stats/per-connection aggregation over ledger + git history"
```

---

### Task 6: Harness readers (Claude Code stats-cache, Codex rate limits) + `/consumption` router

**Files:**
- Create: `api/services/harness_stats.py`
- Create: `api/routers/consumption.py`
- Create: `api/tests/test_harness_stats.py`, `api/tests/test_consumption_api.py`
- Modify: `api/models/schemas.py` (append models), `api/main.py` (mount)

**Interfaces:**
- `harness_stats.claude_code_stats(path: Path | None = None) -> dict | None` keys `daily_activity[{date, message_count, session_count, tool_call_count}]`, `model_usage{model:{input_tokens, output_tokens, cache_read_tokens, cache_write_tokens}}`, `hour_counts[24]`, `total_sessions`, `total_messages`, `longest_session`, `first_session_date`, `source: str`
- `harness_stats.codex_rate_limits(sessions_dir: Path | None = None) -> dict | None` keys `plan_type, primary{used_percent, window_minutes, resets_at}, secondary{...}, observed_at, source`
- Endpoints: `GET /consumption/summary?range=`, `/consumption/calendar?weeks=`, `/consumption/stats?range=`, `/consumption/connections?range=`, `/consumption/harness`

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_harness_stats.py
from __future__ import annotations

import json

from api.services import harness_stats as hs


def test_claude_code_stats_reads_cache(tmp_path):
    cache = tmp_path / "stats-cache.json"
    cache.write_text(json.dumps({
        "version": 5,
        "dailyActivity": [{"date": "2026-08-27", "messageCount": 40, "sessionCount": 3, "toolCallCount": 12}],
        "dailyModelTokens": [],
        "modelUsage": {"claude-sonnet-5": {"inputTokens": 100, "outputTokens": 20, "cacheReadInputTokens": 5, "cacheCreationInputTokens": 1}},
        "totalSessions": 10, "totalMessages": 400,
        "longestSession": {"sessionId": "s", "duration": 3600000, "messageCount": 90, "timestamp": "2026-08-01T00:00:00Z"},
        "firstSessionDate": "2026-05-01", "hourCounts": {"9": 4, "23": 1},
    }))
    got = hs.claude_code_stats(cache)
    assert got["daily_activity"][0] == {"date": "2026-08-27", "message_count": 40, "session_count": 3, "tool_call_count": 12}
    assert got["model_usage"]["claude-sonnet-5"] == {"input_tokens": 100, "output_tokens": 20, "cache_read_tokens": 5, "cache_write_tokens": 1}
    assert got["hour_counts"][9] == 4 and got["hour_counts"][23] == 1 and len(got["hour_counts"]) == 24
    assert got["total_sessions"] == 10 and got["source"] == str(cache)


def test_claude_code_stats_missing_or_corrupt(tmp_path):
    assert hs.claude_code_stats(tmp_path / "nope.json") is None
    (tmp_path / "bad.json").write_text("{")
    assert hs.claude_code_stats(tmp_path / "bad.json") is None


def test_codex_rate_limits_newest_token_count(tmp_path):
    day = tmp_path / "2026" / "08" / "28"
    day.mkdir(parents=True)
    older = day / "rollout-2026-08-28T01-00-00-aaa.jsonl"
    newer = day / "rollout-2026-08-28T02-00-00-bbb.jsonl"
    older.write_text(json.dumps({"type": "event_msg", "payload": {"type": "token_count", "rate_limits": {
        "plan_type": "plus", "primary": {"used_percent": 10, "window_minutes": 300, "resets_at": 1}}}}) + "\n")
    newer.write_text("\n".join([
        json.dumps({"type": "session_meta", "payload": {"id": "x"}}),
        json.dumps({"type": "event_msg", "timestamp": "2026-08-28T02:05:00Z", "payload": {"type": "token_count", "rate_limits": {
            "plan_type": "plus", "primary": {"used_percent": 42.5, "window_minutes": 300, "resets_at": 1756350000},
            "secondary": {"used_percent": 12, "window_minutes": 10080, "resets_at": 1756800000}}}}),
    ]) + "\n")
    got = hs.codex_rate_limits(tmp_path)
    assert got["plan_type"] == "plus" and got["primary"]["used_percent"] == 42.5
    assert got["secondary"]["window_minutes"] == 10080 and got["source"].endswith("bbb.jsonl")


def test_codex_rate_limits_none_when_absent(tmp_path):
    assert hs.codex_rate_limits(tmp_path) is None
```

```python
# api/tests/test_consumption_api.py
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import telemetry as tm
from api.services.connections import registry


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path / "memory"))
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    config.get_settings.cache_clear()
    registry.reset_registry()

    async def statuses(self, fresh=False):
        from api.models.schemas import ConnectionKind, ConnectionStatus
        return [ConnectionStatus(id="byok-openai", label="OpenAI API key", kind=ConnectionKind.usage,
                                 available=True, connected=True, billing="usage")]

    monkeypatch.setattr(registry.Registry, "statuses", statuses)
    tm.record(tm.UsageEvent(kind="llm_call", stage="ask", model="gpt-5.4-mini", connection="byok-openai",
                            input_tokens=10, output_tokens=5, cost_usd=0.01, equiv_cost_usd=0.01))
    yield TestClient(main.app)
    registry.reset_registry()
    config.get_settings.cache_clear()


def test_summary(client):
    body = client.get("/consumption/summary?range=30d").json()
    assert body["costUsd"] == 0.01 and body["invocations"] == 1 and body["range"] == "30d"


def test_calendar_shape(client):
    body = client.get("/consumption/calendar?weeks=4").json()
    assert len(body["days"]) == 28 and {"date", "memoryWrites", "events", "tokens", "level"} <= set(body["days"][0])


def test_stats(client):
    body = client.get("/consumption/stats?range=all").json()
    assert body["byModel"][0]["model"] == "gpt-5.4-mini" and len(body["hourHistogram"]) == 24


def test_connections(client):
    body = client.get("/consumption/connections").json()
    assert body["connections"][0]["id"] == "byok-openai" and body["connections"][0]["costUsd"] == 0.01


def test_harness_is_200_even_when_nothing_exists(client, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    body = client.get("/consumption/harness").json()
    assert body == {"claudeCode": None, "codex": None}


def test_bad_range_422(client):
    assert client.get("/consumption/summary?range=yesterday").status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `api/.venv/bin/python -m pytest api/tests/test_harness_stats.py api/tests/test_consumption_api.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `harness_stats.py`**

```python
# api/services/harness_stats.py
"""Read-only, tolerant readers for the harnesses' OWN usage data (advanced view).

Claude Code keeps a pre-aggregated ``stats-cache.json`` (the store behind its
``/stats`` panel); Codex logs a ``rate_limits`` snapshot on every turn into
its session rollouts. Both are local files, involve no network and no
credential, and are labelled in the UI as the harness's data, not Cicada's.
Everything here returns ``None`` on any problem — never raises.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def _claude_config_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser()


def claude_code_stats(path: Path | None = None) -> dict | None:
    path = path or _claude_config_dir() / "stats-cache.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    hours = [0] * 24
    for k, v in (data.get("hourCounts") or {}).items():
        try:
            hours[int(k)] = int(v)
        except (ValueError, IndexError, TypeError):
            continue
    model_usage = {}
    for model, u in (data.get("modelUsage") or {}).items():
        u = u or {}
        model_usage[model] = {
            "input_tokens": int(u.get("inputTokens", 0) or 0),
            "output_tokens": int(u.get("outputTokens", 0) or 0),
            "cache_read_tokens": int(u.get("cacheReadInputTokens", 0) or 0),
            "cache_write_tokens": int(u.get("cacheCreationInputTokens", 0) or 0),
        }
    return {
        "daily_activity": [
            {"date": d.get("date"), "message_count": int(d.get("messageCount", 0) or 0),
             "session_count": int(d.get("sessionCount", 0) or 0), "tool_call_count": int(d.get("toolCallCount", 0) or 0)}
            for d in (data.get("dailyActivity") or []) if isinstance(d, dict)
        ],
        "model_usage": model_usage,
        "hour_counts": hours,
        "total_sessions": int(data.get("totalSessions", 0) or 0),
        "total_messages": int(data.get("totalMessages", 0) or 0),
        "longest_session": data.get("longestSession"),
        "first_session_date": data.get("firstSessionDate"),
        "source": str(path),
    }


def _codex_sessions_dir() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser() / "sessions"


def codex_rate_limits(sessions_dir: Path | None = None) -> dict | None:
    sessions_dir = sessions_dir or _codex_sessions_dir()
    if not sessions_dir.exists():
        return None
    files = sorted(sessions_dir.rglob("rollout-*.jsonl"), key=lambda p: p.name, reverse=True)
    for path in files[:20]:  # newest files first; stop at the first usable snapshot
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            payload = obj.get("payload") or {}
            if obj.get("type") == "event_msg" and payload.get("type") == "token_count" and payload.get("rate_limits"):
                rl = payload["rate_limits"]
                return {
                    "plan_type": rl.get("plan_type"),
                    "primary": rl.get("primary"),
                    "secondary": rl.get("secondary"),
                    "observed_at": obj.get("timestamp"),
                    "source": str(path),
                }
    return None
```

- [ ] **Step 4: Schemas + router + mount**

Append to `api/models/schemas.py`:

```python
# --- Consumption / traceability (G51) ---


class ConsumptionSummary(CamelModel):
    cost_usd: float = 0.0
    equiv_cost_usd: float = 0.0
    invocations: int = 0
    tokens: int = 0
    memory_writes: int = 0
    sleep_runs: int = 0
    agentic_writes: int = 0
    streak_current: int = 0
    streak_best: int = 0
    range: str
    since: Optional[str] = None


class CalendarDay(CamelModel):
    date: str
    memory_writes: int = 0
    events: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    equiv_cost_usd: float = 0.0
    level: int = 0


class ConsumptionCalendar(CamelModel):
    days: list[CalendarDay]
    weeks: int


class ConsumptionStats(CamelModel):
    by_model: list[dict]
    by_stage: list[dict]
    by_connection: list[dict]
    by_bank: list[dict]
    hour_histogram: list[int]
    peak_day: Optional[dict] = None
    longest_sleep_run: Optional[dict] = None
    favorite_model: Optional[str] = None
    lifetime_tokens: int = 0
    first_event: Optional[str] = None
    series: list[dict]
    range: str


class ConnectionConsumption(CamelModel):
    id: str
    label: str
    billing: str
    connected: bool = False
    price_usd_month: Optional[float] = None
    cost_usd: Optional[float] = None
    equiv_cost_usd: Optional[float] = None
    invocations: int = 0
    tokens: int = 0
    throttle_events: int = 0
    by_model: list[dict] = []


class ConsumptionConnections(CamelModel):
    connections: list[ConnectionConsumption]
    range: str


class HarnessStats(CamelModel):
    claude_code: Optional[dict] = None
    codex: Optional[dict] = None
```

```python
# api/routers/consumption.py
"""Consumption / traceability dashboard (G51)."""
from __future__ import annotations

import re
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from api.config import Settings, get_settings
from api.models.schemas import (
    CalendarDay, ConsumptionCalendar, ConsumptionConnections, ConsumptionStats, ConsumptionSummary,
    ConnectionConsumption, HarnessStats,
)
from api.services import consumption_stats, harness_stats, telemetry
from api.services.connections.registry import get_registry
from pydantic.alias_generators import to_camel

router = APIRouter(prefix="/consumption")
_RANGE_OK = re.compile(r"^(all|month|\d{1,4}d)$")


def _camel_rows(rows: list[dict]) -> list[dict]:
    """The by_* breakdowns are ``list[dict]`` (not declared models), so CamelModel
    does not convert their keys — do it here so Swift's ``StatsRow`` decodes them."""
    return [{to_camel(k): v for k, v in row.items()} for row in rows]


def _range(range_: str = Query("30d", alias="range")) -> str:
    if not _RANGE_OK.match(range_):
        raise HTTPException(status_code=422, detail="range must be 'all', 'month' or '<N>d'")
    return range_


@router.get("/summary", response_model=ConsumptionSummary)
async def summary(range_: str = Depends(_range), settings: Settings = Depends(get_settings)):
    return ConsumptionSummary(**await consumption_stats.summary(settings.memory_path, range_=range_, today=date.today()))


@router.get("/calendar", response_model=ConsumptionCalendar)
async def calendar(weeks: int = Query(53, ge=1, le=106), settings: Settings = Depends(get_settings)):
    days = await consumption_stats.calendar(settings.memory_path, weeks=weeks, today=date.today())
    return ConsumptionCalendar(days=[CalendarDay(**d) for d in days], weeks=weeks)


@router.get("/stats", response_model=ConsumptionStats)
async def stats(range_: str = Depends(_range), settings: Settings = Depends(get_settings)):
    data = await consumption_stats.stats(settings.memory_path, range_=range_, today=date.today())
    for key in ("by_model", "by_stage", "by_connection", "by_bank", "series"):
        data[key] = _camel_rows(data[key])
    return ConsumptionStats(**data)


@router.get("/connections", response_model=ConsumptionConnections)
async def connections(range_: str = Depends(_range), settings: Settings = Depends(get_settings)):
    statuses = [s.model_dump() for s in await get_registry(settings).statuses()]
    start = consumption_stats.resolve_range(range_, date.today())
    events = telemetry.read_events(start=start, end=date.today())
    rows = consumption_stats.per_connection(events, statuses)
    for r in rows:
        r["by_model"] = _camel_rows(r["by_model"])
    return ConsumptionConnections(connections=[ConnectionConsumption(**r) for r in rows], range=range_)


@router.get("/harness", response_model=HarnessStats)
async def harness():
    return HarnessStats(claude_code=harness_stats.claude_code_stats(), codex=harness_stats.codex_rate_limits())
```

`api/main.py`: import `consumption` and `app.include_router(consumption.router, tags=["consumption"])`.

- [ ] **Step 5: Run tests**

Run: `api/.venv/bin/python -m pytest api/tests/test_harness_stats.py api/tests/test_consumption_api.py -v`
Expected: 10 PASS
Run: `api/.venv/bin/python -m pytest api/tests -q`
Expected: all green

- [ ] **Step 6: Commit**

```bash
git add api/services/harness_stats.py api/routers/consumption.py api/models/schemas.py api/main.py \
  api/tests/test_harness_stats.py api/tests/test_consumption_api.py
git commit -m "feat(api): /consumption summary|calendar|stats|connections|harness endpoints"
```

---

### Task 7: Swift test target + pure formatting/layout logic

**Files:**
- Modify: `app/CicadaApp/Package.swift`
- Create: `app/CicadaApp/Sources/CicadaApp/Utilities/UsageFormat.swift`
- Create: `app/CicadaApp/Sources/CicadaApp/Utilities/CalendarLayout.swift`
- Create: `app/CicadaApp/Tests/CicadaAppTests/UsageFormatTests.swift`
- Create: `app/CicadaApp/Tests/CicadaAppTests/CalendarLayoutTests.swift`

**Interfaces:**
- `enum UsageFormat { static func tokens(_ n: Int) -> String; static func usd(_ x: Double?) -> String; static func costLine(costUsd: Double, equivUsd: Double, subscriptionUsd: Double?) -> String }`
- `struct CalendarCell: Hashable { let date: String; let level: Int; let memoryWrites: Int; let events: Int; let tokens: Int }`
- `enum CalendarLayout { static func columns(_ days: [CalendarCell]) -> [[CalendarCell?]]; static func monthLabels(_ columns: [[CalendarCell?]]) -> [(column: Int, label: String)] }` — columns are weeks (Monday-first, 7 rows), the first column padded with `nil` before the first day's weekday.

- [ ] **Step 1: Package.swift**

```swift
// swift-tools-version: 5.10
import PackageDescription

let package = Package(
    name: "CicadaApp",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(
            name: "CicadaApp",
            resources: [.copy("Resources")]
        ),
        .testTarget(
            name: "CicadaAppTests",
            dependencies: ["CicadaApp"]
        )
    ]
)
```

- [ ] **Step 2: Write the failing tests**

```swift
// app/CicadaApp/Tests/CicadaAppTests/UsageFormatTests.swift
import XCTest
@testable import CicadaApp

final class UsageFormatTests: XCTestCase {
    func testTokens() {
        XCTAssertEqual(UsageFormat.tokens(0), "0")
        XCTAssertEqual(UsageFormat.tokens(999), "999")
        XCTAssertEqual(UsageFormat.tokens(41_200), "41.2k")
        XCTAssertEqual(UsageFormat.tokens(1_340_000), "1.34M")
    }

    func testUsd() {
        XCTAssertEqual(UsageFormat.usd(nil), "n/a")
        XCTAssertEqual(UsageFormat.usd(0), "$0.00")
        XCTAssertEqual(UsageFormat.usd(3.126), "$3.13")
        XCTAssertEqual(UsageFormat.usd(0.0031), "$0.0031")
    }

    func testCostLineSubscriptionOnly() {
        XCTAssertEqual(UsageFormat.costLine(costUsd: 0, equivUsd: 4.2, subscriptionUsd: 200),
                       "Included in plan · ≈ $4.20 at API list price")
    }

    func testCostLineUsage() {
        XCTAssertEqual(UsageFormat.costLine(costUsd: 3.12, equivUsd: 3.12, subscriptionUsd: nil), "$3.12 spent")
    }

    func testCostLineMixed() {
        XCTAssertEqual(UsageFormat.costLine(costUsd: 3.12, equivUsd: 7.32, subscriptionUsd: 200),
                       "$3.12 spent · plan work ≈ $4.20 at API list price")
    }
}
```

```swift
// app/CicadaApp/Tests/CicadaAppTests/CalendarLayoutTests.swift
import XCTest
@testable import CicadaApp

final class CalendarLayoutTests: XCTestCase {
    private func cell(_ date: String, level: Int = 0) -> CalendarCell {
        CalendarCell(date: date, level: level, memoryWrites: 0, events: 0, tokens: 0)
    }

    func testPadsFirstWeekToMonday() {
        // 2026-08-27 is a Thursday → 3 nil pads (Mon, Tue, Wed) before it.
        let cols = CalendarLayout.columns([cell("2026-08-27"), cell("2026-08-28")])
        XCTAssertEqual(cols.count, 1)
        XCTAssertEqual(cols[0].count, 7)
        XCTAssertNil(cols[0][0]); XCTAssertNil(cols[0][2])
        XCTAssertEqual(cols[0][3]?.date, "2026-08-27")
        XCTAssertEqual(cols[0][4]?.date, "2026-08-28")
        XCTAssertNil(cols[0][6])
    }

    func testSplitsIntoWeeks() {
        let days = (0..<14).map { i -> CalendarCell in
            let d = Calendar(identifier: .iso8601).date(byAdding: .day, value: i, to: ISO8601DateFormatter().date(from: "2026-08-03T00:00:00Z")!)!
            let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; f.timeZone = TimeZone(identifier: "UTC")
            return cell(f.string(from: d))
        }
        let cols = CalendarLayout.columns(days) // 2026-08-03 is a Monday
        XCTAssertEqual(cols.count, 2)
        XCTAssertEqual(cols[0][0]?.date, "2026-08-03")
        XCTAssertEqual(cols[1][6]?.date, "2026-08-16")
    }

    func testMonthLabelsAtFirstColumnOfEachMonth() {
        let cols = CalendarLayout.columns([cell("2026-07-30"), cell("2026-07-31"), cell("2026-08-01"), cell("2026-08-02"), cell("2026-08-03"), cell("2026-08-04")])
        let labels = CalendarLayout.monthLabels(cols)
        XCTAssertEqual(labels.map(\.label), ["Jul", "Aug"])
        XCTAssertEqual(labels.map(\.column), [0, 1])
    }
}
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd app/CicadaApp && swift test`
Expected: compile errors — `UsageFormat`, `CalendarCell`, `CalendarLayout` undefined

- [ ] **Step 4: Implement**

```swift
// app/CicadaApp/Sources/CicadaApp/Utilities/UsageFormat.swift
import Foundation

/// Number/cost formatting for the Usage page. Honesty rule (spec §6.6):
/// subscription work is never shown as "spent" — only as an API-equivalent estimate.
enum UsageFormat {
    static func tokens(_ n: Int) -> String {
        switch n {
        case ..<1_000: return "\(n)"
        case ..<1_000_000: return trim(Double(n) / 1_000, digits: 1) + "k"
        default: return trim(Double(n) / 1_000_000, digits: 2) + "M"
        }
    }

    static func usd(_ x: Double?) -> String {
        guard let x else { return "n/a" }
        if x == 0 { return "$0.00" }
        if x < 0.01 { return "$" + String(format: "%.4f", x) }
        return "$" + String(format: "%.2f", x)
    }

    static func costLine(costUsd: Double, equivUsd: Double, subscriptionUsd: Double?) -> String {
        let planEquiv = max(0, equivUsd - costUsd)
        if costUsd == 0 && subscriptionUsd != nil {
            return "Included in plan · ≈ \(usd(planEquiv)) at API list price"
        }
        if subscriptionUsd == nil || planEquiv < 0.005 {
            return "\(usd(costUsd)) spent"
        }
        return "\(usd(costUsd)) spent · plan work ≈ \(usd(planEquiv)) at API list price"
    }

    private static func trim(_ v: Double, digits: Int) -> String {
        var s = String(format: "%.\(digits)f", v)
        while s.contains(".") && (s.hasSuffix("0") || s.hasSuffix(".")) { s.removeLast() }
        return s
    }
}
```

```swift
// app/CicadaApp/Sources/CicadaApp/Utilities/CalendarLayout.swift
import Foundation

struct CalendarCell: Hashable {
    let date: String   // yyyy-MM-dd
    let level: Int     // 0…4
    let memoryWrites: Int
    let events: Int
    let tokens: Int
}

/// GitHub-style layout: one column per ISO week, 7 rows Monday→Sunday.
enum CalendarLayout {
    private static let formatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        f.timeZone = TimeZone(identifier: "UTC")
        f.locale = Locale(identifier: "en_US_POSIX")
        return f
    }()

    /// 0 = Monday … 6 = Sunday.
    static func weekdayIndex(_ iso: String) -> Int {
        guard let d = formatter.date(from: iso) else { return 0 }
        var cal = Calendar(identifier: .iso8601)
        cal.timeZone = TimeZone(identifier: "UTC")!
        return (cal.component(.weekday, from: d) + 5) % 7
    }

    static func columns(_ days: [CalendarCell]) -> [[CalendarCell?]] {
        guard let first = days.first else { return [] }
        var flat: [CalendarCell?] = Array(repeating: nil, count: weekdayIndex(first.date))
        flat.append(contentsOf: days.map { Optional($0) })
        while flat.count % 7 != 0 { flat.append(nil) }
        return stride(from: 0, to: flat.count, by: 7).map { Array(flat[$0..<$0 + 7]) }
    }

    static func monthLabels(_ columns: [[CalendarCell?]]) -> [(column: Int, label: String)] {
        var out: [(Int, String)] = []
        var seen = ""
        for (i, col) in columns.enumerated() {
            guard let firstDay = col.compactMap({ $0 }).first else { continue }
            let month = String(firstDay.date.prefix(7))
            if month != seen {
                seen = month
                let idx = Int(firstDay.date.dropFirst(5).prefix(2)) ?? 1
                out.append((i, formatter.shortMonthSymbols[idx - 1]))
            }
        }
        return out.map { (column: $0.0, label: $0.1) }
    }
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd app/CicadaApp && swift test`
Expected: 8 tests pass

- [ ] **Step 6: Commit**

```bash
git add app/CicadaApp/Package.swift app/CicadaApp/Sources/CicadaApp/Utilities app/CicadaApp/Tests
git commit -m "feat(app): CicadaAppTests target + UsageFormat/CalendarLayout pure logic"
```

---

### Task 8: Swift models, API methods, view model, theme ramp

**Files:**
- Create: `app/CicadaApp/Sources/CicadaApp/Models/Consumption.swift`
- Modify: `app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift` (new `// MARK: - Consumption` section)
- Create: `app/CicadaApp/Sources/CicadaApp/ViewModels/UsageViewModel.swift`
- Modify: `app/CicadaApp/Sources/CicadaApp/Theme/CicadaTheme.swift` (add `heatRamp(level:)`)
- Create: `app/CicadaApp/Tests/CicadaAppTests/ConsumptionDecodingTests.swift`

- [ ] **Step 1: Write the failing decoding test**

```swift
// app/CicadaApp/Tests/CicadaAppTests/ConsumptionDecodingTests.swift
import XCTest
@testable import CicadaApp

final class ConsumptionDecodingTests: XCTestCase {
    func testSummaryDecodesWithMissingFields() throws {
        let json = #"{"costUsd": 1.5, "range": "30d"}"#.data(using: .utf8)!
        let s = try JSONDecoder().decode(ConsumptionSummary.self, from: json)
        XCTAssertEqual(s.costUsd, 1.5); XCTAssertEqual(s.invocations, 0); XCTAssertEqual(s.streakCurrent, 0)
    }

    func testCalendarDayToCell() throws {
        let json = #"{"days":[{"date":"2026-08-28","memoryWrites":2,"events":3,"tokens":100,"level":4}],"weeks":1}"#.data(using: .utf8)!
        let c = try JSONDecoder().decode(ConsumptionCalendar.self, from: json)
        XCTAssertEqual(c.days[0].cell, CalendarCell(date: "2026-08-28", level: 4, memoryWrites: 2, events: 3, tokens: 100))
    }

    func testStatsRowsDecodeLooseDicts() throws {
        let json = #"{"byModel":[{"model":"gpt-5.4-mini","tokens":10,"costUsd":null,"invocations":1}],"byStage":[],"byConnection":[],"byBank":[],"hourHistogram":[0],"series":[],"range":"all"}"#.data(using: .utf8)!
        let s = try JSONDecoder().decode(ConsumptionStats.self, from: json)
        XCTAssertEqual(s.byModel[0].name, "gpt-5.4-mini"); XCTAssertNil(s.byModel[0].costUsd); XCTAssertEqual(s.byModel[0].tokens, 10)
    }
}
```

- [ ] **Step 2: Models**

```swift
// app/CicadaApp/Sources/CicadaApp/Models/Consumption.swift
import Foundation

struct ConsumptionSummary: Codable {
    var costUsd: Double = 0
    var equivCostUsd: Double = 0
    var invocations: Int = 0
    var tokens: Int = 0
    var memoryWrites: Int = 0
    var sleepRuns: Int = 0
    var agenticWrites: Int = 0
    var streakCurrent: Int = 0
    var streakBest: Int = 0
    var range: String = "30d"
    var since: String?

    init() {}
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        costUsd = try c.decodeIfPresent(Double.self, forKey: .costUsd) ?? 0
        equivCostUsd = try c.decodeIfPresent(Double.self, forKey: .equivCostUsd) ?? 0
        invocations = try c.decodeIfPresent(Int.self, forKey: .invocations) ?? 0
        tokens = try c.decodeIfPresent(Int.self, forKey: .tokens) ?? 0
        memoryWrites = try c.decodeIfPresent(Int.self, forKey: .memoryWrites) ?? 0
        sleepRuns = try c.decodeIfPresent(Int.self, forKey: .sleepRuns) ?? 0
        agenticWrites = try c.decodeIfPresent(Int.self, forKey: .agenticWrites) ?? 0
        streakCurrent = try c.decodeIfPresent(Int.self, forKey: .streakCurrent) ?? 0
        streakBest = try c.decodeIfPresent(Int.self, forKey: .streakBest) ?? 0
        range = try c.decodeIfPresent(String.self, forKey: .range) ?? "30d"
        since = try c.decodeIfPresent(String.self, forKey: .since)
    }
}

struct CalendarDay: Codable, Identifiable {
    let date: String
    let memoryWrites: Int
    let events: Int
    let tokens: Int
    let costUsd: Double
    let equivCostUsd: Double
    let level: Int
    var id: String { date }

    enum CodingKeys: String, CodingKey { case date, memoryWrites, events, tokens, costUsd, equivCostUsd, level }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        date = try c.decode(String.self, forKey: .date)
        memoryWrites = try c.decodeIfPresent(Int.self, forKey: .memoryWrites) ?? 0
        events = try c.decodeIfPresent(Int.self, forKey: .events) ?? 0
        tokens = try c.decodeIfPresent(Int.self, forKey: .tokens) ?? 0
        costUsd = try c.decodeIfPresent(Double.self, forKey: .costUsd) ?? 0
        equivCostUsd = try c.decodeIfPresent(Double.self, forKey: .equivCostUsd) ?? 0
        level = try c.decodeIfPresent(Int.self, forKey: .level) ?? 0
    }
    var cell: CalendarCell { CalendarCell(date: date, level: level, memoryWrites: memoryWrites, events: events, tokens: tokens) }
}

struct ConsumptionCalendar: Codable {
    let days: [CalendarDay]
    let weeks: Int
}

/// One row of a by-model / by-stage / by-connection / by-bank table. The
/// backend sends loose dicts; the first string-valued key is the row name.
struct StatsRow: Codable, Identifiable {
    let name: String
    let invocations: Int
    let inputTokens: Int
    let outputTokens: Int
    let cacheReadTokens: Int
    let cacheWriteTokens: Int
    let tokens: Int
    let costUsd: Double?
    let equivCostUsd: Double?
    var id: String { name }

    private struct Key: CodingKey {
        var stringValue: String; var intValue: Int? { nil }
        init?(stringValue: String) { self.stringValue = stringValue }
        init?(intValue: Int) { nil }
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: Key.self)
        func int(_ k: String) -> Int { (try? c.decodeIfPresent(Int.self, forKey: Key(stringValue: k)!)) ?? 0 }
        func dbl(_ k: String) -> Double? { try? c.decodeIfPresent(Double.self, forKey: Key(stringValue: k)!) }
        name = ["model", "stage", "connection", "bank"].lazy
            .compactMap { try? c.decodeIfPresent(String.self, forKey: Key(stringValue: $0)!) }.first ?? "unknown"
        invocations = int("invocations"); inputTokens = int("inputTokens"); outputTokens = int("outputTokens")
        cacheReadTokens = int("cacheReadTokens"); cacheWriteTokens = int("cacheWriteTokens"); tokens = int("tokens")
        costUsd = dbl("costUsd"); equivCostUsd = dbl("equivCostUsd")
    }
}

struct SeriesPoint: Codable, Identifiable {
    let date: String
    let tokens: Int
    let costUsd: Double
    let equivCostUsd: Double
    let events: Int
    var id: String { date }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        date = try c.decode(String.self, forKey: .date)
        tokens = try c.decodeIfPresent(Int.self, forKey: .tokens) ?? 0
        costUsd = try c.decodeIfPresent(Double.self, forKey: .costUsd) ?? 0
        equivCostUsd = try c.decodeIfPresent(Double.self, forKey: .equivCostUsd) ?? 0
        events = try c.decodeIfPresent(Int.self, forKey: .events) ?? 0
    }
}

struct ConsumptionStats: Codable {
    let byModel: [StatsRow]
    let byStage: [StatsRow]
    let byConnection: [StatsRow]
    let byBank: [StatsRow]
    let hourHistogram: [Int]
    let peakDay: [String: LooseValue]?
    let longestSleepRun: [String: LooseValue]?
    let favoriteModel: String?
    let lifetimeTokens: Int
    let firstEvent: String?
    let series: [SeriesPoint]
    let range: String

    enum CodingKeys: String, CodingKey {
        case byModel, byStage, byConnection, byBank, hourHistogram, peakDay, longestSleepRun, favoriteModel, lifetimeTokens, firstEvent, series, range
    }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        byModel = try c.decodeIfPresent([StatsRow].self, forKey: .byModel) ?? []
        byStage = try c.decodeIfPresent([StatsRow].self, forKey: .byStage) ?? []
        byConnection = try c.decodeIfPresent([StatsRow].self, forKey: .byConnection) ?? []
        byBank = try c.decodeIfPresent([StatsRow].self, forKey: .byBank) ?? []
        hourHistogram = try c.decodeIfPresent([Int].self, forKey: .hourHistogram) ?? Array(repeating: 0, count: 24)
        peakDay = try c.decodeIfPresent([String: LooseValue].self, forKey: .peakDay)
        longestSleepRun = try c.decodeIfPresent([String: LooseValue].self, forKey: .longestSleepRun)
        favoriteModel = try c.decodeIfPresent(String.self, forKey: .favoriteModel)
        lifetimeTokens = try c.decodeIfPresent(Int.self, forKey: .lifetimeTokens) ?? 0
        firstEvent = try c.decodeIfPresent(String.self, forKey: .firstEvent)
        series = try c.decodeIfPresent([SeriesPoint].self, forKey: .series) ?? []
        range = try c.decodeIfPresent(String.self, forKey: .range) ?? "30d"
    }
}

/// String | number | null — for the small free-form dicts (peakDay, longestSleepRun, harness).
enum LooseValue: Codable, Hashable {
    case string(String), number(Double), null
    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let d = try? c.decode(Double.self) { self = .number(d) }
        else if let s = try? c.decode(String.self) { self = .string(s) }
        else { self = .null }
    }
    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self { case .string(let s): try c.encode(s); case .number(let d): try c.encode(d); case .null: try c.encodeNil() }
    }
    var text: String { switch self { case .string(let s): s; case .number(let d): d == d.rounded() ? "\(Int(d))" : "\(d)"; case .null: "—" } }
    var number: Double? { if case .number(let d) = self { d } else { nil } }
}

struct ConnectionConsumption: Codable, Identifiable {
    let id: String
    let label: String
    let billing: String
    let connected: Bool
    let priceUsdMonth: Double?
    let costUsd: Double?
    let equivCostUsd: Double?
    let invocations: Int
    let tokens: Int
    let throttleEvents: Int
    let byModel: [StatsRow]

    enum CodingKeys: String, CodingKey { case id, label, billing, connected, priceUsdMonth, costUsd, equivCostUsd, invocations, tokens, throttleEvents, byModel }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        label = try c.decodeIfPresent(String.self, forKey: .label) ?? id
        billing = try c.decodeIfPresent(String.self, forKey: .billing) ?? "usage"
        connected = try c.decodeIfPresent(Bool.self, forKey: .connected) ?? false
        priceUsdMonth = try c.decodeIfPresent(Double.self, forKey: .priceUsdMonth)
        costUsd = try c.decodeIfPresent(Double.self, forKey: .costUsd)
        equivCostUsd = try c.decodeIfPresent(Double.self, forKey: .equivCostUsd)
        invocations = try c.decodeIfPresent(Int.self, forKey: .invocations) ?? 0
        tokens = try c.decodeIfPresent(Int.self, forKey: .tokens) ?? 0
        throttleEvents = try c.decodeIfPresent(Int.self, forKey: .throttleEvents) ?? 0
        byModel = try c.decodeIfPresent([StatsRow].self, forKey: .byModel) ?? []
    }
}

struct ConsumptionConnections: Codable {
    let connections: [ConnectionConsumption]
    let range: String
}

struct HarnessStats: Codable {
    let claudeCode: [String: LooseValueTree]?
    let codex: [String: LooseValueTree]?
}

/// Recursive loose JSON for the harness panel (arrays of dicts, nested dicts).
indirect enum LooseValueTree: Codable {
    case value(LooseValue), array([LooseValueTree]), object([String: LooseValueTree])
    init(from decoder: Decoder) throws {
        if let o = try? [String: LooseValueTree](from: decoder) { self = .object(o) }
        else if let a = try? [LooseValueTree](from: decoder) { self = .array(a) }
        else { self = .value(try LooseValue(from: decoder)) }
    }
    func encode(to encoder: Encoder) throws {
        switch self {
        case .value(let v): try v.encode(to: encoder)
        case .array(let a): try a.encode(to: encoder)
        case .object(let o): try o.encode(to: encoder)
        }
    }
    subscript(_ key: String) -> LooseValueTree? { if case .object(let o) = self { o[key] } else { nil } }
    var array: [LooseValueTree] { if case .array(let a) = self { a } else { [] } }
    var value: LooseValue? { if case .value(let v) = self { v } else { nil } }
}
```

- [ ] **Step 3: API methods** (after the Connections section)

```swift
    // MARK: - Consumption (G51)

    func fetchConsumptionSummary(range: String) async throws -> ConsumptionSummary {
        try await get("/consumption/summary?range=\(range)")
    }

    func fetchConsumptionCalendar(weeks: Int = 53) async throws -> ConsumptionCalendar {
        try await get("/consumption/calendar?weeks=\(weeks)")
    }

    func fetchConsumptionStats(range: String) async throws -> ConsumptionStats {
        try await get("/consumption/stats?range=\(range)")
    }

    func fetchConsumptionConnections(range: String) async throws -> ConsumptionConnections {
        try await get("/consumption/connections?range=\(range)")
    }

    func fetchHarnessStats() async throws -> HarnessStats {
        try await get("/consumption/harness")
    }
```

- [ ] **Step 4: View model + theme ramp**

```swift
// app/CicadaApp/Sources/CicadaApp/ViewModels/UsageViewModel.swift
import Foundation
import Observation
import SwiftUI

enum UsageMode: String, CaseIterable { case minimal = "Minimal", advanced = "Advanced" }

@Observable
@MainActor
final class UsageViewModel {
    var mode: UsageMode {
        didSet { UserDefaults.standard.set(mode.rawValue, forKey: "cicada.usageMode") }
    }
    var range = "month"
    var summary = ConsumptionSummary()
    var calendar: [CalendarDay] = []
    var stats: ConsumptionStats?
    var connections: [ConnectionConsumption] = []
    var harness: HarnessStats?
    var selectedDay: CalendarDay?
    var isLoading = false
    var errorMessage: String?

    init() {
        mode = UsageMode(rawValue: UserDefaults.standard.string(forKey: "cicada.usageMode") ?? "") ?? .minimal
    }

    /// Flat monthly price of every connected subscription, or nil when none.
    var subscriptionUsdMonth: Double? {
        let prices = connections.filter { $0.billing == "subscription" && $0.connected }.compactMap(\.priceUsdMonth)
        return prices.isEmpty ? nil : prices.reduce(0, +)
    }

    var costLine: String {
        UsageFormat.costLine(costUsd: summary.costUsd, equivUsd: summary.equivCostUsd, subscriptionUsd: subscriptionUsdMonth)
    }

    func load() async {
        isLoading = calendar.isEmpty
        defer { isLoading = false }
        errorMessage = nil
        let api = APIClient.shared
        async let s = api.fetchConsumptionSummary(range: range)
        async let c = api.fetchConsumptionCalendar()
        async let k = api.fetchConsumptionConnections(range: range)
        do {
            summary = try await s
            calendar = try await c.days
            connections = try await k.connections
        } catch {
            errorMessage = error.localizedDescription
        }
        if mode == .advanced { await loadAdvanced() }
    }

    func loadAdvanced() async {
        let api = APIClient.shared
        async let st = api.fetchConsumptionStats(range: range)
        async let h = api.fetchHarnessStats()
        stats = try? await st
        harness = try? await h
    }
}
```

In `CicadaTheme.swift`, inside `enum CicadaTheme` (next to `statusColor(for:)`):

```swift
    /// Five-step sequential ramp for the usage heatmap (0 = empty cell).
    /// Derived from `accent` so it follows the light/dark palette automatically.
    static func heatRamp(level: Int) -> Color {
        switch max(0, min(4, level)) {
        case 0: surfaceElevated
        case 1: accent.opacity(0.30)
        case 2: accent.opacity(0.55)
        case 3: accent.opacity(0.80)
        default: accent
        }
    }
```

- [ ] **Step 5: Build and test**

Run: `cd app/CicadaApp && swift build && swift test`
Expected: build complete; 11 tests pass

- [ ] **Step 6: Commit**

```bash
git add app/CicadaApp/Sources/CicadaApp/Models/Consumption.swift app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift \
  app/CicadaApp/Sources/CicadaApp/ViewModels/UsageViewModel.swift app/CicadaApp/Sources/CicadaApp/Theme/CicadaTheme.swift \
  app/CicadaApp/Tests/CicadaAppTests/ConsumptionDecodingTests.swift
git commit -m "feat(app): consumption models, API methods, UsageViewModel, heat ramp"
```

---

### Task 9: Usage page — minimal view (tiles + heatmap) + navigation

**Files:**
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Usage/UsageView.swift`
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Usage/HeatmapView.swift`
- Modify: `SidebarView.swift` (`case usage = "Usage"`, icon `chart.bar.xaxis`, provenance section `[.contributors, .usage]`), `ContentView.swift` (`case .usage: UsageView()`)

- [ ] **Step 1: Heatmap**

```swift
// app/CicadaApp/Sources/CicadaApp/Views/Usage/HeatmapView.swift
import SwiftUI

/// GitHub-style 53×7 activity grid. Cells are `CalendarCell`s; the colour is
/// the backend's quantile `level` through `CicadaTheme.heatRamp`.
struct HeatmapView: View {
    let days: [CalendarDay]
    @Binding var selected: CalendarDay?
    private let cellSize: CGFloat = 11
    private let gap: CGFloat = 3

    private var columns: [[CalendarCell?]] { CalendarLayout.columns(days.map(\.cell)) }
    private var byDate: [String: CalendarDay] { Dictionary(uniqueKeysWithValues: days.map { ($0.date, $0) }) }

    var body: some View {
        let cols = columns
        VStack(alignment: .leading, spacing: gap) {
            monthRow(cols)
            HStack(alignment: .top, spacing: gap) {
                weekdayColumn
                ForEach(Array(cols.enumerated()), id: \.offset) { _, col in
                    VStack(spacing: gap) {
                        ForEach(0..<7, id: \.self) { row in
                            cell(col[row])
                        }
                    }
                }
            }
            legend
        }
        .padding(CicadaTheme.spacingMD)
        .glassCard()
    }

    private func cell(_ c: CalendarCell?) -> some View {
        RoundedRectangle(cornerRadius: 2)
            .fill(c.map { CicadaTheme.heatRamp(level: $0.level) } ?? Color.clear)
            .frame(width: cellSize, height: cellSize)
            .overlay {
                if let c, selected?.date == c.date {
                    RoundedRectangle(cornerRadius: 2).stroke(CicadaTheme.textPrimary, lineWidth: 1)
                }
            }
            .help(c.map(tooltip) ?? "")
            .onTapGesture { if let c { selected = selected?.date == c.date ? nil : byDate[c.date] } }
    }

    private func tooltip(_ c: CalendarCell) -> String {
        "\(c.date) · \(c.memoryWrites) memory write\(c.memoryWrites == 1 ? "" : "s") · \(c.events) event\(c.events == 1 ? "" : "s") · \(UsageFormat.tokens(c.tokens)) tokens"
    }

    private func monthRow(_ cols: [[CalendarCell?]]) -> some View {
        let labels = CalendarLayout.monthLabels(cols)
        return HStack(spacing: 0) {
            Spacer().frame(width: 28 + gap)
            ZStack(alignment: .leading) {
                ForEach(Array(labels.enumerated()), id: \.offset) { _, l in
                    Text(l.label).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                        .offset(x: CGFloat(l.column) * (cellSize + gap))
                }
            }
            .frame(height: 14, alignment: .leading)
        }
    }

    private var weekdayColumn: some View {
        VStack(spacing: gap) {
            ForEach(["Mon", "", "Wed", "", "Fri", "", ""], id: \.self) { d in
                Text(d).font(.system(size: 9)).foregroundStyle(CicadaTheme.textTertiary).frame(width: 28, height: cellSize, alignment: .leading)
            }
        }
    }

    private var legend: some View {
        HStack(spacing: gap) {
            Spacer()
            Text("Less").font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            ForEach(0..<5, id: \.self) { l in
                RoundedRectangle(cornerRadius: 2).fill(CicadaTheme.heatRamp(level: l)).frame(width: cellSize, height: cellSize)
            }
            Text("More").font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
        }
    }
}
```

- [ ] **Step 2: The page**

```swift
// app/CicadaApp/Sources/CicadaApp/Views/Usage/UsageView.swift
import SwiftUI

/// G51 — consumption & traceability. Minimal: four tiles + calendar.
/// Advanced: per-connection cost, charts, tables, /stats-style facts.
struct UsageView: View {
    @State private var viewModel = UsageViewModel()

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            PageHeader(title: "Usage", subtitle: "What Cicada consumed, on which connection, at what price.") {
                HStack(spacing: CicadaTheme.spacingSM) {
                    Picker("Range", selection: $viewModel.range) {
                        Text("This month").tag("month"); Text("30 days").tag("30d"); Text("90 days").tag("90d"); Text("All time").tag("all")
                    }
                    .pickerStyle(.menu).frame(width: 130)
                    Picker("Mode", selection: $viewModel.mode) {
                        ForEach(UsageMode.allCases, id: \.self) { Text($0.rawValue).tag($0) }
                    }
                    .pickerStyle(.segmented).frame(width: 180)
                }
            }

            if let err = viewModel.errorMessage {
                Text(err).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.statusColor(for: .decaying))
            }

            ScrollView {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                    tiles
                    HeatmapView(days: viewModel.calendar, selected: $viewModel.selectedDay)
                    if let day = viewModel.selectedDay { dayDetail(day) }
                    connectionsLine
                    if viewModel.mode == .advanced {
                        UsageAdvancedView(viewModel: viewModel)
                    }
                }
            }
        }
        .padding(CicadaTheme.spacingLG)
        .task { await viewModel.load() }
        .onChange(of: viewModel.range) { Task { await viewModel.load() } }
        .onChange(of: viewModel.mode) { if viewModel.mode == .advanced { Task { await viewModel.loadAdvanced() } } }
    }

    private var tiles: some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            StatTile(title: viewModel.range == "month" ? "This month" : "Cost", value: viewModel.subscriptionUsdMonth != nil && viewModel.summary.costUsd == 0
                     ? "Included" : UsageFormat.usd(viewModel.summary.costUsd), footnote: viewModel.costLine)
            StatTile(title: "Memory writes", value: "\(viewModel.summary.memoryWrites)", footnote: "\(viewModel.summary.agenticWrites) in-session · \(viewModel.summary.sleepRuns) sleep runs")
            StatTile(title: "Tokens", value: UsageFormat.tokens(viewModel.summary.tokens), footnote: "\(viewModel.summary.invocations) invocations")
            StatTile(title: "Streak", value: "\(viewModel.summary.streakCurrent)d", footnote: "best \(viewModel.summary.streakBest)d")
        }
    }

    private func dayDetail(_ d: CalendarDay) -> some View {
        HStack(spacing: CicadaTheme.spacingLG) {
            Text(d.date).font(CicadaTheme.headingFont).foregroundStyle(CicadaTheme.textPrimary)
            Label("\(d.memoryWrites) memory writes", systemImage: "square.and.pencil")
            Label("\(d.events) events", systemImage: "bolt")
            Label("\(UsageFormat.tokens(d.tokens)) tokens", systemImage: "number")
            Label(d.costUsd > 0 ? "\(UsageFormat.usd(d.costUsd)) spent" : "≈ \(UsageFormat.usd(d.equivCostUsd)) API-equivalent", systemImage: "dollarsign.circle")
            Spacer()
        }
        .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
        .padding(CicadaTheme.spacingMD).glassCard()
    }

    private var connectionsLine: some View {
        let parts = viewModel.connections.filter(\.connected).map { c -> String in
            switch c.billing {
            case "subscription": c.priceUsdMonth.map { "\(c.label) · $\(Int($0))/mo" } ?? c.label
            case "free": "\(c.label) · free"
            default: "\(c.label) · \(UsageFormat.usd(c.costUsd ?? 0)) \(viewModel.range == "month" ? "this month" : "in range")"
            }
        }
        return Text(parts.isEmpty ? "No connections yet — set one up under Setup › Connections." : "Connections: " + parts.joined(separator: " · "))
            .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
    }
}

struct StatTile: View {
    let title: String
    let value: String
    var footnote: String? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Text(title).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
            Text(value).font(CicadaTheme.titleFont).foregroundStyle(CicadaTheme.textPrimary)
            if let footnote { Text(footnote).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary).lineLimit(2) }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(CicadaTheme.spacingMD)
        .glassCard()
    }
}
```

Add a placeholder so the build passes before Task 10: create `Views/Usage/UsageAdvancedView.swift` with `struct UsageAdvancedView: View { let viewModel: UsageViewModel; var body: some View { EmptyView() } }` — Task 10 replaces it.

- [ ] **Step 3: Navigation + build + smoke-run**

Add the `usage` tab (SidebarView: case, icon `chart.bar.xaxis`, provenance `[.contributors, .usage]`; ContentView: `case .usage: UsageView()`).

Run: `cd app/CicadaApp && swift build && swift test && ./bundle.sh --run`
Expected: build + tests green; the **Usage** page shows four tiles, the 53-week heatmap with month labels, a tooltip on hover, day detail on click, and the connections line.

- [ ] **Step 4: Commit**

```bash
git add app/CicadaApp/Sources/CicadaApp/Views/Usage app/CicadaApp/Sources/CicadaApp/Views/Sidebar/SidebarView.swift app/CicadaApp/Sources/CicadaApp/ContentView.swift
git commit -m "feat(app): Usage page — stat tiles + GitHub-style activity calendar (minimal view)"
```

---

### Task 10: Advanced view — connection cost cards, charts, tables, /stats facts, harness panel

**Files:**
- Replace: `app/CicadaApp/Sources/CicadaApp/Views/Usage/UsageAdvancedView.swift`

- [ ] **Step 1: Implement**

```swift
// app/CicadaApp/Sources/CicadaApp/Views/Usage/UsageAdvancedView.swift
import Charts
import SwiftUI

struct UsageAdvancedView: View {
    let viewModel: UsageViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            connectionCards
            if let stats = viewModel.stats {
                charts(stats)
                facts(stats)
                table("By model", rows: stats.byModel)
                table("By stage", rows: stats.byStage)
                table("By bank", rows: stats.byBank)
            } else {
                ProgressView().frame(maxWidth: .infinity)
            }
            harnessPanel
        }
    }

    // MARK: connections

    private var connectionCards: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            sectionTitle("Connections")
            ForEach(viewModel.connections.filter { $0.connected || $0.tokens > 0 }) { c in
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                    HStack {
                        Text(c.label).font(CicadaTheme.headingFont).foregroundStyle(CicadaTheme.textPrimary)
                        Spacer()
                        Text(priceText(c)).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textPrimary)
                    }
                    Text(detailText(c)).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                    if c.throttleEvents > 0 {
                        Text("Throttled \(c.throttleEvents)× in range — Cicada stopped and resumed the next night.")
                            .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.statusColor(for: .decaying))
                    }
                    if !c.byModel.isEmpty {
                        ForEach(c.byModel) { m in
                            HStack {
                                Text(m.name).font(CicadaTheme.monoFont)
                                Spacer()
                                Text("\(UsageFormat.tokens(m.tokens)) tok")
                                Text(c.billing == "usage" ? UsageFormat.usd(m.costUsd) : "≈ \(UsageFormat.usd(m.equivCostUsd))").frame(width: 90, alignment: .trailing)
                            }
                            .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                        }
                    }
                }
                .padding(CicadaTheme.spacingMD).glassCard()
            }
        }
    }

    private func priceText(_ c: ConnectionConsumption) -> String {
        switch c.billing {
        case "subscription": c.priceUsdMonth.map { "$\(Int($0))/mo" } ?? "plan"
        case "free": "free"
        default: UsageFormat.usd(c.costUsd ?? 0) + " spent"
        }
    }

    private func detailText(_ c: ConnectionConsumption) -> String {
        switch c.billing {
        case "subscription": "\(c.invocations) invocations · \(UsageFormat.tokens(c.tokens)) tokens · ≈ \(UsageFormat.usd(c.equivCostUsd)) at API list price (estimate — not billed)"
        case "free": "\(c.invocations) invocations · \(UsageFormat.tokens(c.tokens)) tokens · on-device"
        default: "\(c.invocations) invocations · \(UsageFormat.tokens(c.tokens)) tokens · real cost from provider list prices"
        }
    }

    // MARK: charts

    private func charts(_ s: ConsumptionStats) -> some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
            chartCard("Tokens per day") {
                Chart(s.series) { p in
                    BarMark(x: .value("Day", p.date), y: .value("Tokens", p.tokens)).foregroundStyle(CicadaTheme.accent)
                }
                .chartXAxis { AxisMarks(values: .automatic(desiredCount: 6)) { _ in AxisValueLabel(format: .dateTime.month().day()) } }
            }
            chartCard("Cost per day") {
                Chart(s.series) { p in
                    BarMark(x: .value("Day", p.date), y: .value("Spent", p.costUsd)).foregroundStyle(CicadaTheme.accent)
                    LineMark(x: .value("Day", p.date), y: .value("API-equivalent", p.equivCostUsd)).foregroundStyle(CicadaTheme.textTertiary)
                }
            }
            chartCard("Hour of day") {
                Chart(Array(s.hourHistogram.enumerated()), id: \.offset) { h in
                    BarMark(x: .value("Hour", h.offset), y: .value("Events", h.element)).foregroundStyle(CicadaTheme.accent.opacity(0.7))
                }
            }
        }
        .frame(height: 180)
    }

    private func chartCard<C: View>(_ title: String, @ViewBuilder content: () -> C) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Text(title).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
            content()
        }
        .frame(maxWidth: .infinity).padding(CicadaTheme.spacingMD).glassCard()
    }

    // MARK: /stats-style facts

    private func facts(_ s: ConsumptionStats) -> some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            StatTile(title: "Lifetime tokens", value: UsageFormat.tokens(s.lifetimeTokens), footnote: s.firstEvent.map { "since \($0)" })
            StatTile(title: "Favorite model", value: s.favoriteModel ?? "—", footnote: "most tokens in range")
            StatTile(title: "Peak day", value: s.peakDay?["date"]?.text ?? "—", footnote: s.peakDay?["tokens"]?.number.map { "\(UsageFormat.tokens(Int($0))) tokens" })
            StatTile(title: "Longest sleep run",
                     value: s.longestSleepRun?["durationMs"]?.number.map { "\(Int($0 / 60000))m" } ?? "—",
                     footnote: s.longestSleepRun?["episodesProcessed"]?.number.map { "\(Int($0)) episodes" })
        }
    }

    // MARK: tables

    private func table(_ title: String, rows: [StatsRow]) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            sectionTitle(title)
            Grid(alignment: .leading, horizontalSpacing: CicadaTheme.spacingMD, verticalSpacing: 4) {
                GridRow {
                    Text("Name"); Text("Calls"); Text("In"); Text("Out"); Text("Cache"); Text("Spent"); Text("≈ API")
                }
                .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                ForEach(rows) { r in
                    GridRow {
                        Text(r.name).font(CicadaTheme.monoFont)
                        Text("\(r.invocations)")
                        Text(UsageFormat.tokens(r.inputTokens))
                        Text(UsageFormat.tokens(r.outputTokens))
                        Text(UsageFormat.tokens(r.cacheReadTokens + r.cacheWriteTokens))
                        Text(UsageFormat.usd(r.costUsd))
                        Text(UsageFormat.usd(r.equivCostUsd))
                    }
                    .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                }
            }
            .padding(CicadaTheme.spacingMD).glassCard()
        }
    }

    // MARK: harness (Claude Code's own stats + Codex rate-limit snapshot)

    @ViewBuilder
    private var harnessPanel: some View {
        if let h = viewModel.harness, h.claudeCode != nil || h.codex != nil {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                sectionTitle("Your agent harnesses (their own data, not Cicada's)")
                if let cc = h.claudeCode {
                    HStack(spacing: CicadaTheme.spacingMD) {
                        StatTile(title: "Claude Code sessions", value: cc["totalSessions"]?.value?.text ?? "—", footnote: "from ~/.claude/stats-cache.json")
                        StatTile(title: "Claude Code messages", value: cc["totalMessages"]?.value?.text ?? "—", footnote: cc["firstSessionDate"]?.value.map { "since \($0.text)" })
                    }
                }
                if let cx = h.codex {
                    let primary = cx["primary"]?["usedPercent"]?.value?.number
                    let secondary = cx["secondary"]?["usedPercent"]?.value?.number
                    HStack(spacing: CicadaTheme.spacingMD) {
                        StatTile(title: "Codex 5-hour window", value: primary.map { "\(Int($0))%" } ?? "—", footnote: "last snapshot in ~/.codex/sessions")
                        StatTile(title: "Codex weekly window", value: secondary.map { "\(Int($0))%" } ?? "—", footnote: cx["planType"]?.value.map { "plan: \($0.text)" })
                    }
                }
                Text("No rate-limit figures are shown for Claude: there is no compliant local source. Cicada reports the throttle events it observed instead.")
                    .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            }
        }
    }

    private func sectionTitle(_ t: String) -> some View {
        Text(t).font(CicadaTheme.headingFont).foregroundStyle(CicadaTheme.textPrimary)
    }
}
```

The backend's `peak_day`/`longest_sleep_run` dict keys arrive camelCased by `CamelModel` only for declared fields; the loose dicts keep the Python keys (`duration_ms`, `episodes_processed`). Change the two lookups to `s.longestSleepRun?["duration_ms"]` and `["episodes_processed"]`, and the harness lookups to `cc["total_sessions"]`, `cc["total_messages"]`, `cc["first_session_date"]`, `cx["primary"]?["used_percent"]`, `cx["plan_type"]` — the `harness_stats` dicts are snake_case as written in Task 6.

- [ ] **Step 2: Build + run**

Run: `cd app/CicadaApp && swift build && swift test && ./bundle.sh --run`
Expected: toggle **Advanced**: connection cards (plan price vs spent vs API-equivalent), three charts, four facts tiles, three tables, and the harness panel when `~/.claude/stats-cache.json` or Codex sessions exist.

- [ ] **Step 3: Commit**

```bash
git add app/CicadaApp/Sources/CicadaApp/Views/Usage/UsageAdvancedView.swift
git commit -m "feat(app): Usage advanced view — connection cost cards, charts, tables, /stats facts, harness panel"
```

---

### Task 11: Docs

**Files:**
- Modify: `CLAUDE.md` (API list: `/consumption/*`; note on the ledger location and `CICADA_TELEMETRY`)
- Modify: `docs/goals/memory-evolution.md` (G51 status; note G49 P4 seam completion landed here)

- [ ] **Step 1: CLAUDE.md** — add:

```
GET  /consumption/summary|calendar|stats|connections|harness → consumption/traceability dashboard (G51);
     ledger at ~/.cicada/telemetry/events-YYYY-MM.jsonl (CICADA_TELEMETRY=off disables)
```

and under Storage Layer a one-liner: *"Telemetry ledger: append-only JSONL under `~/.cicada/telemetry/`, machine-global, never in a bank or git; fed by `providers.resolve_llm_fn` (every LLM call is now routed through it), Sleep `_finalize`, and MCP `cicada_write_claim`."*

- [ ] **Step 2: Full verification**

Run: `api/.venv/bin/python -m pytest api/tests -q && (cd app/CicadaApp && swift build && swift test)`
Expected: all green.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md docs/goals/memory-evolution.md
git commit -m "docs: consumption endpoints + telemetry ledger; G51 status"
```

---

## Self-review

- **Spec coverage:** §6.1 ledger → Task 1; §6.2 capture points 1–4 → Tasks 2–4 (point 5, engines, lands with G49 P1 and calls the same `record`); §6.3 aggregation + API → Tasks 5–6; §6.4 pricing → Task 2 (`estimate_cost`) + connections plan Task 3 (subscription table); §6.5 page (minimal/advanced, heatmap, tiles, charts, tables, facts, harness panel, theme ramp) → Tasks 7–10; §6.6 honesty copy → `UsageFormat.costLine`, connection card copy, harness note; §7 error handling → `record` never raises, tolerant readers, tolerant Swift decoding; §8 tests → Python per task, Swift test target (Task 7) with formatting/layout/decoding tests.
- **Placeholders:** none — the Task 9 stub for `UsageAdvancedView` is explicit scaffolding replaced in Task 10.
- **Type consistency:** `UsageEvent` field names match the JSON keys read by `consumption_stats`; router models mirror the dict keys (`price_usd_month`, `throttle_events`, `by_model`); the `by_*`/`series` rows and per-connection `by_model` rows are `list[dict]` and are camelCased explicitly by `_camel_rows` in the router (Task 6) so Swift's `StatsRow`/`SeriesPoint` decode; `peak_day`/`longest_sleep_run` and the harness dicts stay snake_case, and Task 10 reads them with snake_case keys.

## Execution handoff

Plan complete. Options: **Subagent-Driven** (`superpowers:subagent-driven-development`, recommended) or **Inline** (`superpowers:executing-plans`). Order: Tasks 1→2→3→4 sequential; Task 5 after 4; Task 6 after 5 and after connections-plan Task 8; Tasks 7–10 after 6; Task 11 last.
