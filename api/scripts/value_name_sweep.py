"""Sweep what a memory already holds wrong: doubled values and people held under a qualified name (G148) — plan first
(writes nothing), then apply (no model).

    api/.venv/bin/python -m api.scripts.value_name_sweep plan  --bank <path> --out <dir>                    # census + every name row, no model
    api/.venv/bin/python -m api.scripts.value_name_sweep plan  --bank <path> --out <dir> --judge --max-calls 150
    api/.venv/bin/python -m api.scripts.value_name_sweep apply --bank <path> --plan <dir> --check           # what would be written
    api/.venv/bin/python -m api.scripts.value_name_sweep apply --bank <path> --plan <dir>                   # one `cicada` commit

Two passes, one tool (``--pass values|names|both``, both by default): they share the plan directory, the review text, the
admission and the one commit, and are struck, checked and undone the same way.

**plan** prints, before the first model call, counts only: pages with a value that could be joined to an older one, held
lines written ``Name (qualifier)``, pages titled so, and the most calls that is. The **names pass never uses a model**: it
turns an old line into the shape Sleep writes today (a second person held in doubt, or, when nobody else answers to the bare
name, the bare name's person) and joins nobody, so ``names.jsonl`` and its rows in ``review.txt`` are written on every
plan. The **values pass** needs ``--judge`` (the Claude plan; ``--model`` the main model that reads the values): it writes
one row per page (``values.jsonl``) as it goes. ``review.txt`` opens with what to strike, then shows every pair and every
line, what would change, and the reader's own words. A page whose call failed is not finished: it is listed in
``review.txt`` as not read, and the same command, run again, reads it. ``--out`` must be outside the repository and the bank.
**Strike** a row before applying: delete it, set ``"strike": true``, or name it (``--skip-page``, ``--skip-group
<page>#<n>``, ``--skip-line <name>``).

**apply** makes no model call and writes exactly the reviewed rows, under the bank's admission, page lock and git lock, as ONE
commit authored ``cicada`` (``git revert`` undoes it while nothing has rewritten the files since; see the docs for after a
Sleep). A group or line that changed since the plan is skipped and counted, never re-judged. Refused (exit 3) while Sleep
runs or the backend cannot say it is idle, in a bank with no git, and when ``pending_entities.jsonl`` or
``_same_name_doubts.yaml`` have uncommitted changes; a demo bank is never written (exit 4). A failure after the first write
puts every written file back. Exit 0 done, 2 not a bank or a bad argument, 5 the engine stopped (plan: run it again).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _rows(path: Path) -> list[dict]:
    rows: dict[str, dict] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                if isinstance(row, dict) and (row.get("page") or row.get("line")):
                    rows[str(row.get("page") or row.get("line"))] = row
    return list(rows.values())


def _outside(out: Path, *roots: Path) -> bool:
    out = out.resolve()
    return not any(out == r.resolve() or r.resolve() in out.parents for r in roots)


#: A page the plan finished: a "not_read" page (a failed call, or the run's call limit) is read again by the same command.
_FINISHED = ("done", "capped")


def _settings(args, bank: Path):
    from api.config import Settings

    return Settings(_env_file=None, llm_mode="agent", agent_model=args.model, CICADA_MEMORY_PATH=str(bank))


def cmd_plan(args) -> int:
    from api.services import markdown_parser, name_sweep, value_alignment, value_sweep

    bank = args.bank.expanduser().resolve()
    if not (bank / "entities").is_dir():
        print(json.dumps({"error": "not a bank: no entities/ directory"}))
        return 2
    out = args.out.expanduser().resolve()
    if not _outside(out, REPO, bank):
        print(json.dumps({"error": "--out must be outside the repository and the bank (its rows carry the bank's words)"}))
        return 2
    out.mkdir(parents=True, exist_ok=True)
    os.environ.update({"CICADA_HOME": str(out / "home"), "CICADA_CAPTURE": "off", "CICADA_RECALL": "off",
                       "CICADA_TELEMETRY": "off", "CICADA_ALLOW_CONNECTOR_FETCH": "off"})
    do_values, do_names = args.passes in ("values", "both"), args.passes in ("names", "both")
    summary: dict = {}
    reads: dict[str, value_sweep.Read] = {}
    wanted: list[dict] = []
    if do_values:
        skipped: dict[str, int] = {}
        for path in sorted((bank / "entities").glob("*.md")):
            try:
                parsed = markdown_parser.parse(path)
            except Exception:  # noqa: BLE001
                continue
            read = value_sweep.read_page(path.stem, parsed.frontmatter or {}, parsed.body)
            if read.skip:
                skipped[read.skip] = skipped.get(read.skip, 0) + 1
                continue
            reads[read.id] = read
            wanted.append({"page": read.id, **value_sweep.census(read)})
        wanted.sort(key=lambda c: (-c["eligible"], c["page"]))
        summary["values"] = {"pages_left_alone_by_reason": dict(sorted(skipped.items())), "pages_to_ask": len(wanted),
                             "values_that_could_join_an_older": sum(c["eligible"] for c in wanted),
                             "most_calls_possible": sum(c["max_calls"] for c in wanted)}
    nrows: list[dict] = []
    if do_names:
        nbank = name_sweep.load(bank)
        nrows = name_sweep.plan_rows(nbank)
        summary["names"] = {**name_sweep.census(nbank), "model_calls": 0,
                            "rows_by_action": {a: sum(1 for r in nrows if r["action"] == a)
                                               for a in sorted({r["action"] for r in nrows})}}
        (out / "names.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in nrows), encoding="utf-8")
    (out / "census.json").write_text(json.dumps({"summary": summary, "value_pages": wanted}, indent=1), encoding="utf-8")
    stopped = None
    calls = {"values_ask": 0, "values_check": 0}
    if args.judge and do_values:
        judge = value_alignment.judge_for(_settings(args, bank), main=True)
        if judge is None:
            print(json.dumps({"error": "no engine can answer"}), file=sys.stderr)
            return 2
        path = out / "values.jsonl"
        done = {r["page"] for r in _rows(path) if r.get("status") in _FINISHED}
        todo = [c for c in wanted if c["page"] not in done][: args.limit]
        asked = value_sweep.open_questions(bank)
        meter = value_sweep.Meter()
        print(json.dumps({"values_pages_this_run": len(todo), "already_planned": len(done)}), flush=True)
        with path.open("a", encoding="utf-8") as sink:
            for c in todo:
                room = None if args.max_calls is None else args.max_calls - meter.total
                if room is not None and room < 2:
                    stopped = "max_calls"
                    break
                try:
                    row = value_sweep.plan_page(reads[c["page"]], bank, judge, meter, asked, run_calls_left=room)
                except value_sweep.EngineDown as exc:
                    stopped = f"engine_stopped ({exc})"
                    break
                sink.write(json.dumps(row, ensure_ascii=False) + "\n")
                sink.flush()
        calls["values_ask"], calls["values_check"] = meter.ask, meter.check
    vrows = _rows(out / "values.jsonl")
    (out / "review.txt").write_text(
        value_sweep.GUIDE + "\nVALUES\n\n" + value_sweep.review_text(vrows) + "\nNAMES (no model: nobody is joined)\n\n"
        "A held person written \"Name (qualifier)\" becomes the shape Sleep writes today: a second person held in doubt under the\n"
        "bare name, the written name kept as an alias, its claims on its own key. Whether two are one person is Sleep's later\n"
        "decision, on located evidence, with an undo. Strike a line (--skip-line NAME) to leave it exactly as it is.\n\n"
        + name_sweep.review_text(nrows), encoding="utf-8")
    if not args.judge:
        print(json.dumps(summary, indent=1))
        return 0
    print(json.dumps({
        "calls_this_run": calls, "value_pages_in_file": len(vrows),
        "value_pages_not_read": sum(1 for r in vrows if r.get("status") == "not_read"),
        "value_groups": sum(len(r.get("groups") or []) for r in vrows),
        "name_lines_in_file": len(nrows), "name_actions": {a: sum(1 for r in nrows if r["action"] == a)
                                                           for a in sorted({r["action"] for r in nrows})},
        "stopped": stopped, "review": str(out / "review.txt")}, indent=1))
    return 5 if stopped and stopped.startswith("engine") else 0


def cmd_apply(args) -> int:
    from api.scripts.migrate_claims_jsonl import backend_problem, backend_running
    from api.services import demo_guard, git_service, name_sweep, value_sweep

    bank = args.bank.expanduser().resolve()
    if not (bank / "entities").is_dir():
        print(json.dumps({"error": "not a bank: no entities/ directory"}))
        return 2
    if demo_guard.is_demo(bank):
        print(json.dumps({"refused": "a demo bank is never written"}))
        return 4
    plan = args.plan.expanduser().resolve()
    if not plan.is_dir():
        print(json.dumps({"error": "--plan is the plan directory"}))
        return 2
    try:
        vrows, nrows = _rows(plan / "values.jsonl"), _rows(plan / "names.jsonl")
    except ValueError as exc:
        print(json.dumps({"error": f"the plan directory holds a file that is not JSON lines ({type(exc).__name__})"}))
        return 2
    if args.passes == "values":
        nrows = []
    elif args.passes == "names":
        vrows = []
    undo = value_sweep.Undo()
    try:
        with value_sweep.locked(bank, sleep_running=backend_running, check=args.check):
            dirty = value_sweep.dirty_paths(bank)
            if dirty is None:
                print(json.dumps({"refused": "git cannot say which files are being edited"}))
                return 3
            wanted_names = [r for r in nrows if r.get("action") in (name_sweep.RENAME, name_sweep.HOLD) and not r.get("strike")
                            and r.get("line") not in set(args.skip_line)]
            if wanted_names:
                busy = name_sweep.dirty_files(bank)
                if busy is None or busy:
                    print(json.dumps({"refused": "pending_entities.jsonl or _same_name_doubts.yaml has uncommitted changes (or git "
                                                 "cannot say): let Sleep or its commit finish, then apply again",
                                      "files": sorted(busy or ())}))
                    return 3
            try:
                vres = value_sweep.apply_rows(bank, vrows, skip_pages=args.skip_page, skip_groups=args.skip_group,
                                              check=args.check, dirty=dirty, remember=undo.remember)
                nres = name_sweep.apply_rows(bank, nrows, skip_lines=args.skip_line, check=args.check, remember=undo.remember)
                paths = [*vres.written_pages, *nres.paths]
                committed = False
                if paths and not args.check:
                    n_closed, n_lines = vres.closed, sum(nres.applied.values())
                    head = f"One-time sweep: {n_closed} doubled value(s) closed, {n_lines} held person line(s) re-shaped"
                    body = [*value_sweep.commit_message(vres)[1], *name_sweep.commit_message(nres)[1]]
                    git_service.commit_paths_sync(bank, git_service.build_commit_message(head, body, authors=["cicada"]), paths)
                    committed = vres.committed = True
            except BaseException:
                undo.restore(bank)   # exactly the files written, still under the lock
                raise
    except value_sweep.SleepRunning as exc:
        print(json.dumps({"refused": str(exc), "why": backend_problem()}))
        return 3
    except git_service.GitError as exc:
        print(json.dumps({"failed": f"git could not commit ({type(exc).__name__}); every file written was put back, nothing changed"}))
        return 3
    except value_sweep.NoGit as exc:
        print(json.dumps({"refused": str(exc)}))
        return 3
    except OSError as exc:
        print(json.dumps({"refused": f"the bank's write admission is unavailable ({type(exc).__name__})"}))
        return 3
    print(json.dumps({"values": vres.counts(), "names": nres.counts(), "committed": committed, "paths": paths,
                      "undo": ("git revert <the commit above>; see the docs for when that stops being a clean undo "
                               "(after a Sleep that rewrote pending_entities.jsonl)" if committed else None)}, indent=1))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="the dry run: census and every name row (no model); with --judge, one row per value page")
    p.add_argument("--bank", required=True, type=Path, help="the bank (read only)")
    p.add_argument("--out", required=True, type=Path, help="a directory outside the repo and the bank")
    p.add_argument("--judge", action="store_true", help="read the values (the Claude plan); names never use a model")
    p.add_argument("--pass", dest="passes", choices=("values", "names", "both"), default="both")
    p.add_argument("--model", default="sonnet", help="the main model that reads the values")
    p.add_argument("--limit", type=int, default=None, help="at most this many value pages this run (most joinable first)")
    p.add_argument("--max-calls", type=int, default=None, help="at most this many model calls this run")
    a = sub.add_parser("apply", help="write exactly the rows of a reviewed plan (no model call)")
    a.add_argument("--bank", required=True, type=Path)
    a.add_argument("--plan", required=True, type=Path, help="the plan directory")
    a.add_argument("--pass", dest="passes", choices=("values", "names", "both"), default="both")
    a.add_argument("--check", action="store_true", help="report what would be written, write nothing")
    a.add_argument("--skip-page", action="append", default=[], metavar="ID")
    a.add_argument("--skip-group", action="append", default=[], metavar="PAGE#N")
    a.add_argument("--skip-line", action="append", default=[], metavar="NAME")
    args = ap.parse_args(argv)
    return cmd_plan(args) if args.cmd == "plan" else cmd_apply(args)


if __name__ == "__main__":
    sys.exit(main())
