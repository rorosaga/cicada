"""Price rows Cicada adds to LiteLLM's bundled table, each with its basis (G50/G215; ruling 12: a price shows only
with its basis).

``api.pin_litellm`` keeps LiteLLM's price table the one the installed package ships, and that table (1.83.4) is
behind the vendors' current lineups (providers-2, 2026-10-22). A default the table does not list would read "cost
unknown" (``test_byok_providers``), so a default that has to move before the next LiteLLM bump gets one row here,
copied from the vendor's own price page. A row is added only when the table has none: a newer LiteLLM that prices the
model wins. Remove a row once the pinned LiteLLM lists its model. Claude's rows (G237) stay here whatever LiteLLM lists:
a Claude key's calls do not pass through LiteLLM, and only this table knows the 1-hour write and long-prompt rates. A
model newer than this table reads "cost unknown" until a Cicada release adds it, with its tokens still shown: the
vendor's API gives no price to read, and a guessed one would be worse (ruling 12).
"""
from __future__ import annotations

import re

#: model id → (LiteLLM row, basis). Prices are USD per token.
ROWS: dict[str, tuple[dict, str]] = {
    "xai/grok-4.20-0309-non-reasoning": (
        {"litellm_provider": "xai", "mode": "chat", "input_cost_per_token": 1.25e-06,
         "cache_read_input_token_cost": 2.0e-07, "output_cost_per_token": 2.5e-06, "max_input_tokens": 1_000_000,
         "max_tokens": 1_000_000, "supports_response_schema": True, "supports_function_calling": True},
        "docs.x.ai/docs/models, read 2026-10-22: $1.25 in / $0.20 cached / $2.50 out per 1M under 200k prompt "
        "tokens; structured outputs for the Grok 4 family (docs.x.ai structured-outputs guide)"),
}

#: G237: Claude's list prices, USD per million tokens: (input, 5-minute write, 1-hour write, cache read, output). The
#: Models API gives no price, and LiteLLM's table lags the lineup. Basis: the vendor's own pricing page.
CLAUDE_PRICES_READ = "2026-11-04"
CLAUDE_BASIS = f"platform.claude.com/docs/en/about-claude/pricing, read {CLAUDE_PRICES_READ}"
CLAUDE_PRICES: dict[str, tuple[float, float, float, float, float]] = {
    "claude-fable-5-1": (10, 12.5, 20, 0.25, 50),
    "claude-fable-5": (10, 12.5, 20, 1, 50),
    "claude-opus-5-5": (4, 5, 8, 0.2, 20),
    "claude-opus-5": (5, 6.25, 10, 0.5, 25),
    "claude-opus-4-8": (5, 6.25, 10, 0.5, 25),
    "claude-opus-4-7": (5, 6.25, 10, 0.5, 25),
    "claude-opus-4-6": (5, 6.25, 10, 0.5, 25),
    "claude-opus-4-5": (5, 6.25, 10, 0.5, 25),
    "claude-sonnet-5-5": (2, 2.5, 4, 0.1, 10),
    "claude-sonnet-5": (2, 2.5, 4, 0.2, 10),
    "claude-sonnet-4-6": (3, 3.75, 6, 0.3, 15),
    "claude-sonnet-4-5": (3, 3.75, 6, 0.3, 15),
    "claude-haiku-5-5": (0.1, 0.125, 0.2, 0.01, 0.5),
    "claude-haiku-4-5": (1, 1.25, 2, 0.1, 5),
}
#: The same page: a Haiku 5.5 request whose whole prompt (cache reads and writes included) is over 100,000 tokens pays
#: these rates on all of it.
CLAUDE_LONG_PROMPT: dict[str, tuple[int, tuple[float, float, float, float, float]]] = {
    "claude-haiku-5-5": (100_000, (0.5, 0.625, 1, 0.05, 2.5)),
}
#: The same page: $10 per 1,000 searches.
CLAUDE_SEARCH_USD = 0.01
_DATED = re.compile(r"-\d{8}$")


def claude_row_id(model: str | None) -> str:
    """A model id as the price table names it: no provider prefix, no release date."""
    bare = (model or "").strip().split("/")[-1]
    return _DATED.sub("", bare)


def claude_cost(model: str | None, *, input_tokens: int, output_tokens: int, cache_read: int = 0, cache_write: int = 0,
                cache_write_1h: int = 0, searches: int = 0) -> float | None:
    """One Claude call at list price. ``input_tokens`` is the API's own (the uncached rest), ``cache_write_1h`` the part
    of ``cache_write`` written for an hour. ``None`` for a model with no row: unknown, never zero."""
    row_id = claude_row_id(model)
    rates = CLAUDE_PRICES.get(row_id)
    if rates is None:
        return None
    long_prompt = CLAUDE_LONG_PROMPT.get(row_id)
    if long_prompt and input_tokens + cache_read + cache_write > long_prompt[0]:
        rates = long_prompt[1]
    cost = (input_tokens * rates[0] + (cache_write - cache_write_1h) * rates[1] + cache_write_1h * rates[2]
            + cache_read * rates[3] + output_tokens * rates[4]) / 1e6
    return round(cost + searches * CLAUDE_SEARCH_USD, 6)


def price_basis(model: str | None) -> str | None:
    """Where a shown price comes from (ruling 12), for a model priced here; ``None`` for one read from LiteLLM's table."""
    if claude_row_id(model) in CLAUDE_PRICES and "claude" in (model or ""):
        return CLAUDE_BASIS
    row = ROWS.get((model or "").strip())
    return row[1] if row else None


def _claude_row(rates: tuple[float, float, float, float, float]) -> dict:
    """A Claude price as a LiteLLM row, so every price reader finds it. Search: the model takes the provider's own."""
    return {"litellm_provider": "anthropic", "mode": "chat", "input_cost_per_token": rates[0] / 1e6,
            "cache_creation_input_token_cost": rates[1] / 1e6, "cache_read_input_token_cost": rates[3] / 1e6,
            "output_cost_per_token": rates[4] / 1e6, "supports_response_schema": True, "supports_function_calling": True,
            "supports_prompt_caching": True, "supports_web_search": True}


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
        missing.update({model: _claude_row(rates) for model, rates in CLAUDE_PRICES.items()
                        if model not in litellm_module.model_cost})
        if missing:
            litellm_module.register_model(missing)
        _applied = True
    except Exception:  # noqa: BLE001 — a missing row is "cost unknown", never a failed start
        pass
