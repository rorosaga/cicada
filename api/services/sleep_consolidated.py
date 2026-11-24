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

items-6 (owner 2026-11-24: "I don't get why <a page> was modified there, what influenced this change?"): **a count is a
count of real changes.** One run's main commit touched 1,939 entity files, 1,930 of which changed only claim
bookkeeping (the decay watermark; confidence moved on 812 claims: silence). Each page is classified once
(``page_change``, from the commit's patch, never a model; ``commit_changes`` remembers it per commit outside every
bank): ``created`` / ``removed`` (the file), ``archived`` (a ``status:`` move), ``updated`` (substance: a fact, prose, a
frontmatter key a person reads), ``faded`` (confidence moved by silence alone: its own quiet list) or bookkeeping (in no
list; counted in ``counts.bookkeeping``). The page's claims are its fence plus its ledger file. Every row also says
what caused it: the run's conversations that fed it (``episodes``) and the ``steps`` — which of the run's commits changed
it, named from a closed set (``page_change.STEPS``): the batch's own manifest trigger, the ``(decay)`` commit, and the
tail's commits inside the run's window (:func:`window`: a question Sleep settled, a source re-check, a link enrichment,
a short summary, a merge…), never a commit by the person. The closed card's counts are :func:`figures`, the same
survey, so the two cards never disagree.
"""
from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from api.models.schemas import (
    SleepConsolidated,
    SleepConsolidatedConversation,
    SleepConsolidatedPage,
    SleepConsolidatedQuestion,
    EpisodeMeetingBrief,
)
from api.services import bank_index, commit_changes, git_service, markdown_parser, page_change

#: Folded into the routes' ETag: bump it when the body's shape changes.
#: items-2 (G227): a page row whose title another page shares adds `qualifier` and `displayName`.
#: items-4: a recorder's meetings carry its origin (`queue_origin`). items-3 (owner 2026-11-23): a page row carries the consolidation's commits that changed it (`commits`).
#: items-5 (owner 2026-11-24): pages say `change` and `episodes`, conversations `pages`, `device`, `site`, `meeting`; the body gains `archived` and `removed`.
#: items-6 (owner 2026-11-24): a page changed by bookkeeping alone is in no list; `faded` is its own list; every row says its `steps`; the counts are real changes.
SHAPE = "items-6"
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
          run_episodes: set[str] | frozenset[str] = frozenset(), last: dict | None = None,
          steps: list[str] | None = None) -> SleepConsolidatedPage:
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
                                 episodes=[e for e in dict.fromkeys(_sources_of(fm)) if e in run_episodes],
                                 steps=list(steps or []))


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


async def _decay_tie(memory_path: Path, commit: str) -> tuple[bool, str | None]:
    """``(git answered, the tied decay commit)``: the first commit before ``commit`` that is not a state snapshot must
    be a ``Sleep cycle … (decay)`` commit made no more than ``DECAY_TIE_S`` before it. One git call. A commit another
    writer made between the two leaves the decay commit untied — a page it archived is then not reported, never reported
    wrongly. ``(False, None)`` when git cannot say (never remembered)."""
    try:
        out = await git_service._run_git(Path(memory_path), "log", "--first-parent", "-n", "4",
                                         "--format=%H%x1f%ct%x1f%s", commit)
    except Exception:  # noqa: BLE001 - a list for a dropdown, never worth failing a page
        return False, None
    rows = [line.split("\x1f", 2) for line in out.splitlines()]
    rows = [r for r in rows if len(r) == 3]
    if not rows or not rows[0][0].startswith(commit):
        return False, None
    try:
        at = int(rows[0][1])
    except ValueError:
        return False, None
    for sha, ct, subject in rows[1:]:
        if subject.startswith(_STATE_SUBJECT):
            continue
        if subject.startswith("Sleep cycle") and subject.rstrip().endswith("(decay)"):
            try:
                return True, (sha if 0 <= at - int(ct) <= DECAY_TIE_S else None)
            except ValueError:
                return False, None
        return True, None
    return True, None


async def _decay_commit_of(memory_path: Path, commit: str) -> str | None:
    """The ``(decay)`` commit a batch commit's ``_finalize`` made just before it (:func:`_decay_tie`), or ``None``.
    Commits never change, so an answer is remembered with the commit's classification."""
    hit = commit_changes.cache_get(memory_path, commit)
    if hit is not None and "decay" in hit:
        return hit["decay"] or None
    ok, sha = await _decay_tie(memory_path, commit)
    if ok:
        commit_changes.cache_put(memory_path, commit, {**(hit or {}), "decay": sha or ""})
    return sha


async def _last_version(memory_path: Path, commit: str, entity_id: str) -> dict:
    """A removed page's header as ``commit`` (the commit that removed it) found it: one ``git show`` of its parent's
    copy. ``{}`` when git cannot say — the row then reads as its id."""
    try:
        text = await git_service._run_git(Path(memory_path), "show", f"{commit}^:entities/{entity_id}.md")
    except Exception:  # noqa: BLE001 - a row's name is never worth failing a page
        return {}
    fm, _turns = markdown_parser.header_of(text)
    return fm if isinstance(fm, dict) else {}


class Unreadable(Exception):
    """Git could not say what a commit did (a count must not be made from that)."""


async def _commit(memory_path: Path, sha: str, strict: bool = False) -> dict:
    """The classified commit (``commit_changes.classify_commit``); an empty one when git cannot say — or, ``strict``,
    :class:`Unreadable`: a card's count is never made of a commit nobody could read."""
    found = await commit_changes.classify_commit(memory_path, sha)
    if found is None:
        if strict:
            raise Unreadable(sha[:7])
        return {"files": [], "pages": {}, "triggers": {}}
    return found


@dataclass
class Survey:
    """What a run's commits did to the bank, each page once (see :func:`survey`)."""
    episodes: list[str] = field(default_factory=list)
    raised: list[str] = field(default_factory=list)
    settled: list[str] = field(default_factory=list)
    #: Page ids, in the order the run's commits met them, one list each (a page is in exactly one of the six).
    made: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    shelved: list[str] = field(default_factory=list)
    gone: list[str] = field(default_factory=list)
    faded: list[str] = field(default_factory=list)
    bookkeeping: list[str] = field(default_factory=list)
    #: Page id -> the commit that deleted it; -> the commits that touched it, oldest first; -> its steps.
    removed: dict[str, str] = field(default_factory=dict)
    touched: dict[str, list[str]] = field(default_factory=dict)
    steps: dict[str, list[str]] = field(default_factory=dict)
    fade_steps: dict[str, list[str]] = field(default_factory=dict)
    #: Page id -> its first and last file status in the run's commits (``A`` made, ``M`` changed, ``D`` deleted).
    first: dict[str, str] = field(default_factory=dict)
    last: dict[str, str] = field(default_factory=dict)

    def row_steps(self, eid: str, change: str) -> list[str]:
        return list(self.fade_steps.get(eid, []) if change == "faded" else self.steps.get(eid, []))


async def survey(memory_path: Path, commits: list[str], settles: list[str] | None = None,
                 steps: list[tuple[str, str]] | None = None, *, strict: bool = False) -> Survey:
    """The run's commits (``commits``, oldest first; each batch's tied decay commit read just before it) and the tail
    commits inside its window (``steps``: ``(sha, step)``, from :func:`window`) classified and folded: every page is in
    exactly one list, its FINAL state in the run (removed > archived > created > updated > faded > bookkeeping), with
    the commits that touched it and the steps that changed it. ``settles`` add only to the questions Sleep settled.

    Cost per run commit when its answer is not remembered: its file list, one patch, one ``git log`` for its decay tie
    and the same two for that decay commit; one ``git show`` per removed page listed (the build's). Remembered, none."""
    sv = Survey()
    plan: list[tuple[str, str, str | None]] = []
    for sha in commits:
        decay = await _decay_commit_of(memory_path, sha)
        if decay:
            plan.append((decay, "decay", "decay"))
        plan.append((sha, "batch", None))
    plan.extend((sha, "step", step) for sha, step in steps or [])
    archived: dict[str, bool] = {}
    made: list[str] = []
    changed: list[str] = []
    faded: dict[str, None] = {}
    seen: dict[str, None] = {}

    def add_step(table: dict[str, list[str]], eid: str, step: str) -> None:
        row = table.setdefault(eid, [])
        if step not in row:
            row.append(step)

    for sha in settles or []:
        for status, path in (await _commit(memory_path, sha, strict))["files"]:
            if status == "A" and (m := _SETTLED.match(path)) and m.group("name") not in sv.settled:
                sv.settled.append(m.group("name"))
    for sha, who, named in plan:
        cc = await _commit(memory_path, sha, strict)
        pages, triggers = cc.get("pages") or {}, cc.get("triggers") or {}

        def step_of(eid: str) -> str:
            # A decay commit and a tail commit are named by what they are; a batch's page by its manifest trigger.
            return named if named else page_change.step_for_trigger(triggers.get(eid))

        def touch(eid: str, status: str) -> None:
            row = sv.touched.setdefault(eid, [])
            if row[-1:] != [sha]:
                row.append(sha)
            sv.first.setdefault(eid, status)
            sv.last[eid] = status
            seen.setdefault(eid)

        # A page's `status:` move in this commit (the decay commit's and the batch's own), read from the patch.
        for eid, verdict in pages.items():
            was, now = verdict[1], verdict[2]
            if was is not None or now is not None:
                if was != now:
                    archived[eid] = now == "archived" and was != "archived"
                    if archived[eid]:
                        add_step(sv.steps, eid, step_of(eid))

        def note(eid: str, kind: str) -> None:
            if kind == page_change.SUBSTANCE:
                if eid not in made and eid not in changed:
                    changed.append(eid)
                add_step(sv.steps, eid, step_of(eid))
            elif kind == page_change.FADE:
                # Silence is the cause of a fade, whatever the commit's manifest says: claim-level decay is written
                # back with a generic trigger (`sleep/extraction`), which would read as "changed while Sleep read".
                faded.setdefault(eid)
                add_step(sv.fade_steps, eid, "decay")

        md_seen: set[str] = set()
        for status, path in cc["files"]:
            if m := _ENTITY.match(path):
                eid = m.group("name")
                md_seen.add(eid)
                if status == "D":
                    sv.removed[eid] = sha
                    touch(eid, "D")
                    add_step(sv.steps, eid, step_of(eid))
                    continue
                sv.removed.pop(eid, None)
                if status == "A":
                    touch(eid, "A")
                    if eid not in made:
                        made.append(eid)
                        if eid in changed:
                            changed.remove(eid)
                    add_step(sv.steps, eid, step_of(eid))
                else:
                    touch(eid, "M")
                    note(eid, (pages.get(eid) or [page_change.SUBSTANCE])[0])
            elif who != "batch" or status == "D":
                continue
            elif m := _EPISODE.match(path):
                if m.group("name") not in sv.episodes:
                    sv.episodes.append(m.group("name"))
            elif m := _RAISED.match(path):
                if status == "A" and m.group("name") not in sv.raised:
                    sv.raised.append(m.group("name"))
            elif m := _SETTLED.match(path):
                if status == "A" and m.group("name") not in sv.settled:
                    sv.settled.append(m.group("name"))
        for eid, verdict in pages.items():   # a page whose only change was in its ledger file
            if eid not in md_seen:
                touch(eid, "M")
                note(eid, verdict[0])
    # One list a page: removed, else archived, else created, else updated, else faded, else bookkeeping. A page the
    # decay commit archived that no batch commit touched is archived without being in `made` or `changed`.
    sv.gone = list(sv.removed)
    sv.shelved = [e for e, on in archived.items() if on and e not in sv.removed]
    sv.made = [e for e in made if e not in sv.removed and e not in sv.shelved]
    placed = set(sv.gone) | set(sv.shelved) | set(sv.made)
    sv.changed = [e for e in changed if e not in placed]
    placed |= set(sv.changed)
    sv.faded = [e for e in faded if e not in placed]
    placed |= set(sv.faded)
    sv.bookkeeping = [e for e in seen if e not in placed]
    return sv


def change_of(sv: Survey, eid: str) -> str | None:
    """The page's final class in the run — ``removed``, ``archived``, ``created``, ``updated``, ``faded`` or
    ``bookkeeping`` — or ``None`` when no commit of the run touched it."""
    for name, ids in (("removed", sv.gone), ("archived", sv.shelved), ("created", sv.made), ("updated", sv.changed),
                      ("faded", sv.faded), ("bookkeeping", sv.bookkeeping)):
        if eid in ids:
            return name
    return None


def _counts(sv: Survey) -> dict[str, int]:
    return {"created": len(sv.made), "updated": len(sv.changed), "archived": len(sv.shelved),
            "removed": len(sv.gone), "faded": len(sv.faded), "bookkeeping": len(sv.bookkeeping)}


async def build(memory_path: Path, commits: list[str], settles: list[str] | None = None,
                steps: list[tuple[str, str]] | None = None) -> SleepConsolidated:
    """The items of ``commits`` (oldest first), each listed once: a page made in one batch and changed in a later
    one is a new page; a question raised and settled inside the run is listed under both. ``settles`` are Sleep's own
    settle commits during the run (:func:`window`) — they add to the questions it settled — and ``steps`` the tail
    commits that changed pages (``(sha, step)``).

    A page's row is its FINAL state across the commits (:func:`survey`), so the five lists never share a page, and a
    page with only bookkeeping changed is in none. Cost per run commit: see :func:`survey`; one ``git show`` per removed
    page listed."""
    sv = await survey(memory_path, commits, settles, steps)
    from api.services import episode_copy

    own_device = episode_copy.own_device_id()
    conversations = sorted((_conversation(memory_path, n, own_device) for n in sv.episodes),
                           key=lambda c: (c.timestamp or "", c.id))
    run_eps = frozenset(c.id for c in conversations)
    made_ids, t2 = _capped(sv.made)
    changed_ids, t3 = _capped(sv.changed)
    shelved_ids, t6 = _capped(sv.shelved)
    rem_ids, t7 = _capped(sv.gone)
    faded_ids, t8 = _capped(sv.faded)

    def row(eid: str, change: str, **more) -> SleepConsolidatedPage:
        return _page(memory_path, eid, sv.touched.get(eid), change, run_eps, steps=sv.row_steps(eid, change), **more)

    new = [row(e, "created") for e in made_ids]
    chg = [row(e, "updated") for e in changed_ids]
    arch = [row(e, "archived") for e in shelved_ids]
    rem = [row(e, "removed", last=await _last_version(memory_path, sv.removed[e], e)) for e in rem_ids]
    fad = [row(e, "faded") for e in faded_ids]
    # Which of the listed pages each conversation fed (never a page the lists cut off, so every id resolves).
    fed: dict[str, list[str]] = {}
    for r in [*new, *chg, *arch, *rem]:
        for ep in r.episodes:
            fed.setdefault(ep, []).append(r.id)
    for c in conversations:
        c.pages = fed.get(c.id, [])
    conv, t1 = _capped(conversations)
    # A question raised in the run and settled since lives under settled/ now; read it from wherever it is.
    up, t4 = _capped([_question(memory_path, "inbox" if (Path(memory_path) / "inbox" / n).exists()
                                else "inbox/settled", n) for n in sv.raised])
    down, t5 = _capped([_question(memory_path, "inbox/settled", n) for n in sv.settled])
    return SleepConsolidated(
        commits=list(commits), conversations=conv, created=new, updated=chg, archived=arch, removed=rem, faded=fad,
        questions_raised=up, questions_settled=down,
        counts={"conversations": len(sv.episodes), **_counts(sv),
                "questions_raised": len(sv.raised), "questions_settled": len(sv.settled)},
        truncated=any((t1, t2, t3, t4, t5, t6, t7, t8)),
    )


# --------------------------------------------------------------------------------------------------------------------
# The window: Sleep's own commits after a batch (settles, and the tail's page-changing steps)
# --------------------------------------------------------------------------------------------------------------------

#: Sleep's settles are commits of their own (``inbox_tend``: ``Inbox settled by Sleep (<kind>) <date>``, its own
#: author), made after a batch's commit and once per drain — never inside a batch commit. A run's settles are those
#: subjects inside its window; the grace covers the per-drain tidy that runs after its last batch.
SETTLE_SUBJECT = "Inbox settled by Sleep"
SETTLE_GRACE_S = 300
#: A window older than this past its end can no longer gain a commit: its answer is remembered.
WINDOW_FINAL_S = 900


def _final(end: str | None) -> bool:
    if not end:
        return False
    try:
        at = datetime.fromisoformat(end)
    except ValueError:
        return False
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - at).total_seconds() > SETTLE_GRACE_S + WINDOW_FINAL_S


def _key(*parts) -> str:
    return hashlib.sha1("\x1f".join(str(p) for p in parts).encode()).hexdigest()[:20]


def _is_sleeps(authors: str) -> bool:
    """Was this commit written by Cicada's own machinery — every ``Cicada-Author`` is ``cicada`` or a model (never the
    person, an agent harness, nobody)? A subject alone proves nothing: the person's own merge reads like Sleep's."""
    names = [a.strip() for a in authors.split(",") if a.strip()]
    return bool(names) and all(git_service.author_identity(a)[0] in ("system", "model") for a in names)


async def window(memory_path: Path, start: str | None, end: str | None) -> tuple[list[str], list[tuple[str, str]]]:
    """``(settles, steps)`` between ``start`` and ``end`` (+ the grace; aware ISO; ``end`` None = now), oldest first:
    Sleep's settle commits, and every tail commit whose subject names a step that changes pages already on the record
    (:data:`page_change._SUBJECT_STEP`: a settle, a merge, a source re-check, a link enrichment, a short summary…) as
    ``(sha, step)`` — never a commit the person or an agent harness wrote (its ``Cicada-Author``), whatever its subject. ``([], [])`` with no
    start or when git cannot answer. A finished window is remembered."""
    if not start:
        return [], []
    cache_key = f"window-{_key(start, end)}"
    if _final(end):
        hit = commit_changes.cache_get(memory_path, cache_key)
        if hit is not None and "steps" in hit:
            return list(hit.get("settles") or []), [(s, t) for s, t in hit["steps"]]
    try:
        since = datetime.fromisoformat(start)
        until = datetime.fromisoformat(end) if end else datetime.now(timezone.utc)
    except ValueError:
        return [], []
    until = until + timedelta(seconds=SETTLE_GRACE_S)
    try:
        out = await git_service._run_git(
            Path(memory_path), "log", "--reverse", "--format=%H%x1f%s%x1f%(trailers:key=Cicada-Author,valueonly=true,separator=%x2c)",
            f"--since={since.isoformat()}", f"--until={until.isoformat()}")
    except Exception:  # noqa: BLE001 - a list for a dropdown, never worth failing a page
        return [], []
    settles: list[str] = []
    steps: list[tuple[str, str]] = []
    for line in out.splitlines():
        sha, _, rest = line.partition("\x1f")
        subject, _, authors = rest.partition("\x1f")
        if not sha:
            continue
        if subject.startswith(SETTLE_SUBJECT):
            settles.append(sha)
        step = page_change.step_for_subject(subject)
        if step is not None and _is_sleeps(authors):
            steps.append((sha, step))
    if _final(end):
        commit_changes.cache_put(memory_path, cache_key, {"settles": settles, "steps": [[s, t] for s, t in steps]})
    return settles, steps


async def settle_commits(memory_path: Path, start: str | None, end: str | None) -> list[str]:
    """Sleep's settle commits between ``start`` and ``end`` (:func:`window`), oldest first."""
    return (await window(memory_path, start, end))[0]


def cycle_window(date: str, duration_ms: int | None) -> tuple[str | None, str | None]:
    """A plain cycle's window: from when it began reading (its commit less its duration) to its commit."""
    try:
        end_at = datetime.fromisoformat(date)
    except ValueError:
        return None, None
    return (end_at - timedelta(milliseconds=duration_ms or 0)).isoformat(), end_at.isoformat()


# --------------------------------------------------------------------------------------------------------------------
# The closed card: the same survey, counted
# --------------------------------------------------------------------------------------------------------------------

FIGURE_KEYS = ("created", "updated", "archived", "removed", "faded")


async def figures(memory_path: Path, commits: list[str], start: str | None = None, end: str | None = None,
                  *, tail: bool = True) -> dict[str, int]:
    """``{created, updated, archived, removed, faded}`` for ``commits`` and (``tail``) their window — exactly the
    opened card's counts (:func:`build` counts the same :func:`survey`). A finished run's figures are remembered."""
    cache_key = f"figures-{_key(','.join(commits), start, end, tail)}"
    final = _final(end)
    if final:
        hit = commit_changes.cache_get(memory_path, cache_key)
        if hit is not None and all(k in hit for k in FIGURE_KEYS):
            return {k: int(hit[k]) for k in FIGURE_KEYS}
    settles, steps = await window(memory_path, start, end) if tail else ([], [])
    counts = _counts(await survey(memory_path, commits, settles, steps, strict=True))
    out = {k: counts[k] for k in FIGURE_KEYS}
    if final:
        commit_changes.cache_put(memory_path, cache_key, out)
    return out


async def apply_figures(memory_path: Path, entries: list, run_commit_ids: dict[str, list[str]]) -> None:
    """Make every history entry's page counts the opened card's (owner 2026-11-24): a plain cycle's
    ``entities_created`` / ``entities_updated`` (and archived, removed, faded) and a run's ``run.created`` /
    ``run.updated`` are :func:`figures` — pages really changed, never the manifest's file lines (a decay stamp is not an
    update) and never Stage 2's resolver tally. ``run_commit_ids`` is each run's batch commits from the ledger.
    Concurrent and bounded; an answer git cannot give leaves the entry's own number."""
    gate = asyncio.Semaphore(3)
    shared: dict[tuple, asyncio.Task] = {}

    def once(commits: list[str], start, end, tail: bool) -> asyncio.Task:
        """The batches of one run share one whole-run survey, started once."""
        key = (tuple(commits), start, end, tail)
        if key not in shared:
            shared[key] = asyncio.ensure_future(figures(memory_path, commits, start, end, tail=tail))
        return shared[key]

    async def one(entry) -> None:
        if getattr(entry, "kind", "sleep") != "sleep":
            return
        run = entry.run
        try:
            async with gate:
                if run is not None and run_commit_ids.get(run.id):
                    start, end = run.started_at, run.finished_at
                    entry_fig = await once([entry.commit_hash], None, None, False)
                    run_fig = await once(run_commit_ids[run.id], start, end, True)
                else:
                    start, end = cycle_window(entry.date, entry.duration_ms)
                    entry_fig = run_fig = await once([entry.commit_hash], start, end, True)
        except Exception as exc:  # noqa: BLE001 - a number on a card is never worth failing the list
            from loguru import logger

            logger.warning(f"sleep figures skipped: {type(exc).__name__}")
            return
        entry.entities_created, entry.entities_updated = entry_fig["created"], entry_fig["updated"]
        entry.entities_archived, entry.entities_removed = entry_fig["archived"], entry_fig["removed"]
        entry.entities_faded = entry_fig["faded"]
        if run is not None and run_commit_ids.get(run.id):
            run.created, run.updated = run_fig["created"], run_fig["updated"]
            run.archived, run.removed, run.faded = run_fig["archived"], run_fig["removed"], run_fig["faded"]

    await asyncio.gather(*(one(e) for e in entries))


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
