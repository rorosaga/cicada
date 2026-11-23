"""Heal the facts a bank's pages already repeat — plan first (the judge, writes nothing), then apply (no model) (G148).

    api/.venv/bin/python -m api.scripts.fact_fold_heal plan  --bank <path> --out <dir>                      # census, no call
    api/.venv/bin/python -m api.scripts.fact_fold_heal plan  --bank <path> --out <dir> --judge --limit 25   # + the judge
    api/.venv/bin/python -m api.scripts.fact_fold_heal apply --bank <path> --plan <dir> --check             # what would be written
    api/.venv/bin/python -m api.scripts.fact_fold_heal apply --bank <path> --plan <dir>                     # one `cicada` commit

**plan** reads every page and prints, before the first model call, counts only: pages by why they are left, pages a rule
alone folds, pages it would ask the judge about, and the most calls that is. Without ``--judge`` it stops there (and
writes ``census.json``: page ids, bullet counts, never a word). With ``--judge`` (Sleep's small judge on the Claude plan,
``--model haiku``) it replays each page's Key Facts, the pages with the most repeats first, ``--limit`` pages and
``--max-calls`` calls at most (``--max-calls-page`` a page), and appends one row a page to ``<out>/pages.jsonl`` as it
goes: every fold (the line kept, the line dropped, the path through ask / code guard / second reader, the conversations
whose source rows move), what the judge named and a later stage refused, and the page's bullets before and after. A
run that stops (a limit, a plan limit, Ctrl-C) is resumed by running the same command again: pages already in the file
are not asked again (a page that stopped at its call cap says ``capped``: plan it again with ``--page <id> --max-calls-page N``). ``<out>/review.txt`` reads the same rows as text. **Strike** a fold or a page before applying: delete
it from ``pages.jsonl``, set its ``"strike": true``, or name it on the apply line (``--skip-page``, ``--skip-fold
<page>#<n>``). ``--out`` must be outside the repository and the bank: the rows carry the bank's words; stdout never does.

**apply** makes no model call and writes exactly the folds the file holds, under the bank's admission, page lock and git
lock, as ONE commit authored ``cicada`` (a plain ``git revert`` undoes it). A page whose Key Facts changed since the plan
is skipped and counted, never re-judged; so is a page a person has edited since, and a fold the guard would no longer
pass. ``--check`` reads the bank and reports the same counts without writing (and without asking the backend). Refused (exit 3) while Sleep runs or the
backend cannot say it is idle, like every one-time repair here (`repair_page_quality`); a demo bank is never written
(exit 4). Exit 0 done, 2 not a bank or a bad argument, 5 the engine stopped (plan: run it again).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _load(bank: Path) -> tuple[list[dict], object, str | None]:
    from api.services import link_names, markdown_parser

    pages = []
    for path in sorted((bank / "entities").glob("*.md")):
        try:
            parsed = markdown_parser.parse(path)
        except Exception:  # noqa: BLE001 - an unreadable page is left alone
            continue
        pages.append({"id": path.stem, "frontmatter": parsed.frontmatter or {}, "body": parsed.body})
    owner = next((str((p["frontmatter"]).get("name") or "") for p in pages if p["frontmatter"].get("owner")), None)
    return pages, link_names.Names(pages), owner


def _rows(plan: Path) -> list[dict]:
    path = plan / "pages.jsonl" if plan.is_dir() else plan
    rows: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            rows[str(row.get("page"))] = row
    return list(rows.values())


def _outside(out: Path, *roots: Path) -> bool:
    out = out.resolve()
    return not any(out == r.resolve() or r.resolve() in out.parents for r in roots)


def _review(rows: list[dict], out: Path) -> None:
    lines: list[str] = []
    for row in sorted(rows, key=lambda r: (-len(r.get("folds") or []), str(r.get("page")))):
        if not row.get("folds") and not row.get("refused"):
            continue
        lines.append(f"## {row['page']}  ({row.get('name')})  {row['before']} -> {row['after']} facts  "
                     f"[{row['status']}, {row['calls']['total']} calls]")
        for fold in row.get("folds") or []:
            lines.append(f"  {fold['id']}  {fold['how']}"
                         + (f", guard {fold['guard']}" if fold.get("guard") else "")
                         + (", turned round" if fold.get("flipped") else "")
                         + (", second reader agreed" if fold.get("second_reader") else "")
                         + ("  [STRUCK]" if fold.get("strike") else ""))
            lines.append(f"    dropped: {fold['drop']}")
            lines.append(f"    kept:    {fold['into']}")
            if fold.get("chain"):
                lines.append(f"    first folded into (itself folded later): {' ; '.join(fold['chain'])}")
            lines.append(f"    sources moving to the kept line: {', '.join(fold.get('sources_move') or []) or '(none)'}")
        for item in row.get("refused") or []:
            lines.append(f"  left alone ({item['stage']}): {item['drop']}  <-/-  {item['by']}")
        lines.append("")
    (out / "review.txt").write_text("\n".join(lines), encoding="utf-8")


def _judge(model: str, bank: Path):
    from api.config import Settings
    from api.services import fact_fold

    settings = Settings(_env_file=None, llm_mode="agent", agent_model=model, agent_disambiguation_model=model,
                        CICADA_MEMORY_PATH=str(bank))
    return fact_fold.judge_for(settings)


def cmd_plan(args) -> int:
    from api.services import fact_fold_heal as heal

    bank = args.bank.expanduser().resolve()
    if not (bank / "entities").is_dir():
        print(json.dumps({"error": "not a bank: no entities/ directory"}))
        return 2
    out = args.out.expanduser().resolve()
    if not _outside(out, REPO, bank):
        print(json.dumps({"error": "--out must be outside the repository and the bank (its rows carry the bank's words)"}))
        return 2
    out.mkdir(parents=True, exist_ok=True)
    # Nothing of the person's: the engine's ledger rows and any capture hook go to a scratch home.
    os.environ.update({"CICADA_HOME": str(out / "home"), "CICADA_CAPTURE": "off", "CICADA_RECALL": "off",
                       "CICADA_TELEMETRY": "off", "CICADA_ALLOW_CONNECTOR_FETCH": "off"})
    chunk, page_cap = args.chunk, args.max_calls_page
    pages, names, owner = _load(bank)
    reads = {}
    skipped: dict[str, int] = {}
    census = []
    for page in pages:
        read = heal.read_page(page["id"], page["frontmatter"], page["body"], max_bullets=args.max_bullets)
        if read.skip:
            skipped[read.skip] = skipped.get(read.skip, 0) + 1
            continue
        if len(read.foldable) < 2:   # no row proves Sleep wrote them (a legacy or typed page): nothing may be dropped
            skipped["no_source_rows"] = skipped.get("no_source_rows", 0) + 1
            continue
        info = heal.census(read, chunk=chunk, page_cap=page_cap, names=names, owner=owner)
        reads[read.id] = read
        census.append({"page": read.id, "bullets": len(read.bullets), "rowless": sum(1 for ok in read.rowed if not ok),
                       **info})
    wanted = [c for c in census if c["candidates"] or c.get("rule_folds")]
    wanted.sort(key=lambda c: (not c["candidates"], -c["candidates"], -c.get("rule_folds", 0), -c["bullets"], c["page"]))
    asked = [c for c in wanted if c["candidates"]]
    max_calls = sum(min(c["max_calls"], page_cap) for c in asked)
    summary = {
        "pages": len(pages), "left_alone_by_reason": dict(sorted(skipped.items())),
        "pages_read": len(reads), "key_facts_read": sum(len(r.bullets) for r in reads.values()),
        "rowless_kept": sum(c["rowless"] for c in census),
        "pages_a_rule_folds": sum(1 for c in wanted if c.get("rule_folds")),
        "pages_to_ask": len(asked), "most_calls_possible": max_calls, "chunk": chunk, "max_calls_per_page": page_cap,
    }
    (out / "census.json").write_text(json.dumps({"summary": summary, "pages": wanted}, indent=1), encoding="utf-8")
    if not args.judge:
        print(json.dumps(summary, indent=1))
        return 0
    judge = _judge(args.model, bank)
    if judge is None:
        print(json.dumps({"error": "no engine can answer"}), file=sys.stderr)
        return 2
    path = out / "pages.jsonl"
    done = {r["page"] for r in _rows(path)} if path.exists() else set()
    todo = [c for c in wanted if c["page"] not in done]
    if args.page:
        todo = [c for c in wanted if c["page"] in set(args.page)]
    todo = todo[: args.limit] if args.limit is not None else todo
    this_run = sum(min(c["max_calls"], page_cap) for c in todo if c["candidates"])
    if args.max_calls is not None:
        this_run = min(this_run, args.max_calls)
    print(json.dumps({**summary, "already_planned": len(done), "pages_this_run": len(todo),
                      "most_calls_this_run": this_run}, indent=1), flush=True)
    meter = heal.Meter()
    stopped = None
    new = 0
    with path.open("a", encoding="utf-8") as sink:
        for c in todo:
            left = None if args.max_calls is None else args.max_calls - meter.total
            if c["candidates"] and left is not None and left < 2:
                stopped = "max_calls"
                break
            try:
                row = heal.plan_page(reads[c["page"]], names, owner, judge, meter, chunk=chunk,
                                     max_calls=page_cap, run_calls_left=left)
            except heal.EngineDown as exc:
                stopped = f"engine_stopped ({exc})"
                break
            sink.write(json.dumps(row, ensure_ascii=False) + "\n")
            sink.flush()
            new += 1
    rows = _rows(path) if path.exists() else []
    _review(rows, out)
    folds = [f for r in rows for f in r["folds"]]
    print(json.dumps({
        "pages_planned_this_run": new, "pages_in_file": len(rows), "calls_this_run": {"ask": meter.ask, "check": meter.check},
        "folds": len(folds), "by_how": {h: sum(1 for f in folds if f["how"] == h) for h in sorted({f["how"] for f in folds})},
        "facts_before": sum(r["before"] for r in rows), "facts_after": sum(r["after"] for r in rows),
        "pages_capped": sum(1 for r in rows if r["status"] == "capped"), "stopped": stopped,
        "rows": str(path), "review": str(out / "review.txt")}, indent=1))
    return 5 if stopped and stopped.startswith("engine") else 0


def cmd_apply(args) -> int:
    from api.scripts.migrate_claims_jsonl import backend_problem, backend_running
    from api.services import demo_guard
    from api.services import fact_fold_heal as heal

    bank = args.bank.expanduser().resolve()
    if not (bank / "entities").is_dir():
        print(json.dumps({"error": "not a bank: no entities/ directory"}))
        return 2
    if demo_guard.is_demo(bank):
        print(json.dumps({"refused": "a demo bank is never written"}))
        return 4
    plan = args.plan.expanduser().resolve()
    if not (plan / "pages.jsonl" if plan.is_dir() else plan).is_file():
        print(json.dumps({"error": "no pages.jsonl in --plan"}))
        return 2
    rows = _rows(plan)
    _pages, names, owner = _load(bank)
    try:
        result = heal.apply(bank, rows, sleep_running=backend_running, names=names, owner=owner,
                            skip_pages=args.skip_page, skip_folds=args.skip_fold, check=args.check)
    except heal.SleepRunning as exc:
        print(json.dumps({"refused": str(exc), "why": backend_problem()}))
        return 3
    except OSError as exc:   # the bank's admission lock cannot be opened: fail closed
        print(json.dumps({"refused": f"the bank's write admission is unavailable ({type(exc).__name__})"}))
        return 3
    print(json.dumps(result.counts(), indent=1))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="the dry run: census, then (--judge) the folds per page; writes nothing to the bank")
    p.add_argument("--bank", required=True, type=Path, help="the bank (read only) — a copy is fine")
    p.add_argument("--out", required=True, type=Path, help="a directory outside the repo and the bank")
    p.add_argument("--judge", action="store_true", help="ask Sleep's small judge (the Claude plan)")
    p.add_argument("--model", default="haiku")
    p.add_argument("--limit", type=int, default=None, help="at most this many pages this run (most repeated first)")
    p.add_argument("--max-calls", type=int, default=None, help="at most this many model calls this run")
    p.add_argument("--max-calls-page", type=int, default=None, help="at most this many calls on one page")
    p.add_argument("--chunk", type=int, default=None, help="new lines per ask")
    p.add_argument("--max-bullets", type=int, default=None, help="pages with more Key Facts are left alone")
    p.add_argument("--page", action="append", default=[], help="only this page id (repeatable); re-plans it")
    a = sub.add_parser("apply", help="write exactly the folds of a reviewed plan (no model call)")
    a.add_argument("--bank", required=True, type=Path)
    a.add_argument("--plan", required=True, type=Path, help="the plan directory (or its pages.jsonl)")
    a.add_argument("--check", action="store_true", help="report what would be written, write nothing")
    a.add_argument("--skip-page", action="append", default=[], metavar="ID")
    a.add_argument("--skip-fold", action="append", default=[], metavar="PAGE#N")
    args = ap.parse_args(argv)
    if args.cmd == "plan":
        from api.services import fact_fold_heal as heal

        args.chunk = args.chunk or heal.CHUNK
        args.max_calls_page = args.max_calls_page or heal.MAX_CALLS_PAGE
        args.max_bullets = args.max_bullets or heal.MAX_BULLETS
        for flag in ("chunk", "max_calls_page"):
            if getattr(args, flag) < 1 or (flag == "chunk" and args.chunk > 12):
                print(json.dumps({"error": f"--{flag.replace('_', '-')} out of range"}))
                return 2
        return cmd_plan(args)
    return cmd_apply(args)


if __name__ == "__main__":
    sys.exit(main())
