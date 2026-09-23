"""`cicada_project`'s reply (G141 PJ-2, spec §10.2) — absolute data from the
read model, relative words derived per call and printed beside the date:
"yesterday (2026-09-22)". An agent never has to trust a relative word alone
(R-PJ6), and nothing here is stored, so a reply is only ever as old as the
call that made it.

R12 holds for tool output as for the primer: the closing line names
`cicada_recall_detail(entity_id)` only when the caller holds it, and
`cicada_note_progress` only when the caller holds that (T5). A quote is the
person's verbatim words, printed only when `raw` — a remote caller needs the
`sources` scope (R-PJ23), the line G135 draws for every other verbatim word.

Each rung is emitted only when it has content: a missing fact omits its line,
never a guess (the Sleep page's `SentenceLine` rule).
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

DEFAULT_SINCE_DAYS, MAX_SINCE_DAYS, HAPPENED_ROWS, QUOTE_CHARS = 90, 365, 12, 160
NEXT_ROWS = 3
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}")


def since_day(raw, today: date) -> str:
    """R-PJB26: a date, or a number of days back (default 90, at most 365)."""
    text = str(raw or "").strip()
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        pass
    try:
        n = max(1, min(int(text), MAX_SINCE_DAYS))
    except ValueError:
        n = DEFAULT_SINCE_DAYS
    return (today - timedelta(days=n)).isoformat()


def _word(n: int) -> str:
    return {0: "today", -1: "yesterday", 1: "tomorrow"}.get(n) or (f"in {n} days" if n > 0 else f"{-n} days ago")


def rel(day: str | None, today: date) -> str:
    """Both forms, always: `today (2026-09-23)`, `in 8 days (2026-10-01)`."""
    if not day:
        return "undated"
    n = (date.fromisoformat(day[:10]) - today).days
    return f"{_word(n)} ({day[:10]})"


def _link_target(claim) -> str | None:
    """A chain link's target day: a milestone's `target` (PJ-3), else a G17
    `due` link's own ISO-date object."""
    target = getattr(claim, "target", None)
    if target:
        return str(target)[:10]
    obj = str(getattr(claim, "object", "") or "")
    return obj[:10] if _ISO.match(obj) else None


def _next_line(timeline, state: dict) -> str | None:
    rows = {m.slug: m for m in timeline.milestones}
    bits: list[str] = []
    for ms in state.get("milestones") or []:
        m = rows.get(ms.get("slug"))
        if m is None or m.status != "planned" or m.source == "expectedEnd":
            continue
        if not m.target or ms.get("state") == "someday":
            bits.append(f"{m.name} — no date")
        else:
            days = ms.get("days") or 0
            when_words = f"in {days} days" if days > 1 else (
                "tomorrow" if days == 1 else "today" if days == 0 else f"{-days} days overdue")
            moved = ""
            if ms.get("moved") and len(m.chain) > 1:
                before = _link_target(m.chain[1])
                if before:
                    moved = f", moved from {before}"
            bits.append(f"{m.name} — {m.target}, {when_words}{moved}")
        if len(bits) >= NEXT_ROWS:
            break
    return ("Next: " + " · ".join(bits)) if bits else None


def _passed_line(timeline, state: dict) -> str | None:
    passed = {ms.get("slug") for ms in state.get("milestones") or [] if ms.get("state") == "passed-no-word"}
    # Oldest first: the list reads as the order things were meant to happen in.
    rows = sorted((m for m in timeline.milestones if m.slug in passed), key=lambda m: (m.target or "", m.slug))
    if not rows:
        return None
    return "Passed, no word on how it went: " + " · ".join(f"{m.name} — {m.target}" for m in rows)


def _quote_text(item, memory_path: Path, texts: dict[str, str | None]) -> str | None:
    q = item.quote
    if q is None or q.start is None or q.end is None or q.status == "stale":
        return None
    if q.episode not in texts:
        from api.services import evidence

        texts[q.episode] = evidence.source_text(memory_path, q.episode)
    text = texts[q.episode]
    if not text or q.end > len(text):
        return None
    words = " ".join(text[q.start:q.end].split())
    if not words:
        return None
    return words if len(words) <= QUOTE_CHARS else words[: QUOTE_CHARS - 1].rstrip() + "…"


def _happened_lines(timeline, *, memory_path: Path, today: date, raw: bool) -> list[str]:
    rows = [i for i in timeline.items if i.kind in ("moment", "happening", "milestone") and i.day]
    if not rows:
        return []
    texts: dict[str, str | None] = {}
    out = ["Happened (newest first):"]
    for item in rows[:HAPPENED_ROWS]:
        line = f"- {rel(item.day, today)} · {item.state or 'said'} · "
        quote = _quote_text(item, memory_path, texts) if raw else None
        if quote:
            line += f'"{quote}" — '
        phrases = [f.phrase for f in item.facts] or ([item.text] if item.text else [])
        line += "; ".join(phrases)
        if item.more_facts:
            line += f" +{item.more_facts} fact{'s' if item.more_facts != 1 else ''}"
        episode = (item.quote.episode if item.quote else None) or (
            item.conversation.episode_id if item.conversation else None)
        if episode:
            line += f" [{episode}]"
        out.append(line)
    if len(rows) > HAPPENED_ROWS:
        out.append(f"… {len(rows) - HAPPENED_ROWS} more")
    return out


def _around_line(timeline) -> str | None:
    def member(m) -> str:
        return f"{m.name} ({m.fact})" if m.fact else m.name

    bits = [f"{g.label} — " + ", ".join(member(m) for m in g.members) + (f" +{g.more} more" if g.more else "")
            for g in timeline.cluster.groups if g.members]
    if timeline.cluster.also_uses:
        bits.append("Also uses — " + ", ".join(member(m) for m in timeline.cluster.also_uses))
    return ("Around it: " + " · ".join(bits)) if bits else None


def render(timeline, state: dict, *, memory_path: Path, today: date, raw: bool, can_note: bool,
           can_detail: bool) -> str:
    """The reply, line by line (§10.2). `state` is `project_state.timeline_state`
    for `today`; it carries only `slug/state/days/moved` per milestone, so
    names, targets and chains are joined from `timeline.milestones` by slug.
    `can_note` names `cicada_note_progress` in the closing line once that tool
    exists (T5); `Now:` and `Quiet:` join with the event layer then too."""
    lines: list[str] = []
    head = f"{timeline.project.name} — {'planned' if state.get('planned') else 'unplanned'}"
    if state.get("planned"):
        prog = state.get("progress") or {}
        head += f" · {prog.get('done', 0)} of {prog.get('total', 0)} milestones done"
    if timeline.last_moment_day:
        head += f" · last activity {rel(timeline.last_moment_day, today)}"
    lines.append(head)
    for line in (_next_line(timeline, state), _passed_line(timeline, state)):
        if line:
            lines.append(line)
    pending = timeline.pending
    if pending.unconsolidated:
        n = pending.unconsolidated
        # The word only ("from today"): the date is the newest conversation's, not a deadline.
        since = f" from {rel(pending.newest_day, today).split(' (')[0]}" if pending.newest_day else ""
        lines.append(f"Waiting for Sleep: {n} conversation{'s' if n != 1 else ''}{since}")
    lines += _happened_lines(timeline, memory_path=memory_path, today=today, raw=raw)
    around = _around_line(timeline)
    if around:
        lines.append(around)
    if can_detail:
        lines.append("Open a page with cicada_recall_detail(entity_id).")
    return "\n".join(lines)
