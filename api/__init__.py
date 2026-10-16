"""Cicada's backend package.

**litellm's price table is the one it ships with.** `import litellm` builds `litellm.model_cost` — every model's
per-token price and capabilities (`supports_response_schema`) — and, unless told otherwise, builds it by fetching the
newest table from GitHub at import time (5 s timeout), falling back to the copy bundled with the installed version.
That made every price Cicada shows, every list-price estimate and the test that pins the key providers' default models
depend on the network and on whatever upstream had merged that day: an id present one week (an OpenRouter `-latest`
alias) was gone the next, and the fetch was an outbound request no gate covered. `LITELLM_LOCAL_MODEL_COST_MAP=True`
is forced here, before any submodule can import litellm — the backend, the CLI, the MCP server and the test suite all
import this package first — so the table is the installed litellm's own, a version bump is the only thing that
changes it, and a model it does not list is priced unknown (never zero).
"""
from __future__ import annotations

import os
from collections.abc import MutableMapping

#: litellm switches Cicada sets itself; no settings file or inherited value may change them.
LITELLM_PINNED: dict[str, str] = {"LITELLM_LOCAL_MODEL_COST_MAP": "True"}


def pin_litellm(environ: MutableMapping[str, str] | None = None) -> None:
    """Force ``LITELLM_PINNED`` into ``environ`` (the process environment by default). Idempotent."""
    env = os.environ if environ is None else environ
    env.update(LITELLM_PINNED)


pin_litellm()
