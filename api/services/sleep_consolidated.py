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

items-5 (owner 2026-11-24: "the pages affected per source, if it was an update, creation or deletion"): every page says
what the consolidation did to it (``change``: created / updated / archived / removed) and which of THIS run's
conversations fed it (``episodes``, the intersection of its ``source_episodes`` with the run's own); every conversation
says the pages it fed (``pages``) and the facts the Waiting row carries (``episode_copy.row_facets``). A page is in
exactly one list (removed > archived > created > updated), its final state in the run. Removed is a deleted page file
(its name, type and sources read from its last version in git); archived is a ``status:`` transition to ``archived``
read from the diffs — in the run's own commits, or in the ``(decay)`` commit a batch's ``_finalize`` made just before
its own (:func:`_decay_commit_of`) — never the page's status today, which a later run may have changed.
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
    EpisodeMeetingBrief,
)
from api.services import bank_index, git_service, markdown_parser

#: Folded into the routes' ETag: bump it when the body's shape changes.
#: items-2 (G227): a page row whose title another page shares adds `qualifier` and `displayName`.
#: items-4: a recorder's meetings carry its origin (`queue_origin`). items-3 (owner 2026-11-23): a page row carries the consolidation's commits that changed it (`commits`).
#: items-5 (owner 2026-11-24): pages say `change` and `episodes`, conversations `pages`, `device`, `site`, `meeting`; the body gains `archived` and `removed`.
SHAPE = "items-5"
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
        if status == "R" and len(parts) >= 3:
            # A rename's source is gone: a page merged away beside a similar new one must still read as removed.
            rows.append(("D", parts[1].strip()))
        rows.append(("A" if status == "R" else status, parts[-1].strip()))
    return rows


def _header(memory_path: Path, subdir: str, name: str) -> dict:
    entry = bank_index.file(Path(memory_path), subdir, name)
    return dict(entry.frontmatter or {}) if entry is not None else {}


def _conversation(memory_path: Path, name: str, own_device: str | None = None) -> SleepConsolidatedConversation:
    from api.services import episode_copy
    from api.services.sleep_cycle import queue_origin

    fm = _header(memory_path, "episodes", name)
    facets = episode_copy.row_facets(fm, own_device) if fm else {"site": None, "device": None, "meeting": None}
    return SleepConsolidatedConversation(
        id=str(fm.get("id") or name[:-3]),
        title=(str(fm.get("title")).strip() or None) if fm.get("title") else None,
        origin=queue_origin(fm) if fm else "unknown",
        timestamp=str(fm.get("timestamp")) if fm.get("timestamp") else None,
        device=facets["device"], site=facets["site"],
        meeting=EpisodeMeetingBrief(**facets["meeting"]) if facets["meeting"] else None,
    )


def _sources_of(fm: dict) -> list[str]:
    """The conversations a page's header says fed it (``source_episodes``, the last one merged too)."""
    ids = [str(e) for e in (fm.get("source_episodes") or []) if e]
    last = str(fm.get("source_episode") or "")
    return ids + ([last] if last and last not in ids else [])


def _page(memory_path: Path, entity_id: str, commits: list[str] | None = None, change: str = "updated",
          run_episodes: set[str] | frozenset[str] = frozenset(), last: dict | None = None) -> SleepConsolidatedPage:
    """One page row. ``last`` is a removed page's last version (its header from git): the name, the type and the
    sources come from it, and the row is ``gone`` unless the file is back in the bank."""
    from api.services import same_name

    now = _header(memory_path, "entities", f"{entity_id}.md")
    fm = last if last is not None else now
    name = str(fm.get("name") or "") or None
    q = same_name.qualifier(memory_path, entity_id) if now else None
    return SleepConsolidatedPage(id=entity_id, name=name, type=str(fm.get("type") or "") or None, gone=not now,
                                 qualifier=q, display_name=same_name.display(name, q) if q and name else None,
                                 commits=list(commits or []), change=change,
                                 episodes=[e for e in dict.fromkeys(_sources_of(fm)) if e in run_episodes])


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


#: A batch's ``_finalize`` commits its arithmetic decay (``Sleep cycle <date> (decay)``, authored ``cicada``) FIRST and
#: the main commit right after, with at most the state snapshot between them. The decay commit belongs to the main
#: commit that follows it at once, inside this many seconds — anything else between, or a longer gap, and it is not tied.
DECAY_TIE_S = 600
_STATE_SUBJECT = "State snapshot"


async def _decay_commit_of(memory_path: Path, commit: str) -> str | None:
    """The ``(decay)`` commit a batch commit's ``_finalize`` made just before it, or ``None`` when git cannot say or
    nothing certain ties one: the first commit before ``commit`` that is not a state snapshot must be a ``Sleep cycle
    … (decay)`` commit made no more than ``DECAY_TIE_S`` before it. One git call. A commit another writer made between
    the two leaves the decay commit untied — a page it archived is then not reported, never reported wrongly."""
    try:
        out = await git_service._run_git(Path(memory_path), "log", "--first-parent", "-n", "4",
                                         "--format=%H%x1f%ct%x1f%s", commit)
    except Exception:  # noqa: BLE001 - a list for a dropdown, never worth failing a page
        return None
    rows = [line.split("\x1f", 2) for line in out.splitlines()]
    rows = [r for r in rows if len(r) == 3]
    if not rows or not rows[0][0].startswith(commit):
        return None
    try:
        at = int(rows[0][1])
    except ValueError:
        return None
    for sha, ct, subject in rows[1:]:
        if subject.startswith(_STATE_SUBJECT):
            continue
        if subject.startswith("Sleep cycle") and subject.rstrip().endswith("(decay)"):
            try:
                return sha if 0 <= at - int(ct) <= DECAY_TIE_S else None
            except ValueError:
                return None
        return None
    return None


async def _status_changes(memory_path: Path, commit: str) -> list[tuple[str, str, str]]:
    """``(page id, status before, status after)`` for each page ``commit`` modified with a ``status:`` line change, in
    one git call (``-G`` keeps every other page's diff out of the output; an added page is not a transition)."""
    try:
        out = await git_service._run_git(Path(memory_path), "diff-tree", "--root", "--no-commit-id", "-r", "-p", "-U0",
                                         "--no-color", "--diff-filter=M", "-G^status:", commit, "--", "entities/")
    except Exception:  # noqa: BLE001 - a list for a dropdown, never worth failing a page
        return []
    rows: list[tuple[str, str, str]] = []
    page: str | None = None
    old = new = None

    def flush() -> None:
        if page and old is not None and new is not None and old != new:
            rows.append((page, old, new))

    for line in out.splitlines():
        if line.startswith("diff --git "):
            flush()
            old = new = None
            m = re.search(r" b/entities/(?P<id>[^/]+)\.md$", line)
            page = m.group("id") if m else None
        elif line.startswith("-status:"):
            old = line[len("-status:"):].strip().strip("\"'")
        elif line.startswith("+status:"):
            new = line[len("+status:"):].strip().strip("\"'")
    flush()
    return rows


async def _last_version(memory_path: Path, commit: str, entity_id: str) -> dict:
    """A removed page's header as ``commit`` (the commit that removed it) found it: one ``git show`` of its parent's
    copy. ``{}`` when git cannot say — the row then reads as its id."""
    try:
        text = await git_service._run_git(Path(memory_path), "show", f"{commit}^:entities/{entity_id}.md")
    except Exception:  # noqa: BLE001 - a row's name is never worth failing a page
        return {}
    fm, _turns = markdown_parser.header_of(text)
    return fm if isinstance(fm, dict) else {}


async def build(memory_path: Path, commits: list[str], settles: list[str] | None = None) -> SleepConsolidated:
    """The items of ``commits`` (oldest first), each listed once: a page made in one batch and changed in a later
    one is a new page; a question raised and settled inside the run is listed under both. ``settles`` are Sleep's own
    settle commits during the run (:func:`settle_commits`) — they add only to the questions it settled.

    A page's row is its FINAL state across the commits (removed > archived > created > updated), so the four lists
    never share a page. Cost per run commit: its file list, one ``git log`` to find its decay commit, one diff for
    ``status:`` changes (skipped when it modified no page) and one more for the decay commit; one ``git show`` per
    removed page listed."""
    episodes: list[str] = []
    created: list[str] = []
    updated: list[str] = []
    raised: list[str] = []
    settled: list[str] = []
    #: Page id -> the commit that deleted it, while it stays deleted (a later add of the same id brings it back).
    removed: dict[str, str] = {}
    #: Page id -> whether its last ``status:`` change in the run put it in ``archived`` (a later restore clears it).
    archived: dict[str, bool] = {}
    #: Each page's commits in the consolidation, oldest first: what its "what changed" diff spans.
    touched: dict[str, list[str]] = {}
    for commit in settles or []:
        for status, path in await changed_files(memory_path, commit):
            if status == "A" and (m := _SETTLED.match(path)) and m.group("name") not in settled:
                settled.append(m.group("name"))
    for commit in commits:
        files = await changed_files(memory_path, commit)
        # The batch's decay commit lands first; what it archived is read before the main commit's own changes.
        decay = await _decay_commit_of(memory_path, commit)
        if decay:
            for eid, was, now in await _status_changes(memory_path, decay):
                archived[eid] = now == "archived" and was != "archived"
                touched.setdefault(eid, []).append(decay)
        if any(st == "M" and _ENTITY.match(path) for st, path in files):
            for eid, was, now in await _status_changes(memory_path, commit):
                archived[eid] = now == "archived" and was != "archived"
        for status, path in files:
            if m := _ENTITY.match(path):
                eid = m.group("name")
                if status == "D":
                    removed[eid] = commit
                    touched.setdefault(eid, []).append(commit)
                    continue
                removed.pop(eid, None)
                if touched.get(eid, [None])[-1] != commit:
                    touched.setdefault(eid, []).append(commit)
                if status == "A" and eid not in created:
                    created.append(eid)
                    if eid in updated:
                        updated.remove(eid)
                elif status != "A" and eid not in created and eid not in updated:
                    updated.append(eid)
            elif status == "D":
                continue
            elif m := _EPISODE.match(path):
                if m.group("name") not in episodes:
                    episodes.append(m.group("name"))
            elif m := _RAISED.match(path):
                if status == "A" and m.group("name") not in raised:
                    raised.append(m.group("name"))
            elif m := _SETTLED.match(path):
                if status == "A" and m.group("name") not in settled:
                    settled.append(m.group("name"))
    # One list a page: removed, else archived, else created, else updated. A page the decay commit archived that no
    # batch commit touched is archived without being in `created` or `updated`.
    gone_ids = list(removed)
    shelved = [e for e, on in archived.items() if on and e not in removed]
    made = [e for e in created if e not in removed and e not in shelved]
    changed = [e for e in updated if e not in removed and e not in shelved]
    from api.services import episode_copy

    own_device = episode_copy.own_device_id()
    conversations = sorted((_conversation(memory_path, n, own_device) for n in episodes),
                           key=lambda c: (c.timestamp or "", c.id))
    run_eps = frozenset(c.id for c in conversations)
    made_ids, t2 = _capped(made)
    changed_ids, t3 = _capped(changed)
    shelved_ids, t6 = _capped(shelved)
    rem_ids, t7 = _capped(gone_ids)
    new = [_page(memory_path, e, touched.get(e), "created", run_eps) for e in made_ids]
    chg = [_page(memory_path, e, touched.get(e), "updated", run_eps) for e in changed_ids]
    arch = [_page(memory_path, e, touched.get(e), "archived", run_eps) for e in shelved_ids]
    rem = [_page(memory_path, e, touched.get(e), "removed", run_eps, last=await _last_version(memory_path, removed[e], e))
           for e in rem_ids]
    # Which of the listed pages each conversation fed (never a page the lists cut off, so every id resolves).
    fed: dict[str, list[str]] = {}
    for row in [*new, *chg, *arch, *rem]:
        for ep in row.episodes:
            fed.setdefault(ep, []).append(row.id)
    for c in conversations:
        c.pages = fed.get(c.id, [])
    conv, t1 = _capped(conversations)
    # A question raised in the run and settled since lives under settled/ now; read it from wherever it is.
    up, t4 = _capped([_question(memory_path, "inbox" if (Path(memory_path) / "inbox" / n).exists()
                                else "inbox/settled", n) for n in raised])
    down, t5 = _capped([_question(memory_path, "inbox/settled", n) for n in settled])
    return SleepConsolidated(
        commits=list(commits), conversations=conv, created=new, updated=chg, archived=arch, removed=rem,
        questions_raised=up, questions_settled=down,
        counts={"conversations": len(episodes), "created": len(made), "updated": len(changed),
                "archived": len(shelved), "removed": len(gone_ids),
                "questions_raised": len(raised), "questions_settled": len(settled)},
        truncated=any((t1, t2, t3, t4, t5, t6, t7)),
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
