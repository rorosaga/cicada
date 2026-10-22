"""Price rows Cicada adds to LiteLLM's bundled table, each with its basis (G50/G215; ruling 12: a price shows only
with its basis).

``api.pin_litellm`` keeps LiteLLM's price table the one the installed package ships, and that table (1.83.4) is
behind the vendors' current lineups (providers-2, 2026-10-22). A default the table does not list would read "cost
unknown" (``test_byok_providers``), so a default that has to move before the next LiteLLM bump gets one row here,
copied from the vendor's own price page. A row is added only when the table has none: a newer LiteLLM that prices the
model wins. Remove a row once the pinned LiteLLM lists its model.
"""
from __future__ import annotations

#: model id → (LiteLLM row, basis). Prices are USD per token.
ROWS: dict[str, tuple[dict, str]] = {
    "xai/grok-4.20-0309-non-reasoning": (
        {"litellm_provider": "xai", "mode": "chat", "input_cost_per_token": 1.25e-06,
         "cache_read_input_token_cost": 2.0e-07, "output_cost_per_token": 2.5e-06, "max_input_tokens": 1_000_000,
         "max_tokens": 1_000_000, "supports_response_schema": True, "supports_function_calling": True},
        "docs.x.ai/docs/models, read 2026-10-22: $1.25 in / $0.20 cached / $2.50 out per 1M under 200k prompt "
        "tokens; structured outputs for the Grok 4 family (docs.x.ai structured-outputs guide)"),
}

_applied = False


def apply(litellm_module=None) -> None:
    """Add every row LiteLLM's table lacks. Idempotent; never raises."""
    global _applied
    if _applied:
        return
    try:
        if litellm_module is None:
            import litellm as litellm_module
        missing = {model: row for model, (row, _basis) in ROWS.items() if model not in litellm_module.model_cost}
        if missing:
            litellm_module.register_model(missing)
        _applied = True
    except Exception:  # noqa: BLE001 — a missing row is "cost unknown", never a failed start
        pass
