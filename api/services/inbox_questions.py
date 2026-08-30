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

from datetime import date, datetime, timedelta
from pathlib import Path

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


def is_deferred(fm: dict, today: str) -> bool:
    """True while a deferred item's ``remind_after`` is still in the future.

    A deferred item is hidden from ``GET /inbox`` and ``cicada_check_nudges``;
    the file stays on disk and reappears the day the date passes.
    """
    remind = _as_date(fm.get("remind_after"))
    now = _as_date(today)
    if remind is None or now is None:
        return False
    return remind > now


_NEITHER_OPTION = {
    "key": "neither",
    "label": "Neither anymore",
    "description": "Close both; tell me what's current below",
    "claim_id": None,
}

_STALE_PRIORITY = 0.6


def _stale_question(name: str, age_phrase: str) -> str:
    return (
        f"It's been {age_phrase.replace(' ago', '')} since either came up. "
        f"Is {name} still at one of these?"
    )


def _shift(today: str, days: int) -> str:
    """``today`` minus ``days``, as an ISO date string (helper for age phrasing)."""
    base = _as_date(today)
    if base is None:
        return today
    return (base - timedelta(days=days)).isoformat()


def refresh_open_questions(
    memory_path: Path,
    claims_by_subject: dict,
    today: str,
    *,
    stale_after_days: int = 90,
) -> dict:
    """Re-score every open conflict question against this cycle's claims (§2.3).

    1. **Bump + re-order.** An option whose claim was reinforced since the option
       was last referenced gets ``last_referenced`` bumped; options are then
       re-sorted most-recent-first (synthetic rows always stay last).
    2. **Organic resolution.** If a ``user_stated`` claim now exists on the same
       ``(subject, predicate)`` — dated AFTER the item's ``created_date`` (older
       human claims were already reconciled into the graph before this question
       ever opened, so they carry no new information about it) — or one of the
       option claims has been closed (``valid_to`` set) by the reconciler, the
       question is answered — the item file is removed. The caller commits with
       trigger ``inbox/organic_resolution``.
    3. **Stale escalation.** When EVERY option is older than ``stale_after_days``,
       the question is rewritten to the stale template, a ``neither`` option is
       inserted first, and priority drops to 0.6 so fresh conflicts sort above it.
       Idempotent: an item that already carries ``neither`` is not re-escalated.
    4. Deferred items are skipped entirely.

    Returns ``{"bumped": n, "organic_resolutions": n, "escalated": n,
    "resolved_paths": [str, ...]}`` — ``resolved_paths`` lists the
    memory-relative paths (e.g. ``"inbox/inbox-001.md"``) of items removed
    by organic resolution, so the caller can tag exactly those paths with
    the ``inbox/organic_resolution`` commit trigger instead of the generic
    ``sleep/inbox_generation`` one every other ``inbox/`` write gets.
    """
    from api.services import markdown_parser

    inbox = Path(memory_path) / "inbox"
    counts = {"bumped": 0, "organic_resolutions": 0, "escalated": 0, "resolved_paths": []}
    if not inbox.exists():
        return counts

    for filepath in sorted(inbox.glob("inbox-*.md")):
        try:
            parsed = markdown_parser.parse(filepath)
        except Exception:
            continue
        fm = parsed.frontmatter
        if str(fm.get("kind", "")) != "conflict":
            continue
        if str(fm.get("status", "pending") or "pending") != "pending":
            continue
        if is_deferred(fm, today):
            continue

        subject = str(fm.get("entity_id", "") or "")
        predicate = str(fm.get("predicate", "") or "description")
        subject_claims = list(claims_by_subject.get(subject, []) or [])
        by_id = {c.id: c for c in subject_claims}
        options = normalize_options(fm.get("options"))
        option_claim_ids = [
            str(o["claim_id"]) for o in options if o.get("claim_id")
        ]

        # --- 2. organic resolution -----------------------------------------
        human_answer = any(
            c.predicate == predicate
            and c.source_trust == "user_stated"
            and c.valid_to is None
            and str(c.valid_from or "") > str(fm.get("created_date", "") or "")
            for c in subject_claims
        )
        superseded = any(
            by_id.get(cid) is not None and by_id[cid].valid_to is not None
            for cid in option_claim_ids
        )
        if human_answer or (option_claim_ids and superseded):
            filepath.unlink()
            counts["organic_resolutions"] += 1
            counts["resolved_paths"].append(f"inbox/{filepath.name}")
            continue

        changed = False

        # --- 1. bump + re-order --------------------------------------------
        bumped_any = False
        for option in options:
            claim = by_id.get(str(option.get("claim_id") or ""))
            if claim is None:
                continue
            seen = str(claim.recorded_at or claim.valid_from or "")
            current = str(option.get("last_referenced") or option.get("observed_at") or "")
            if seen and seen > current:
                option["last_referenced"] = seen
                bumped_any = True
        if bumped_any:
            counts["bumped"] += 1
            changed = True

        real = [o for o in options if str(o.get("key")) not in {"both", "neither"}]
        synthetic = [o for o in options if str(o.get("key")) in {"both", "neither"}]
        real.sort(
            key=lambda o: str(o.get("last_referenced") or o.get("observed_at") or ""),
            reverse=True,
        )
        neither = [o for o in synthetic if str(o.get("key")) == "neither"]
        both = [o for o in synthetic if str(o.get("key")) == "both"]
        options = neither + real + both

        # --- 3. stale escalation -------------------------------------------
        already_escalated = bool(neither)
        answerable = [o for o in options if str(o.get("key")) not in {"both", "neither"}]
        ages = [
            age_days(o.get("last_referenced") or o.get("observed_at"), today)
            for o in answerable
        ]
        all_stale = bool(ages) and all(a is not None and a >= stale_after_days for a in ages)
        if all_stale and not already_escalated:
            # Phrase the window from the FRESHEST option — "it's been 6 months
            # since EITHER came up" must be true of the most recent one.
            freshest = min((a for a in ages if a is not None), default=None)
            phrase = humanize_age(
                None if freshest is None else _shift(today, freshest), today
            )
            fm["question"] = _stale_question(
                str(fm.get("entity_name", "") or subject), phrase
            )
            fm["title"] = fm["question"]
            fm["priority"] = _STALE_PRIORITY
            options = [dict(_NEITHER_OPTION)] + options
            counts["escalated"] += 1
            changed = True

        if changed:
            fm["options"] = options
            fm["updated_date"] = today
            markdown_parser.write(filepath, fm, parsed.body)

    return counts
