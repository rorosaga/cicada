"""`cicada_project`'s reply (G141 PJ-2, spec §10.2) — absolute data from the
read model, relative words derived per call and printed beside the date:
"yesterday (2026-09-22)". An agent never has to trust a relative word alone
(R-PJ6), and nothing here is stored, so a reply is only ever as old as the
call that made it.

R12 holds for tool output as for the primer: the closing line names
`cicada_recall_detail(entity_id)` only when the caller holds it, and
`cicada_note_progress` only when the caller holds that (T5). The Now and
Quiet lines print each thread's claim id: `settles` needs it, and this reply is
the only place an agent can learn it (§10.2). A quote is the
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


def _names(timeline) -> dict[str, str]:
    return {timeline.project.id: timeline.project.name, **{
        m.id: m.name for g in timeline.cluster.groups for m in g.members if m.id}}


def _page_name(timeline, memory_path: Path, stem: str | None) -> str:
    if not stem:
        return timeline.project.name
    known = _names(timeline).get(stem)
    if known:
        return known
    try:
        from api.services import markdown_parser

        fm = markdown_parser.parse(Path(memory_path) / "entities" / f"{stem}.md").frontmatter or {}
    except Exception:  # noqa: BLE001 — a name is never worth a failed reply
        fm = {}
    return str(fm.get("name") or stem.replace("-", " ").title())


def _asked(memory_path: Path) -> set[str]:
    """Claim ids a pending `followup` inbox item already asks about (PJ-6) —
    the Quiet line then says so, so an agent does not ask the same question."""
    from api.services import bank_index

    out: set[str] = set()
    for f in bank_index.files(Path(memory_path), "inbox"):
        fm = f.frontmatter or {}
        if fm.get("kind") == "followup" and str(fm.get("status") or "pending") == "pending" and fm.get("claim_id"):
            out.add(str(fm["claim_id"]))
    return out


def _thread_lines(timeline, state: dict, *, memory_path: Path, today: date,
                  raw: bool) -> tuple[list[str], list[str]]:
    """`(Now lines, Quiet lines)`: a thread still inside its quiet threshold is
    NOW; one past it (`followupEligible`, §6.2) is QUIET, with the day it was
    last heard — the same split the app draws from the same function. A thread
    in the person's own Log words (`verbatim`) is a quote like any other: without
    `raw` it reads "a note of yours on <page>" (R-PJ23; task-5 review r1 found
    these lines printing the words the Happened row already hid). The claim id
    stays, so `settles` still works."""
    eligible = {t.get("claimId") for t in state.get("threads") or [] if t.get("followupEligible")}
    quiet_days = {t.get("claimId"): t.get("quietDays") for t in state.get("threads") or []}
    asked = _asked(memory_path) if eligible else set()
    now, quiet = [], []
    for t in timeline.now.threads:
        text = t.text
        if t.verbatim and not raw:
            text = f"a note of yours on {_page_name(timeline, memory_path, t.on)}"
        if t.claim_id in eligible:
            tail = "; asked in Inbox" if t.claim_id in asked else ""
            quiet.append(f"Quiet: {text} — quiet {quiet_days.get(t.claim_id)} days (last {t.last_heard}){tail} "
                         f"[{t.claim_id}]")
        else:
            now.append(f"Now: {text} — since {rel(t.since, today)} "
                       f"[on {_page_name(timeline, memory_path, t.on)}; {t.claim_id}]")
    return now, quiet


def _early_late(days) -> str:
    if not days:
        return "on time"
    return f"{abs(days)} day{'s' if abs(days) != 1 else ''} {'early' if days < 0 else 'late'}"


def _happened_lines(timeline, state: dict, *, memory_path: Path, today: date, raw: bool) -> list[str]:
    done = {m.get("slug"): m for m in state.get("milestones") or [] if m.get("state") == "done"}
    marks = [(m.done_on, m) for m in timeline.milestones if m.slug in done and m.done_on]
    rows = [(i.day, i) for i in timeline.items if i.kind in ("moment", "happening") and i.day]
    rows += marks
    # Newest first, a happening before a moment and a milestone on the same day.
    rank = {"happening": 0, "moment": 1}
    rows.sort(key=lambda r: (r[0], -rank.get(getattr(r[1], "kind", ""), 2)), reverse=True)
    if not rows:
        return []
    texts: dict[str, str | None] = {}
    out = ["Happened (newest first):"]
    for day, item in rows[:HAPPENED_ROWS]:
        if not hasattr(item, "kind"):      # a done milestone (§10.2)
            out.append(f"- {rel(day, today)} · done · {item.name} "
                       f"(milestone, {_early_late(done[item.slug].get('days'))})")
            continue
        if item.kind == "happening":
            out.append(_happening_line(timeline, item, memory_path=memory_path, today=today, raw=raw, texts=texts))
            continue
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


def _happening_line(timeline, item, *, memory_path: Path, today: date, raw: bool, texts: dict) -> str:
    """`- day · status · sentence <document url> · "quote" [claim, episode]`.
    The person's own Log words (`verbatim`) are a quote too: without `raw`
    (a remote caller lacking `sources`, R-PJ23) the row says only that a note
    of theirs exists, never its words."""
    head = f"- {rel(item.day, today)} · {item.state or 'done'} · "
    if item.verbatim and not raw:
        return head + f"a note of yours on {_page_name(timeline, memory_path, item.project)} [{item.id}]"
    line = head + item.text
    for p in item.participants:
        if p.role == "document" and p.url:
            line += f" <{p.url}>"
    quote = _quote_text(item, memory_path, texts) if raw else None
    if quote:
        line += f' · "{quote}"'
    episode = item.quote.episode if item.quote else None
    return line + (f" [{item.id}, {episode}]" if episode else f" [{item.id}]")


def _around_line(timeline) -> str | None:
    def member(m) -> str:
        return f"{m.name} ({m.fact})" if m.fact else m.name

    bits = []
    for g in timeline.cluster.groups:
        linked = [m for m in g.members if not m.pending]
        if linked:
            bits.append(f"{g.label} — " + ", ".join(member(m) for m in linked) + (f" +{g.more} more" if g.more else ""))
    if timeline.cluster.also_uses:
        bits.append("Also uses — " + ", ".join(member(m) for m in timeline.cluster.also_uses))
    if not bits:
        return None
    # §6.4: a name that took part in an event but has no page yet — the
    # promotion rule made visible, never hidden.
    pending = [m.name for g in timeline.cluster.groups for m in g.members if m.pending]
    bits.append("Not a page yet — " + (", ".join(pending) if pending else "(none)"))
    return "Around it: " + " · ".join(bits)


BACKLOG_IN_REPLY = 5


def _backlog_line(items, can_backlog: bool) -> str | None:
    """G150 (R-B16): the project's open backlog items, most recently touched
    first, at most five by title — and the tool that lists them all, named
    only for a caller that holds it (R12 for tool output)."""
    items = list(items or ())
    if not items:
        return None
    shown = ["{} {}".format(i.id, i.title) + (f" [{i.triage}]" if i.triage else "")
             + (" (doing)" if i.status == "doing" else "") for i in items[:BACKLOG_IN_REPLY]]
    line = f"Backlog: {len(items)} open — " + "; ".join(shown)
    if len(items) > BACKLOG_IN_REPLY:
        line += f"; and {len(items) - BACKLOG_IN_REPLY} more"
    return line + (" — cicada_backlog(project) lists them all" if can_backlog else "")


def render(timeline, state: dict, *, memory_path: Path, today: date, raw: bool, can_note: bool,
           can_detail: bool, backlog=(), can_backlog: bool = False) -> str:
    """The reply, line by line (§10.2). `state` is `project_state.timeline_state`
    for `today`; it carries only `slug/state/days/moved` per milestone, so
    names, targets and chains are joined from `timeline.milestones` by slug.
    `can_note` names `cicada_note_progress` in the closing line (T5) only for
    a caller that holds it (R12 for tool output); `backlog` is the project's
    open items in list order (G150), `can_backlog` the same gate for
    `cicada_backlog`."""
    lines: list[str] = []
    head = f"{timeline.project.name} — {'planned' if state.get('planned') else 'unplanned'}"
    if state.get("planned"):
        prog = state.get("progress") or {}
        head += f" · {prog.get('done', 0)} of {prog.get('total', 0)} milestones done"
    if timeline.last_moment_day:
        head += f" · last activity {rel(timeline.last_moment_day, today)}"
    lines.append(head)
    now_lines, quiet_lines = _thread_lines(timeline, state, memory_path=memory_path, today=today, raw=raw)
    lines += now_lines
    for line in (_next_line(timeline, state), _passed_line(timeline, state)):
        if line:
            lines.append(line)
    lines += quiet_lines
    pending = timeline.pending
    if pending.unconsolidated:
        n = pending.unconsolidated
        # The word only ("from today"): the date is the newest conversation's, not a deadline.
        since = f" from {rel(pending.newest_day, today).split(' (')[0]}" if pending.newest_day else ""
        lines.append(f"Waiting for Sleep: {n} conversation{'s' if n != 1 else ''}{since}")
    lines += _happened_lines(timeline, state, memory_path=memory_path, today=today, raw=raw)
    backlog_line = _backlog_line(backlog, can_backlog)
    if backlog_line:
        lines.append(backlog_line)
    around = _around_line(timeline)
    if around:
        lines.append(around)
    note = "record progress with cicada_note_progress (settles=<claim id> to finish a thread above)"
    if can_detail and can_note:
        lines.append(f"Open a page with cicada_recall_detail(entity_id); {note}.")
    elif can_detail:
        lines.append("Open a page with cicada_recall_detail(entity_id).")
    elif can_note:
        lines.append(f"{note[0].upper()}{note[1:]}.")
    return "\n".join(lines)
