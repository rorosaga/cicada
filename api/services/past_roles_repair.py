"""Close the past roles a bank holds as current, and write a start as the belief it starts (2026-10-27) — dry run first.

**Why a bank needs it.** Until 2026-10-14 Stage 1 folded "worked at" into ``works-at`` (the seed's synonyms) and Stage 3
had no ending labels, so "<person> worked at <company>" — a past job, often a public figure's earlier employer — was
stored as a current place dated the day it was said, and the person card's "Works at" named it. The 2026-10-14 change
keeps a past tense as closed history for claims read since (``claim_reconciler._place_ending``), but nothing touched the
claims already written. The same was true of every predicate with no ending at all ("lived in", "studied at",
"reported to"; ``endings`` in the seed since 2026-10-27). And "joined <company>" stayed under its own label, so the card
never saw the job it starts; Stage 3 now writes a start under its canonical (``starts`` in the seed), and this does the
same for the claims already on a page.

**What changes — every check must pass; when in doubt, nothing.**

* ``close`` — an open claim whose predicate is one of a person's states (:data:`STATES`), whose own words carry one
  of that canonical's ``past`` or ``over`` labels ("Bob worked at Acme"; for :data:`ENDINGS_ONLY` only an ending — "worked
  on" and "worked with" report ongoing work) and none of its present ones ("works at", "works for"), and which is not the person's own
  (``is_human``) — becomes the closed history Stage 3 writes for a past tense with nothing open: ``valid_to =
  valid_from``. A present belief on the same object stays as it is. **Only when it rests on one conversation, or every
  quote it cites says the past or an ending:** a restatement only adds sources and never rewrites the claim's words,
  so "worked at" first and "works at" in later conversations is one open claim whose words are the first ones
  (``restated``, kept).
* ``close`` too — an open claim kept under an ending's own label that is a synonym of its canonical ("formerly worked
  at", "studied at" in a bank seeded before the synonym): moved under the canonical and closed the same way.
* ``start`` — an open claim under a ``starts`` label ("started working at") between the declared page types (a person and a
  company for ``works-at``): moved under the canonical, nothing else touched. Kept, counted, when the page already
  holds that belief current (``already_current``), held it and it ended after the start was said (``ended_since``, the
  reconciler's departure rule — never reopened), or the types do not fit (``types``).

A start never closes another place, and nothing here closes a current belief because a newer one exists — a person
holds several places at once (2026-10-14); which one wins is the owner's ruling to make, not this script's.

**Dry run (default)** prints counts by action and reason; ``--plan`` writes ids, page paths, predicates and reasons,
never claim text. **``--apply``** refuses unless Sleep is idle (``coexist_reopen``'s guards: admission, then the
backend's ``writing: false``), takes the page lock and git's write lock, re-makes the plan under them, skips a dirty or
unreadable page, writes each page through the one claims writer and commits only the pages written, alone, as
``cicada`` (``Close past roles <date>``), put back from HEAD on a failure. Nothing is deleted. A re-run finds nothing.

    python -m api.services.past_roles_repair --bank <path> [--plan <file>] [--apply]
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

from api.services import (claim_recovery, decay_policy, evidence, git_service, markdown_parser, page_lock, predicates,
                          write_admission)
from api.services.claim_reconciler import ended_since, is_human, open_, same_object
from api.services.claims import (
    Claim,
    MalformedClaimsBlockError,
    is_event,
    is_record,
    is_recovered_history,
    parse_claims,
    write_claims,
)

TRIGGER = "maintenance/past-roles"
AUTHOR = git_service.CICADA_AUTHOR
SUBJECT = "Close past roles"
LEDGER_SUFFIX = ".claims.jsonl"
#: A person's states: the canonicals whose past or ending words are history (never a tool's ``uses``).
STATES = ("works-at", "works-on", "works-with", "lives-in", "studies-at", "reports-to")
#: States whose past tense is no ending on its own, so only their ``over`` labels close a claim here: "I worked on
#: alpha-project today" or "worked with Bob this morning" reports ongoing work (review 2026-10-27). Stage 3's live rule
#: for "worked with" (2026-10-22) is unchanged; this repair does not apply it backwards to a bank's history.
ENDINGS_ONLY = ("works-on", "works-with")
CLOSE, START = "close", "start"

SleepIsWriting = claim_recovery.SleepIsWriting


class NotAGitBank(ValueError):
    """The path is not a git-versioned bank: a repair must be revertible."""


@dataclass
class Item:
    page: str
    claim_id: str
    action: str | None          # CLOSE | START | None (kept)
    reason: str
    predicate: str              # as the page holds it
    canonical: str | None = None

    def to_dict(self) -> dict:
        return {"page": self.page, "claim_id": self.claim_id, "action": self.action, "reason": self.reason,
                "predicate": self.predicate, "canonical": self.canonical}


@dataclass
class Plan:
    head: str
    items: list[Item] = field(default_factory=list)
    pages_skipped: dict[str, int] = field(default_factory=dict)

    @property
    def changes(self) -> list[Item]:
        return [i for i in self.items if i.action]

    def counts(self) -> dict:
        by: dict[str, int] = {}
        for i in self.items:
            key = f"{i.action or 'kept'}:{i.reason}"
            by[key] = by.get(key, 0) + 1
        return {"close": sum(1 for i in self.items if i.action == CLOSE),
                "start": sum(1 for i in self.items if i.action == START),
                "pages": len({i.page for i in self.changes}), "by_reason": dict(sorted(by.items())),
                "pages_skipped": dict(sorted(self.pages_skipped.items()))}

    def to_dict(self) -> dict:
        return {"head": self.head, "items": [i.to_dict() for i in self.items], "pages_skipped": self.pages_skipped}


@dataclass
class _Vocabulary:
    tenses: dict[str, tuple[set[str], set[str]]]   # canonical -> (past and over labels, present labels), slugged
    ending: predicates.EndingFn
    onset: predicates.OnsetFn


def _vocabulary(bank: Path) -> _Vocabulary:
    """Each canonical with endings: its past and over labels, and the labels that say it holds now — the canonical's
    own words and every synonym folding into it that is not itself an ending ("works for"). Seed ∪ bank."""
    sources = [predicates._load_seed_map(), predicates._read_runtime_map(bank)]
    endings: dict[str, set[str]] = {}
    synonyms: dict[str, set[str]] = {}
    for data in sources:
        if not isinstance(data, dict):
            continue
        for label, canonical in (data.get("synonyms") or {}).items():
            synonyms.setdefault(predicates._slugify_predicate(str(canonical)), set()).add(
                predicates._slugify_predicate(str(label)))
        for canonical, modes in (data.get("endings") or {}).items():
            if not isinstance(modes, dict):
                continue
            canon = predicates._slugify_predicate(str(canonical))
            modes_read = (predicates.ENDING_OVER,) if canon in ENDINGS_ONLY else (predicates.ENDING_OVER,
                                                                                   predicates.ENDING_PAST)
            for mode in modes_read:
                endings.setdefault(canon, set()).update(
                    predicates._slugify_predicate(str(label)) for label in modes.get(mode) or [])
    tenses = {canon: (labels, ({canon} | synonyms.get(canon, set())) - labels)
              for canon, labels in endings.items() if canon in STATES and labels}
    ending = predicates.build_endings_fn(bank)
    return _Vocabulary(tenses, ending, getattr(ending, "onset"))


def _says(text: str, labels: set[str]) -> bool:
    words = "-" + predicates._slugify_predicate(text or "") + "-"
    return any(label and f"-{label}-" in words for label in labels)


def _without(text: str, labels: set[str]) -> str:
    """``text`` slugged with every one of ``labels`` taken out, longest first."""
    words = "-" + predicates._slugify_predicate(text or "") + "-"
    for label in sorted((lb for lb in labels if lb), key=len, reverse=True):
        words = words.replace(f"-{label}-", "-")
    return words


def _head(bank: Path) -> str:
    try:
        return claim_recovery._head(bank)
    except git_service.GitError:
        return ""


def _conversations(c: Claim) -> set[str]:
    refs = {str(e) for e in c.source_episodes or [] if e}
    refs.update(str(ev.episode) for ev in c.evidence or [] if getattr(ev, "episode", None))
    return refs


def _every_quote_says(c: Claim, labels: set[str], quote_of: Callable[[object], str | None]) -> bool:
    """Every cited span reads one of ``labels`` — a reasoning entry or an unreadable span is no such quote."""
    quotes = [quote_of(ev) for ev in c.evidence or []]
    return bool(quotes) and all(q and _says(q, labels) for q in quotes)


def classify(c: Claim, page_claims: list[Claim], vocab: _Vocabulary, type_of: Callable[[str], str],
             quote_of: Callable[[object], str | None] = lambda _ev: None) -> tuple[str | None, str, str | None] | None:
    """``(action, reason, canonical)`` for one claim, or ``None`` when nothing here is about it. ``quote_of`` reads an
    evidence entry's quoted text (``None`` for a reasoning entry); the rest is pure."""
    if not open_(c) or c.superseded_by or is_event(c) or is_record(c) or is_recovered_history(c):
        return None
    if c.predicate in vocab.tenses:
        ended, present = vocab.tenses[c.predicate]
        if not _says(c.text, ended):
            return None
        if _says(_without(c.text, ended), present):   # "previously worked on" holds "worked on": not present words
            return None, "present_words", c.predicate
        if is_human(c):
            return None, "persons_own", c.predicate
        if len(_conversations(c)) > 1 and not _every_quote_says(c, ended, quote_of):
            return None, "restated", c.predicate
        return CLOSE, "past_words", c.predicate
    hit = vocab.ending(c.predicate)
    if hit is not None and hit.synonym and hit.canonical in vocab.tenses:
        # An ending under its own label (a bank seeded before the synonym): the canonical's closed history.
        if is_human(c):
            return None, "persons_own", hit.canonical
        return CLOSE, "ending_label", hit.canonical
    start = vocab.onset(c.predicate)
    if start is None or c.object_kind != "node":
        return None
    if not start.fits(type_of(c.subject), type_of(c.object)):
        return None, "types", start.canonical
    if any(o is not c and open_(o) and not o.superseded_by and o.predicate == start.canonical
           and o.context == c.context and o.observer == c.observer and same_object(o, c) for o in page_claims):
        return None, "already_current", start.canonical
    if ended_since(c, page_claims, start.canonical, c.valid_from):
        # The belief it starts held and ended after it was said ("enrolled at" before "graduated"): writing it under
        # the canonical would reopen what finished — the live reconciler's departure rule (2026-10-29).
        return None, "ended_since", start.canonical
    return START, "start_label", start.canonical


def analyze(bank) -> Plan:
    """Classify every open claim on every page, archived ones included. Reads only; writes nothing."""
    bank = Path(bank)
    if not (bank / ".git").exists():
        raise NotAGitBank(str(bank))
    plan = Plan(head=_head(bank))
    vocab = _vocabulary(bank)
    lookup = decay_policy.subject_lookup(bank)

    def type_of(entity_id: str) -> str:
        return lookup(entity_id).entity_type

    texts: dict[str, str | None] = {}

    def quote_of(ev) -> str | None:
        if not getattr(ev, "is_span", lambda: False)():
            return None
        doc = str(ev.episode or "")
        if doc not in texts:
            texts[doc] = evidence.source_text(bank, doc)
        text = texts[doc]
        return text[ev.start:ev.end] if text else None

    for path in sorted((bank / "entities").glob("*.md")):
        rel = f"entities/{path.name}"
        try:
            parsed = markdown_parser.parse(path)
            page_claims = parse_claims(parsed.body, strict=True)
        except (OSError, ValueError, MalformedClaimsBlockError):
            plan.pages_skipped["unreadable"] = plan.pages_skipped.get("unreadable", 0) + 1
            continue
        if not page_claims:
            continue
        # An archived page is repaired too: a mention brings it back with its claims, and a past job must not return
        # as a current one.
        for c in page_claims:
            verdict = classify(c, page_claims, vocab, type_of, quote_of)
            if verdict is not None:
                action, reason, canonical = verdict
                plan.items.append(Item(rel, c.id, action, reason, c.predicate, canonical))
    return plan


def change(c: Claim, item: Item) -> bool:
    """Apply one planned change to ``c`` in place; ``False`` when it no longer applies (re-read under the locks)."""
    if not open_(c) or c.superseded_by or not item.canonical:
        return False
    if item.action == CLOSE:
        c.predicate = item.canonical
        c.valid_to = c.valid_from or (c.recorded_at or None)
        return c.valid_to is not None
    if item.action == START:
        c.predicate = item.canonical
        return True
    return False


@dataclass
class ApplyResult:
    plan: Plan | None = None
    pages: list[str] = field(default_factory=list)
    closed: int = 0
    started: int = 0
    skipped_dirty: list[str] = field(default_factory=list)
    skipped_unreadable: list[str] = field(default_factory=list)
    commit: str | None = None


def _ledger_rel(page: str) -> str:
    return page[: -len(".md")] + LEDGER_SUFFIX


def commit_message(lines: dict[str, tuple[int, int]], today: date) -> str:
    return git_service.build_commit_message(
        f"{SUBJECT} {today.isoformat()}",
        [f"{rel}: updated (closed: {c}, started: {s}, trigger: {TRIGGER})" for rel, (c, s) in sorted(lines.items())],
        authors=[AUTHOR],
    )


def apply(bank, *, sleep_holding: Callable[[], bool] | None = None, today: date | None = None) -> ApplyResult:
    """Make every planned change and commit the pages written, alone, as ``cicada``. Admission first, Sleep asked once
    it is held, then the page lock, then git's write lock (G183's order); the plan is re-made under them."""
    bank = Path(bank)
    if not (bank / ".git").exists():
        raise NotAGitBank(str(bank))
    holding = sleep_holding or write_admission.holding
    today = today or date.today()
    with write_admission.shared(bank):
        if holding():
            raise SleepIsWriting(str(bank))
        with page_lock.page_lock(bank), git_service.write_lock(bank):
            plan = analyze(bank)
            return _apply_locked(bank, plan, today)


def _apply_locked(bank: Path, plan: Plan, today: date) -> ApplyResult:
    result = ApplyResult(plan=plan)
    by_page: dict[str, list[Item]] = {}
    for item in plan.changes:
        by_page.setdefault(item.page, []).append(item)
    if not by_page:
        return result
    dirty = git_service.dirty_paths_sync(bank, *by_page, *(_ledger_rel(p) for p in by_page))
    written: dict[str, tuple[int, int]] = {}
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
            closed = started = 0
            for item in items:
                c = by_id.get(item.claim_id)
                if c is None or not change(c, item):
                    continue
                closed += item.action == CLOSE
                started += item.action == START
            if not (closed or started):
                continue
            markdown_parser.write(path, parsed.frontmatter, write_claims(parsed.body, page_claims))
            written[rel] = (closed, started)
        if written:
            git_service.commit_paths_sync(bank, commit_message(written, today), sorted(written))
            result.commit = claim_recovery._head(bank)
    except BaseException:
        if written:
            # Every page written was clean at HEAD, so HEAD is exactly what was there.
            git_service.run_git_write_sync(bank, "checkout", "HEAD", "--", *sorted(written))
        raise
    result.pages = sorted(written)
    result.closed = sum(c for c, _ in written.values())
    result.started = sum(s for _, s in written.values())
    return result


# --- CLI ---------------------------------------------------------------------------------------------------------


def _print_counts(plan: Plan) -> None:
    counts = plan.counts()
    print(f"would close: {counts['close']}, would start: {counts['start']}, on {counts['pages']} pages")
    for key, n in counts["by_reason"].items():
        print(f"  {key}: {n}")
    for reason, n in counts["pages_skipped"].items():
        print(f"pages skipped ({reason}): {n}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m api.services.past_roles_repair",
                                     description="Close past roles held as current and write starts as the belief "
                                                 "they start (dry run by default).")
    parser.add_argument("--bank", required=True, help="the bank directory (a git repository)")
    parser.add_argument("--plan", help="write the plan (ids, page paths, predicates, reasons — no claim text) here")
    parser.add_argument("--apply", action="store_true", help="make the changes, in one commit")
    args = parser.parse_args(argv)
    bank = Path(args.bank).expanduser()
    try:
        if args.apply:
            result = apply(bank, sleep_holding=lambda: write_admission.holding()
                           or claim_recovery.backend_sleep_holding())
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
        print(f"closed: {result.closed}, started: {result.started}, on {len(result.pages)} pages")
        if result.skipped_dirty:
            print(f"pages skipped (uncommitted edits): {len(result.skipped_dirty)}")
        if result.skipped_unreadable:
            print(f"pages skipped (unreadable fence): {len(result.skipped_unreadable)}")
        print(f"commit: {result.commit or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
