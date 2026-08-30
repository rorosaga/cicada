"""Subscription prices (USD/month) for the connections + usage surfaces.

Hand-verified against the vendors' pricing pages on ``PRICES_VERIFIED``; the
date is surfaced in the UI so a stale table is visible, not silent. Usage-based
(per-token) pricing lives in litellm and is added by the consumption plan.
"""
from __future__ import annotations

PRICES_VERIFIED = "2026-08-28"

SUBSCRIPTION_PRICES: dict[str, dict[str, float]] = {
    "claude-plan": {"pro": 20.0, "max-5x": 100.0, "max-20x": 200.0},
    "chatgpt-plan": {"free": 0.0, "go": 8.0, "plus": 20.0, "pro-5x": 100.0, "pro-20x": 200.0},
    "gemini-plan": {"pro": 19.99, "ultra-5x": 99.99, "ultra-20x": 199.99},
    "copilot-plan": {"pro": 10.0, "pro-plus": 39.0, "max": 100.0},
}

# (connection, plan) -> tiers the user must choose between.
TIERED: dict[tuple[str, str], tuple[str, ...]] = {
    ("claude-plan", "max"): ("5x", "20x"),
    ("chatgpt-plan", "pro"): ("5x", "20x"),
    ("gemini-plan", "ultra"): ("5x", "20x"),
}

_BRAND = {"claude-plan": "Claude", "chatgpt-plan": "ChatGPT", "gemini-plan": "Google AI", "copilot-plan": "Copilot"}


def price_for(connection_id: str, plan: str | None, tier: str | None = None) -> tuple[float | None, str]:
    if not plan:
        return None, "not connected"
    table = SUBSCRIPTION_PRICES.get(connection_id, {})
    plan = plan.lower()
    tiers = TIERED.get((connection_id, plan))
    if tiers:
        if tier in tiers:
            return table[f"{plan}-{tier}"], f"verified {PRICES_VERIFIED}"
        options = " or ".join(f"${table[f'{plan}-{t}']:.0f} ({t})" for t in tiers)
        return None, f"{plan.capitalize()} is {options} — pick your tier"
    if plan in table:
        return table[plan], f"verified {PRICES_VERIFIED}"
    return None, f"price unknown for '{plan}'"


def plan_label(connection_id: str, plan: str | None, tier: str | None) -> str | None:
    if not plan:
        return None
    brand = _BRAND.get(connection_id, connection_id)
    label = f"{brand} {plan.replace('-', ' ').title()}"
    if tier and TIERED.get((connection_id, plan.lower())):
        label += f" {tier}"
    return label


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
