"""Reading options — the choices a Sleep run reads (Sleep page v5; ruling 4b).

Stored beside the engine choice in ``~/.cicada/connections.json`` (machine-global,
bank-independent, the store ``sleep-engine`` lives in), under the pseudo-connection
id ``sleep-run``:

* ``batch_size`` — how often progress is saved (10, 25 or 50). Unset means the
  ``sleep_max_episodes_per_cycle`` setting. 50 is the ceiling on purpose: a commit
  records at most ``MAX_SESSION_TRAILERS`` (50) conversations.
* ``continue_after_reset`` — TODO ruling 15. Off by default. A run the person
  started may continue itself once, after its own plan window resets, if this was
  on when they started it. See ``sleep_autocontinue`` for the bounds.
* ``reserve_pct`` — "Leave room in my plan" (5, 10, 20 or 30 percent of a plan
  window). Off (unset) by default; set in the engine menu; only meaningful for a
  plan engine. See ``sleep_reserve`` for what enforcing it means and does not.
* ``spend_limit_usd`` — ROR-102: a run on a key stops here (``sleep_spend``). Unset reads as the suggested figure, on;
  stored ``0`` is the person's off.
* ``scheduled_use_plan`` — TODO ruling 4b (owner, 2026-10-16), amended 2026-10-19 ("Make scheduled
  runs run on the plan by default"): ON unless the person turned it off. Lets a SCHEDULED run use the
  person's plan, Claude or ChatGPT (``engine_select.SCHEDULE_PLAN_MODES``): nightly runs count against
  the plan's limits, said where it can be turned off. Stored only as an explicit ``false`` (off); a
  machine that never set it — a new install, a bank that never chose — reads as on.

* ``keep_awake`` — G243: off by default. While a run reads, the Mac does not sleep on power (``keep_awake``).

A run snapshots all three when it starts, so a change applies to the next start or
Continue and never to a run in flight.
"""
from __future__ import annotations

from dataclasses import dataclass

from api.services import sleep_spend

PREF_KEY = "sleep-run"
BATCH_CHOICES = (10, 25, 50)
RESERVE_CHOICES = (5, 10, 20, 30)


@dataclass(frozen=True)
class RunOptions:
    batch_size: int | None = None
    continue_after_reset: bool = False
    reserve_pct: int | None = None
    scheduled_use_plan: bool = True
    spend_limit_usd: float | None = sleep_spend.DEFAULT_USD
    keep_awake: bool = False


def _entry(registry) -> dict:
    try:
        entry = registry.prefs().get(PREF_KEY) or {}
    except Exception:
        return {}
    return entry if isinstance(entry, dict) else {}


def load(registry) -> RunOptions:
    """Defensive like every prefs reader: an unreadable or hand-edited file reads
    as the defaults, never as a reason to spend more — except the scheduled-plan switch,
    whose default is on (ruling 4b as amended 2026-10-19): only an explicit ``false`` turns it off,
    and a value that is neither ``true`` nor ``false`` (hand-edited) reads as off."""
    e = _entry(registry)
    size = e.get("batch_size")
    pct = e.get("reserve_pct")
    return RunOptions(
        batch_size=size if isinstance(size, int) and not isinstance(size, bool) and size in BATCH_CHOICES else None,
        continue_after_reset=e.get("continue_after_reset") is True,
        reserve_pct=pct if isinstance(pct, int) and not isinstance(pct, bool) and pct in RESERVE_CHOICES else None,
        scheduled_use_plan=_switch(e, "scheduled_use_plan", default=True),
        spend_limit_usd=_spend_limit(e),
        keep_awake=e.get("keep_awake") is True,
    )


def _spend_limit(entry: dict) -> float | None:
    """The person's figure; a stored ``0`` is their off; unset or hand-edited nonsense is the suggested one."""
    value = entry.get("spend_limit_usd")
    if value == 0 and not isinstance(value, bool):
        return None
    return float(value) if sleep_spend.valid(value) else sleep_spend.DEFAULT_USD


def _switch(entry: dict, key: str, *, default: bool) -> bool:
    """A stored switch: unset reads as ``default``; ``true``/``false`` as themselves; anything else as off."""
    if key not in entry:
        return default
    value = entry.get(key)
    return value if isinstance(value, bool) else False


def effective_batch_size(opts: RunOptions, settings) -> int:
    """The batch size a run reads with: the person's choice, else the setting."""
    from api.services.sleep_cycle import configured_batch_size

    return opts.batch_size or configured_batch_size(settings)


def write(registry, *, batch_size=..., continue_after_reset=..., reserve_pct=..., scheduled_use_plan=...,
          spend_limit_usd=..., keep_awake=...) -> None:
    """Persist the fields that were passed (``...`` leaves one alone; ``None``
    clears ``batch_size`` / ``reserve_pct`` and turns the spending limit off). Callers validate first."""
    if spend_limit_usd is not ...:
        registry.set_pref(PREF_KEY, "spend_limit_usd", 0 if spend_limit_usd is None else spend_limit_usd)
    if batch_size is not ...:
        registry.set_pref(PREF_KEY, "batch_size", batch_size)
    if continue_after_reset is not ...:
        registry.set_pref(PREF_KEY, "continue_after_reset", True if continue_after_reset else None)
    if reserve_pct is not ...:
        registry.set_pref(PREF_KEY, "reserve_pct", reserve_pct)
    if scheduled_use_plan is not ...:
        # Stored both ways: an explicit off must outlive the default flipping on (2026-10-19).
        registry.set_pref(PREF_KEY, "scheduled_use_plan", bool(scheduled_use_plan))
    if keep_awake is not ...:
        registry.set_pref(PREF_KEY, "keep_awake", True if keep_awake else None)
