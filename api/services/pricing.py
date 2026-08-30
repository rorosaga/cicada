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
