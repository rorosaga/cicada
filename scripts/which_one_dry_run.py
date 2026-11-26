"""Dry run of "context decides which one was meant" (`which_one_reader`, ruling 83, 2026-11-26). Writes nothing to the bank.

One stable line per open which-one question and conversation the reader would look at, in the order it looks (`question_order`),
plus one for each pairwise "same as?" question about a mention tonight's rewrite (`which_one.tend`) would turn into one:

  inbox-123  ep_2026-10-03_001  page-a,page-b  named:page-a        -
  inbox-123  ep_2026-10-04_001  page-a,page-b  named:page-a        -
  inbox-123  -                  page-a,page-b  would_file:page-a   which_one_read
  inbox-124  ep_2026-10-03_001  page-a,page-b  left:nothing_tells_them_apart  -
  inbox-124  -                  page-a,page-b  read:left:nothing_tells_them_apart -
  inbox-125  -                  page-a,page-b  left:subject_has_page -
  inbox-126  ep_2026-10-05_001  page-a,page-b  would_read          which_one_read     (without --read: a model decides)
  inbox-127  -                  page-a,page-b  would_convert       which_one_folded   (a pairwise question the rewrite changes first)

  the question id, the conversation id (``-`` for the question as a whole), the candidates' page ids, the outcome and the rule.
  Never a name or a word of text. ``named:<page>`` is what one conversation's two reads agreed on and the code accepted;
  ``would_file`` is the question as a whole, which needs every conversation the held line holds to name the same page.

The reasons a question is ``left:<why>`` without a read: ``subject_has_page`` (the mention shares its id with a page: filing is the
person's call), ``nothing_held`` (no line holds it: nothing to file), ``one_candidate`` (after what the person already said),
``guard:<why>`` (a person guard of the second look: owner or archived, a relation's page, kept apart, in a doubt, an alias
removed, a page that carries another full name, two full names), ``conversation_unreadable``, ``too_many_conversations`` (a filing
lifts the whole held line, so every conversation it holds must be read: at most 3). A dry run reads again what Sleep remembers.
With a read: ``first_read_none`` / ``first_read_cannot_tell`` / ``first_read_sentence_not_located`` /
``first_read_not_the_persons_words`` / ``nothing_tells_them_apart`` (the record holds nothing for the pick that the words say, or
says something for another candidate too) / ``second_read_*`` / ``reads_disagree`` / ``mention_not_in_the_persons_turns`` /
``conversations_differ``.

Without ``--read`` nothing is sent to a model. With ``--read`` the engine's main model reads at most ``--max-reads`` questions,
twice a conversation, exactly as Sleep would (this is the person's own command, so a plan is theirs to spend); a read here is never
remembered. ``--eyes FILE`` (refused inside the repository) writes the same lines with the mention, the sentence the model copied
(located in the person's own turn), the page's name and what tied them, for the owner's eyes only.

A demo bank (`demo_guard`) is refused up front, with or without --read.

Reads files and, with --read, calls the engine: no git write, no network but the engine's. Run it on the real bank and read every
line before this reaches a real Sleep.

Usage:
  api/.venv/bin/python scripts/which_one_dry_run.py --memory /path/to/bank
  api/.venv/bin/python scripts/which_one_dry_run.py --memory /path/to/bank --read --max-reads 6 --eyes ~/which-one-eyes.txt

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


def _line(row: dict) -> str:
    return f"{row['id']:<14} {row['episode']:<20} {','.join(row['candidates']) or '-':<28} {row['what']:<44} {row['rule'] or '-'}"


def _eyes(row: dict) -> str:
    e = row.get("eyes") or {}
    if not e:
        return _line(row)
    bits = [f"mention={e.get('mention', '')!r}", f"page={e.get('page', '')!r}"]
    if e.get("sentence"):
        bits.append(f"sentence={e['sentence']!r}")
    if e.get("tied_by"):
        bits.append("tied_by=" + ",".join(e["tied_by"]))
    return f"{_line(row)}  | " + " ".join(bits)


def _convertible(memory: Path, today: str) -> list[tuple[Path, dict]]:
    """The pairwise "same as?" questions `which_one.tend` would rewrite tonight, as the question it would make (one a mention):
    ``(path, the question as it would read)``. Nothing is written."""
    from api.services import inbox_tend, which_one
    from api.services.id_utils import sanitize_id

    seen: set[str] = set()
    out = []
    for path, fm, _body in inbox_tend.pending(memory):
        if (str(fm.get("kind") or "") != "merge_suggestion" or fm.get("detected") or fm.get("heard_in") or fm.get("fold_page")
                or inbox_tend._blocked(fm, today) or not which_one._mention_like(memory, fm)):
            continue
        mention = " ".join(str(fm.get("entity_name") or "").split())
        key = sanitize_id(mention)
        if not mention or key in seen:
            continue
        hint = str(fm.get("merge_target_hint") or "")
        ids = which_one.candidates_for(memory, mention, [hint])
        if len(ids) < 2 or (hint and hint not in ids):
            continue   # the page the question is about may not be offered: it stays the question it is
        seen.add(key)
        out.append((path, {**fm, **which_one.fields(memory, mention, ids), "held_mention": True}))
    return out


async def _ask(read: bool):
    if not read:
        return None
    from api.config import get_settings
    from api.services import full_name_join, same_name_tend

    strong, why = await same_name_tend.main_engine(get_settings(), user_triggered=True)
    if strong is None:
        print(f"no engine to read with ({why}): questions that need a read stay marked would_read", file=sys.stderr)
        return None

    async def ask(system: str, prompt: str) -> object:
        return await full_name_join.ask_main(strong, system, prompt)

    return ask


async def _run(memory: Path, args, eyes) -> int:
    from api.config import get_settings
    from api.services import which_one_reader as wr

    today = date.today().isoformat()
    ask = await _ask(args.read)
    own = await asyncio.to_thread(wr.eligible, memory, today)
    convert = await asyncio.to_thread(_convertible, memory, today)
    rows: list[dict] = [{"id": p.stem, "episode": "-", "candidates": list(fm["same_title"]), "what": "would_convert",
                         "rule": "which_one_folded"} for p, fm in convert]
    report = await wr.tend(memory, get_settings(), ask, dry_run=True, trace=rows.append, max_reads=args.max_reads,
                           max_looks=args.max_looks, rows=[*own, *convert])
    counts: Counter = Counter()
    for row in rows:
        if row["episode"] == "-":
            counts[row["what"].split(":")[0] if row["what"].startswith("would") else row["what"]] += 1
        if not args.summary:
            print(_line(row))
        if eyes is not None:
            eyes.write(_eyes(row) + "\n")
    per = f", {report.calls / report.read:.2f} per question read" if report.read else ""
    print(f"\nlooked at {report.looked}, read {report.read} ({report.calls} model calls{per}), would file {report.settled}; "
          f"{len(convert)} pairwise question(s) would be converted first")
    print("outcomes per question: " + (", ".join(f"{k} {n}" for k, n in sorted(counts.items())) or "none"))
    if report.skipped:
        print("stopped or skipped: " + ", ".join(f"{k} {n}" for k, n in sorted(report.skipped.items())))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--memory", required=True, help="the bank directory (never defaulted)")
    parser.add_argument("--summary", action="store_true", help="counts only")
    parser.add_argument("--read", action="store_true", help="make the model reads (at most --max-reads questions), writing nothing")
    parser.add_argument("--max-reads", type=int, default=8, help="questions read with --read")
    parser.add_argument("--max-looks", type=int, default=100_000, help="questions looked at")
    parser.add_argument("--eyes", type=Path, help="also write the lines with the words, for the owner's eyes (outside the repository)")
    args = parser.parse_args(argv)
    memory = Path(args.memory).expanduser().resolve()
    if not memory.is_dir():
        print(f"not a bank: {memory}", file=sys.stderr)
        return 2
    from api.services import demo_guard

    if demo_guard.is_demo(memory):
        print("a demo bank is never read, with or without --read: it is synthetic and no model reads it", file=sys.stderr)
        return 2
    eyes = None
    if args.eyes is not None:
        target = args.eyes.expanduser().resolve()
        if target == REPO_ROOT or REPO_ROOT in target.parents:
            print("--eyes is refused inside the repository: it carries words from the bank", file=sys.stderr)
            return 2
        eyes = target.open("w", encoding="utf-8")
    try:
        return asyncio.run(_run(memory, args, eyes))
    finally:
        if eyes is not None:
            eyes.close()


if __name__ == "__main__":
    raise SystemExit(main())
