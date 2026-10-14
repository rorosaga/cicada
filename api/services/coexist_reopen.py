"""Reopen the places a single-valued close ended only because another place was mentioned (2026-10-14) — dry run first.

Until 2026-10-14 ``works-at`` was single-valued: Stage 3 closed the open ``works-at`` belief whenever one with a different
object arrived (``claim_reconciler._place_claim`` → ``_close``). A person holds more than one place at once, so their
jobs kept ending each other — one measured owner page held 26 ``works-at`` claims, 25 closed, flipping between six
places 1–60 days apart. The vocabulary now lets places coexist (``predicates-seed.yaml``); this puts back, as current, a
belief that the old rule closed and nothing else did.

**What reopens — every check must pass; when in doubt, history** (the G148 reopen rule). A closed claim on a predicate in
:data:`PREDICATES` whose ``superseded_by`` names a claim on the same page that:

* has the same predicate, observer and context, a **different** object, and ``supersedes`` it back — the reconciler's
  close, and ``valid_to`` is that successor's ``valid_from`` exactly (``_close``'s date; an inbox answer closes on the
  day it was given, an ending on the day it was said, with the same object);
* and neither claim is the person's own (``is_human``): the person choosing one place over another is a verdict.

and the commit that closed it is a ``Sleep cycle`` commit written only by models or ``cicada``
(``claim_recovery._classify_commit``) — found by bisecting the page's own history (page and its claims ledger, when it
has one) for the first version that carries the close. **Stays closed**, counted by reason: a recovered entry
(``claims.is_recovered_history``), a withdrawn one, a close with no successor (a stated end, a person's edit, expiry), a
successor that is missing, the same object (an ending), another predicate or slot, a close whose date or link is not
the reconciler's, the person's word, a stated end already past, a claim whose own words are in the past tense or an
ending ("worked at", "left" — ``endings`` in the seed), a page that also says the person left that place, a close by
any other writer, an unprovable close, a place already current under the same slot, and every older closed copy of the
same place (the newest one reopens; the rest stay as the history they are). ``--said-since`` keeps closed, as
``said_before_cutoff``, a place last said before that day. **The CLI defaults it to 180 days ago** (``--all`` lifts
it): a place closed once by a new job and never said again passes every check above, and is a real job change as
often as not — so by default only recently said places come back, and the dry run counts the rest by age.

**Dry run (default)** prints counts only — by reason, and the places it would reopen by when they were last said;
``--plan`` writes ids, page paths, commits and reasons, never claim text. **``--apply``** refuses unless Sleep is idle
(the bank's write admission held, Sleep asked once it is held, and the backend's ``/sleep/status`` must answer a clear
``writing: false`` — ``claim_recovery.backend_sleep_holding``), then takes the page lock and git's write lock, re-reads
under them, skips a dirty or unreadable page, and writes each page through the one claims writer
(``markdown_parser.parse`` → ``write_claims`` → ``markdown_parser.write``): ``valid_to`` and ``superseded_by`` cleared
on the reopened claim, the successor's ``supersedes`` cleared when it named it. Nothing is deleted; git holds the
close. One ``Reopen coexisting places <date>`` commit of only the pages written, ``Cicada-Author: cicada``, put back
from HEAD on a failure. A re-run finds nothing.

    python -m api.services.coexist_reopen --bank <path> [--plan <file>] [--said-since YYYY-MM-DD | --all] [--apply]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

from api.services import claim_recovery, git_service, markdown_parser, page_lock, predicates, write_admission
from api.services.claim_reconciler import _said, is_human, same_object
from api.services.claims import (
    Claim,
    MalformedClaimsBlockError,
    is_event,
    is_record,
    is_recovered_history,
    parse_claims,
    stated_end,
    write_claims,
)

TRIGGER = "maintenance/coexist-reopen"
AUTHOR = git_service.CICADA_AUTHOR
SUBJECT = "Reopen coexisting places"
#: The predicates this repair reopens: the ones 2026-10-14 moved from single- to multi-valued.
PREDICATES = ("works-at",)
LEDGER_SUFFIX = ".claims.jsonl"
_GONE = frozenset({"archived", "dropped"})
_AGE_BUCKETS = ((30, "said within 30 days"), (90, "said within 90 days"), (180, "said within 180 days"),
                (365, "said within a year"))
#: The CLI's default window: a place closed once by a new job and never said again is a real job change the old rule
#: happened to get right, and nothing on the page tells the two apart — so by default only places said in the last
#: 180 days come back; `--all` lifts it, after reading the dry run's age groups (review 2026-10-14).
DEFAULT_WINDOW_DAYS = 180


class NotAGitBank(ValueError):
    """The path is not a git-versioned bank: there is no history to prove a close from."""


SleepIsWriting = claim_recovery.SleepIsWriting


@dataclass
class Item:
    page: str
    claim_id: str
    reason: str                    # "reopen" or why it stays closed
    successor: str | None = None
    commit: str | None = None
    said: str | None = None

    def to_dict(self) -> dict:
        return {"page": self.page, "claim_id": self.claim_id, "reason": self.reason, "successor": self.successor,
                "commit": self.commit, "said": self.said}


@dataclass
class Plan:
    head: str
    items: list[Item] = field(default_factory=list)
    pages_skipped: dict[str, int] = field(default_factory=dict)

    @property
    def reopen(self) -> list[Item]:
        return [i for i in self.items if i.reason == "reopen"]

    def counts(self, today: date | None = None) -> dict:
        today = today or date.today()
        kept: dict[str, int] = {}
        for i in self.items:
            if i.reason != "reopen":
                kept[i.reason] = kept.get(i.reason, 0) + 1
        ages: dict[str, int] = {}
        for i in self.reopen:
            ages[_bucket(i.said, today)] = ages.get(_bucket(i.said, today), 0) + 1
        cut: dict[str, int] = {}
        for i in self.items:
            if i.reason == "said_before_cutoff":
                cut[_bucket(i.said, today)] = cut.get(_bucket(i.said, today), 0) + 1
        return {"closed_candidates": len(self.items), "reopen": len(self.reopen),
                "pages": len({i.page for i in self.reopen}), "kept_closed": dict(sorted(kept.items())),
                "reopen_by_last_said": _ordered(ages), "cutoff_by_last_said": _ordered(cut),
                "pages_skipped": dict(sorted(self.pages_skipped.items()))}

    def to_dict(self) -> dict:
        return {"head": self.head, "items": [i.to_dict() for i in self.items], "pages_skipped": self.pages_skipped}


def _ordered(counts: dict[str, int]) -> dict[str, int]:
    order = [label for _, label in _AGE_BUCKETS] + ["said more than a year ago", "said on no dated conversation"]
    return {k: counts[k] for k in order if k in counts}


def _bucket(said: str | None, today: date) -> str:
    try:
        days = (today - date.fromisoformat(str(said)[:10])).days
    except (TypeError, ValueError):
        return "said on no dated conversation"
    for limit, label in _AGE_BUCKETS:
        if days <= limit:
            return label
    return "said more than a year ago"


# --- reading -----------------------------------------------------------------------------------------------------


def _ledger_rel(page: str) -> str:
    return page[: -len(".md")] + LEDGER_SUFFIX


def _version_claims(blobs: claim_recovery._Blobs, rev: str, page: str) -> dict[str, dict] | None:
    """Every claim entry a page held at ``rev`` — its fence, plus its claims ledger when it has one (the fence's copy
    wins) — by id; ``None`` when the page is absent or its fence unreadable."""
    version = claim_recovery._version(blobs.read(rev, page))
    if version is None or version.entries is None:
        return None
    out: dict[str, dict] = {}
    held = blobs.read(rev, _ledger_rel(page))
    for line in (held or "").split("\n"):
        try:
            entry = json.loads(line) if line.strip() else None
        except ValueError:
            continue
        if isinstance(entry, dict) and entry.get("id") is not None:
            out[str(entry["id"])] = entry
    for entry in version.entries:
        if entry.get("id") is not None:
            out[str(entry["id"])] = entry
    return out


def _page_commits(bank: Path, page: str) -> list[claim_recovery._Commit]:
    """The first-parent commits that touched the page or its ledger, oldest first."""
    out = claim_recovery._git_read(
        bank, "log", "--first-parent", "--reverse", "--no-renames",
        "--format=%x1e%H%x1f%cI%x1f%s%x1f%(trailers:key=Cicada-Author,valueonly,separator=%x2C)",
        "--", page, _ledger_rel(page))
    commits = []
    for index, record in enumerate(r for r in out.split("\x1e") if r.strip()):
        head = record.strip("\n").split("\n", 1)[0]
        sha, when, subject, authors = (head.split("\x1f") + ["", "", ""])[:4]
        commits.append(claim_recovery._Commit(index, sha, when[:10], subject,
                                              [a.strip() for a in authors.split(",") if a.strip()], []))
    return commits


class _History:
    """A page's history, read lazily: each version once, however many candidates bisect it."""

    def __init__(self, bank: Path, blobs: claim_recovery._Blobs, page: str) -> None:
        self.bank, self.blobs, self.page = bank, blobs, page
        self._commits: list[claim_recovery._Commit] | None = None
        self._versions: dict[int, dict[str, dict] | None] = {}

    @property
    def commits(self) -> list[claim_recovery._Commit]:
        if self._commits is None:
            self._commits = _page_commits(self.bank, self.page)
        return self._commits

    def at(self, index: int) -> dict[str, dict] | None:
        if index not in self._versions:
            self._versions[index] = _version_claims(self.blobs, self.commits[index].sha, self.page)
        return self._versions[index]

    def closing_commit(self, claim: Claim) -> claim_recovery._Commit | None:
        """The first commit whose version carries this close (``valid_to`` and ``superseded_by`` as now), by
        bisection; ``None`` when HEAD's version does not carry it (uncommitted) or the page has no history."""
        def closed(index: int) -> bool:
            entry = (self.at(index) or {}).get(claim.id)
            return bool(entry) and str(entry.get("superseded_by") or "") == claim.superseded_by \
                and str(entry.get("valid_to") or "")[:10] == str(claim.valid_to)[:10]

        n = len(self.commits)
        if n == 0 or not closed(n - 1):
            return None
        lo, hi = 0, n - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if closed(mid):
                hi = mid
            else:
                lo = mid + 1
        return self.commits[lo]


# --- the plan ----------------------------------------------------------------------------------------------------


def _slug(text: str) -> str:
    return "-" + predicates._slugify_predicate(text) + "-"


def _ending_labels(memory_path: Path, predicate: str) -> tuple[set[str], set[str]]:
    """The seed's and the bank's ending labels for ``predicate``, slugged: (over, every)."""
    over: set[str] = set()
    every: set[str] = set()
    for data in (predicates._load_seed_map(), predicates._read_runtime_map(memory_path)):
        modes = ((data.get("endings") or {}) if isinstance(data, dict) else {}).get(predicate) or {}
        if not isinstance(modes, dict):
            continue
        for mode in (predicates.ENDING_OVER, predicates.ENDING_PAST):
            for label in modes.get(mode) or []:
                slug = predicates._slugify_predicate(str(label))
                if slug:
                    every.add(slug)
                    if mode == predicates.ENDING_OVER:
                        over.add(slug)
    return over, every


def _says(text: str, labels: set[str]) -> bool:
    words = _slug(text)
    return any(f"-{label}-" in words for label in labels)


def _head(bank: Path) -> str:
    try:
        return claim_recovery._head(bank)
    except git_service.GitError:
        return ""


def analyze(bank, *, today: date | None = None, said_since: str | None = None) -> Plan:
    """Classify every closed claim on :data:`PREDICATES`. Reads only; writes nothing."""
    bank = Path(bank)
    if not (bank / ".git").exists():
        raise NotAGitBank(str(bank))
    today = today or date.today()
    plan = Plan(head=_head(bank))
    single = predicates.build_cardinality_fn(bank)
    labels = {p: _ending_labels(bank, p) for p in PREDICATES}
    blobs = claim_recovery._Blobs(bank)
    try:
        for path in sorted((bank / "entities").glob("*.md")):
            rel = f"entities/{path.name}"
            try:
                parsed = markdown_parser.parse(path)
                page_claims = parse_claims(parsed.body, strict=True)
            except (OSError, ValueError, MalformedClaimsBlockError):
                plan.pages_skipped["unreadable"] = plan.pages_skipped.get("unreadable", 0) + 1
                continue
            candidates = [c for c in page_claims if c.predicate in PREDICATES and c.valid_to
                          and not is_event(c) and not is_record(c)]
            if not candidates:
                continue
            if str((parsed.frontmatter or {}).get("status") or "").lower() in _GONE:
                plan.pages_skipped["page_archived"] = plan.pages_skipped.get("page_archived", 0) + 1
                continue
            items = _classify_page(bank, blobs, rel, page_claims, candidates, single, labels, today, said_since)
            plan.items.extend(items)
    finally:
        blobs.close()
    return plan


def _classify_page(bank: Path, blobs, rel: str, page_claims: list[Claim], candidates: list[Claim], single,
                   labels: dict, today: date, said_since: str | None) -> list[Item]:
    by_id = {c.id: c for c in page_claims}
    history = _History(bank, blobs, rel)
    eligible: list[tuple[Item, Claim]] = []
    items: list[Item] = []
    for c in candidates:
        item = Item(rel, c.id, "", successor=c.superseded_by, said=_said(c) or c.valid_from)
        item.reason = _reason(c, by_id, page_claims, single, labels[c.predicate], today, said_since)
        if not item.reason:
            commit = history.closing_commit(c)
            if commit is None:
                item.reason = "unproven_close"
            else:
                item.commit = commit.sha
                item.reason = claim_recovery._classify_commit(commit) or ""
        items.append(item)
        if not item.reason:
            eligible.append((item, c))
    # One reopened belief per (slot, place): the newest close; an older copy is the history it is, and a place
    # already current stays as it is.
    groups: dict[tuple, list[tuple[Item, Claim]]] = {}
    for item, c in eligible:
        groups.setdefault((c.predicate, c.context, c.observer, " ".join(c.object.lower().split())), []).append((item, c))
    for (pred, ctx, obs, _obj), members in groups.items():
        current = any(o.valid_to is None and o.predicate == pred and o.context == ctx and o.observer == obs
                      and same_object(o, members[0][1]) for o in page_claims)
        members.sort(key=lambda m: (str(m[1].valid_to or ""), str(m[1].valid_from or ""), m[1].id), reverse=True)
        for rank, (item, _c) in enumerate(members):
            item.reason = "already_current" if current else ("reopen" if rank == 0 else "older_copy")
    return items


def _reason(c: Claim, by_id: dict[str, Claim], page_claims: list[Claim], single: Callable[[str], bool],
            labels: tuple[set[str], set[str]], today: date, said_since: str | None) -> str:
    """Why this closed claim stays closed, or ``""`` when everything on the page says the old rule alone closed it."""
    over, every = labels
    if single(c.predicate):
        return "still_single_valued"     # the bank's vocabulary would close it again on the next Sleep
    if is_recovered_history(c):
        return "recovered_history"
    if not c.superseded_by:
        return "no_successor"
    s = by_id.get(c.superseded_by)
    if s is None:
        return "successor_missing"
    if is_record(s):
        return "withdrawn"
    if s.predicate != c.predicate:
        return "other_predicate"
    if same_object(s, c):
        return "ended"
    if (s.context, s.observer) != (c.context, c.observer):
        return "other_slot"
    if s.supersedes != c.id or str(c.valid_to)[:10] != str(s.valid_from or "")[:10]:
        return "not_a_reconciler_close"
    if is_human(c) or is_human(s):
        return "persons_word"
    end = stated_end(c)
    if end and end[:10] <= today.isoformat():
        return "stated_end"
    if _says(c.text, every):
        return "said_past"
    for o in page_claims:
        if o is c or not same_object(o, c):
            continue
        ending = o.predicate != c.predicate and predicates._slugify_predicate(o.predicate) in over
        if ending or (o.predicate == c.predicate and _says(o.text, over)):
            return "departure_stated"
    said = _said(c) or c.valid_from
    if said_since and (not said or str(said)[:10] < said_since):
        return "said_before_cutoff"
    return ""


# --- apply -------------------------------------------------------------------------------------------------------


@dataclass
class ApplyResult:
    plan: Plan | None = None
    pages: list[str] = field(default_factory=list)
    reopened: int = 0
    skipped_dirty: list[str] = field(default_factory=list)
    skipped_unreadable: list[str] = field(default_factory=list)
    commit: str | None = None


def commit_message(lines: dict[str, int], today: date) -> str:
    return git_service.build_commit_message(
        f"{SUBJECT} {today.isoformat()}",
        [f"{rel}: updated (reopened: {n}, trigger: {TRIGGER})" for rel, n in sorted(lines.items())],
        authors=[AUTHOR],
    )


def apply(bank, *, sleep_holding: Callable[[], bool] | None = None, today: date | None = None,
          said_since: str | None = None) -> ApplyResult:
    """Reopen every ``reopen`` item and commit the pages written, alone, as ``cicada``. Admission first, Sleep asked
    once it is held, then the page lock, then git's write lock (G183's order); the plan is re-made under them."""
    bank = Path(bank)
    if not (bank / ".git").exists():
        raise NotAGitBank(str(bank))
    holding = sleep_holding or write_admission.holding
    today = today or date.today()
    with write_admission.shared(bank):
        if holding():
            raise SleepIsWriting(str(bank))
        with page_lock.page_lock(bank), git_service.write_lock(bank):
            plan = analyze(bank, today=today, said_since=said_since)
            return _apply_locked(bank, plan, today)


def _apply_locked(bank: Path, plan: Plan, today: date) -> ApplyResult:
    result = ApplyResult(plan=plan)
    by_page: dict[str, list[Item]] = {}
    for item in plan.reopen:
        by_page.setdefault(item.page, []).append(item)
    if not by_page:
        return result
    dirty = git_service.dirty_paths_sync(bank, *by_page, *(_ledger_rel(p) for p in by_page))
    written: dict[str, int] = {}
    try:
        for rel, items in sorted(by_page.items()):
            if rel in dirty or _ledger_rel(rel) in dirty:
                result.skipped_dirty.append(rel)
                continue
            path = bank / rel
            try:
                parsed = markdown_parser.parse(path)
                page_claims = parse_claims(parsed.body, strict=True)
            except (OSError, ValueError, MalformedClaimsBlockError):
                result.skipped_unreadable.append(rel)
                continue
            by_id = {c.id: c for c in page_claims}
            n = 0
            for item in items:
                c = by_id.get(item.claim_id)
                if c is None or c.valid_to is None or is_recovered_history(c):
                    continue
                successor = by_id.get(c.superseded_by or "")
                c.valid_to = None
                c.superseded_by = None
                if successor is not None and successor.supersedes == c.id:
                    successor.supersedes = None
                n += 1
            if not n:
                continue
            markdown_parser.write(path, parsed.frontmatter, write_claims(parsed.body, page_claims))
            written[rel] = n
        if written:
            git_service.commit_paths_sync(bank, commit_message(written, today), sorted(written))
            result.commit = claim_recovery._head(bank)
    except BaseException:
        if written:
            # Every page written was clean at HEAD, so HEAD is exactly what was there.
            git_service.run_git_write_sync(bank, "checkout", "HEAD", "--", *sorted(written))
        raise
    result.pages = sorted(written)
    result.reopened = sum(written.values())
    return result


# --- CLI ---------------------------------------------------------------------------------------------------------


_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _print_counts(plan: Plan, said_since: str | None) -> None:
    counts = plan.counts()
    print(f"closed {', '.join(PREDICATES)} claims read: {counts['closed_candidates']}")
    print(f"window: {'places said since ' + said_since if said_since else 'every place (--all)'}")
    print(f"would reopen: {counts['reopen']} on {counts['pages']} pages, by when last said:")
    for bucket, n in counts["reopen_by_last_said"].items():
        print(f"  {bucket}: {n}")
    if counts["cutoff_by_last_said"]:
        print("kept closed by the window (--all would weigh them), by when last said:")
        for bucket, n in counts["cutoff_by_last_said"].items():
            print(f"  {bucket}: {n}")
    for reason, n in counts["kept_closed"].items():
        print(f"kept closed ({reason}): {n}")
    for reason, n in counts["pages_skipped"].items():
        print(f"pages skipped ({reason}): {n}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m api.services.coexist_reopen",
                                     description="Reopen places a single-valued close ended only because another "
                                                 "place was mentioned (dry run by default).")
    parser.add_argument("--bank", required=True, help="the bank directory (a git repository)")
    parser.add_argument("--plan", help="write the plan (ids, page paths, commits, reasons — no claim text) here")
    parser.add_argument("--said-since", help="keep closed a place last said before this day (YYYY-MM-DD); "
                                             f"default: {DEFAULT_WINDOW_DAYS} days ago")
    parser.add_argument("--all", action="store_true", help="no window: weigh every place, however long ago said")
    parser.add_argument("--apply", action="store_true", help="reopen them, in one commit")
    args = parser.parse_args(argv)
    if args.said_since and not _DAY.match(args.said_since):
        print("--said-since takes a day, YYYY-MM-DD", file=sys.stderr)
        return 2
    if args.all and args.said_since:
        print("--all and --said-since are two windows; pass one", file=sys.stderr)
        return 2
    if not args.all and not args.said_since:
        args.said_since = (date.today() - timedelta(days=DEFAULT_WINDOW_DAYS)).isoformat()
    bank = Path(args.bank).expanduser()
    try:
        if args.apply:
            result = apply(bank, said_since=args.said_since,
                           sleep_holding=lambda: write_admission.holding() or claim_recovery.backend_sleep_holding())
            plan = result.plan or Plan(head="")
        else:
            plan = analyze(bank, said_since=args.said_since)
    except NotAGitBank:
        print(f"not a git bank: {bank}", file=sys.stderr)
        return 2
    except SleepIsWriting:
        print("Sleep is writing this bank's pages, or the backend could not confirm it is not; nothing was changed.",
              file=sys.stderr)
        return 3
    except write_admission.AdmissionUnavailable:
        print("the bank's write admission cannot be opened; nothing was changed.", file=sys.stderr)
        return 3
    _print_counts(plan, args.said_since)
    if args.plan:
        Path(args.plan).write_text(json.dumps(plan.to_dict(), indent=2) + "\n", encoding="utf-8")
    if args.apply:
        print(f"reopened: {result.reopened} on {len(result.pages)} pages")
        if result.skipped_dirty:
            print(f"pages skipped (uncommitted edits): {len(result.skipped_dirty)}")
        if result.skipped_unreadable:
            print(f"pages skipped (unreadable fence): {len(result.skipped_unreadable)}")
        print(f"commit: {result.commit or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
