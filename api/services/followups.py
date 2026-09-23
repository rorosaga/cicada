"""G141 PJ-6 (§9) — ask "how did it go?" instead of letting a thread decay (G4).

Engine-free, so it runs on idle nights and on scheduled cycles without touching
a plan (ruling 4). Sleep's tail calls it right after claim expiry — the night's
expiries are visible — and before the connector poll, whose `git add -A` must
never sweep its files (R-PJB23). It writes one inbox file per item holding only
`kind, entity_id, predicate, claim_id` (+ the page name and the date — no
`source_episode`, so the card's cause is read through the claim tier and its
span): the question, its options and its age are synthesised at read by
`inbox_questions.followup_question`, like decay's — a stored copy could only go
stale. Non-intrusive by construction (UX principle 4): at most one open per
project, three in the bank, and a "not now" is never asked again for 30 days.

Eligibility is the read model's own (`project_timeline` + `project_state`), so
the Projects page, `cicada_project` and this proposer can never disagree about
whether a thread is quiet: a quiet `ongoing` happening (quiet ≥ max(21 days,
the project's own Q)), a planned milestone ≥ 3 days overdue, or a G17 `due`
that expiry closed with no word in the last 14 days (R-PJB21's
`passed-no-word`). Priority per project is that order (R-PJB23). The same test
decides whether an open follow-up still stands: a thread the app settled or the
person reinforced ("Still going" resets the quiet clock), a milestone moved or
marked, a `due` a milestone replaced — each is no longer eligible, and its file
is removed in the same commit.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from loguru import logger

from api.services import bank_index, git_service, handshake, markdown_parser, project_state, project_timeline

TRIGGER = "sleep/followup"
AUTHOR = "cicada"
MAX_OPEN = 3
PASSED_DUE_DAYS = 14
TITLE = "How did it go?"
BODY = "A follow-up on a quiet thread or a milestone."


@dataclass
class Report:
    written: list[str] = field(default_factory=list)   # memory-relative inbox paths created
    removed: list[str] = field(default_factory=list)   # stale follow-ups deleted


@dataclass(frozen=True)
class _Candidate:
    page: str          # the page that holds the claim — the item's `entity_id`
    predicate: str     # happened | milestone | due
    claim_id: str

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.page, self.predicate, self.claim_id)


def _days_since(day: str | None, today: date) -> int | None:
    try:
        return (today - date.fromisoformat(str(day)[:10])).days
    except (TypeError, ValueError):
        return None


def _eligible(memory_path: Path, today: date, tz_name: str) -> list[tuple[str, list[str], list[_Candidate], int]]:
    """`[(project, tree, candidates in priority order, quiet days of its
    quietest eligible thread)]` for every ACTIVE project. Read-only."""
    rows = project_timeline.list_projects(memory_path, tz_name=tz_name).projects
    bank = project_timeline._Bank(memory_path, tz_name)
    owner = bank.owner()
    out: list[tuple[str, list[str], list[_Candidate], int]] = []
    for row in rows:
        if str(row.status or "active") != "active":
            continue
        tree, _ = project_timeline._tree(bank, row.id)
        milestones = project_timeline._milestones(bank, tree)
        overdue: list[tuple[str, _Candidate]] = []
        passed: list[tuple[str, _Candidate]] = []
        for m in milestones:
            if not m.claim_id:
                continue
            page = m.on or row.id
            if m.source == "milestone" and m.status == "planned":
                if project_state.milestone_state(m.model_dump(by_alias=True), today)["followupEligible"]:
                    overdue.append((m.target or "", _Candidate(page, "milestone", m.claim_id)))
            elif m.source == "due" and m.status == "passed-no-word":
                age = _days_since(m.target, today)
                if age is not None and 0 < age <= PASSED_DUE_DAYS:
                    passed.append((m.target or "", _Candidate(page, "due", m.claim_id)))
        threads = project_timeline._threads(bank, row.id, project_timeline._events(bank, tree, owner))
        state = project_state.timeline_state({
            "status": row.status, "lastMomentDay": row.last_moment_day, "medianGapDays": row.median_gap_days,
            "openThreads": [t.model_dump(by_alias=True) for t in threads]}, today)
        quiet: list[tuple[int, _Candidate]] = []
        for t, s in zip(threads, state["threads"]):
            if s["followupEligible"]:
                quiet.append((int(s["quietDays"] or 0), _Candidate(t.on or row.id, "happened", t.claim_id)))
        candidates = ([c for _, c in sorted(overdue, key=lambda x: (x[0], x[1].claim_id))]
                      + [c for _, c in sorted(passed, key=lambda x: (x[0], x[1].claim_id))]
                      + [c for _, c in sorted(quiet, key=lambda x: (-x[0], x[1].claim_id))])
        out.append((row.id, tree, candidates, max((q for q, _ in quiet), default=0)))
    return out


def propose(memory_path: Path, today: date, *, skip: frozenset[str] = frozenset(),
            tz_name: str | None = None) -> Report:
    """Clear the follow-ups that no longer stand, then ask at most one per
    project and three in the bank. Writes files only — the caller commits
    `report.written + report.removed` (R-PJB23). `skip` holds memory-relative
    paths dirty before the run: a follow-up on such a page is neither written
    nor removed, so a person's uncommitted edit is never asked about, smeared
    into a `cicada` commit, or lost to `restore`'s checkout."""
    memory_path = Path(memory_path)
    report = Report()
    tz_name = tz_name or handshake.local_timezone() or "UTC"
    projects = _eligible(memory_path, today, tz_name)
    eligible: dict[tuple[str, str, str], set[str]] = {}
    for project, _, candidates, _ in projects:
        for c in candidates:
            eligible.setdefault(c.key, set()).add(project)

    open_keys: list[tuple[str, str, str]] = []
    for f in bank_index.files(memory_path, "inbox"):
        fm = f.frontmatter or {}
        if str(fm.get("kind") or "") != "followup":
            continue
        key = (str(fm.get("entity_id") or ""), str(fm.get("predicate") or ""), str(fm.get("claim_id") or ""))
        if key not in eligible and f"entities/{key[0]}.md" not in skip:
            try:
                f.path.unlink()
            except OSError as exc:
                logger.warning(f"follow-up cleanup skipped {f.path.name}: {type(exc).__name__}")
                open_keys.append(key)
                continue
            report.removed.append(f"inbox/{f.path.name}")
            continue
        open_keys.append(key)       # a deferred item still counts as open (it comes back by itself)
    if report.removed:
        bank_index.invalidate(memory_path)

    asked: set[str] = {p for k in open_keys for p in eligible.get(k, ())}
    open_pages = {k[0] for k in open_keys}
    inbox_dir = memory_path / "inbox"
    names = project_timeline._Bank(memory_path, tz_name)
    count = len(open_keys)
    for project, tree, candidates, _ in sorted(projects, key=lambda p: (-p[3], p[0])):
        if count >= MAX_OPEN:
            break
        if project in asked or open_pages & set(tree):
            continue
        pick = next((c for c in candidates if f"entities/{c.page}.md" not in skip
                     and c.key not in open_keys), None)
        if pick is None:
            continue
        inbox_dir.mkdir(parents=True, exist_ok=True)
        from api.services import inbox_service   # lazy: inbox_service's import graph is wide

        path = inbox_dir / f"inbox-{inbox_service.next_inbox_num(inbox_dir):03d}.md"
        markdown_parser.write(path, {
            "kind": "followup", "required_input": "choice", "status": "pending", "priority": 0.5,
            "entity_id": pick.page, "entity_name": names.name(pick.page), "predicate": pick.predicate,
            "claim_id": pick.claim_id, "title": TITLE, "created_date": today.isoformat()}, BODY)
        report.written.append(f"inbox/{path.name}")
        open_keys.append(pick.key)
        asked |= eligible.get(pick.key, set())
        count += 1
    if report.written:
        bank_index.invalidate(memory_path)
    return report


def commit_message(report: Report, today: date) -> str:
    """`Follow-ups <date>`, `Cicada-Author: cicada`, no engine trailer — no
    LLM ran (the G85 / expiry shape). Inbox lines only: `_infer_change_type`
    keys on entity lines, so the commit never reads as a consolidation."""
    return git_service.build_commit_message(
        f"Follow-ups {today.isoformat()}",
        [f"{p}: created (source: n/a, trigger: {TRIGGER})" for p in report.written]
        + [f"{p}: removed (source: n/a, trigger: {TRIGGER})" for p in report.removed],
        authors=[AUTHOR])


def restore(memory_path: Path, report: Report) -> None:
    """Undo a run whose commit failed: the files it wrote are unlinked and the
    ones it removed come back from HEAD. Left on disk, either would ride the
    next `git add -A` writer's commit under the wrong author (the G85 smear);
    the proposal is re-derived tomorrow."""
    memory_path = Path(memory_path)
    for rel in report.written:
        (memory_path / rel).unlink(missing_ok=True)
    if report.removed and (memory_path / ".git").exists():
        try:
            subprocess.run(["git", "checkout", "--", *report.removed], cwd=str(memory_path),
                           capture_output=True, timeout=10, check=False)
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.warning(f"follow-up restore failed: {type(exc).__name__}")
    bank_index.invalidate(memory_path)
