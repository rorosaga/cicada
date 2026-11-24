"""Dry run of Cicada's own agent (`harness_questions`, ruling 83, 2026-11-25). Writes nothing to the bank.

Without --work: one line per open question the agent would work, in the order it works them: the id and the kind, nothing
else (no name, no title). With --work N (default 1 when given; keep it small): the agent really works the first N, on this
machine, with this person's own files, web and browser. Before each question this prints the tools it will hold and the
folders it may read; while it works, every call it makes as it makes it (a search, an address, a file); after it, what it
concluded, what the code's gate would do with it (``would_settle`` / ``would_note`` / ``left:<why>``), the evidence it cited
and the audit. Nothing is settled, noted or remembered.

--attended lets it read Documents, Desktop and Downloads (this shell's own permissions; a scheduled run never does).
It uses the Claude plan: a metered key or another engine is refused.

Usage:
  api/.venv/bin/python scripts/harness_agent_dry_run.py --memory /path/to/bank
  api/.venv/bin/python scripts/harness_agent_dry_run.py --memory /path/to/bank --work 2 --attended

The output names ids and quotes from the bank and the person's files: keep it out of commits, PRs and repo docs.
"""
import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--memory", required=True)
    ap.add_argument("--work", type=int, default=0, metavar="N")
    ap.add_argument("--attended", action="store_true")
    ap.add_argument("--model", default="")
    args = ap.parse_args()

    from api.config import Settings
    from api.services import harness_agent as ha, harness_questions as hq, markdown_parser, web_lookup

    memory = Path(args.memory).resolve()
    settings = Settings(memory_path=memory)
    rows = await asyncio.to_thread(hq.candidates, memory)
    print(f"{len(rows)} open questions this agent may work")
    for path, fm in rows[:40]:
        print(f"  {path.stem}  {fm.get('kind')}")
    if not args.work:
        return 0
    resolved, _label, why = await web_lookup.engine_for(settings, user_triggered=True)
    if resolved is None or why != "plan":
        print(f"not run: the agent runs on a signed-in Claude plan only ({why})")
        return 1
    from api.services import same_name_tend

    model = args.model or str(getattr(same_name_tend.main_tier(resolved), "agent_model", "") or "") or "sonnet"
    policy = await asyncio.to_thread(hq.make_policy, memory, attended=args.attended)
    for path, fm in rows[:args.work]:
        fm = dict(markdown_parser.parse(path).frontmatter)
        print(f"\n== {path.stem} ({fm.get('kind')}) on {model}")
        print("   tools: files (Read, Glob, Grep), web search and fetch" + (", the browser, read-only" if policy.browser else
                                                                          " (no browser reachable: skipped)"))
        print("   folders it may read: " + ", ".join(Path(r).name or r for r in policy.roots))
        out = await hq.work_one(memory, settings, path, fm, policy, model, apply=False,
                                on_call=lambda c: print(f"   -> {c.line()['tool']}: {c.what[:160]}" + ("  [REFUSED]" if c.denied else "")))
        print(f"   concluded: {out.concluded}")
        print(f"   gate: {out.what}  answer: {out.answer!r}  ({out.calls} calls, {out.seconds}s, {out.denied} refused)")
        for e in out.evidence:
            print(f"   evidence: {e['where']}  \"{e['quote']}\"")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
