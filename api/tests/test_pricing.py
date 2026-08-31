from api.services import pricing


def test_flat_plan_price():
    usd, note = pricing.price_for("claude-plan", "pro")
    assert usd == 20.0
    assert "2026-08-28" in note


def test_tiered_plan_needs_tier():
    usd, note = pricing.price_for("claude-plan", "max")
    assert usd is None
    assert "5x" in note and "20x" in note


def test_tiered_plan_with_tier():
    assert pricing.price_for("claude-plan", "max", "20x")[0] == 200.0
    assert pricing.price_for("chatgpt-plan", "pro", "5x")[0] == 100.0


def test_unknown_plan():
    usd, note = pricing.price_for("chatgpt-plan", "enterprise")
    assert usd is None and "enterprise" in note


def test_none_plan():
    assert pricing.price_for("claude-plan", None) == (None, "not connected")


def test_labels():
    assert pricing.plan_label("claude-plan", "max", "20x") == "Claude Max 20x"
    assert pricing.plan_label("claude-plan", "max", None) == "Claude Max"
    assert pricing.plan_label("chatgpt-plan", "plus", None) == "ChatGPT Plus"
    assert pricing.plan_label("chatgpt-plan", None, None) is None


def test_chatgpt_free_is_zero():
    assert pricing.price_for("chatgpt-plan", "free") == (0.0, f"verified {pricing.PRICES_VERIFIED}")
    assert pricing.plan_label("chatgpt-plan", "free", None) == "ChatGPT Free"


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


def test_estimate_cost_legacy_fallback_does_not_double_price_cache_tokens():
    """D5: `input_tokens` is already GROSS (the cache buckets are a breakdown
    OF it, not extra tokens beside it — see `telemetry.usage_from_response`).
    The TypeError-compat path (older litellm with no cache kwargs) must pass
    `input_tokens` straight through, not add the cache buckets back on top."""
    calls = []

    def legacy_cost_fn(**kw):
        if "cache_read_input_tokens" in kw or "cache_creation_input_tokens" in kw:
            raise TypeError("cost_per_token() got an unexpected keyword argument")
        calls.append(kw["prompt_tokens"])
        return (0.001, 0.0005)

    usd = pricing.estimate_cost(
        "gpt-5.4-mini", 1000, 100,
        cache_read_tokens=300, cache_write_tokens=200,
        cost_fn=legacy_cost_fn,
    )
    assert usd == 0.0015
    assert calls == [1000], (
        f"the fallback must price the gross input_tokens (1000), not "
        f"input_tokens + cache buckets (1500): got {calls}"
    )
