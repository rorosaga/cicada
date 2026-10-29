"""What one consolidation read and wrote, item by item — the Sleep page's run card dropdown (owner 2026-10-26).

``GET /sleep/runs/{id}/items`` (a run's batch commits, from its ``sleep_run`` ledger rows) and
``GET /sleep/history/{commit}/items`` (one plain cycle). Read from git, never from a model: each commit's own file
list (``git diff-tree --name-status``) says which conversations a batch read (their ``processed`` flip lands in the
batch commit), which pages it made (added) or changed (modified), and which questions it raised (a new
``inbox/inbox-*.md``) or settled (an item moved under ``inbox/settled/`` — in Sleep's own settle commits during the run,
:func:`settle_commits`, since a settle never rides a batch commit). The manifest in the commit body is not
enough on its own: the first commit of a bank collapses a new folder to one ``episodes/`` line.

Names and titles are read from the bank now — what the app already shows for each episode, page and question — and a
file gone since reads as its id. Each list is capped (``CAP``) with ``truncated`` set; the counts stay whole.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from api.models.schemas import (
    SleepConsolidated,
    SleepConsolidatedConversation,
    SleepConsolidatedPage,
    SleepConsolidatedQuestion,
)
from api.services import bank_index, git_service

#: Folded into the routes' ETag: bump it when the body's shape changes.
#: items-2 (G227): a page row whose title another page shares adds `qualifier` and `displayName`.
SHAPE = "items-2"
CAP = 200

_EPISODE = re.compile(r"^episodes/(?P<name>[^/]+\.md)$")
_ENTITY = re.compile(r"^entities/(?P<name>[^/]+)\.md$")
_RAISED = re.compile(r"^inbox/(?P<name>inbox-[^/]+\.md)$")
_SETTLED = re.compile(r"^inbox/settled/(?P<name>inbox-[^/]+\.md)$")


async def changed_files(memory_path: Path, commit: str) -> list[tuple[str, str]]:
    """``(status letter, path)`` for every file ``commit`` changed — the root commit included (``--root``); a rename
    reads as its destination, added. ``[]`` when git cannot answer."""
    try:
        out = await git_service._run_git(Path(memory_path), "diff-tree", "--root", "--no-commit-id", "-r",
                                         "--name-status", "-M", commit)
    except Exception:  # noqa: BLE001 - a list for a dropdown, never worth failing a page
        return []
    rows: list[tuple[str, str]] = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0][:1]
        rows.append(("A" if status == "R" else status, parts[-1].strip()))
    return rows


def _header(memory_path: Path, subdir: str, name: str) -> dict:
    entry = bank_index.file(Path(memory_path), subdir, name)
    return dict(entry.frontmatter or {}) if entry is not None else {}


def _conversation(memory_path: Path, name: str) -> SleepConsolidatedConversation:
    from api.services.sleep_cycle import _derive_origin

    fm = _header(memory_path, "episodes", name)
    return SleepConsolidatedConversation(
        id=str(fm.get("id") or name[:-3]),
        title=(str(fm.get("title")).strip() or None) if fm.get("title") else None,
        origin=str(fm.get("origin") or _derive_origin(fm.get("source"))) if fm else "unknown",
        timestamp=str(fm.get("timestamp")) if fm.get("timestamp") else None,
    )


def _page(memory_path: Path, entity_id: str) -> SleepConsolidatedPage:
    from api.services import same_name

    fm = _header(memory_path, "entities", f"{entity_id}.md")
    name = str(fm.get("name") or "") or None
    q = same_name.qualifier(memory_path, entity_id) if fm else None
    return SleepConsolidatedPage(id=entity_id, name=name, type=str(fm.get("type") or "") or None, gone=not fm,
                                 qualifier=q, display_name=same_name.display(name, q) if q and name else None)


def _question(memory_path: Path, subdir: str, name: str) -> SleepConsolidatedQuestion:
    fm = _header(memory_path, subdir, name)
    title = fm.get("question") or fm.get("title")
    return SleepConsolidatedQuestion(
        id=str(fm.get("id") or name[:-3]), title=str(title).strip() if title else None,
        kind=str(fm.get("kind") or "") or None, entity_id=str(fm.get("entity_id") or "") or None,
        status=str(fm.get("status") or "") or None,
    )


def _capped(items: list) -> tuple[list, bool]:
    return items[:CAP], len(items) > CAP


async def build(memory_path: Path, commits: list[str], settles: list[str] | None = None) -> SleepConsolidated:
    """The items of ``commits`` (oldest first), each listed once: a page made in one batch and changed in a later
    one is a new page; a question raised and settled inside the run is listed under both. ``settles`` are Sleep's own
    settle commits during the run (:func:`settle_commits`) — they add only to the questions it settled."""
    episodes: list[str] = []
    created: list[str] = []
    updated: list[str] = []
    raised: list[str] = []
    settled: list[str] = []
    for commit in settles or []:
        for status, path in await changed_files(memory_path, commit):
            if status == "A" and (m := _SETTLED.match(path)) and m.group("name") not in settled:
                settled.append(m.group("name"))
    for commit in commits:
        for status, path in await changed_files(memory_path, commit):
            if status == "D":
                continue
            if m := _EPISODE.match(path):
                if m.group("name") not in episodes:
                    episodes.append(m.group("name"))
            elif m := _ENTITY.match(path):
                eid = m.group("name")
                if status == "A" and eid not in created:
                    created.append(eid)
                    if eid in updated:
                        updated.remove(eid)
                elif status != "A" and eid not in created and eid not in updated:
                    updated.append(eid)
            elif m := _RAISED.match(path):
                if status == "A" and m.group("name") not in raised:
                    raised.append(m.group("name"))
            elif m := _SETTLED.match(path):
                if status == "A" and m.group("name") not in settled:
                    settled.append(m.group("name"))
    conversations = sorted((_conversation(memory_path, n) for n in episodes),
                           key=lambda c: (c.timestamp or "", c.id))
    conv, t1 = _capped(conversations)
    new, t2 = _capped([_page(memory_path, e) for e in created])
    changed, t3 = _capped([_page(memory_path, e) for e in updated])
    # A question raised in the run and settled since lives under settled/ now; read it from wherever it is.
    up, t4 = _capped([_question(memory_path, "inbox" if (Path(memory_path) / "inbox" / n).exists()
                                else "inbox/settled", n) for n in raised])
    down, t5 = _capped([_question(memory_path, "inbox/settled", n) for n in settled])
    return SleepConsolidated(
        commits=list(commits), conversations=conv, created=new, updated=changed,
        questions_raised=up, questions_settled=down,
        counts={"conversations": len(episodes), "created": len(created), "updated": len(updated),
                "questions_raised": len(raised), "questions_settled": len(settled)},
        truncated=any((t1, t2, t3, t4, t5)),
    )


#: Sleep's settles are commits of their own (``inbox_tend``: ``Inbox settled by Sleep (<kind>) <date>``, its own
#: author), made after a batch's commit and once per drain — never inside a batch commit. A run's settles are those
#: subjects inside its window; the grace covers the per-drain tidy that runs after its last batch.
SETTLE_SUBJECT = "Inbox settled by Sleep"
SETTLE_GRACE_S = 300


async def settle_commits(memory_path: Path, start: str | None, end: str | None) -> list[str]:
    """Sleep's settle commits between ``start`` and ``end`` (+ the grace; aware ISO; ``end`` None = now), oldest
    first. ``[]`` with no start or when git cannot answer."""
    if not start:
        return []
    try:
        since = datetime.fromisoformat(start)
        until = datetime.fromisoformat(end) if end else datetime.now(timezone.utc)
    except ValueError:
        return []
    until = until + timedelta(seconds=SETTLE_GRACE_S)
    try:
        out = await git_service._run_git(Path(memory_path), "log", "--reverse", "--format=%H%x1f%s",
                                         f"--since={since.isoformat()}", f"--until={until.isoformat()}")
    except Exception:  # noqa: BLE001 - a list for a dropdown, never worth failing a page
        return []
    commits: list[str] = []
    for line in out.splitlines():
        sha, _, subject = line.partition("\x1f")
        if subject.startswith(SETTLE_SUBJECT) and sha:
            commits.append(sha)
    return commits


def run_window(memory_path: Path, drain_id: str) -> tuple[str | None, str | None]:
    """A run's ``(started_at, finished_at)`` from its summary (``finished_at`` None while it reads or waits)."""
    from api.services import sleep_runs

    summary = sleep_runs.get(memory_path, drain_id) or {}
    return summary.get("started_at"), summary.get("finished_at")


def run_commits(memory_path: Path, drain_id: str) -> list[str]:
    """A run's batch commits, oldest batch first, from its ``sleep_run`` ledger rows (``refs.commit``)."""
    from api.services import cycle_usage, sleep_run_detail, sleep_runs, telemetry

    summary = sleep_runs.get(memory_path, drain_id)
    events = telemetry.read_events(start=sleep_run_detail._ledger_start(summary))
    rows = cycle_usage.Ledger.build(events).runs_by_drain.get(drain_id, [])
    rows = sorted(rows, key=lambda r: int((r.refs or {}).get("batch") or 0))
    out: list[str] = []
    for r in rows:
        commit = str((r.refs or {}).get("commit") or "")
        if re.fullmatch(r"[0-9a-f]{7,40}", commit) and commit not in out:
            out.append(commit)
    return out
