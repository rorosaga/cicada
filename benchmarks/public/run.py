"""Run a public memory benchmark end to end through Cicada, on the person's Claude plan (standard library only).

    api/.venv/bin/python -m benchmarks.public.run prepare --cache ~/cicada-bench --dataset locomo
    api/.venv/bin/python -m benchmarks.public.run run --cache ~/cicada-bench --dataset locomo \\
        --units 1 --per-category 10                      # a small slice: one conversation, 10 questions a category
    api/.venv/bin/python -m benchmarks.public.run run --cache ~/cicada-bench --resume <run dir>   # continue
    api/.venv/bin/python -m benchmarks.public.run report --run <run dir>

``prepare`` is the only step that touches the network: the pinned dataset file (sha256-checked) and the on-device
search model into the benchmark home. ``run`` then never fetches anything (``HF_HUB_OFFLINE``), never reads the
person's bank, ``~/.cicada`` or ``api/.env``: every unit gets its own marked throwaway bank under the run folder and
a child process whose environment is built from an allowlist — ``HOME``/``CICADA_HOME`` the benchmark home,
``CICADA_MEMORY_PATH`` the unit's bank, capture/telemetry/connector/feed/logo fetches off, no provider keys,
``CICADA_LLM_MODE=agent`` (every model call a ``claude -p`` on the plan). The ``claude`` children alone find the
person's sign-in (``--claude-home``, default: this user's home folder; see ``unit.py``).

Resumable at every step: a unit that finished is skipped; a unit stopped mid-Sleep (a plan limit pauses it) continues
from its paused record; answers and judgments already written are never redone. ``--limit``/``--per-category``/
``--units`` slice deterministically (first N), so a resumed or repeated slice is the same questions.
"""
from __future__ import annotations

import argparse
import json
import os
import pwd
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from benchmarks.public import datasets, report
from benchmarks.system.runner import MARKER, REPO, _no_symlinks

HOME_MARKER = "_bench_home.yaml"
BANK_MARKER = "_bench.yaml"
RUN_MARKER = "_bench_run.yaml"
PATHS = ("ask", "full-context")
#: The run's settings that must match on --resume (anything else would mix two experiments in one table).
PINNED = ("dataset", "sleep_model", "disambiguation_model", "answer_model", "judge_model", "paths",
          "sleep_schedule", "batch_size", "embedding_model", "units", "only", "per_category", "limit",
          "include_adversarial")


def _mark(path: Path, marker: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / marker).write_text(json.dumps({"kind": MARKER}) + "\n", encoding="utf-8")


def _check_marked(path: Path, marker: str) -> None:
    try:
        ok = json.loads((path / marker).read_text(encoding="utf-8")) == {"kind": MARKER}
    except (OSError, ValueError):
        ok = False
    if not ok:
        raise SystemExit(f"{path} is not a benchmark-owned folder (no {marker} marker) — refusing it")


def cache_layout(cache: Path) -> dict[str, Path]:
    cache = cache.expanduser().absolute()
    _no_symlinks(cache)
    return {"cache": cache, "data": cache / "data", "home": cache / "home", "runs": cache / "runs",
            "release_cache": cache / "release-cache"}


def _guard_cache(cache: Path) -> None:
    """The cache holds banks with their own git: never the person's home itself, their Cicada folders or this repo."""
    real_home = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()
    resolved = cache.resolve()
    if resolved == real_home:
        raise SystemExit("--cache must be a folder of its own, not your home folder")
    for forbidden in (real_home / ".cicada", real_home / "cicada", REPO.resolve()):
        if resolved == forbidden or forbidden in resolved.parents or resolved in forbidden.parents:
            raise SystemExit(f"--cache {cache} overlaps {forbidden} — pick a folder of its own")


# --------------------------------------------------------------------------------------------------------------- #
# prepare
# --------------------------------------------------------------------------------------------------------------- #

def prepare(args) -> int:
    lay = cache_layout(args.cache)
    _guard_cache(lay["cache"])
    path = datasets.fetch(args.dataset, lay["data"])
    print(f"dataset {args.dataset}: {path} (sha256 verified)")
    home = lay["home"]
    if not home.exists():
        _mark(home, HOME_MARKER)
    _check_marked(home, HOME_MARKER)
    models = home / "models"
    env = {k: os.environ[k] for k in ("PATH", "TMPDIR", "LANG") if k in os.environ}
    env.update({"HOME": str(home), "CICADA_HOME": str(home), "CICADA_RELEASE_CACHE": str(lay["release_cache"]),
                "PYTHONPATH": str(REPO)})
    if args.embedding in ("small", "both"):
        subprocess.run(["bash", str(REPO / "scripts" / "fetch-embedding-model.sh"), str(models)], env=env, check=True)
    if args.embedding in ("gemma2", "both"):
        subprocess.run([sys.executable, "-m", "api.services.model_fetch"], env=env, cwd=REPO, check=True)
    print(f"benchmark home {home} (models: {', '.join(sorted(p.name for p in models.iterdir())) if models.is_dir() else 'none'})")
    return 0


# --------------------------------------------------------------------------------------------------------------- #
# run
# --------------------------------------------------------------------------------------------------------------- #

def unit_env(home: Path, bank: Path, cfg: dict, claude_home: str) -> dict[str, str]:
    # USER/LOGNAME: the `claude` CLI finds its sign-in in the login keychain by the account name; without them a
    # signed-in plan reads as signed out. Neither is a secret.
    env = {k: os.environ[k] for k in ("PATH", "TMPDIR", "LANG", "LC_ALL", "USER", "LOGNAME") if k in os.environ}
    env.update({
        "HOME": str(home), "CICADA_HOME": str(home), "CICADA_MEMORY_PATH": str(bank),
        "CICADA_CAPTURE": "off", "CICADA_TELEMETRY": "off",
        "CICADA_ALLOW_CONNECTOR_FETCH": "off", "CICADA_ALLOW_FEED_FETCH": "off", "CICADA_ALLOW_LOGO_FETCH": "off",
        "CICADA_LLM_MODE": "agent", "CICADA_AGENT_MODEL": cfg["answer_model"],
        "CICADA_AGENT_DISAMBIGUATION_MODEL": cfg["disambiguation_model"],
        "CICADA_AGENT_MAX_CONCURRENCY": str(cfg["concurrency"]),
        "CICADA_EMBEDDING_MODE": "local", "LITELLM_MODE": "PRODUCTION",
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "PYTHONPATH": str(REPO), "PYTHONHASHSEED": "0",
        "CICADA_BENCH_CLAUDE_HOME": claude_home,
    })
    if cfg.get("embedding_model"):
        env["CICADA_EMBEDDING_MODEL_LOCAL"] = cfg["embedding_model"]
    return env


def _config(args) -> dict:
    return {
        "dataset": args.dataset, "sleep_model": args.sleep_model, "disambiguation_model": args.disambiguation_model,
        "answer_model": args.answer_model, "judge_model": args.judge_model,
        "paths": [p.strip() for p in args.paths.split(",") if p.strip()],
        "sleep_schedule": args.sleep_schedule, "batch_size": args.batch_size,
        "embedding_model": args.embedding_model or "", "units": args.units, "only": args.only or [],
        "per_category": args.per_category, "limit": args.limit, "include_adversarial": args.include_adversarial,
        "concurrency": args.concurrency, "fake_engine": bool(args.fake_engine),
        "dataset_file": str(args.dataset_file) if args.dataset_file else "",
    }


def run(args) -> int:
    lay = cache_layout(args.cache)
    _guard_cache(lay["cache"])
    home = lay["home"]
    _check_marked(home, HOME_MARKER)
    if getattr(args, "dataset_file", None) and not args.fake_engine:
        raise SystemExit("--dataset-file is for the offline harness test (with --fake-engine) only")
    if args.resume:
        run_dir = Path(args.resume).expanduser().absolute()
        _check_marked(run_dir, RUN_MARKER)
        cfg = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
        cfg["concurrency"] = args.concurrency
    else:
        cfg = _config(args)
        bad = [p for p in cfg["paths"] if p not in PATHS]
        if bad or not cfg["paths"]:
            raise SystemExit(f"--paths takes {', '.join(PATHS)}")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_dir = lay["runs"] / f"{cfg['dataset']}-{stamp}"
        _mark(run_dir, RUN_MARKER)
        cfg["created"] = stamp
        cfg["revision"] = _git_rev()
        cfg["dataset_sha256"] = "unpinned" if cfg["dataset_file"] else datasets.SOURCES[cfg["dataset"]]["sha256"]
        (run_dir / "config.json").write_text(json.dumps(cfg, indent=1), encoding="utf-8")
    claude_home = str(Path(args.claude_home).expanduser()) if args.claude_home else pwd.getpwuid(os.getuid()).pw_dir

    if cfg.get("dataset_file"):   # the harness's own offline test: an unpinned synthetic file, never a score
        path = Path(cfg["dataset_file"])
        units = (datasets.locomo_units(path) if cfg["dataset"] == "locomo"
                 else datasets.longmemeval_units(path, cfg["dataset"].split("-", 1)[1]))
    else:
        units = datasets.load_units(cfg["dataset"], lay["data"])
    units = datasets.select(units, units_limit=cfg["units"], only=cfg["only"] or None,
                            per_category=cfg["per_category"], limit=cfg["limit"],
                            skip_categories=() if cfg["include_adversarial"] else ("adversarial",))
    print(f"run {run_dir}\n  {len(units)} unit(s), {sum(len(u['questions']) for u in units)} question(s) · "
          f"Sleep {cfg['sleep_model']} (+{cfg['disambiguation_model']}) · answer {cfg['answer_model']} · "
          f"judge {cfg['judge_model']} · paths {','.join(cfg['paths'])}", flush=True)
    status = 0
    for unit in units:
        uid = unit["unit_id"].replace(":", "_").replace("/", "_")
        out = run_dir / "units" / uid
        state = out / "state.json"
        if state.is_file() and json.loads(state.read_text(encoding="utf-8")).get("done"):
            continue
        out.mkdir(parents=True, exist_ok=True)
        (out / "unit.json").write_text(json.dumps(unit), encoding="utf-8")
        bank = run_dir / "banks" / uid
        if not bank.exists():
            _mark(bank, BANK_MARKER)
        _check_marked(bank, BANK_MARKER)
        job = {"unit_path": str(out / "unit.json"), "bank": str(bank), "out_dir": str(out),
               **{k: cfg[k] for k in ("sleep_model", "disambiguation_model", "answer_model", "judge_model", "paths",
                                      "sleep_schedule", "batch_size", "concurrency")},
               "fake_engine": bool(cfg.get("fake_engine"))}
        started = time.perf_counter()
        print(f"  unit {unit['unit_id']}: {len(unit['sessions'])} sessions, {len(unit['questions'])} questions …",
              flush=True)
        with (out / "child.log").open("a", encoding="utf-8") as log:
            rc = subprocess.run([sys.executable, "-P", "-m", "benchmarks.public.unit"], input=json.dumps(job),
                                text=True, cwd=home, env=unit_env(home, bank, cfg, claude_home),
                                stdout=log, stderr=log, check=False).returncode
        print(f"    -> exit {rc} in {time.perf_counter() - started:.0f} s", flush=True)
        if rc == 3:
            print("  paused on a plan limit — re-run with --resume to continue", flush=True)
            status = 3
            break
        if rc != 0:
            print(f"  unit failed — see {out / 'child.log'}", flush=True)
            status = 1
    summary = report.summarize(run_dir)
    (run_dir / "report.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(report.render(summary))
    return status


def _git_rev() -> str:
    try:
        return subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"], text=True,
                              capture_output=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def report_cmd(args) -> int:
    run_dir = Path(args.run).expanduser().absolute()
    summary = report.summarize(run_dir)
    (run_dir / "report.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(report.render(summary))
    return 0


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare", help="fetch the pinned dataset and the on-device search model (the only network step)")
    p.add_argument("--cache", type=Path, required=True, help="a folder of its own: data, benchmark home, runs")
    p.add_argument("--dataset", choices=sorted(datasets.SOURCES), required=True)
    p.add_argument("--embedding", choices=("small", "gemma2", "both", "none"), default="small",
                   help="small = the multilingual model a release bundles (~130 MB); gemma2 = EmbeddingGemma 2 "
                        "(the preferred model on macOS 15+, ~585 MB)")
    r = sub.add_parser("run", help="ingest → Sleep → answer → judge, unit by unit; resumable")
    r.add_argument("--cache", type=Path, required=True)
    r.add_argument("--dataset", choices=sorted(datasets.SOURCES), default="locomo")
    r.add_argument("--resume", help="a run folder to continue (its saved settings are used)")
    r.add_argument("--units", type=int, help="first N units (LoCoMo: conversations)")
    r.add_argument("--only", nargs="*", help="these unit ids only")
    r.add_argument("--per-category", type=int, help="first N questions of each category (stratified slice)")
    r.add_argument("--limit", type=int, help="at most N questions per unit (LongMemEval: N units)")
    r.add_argument("--include-adversarial", action="store_true",
                   help="LoCoMo category 5 too (scored apart with the abstention judge; never in the headline)")
    r.add_argument("--sleep-model", default="sonnet", help="Sleep's model on the plan (CICADA_AGENT_MODEL)")
    r.add_argument("--disambiguation-model", default="haiku")
    r.add_argument("--answer-model", default="sonnet")
    r.add_argument("--judge-model", default="sonnet")
    r.add_argument("--paths", default="ask", help="comma list: ask (cicada_ask) and/or full-context (the control)")
    r.add_argument("--sleep-schedule", choices=("once", "per-session"), default="once",
                   help="once: one drain after everything is staged; per-session: a drain after each session, "
                        "on that session's day (the nightly rhythm; more Sleep calls)")
    r.add_argument("--batch-size", type=int, default=25)
    r.add_argument("--embedding-model", default="", help="pin the search model id (default: what the home has)")
    r.add_argument("--concurrency", type=int, default=3, help="concurrent plan calls (CICADA_AGENT_MAX_CONCURRENCY)")
    r.add_argument("--claude-home", help="the home folder whose `claude` sign-in the plan calls use "
                                         "(default: yours; a separate signed-in folder works too)")
    r.add_argument("--fake-engine", action="store_true", help=argparse.SUPPRESS)   # offline test of the harness
    r.add_argument("--dataset-file", type=Path, help=argparse.SUPPRESS)          # with --fake-engine only
    rep = sub.add_parser("report", help="re-aggregate a run folder")
    rep.add_argument("--run", required=True)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    return {"prepare": prepare, "run": run, "report": report_cmd}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
