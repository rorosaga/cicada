"""The spending limit: a run on a key stops at the figure the person set (ROR-102; ruling 63 (g)).

The owner, 2026-11-04: "from cicada you can put a limit on spending." It amends ruling 4's "no limit Cicada sets".

* **A soft stop, the reserve's own path** (``sleep_reserve``): Stage 1 stops starting new reads, what was already read
  is filed, the rest wait. So a run ends a little past the line, by the reads in flight and the filing of what they
  read, and it is a pause, never a failure: ``DrainStop("reserve", …, limit="spend")``.
* **Per run, and a Continue is a new allowance.** The figure is snapshotted when a run or a Continue starts; the
  person's click is what spends it again. A scheduled run that reaches it waits for that click.
* **The figure is the ledger's** (``providers._emit``): what each call cost, a failed one included, at the provider's
  list price.
* **A model with no known price stops the run: never tokens counted, never a guess.** A limit in dollars cannot hold on
  a price nobody knows, and a run that spends past it silently is the one thing this exists to prevent. Told before the
  first read when the model is known up front, else at the first call that reports no price.
* **Metered engines only.** A plan's limits are the plan's, and a local model costs nothing.
"""
from __future__ import annotations

import threading

#: What a machine that never chose reads. Hand-edited nonsense reads as this too: never a reason to spend more.
DEFAULT_USD = 5.0
CHOICES = (1, 5, 10, 20, 50)
MAX_USD = 100_000.0
LIMIT = "spend"
#: Each fits the Sleep page's sentence (``SentenceLine.maxTail``) and names no figure (ruling 12).
SENTENCE = "Spending limit reached; what was read is kept. Continue spends up to it again."
NO_PRICE_SENTENCE = "No price known for this model, so the limit can't hold. Change either to go on."


class SpendGuard:
    """What a run has cost against the person's figure, safe across the provider seam's threads."""

    def __init__(self, limit_usd: float):
        self.limit_usd = float(limit_usd)
        self.spent_usd = 0.0
        self.no_price = False
        self._lock = threading.Lock()

    def observe(self, cost_usd: float | None) -> None:
        with self._lock:
            if cost_usd is None:
                self.no_price = True
            else:
                self.spent_usd += float(cost_usd)

    def observe_snapshot(self, snap) -> None:
        """A plan window's snapshot: nothing to a key (``ReserveGuard``'s other half)."""

    def is_reached(self) -> bool:
        with self._lock:
            return self.no_price or self.spent_usd >= self.limit_usd

    def stop_values(self) -> tuple[int | None, str]:
        return None, LIMIT

    @property
    def sentence(self) -> str:
        return NO_PRICE_SENTENCE if self.no_price else SENTENCE


def valid(value) -> bool:
    """A figure the limit can be: a positive, finite number up to ``MAX_USD``."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return 0 < float(value) <= MAX_USD


def _priced(model: str) -> bool:
    from api.services import anthropic_models, direct_engines, price_supplement, pricing

    if direct_engines.for_model(model) is not None:
        return price_supplement.claude_cost(anthropic_models.resolve(model).model, input_tokens=1, output_tokens=1) is not None
    return pricing.estimate_cost(model, 1, 1) is not None


def guard_for(resolved, limit_usd: float | None) -> SpendGuard | None:
    """The guard for a run on ``resolved``, or ``None`` when no limit applies: none set, or an engine that is not charged
    per use. A model whose price cannot be read at all waits for the first call to say so."""
    from api.services import telemetry

    main = str(getattr(resolved, "litellm_model", "") or "")
    if not limit_usd or not main or telemetry.connection_for_model(main)[1] != "usage":
        return None
    guard = SpendGuard(limit_usd)
    models = {main, str(getattr(resolved, "effective_consolidation_model", "") or ""),
              str(getattr(resolved, "litellm_disambiguation_model", "") or "")}
    try:
        if not all(_priced(m) for m in models if m):
            guard.observe(None)
    except Exception:  # noqa: BLE001 — a table that cannot be read leaves it to the first call's own report
        pass
    return guard
