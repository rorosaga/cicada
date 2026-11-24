"""Replay battery for `value_ended` (G148, 2026-11-23): does a drop close the value that names what was dropped?

Why: a conversation says the thing dropped X. The page's link to X closes; a value whose literal carries X with
something more ("implementation language: Python with Pillow") must close too, and a value that only mentions X, or is
about another part or purpose of the thing, must stay. A benchmark run meets this about once; this replays the real
judge call many times, through the product's own `value_ended.plan` (the same prompt, words read back from located
spans), for cents. Every name, value and line below is invented.

    api/.venv/bin/python -m benchmarks.consolidation.value_ended_battery --repeats 20

Needs ``ANTHROPIC_API_KEY`` in the environment or in ``--key-file`` (never printed). Exit 1 when a CLOSE case stays
open or a STAY case closes, in any repeat.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

# (name, should close, subject, old attribute, old literal, old line, label, dropped id, dropped name, ending line)
CASES = [
    ("a language dropped, its library named with it", True, "alpha-project", "implementation language", "Python with Pillow",
     "I'm writing it in Python with Pillow for now.", "dropped", "python", "Python",
     "I rewrote the core in TypeScript so it runs in the browser, and dropped the Python version entirely."),
    ("the same, said in Spanish", True, "proyecto-luz", "lenguaje de implementación", "Python con Pillow",
     "Lo estoy escribiendo en Python con Pillow por ahora.", "dropped", "python", "Python",
     "Reescribí el núcleo en TypeScript y dejé Python por completo."),
    ("a host moved off", True, "notebook-app", "hosting", "Heroku with a Postgres add-on",
     "I host it on Heroku with a Postgres add-on.", "dropped", "heroku", "Heroku",
     "I moved the whole thing off Heroku to Fly last week."),
    ("an editor given up", True, "setup-notes", "editor", "VS Code with Vim keys",
     "I write code in VS Code with Vim keys.", "stopped using", "vs-code", "VS Code",
     "I stopped using VS Code, I'm on Zed now."),
    ("the API moves, the scripts stay", False, "orbit-tool", "scripting language", "Python with Click",
     "The helper scripts are in Python with Click.", "dropped", "python", "Python",
     "I moved the API off Python to Go, but the helper scripts are still Python."),
    ("a reason that only mentions it", False, "orbit-tool", "reason for the rewrite", "Python was too slow for large inputs",
     "The rewrite is because Python was too slow for large inputs.", "dropped", "python", "Python",
     "Orbit dropped Python, the rewrite is done."),
    ("another purpose of the dropped thing", False, "orbit-tool", "data analysis tooling", "Python notebooks",
     "I do the analysis in Python notebooks.", "dropped", "python", "Python",
     "We dropped Python from the app itself, the notebooks stay as they are."),
    ("another prototype dropped, the engine stays", False, "orbit-tool", "engine language", "Rust with Tokio",
     "The engine is Rust with Tokio.", "dropped", "rust", "Rust",
     "I dropped the Rust prototype of the importer, the engine itself stays Rust with Tokio."),
    ("two languages at once, one dropped from one part", False, "orbit-tool", "implementation languages", "Python and Rust",
     "Orbit is written in Python and Rust.", "dropped", "python", "Python",
     "I dropped Python from the build scripts; the Rust core and the Python bindings stay."),
    ("named in passing in a longer literal", False, "orbit-tool", "inspiration", "a Python tutorial series on cutting layouts",
     "The idea came from a Python tutorial series on cutting layouts.", "dropped", "python", "Python",
     "I dropped Python from Orbit last week and rewrote it in Rust."),
]


def build(case):
    from api.services import evidence
    from api.services.claims import Claim, value_predicate

    _name, _close, subject, attribute, literal, old_line, label, thing, thing_name, end_line = case
    bank = Path(tempfile.mkdtemp(prefix="ended-bank-"))
    (bank / "episodes").mkdir()
    for ep, day, line in (("ep_2026-09-01_001", "2026-09-01", old_line), ("ep_2026-11-08_001", "2026-11-08", end_line)):
        (bank / "episodes" / f"{ep}.md").write_text(
            f"---\nid: {ep}\ntimestamp: '{day}T10:00:00+00:00'\nsource: import\nprocessed: true\n---\n\nuser: {line}\n",
            encoding="utf-8")
    old = Claim(id="old", text=f"{subject} {attribute}: {literal}", subject=subject, predicate=value_predicate(attribute),
                object=literal, object_kind="literal", valid_from="2026-09-01", source_episodes=["ep_2026-09-01_001"],
                source_trust="agent_extracted", origin="benchmark")
    old.evidence = [evidence.verify(bank, "ep_2026-09-01_001", old_line)]
    end = Claim(id="end", text=f"{subject} {label} {thing_name}", subject=subject, predicate=label, object=thing,
                object_kind="node", valid_from="2026-11-08", source_episodes=["ep_2026-11-08_001"],
                source_trust="agent_extracted", origin="benchmark")
    end.predicate_raw = label
    end.evidence = [evidence.verify(bank, "ep_2026-11-08_001", end_line)]
    return [end], {subject: [old]}, bank


def main(argv=None) -> int:
    from benchmarks.consolidation import engines

    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=20)
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--key-file", default="~/.cicada/secrets.env")
    engines.add_argument(ap)
    args = ap.parse_args(argv)
    os.environ["CICADA_HOME"] = tempfile.mkdtemp(prefix="ended-home-")
    from api.services import value_alignment, value_ended

    if args.engine == "key":
        from benchmarks.engine_parity import read_key_file

        key = os.environ.get("ANTHROPIC_API_KEY") or read_key_file(Path(args.key_file))
        if not key:
            print("no ANTHROPIC_API_KEY", file=sys.stderr)
            return 2
        os.environ["ANTHROPIC_API_KEY"] = key
    engines.arm(args.engine)
    with engines.tally() as counted:
        judge = value_alignment.judge_for(engines.settings(args.engine, Path(tempfile.mkdtemp()), model=args.model, judge=args.model))
        jobs = [(c, i) for c in CASES for i in range(args.repeats)]

        def one(job):
            case, _i = job
            incoming, existing, bank = build(case)
            return case, bool(value_ended.plan(incoming, existing, judge, bank)[1])

        with ThreadPoolExecutor(8 if args.engine == "key" else 3) as pool:
            results = list(pool.map(one, jobs))
        wrong = 0
        for case in CASES:
            closed = sum(1 for c, did in results if c is case and did)
            bad = (args.repeats - closed) if case[1] else closed
            wrong += bad
            print(f"{'CLOSE' if case[1] else 'STAY '}  {closed:>3}/{args.repeats} closed  {'WRONG x' + str(bad) if bad else 'ok'}  {case[0]}")
        print(f"wrong answers: {wrong} of {len(results)}")
        if args.engine == "plan":
            print(counted.report())
    return 1 if wrong else 0


if __name__ == "__main__":
    raise SystemExit(main())
