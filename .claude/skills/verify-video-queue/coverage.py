"""Keep VideoQueue.tla in step with the code it describes.

python3 coverage.py           compare the covered code with coverage.lock, and check every line citation
python3 coverage.py --update  rewrite coverage.lock (only after re-reading the changed code against the model)

Three checks, each a reason to exit 3:
- A fingerprint moved. A fingerprint is the sha256 of a definition's source, decorators included. For the two
  reply builders in REPLY_BUILDERS it is the sha256 of the definition's syntax tree with sentence-like strings
  (any string with a space, every f-string, every docstring) blanked, so rewording a reply does not move it, while
  any change to a call, an argument, a condition or a short string key does.
- The set of places that name a queue writer (video_queue.put, remove, retry, handoff, claim, release, complete)
  is not the set in coverage.lock. A new caller is a new actor the model may not have.
- A citation `<module>.<name>:<line>` in the skill's files names a line outside that definition, or a line number
  appears without a qualified name in front of it."""
from __future__ import annotations

import ast
import hashlib
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
LOCK = HERE / "coverage.lock"

MODULES = {
    "video_queue": "api/services/video_queue.py",
    "video_state": "api/services/video_state.py",
    "mcp_tools": "api/services/mcp_tools.py",
    "watch_record": "api/services/watch_record.py",
    "episode_ids": "api/services/episode_ids.py",
    "session_identity": "api/services/session_identity.py",
    "tool_door": "api/services/tool_door.py",
    "explore_queue": "api/services/explore_queue.py",
    "cli_app": "api/cli_app.py",
    "cli": "api/cli.py",
    "runtime": "api/remote/runtime.py",
    "videos": "api/routers/videos.py",
    "server": "mcp/server.py",
}

COVERED = {
    "video_queue": [
        "LEASE_MINUTES", "MAX_ATTEMPTS", "EXPIRE_FAILED_DAYS", "CLAIM_PAGE", "DEFAULT_CLAIM",
        "_iso", "_parse", "_now", "_stat", "_clean_row", "clean_code", "_read_file", "_locked", "_write",
        "_failed_expiry", "_lapsed", "_settle", "_drop_orphans", "view", "_saved", "_records_fn", "_open", "_reset",
        "_upsert", "put", "remove", "retry", "handoff", "_refresh", "claim", "release", "complete",
    ],
    "video_state": ["BASES", "basis_facts", "clean_basis", "saved_videos", "watch_records", "newer_than", "satisfies",
                    "_parse"],
    "mcp_tools": ["SLEEP_PROBE_TIMEOUT_S", "_backend_sleep_running", "ToolContext.pages_held", "record_watch",
                  "_credit_video_queue", "video_claim"],
    "watch_record": ["_write_episode", "record"],
    "episode_ids": ["utc_now_iso"],
    "session_identity": ["parse", "stdio_identity", "cli_identity"],
    "tool_door": ["Caller", "context"],
    "cli_app": ["door"],
    "cli": ["_tool_context"],
    "runtime": ["mint_handle", "resolve_handle"],
    "videos": ["_view", "_put", "delete_video_queue", "_retry", "_handoff"],
}
REPLY_BUILDERS = {"mcp_tools::record_watch", "mcp_tools::video_claim", "watch_record::record"}

WRITERS = {"put", "remove", "retry", "handoff", "claim", "release", "complete"}
CALLER_ROOTS = ("api", "mcp", "plugins")

CITED_FILES = ["SKILL.md", "statechart.md", "VideoQueue.tla", "trace.py"]
CITED_OUTSIDE = ["api/tests/test_video_queue_formal.py"]
CITE = re.compile(r"\b(" + "|".join(sorted(MODULES, key=len, reverse=True)) + r")\.(?!py:)([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?):(\d+)")
BARE = re.compile(r"(?:(?<![\w\]\)\"'])|(?<=\.py)):\d{2,4}\b")


def definitions(rel: str) -> dict[str, ast.AST]:
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    out: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out[node.name] = node
            if isinstance(node, ast.ClassDef):
                for inner in node.body:
                    if isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        out[f"{node.name}.{inner.name}"] = inner
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                if isinstance(target, ast.Name):
                    out[target.id] = node
    return out


class _BlankSentences(ast.NodeTransformer):
    def visit_JoinedStr(self, node):
        return ast.Constant("")

    def visit_Constant(self, node):
        if isinstance(node.value, str) and " " in node.value:
            return ast.Constant("")
        return node


def _canon(value) -> str:
    # Interpreter-independent: ast.dump drops empty fields from 3.13 and 3.15 adds ImportFrom.is_lazy=0, so a field
    # that is None, [] or (outside a Constant's value) 0 is left out rather than letting the lock depend on the version.
    if isinstance(value, ast.AST):
        def kept(v):
            return v is not None and v != [] and (isinstance(value, ast.Constant) or type(v) not in (int, bool) or v)
        fields = (f"{f}={_canon(v)}" for f in value._fields if kept(v := getattr(value, f, None)))
        return f"{type(value).__name__}({','.join(fields)})"
    if isinstance(value, list):
        return "[" + ",".join(_canon(v) for v in value) + "]"
    return repr(value)


def fingerprint(source: str, node: ast.AST, reply_builder: bool) -> str:
    if reply_builder:
        text = _canon(_BlankSentences().visit(node))
    else:
        first = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
        text = "\n".join(source.splitlines()[first - 1:node.end_lineno])
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def fingerprints() -> dict[str, str]:
    out = {}
    for module, names in COVERED.items():
        rel = MODULES[module]
        source = (ROOT / rel).read_text(encoding="utf-8")
        found = definitions(rel)
        for name in names:
            key = f"{module}::{name}"
            node = found.get(name)
            out[key] = fingerprint(source, node, key in REPLY_BUILDERS) if node is not None else "MISSING"
    return out


def _enclosing(tree: ast.Module) -> dict[int, str]:
    owner: dict[int, str] = {}

    def walk(node, name):
        for child in ast.iter_child_nodes(node):
            inner = name
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                inner = f"{name}.{child.name}" if name else child.name
            owner[id(child)] = inner or "<module>"
            walk(child, inner)

    walk(tree, "")
    return owner


def callers() -> list[str]:
    found = set()
    for root in CALLER_ROOTS:
        for path in sorted((ROOT / root).rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            if "/tests/" in rel or rel.startswith("api/tests") or "/.venv/" in rel or rel == MODULES["video_queue"]:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            owner = _enclosing(tree)
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in WRITERS and isinstance(node.value, ast.Name) \
                        and node.value.id == "video_queue":
                    found.add(f"{rel}::{owner.get(id(node), '<module>')}::{node.attr}")
                elif isinstance(node, ast.ImportFrom) and node.module == "api.services.video_queue":
                    found.add(f"{rel}::{owner.get(id(node), '<module>')}::from-import")
    return sorted(found)


def citation_errors() -> list[str]:
    defs = {m: definitions(rel) for m, rel in MODULES.items()}
    errors = []
    paths = [HERE / f for f in CITED_FILES] + [ROOT / f for f in CITED_OUTSIDE]
    for path in paths:
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for m in CITE.finditer(line):
                module, name, cited = m.group(1), m.group(2), int(m.group(3))
                node = defs[module].get(name)
                where = f"{path.relative_to(ROOT)}:{n}: {m.group(0)}"
                if node is None:
                    errors.append(f"{where} names no definition in {MODULES[module]}")
                elif not node.lineno <= cited <= node.end_lineno:
                    errors.append(f"{where} is outside {name} (lines {node.lineno}-{node.end_lineno})")
            rest = CITE.sub("", line)
            for m in BARE.finditer(rest):
                errors.append(f"{path.relative_to(ROOT)}:{n}: '{m.group(0)}' cites a line with no <module>.<name> "
                              "in front of it")
    return errors


def lock_text(prints: dict[str, str], calls: list[str]) -> str:
    return "".join(f"{k} {v}\n" for k, v in prints.items()) + "".join(f"caller {c}\n" for c in calls)


def main(argv: list[str]) -> int:
    prints, calls = fingerprints(), callers()
    if argv[:1] == ["--update"]:
        LOCK.write_text(lock_text(prints, calls), encoding="utf-8")
        print(f"coverage.lock rewritten ({len(prints)} definitions, {len(calls)} callers); move the sync commit in "
              "SKILL.md to this commit")
        return 0 if not citation_errors() else 3
    was_prints, was_calls = {}, set()
    for line in LOCK.read_text(encoding="utf-8").splitlines():
        if line.startswith("caller "):
            was_calls.add(line[len("caller "):])
        elif line:
            key, value = line.split(" ", 1)
            was_prints[key] = value.strip()
    status = 0
    changed = sorted(k for k in prints.keys() | was_prints.keys() if prints.get(k) != was_prints.get(k))
    if changed:
        status = 3
        print("Covered code changed since the sync commit; the model may no longer describe it:")
        for k in changed:
            print(f"  {k}")
    added, gone = sorted(set(calls) - was_calls), sorted(was_calls - set(calls))
    if added or gone:
        status = 3
        print("The places that call a queue writer changed (a new caller is an actor the model may lack):")
        for c in added:
            print(f"  new   {c}")
        for c in gone:
            print(f"  gone  {c}")
    errors = citation_errors()
    if errors:
        status = 3
        print("Line citations that no longer point inside the definition they name:")
        for e in errors:
            print(f"  {e}")
    if status:
        print("Re-read each against SKILL.md's coverage table, update VideoQueue.tla if the behaviour moved, fix the "
              "citations, rerun, then `python3 coverage.py --update` and move the sync commit.")
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
