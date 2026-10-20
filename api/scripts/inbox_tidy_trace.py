"""The inbox tidy, one question at a time: a dry run a coordinator reads before anything is applied, then a vetted
apply of only what they kept (owner rule 2026-10-20: read every proposed answer before any bulk write).

    api/.venv/bin/python -m api.scripts.inbox_tidy_trace trace --bank <path> --out <file> \\
        --engine plan --model haiku [--kind merge_suggestion] [--limit N] [--no-judge]
    api/.venv/bin/python -m api.scripts.inbox_tidy_trace apply --vetted <file> [--bank <name>]

**trace** runs Sleep's inbox policy (``inbox_tend.tidy``, ``dry_run=True``) over the open questions of the bank named
by path and writes one JSON line per question read — ``id``, ``kind``, the two ``names`` (a duplicate's mention and
its page, a fold's two labels; else the subject), ``decision`` (``merge`` / ``keep_apart`` / ``settle`` / ``leave``),
``rule``, the judge's own ``confidence`` (``null`` for an engine-free rule), a one-line ``reason``, and for a decided
question an ``apply`` block: the decision exactly as made, with hashes of the question file and every page it read.
The file is created 0600, refused inside the bank or the memory root (every bank lives there), and is the only place
the rows go: stdout gets counts only, nothing is logged, and the engine's usage is not written to the telemetry
ledger. It runs in this process and reads the bank only — no backend, no write admission, no settle, no commit; the
derived lexical index (``search_index.db``, untracked and disposable) may be brought up to date, as any search does.
``--engine plan --model haiku`` (the default) judges on the Claude plan through the ``claude`` CLI, with that model:
the engine the bank is set to — a metered key, perhaps — is never resolved or called. ``--engine configured`` uses
the person's chosen engine instead (it may spend). ``--kind`` (repeatable or comma-separated) and ``--limit`` narrow
the run; ``--no-judge`` runs the engine-free rules alone.

**apply** sends the rows of an edited trace that still carry an ``apply`` block — delete the lines you do not want —
to the running backend's ``POST /inbox/tidy/apply`` (ruling 21a: the backend owns the inbox's writes; the token and
the pinned bank, after ``/healthz`` confirms the memory root). Each settles through the person's own resolver as
Sleep's commit, undoable under "Settled by Sleep"; one whose question or pages moved since the trace is left as it is
(``changed``). ``--bank <name>`` asserts the active bank. Prints per-id outcomes and counts.

Exit 0 done, 1 refused, 2 usage.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

PLAN_ENGINE = "plan"
CONFIGURED_ENGINE = "configured"
#: The apply's HTTP wait: a base plus a few seconds per row (a merge folds two pages), bounded.
APPLY_TIMEOUT_BASE_S = 30.0
APPLY_TIMEOUT_PER_ROW_S = 10.0
APPLY_TIMEOUT_MAX_S = 1800.0


class TraceFile:
    """The trace's one output: created 0600 (and made 0600 if it existed), never through a symlink; a row is flushed
    as it is decided, so a plan limit or an interruption keeps what was read."""

    def __init__(self, path: Path) -> None:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.fchmod(fd, 0o600)
        self._file = os.fdopen(fd, "w", encoding="utf-8")
        self.rows = 0

    def write(self, row: dict) -> None:
        self._file.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        self._file.flush()
        self.rows += 1

    def close(self) -> None:
        self._file.close()


def _kinds(values: list[str] | None) -> frozenset[str] | None:
    if not values:
        return None
    out = frozenset(k.strip() for v in values for k in v.split(",") if k.strip())
    return out or None


def _inside(path: Path, folder: Path) -> bool:
    try:
        return path.is_relative_to(folder)
    except (OSError, ValueError):
        return False


def plan_llm_fn(settings, model: str):
    """The judge on the Claude plan with ``model``, whatever engine the bank is set to: a resolved copy pinned to the
    plan rung (``llm_mode=agent``), its usage kept off the ledger. ``(llm_fn, engine label)``."""
    from api.services import engine_select, inbox_tend

    plan = settings.model_copy(update={"llm_mode": "agent", "agent_model": model,
                                       "agent_disambiguation_model": model, "no_engine_reason": ""})
    return inbox_tend.default_llm_fn(plan, sink=lambda _event: None), engine_select.engine_label(plan)


def run_trace(bank: Path, out: Path, *, engine: str, model: str, kinds: frozenset[str] | None, limit: int | None,
              judge: bool, settings=None, llm_fn=None) -> dict:
    """The trace, in this process. ``llm_fn`` is a test's fake engine; otherwise ``engine`` picks it."""
    from api.config import Settings
    from api.services import inbox_tend

    settings = settings if settings is not None else Settings().model_copy(update={"memory_path": bank})
    label = None
    if judge and llm_fn is None and engine == PLAN_ENGINE:
        llm_fn, label = plan_llm_fn(settings, model)
    sink = TraceFile(out)
    try:
        counts = asyncio.run(inbox_tend.tidy(bank, settings, dry_run=True, limit=limit, judge=judge, llm_fn=llm_fn,
                                             engine=label, kinds=kinds, trace=sink.write))
    finally:
        sink.close()
    counts["trace_rows"] = sink.rows
    return counts


def _trace(args) -> int:
    bank = Path(args.bank).expanduser().resolve()
    if not (bank / "entities").is_dir() or not (bank / "inbox").is_dir():
        print(json.dumps({"error": "not a bank: no entities/ or inbox/ directory"}))
        return 2
    out = Path(args.out).expanduser()
    out = out.parent.resolve() / out.name
    if not out.parent.is_dir():
        print(json.dumps({"error": "the trace's folder does not exist"}))
        return 2
    from api.config import Settings

    root = Path(Settings().memory_root).expanduser().resolve()
    if _inside(out, bank) or _inside(out, root):
        print(json.dumps({"error": "the trace names people and pages: write it outside every bank"}))
        return 2
    if args.engine == CONFIGURED_ENGINE and not args.no_judge:
        print("note: --engine configured judges with the engine the bank is set to, which may spend", file=sys.stderr)
    counts = run_trace(bank, out, engine=args.engine, model=args.model, kinds=_kinds(args.kind), limit=args.limit,
                       judge=not args.no_judge)
    counts["trace"] = str(out)
    print(json.dumps(counts, sort_keys=True))
    return 0


def vetted_rows(path: Path) -> tuple[list[dict], int]:
    """The rows of an edited trace still carrying an ``apply`` block, and how many lines were left out."""
    rows: list[dict] = []
    skipped = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            raise SystemExit(json.dumps({"error": "the vetted file has a line that is not JSON"})) from None
        if isinstance(row, dict) and isinstance(row.get("apply"), dict):
            rows.append({"id": row.get("id"), "kind": row.get("kind"), "apply": row["apply"]})
        else:
            skipped += 1
    return rows, skipped


def _apply(args) -> int:
    from api import cli, cli_app   # the CLI's one bootstrap comes before any service import
    from api.cli_types import Refusal

    rows, skipped = vetted_rows(Path(args.vetted).expanduser())
    if not rows:
        print(json.dumps({"error": "nothing to apply: no row carries an apply block", "skipped": skipped}))
        return 2
    try:
        boot = cli.bootstrap()
        if boot.client:
            raise Refusal("refused", "Run the apply on the machine that holds the bank.")
        cli._check_bank(boot, args.bank)
        boot.probe = {"state": "unverified"}   # every write asks /healthz to confirm the memory root first
        timeout = min(APPLY_TIMEOUT_MAX_S, APPLY_TIMEOUT_BASE_S + APPLY_TIMEOUT_PER_ROW_S * len(rows))
        out = boot.ctx.run(cli_app.call, boot, "POST", "/inbox/tidy/apply", body={"decisions": rows},
                           timeout=timeout)
    except Refusal as exc:
        print(json.dumps({"error": exc.code, "text": str(exc)}))
        return 1
    except cli.BootstrapError as exc:
        print(json.dumps({"error": "bootstrap", "text": str(exc)}))
        return 1
    out["skipped"] = skipped
    print(json.dumps(out, sort_keys=True))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="inbox_tidy_trace", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    trace = sub.add_parser("trace", help="the dry run, one row per question, into a 0600 file outside every bank")
    trace.add_argument("--bank", required=True, help="the bank directory (holds entities/ and inbox/)")
    trace.add_argument("--out", required=True, help="the trace file to write (outside every bank)")
    trace.add_argument("--engine", choices=(PLAN_ENGINE, CONFIGURED_ENGINE), default=PLAN_ENGINE,
                       help="plan: the Claude plan with --model (default); configured: the bank's own engine")
    trace.add_argument("--model", default="haiku", help="the Claude model for --engine plan (default haiku)")
    trace.add_argument("--kind", action="append", help="only these kinds (repeatable or comma-separated)")
    trace.add_argument("--limit", type=int, default=None, help="read at most this many questions")
    trace.add_argument("--no-judge", action="store_true", help="the engine-free rules only: no engine call")
    apply = sub.add_parser("apply", help="settle the rows kept in an edited trace, through the running backend")
    apply.add_argument("--vetted", required=True, help="the edited trace file")
    apply.add_argument("--bank", default=None, help="assert the active bank's name")
    args = parser.parse_args(argv)
    if args.command == "trace":
        return _trace(args)
    return _apply(args)


if __name__ == "__main__":
    sys.exit(main())
