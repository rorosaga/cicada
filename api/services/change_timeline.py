"""``cicada_timeline(since)`` — what changed in memory, read from git on demand (G140 Q-R4, R3 P6).

Instinct keeps ``timeline/daily`` and ``timeline/weekly`` folders, and the
article's replication demos "what changed recently?". Cicada already holds the
answer in machine-parseable form: every writer commits one manifest line per
file (``<path>: <action> (source: …, trigger: …)``) under a subject that
names the writer, above its ``Cicada-*`` trailers. So this module READS the
history and stores nothing — no file in the bank (a second timeline is the
redundant, stale copy the article itself reports), no cache (the
``sleep.next_at`` precedent: a clock-shaped answer is computed per request).

Rails:
* **Engine-free and bounded.** One ``git log`` with ``-n MAX_COMMITS`` and a
  timeout; bodies are parsed HERE by ``git_service.parse_cycle_body`` and
  never sent anywhere (``get_sleep_history``'s lesson: ``%b`` over the wire
  grew one endpoint to 378 KB). Captures come from ``bank_index``'s
  frontmatter cache.
* **Ids and counts only.** No episode title, no claim text, no conversation
  id leaves this module — a remote connection holding only ``read`` must not
  receive the person's words (G135: that is the ``sources`` scope).
* **Its own repo or nothing.** A bank that is not a git root is never read:
  ``git`` would otherwise climb into whatever repo encloses it (the
  ``agent_commits`` rule).
* **Never raises.** No git, a timeout, a garbled body — each is fewer rows.
"""
from __future__ import annotations

import subprocess
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

from api.services import bank_index, episode_ids, git_service

DEFAULT_DAYS = 7
MAX_DAYS = 90
MAX_COMMITS = 1000
GIT_TIMEOUT_S = 3.0
IDS_PER_ROW = 5
_SEP, _REC = "\x1f", "\x1e"


@dataclass
class Day:
    """One day of change, as counts and page ids (never text)."""

    day: date
    captured: Counter = field(default_factory=Counter)       # episode origin -> episodes
    consolidations: int = 0
    authors: list[str] = field(default_factory=list)         # models that ran Sleep
    conversations: set = field(default_factory=set)          # counted, never rendered
    created: list[str] = field(default_factory=list)
    updated: int = 0
    archived: list[str] = field(default_factory=list)
    faded: int = 0
    expired: list[str] = field(default_factory=list)
    agent_writes: Counter = field(default_factory=Counter)   # author -> commits
    retracted: int = 0
    answered: int = 0

    def empty(self) -> bool:
        return not (self.captured or self.consolidations or self.archived or self.faded or self.expired
                    or self.agent_writes or self.answered)


def parse_since(raw, today: date) -> date:
    """``since`` as an agent sends it: a date (``2026-09-16``), a number of
    days (``7``, ``"7d"``), or nothing (``DEFAULT_DAYS``). Clamped to
    ``MAX_DAYS`` back and never after today; anything unreadable is the default."""
    start = today - timedelta(days=DEFAULT_DAYS)
    value = "" if raw is None or isinstance(raw, bool) else str(raw).strip().lower()
    if value:
        digits = value[:-1] if value.endswith("d") else value
        if digits.isdigit():
            start = today - timedelta(days=int(digits))
        else:
            try:
                start = date.fromisoformat(value[:10])
            except ValueError:
                pass
    return min(max(start, today - timedelta(days=MAX_DAYS)), today)


def kind_of(subject: str) -> str | None:
    """Which writer made a commit, from its subject. ``None`` = not a change
    worth reporting (the ``State snapshot`` projection)."""
    s = (subject or "").strip().lower()
    if s.startswith("state snapshot"):
        return None
    if s.startswith("sleep cycle"):
        return "decay" if s.endswith("(decay)") else "sleep"
    if s.startswith("expiry"):
        return "expiry"
    if s.startswith("inbox resolution"):
        return "inbox"
    if s.startswith(("agent write", "remote write")):
        return "agent"
    return "other"


def _git_log(memory_path: Path, since: date, until: date) -> str | None:
    """git's ``--since``/``--until`` read LOCAL time while a commit's ``%ad``
    carries its own zone, so the window is padded a day each side and
    ``collect`` cuts it on the commit's own date — the same day the Sleep
    page shows (``get_sleep_history`` reads ``%ad`` too)."""
    try:
        proc = subprocess.run(
            ["git", "log", f"-n{MAX_COMMITS}", f"--since={(since - timedelta(days=1)).isoformat()}",
             f"--until={(until + timedelta(days=1)).isoformat()}T23:59:59", "--date=iso-strict",
             f"--format=%H{_SEP}%ad{_SEP}%s{_SEP}%b{_REC}"],
            cwd=str(memory_path), capture_output=True, text=True, timeout=GIT_TIMEOUT_S, check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    return proc.stdout if proc.returncode == 0 else None


def _local_day(raw) -> date | None:
    """An episode timestamp of any stored shape as a LOCAL calendar day
    (G114: legacy naive, ``Z`` and ``+00:00`` coexist; YAML may hand back a
    ``datetime``)."""
    if isinstance(raw, datetime):
        dt = raw
    else:
        key = episode_ids.timestamp_sort_key(str(raw) if raw else None)
        if not key:
            return None
        try:
            dt = datetime.fromisoformat(key)
        except ValueError:
            return None
    try:
        return dt.astimezone().date()
    except (ValueError, OverflowError, OSError):
        return None


def collect(memory_path: Path, since: date, until: date, *,
            git_log: Callable[[Path, date, date], str | None] | None = None) -> list[Day]:
    """Every day in ``[since, until]`` that had a change, newest first."""
    memory_path = Path(memory_path)
    days: dict[date, Day] = {}

    def row(d: date) -> Day:
        return days.setdefault(d, Day(d))

    raw = (git_log or _git_log)(memory_path, since, until) if (memory_path / ".git").exists() else None
    for record in (raw or "").split(_REC):
        fields = record.strip("\n").split(_SEP, 3)
        if len(fields) < 4:
            continue
        kind = kind_of(fields[2])
        if kind is None or kind == "other":
            continue
        try:
            d = date.fromisoformat(fields[1].strip()[:10])
        except ValueError:
            continue
        if not since <= d <= until:
            continue
        m = git_service.parse_cycle_body(fields[2], fields[3])
        r = row(d)
        if kind == "sleep":
            r.consolidations += 1
            r.conversations.update(m.sessions)
            r.authors += [a for a in m.authors if a not in r.authors]
            for e in m.entities:
                if e["action"] == "created":
                    r.created.append(e["id"])
                else:
                    r.updated += 1
        elif kind == "decay":
            for e in m.entities:
                if e["action"] == "archive":   # conflict_resolver's action word
                    r.archived.append(e["id"])
                else:
                    r.faded += 1
        elif kind == "expiry":
            r.expired += [e["id"] for e in m.entities]
        elif kind == "inbox":
            r.answered += 1
        elif kind == "agent":
            for author in m.authors or ["agent"]:
                r.agent_writes[author] += 1
            r.retracted += sum(1 for e in m.entities if e["action"] == "retracted")
    for f in bank_index.files(memory_path, "episodes"):
        d = _local_day(f.frontmatter.get("timestamp"))
        if d is not None and since <= d <= until:
            row(d).captured[str(f.frontmatter.get("origin") or f.frontmatter.get("harness") or "unknown")] += 1
    return [days[d] for d in sorted(days, reverse=True) if not days[d].empty()]


def _ids(ids: list[str]) -> str:
    ids = list(dict.fromkeys(ids))
    if not ids:
        return ""
    more = f" +{len(ids) - IDS_PER_ROW} more" if len(ids) > IDS_PER_ROW else ""
    return " (" + ", ".join(f"`{i}`" for i in ids[:IDS_PER_ROW]) + more + ")"


def _counted(counter: Counter) -> str:
    return ", ".join(f"{k} {n}" for k, n in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])))


def render(days: list[Day], since: date, until: date) -> str:
    """The tool's reply: one section per day, ids and counts only."""
    span = f"{since.isoformat()} → {until.isoformat()}"
    if not days:
        return f"Nothing changed in memory between {span}."
    lines = [f"What changed in memory, {span} (newest day first; ids and counts only — "
             "open a page with cicada_recall_detail):"]
    for d in days:
        lines += ["", f"## {d.day.isoformat()}"]
        if d.captured:
            lines.append(f"- Captured {sum(d.captured.values())} episode(s): {_counted(d.captured)}")
        if d.consolidations:
            who = f" by {', '.join(d.authors)}" if d.authors else ""
            convs = f" from {len(d.conversations)} conversation(s)" if d.conversations else ""
            lines.append(f"- Sleep{who}{convs}: {len(d.created)} new page(s){_ids(d.created)}, "
                         f"{d.updated} updated")
        if d.archived or d.faded:
            lines.append(f"- Faded: {d.faded} page(s) lost confidence, {len(d.archived)} archived{_ids(d.archived)}")
        if d.expired:
            lines.append(f"- Reached their stated end: facts on {len(d.expired)} page(s){_ids(d.expired)}")
        if d.agent_writes:
            extra = f" ({d.retracted} withdrawal(s))" if d.retracted else ""
            lines.append(f"- Agent writes: {_counted(d.agent_writes)}{extra}")
        if d.answered:
            lines.append(f"- Questions answered in the inbox: {d.answered}")
    return "\n".join(lines)
