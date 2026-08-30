"""G60 — the inbox *question object*: age phrasing, option normalization,
defer visibility, and the Stage-3 re-scoring sweep.

Every inbox item of kind ``conflict`` / ``clarification`` / ``merge_suggestion``
carries a question (one sentence) and a list of option objects modelled on
Claude Code's ``AskUserQuestion``. This module owns the pure helpers that build
and read that shape; ``inbox_generator`` writes it and ``inbox_service`` reads it.

``age_days`` is DERIVED at read time (never persisted) so a stored item never
goes stale-by-arithmetic.
"""

from __future__ import annotations

from datetime import date, datetime

_UNKNOWN_AGE = "unknown"


def _as_date(value: str | None) -> date | None:
    """Parse a plain ``YYYY-MM-DD`` or a full ISO timestamp into a date."""
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if "T" in text:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def age_days(observed: str | None, today: str) -> int | None:
    """Whole days between ``observed`` and ``today``; ``None`` if unparseable."""
    a = _as_date(observed)
    b = _as_date(today)
    if a is None or b is None:
        return None
    return max(0, (b - a).days)


def humanize_age(observed: str | None, today: str) -> str:
    """A short human age phrase: today / yesterday / N days|weeks|months|years ago."""
    days = age_days(observed, today)
    if days is None:
        return _UNKNOWN_AGE
    if days == 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 14:
        return f"{days} days ago"
    if days < 60:
        weeks = round(days / 7)
        return "a week ago" if weeks == 1 else f"{weeks} weeks ago"
    if days < 365:
        months = round(days / 30)
        return "a month ago" if months == 1 else f"{months} months ago"
    years = round(days / 365)
    return "a year ago" if years == 1 else f"{years} years ago"


def normalize_options(raw: object) -> list[dict]:
    """Coerce whatever is in ``options:`` into the object form.

    - ``None`` / ``[]``            -> ``[]``
    - legacy ``["A", "B"]``        -> ``[{"key": "0", "label": "A"}, ...]``
    - object form                  -> passed through, with a positional ``key``
                                      filled in when one is missing.
    """
    if not raw or not isinstance(raw, list):
        return []
    out: list[dict] = []
    for i, item in enumerate(raw):
        if isinstance(item, dict):
            opt = dict(item)
            if not str(opt.get("key", "") or "").strip():
                opt["key"] = str(i)
            opt["label"] = str(opt.get("label", "") or "")
            out.append(opt)
        else:
            out.append({"key": str(i), "label": str(item)})
    return out
