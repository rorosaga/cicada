"""The entity card's bands, computed behind the API (G180 parity: a browser front end must not re-derive them).

Three classifications the app used to make only in Swift (`EntityHeaderWords`, `FadeWords`):

- **confidence** — ``very`` (0.85 and up), ``fairly`` (0.6), ``unsure`` (0.4), else ``doubtful`` (R-DG14);
- **fade pace** — from the rate Sleep actually charges (`decay_policy.effective`, G147): ``never`` at or under 0,
  ``very_slowly`` at or under 0.0125, ``slowly`` at or under 0.03, ``usual`` under 0.08, else ``quickly``;
- **last mentioned** — the page's ``last_referenced`` day when it is a real past day more than
  ``OLD_AFTER_DAYS`` before today (G194 D1/A2): the header then names that month instead of a confidence word.

Bands only: the words a person reads stay in each client's copy (localised there). One table pins both sides,
``api/tests/fixtures/entity_bands.json`` (`test_entity_bands.py`, `EntityBandsTests.swift`). Pure; nothing stored.
"""
from __future__ import annotations

import math
from datetime import date

from api.services.source_dates import OLD_AFTER_DAYS

__all__ = ["OLD_AFTER_DAYS", "bands", "confidence_band", "fade_pace", "last_mentioned", "strict_day"]

CONFIDENCE_STEPS = ((0.85, "very"), (0.6, "fairly"), (0.4, "unsure"))
VERY_SLOWLY_MAX = 0.0125
SLOWLY_MAX = 0.03
USUAL_BELOW = 0.08


def confidence_band(value) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "doubtful"
    if math.isnan(v):
        return "doubtful"
    for floor, band in CONFIDENCE_STEPS:
        if v >= floor:
            return band
    return "doubtful"


def fade_pace(rate_per_week) -> str:
    try:
        rate = float(rate_per_week)
    except (TypeError, ValueError):
        return "usual"
    if rate <= 0:
        return "never"
    if rate <= VERY_SLOWLY_MAX:
        return "very_slowly"
    if rate <= SLOWLY_MAX:
        return "slowly"
    if rate < USUAL_BELOW:
        return "usual"
    return "quickly"


def strict_day(raw) -> date | None:
    """`YYYY-MM-DD`, alone or before a time (`T` or a space), naming a day the calendar has; anything else is no
    day (the card must never show a day the page did not name)."""
    if not isinstance(raw, str) or len(raw) < 10:
        return None
    head = raw[:10]
    if head[4] != "-" or head[7] != "-" or not all(head[i].isdigit() for i in (0, 1, 2, 3, 5, 6, 8, 9)):
        return None
    if len(raw) > 10 and raw[10] not in ("T", " "):
        return None
    try:
        return date.fromisoformat(head)
    except ValueError:
        return None


def last_mentioned(raw, today: date) -> date | None:
    day = strict_day(raw)
    return day if day is not None and (today - day).days > OLD_AFTER_DAYS else None


def bands(*, confidence, rate_per_week, last_referenced, today: date) -> dict:
    day = last_mentioned(last_referenced, today)
    return {"confidence": confidence_band(confidence), "fade_pace": fade_pace(rate_per_week),
            "last_mentioned": day.isoformat() if day else None}
