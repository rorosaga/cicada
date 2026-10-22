"""Fingerprint the code VideoQueue.tla describes, so a change to it cannot slip past the model.

python3 coverage.py           compare every covered function and constant with coverage.lock
python3 coverage.py --update  rewrite coverage.lock (only after re-reading the changed code against the model)

A fingerprint is the sha256 of the function's source as `ast` sees it (formatting kept, nothing else)."""
from __future__ import annotations

import ast
import hashlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
LOCK = HERE / "coverage.lock"

COVERED = {
    "api/services/video_queue.py": [
        "LEASE_MINUTES", "MAX_ATTEMPTS", "EXPIRE_FAILED_DAYS", "CLAIM_PAGE", "DEFAULT_CLAIM",
        "clean_code", "_read_file", "_locked", "_write", "_failed_expiry", "_lapsed", "_settle", "_drop_orphans",
        "view", "_saved", "_open", "_reset", "_upsert", "put", "remove", "retry", "handoff", "_refresh", "claim",
        "release", "complete",
    ],
    "api/services/video_state.py": ["newer_than", "satisfies", "clean_basis", "saved_videos"],
    "api/services/mcp_tools.py": ["ToolContext.pages_held", "record_watch", "_credit_video_queue", "video_claim"],
    "api/routers/videos.py": ["_view", "_put", "delete_video_queue", "_retry", "_handoff"],
}


def _nodes(tree: ast.Module):
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node.name, node
        elif isinstance(node, ast.ClassDef):
            for inner in node.body:
                if isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    yield f"{node.name}.{inner.name}", inner
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    yield target.id, node


def fingerprints() -> dict[str, str]:
    out = {}
    for rel, names in COVERED.items():
        source = (ROOT / rel).read_text(encoding="utf-8")
        found = dict(_nodes(ast.parse(source)))
        for name in names:
            node = found.get(name)
            segment = ast.get_source_segment(source, node) if node is not None else None
            out[f"{rel}::{name}"] = hashlib.sha256(segment.encode()).hexdigest()[:16] if segment else "MISSING"
    return out


def main(argv: list[str]) -> int:
    now = fingerprints()
    if argv[:1] == ["--update"]:
        LOCK.write_text("".join(f"{k} {v}\n" for k, v in now.items()), encoding="utf-8")
        print(f"coverage.lock rewritten ({len(now)} entries); move the sync commit in SKILL.md to this commit")
        return 0
    was = dict(line.split(" ", 1) for line in LOCK.read_text(encoding="utf-8").split("\n") if line)
    was = {k: v.strip() for k, v in was.items()}
    changed = sorted(k for k in now.keys() | was.keys() if now.get(k) != was.get(k))
    if changed:
        print("Covered code changed since the sync commit; the model may no longer describe it:")
        for k in changed:
            print(f"  {k}")
        print("Re-read each against SKILL.md's coverage table, update VideoQueue.tla if the behaviour moved, rerun, "
              "then `python3 coverage.py --update` and move the sync commit.")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
