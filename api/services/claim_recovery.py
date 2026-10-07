"""Recover, as closed history, the claims a Sleep prose rewrite dropped (G148 follow-up; G118, G183) — dry run first.

Before the claim-fence fix, Stage 5 / conflict resolution sectioned a page's RAW body, so the trailing ```claims fence
rode inside its last section and was rebuilt or lost with it; the claim pipeline, which runs after the prose writes,
then re-wrote only what it could still read. Claims are bi-temporal — a superseded belief stays as history — so an id
that left every page is a hole in the record.

**Nothing comes back as a current belief.** A recovered entry is restored CLOSED: ``valid_to`` is the day the rewrite
dropped it, or its own stated end (``claim_expiry.stated_end``) when that came first, never before ``valid_from``; an
entry that was already closed keeps its own ``valid_to``. It carries ``recovered_from: <removing commit>`` and
``recovered_by: claim_recovery``, and no writer reopens it (``claims.is_recovered_history``). So no single-valued
conflict, obsolete belief or expired fact comes back as current through the record itself.

**Finding losses (git only).** Every first-parent commit that touched ``entities/`` is replayed with one
``git cat-file --batch``; an id in a page's fence before a commit and not after it is a removal, and the id's LAST
removal decides (several pages in one commit count as one removal each). An id on any page at HEAD is no loss.

**Excluded, by reason, in this order** — each needs positive evidence to pass, and when unsure it excludes:

* who removed it: ``person_edit`` (``Cicada-Author: user``), ``merged`` (``Dedup sweep``), ``inbox_resolution``,
  ``other_writer`` (not a ``Sleep cycle …`` subject), ``unproven_writer`` (a Sleep subject whose authors are not all
  models or ``cicada`` — an agent's label, ``unknown``, or none);
* ``unreadable_fence``: the page's fence was unterminated, repeated or unparseable at any version read, or is now;
  an unreadable HEAD page is read as YAML decodes it (``claims.loose_claim_entries``), so an id it holds — escaped or
  quoted — is present and a ``retracts`` record it holds excludes; ``unreadable_elsewhere``: some page's YAML will not
  load at all, so absence cannot be proven and every candidate is excluded;
* ``retracted``: a ``retracts`` record named the id at any version read (an incarnation restated after a withdrawal
  is excluded too — the history cannot tell them apart), or the entry is itself such a record;
* ``merged``: a ``<id>-from-<loser>`` copy is at HEAD; ``page_gone``; ``page_archived`` (``archived``/``dropped``
  before or after the removal, or now);
* ``not_rewrite``: the rewrite's own signature is missing — the section that held the fence when the page was
  sectioned RAW (``entity_body.parse_sections``, as the unfixed code did) must have had its prose rewritten (compared
  fence-stripped, as the fixed code sections it). A fence that shrank under that section's unchanged prose is a hand
  edit a Sleep commit swept up, or something else.

**Classes of what is left.** ``replaced``: a current claim on the page has the same subject and predicate (and object,
unless the vocabulary marks the predicate single-valued), or a HEAD claim ``supersedes`` it — restored as history.
``closed_history``: every dropped copy was already closed — restored as the history it was. ``no_current_replacement``:
a belief that was current when dropped and has no successor — listed by id and page only, never written; the person
decides.

**Dry run (default)** prints counts by class and reason; ``--plan`` writes ids, page paths, the removing commit, class
and reason — never claim text. **``--apply``** writes ``replaced`` and ``closed_history``: each entry as the YAML held it
(unknown fields and key order kept), appended to the fence without re-rendering any entry already there
(``claims.append_claim_entries``; the frontmatter is not re-rendered either), spans checked against their sources as
readers check them (one that no longer locates becomes ``reasoning`` — provenance never blocks memory). Inside the
bank's write admission, Sleep asked once it is held (the CLI also asks the backend and refuses on ANY answer but a clear
``writing: false``), then the page lock, then git's write lock; a dirty or unreadable page is skipped; one
``Recover dropped claims <date>`` commit of only the pages written, ``Cicada-Author: cicada``, put back from HEAD on a
failed commit. A re-run finds nothing.

    python -m api.services.claim_recovery --bank <path> [--plan <file>] [--apply]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable, Iterator

import yaml

from api.services import claim_expiry, entity_body, evidence, git_service, markdown_parser, page_lock, \
    predicates, write_admission
from api.services.claims import (
    FENCE_NONE,
    FENCE_OK,
    RETRACT_PREDICATE,
    Claim,
    MalformedClaimsBlockError,
    append_claim_entries,
    event_cardinality,
    fence_state,
    loose_claim_entries,
    raw_claim_entries,
    strip_claims_block,
)

TRIGGER = "maintenance/claim-recovery"
AUTHOR = git_service.CICADA_AUTHOR
SUBJECT = "Recover dropped claims"
RECOVERED_BY = "claim_recovery"

#: The one writer whose removals may be the rewrite bug: Sleep's own commits (main, batch, the split decay commit).
_SLEEP_SUBJECT = re.compile(r"^Sleep cycle \d{4}-\d{2}-\d{2}\b")
_PAGE_RE = re.compile(r"^entities/[^/]+\.md$")
_GONE_STATUSES = frozenset({"archived", "dropped"})
_MACHINE_KINDS = frozenset({"model", "system"})
_SAFE_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)

REASONS = ("person_edit", "merged", "inbox_resolution", "other_writer", "unproven_writer", "unreadable_fence",
           "unreadable_elsewhere", "retracted", "page_gone", "page_archived", "not_rewrite")
REPLACED, CLOSED_HISTORY, NO_REPLACEMENT = "replaced", "closed_history", "no_current_replacement"
CLASSES = (REPLACED, CLOSED_HISTORY, NO_REPLACEMENT)
#: The classes `--apply` writes. A belief with no successor is the person's to decide.
WRITTEN = (REPLACED, CLOSED_HISTORY)


class NotAGitBank(ValueError):
    """The path is not a git-versioned bank: there is no history to recover from."""


class SleepIsWriting(RuntimeError):
    """Sleep holds the bank's pages, or whether it does could not be established; nothing was written."""


# --- reading history ---------------------------------------------------------------------------------------------


def _git_read(bank: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-c", "core.quotePath=off", *args], cwd=str(bank), capture_output=True,
                          env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
    if proc.returncode != 0:
        raise git_service.GitError(f"git {args[0]} failed: {proc.stderr.decode(errors='replace')}")
    return proc.stdout.decode("utf-8", errors="replace")


class _Blobs:
    """One ``git cat-file --batch`` for every page version the replay reads."""

    def __init__(self, bank: Path) -> None:
        self._proc = subprocess.Popen(["git", "cat-file", "--batch"], cwd=str(bank), stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                      env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})

    def read(self, rev: str, path: str) -> str | None:
        assert self._proc.stdin is not None and self._proc.stdout is not None
        self._proc.stdin.write(f"{rev}:{path}\n".encode("utf-8"))
        self._proc.stdin.flush()
        header = self._proc.stdout.readline().decode("utf-8", errors="replace").split()
        if len(header) != 3:
            return None   # "<rev>:<path> missing"
        data = self._proc.stdout.read(int(header[2]))
        self._proc.stdout.read(1)
        return data.decode("utf-8", errors="replace")

    def close(self) -> None:
        if self._proc.stdin:
            self._proc.stdin.close()
        self._proc.wait()


@dataclass
class _Version:
    raw: str
    frontmatter: dict
    body: str                      # as markdown_parser.parse returns it: fence included, stripped
    entries: list[dict] | None     # None: the fence is unterminated, repeated or unparseable
    loose: list[dict] | None = None   # an unreadable fence's entries as YAML decodes them; None: will not load

    def markers(self) -> set[str]:
        """The ids a ``retracts`` record on this version names — read loosely when the fence is unreadable."""
        rows = self.entries if self.entries is not None else (self.loose or [])
        return {str(e.get("object")) for e in rows if e.get("predicate") == RETRACT_PREDICATE and e.get("object")}

    def ids(self) -> set[str]:
        rows = self.entries if self.entries is not None else (self.loose or [])
        return {str(e.get("id")) for e in rows if e.get("id") is not None}

    @property
    def status(self) -> str:
        return str(self.frontmatter.get("status") or "").lower()

    def claims(self) -> list[Claim]:
        return [Claim.from_dict(e) for e in self.entries or []]


def _version(text: str | None) -> _Version | None:
    if text is None:
        return None
    split = markdown_parser.split_frontmatter(text)
    fm: dict = {}
    body = text
    if split is not None:
        try:
            loaded = yaml.load(split[0].strip(), Loader=_SAFE_LOADER)  # noqa: S506 — a SAFE loader
            fm = loaded if isinstance(loaded, dict) else {}
        except yaml.YAMLError:
            fm = {}
        body = split[1].strip()
    entries: list[dict] | None
    try:
        entries = raw_claim_entries(body) if fence_state(body) in (FENCE_NONE, FENCE_OK) else None
        if entries is not None:
            [Claim.from_dict(e) for e in entries]   # a field that cannot convert is as unreadable as bad YAML
    except (MalformedClaimsBlockError, TypeError, ValueError):
        entries = None
    return _Version(text, fm, body, entries, loose_claim_entries(body) if entries is None else None)


def _rewrote_the_fence_section(before: _Version, after: _Version | None) -> bool:
    """The bug's signature: sectioned RAW (fence included) as the unfixed code did, the fence sat inside a section;
    that section's prose — compared fence-stripped, as the fixed code sections — was rewritten (or is gone)."""
    raw_sections = entity_body.parse_sections(before.body)
    holders = [title for title, text in raw_sections.items() if "```claims" in text]
    if not holders:
        return False
    if after is None:
        return False   # a deleted page is not a rewrite
    old = entity_body.parse_sections(strip_claims_block(before.body))
    new = entity_body.parse_sections(strip_claims_block(after.body))
    return any(old.get(title) != new.get(title) for title in holders)


@dataclass
class _Commit:
    index: int
    sha: str
    day: str
    subject: str
    authors: list[str]
    pages: list[tuple[str, str]]   # (status letter, path)


def _commits(bank: Path) -> Iterator[_Commit]:
    out = _git_read(bank, "log", "--first-parent", "--reverse", "-m", "--no-renames", "--name-status",
                    "--format=%x1e%H%x1f%cI%x1f%s%x1f%(trailers:key=Cicada-Author,valueonly,separator=%x2C)",
                    "--", "entities")
    for index, record in enumerate(r for r in out.split("\x1e") if r.strip()):
        head, _, rest = record.partition("\n")
        sha, when, subject, authors = (head.split("\x1f") + ["", "", ""])[:4]
        pages = []
        for line in rest.splitlines():
            status, _, path = line.partition("\t")
            if status and _PAGE_RE.match(path):
                pages.append((status[0], path))
        yield _Commit(index, sha, when[:10], subject, [a.strip() for a in authors.split(",") if a.strip()], pages)


def _classify_commit(commit: _Commit) -> str | None:
    if git_service.USER_AUTHOR in commit.authors:
        return "person_edit"
    if commit.subject.startswith("Dedup sweep"):
        return "merged"
    if commit.subject.startswith("Inbox resolution"):
        return "inbox_resolution"
    if not _SLEEP_SUBJECT.match(commit.subject):
        return "other_writer"
    if not commit.authors or any(git_service.author_identity(a)[0] not in _MACHINE_KINDS for a in commit.authors):
        return "unproven_writer"
    return None


@dataclass
class _Removal:
    commit: _Commit
    page: str
    entries: list[dict]          # every copy of the id the page held just before, as the YAML held it
    signature: bool              # the fence's section was rewritten
    archived: bool               # the page was archived/dropped just before or just after


# --- the plan ----------------------------------------------------------------------------------------------------


@dataclass
class Item:
    claim_id: str
    page: str          # memory-relative, entities/<id>.md
    removed_in: str    # the commit that removed it last
    removed_on: str    # that commit's date
    reason: str | None = None   # an exclusion
    kind: str | None = None     # a class, when not excluded
    entries: list[dict] = field(default_factory=list, repr=False)   # as it last existed; never serialized

    def to_dict(self) -> dict:
        out = {"claim_id": self.claim_id, "page": self.page, "removed_in": self.removed_in}
        out.update({"reason": self.reason} if self.reason else {"class": self.kind})
        return out


@dataclass
class Plan:
    """Every count is per (claim id, page) item; ``ids`` counts distinct ids and ``entries`` the YAML entries the
    written classes would append (an id can repeat on a page: withdraw → restate)."""
    head: str
    items: list[Item] = field(default_factory=list)

    def of(self, *kinds: str) -> list[Item]:
        return [i for i in self.items if i.reason is None and i.kind in kinds]

    @property
    def excluded(self) -> list[Item]:
        return [i for i in self.items if i.reason]

    def counts(self) -> dict:
        reasons: dict[str, int] = {}
        for item in self.excluded:
            reasons[item.reason] = reasons.get(item.reason, 0) + 1
        written = self.of(*WRITTEN)
        return {
            "candidates": len(self.items),
            "ids": len({i.claim_id for i in self.items}),
            **{kind: len(self.of(kind)) for kind in CLASSES},
            "excluded": {r: reasons[r] for r in REASONS if r in reasons},
            "entries": sum(len(i.entries) for i in written),
            "pages": len({i.page for i in written}),
        }

    def to_dict(self) -> dict:
        return {"head": self.head, "counts": self.counts(), "items": [i.to_dict() for i in self.items]}


def _head(bank: Path) -> str:
    try:
        return _git_read(bank, "rev-parse", "--verify", "-q", "HEAD^{commit}").strip()
    except git_service.GitError:
        return ""


@dataclass
class _Head:
    present: set[str]
    pages: dict[str, _Version]
    retracted: set[str]
    opaque: bool = False   # some page's fence is unreadable AND its YAML will not load: presence cannot be proven


def _head_state(bank: Path, blobs: _Blobs) -> _Head:
    """Which ids every HEAD page holds. An unreadable fence is read as YAML decodes it (an escaped or quoted id is
    still that id); one whose YAML will not load makes the whole bank's absence unprovable."""
    state = _Head(set(), {}, set())
    for path in _git_read(bank, "ls-tree", "-r", "--name-only", "HEAD", "--", "entities").splitlines():
        if not _PAGE_RE.match(path):
            continue
        version = _version(blobs.read("HEAD", path))
        if version is None:
            continue
        state.pages[path] = version
        if version.entries is None and version.loose is None:
            state.opaque = True
        state.present.update(version.ids())
        state.retracted.update(version.markers())
    return state


def analyze(bank) -> Plan:
    """Replay the bank's history and classify every lost id. Reads only; writes nothing."""
    bank = Path(bank)
    if not (bank / ".git").exists():
        raise NotAGitBank(str(bank))
    head = _head(bank)
    plan = Plan(head=head)
    if not head:
        return plan
    last: dict[str, list[_Removal]] = {}
    retracted: set[str] = set()
    ever_unreadable: set[str] = set()
    blobs = _Blobs(bank)
    try:
        for commit in _commits(bank):
            for status, path in commit.pages:
                after = _version(blobs.read(commit.sha, path)) if status != "D" else None
                before = _version(blobs.read(f"{commit.sha}^", path)) if status in ("M", "D") else None
                for version in (before, after):
                    if version is None:
                        continue
                    if version.entries is None:
                        ever_unreadable.add(path)
                    retracted.update(version.markers())
                if before is None or before.entries is None or (after is not None and after.entries is None):
                    continue   # trapped in a fence nobody can read — not proven removed
                kept = {str(e.get("id") or "") for e in after.entries} if after is not None else set()
                lost = dict.fromkeys(str(e.get("id") or "") for e in before.entries)
                lost = [cid for cid in lost if cid and cid not in kept]
                if not lost:
                    continue
                signature = _rewrote_the_fence_section(before, after)
                archived = before.status in _GONE_STATUSES or (after is not None and after.status in _GONE_STATUSES)
                for cid in lost:
                    removal = _Removal(commit, path, [e for e in before.entries if str(e.get("id") or "") == cid],
                                       signature, archived)
                    previous = last.get(cid)
                    if previous and previous[0].commit.index == commit.index:
                        previous.append(removal)
                    else:
                        last[cid] = [removal]
        if not last:
            return plan
        now = _head_state(bank, blobs)
        retracted |= now.retracted
    finally:
        blobs.close()
    for cid, removals in last.items():
        if cid in now.present:
            continue
        for removal in removals:
            item = Item(cid, removal.page, removal.commit.sha, removal.commit.day, entries=removal.entries)
            item.reason = _exclusion(bank, cid, removal, now, retracted, ever_unreadable)
            if item.reason is None:
                item.kind = _class(bank, removal, now.pages[removal.page])
            plan.items.append(item)
    return plan


def _exclusion(bank: Path, cid: str, removal: _Removal, now: _Head, retracted: set[str],
               ever_unreadable: set[str]) -> str | None:
    why = _classify_commit(removal.commit)
    if why:
        return why
    page = now.pages.get(removal.page)
    if removal.page in ever_unreadable or (page is not None and page.entries is None):
        return "unreadable_fence"
    if now.opaque:
        return "unreadable_elsewhere"
    if cid in retracted or any(e.get("predicate") == RETRACT_PREDICATE for e in removal.entries):
        return "retracted"
    if any(other.startswith(f"{cid}-from-") for other in now.present):
        return "merged"
    if page is None:
        return "page_gone"
    if removal.archived or page.status in _GONE_STATUSES:
        return "page_archived"
    if not removal.signature:
        return "not_rewrite"
    return None


def _norm(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def _class(bank: Path, removal: _Removal, page: _Version) -> str:
    lost = [Claim.from_dict(e) for e in removal.entries]
    current = [c for c in page.claims() if c.valid_to is None and c.predicate != RETRACT_PREDICATE]
    ids = {c.id for c in lost}
    if any(c.supersedes in ids for c in page.claims()):
        return REPLACED
    for claim in lost:
        single = (event_cardinality(claim.predicate) or predicates.cardinality(bank, claim.predicate)) == "single"
        for other in current:
            if (other.subject, other.predicate) != (claim.subject, claim.predicate):
                continue
            if single or _norm(other.object) == _norm(claim.object):
                return REPLACED
    if all(c.valid_to is not None for c in lost):
        return CLOSED_HISTORY
    return NO_REPLACEMENT


# --- apply -------------------------------------------------------------------------------------------------------


@dataclass
class ApplyResult:
    recovered: int = 0            # YAML entries appended
    pages: list[str] = field(default_factory=list)
    degraded_spans: int = 0
    skipped_dirty: list[str] = field(default_factory=list)
    skipped_unreadable: list[str] = field(default_factory=list)
    commit: str | None = None
    plan: Plan | None = None


def closing_day(claim: Claim, removed_on: str) -> str:
    """When a recovered open claim stops being current: the day it was dropped, or its own stated end when that came
    first (the expiry rule), never before it began."""
    end = removed_on
    stated = claim_expiry.stated_end(claim)
    if stated and stated < end:
        end = stated
    try:
        began = date.fromisoformat(str(claim.valid_from or "")[:10]).isoformat()
    except ValueError:
        return end
    return max(end, began)


def _as_history(bank: Path, entry: dict, item: Item) -> tuple[dict, int]:
    """The entry as the YAML held it, closed, marked, with each span checked as readers check it."""
    out = dict(entry)
    if out.get("valid_to") is None:
        out["valid_to"] = closing_day(Claim.from_dict(entry), item.removed_on)
    degraded = 0
    if isinstance(out.get("evidence"), list):
        spans = []
        for raw in out["evidence"]:
            ev = evidence.Evidence.from_dict(raw)
            if isinstance(raw, dict) and ev.is_span() and _stale(bank, ev):
                text = evidence.source_text(bank, ev.episode)
                raw = evidence.reasoning(ev.episode, hash=evidence.body_hash(text) if text is not None else "").to_dict()
                degraded += 1
            spans.append(raw)
        out["evidence"] = spans
    out["recovered_from"] = item.removed_in
    out["recovered_by"] = RECOVERED_BY
    return out, degraded


def _stale(bank: Path, ev: evidence.Evidence) -> bool:
    text = evidence.source_text(bank, ev.episode)
    if text is None or ev.end > len(text):
        return True
    status = evidence.span_status(text, end=ev.end, hash=ev.hash, appendable=evidence.is_episode_id(ev.episode))
    return status == evidence.SPAN_STALE


def commit_message(lines: dict[str, int], today: date) -> str:
    return git_service.build_commit_message(
        f"{SUBJECT} {today.isoformat()}",
        [f"{rel}: updated (recovered as history: {n}, trigger: {TRIGGER})" for rel, n in sorted(lines.items())],
        authors=[AUTHOR],
    )


def apply(bank, *, sleep_holding: Callable[[], bool] | None = None, today: date | None = None) -> ApplyResult:
    """Restore every ``replaced`` and ``closed_history`` item as closed history and commit the pages written, alone,
    as ``cicada``. Admission first, Sleep asked once it is held — :func:`write_admission.holding` by default; the CLI
    also asks a running backend — then the page lock, then git's write lock (G183's order)."""
    bank = Path(bank)
    if not (bank / ".git").exists():
        raise NotAGitBank(str(bank))
    holding = sleep_holding or write_admission.holding
    plan = analyze(bank)
    with write_admission.shared(bank):
        if holding():
            raise SleepIsWriting(str(bank))
        with page_lock.page_lock(bank), git_service.write_lock(bank):
            if _head(bank) != plan.head:
                plan = analyze(bank)   # another writer committed between the read and the hold
            return _apply_locked(bank, plan, today or date.today())


def _apply_locked(bank: Path, plan: Plan, today: date) -> ApplyResult:
    result = ApplyResult(plan=plan)
    by_page: dict[str, list[Item]] = {}
    for item in plan.of(*WRITTEN):
        by_page.setdefault(item.page, []).append(item)
    if not by_page:
        return result
    dirty = git_service.dirty_paths_sync(bank, *by_page)
    written: dict[str, int] = {}
    try:
        for rel, items in sorted(by_page.items()):
            if rel in dirty:
                result.skipped_dirty.append(rel)
                continue
            path = bank / rel
            try:
                document = path.read_text(encoding="utf-8")
                have = {str(e.get("id") or "") for e in raw_claim_entries(document)}
            except (OSError, MalformedClaimsBlockError):
                result.skipped_unreadable.append(rel)
                continue
            added: list[dict] = []
            degraded = 0
            for item in items:
                if item.claim_id in have:
                    continue
                for entry in item.entries:
                    restored, n = _as_history(bank, entry, item)
                    degraded += n
                    added.append(restored)
            if not added:
                continue
            try:
                updated = append_claim_entries(document, added)
            except MalformedClaimsBlockError:
                result.skipped_unreadable.append(rel)
                continue
            markdown_parser.write_document(path, updated)
            written[rel] = len(added)
            result.degraded_spans += degraded
        if written:
            git_service.commit_paths_sync(bank, commit_message(written, today), sorted(written))
            result.commit = _head(bank)
    except BaseException:
        if written:
            # From HEAD, not the index: a commit that failed after its `git add` left the new bytes staged. Every
            # page written was clean at HEAD, so this is exactly what was there.
            git_service.run_git_write_sync(bank, "checkout", "HEAD", "--", *sorted(written))
        raise
    result.pages = sorted(written)
    result.recovered = sum(written.values())
    return result


# --- CLI ---------------------------------------------------------------------------------------------------------


def backend_sleep_holding(timeout: float = 4.0) -> bool:
    """This is its own process, so Sleep's flag lives in the backend's: ask ``GET /sleep/status`` and FAIL CLOSED.
    Only an HTTP 200 whose JSON carries ``writing: false`` lets the write go ahead; no backend, an auth or server
    error, a timeout, a malformed body or an older backend without ``writing`` all answer "holding" — the apply is
    refused, nothing written. The token is read, never created."""
    import urllib.request

    from api.services import runtime_layout

    token = (os.environ.get("CICADA_API_TOKEN") or "").strip()
    if not token:
        home = Path(os.environ.get("CICADA_HOME") or Path.home() / ".cicada").expanduser()
        try:
            token = (home / "api_token").read_text(encoding="utf-8").strip()
        except OSError:
            token = ""
    headers = {"Accept": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})}
    req = urllib.request.Request(f"{runtime_layout.backend_url()}/sleep/status", headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return True
            body = json.loads(resp.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 — any failure is "cannot establish that Sleep is idle"
        return True
    return not (isinstance(body, dict) and body.get("writing") is False)


def _print_counts(plan: Plan) -> None:
    counts = plan.counts()
    print(f"candidates (id/page): {counts['candidates']} ({counts['ids']} ids)")
    for kind in CLASSES:
        print(f"{kind}: {counts[kind]}")
    for reason, n in counts["excluded"].items():
        print(f"excluded ({reason}): {n}")
    print(f"entries to restore as history: {counts['entries']} on {counts['pages']} pages")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m api.services.claim_recovery",
                                     description="Recover, as closed history, claims a Sleep prose rewrite dropped "
                                                 "(dry run by default).")
    parser.add_argument("--bank", required=True, help="the bank directory (a git repository)")
    parser.add_argument("--plan", help="write the plan (ids, page paths, commits, classes — no claim text) here")
    parser.add_argument("--apply", action="store_true", help="restore the replaced and closed claims as history")
    args = parser.parse_args(argv)
    bank = Path(args.bank).expanduser()
    try:
        if args.apply:
            result = apply(bank, sleep_holding=lambda: write_admission.holding() or backend_sleep_holding())
            plan = result.plan or Plan(head="")
        else:
            plan = analyze(bank)
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
    _print_counts(plan)
    if args.plan:
        Path(args.plan).write_text(json.dumps(plan.to_dict(), indent=2) + "\n", encoding="utf-8")
    if args.apply:
        print(f"restored as history: {result.recovered} entries on {len(result.pages)} pages")
        print(f"spans kept as reasoning: {result.degraded_spans}")
        if result.skipped_dirty:
            print(f"pages skipped (uncommitted edits): {len(result.skipped_dirty)}")
        if result.skipped_unreadable:
            print(f"pages skipped (unreadable fence): {len(result.skipped_unreadable)}")
        print(f"commit: {result.commit or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
