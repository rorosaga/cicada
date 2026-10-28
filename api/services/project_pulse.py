"""A project's pulse (decision 9, owner 2026-10-28): three counted facts, no model, read at the viewer's today.

* **Last 4 weeks** — the conversations tied to the project, one bar per week (the server counts each conversation
  once, on its newest day: ``conversationDays``), and how many things were done in those 28 days (a done happening on
  its day, a done milestone on its ``doneOn``).
* **Waiting on** — an open thread that names who it comes from (a participant with the ``from`` role, written by the
  one event writer, ``progress``): "the supplier · fibreglass cloth". A structural fact on the claim, never a reading
  of its words.
* **Gone quiet** — an open thread nothing has been heard of for at least the project's quiet threshold
  (``project_state.quiet_threshold``, the same Q the list and the follow-ups use), most quiet first, never one already
  under Waiting on.

The pulse never repeats the header's standing line or its Next (DR-38). It is a pure function of the wire and
``today`` — Python here (for ``cicada_project``) and Swift in the app (``ProjectPulse.swift``) run ONE fixture,
``api/tests/fixtures/project_pulse.json``, the ``timeline_state.json`` precedent: two languages, one table. Nothing is
stored and nothing reads a clock.
"""
from __future__ import annotations

from datetime import date, timedelta

from api.services import project_state

WEEKS = 4
#: Each of Waiting on and Gone quiet names at most this many threads; the In motion section lists them all.
SHOWN = 2


def _d(value) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def pulse(state_in: dict, today) -> dict:
    """``state_in``: ``conversationDays`` [{day, n}], ``done`` [days], ``openThreads`` [{claimId, text, since,
    lastHeard, waitingOn?}], ``medianGapDays`` / ``momentDays`` (for the quiet threshold). See :func:`input_from_timeline`."""
    today = _d(today)
    first = today - timedelta(days=7 * WEEKS - 1)
    weeks = [0] * WEEKS
    for row in state_in.get("conversationDays") or []:
        day = _d(row.get("day"))
        if day is None or day < first or day > today:
            continue
        weeks[(day - first).days // 7] += int(row.get("n") or 0)
    done = sum(1 for d in (_d(x) for x in state_in.get("done") or []) if d is not None and first <= d <= today)
    gap = state_in.get("medianGapDays")
    if gap is None and state_in.get("momentDays"):
        gap = project_state.median_gap(state_in["momentDays"])
    q = project_state.quiet_threshold(gap)
    waiting, quiet = [], []
    for t in state_in.get("openThreads") or []:
        who = " ".join(str(t.get("waitingOn") or "").split())
        if who:
            waiting.append({"claimId": t.get("claimId"), "who": who, "text": t.get("text") or "",
                            "since": t.get("since")})
            continue
        heard = _d(t.get("lastHeard")) or _d(t.get("since"))
        if heard is None:
            continue
        days = (today - heard).days
        if days >= q:
            quiet.append({"claimId": t.get("claimId"), "text": t.get("text") or "", "since": t.get("since"),
                          "quietDays": days})
    waiting.sort(key=lambda w: (str(w["since"] or ""), str(w["claimId"])))
    quiet.sort(key=lambda w: (-w["quietDays"], str(w["claimId"])))
    conversations = sum(weeks)
    return {"weeks": weeks, "conversations": conversations, "done": done, "quietThreshold": q,
            "waiting": waiting[:SHOWN], "waitingTotal": len(waiting), "quiet": quiet[:SHOWN],
            "quietTotal": len(quiet), "empty": not (conversations or done or waiting or quiet)}


def input_from_timeline(timeline) -> dict:
    """A ``ProjectTimeline`` as :func:`pulse`'s input."""
    wire = timeline.model_dump(by_alias=True)
    done = [i.get("day") for i in wire.get("items") or []
            if i.get("kind") == "happening" and i.get("state") == "done" and i.get("day")]
    done += [m.get("doneOn") for m in wire.get("milestones") or []
             if m.get("status") == "done" and m.get("doneOn") and m.get("source") != "expectedEnd"]
    return {"conversationDays": wire.get("conversationDays") or [], "done": done,
            "openThreads": (wire.get("now") or {}).get("threads") or [],
            "medianGapDays": wire.get("medianGapDays"), "momentDays": wire.get("momentDays") or []}


def lines(p: dict, *, hidden: set[str] = frozenset()) -> list[str]:
    """The pulse in words, for an agent (``cicada_project``). Gone quiet is left to the reply's own "Quiet:" lines
    (``project_text``), which say the same threads — never twice. ``hidden``: the claim ids whose words are the
    person's own Log sentence and may not be printed here (R-PJ23: a remote caller without ``sources``)."""
    out: list[str] = []
    if p["conversations"] or p["done"]:
        bits = [f"{p['conversations']} conversation{'s' if p['conversations'] != 1 else ''}"] if p["conversations"] else []
        if p["done"]:
            bits.append(f"{p['done']} done")
        out.append("Last 4 weeks: " + " · ".join(bits) + f" (weekly, oldest first: {', '.join(map(str, p['weeks']))}).")
    for w in p["waiting"]:
        text = "a note of yours" if w["claimId"] in hidden else w["text"]
        out.append(f"Waiting on: {w['who']} · {text} (since {w['since']}) [{w['claimId']}]")
    return out
