"""Dry run of Sleep's tending of questions the record already answers (ruling 74c, 2026-11-24). Writes nothing.

For every open question, prints what the engine-free rules (`answered_questions`, read by `inbox_tend.policy`) WOULD settle
and why, by id and rule only — no names, no text:

  inbox-123  merge_suggestion  already_one_page      both ends are one page through redirects
  inbox-124  merge_suggestion  already_a_name (lands what is held)   the asked name is already a name of the page; a
                                                                 line still holds what was said under it, which lands there
  inbox-125  merge_suggestion  subject_gone          nothing waits under the name: the older rule closes it
  inbox-126  conflict          names_one_page        every value is a name of one page

and, in a second list, EVERY engine-free settle the tending would now make that JOINS or FOLDS pages, whatever the rule
(``two_signals``, ``same_spelling``, ``already_a_name`` landing a held line, any other whose request is a merge), marked
JOIN, by id and rule only. ``two_signals`` (ruling 74) was never live for an existing question before the resolver
change of 74c (a ``person_duplicate`` question is a page question now): read this list before the merge. Third, the
questions Sleep's typo join (``typo_join``, ruling 74c) would put to a model read at the end of a cycle — not settles,
reads: ``READ`` with the guard's shape only. And, at the end, how many open questions of each kind stay (the others are
untouched). A question the person took back (``sleep_settle: undone``) or put off is never listed.

Reads files only: no backend, no git, no model, no network, no index. Run it on the real bank and read it; the tending
itself settles exactly these, as Sleep's own commits listed under "Settled by Sleep", each undoable.

Usage:
  api/.venv/bin/python scripts/answered_questions_dry_run.py --memory /path/to/bank
  api/.venv/bin/python scripts/answered_questions_dry_run.py --memory /path/to/bank --summary   # counts only
  api/.venv/bin/python scripts/answered_questions_dry_run.py --memory /path/to/bank --read      # also READ the pairs a model decides
  api/.venv/bin/python scripts/answered_questions_dry_run.py --memory /path/to/bank --no-read    # (the default) engine-free only

The output names ids from the bank: keep it out of commits, PRs and repo docs (the privacy rule).
"""

import argparse
import sys
from collections import Counter
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def typo_reads(memory: Path, today: str, *, summary: bool) -> int:
    """The candidates the typo join would read (ids only, with the engine-free guards' verdict): reads only."""
    from api.services import typo_join

    n = 0
    for path, fm in typo_join.all_candidates(memory):
        case, why = typo_join.guards(memory, path, fm, today=today)
        if case is None:
            continue
        n += 1
        if not summary:
            print(f"{(path.stem if path is not None else 'held-' + str(fm.get('entity_id'))):<14} merge_suggestion  READ  typo_one  "
                  f"(a model copies one line about each side; read twice; else nothing changes)")
    return n


def alias_pairs(memory: Path, *, read: bool, max_reads: int, summary: bool) -> Counter:
    """One line per pair (ids and rule only): what the alias-collision tending would do. Writes nothing — a read here is
    never remembered, so the real run reads again. One event loop for the engine and every read."""
    import asyncio

    return asyncio.run(_alias_pairs(memory, read=read, max_reads=max_reads, summary=summary))


async def _alias_pairs(memory: Path, *, read: bool, max_reads: int, summary: bool) -> Counter:
    from api.services import alias_collisions, bank_index

    judge = await _engine_judge() if read else None
    counts: Counter = Counter()
    left = max_reads
    today = date.today().isoformat()
    held = alias_collisions.held_pairs(memory, today)
    for pair in alias_collisions.pairs(memory):
        fa = bank_index.file(memory, "entities", f"{pair.a}.md")
        fb = bank_index.file(memory, "entities", f"{pair.b}.md")
        types = "/".join(str(((f.frontmatter if f else None) or {}).get("type") or "?") for f in (fa, fb))
        plan = alias_collisions.triage(memory, pair)
        rule, why = plan.rule or "skip", plan.why
        if pair.key in held:
            # A question the person took back or put off is theirs: the tending reads, closes and asks nothing for the pair.
            rule, why = "skip", "person_holds"
            asked = [p.stem for p, _fm, key in alias_collisions._questions(memory) if key == pair.key]
            counts[rule] += 1
            if not summary:
                print(f"ALIAS {pair.a} {pair.b} {'mutual' if pair.mutual else 'one-way'} {types} {rule} {why}"
                      + (f" questions: {','.join(asked)} (left as they are)" if asked else ""))
            continue
        if plan.rule == "read" and judge is not None and left > 0:
            left -= 1
            plan = await alias_collisions.assess(memory, pair, judge)
            rule, why = plan.rule, plan.why
        elif plan.rule == "read":
            why = "needs_a_model_read" if judge is None else "over_the_cap"
        # Only a question the tending would CLOSE is listed: a doubt (held, remembered) closes nothing, and an `ask` rewrites one.
        asked = ([p.stem for p, _fm in alias_collisions.open_questions(memory, pair, today)]
                 if rule != alias_collisions.DOUBT else [])
        counts[rule] += 1
        if not summary:
            print(f"ALIAS {pair.a} {pair.b} {'mutual' if pair.mutual else 'one-way'} {types} {rule} {why}"
                  + (f" questions: {','.join(asked)}" if asked else "")
                  + (" (held, nothing closed)" if rule == alias_collisions.DOUBT else ""))
    return counts


async def _engine_judge():
    """The main model of the engine Sleep would run, as the dry run's reader (this is the person's own command, so a plan
    is theirs to spend). ``None`` when no engine answers."""
    from api.config import get_settings
    from api.services import full_name_join, same_name_tend

    strong, why = await same_name_tend.main_engine(get_settings(), user_triggered=True)
    if strong is None:
        print(f"no engine to read with ({why}): the pairs that need a read stay marked read", file=sys.stderr)
        return None

    async def judge(system: str, prompt: str):
        return await full_name_join.ask_main(strong, system, prompt)
    return judge


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--memory", required=True, help="the bank directory (never defaulted)")
    parser.add_argument("--summary", action="store_true", help="counts only")
    parser.add_argument("--read", dest="read", action="store_true",
                        help="also read, with the engine's main model, the alias pairs that need it (at most --max-reads)")
    parser.add_argument("--no-read", dest="read", action="store_false", help="engine-free only (the default)")
    parser.add_argument("--max-reads", type=int, default=8, help="pairs read with --read (the tending's own cap)")
    parser.set_defaults(read=False)
    args = parser.parse_args(argv)
    memory = Path(args.memory).expanduser()
    if not (memory / "inbox").is_dir():
        print(f"no inbox/ under {memory}", file=sys.stderr)
        return 2
    from api.services import answered_questions, inbox_questions, inbox_tend

    today = date.today().isoformat()
    would: Counter = Counter()
    joins: Counter = Counter()
    stays: Counter = Counter()
    for path, fm, _body in inbox_tend.pending(memory):
        kind = str(fm.get("kind") or "")
        if kind not in ("merge_suggestion", "conflict"):
            stays[kind or "unknown"] += 1
            continue
        if str(fm.get("sleep_settle") or "") == "undone" or inbox_questions.is_deferred(fm, today):
            stays[f"{kind}: taken back or put off"] += 1
            continue
        found = (answered_questions.pair_answer(memory, fm) if kind == "merge_suggestion"
                 else answered_questions.labels_one_page(memory, fm))
        decided, why = None, ""
        if found is not None or kind == "merge_suggestion":
            # Only these go through the policy (it decides before any judge or index read), so the rule printed is the one
            # the tending would settle it by: an older rule (`subject_gone`) may come first.
            decided, why = inbox_tend.policy(memory, path, fm, today=today)
        if decided is not None and (decided.request or {}).get("action") == "merge":
            # A settle that JOINS or FOLDS pages, whichever rule makes it: listed whether or not this PR made it possible.
            joins[(decided.rule, str(fm.get("detected") or "ordinary"))] += 1
            would[(kind, decided.rule + " (lands what is held)" if decided.rule == answered_questions.A_NAME else decided.rule)] += 1
            if not args.summary:
                print(f"{path.stem:<14} {kind:<16} JOIN  {decided.rule}  ({fm.get('detected') or 'ordinary question'})")
            continue
        if found is None:
            stays[kind] += 1
            continue
        label = decided.rule if decided is not None else f"stays: {why}"
        would[(kind, label)] += 1
        if not args.summary:
            print(f"{path.stem:<14} {kind:<16} {label}")
    reads = typo_reads(memory, today, summary=args.summary)
    alias = alias_pairs(memory, read=args.read, max_reads=args.max_reads, summary=args.summary)
    total = sum(would.values())
    print(f"\nwould settle {total}: "
          + (", ".join(f"{k[0]} {k[1]} {n}" for k, n in sorted(would.items())) or "none"))
    print("would JOIN or FOLD pages: " + (", ".join(f"{r} ({d}) {n}" for (r, d), n in sorted(joins.items())) or "none"))
    print(f"would be READ by the typo join (a model decides, nothing settled here): {reads}")
    print("alias collisions, by what the tending would do: " + (", ".join(f"{k} {n}" for k, n in sorted(alias.items())) or "none"))
    print("stay as they are: " + (", ".join(f"{k} {n}" for k, n in sorted(stays.items())) or "none"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
