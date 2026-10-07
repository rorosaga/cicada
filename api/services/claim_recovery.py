"""Recover the claims a Sleep prose rewrite dropped (G148 follow-up; G118, G183) — from git alone, dry run first.

Before the claim-fence fix, a Stage-5 / conflict-resolution rewrite took a page's trailing ```claims fence for part of
its last section and rebuilt it, so claims vanished while the prose grew. Claims are bi-temporal — a superseded belief
stays as history — so an id that left every page is a loss unless someone removed it on purpose. This module finds
those losses in the bank's own history and puts them back exactly as they last were.

**Candidates come from git only.** Every first-parent commit that touched ``entities/`` is replayed; a claim id that
was in a page's fence before a commit and not after it is a *removal*. An id still present on any page at HEAD is not a
loss. For the rest, the id's LAST removal decides (several pages in one commit count together):

* only a ``Sleep cycle …`` commit (a batch, a plain cycle, its split ``(decay)`` commit) ran the rewrite that dropped
  claims — the inbox's conflict answer re-writes its fence from the claims it parsed, and every other writer
  appends or closes, never drops. Anything else is excluded by what it was: ``person_edit`` (``Cicada-Author: user``),
  ``merged`` (the dedup sweep), ``inbox_resolution``, ``other_writer``;
* at HEAD: ``retracted`` (a ``retracts`` record names it), ``merged`` (a ``<id>-from-<loser>`` copy carries it),
  ``page_gone``, ``page_archived`` (``archived``/``dropped``), ``page_unreadable`` (a fence strict parsing refuses);
* ``prose_unchanged``: the rewrite's signature is prose that moved; a fence that shrank under identical prose is
  something else (a hand edit a Sleep commit swept up) and is reported, never guessed at.

When unsure it excludes — nothing a person or an agent removed deliberately is resurrected.

**Dry run (the default)** prints counts only and, when asked, writes a plan of ids, page paths, the removing commit
and the exclusion reason — never claim text. **``--apply``** re-adds each recoverable claim as it last existed (same
id, same fields) through ``claims.write_claims``, the one fence writer; each evidence span is checked against its
source as the readers check it (``evidence.span_status``) and one that no longer locates is kept as ``reasoning`` —
provenance never blocks memory. It runs inside the bank's write admission (refused while Sleep holds the pages), the
page lock and git's write lock, in that order; a page with an uncommitted edit is skipped; the run is one
``Recover dropped claims <date>`` commit of only the pages it wrote, ``Cicada-Author: cicada``, put back on a failed
commit. A second run finds nothing: every recovered id is present again.

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

from api.services import evidence, git_service, markdown_parser, page_lock, write_admission
from api.services.claims import (
    RETRACT_PREDICATE,
    Claim,
    MalformedClaimsBlockError,
    parse_claims,
    strip_claims_block,
    write_claims,
)

TRIGGER = "maintenance/claim-recovery"
AUTHOR = git_service.CICADA_AUTHOR
SUBJECT = "Recover dropped claims"

#: The one writer whose removals are recoverable: Sleep's own commits (main, batch and the split decay commit).
_SLEEP_SUBJECT = re.compile(r"^Sleep cycle \d{4}-\d{2}-\d{2}\b")
_PAGE_RE = re.compile(r"^entities/[^/]+\.md$")
_GONE_STATUSES = frozenset({"archived", "dropped"})
_SAFE_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)

#: Exclusion reasons, in the order they are decided.
REASONS = ("person_edit", "merged", "inbox_resolution", "other_writer", "retracted", "page_gone",
           "page_archived", "page_unreadable", "prose_unchanged")


class NotAGitBank(ValueError):
    """The path is not a git-versioned bank: there is no history to recover from."""


class SleepIsWriting(RuntimeError):
    """Sleep holds the bank's pages; nothing was written."""


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
    frontmatter: dict
    prose: str
    claims: list[Claim] | None   # None: a fence strict parsing refuses


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
    try:
        claims: list[Claim] | None = parse_claims(body, strict=True)
    except MalformedClaimsBlockError:
        claims = None
    return _Version(fm, strip_claims_block(body), claims)


@dataclass
class _Commit:
    index: int
    sha: str
    subject: str
    authors: list[str]
    pages: list[tuple[str, str]]   # (status letter, path)


def _commits(bank: Path) -> Iterator[_Commit]:
    out = _git_read(bank, "log", "--first-parent", "--reverse", "-m", "--no-renames", "--name-status",
                    "--format=%x1e%H%x1f%s%x1f%(trailers:key=Cicada-Author,valueonly,separator=%x2C)",
                    "--", "entities")
    for index, record in enumerate(r for r in out.split("\x1e") if r.strip()):
        head, _, rest = record.partition("\n")
        sha, subject, authors = (head.split("\x1f") + ["", ""])[:3]
        pages = []
        for line in rest.splitlines():
            status, _, path = line.partition("\t")
            if status and _PAGE_RE.match(path):
                pages.append((status[0], path))
        yield _Commit(index, sha, subject, [a.strip() for a in authors.split(",") if a.strip()], pages)


@dataclass
class _Removal:
    commit: _Commit
    page: str
    claims: list[Claim]          # every copy of the id the page held just before (an id can repeat: Q-R5)
    prose_changed: bool


def _classify_commit(commit: _Commit) -> str | None:
    if git_service.USER_AUTHOR in commit.authors:
        return "person_edit"
    if commit.subject.startswith("Dedup sweep"):
        return "merged"
    if commit.subject.startswith("Inbox resolution"):
        return "inbox_resolution"
    if not _SLEEP_SUBJECT.match(commit.subject):
        return "other_writer"
    return None


# --- the plan ----------------------------------------------------------------------------------------------------


@dataclass
class Item:
    claim_id: str
    page: str          # memory-relative, entities/<id>.md
    removed_in: str    # the commit that removed it last
    reason: str | None = None
    claims: list[Claim] = field(default_factory=list, repr=False)   # as it last existed; never serialized

    def to_dict(self) -> dict:
        out = {"claim_id": self.claim_id, "page": self.page, "removed_in": self.removed_in}
        if self.reason:
            out["reason"] = self.reason
        return out


@dataclass
class Plan:
    head: str
    recoverable: list[Item] = field(default_factory=list)
    excluded: list[Item] = field(default_factory=list)

    def counts(self) -> dict:
        reasons: dict[str, int] = {}
        for item in self.excluded:
            reasons[item.reason or ""] = reasons.get(item.reason or "", 0) + 1
        return {
            "candidates": len({i.claim_id for i in [*self.recoverable, *self.excluded]}),
            "excluded": {r: reasons[r] for r in REASONS if r in reasons},
            "recoverable": len(self.recoverable),
            "pages": len({i.page for i in self.recoverable}),
        }

    def to_dict(self) -> dict:
        return {"head": self.head, "counts": self.counts(),
                "recoverable": [i.to_dict() for i in self.recoverable],
                "excluded": [i.to_dict() for i in self.excluded]}


def _head(bank: Path) -> str:
    try:
        return _git_read(bank, "rev-parse", "--verify", "-q", "HEAD^{commit}").strip()
    except git_service.GitError:
        return ""


def analyze(bank) -> Plan:
    """Replay the bank's history and decide, per lost id, whether it is recoverable. Reads only; writes nothing."""
    bank = Path(bank)
    if not (bank / ".git").exists():
        raise NotAGitBank(str(bank))
    head = _head(bank)
    plan = Plan(head=head)
    if not head:
        return plan
    last: dict[str, list[_Removal]] = {}
    blobs = _Blobs(bank)
    try:
        for commit in _commits(bank):
            for status, path in commit.pages:
                if status not in ("M", "D"):
                    continue
                before = _version(blobs.read(f"{commit.sha}^", path))
                after = _version(blobs.read(commit.sha, path)) if status == "M" else None
                if before is None or before.claims is None:
                    continue
                if after is not None and after.claims is None:
                    continue   # trapped in a fence nobody can read — not removed
                kept = {c.id for c in after.claims} if after is not None and after.claims is not None else set()
                prose_changed = after is None or after.prose != before.prose
                for cid in dict.fromkeys(c.id for c in before.claims if c.id and c.id not in kept):
                    removal = _Removal(commit, path, [c for c in before.claims if c.id == cid], prose_changed)
                    previous = last.get(cid)
                    if previous and previous[0].commit.index == commit.index:
                        previous.append(removal)
                    else:
                        last[cid] = [removal]
        if not last:
            return plan
        present, retracted, merged_copies, pages = _head_state(bank, blobs)
    finally:
        blobs.close()
    for cid, removals in last.items():
        if cid in present:
            continue
        reason = _classify_commit(removals[0].commit)
        for removal in removals:
            page = pages.get(removal.page)
            why = reason
            if why is None and cid in retracted:
                why = "retracted"
            if why is None and any(m.startswith(f"{cid}-from-") for m in merged_copies):
                why = "merged"
            if why is None and page is None:
                why = "page_gone"
            if why is None and str(page.frontmatter.get("status") or "").lower() in _GONE_STATUSES:
                why = "page_archived"
            if why is None and page.claims is None:
                why = "page_unreadable"
            if why is None and not removal.prose_changed:
                why = "prose_unchanged"
            item = Item(cid, removal.page, removal.commit.sha, why, removal.claims)
            (plan.excluded if why else plan.recoverable).append(item)
    return plan


def _head_state(bank: Path, blobs: _Blobs) -> tuple[set[str], set[str], set[str], dict[str, _Version]]:
    present: set[str] = set()
    retracted: set[str] = set()
    pages: dict[str, _Version] = {}
    for path in _git_read(bank, "ls-tree", "-r", "--name-only", "HEAD", "--", "entities").splitlines():
        if not _PAGE_RE.match(path):
            continue
        version = _version(blobs.read("HEAD", path))
        if version is None:
            continue
        pages[path] = version
        for claim in version.claims or []:
            present.add(claim.id)
            if claim.predicate == RETRACT_PREDICATE and claim.object:
                retracted.add(claim.object)
    merged_copies = {cid for cid in present if "-from-" in cid}
    return present, retracted, merged_copies, pages


# --- apply -------------------------------------------------------------------------------------------------------


@dataclass
class ApplyResult:
    recovered: int = 0
    pages: list[str] = field(default_factory=list)
    degraded_spans: int = 0
    skipped_dirty: list[str] = field(default_factory=list)
    commit: str | None = None
    plan: Plan | None = None


def _verified(bank: Path, claim: Claim) -> tuple[Claim, int]:
    """The claim with every span checked against its source as the readers check it; a span that no longer locates
    becomes ``reasoning`` on the same document (the claim is still written — G118)."""
    kept: list[evidence.Evidence] = []
    degraded = 0
    for ev in claim.evidence:
        if not ev.is_span():
            kept.append(ev)
            continue
        text = evidence.source_text(bank, ev.episode)
        if text is None:
            kept.append(evidence.reasoning(ev.episode))
            degraded += 1
            continue
        status = evidence.span_status(text, end=ev.end, hash=ev.hash, appendable=evidence.is_episode_id(ev.episode))
        if ev.end > len(text) or status == evidence.SPAN_STALE:
            kept.append(evidence.reasoning(ev.episode, hash=evidence.body_hash(text)))
            degraded += 1
            continue
        kept.append(ev)
    if degraded:
        claim = Claim.from_dict({**claim.to_dict(), "evidence": [e.to_dict() for e in kept]})
    return claim, degraded


def commit_message(lines: dict[str, int], today: date) -> str:
    return git_service.build_commit_message(
        f"{SUBJECT} {today.isoformat()}",
        [f"{rel}: updated (recovered: {n}, trigger: {TRIGGER})" for rel, n in sorted(lines.items())],
        authors=[AUTHOR],
    )


def apply(bank, *, sleep_holding: Callable[[], bool] | None = None, today: date | None = None) -> ApplyResult:
    """Put every recoverable claim back and commit the pages written, alone, as ``cicada``.

    Admission first, then the page lock, then git's write lock (G183's order); ``sleep_holding`` is asked once the
    admission is held — :func:`write_admission.holding` by default, the CLI also asks a running backend."""
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
    for item in plan.recoverable:
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
                parsed = markdown_parser.parse(path)
                claims = parse_claims(parsed.body, strict=True)
            except (OSError, MalformedClaimsBlockError):
                continue
            have = {c.id for c in claims}
            added: list[Claim] = []
            for item in items:
                if item.claim_id in have:
                    continue
                for claim in item.claims:
                    claim, degraded = _verified(bank, claim)
                    result.degraded_spans += degraded
                    added.append(claim)
            if not added:
                continue
            markdown_parser.write(path, parsed.frontmatter, write_claims(parsed.body, [*claims, *added]))
            written[rel] = len({c.id for c in added})
        if written:
            git_service.commit_paths_sync(bank, commit_message(written, today), sorted(written))
            result.commit = _head(bank)
    except BaseException:
        if written:
            git_service.run_git_write_sync(bank, "checkout", "--", *sorted(written))
        raise
    result.pages = sorted(written)
    result.recovered = sum(written.values())
    return result


# --- CLI ---------------------------------------------------------------------------------------------------------


def _backend_sleep_holding() -> bool:
    """This is its own process: Sleep's flag lives in the backend's, so ask it as the stdio MCP server does
    (``GET /sleep/status``; no backend answering means no cycle). The token is read, never created."""
    from api.services import mcp_tools, runtime_layout

    token = (os.environ.get("CICADA_API_TOKEN") or "").strip()
    if not token:
        home = Path(os.environ.get("CICADA_HOME") or Path.home() / ".cicada").expanduser()
        try:
            token = (home / "api_token").read_text(encoding="utf-8").strip()
        except OSError:
            token = ""
    headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})}
    return mcp_tools._backend_sleep_running(runtime_layout.backend_url(), headers)


def _print_counts(plan: Plan) -> None:
    counts = plan.counts()
    print(f"candidates: {counts['candidates']}")
    for reason, n in counts["excluded"].items():
        print(f"excluded ({reason}): {n}")
    print(f"recoverable: {counts['recoverable']}")
    print(f"pages affected: {counts['pages']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m api.services.claim_recovery",
                                     description="Recover claims a Sleep prose rewrite dropped (dry run by default).")
    parser.add_argument("--bank", required=True, help="the bank directory (a git repository)")
    parser.add_argument("--plan", help="write the plan (ids, page paths, commits — no claim text) to this file")
    parser.add_argument("--apply", action="store_true", help="re-add the recoverable claims and commit them")
    args = parser.parse_args(argv)
    bank = Path(args.bank).expanduser()
    try:
        if args.apply:
            result = apply(bank, sleep_holding=lambda: write_admission.holding() or _backend_sleep_holding())
            plan = result.plan or Plan(head="")
        else:
            plan = analyze(bank)
    except NotAGitBank:
        print(f"not a git bank: {bank}", file=sys.stderr)
        return 2
    except SleepIsWriting:
        print("Sleep is writing this bank's pages; nothing was changed. Run again once it finishes.", file=sys.stderr)
        return 3
    except write_admission.AdmissionUnavailable:
        print("the bank's write admission cannot be opened; nothing was changed.", file=sys.stderr)
        return 3
    _print_counts(plan)
    if args.plan:
        Path(args.plan).write_text(json.dumps(plan.to_dict(), indent=2) + "\n", encoding="utf-8")
    if args.apply:
        print(f"recovered: {result.recovered}")
        print(f"pages written: {len(result.pages)}")
        print(f"spans kept as reasoning: {result.degraded_spans}")
        if result.skipped_dirty:
            print(f"pages skipped (uncommitted edits): {len(result.skipped_dirty)}")
        print(f"commit: {result.commit or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
