"""Dry run of Cicada's own agent (`harness_questions`, ruling 84, 2026-11-25). Writes nothing to the bank.

Without --work: what a run would really start a session for, in the order it works them: the id, the kind, the compartments each
would use (private: files and conversation copies, no web; web: search and fetch, no files) and whether a public thing or not (the
test that decides it), then how many open questions it leaves and why (the person's own words, not two separate people, worked
already, nothing to read...), and the folders it would grant and why it would not grant the others (counts by kind). With --work N
(default 1 when given; keep it small): the agent really works the first N of those, on this machine, with this person's own files
and the public web. Before each question this prints the compartments it will use and what the web one may fetch; while it works,
every call as it is made (a search, an address, a file); after it, what it concluded, what the code's gate would do with it
(``would_settle`` / ``would_note`` / ``left:<why>``), the evidence it cited, what was dropped before storage, what it scanned (files,
bytes, folders, refusals) and the audit. Nothing is settled, noted or remembered.

--attended lets the private session read Documents, Desktop and Downloads (this shell's own permissions; a scheduled run
never does). It uses the Claude plan: a metered key or another engine is refused. The signed-in browser is the third compartment: it
is listed (and used by --work) only when the person connected a site for reading and their own browser-harness daemon is already
running; this script never starts a browser, and says in words when it skipped the compartment.

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
    from api.services import harness_questions as hq, markdown_parser, web_lookup

    memory = Path(args.memory).resolve()
    settings = Settings(memory_path=memory)
    rows = await asyncio.to_thread(hq.candidates, memory)
    grant = await asyncio.to_thread(hq.home_grant, memory, attended=args.attended)
    browse = hq.Browse()
    sites = await asyncio.to_thread(browse.connected)
    if sites:
        await asyncio.to_thread(browse.check)
    print("signed-in browser: " + (f"{len(sites)} connected site(s) ({', '.join(sorted(sites))}); "
                                   + ("the person's own browser answers" if browse.ready else f"skipped: {browse.why}")
                                   if sites else "no site connected for reading, not used"))
    ready, left = await asyncio.to_thread(hq.plan_run, memory, rows, grant, browse=browse)
    print(f"{len(rows)} open questions of the kinds this agent works; a run would start a session for {len(ready)}"
          f" (it takes {hq.PER_RUN} a run, in this order):")
    for i, p in enumerate(ready[:40]):
        print(f"  {'*' if i < hq.PER_RUN else ' '} {p.path.stem}  {p.kind}  {' then '.join(p.compartments)}"
              f"  ({'public' if p.public else 'private: ' + p.why_public})")
    print(f"  it leaves {sum(left.values())}: " + (", ".join(f"{n} {why}" for why, n in sorted(left.items())) or "none"))
    print(f"  folders it would let the private session read: {len(grant.roots)} "
          f"({', '.join(Path(r).name for r in grant.roots) or 'none'}); not granted, by kind: "
          + (", ".join(f"{n} {why}" for why, n in sorted(grant.why_counts().items())) or "none")
          + f"; {grant.walked} entries walked, {len(grant.deny)} deny rules")
    if not args.work:
        return 0
    resolved, _label, why = await web_lookup.engine_for(settings, user_triggered=True)
    if resolved is None or why != "plan":
        print(f"not run: the agent runs on a signed-in Claude plan only ({why})")
        return 1
    from api.services import same_name_tend

    model = args.model or str(getattr(same_name_tend.main_tier(resolved), "agent_model", "") or "") or "sonnet"
    for planned in ready[:args.work]:
        path = planned.path
        fm = dict(markdown_parser.parse(path).frontmatter)
        print(f"\n== {path.stem} ({planned.kind}) on {model}")
        print("   compartments: " + " then ".join(planned.compartments))
        out = await hq.work_one(memory, settings, path, fm, model, apply=False, grant=grant, public=planned.public, browse=browse,
                                on_call=lambda c: print(f"   -> {c.line()['tool']}: {c.what[:160]}" + ("  [REFUSED]" if c.denied else "")))
        print(f"   concluded: {out.concluded}")
        print(f"   gate: {out.what}  answer: {out.answer!r}  ({out.calls} calls, {out.seconds}s, {out.denied} refused, "
              f"{out.dropped} dropped before storage; {[c['in'] + (':' + c['stopped'] if c['stopped'] else '') for c in out.compartments]})")
        print(f"   scanned: {out.scan}")
        for e in out.evidence:
            print(f"   evidence: {e['where']}  \"{e['quote']}\"")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
