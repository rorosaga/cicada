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


def test_sync_call_records_event(monkeypatch):
    # Hermetic: don't depend on whatever price table this litellm install
    # happens to ship for the model id — force the list-price lookup to miss
    # so equiv_cost_usd falls back to the real billed cost (cost_usd), per
    # the fallback in providers._emit.
    import litellm

    def _unknown(**kw):
        raise ValueError("no pricing data")

    monkeypatch.setattr(litellm, "cost_per_token", _unknown)

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
