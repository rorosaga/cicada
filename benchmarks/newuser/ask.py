"""Ask the synthetic new user's 25 questions through the MCP stdio server, and grade them.

    api/.venv/bin/python -m benchmarks.newuser.ask --run <verify-cicada run dir> --repeats 3 --out results.jsonl
    api/.venv/bin/python -m benchmarks.newuser.ask --summary results.jsonl
    api/.venv/bin/python -m benchmarks.newuser.ask --compare before.jsonl after.jsonl
    api/.venv/bin/python -m benchmarks.newuser.ask --regrade results.jsonl     # after editing questions.json

Each question is one `tools/call` on a fresh `mcp/server.py` spawned with the run's environment (the door a new
user's agent uses); a `cwd` on the question becomes the harness's project folder (`CLAUDE_PROJECT_DIR`), so
`cicada_continue` asks about that folder. Answers are graded by spelling (`expect` groups, `forbid`, `abstain`) into
correct / partial / wrong / refused: a first pass, cheap and repeatable, that a person reads before quoting it.
Every line records the reply's size in characters and approximate tokens (characters / 4).
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import threading
import time
import uuid
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
#: Phrases that mean "the record does not hold this" — an abstention when it was asked for, a refusal otherwise.
NOT_KNOWN = ("don't have", "do not have", "doesn't say", "does not say", "not recorded", "isn't recorded",
             "no record", "not in the record", "not in memory", "doesn't record", "does not record",
             "no information", "not mentioned", "isn't mentioned", "can't find", "cannot find", "couldn't find",
             "nothing in", "no mention", "not stated", "isn't stated", "unknown", "not available", "doesn't mention",
             "does not mention", "doesn't include", "does not include", "not enough", "no data")


def _env(run: dict, cwd: str | None) -> dict:
    env = {k: os.environ[k] for k in ("PATH", "TMPDIR", "LANG", "LC_ALL", "USER", "LOGNAME") if k in os.environ}
    env.update(run["env"])
    env["CICADA_CAPTURE"] = "off"
    if cwd:
        env.update({"CLAUDE_CODE_SESSION_ID": str(uuid.uuid4()), "CLAUDE_PROJECT_DIR": cwd,
                    "CICADA_SESSION_HARNESS": "claude-code"})
    else:
        env.update({"CICADA_SESSION_ID": f"newuser-{run['run_id']}", "CICADA_SESSION_HARNESS": "verify"})
    return env


def call(run: dict, tool: str, arguments: dict, *, cwd: str | None = None, timeout: float = 240.0) -> dict:
    """One stdio session: initialize, initialized, one tools/call. Returns {text, isError, seconds, init}."""
    proc = subprocess.Popen([run["python"], str(Path(run["worktree"]) / "mcp/server.py")], cwd=run["run_dir"],
                            env=_env(run, cwd), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True, start_new_session=True)
    lines: queue.Queue = queue.Queue()
    threading.Thread(target=lambda: [lines.put(x) for x in proc.stdout] + [lines.put(None)], daemon=True).start()

    def send(msg: dict) -> dict | None:
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()
        if "id" not in msg:
            return None
        deadline = time.time() + timeout
        while True:
            out = lines.get(timeout=max(deadline - time.time(), 0.1))
            if out is None:
                raise RuntimeError("server closed stdout")
            try:
                reply = json.loads(out)
            except ValueError:
                continue
            if reply.get("id") == msg["id"]:
                return reply

    started = time.time()
    try:
        init = send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "newuser-bench", "version": "1"}}})
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        t0 = time.time()
        reply = send({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": tool, "arguments": arguments}})
        seconds = time.time() - t0
    except (queue.Empty, RuntimeError) as exc:
        return {"text": "", "isError": True, "error": type(exc).__name__, "seconds": time.time() - started}
    finally:
        try:
            proc.stdin.close()
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
    result = reply.get("result") or {}
    text = "\n".join(b.get("text", "") for b in result.get("content", []) if isinstance(b, dict))
    return {"text": text, "isError": bool(result.get("isError") or "error" in reply), "seconds": round(seconds, 2),
            "instructions": (init.get("result") or {}).get("instructions") or ""}


def grade(q: dict, text: str, is_error: bool) -> tuple[str, list]:
    low = text.lower()
    hit = [any(s.lower() in low for s in group) for group in q.get("expect", [])]
    forbidden = [s for s in q.get("forbid", []) if s.lower() in low]
    unknown = any(p in low for p in NOT_KNOWN)
    if q.get("abstain"):
        return ("correct" if unknown and not forbidden else "wrong"), forbidden
    if is_error or not text.strip():
        return "refused", forbidden
    if forbidden:
        return "wrong", forbidden
    if hit and all(hit):
        return "correct", forbidden
    if any(hit):
        return "partial", forbidden
    return ("refused" if unknown else "wrong"), forbidden


def run_questions(run_dir: Path, questions: Path, repeats: int, out: Path, only: set[str] | None) -> None:
    run = json.loads((run_dir / "run.json").read_text())
    qs = [q for q in json.loads(questions.read_text())["questions"] if not only or q["id"] in only]
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a") as fh:
        for rep in range(1, repeats + 1):
            for q in qs:
                r = call(run, q["tool"], q["args"], cwd=q.get("cwd"))
                verdict, forbidden = grade(q, r["text"], r["isError"])
                row = {"id": q["id"], "kind": q["kind"], "tool": q["tool"], "repeat": rep, "verdict": verdict,
                       "forbidden": forbidden, "chars": len(r["text"]), "tokens": len(r["text"]) // 4,
                       "seconds": r["seconds"], "isError": r["isError"], "text": r["text"]}
                fh.write(json.dumps(row) + "\n")
                fh.flush()
                print(f"rep {rep} {q['id']} {q['tool']:16} {verdict:8} {row['tokens']:>5} tok {r['seconds']:>6}s")
    instructions = call(run, "cicada_timeline", {"since": "1"})["instructions"]
    out.with_suffix(".handshake.txt").write_text(instructions)


def _rows(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def summary(path: Path) -> dict:
    rows = _rows(path)
    per_rep: dict[int, Counter] = defaultdict(Counter)
    per_q: dict[str, list] = defaultdict(list)
    for r in rows:
        per_rep[r["repeat"]][r["verdict"]] += 1
        per_q[r["id"]].append(r["verdict"])
    correct = [c["correct"] for c in per_rep.values()]
    score = [c["correct"] + 0.5 * c["partial"] for c in per_rep.values()]
    flips = {q: v for q, v in per_q.items() if len(set(v)) > 1}
    biggest = max(rows, key=lambda r: r["tokens"]) if rows else None
    out = {"repeats": len(per_rep), "questions": len(per_q),
           "correct_mean": round(sum(correct) / len(correct), 2) if correct else 0,
           "correct_min_max": [min(correct), max(correct)] if correct else [],
           "score_mean": round(sum(score) / len(score), 2) if score else 0,
           "score_min_max": [min(score), max(score)] if score else [],
           "per_repeat": {k: dict(v) for k, v in sorted(per_rep.items())},
           "per_question": {q: dict(Counter(v)) for q, v in sorted(per_q.items())},
           "flips": flips, "max_tokens": biggest and {"id": biggest["id"], "tokens": biggest["tokens"]}}
    return out


def regrade(path: Path, questions: Path) -> None:
    """Grade stored answers again with the current questions file (a fixed spelling list costs no new calls)."""
    by_id = {q["id"]: q for q in json.loads(questions.read_text())["questions"]}
    rows = _rows(path)
    for r in rows:
        r["verdict"], r["forbidden"] = grade(by_id[r["id"]], r["text"], r["isError"])
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def compare(before: Path, after: Path) -> dict:
    a, b = summary(before), summary(after)
    moved = {}
    for q in sorted(set(a["per_question"]) | set(b["per_question"])):
        if a["per_question"].get(q) != b["per_question"].get(q):
            moved[q] = {"before": a["per_question"].get(q), "after": b["per_question"].get(q)}
    return {"before": {k: a[k] for k in ("correct_mean", "correct_min_max", "score_mean", "score_min_max")},
            "after": {k: b[k] for k in ("correct_mean", "correct_min_max", "score_mean", "score_min_max")},
            "moved": moved}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", type=Path)
    ap.add_argument("--questions", type=Path, default=HERE / "questions.json")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--only", help="comma-separated question ids")
    ap.add_argument("--summary", type=Path)
    ap.add_argument("--compare", nargs=2, type=Path)
    ap.add_argument("--regrade", type=Path, help="re-grade a results file with the current questions")
    args = ap.parse_args()
    if args.regrade:
        regrade(args.regrade, args.questions)
        print(json.dumps(summary(args.regrade), indent=1))
    elif args.summary:
        print(json.dumps(summary(args.summary), indent=1))
    elif args.compare:
        print(json.dumps(compare(*args.compare), indent=1))
    else:
        if not (args.run and args.out):
            ap.error("--run and --out are required to ask")
        run_questions(args.run, args.questions, args.repeats, args.out,
                      set(args.only.split(",")) if args.only else None)


if __name__ == "__main__":
    main()
