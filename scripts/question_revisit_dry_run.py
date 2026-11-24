"""Dry run of Sleep's second look at open questions (`question_revisit`, ruling 82, 2026-11-24). Writes nothing.

One stable line per open question the step would look at, in the order it looks (`question_order`):

  inbox-123  merge_suggestion  would_join     revisit_one      ep_2026-10-03_001:12-61(user)
  inbox-124  merge_suggestion  read:two       -
  inbox-125  conflict          would_settle   said_on_record   ep_2026-10-01_001
  inbox-126  conflict          left:not_on_record -
  inbox-127  merge_suggestion  left:short_name_not_alone -
  inbox-128  merge_suggestion  would_read     revisit_one      -          (without --read: a model decides)
  inbox-129  name_no_page      would_join     revisit_same     ep_2026-10-03_001:12-61(user)
  inbox-130  name_no_page      would_apart    revisit_apart    -
  inbox-131  name_no_page      read:unsure    -
  inbox-132  name_no_page      left:said_apart -

  ``name_no_page`` is "Is <name> the same as <page>?" about a name with NO page (`name_revisit`): ``would_join`` files the
  name as an alias of the page and lands what is held (``revisit_same``, only on the person's own located line saying they
  are one thing); ``would_apart`` closes it as the person's "No, different" does (``revisit_apart``: the held lines stay
  held under their own name, nothing lands, no relation is written). Questions about one page are read together, so the
  summary prints the model calls per question read.

  the id, the kind, what it would do, the rule, and the ids of the evidence (a conversation and the offsets of the located
  words, and whose words they are: only the person's own turn or a named speaker's can be one). Never a name, a title or a
  word of text.

The reasons a pair is ``left:<why>`` without a read: ``same_title`` (two pages with one title: ruling 74a's), ``one_spelling``
(a spelling shared that is neither page's title), ``short_name_not_alone`` (another page of any type, another person or a
person held with no page could be whom a short name means), ``page_is_someone_in_full`` (a short-name page that carries
another full name), ``two_full_names`` (two full names sharing no spelling), ``kept_apart``, ``in_a_doubt``,
``alias_removed``, ``too_many_conversations`` (more conversations hold both names than can be shown: never cut),
``index_not_ready``, ``too_many_turns``, ``turn_too_long``, ``nothing_ties_them``, ``read_already`` (answered, nothing
changed; a read that produced nothing usable is read again up to twice). For a name with no page also: ``held_against_a_page``,
``said_apart``, ``kept_apart``, ``person_and_a_thing``, ``not_a_name`` (a reference or a pronoun), ``name_of_a_page`` (a page
already answers to it), ``title_of_another_page``, ``alias_removed``, ``not_this_name`` (a correspondent or a same-name
person), ``policy:<why>`` (the engine-free rules decide it or only the person does) and the person guards of a pair.

Without ``--read`` nothing is sent to a model: a question that passes its engine-free guards is listed ``would_read``. With
``--read`` the engine's main model reads at most ``--max-reads`` of them, twice each for a pair, exactly as Sleep would
(this is the person's own command, so a plan is theirs to spend), and the line says what the reads found. A read here is never
remembered, so the real run reads again. Questions the person took back or put off are never listed; questions of a kind
this step does not read are counted at the end.

Reads files and, with --read, calls the engine: no git write, no network but the engine's. Run it on the real bank and read
every line before this reaches a real Sleep.

Usage:
  api/.venv/bin/python scripts/question_revisit_dry_run.py --memory /path/to/bank
  api/.venv/bin/python scripts/question_revisit_dry_run.py --memory /path/to/bank --read --max-reads 6
  api/.venv/bin/python scripts/question_revisit_dry_run.py --memory /path/to/bank --summary

The output names ids from the bank: keep it out of commits, PRs and repo docs (the privacy rule).
"""

import argparse
import asyncio
import sys
from collections import Counter
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _evidence(rows: list) -> str:
    out = []
    for e in rows or []:
        if e.get("start") is not None:
            out.append(f"{e['episode']}:{e['start']}-{e['end']}({e.get('kind', '?')})")
        else:
            out.append(str(e.get("episode")))
    return ",".join(out) or "-"


async def _llm(read: bool):
    if not read:
        return None, ""
    from api.config import get_settings
    from api.services import engine_select, inbox_tend, same_name_tend

    strong, why = await same_name_tend.main_engine(get_settings(), user_triggered=True)
    if strong is None:
        print(f"no engine to read with ({why}): questions that need a read stay marked would_read", file=sys.stderr)
        return None, ""
    return inbox_tend.default_llm_fn(strong), engine_select.shown_model(strong)


async def _run(memory: Path, args) -> int:
    from api.config import get_settings
    from api.services import inbox_tend, question_revisit

    llm_fn, model = await _llm(args.read)
    rows: list[dict] = []
    report = await question_revisit.tend(memory, get_settings(), llm_fn, dry_run=True, trace=rows.append, model=model,
                                         max_reads=args.max_reads, max_looks=args.max_looks)
    counts: Counter = Counter()
    for row in rows:
        counts[(row["kind"], row["what"])] += 1
        if not args.summary:
            print(f"{row['id']:<14} {row['kind']:<16} {row['what']:<26} {row['rule'] or '-':<16} {_evidence(row['evidence'])}")
    left: Counter = Counter()
    today = date.today().isoformat()
    for _path, fm, _body in inbox_tend.pending(memory):
        kind = str(fm.get("kind") or "unknown")
        if inbox_tend._blocked(fm, today):
            left[f"{kind}: taken back, put off or the person's"] += 1
        elif kind not in ("merge_suggestion", *inbox_tend.RECORD_KINDS):
            left[f"{kind}: not read by this step"] += 1
    per = f", {report.calls / report.read:.2f} per question read" if report.read else ""
    print(f"\nlooked at {report.looked}, read {report.read} ({report.calls} model calls{per}), would settle {report.settled}")
    print("by kind and outcome: " + (", ".join(f"{k[0]} {k[1]} {n}" for k, n in sorted(counts.items())) or "none"))
    print("not looked at: " + (", ".join(f"{k} {n}" for k, n in sorted(left.items())) or "none"))
    if report.skipped:
        print("stopped or skipped: " + ", ".join(f"{k} {n}" for k, n in sorted(report.skipped.items())))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--memory", required=True, help="the bank directory (never defaulted)")
    parser.add_argument("--summary", action="store_true", help="counts only")
    parser.add_argument("--read", dest="read", action="store_true",
                        help="make the model reads (at most --max-reads questions), writing nothing")
    parser.add_argument("--no-read", dest="read", action="store_false", help="engine-free only (the default)")
    parser.add_argument("--max-reads", type=int, default=8, help="questions read with --read (the step's own cap)")
    parser.add_argument("--max-looks", type=int, default=100_000, help="questions looked at (the step's own cap is lower)")
    parser.set_defaults(read=False)
    args = parser.parse_args(argv)
    memory = Path(args.memory).expanduser()
    if not (memory / "inbox").is_dir():
        print(f"no inbox/ under {memory}", file=sys.stderr)
        return 2
    return asyncio.run(_run(memory, args))


if __name__ == "__main__":
    raise SystemExit(main())
