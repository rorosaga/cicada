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
