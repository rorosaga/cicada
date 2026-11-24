"""Sweep what a memory already holds wrong: doubled values and people held under a qualified name (G148) — plan first
(the judge, writes nothing), then apply (no model).

    api/.venv/bin/python -m api.scripts.value_name_sweep plan  --bank <path> --out <dir>                    # census, no call
    api/.venv/bin/python -m api.scripts.value_name_sweep plan  --bank <path> --out <dir> --judge --max-calls 150
    api/.venv/bin/python -m api.scripts.value_name_sweep apply --bank <path> --plan <dir> --check           # what would be written
    api/.venv/bin/python -m api.scripts.value_name_sweep apply --bank <path> --plan <dir>                   # one `cicada` commit

Two passes, one tool (``--pass values|names|both``, both by default): they share the plan directory, the review text, the
admission and the one commit, and are struck, checked and undone the same way.

**plan** prints, before the first model call, counts only: pages with a value that could be joined to an older one, held
lines written ``Name (qualifier)``, pages titled so, and the most calls that is. Without ``--judge`` it stops there (and
writes ``census.json``: ids and counts, never a word). With ``--judge`` (the Claude plan; ``--model`` the main model that
reads the values and the second reading of a name, ``--small-model`` the small judge) it writes one row per page (``values.jsonl``)
and per held line (``names.jsonl``) as it goes, and ``review.txt``: every pair and every line, what would change, and the
judge's own words. A run that stops is resumed by the same command. ``--out`` must be outside the repository and the bank.
**Strike** a row before applying: delete it, set ``"strike": true``, or name it (``--skip-page``, ``--skip-group
<page>#<n>``, ``--skip-line <name>``).

**apply** makes no model call and writes exactly the reviewed rows, under the bank's admission, page lock and git lock, as ONE
commit authored ``cicada`` (a plain ``git revert`` undoes it). A group or line that changed since the plan is skipped and
counted, never re-judged. Refused (exit 3) while Sleep runs or the backend cannot say it is idle; a demo bank is never
written (exit 4). Exit 0 done, 2 not a bank or a bad argument, 5 the engine stopped (plan: run it again).
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
                rows[str(row.get("page") or row.get("line"))] = row
    return list(rows.values())


def _outside(out: Path, *roots: Path) -> bool:
    out = out.resolve()
    return not any(out == r.resolve() or r.resolve() in out.parents for r in roots)


def _settings(args, bank: Path):
    from api.config import Settings

    return Settings(_env_file=None, llm_mode="agent", agent_model=args.model, agent_disambiguation_model=args.small_model,
                    CICADA_MEMORY_PATH=str(bank))


def _asker(settings, model: str):
    """``(system, prompt) -> parsed JSON`` on the Claude plan, model ``model``, the same call Stage 2 makes for the same-name
    judge but under its own stage label: the plan engine forces the ``disambiguation`` stage into the one-pair
    ``{decision, reason}`` schema, which has no room for the same-name judge's ``people`` and ``pairs`` (measured 2026-11-24,
    ``docs/architecture/capture-and-sleep.md``), and a stage with no schema answers in the shape asked for."""
    from api.services import json_parse, providers

    llm_fn = providers.resolve_llm_fn(settings.model_copy(update={"agent_model": model}), stage="same_name_sweep",
                                      is_async=False)

    def ask(system: str, prompt: str) -> object:
        resp = llm_fn(messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                      response_format={"type": "json_object"})
        try:
            raw = resp.choices[0].message.content
        except (AttributeError, IndexError, TypeError):
            raw = resp.get("choices", [{}])[0].get("message", {}).get("content") if isinstance(resp, dict) else ""
        return json_parse.parse_json_object_or(raw or "", {})
    return ask


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
    nbank = name_sweep.load(bank) if do_names else None
    if do_names:
        summary["names"] = name_sweep.census(nbank)
    (out / "census.json").write_text(json.dumps({"summary": summary, "value_pages": wanted}, indent=1), encoding="utf-8")
    if not args.judge:
        print(json.dumps(summary, indent=1))
        return 0
    settings = _settings(args, bank)
    stopped = None
    calls = {"values_ask": 0, "values_check": 0, "names_small": 0, "names_strong": 0}
    left = args.max_calls
    if do_values:
        judge = value_alignment.judge_for(settings, main=True)
        if judge is None:
            print(json.dumps({"error": "no engine can answer"}), file=sys.stderr)
            return 2
        path = out / "values.jsonl"
        done = {r["page"] for r in _rows(path)}
        todo = [c for c in wanted if c["page"] not in done][: args.limit]
        asked = value_sweep.open_questions(bank)
        meter = value_sweep.Meter()
        print(json.dumps({"values_pages_this_run": len(todo), "already_planned": len(done)}), flush=True)
        with path.open("a", encoding="utf-8") as sink:
            for c in todo:
                room = None if left is None else left - meter.total - (calls["names_small"] + calls["names_strong"])
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
    if do_names and not (stopped or "").startswith("engine"):
        cands, _ = name_sweep.candidates(nbank)
        by_stem: dict[str, list] = {}
        for line in cands:
            by_stem.setdefault(name_sweep.snp.stem_of(line.name)[0].lower(), []).append(line)
        path = out / "names.jsonl"
        done = {r["line"] for r in _rows(path)}
        meter = name_sweep.Meter()
        small = _asker(settings, args.small_model)
        strong = _asker(settings, args.model)
        with path.open("a", encoding="utf-8") as sink:
            for stem, lines in sorted(by_stem.items()):
                lines = [ln for ln in lines if ln.name not in done]
                if not lines:
                    continue
                used = calls["values_ask"] + calls["values_check"] + meter.total
                if left is not None and left - used < 3:
                    stopped = stopped or "max_calls"
                    break
                try:
                    rows = asyncio.run(name_sweep.plan_name(nbank, stem, lines[: name_sweep.MAX_LINES], small, strong, meter))
                except name_sweep.EngineDown as exc:
                    stopped = f"engine_stopped ({exc})"
                    break
                except Exception as exc:  # noqa: BLE001 - a failed name decides nothing: left as it is, said so
                    rows = [{"v": 1, "pass": "names", "line": ln.name, "stem": stem, "state": name_sweep.line_state(ln),
                             "action": "leave", "reason": f"the reading failed ({type(exc).__name__})", "strike": False}
                            for ln in lines]
                for row in rows:
                    sink.write(json.dumps(row, ensure_ascii=False) + "\n")
                sink.flush()
        calls["names_small"], calls["names_strong"] = meter.small, meter.strong
    vrows, nrows = _rows(out / "values.jsonl"), _rows(out / "names.jsonl")
    (out / "review.txt").write_text(
        "VALUES\n\n" + value_sweep.review_text(vrows) + "\nNAMES\n\n" + name_sweep.review_text(nrows), encoding="utf-8")
    print(json.dumps({
        "calls_this_run": calls, "value_pages_in_file": len(vrows),
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
    vrows, nrows = _rows(plan / "values.jsonl"), _rows(plan / "names.jsonl")
    if args.passes == "values":
        nrows = []
    elif args.passes == "names":
        vrows = []
    try:
        with value_sweep.locked(bank, sleep_running=backend_running, check=args.check):
            dirty = value_sweep.dirty_paths(bank)
            if dirty is None:
                print(json.dumps({"refused": "git cannot say which pages are being edited"}))
                return 3
            vres = value_sweep.apply_rows(bank, vrows, skip_pages=args.skip_page, skip_groups=args.skip_group,
                                          check=args.check, dirty=dirty)
            nres = name_sweep.apply_rows(bank, nrows, skip_lines=args.skip_line, check=args.check)
            paths = [*vres.written_pages, *nres.paths]
            committed = False
            if paths and not args.check and (bank / ".git").exists():
                n_closed, n_lines = vres.closed, sum(nres.applied.values())
                head = f"One-time sweep: {n_closed} doubled value(s) closed, {n_lines} held person line(s) placed"
                body = [*value_sweep.commit_message(vres)[1], *name_sweep.commit_message(nres)[1]]
                git_service.commit_paths_sync(bank, git_service.build_commit_message(head, body, authors=["cicada"]), paths)
                committed = True
    except value_sweep.SleepRunning as exc:
        print(json.dumps({"refused": str(exc), "why": backend_problem()}))
        return 3
    except OSError as exc:
        print(json.dumps({"refused": f"the bank's write admission is unavailable ({type(exc).__name__})"}))
        return 3
    print(json.dumps({"values": vres.counts(), "names": nres.counts(), "committed": committed, "paths": paths}, indent=1))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="the dry run: census, then (--judge) one row per page and per line; writes nothing to the bank")
    p.add_argument("--bank", required=True, type=Path, help="the bank (read only)")
    p.add_argument("--out", required=True, type=Path, help="a directory outside the repo and the bank")
    p.add_argument("--judge", action="store_true", help="ask the judge (the Claude plan)")
    p.add_argument("--pass", dest="passes", choices=("values", "names", "both"), default="both")
    p.add_argument("--model", default="sonnet", help="the main model: reads the values and a name's second reading")
    p.add_argument("--small-model", default="haiku", help="the small judge that reads a name first")
    p.add_argument("--limit", type=int, default=None, help="at most this many value pages this run (most joinable first)")
    p.add_argument("--max-calls", type=int, default=None, help="at most this many model calls this run, both passes")
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
