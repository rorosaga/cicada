"""The tests a change can break, chosen from the change itself (owner 2026-11-24: "when developing features only relevant
tests run"). `make test-changed` runs them; the crucial tier, CI and the whole suite stay what they were
(docs/goals/working-method.md, "Test tiers").

The change is every file that differs from the merge base with `origin/dev`: commits on the branch, the index, the
working tree and untracked files. What it selects:

- **Python, by name.** The diff's hunks name the top-level functions, classes and constants that changed, on the old
  side and the new (so a deleted function counts), and that set grows to whatever in the same module refers to them. A
  test file runs when it uses one of those names from that module (imported by name, as `module.name`, through a
  `monkeypatch` target string) or hands the module around whole. A change to module-level code that is not an import, a
  definition or a constant counts as the whole module.
- **Callers, one hop.** A module that imports a changed name counts its own definitions that use it as changed, and the
  tests using those run too. `api.main` imports every router, so it is never a caller.
- **Routes.** A changed endpoint selects the tests whose strings name its path, so a test that reaches it through the
  app (`TestClient(app)`) runs too.
- **Any file a test names.** A test whose string literals name a changed file by its repository path, or by a
  distinctive file name, runs: the source scans, the script and hook tests, the docs-size checks. Docstrings and
  comments never count.
- **The gates.** Whenever Python under `api/` or `mcp/` changes, the repository-wide inventories run too (`GATES`):
  they read every module or route, so no import ties them to the one that moved.
- **Swift.** A changed source file selects the test classes whose file names a type it declares or its own file name;
  any source change adds the `*Lint*` classes, which scan every source. A changed test file selects its own classes.
- **Graph JS.** A change under the graph's resources or tests runs every `Tests/graph/*.test.js` (a few seconds).
- **Everything.** `conftest.py`, the lockfile or `pyproject.toml` reach every backend test: the whole backend suite,
  said in words.

It is a fast first net, not a proof: CI's crucial tier still runs on every PR and the whole suite on every push to
`dev`. Its known blind spot is a test that drives a subprocess (`_stdio_server`'s MCP server, a hook, a second backend):
it is chosen only by what it imports or names, never by what the subprocess runs.

Run as a script: `--pytest` prints the backend test files (nothing when none), `--swift-filter` one `swift test
--filter` regex (empty when none), `--node` the graph test files, `--explain` why each was chosen. `--base <ref>` diffs
against another ref."""
from __future__ import annotations

import argparse
import ast
import functools
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# Python roots importable as `<root>.<path>` from the repository root.
PY_ROOTS = ("api", "mcp", "scripts", "plugins", "tools", "benchmarks", "clients", "relay")
SKIP_DIRS = {".venv", "node_modules", ".build", "__pycache__", ".git"}

# A module that imports every router for wiring: never a caller.
HUBS = {"api.main"}

# Files whose change reaches every backend test.
EVERYTHING = {"api/tests/conftest.py", "api/pyproject.toml", "api/uv.lock"}

# The repository-wide inventories: each reads every module, route or tool, so it guards a change no import ties it to.
# Three merges on 2026-11-24 went red on these, which the PR checks never ran.
GATES = (
    "test_write_admission_sites.py",
    "test_replica_routes_inventory.py",
    "test_event_readers_gate.py",
    "test_section_provenance_writer_inventory.py",
    "test_request_listings_gate.py",
    "test_question_order_gate.py",
    "test_backend_never_reads_folders.py",
    "test_owner_name_portability.py",
    "test_sync_relay_isolation.py",
    "test_mcp_schema_size.py",
    "test_cli_map.py",
    "test_claude_md_size.py",
)

# File names too common to tie a test to one file by name alone.
COMMON_NAMES = {"__init__.py", "README.md", "server.py", "main.py", "config.py", "models.py", "utils.py",
                "Package.swift", "index.html", "SKILL.md", "install.sh", "Makefile", "TODO.md"}

WHOLE = "*"  # a module-level change, or a module handed around whole


def _git(*args: str, repo: Path = REPO) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False).stdout


def merge_base(base: str, repo: Path = REPO) -> str:
    return _git("merge-base", "HEAD", base, repo=repo).strip() or base


def changed_files(base: str = "origin/dev", repo: Path = REPO) -> list[str]:
    """Every path that differs from the merge base with `base`, untracked files included."""
    ref = merge_base(base, repo)
    paths = _git("diff", "--name-only", ref, repo=repo).splitlines()
    paths += _git("ls-files", "--others", "--exclude-standard", repo=repo).splitlines()
    return sorted({p for p in paths if p.strip()})


# --- reading Python -----------------------------------------------------------------------------------------------


def _module_name(rel: Path) -> str:
    parts = list(rel.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def python_modules(repo: Path = REPO) -> dict[str, Path]:
    """Dotted name → file for every Python file under the importable roots; test files are not modules here."""
    out: dict[str, Path] = {}
    for root in PY_ROOTS:
        base = repo / root
        if base.is_dir():
            for path in base.rglob("*.py"):
                rel = path.relative_to(repo)
                if not SKIP_DIRS.intersection(rel.parts) and not path.name.startswith("test_"):
                    out[_module_name(rel)] = path
    return out


@dataclass
class Py:
    """One file's imports and uses, read once."""
    symbols: dict[str, tuple[int, int]] = field(default_factory=dict)  # top-level name → (first, last) line
    other: list[tuple[int, int]] = field(default_factory=list)          # module-level code that is no definition
    imports: set[str] = field(default_factory=set)                      # repo modules imported
    uses: dict[str, set[str]] = field(default_factory=dict)             # repo module → names used from it, or WHOLE
    sym_uses: dict[str, dict[str, set[str]]] = field(default_factory=dict)  # top-level name → module → names
    sym_refs: dict[str, set[str]] = field(default_factory=dict)         # top-level name → bare names it refers to
    strings: str = ""                                                   # every string literal but docstrings


def _resolve(name: str, modules) -> tuple[str, str] | None:
    """`a.b.c` → (deepest module prefix, the next part or "")."""
    parts = name.split(".")
    for i in range(len(parts), 0, -1):
        mod = ".".join(parts[:i])
        if mod in modules:
            return mod, (parts[i] if i < len(parts) else "")
    return None


def _toplevel_ranges(tree: ast.Module):
    symbols: dict[str, tuple[int, int]] = {}
    other: list[tuple[int, int]] = []
    for node in tree.body:
        start = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
        end = node.end_lineno or node.lineno
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols[node.name] = (start, end)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = [t.id for t in targets if isinstance(t, ast.Name)]
            if names:
                for n in names:
                    symbols[n] = (start, end)
            else:
                other.append((start, end))
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            continue  # an import alone changes nothing a test can see; the code that uses it is what changed
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue  # the module docstring
        else:
            other.append((start, end))
    return symbols, other


def _read(path: Path, own: str, modules, source: str | None = None) -> Py:
    py = Py()
    try:
        tree = ast.parse(source if source is not None else path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, OSError, ValueError):
        return py
    py.symbols, py.other = _toplevel_ranges(tree)
    package = own if path.name == "__init__.py" else own.rpartition(".")[0]
    is_test = "tests" in path.parts
    bindings: dict[str, tuple[str, str]] = {}  # local name → (module, attribute or "" for the module itself)

    def bind(local: str, target: str) -> None:
        hit = _resolve(target, modules)
        if hit is None and is_test and target.startswith("_"):
            hit = _resolve(f"api.tests.{target}", modules)
        if hit:
            py.imports.add(hit[0])
            bindings[local] = hit

    # One walk per top-level statement, shared by every pass below (a walk per pass cost two minutes a tree).
    walked = [(stmt, list(ast.walk(stmt))) for stmt in tree.body]
    for _, nodes in walked:
        for node in nodes:
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.asname:
                        bind(a.asname, a.name)
                        continue
                    hit = _resolve(a.name, modules) or (_resolve(f"api.tests.{a.name}", modules) if is_test else None)
                    if hit:
                        py.imports.add(hit[0])
                        root = a.name.split(".")[0]
                        bindings[root] = (hit[0], "") if "." not in a.name else (root, "")
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    anchor = package.split(".")
                    if node.level > 1:
                        anchor = anchor[: len(anchor) - (node.level - 1)]
                    stem = ".".join(anchor + ([node.module] if node.module else []))
                else:
                    stem = node.module or ""
                for a in node.names:
                    bind(a.asname or a.name, f"{stem}.{a.name}" if stem else a.name)

    docstrings = set()
    for node in [tree] + [n for _, nodes in walked for n in nodes]:
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    strings: list[str] = []

    def dotted(node: ast.AST) -> tuple[list[str], ast.Name] | None:
        parts = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        return (parts[::-1], node) if isinstance(node, ast.Name) else None

    def scan(nodes: list[ast.AST]) -> tuple[dict[str, set[str]], set[str]]:
        """What these nodes use from each repo module, and every bare name or attribute they refer to."""
        out: dict[str, set[str]] = {}
        refs: set[str] = set()
        consumed = set()  # module names already read as `m.f` or `setattr(m, "f")`
        for node in nodes:
            if isinstance(node, ast.Attribute):
                refs.add(node.attr)
                chain = dotted(node)
                if chain is None or chain[1].id not in bindings or id(chain[1]) in consumed:
                    continue
                mod, attr = bindings[chain[1].id]
                if attr:
                    continue
                # `m.f`, or `api.services.m.f` after `import api.services.m`: the deepest module, then the next name.
                hit = _resolve(".".join([mod, *chain[0]]), modules)
                if hit and hit[1]:
                    out.setdefault(hit[0], set()).add(hit[1])
                    consumed.add(id(chain[1]))
            elif (isinstance(node, ast.Call) and len(node.args) >= 2 and isinstance(node.args[0], ast.Name)
                    and node.args[0].id in bindings and not bindings[node.args[0].id][1]
                    and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str)):
                # `monkeypatch.setattr(m, "f", …)`, `patch.object(m, "f")`, `getattr(m, "f")`: one attribute.
                out.setdefault(bindings[node.args[0].id][0], set()).add(node.args[1].value)
                consumed.add(id(node.args[0]))
        for node in nodes:
            if isinstance(node, ast.Name):
                refs.add(node.id)
                if node.id in bindings and id(node) not in consumed:
                    mod, attr = bindings[node.id]
                    out.setdefault(mod, set()).add(attr or WHOLE)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
                strings.append(node.value)
                if "." in node.value and re.fullmatch(r"[A-Za-z_][\w.]+", node.value):
                    hit = _resolve(node.value, modules)
                    if hit and hit[1]:
                        out.setdefault(hit[0], set()).add(hit[1])
        return out, refs

    for stmt, nodes in walked:
        uses, refs = scan(nodes)
        for mod, used in uses.items():
            py.uses.setdefault(mod, set()).update(used)
        names = []
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names = [stmt.name]
        elif isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
            names = [t.id for t in targets if isinstance(t, ast.Name)]
        for n in names:
            py.sym_uses[n] = uses
            py.sym_refs[n] = refs
    # A name imported from a module is a use of it (`from m import f` uses `f`).
    for mod, attr in bindings.values():
        if attr:
            py.uses.setdefault(mod, set()).add(attr)
    py.strings = "\n".join(strings)
    py.imports.discard(own)
    py.uses.pop(own, None)
    return py


# --- what changed inside a module ---------------------------------------------------------------------------------


_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", re.M)


def _hunks(ref: str, rel: str, repo: Path) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """Changed line ranges on the old side and the new side."""
    old, new = [], []
    for m in _HUNK.finditer(_git("diff", "-U0", ref, "--", rel, repo=repo)):
        a, b = int(m.group(1)), int(m.group(2) or 1)
        c, d = int(m.group(3)), int(m.group(4) or 1)
        old.append((a, a + max(b, 1) - 1))
        new.append((c, c + max(d, 1) - 1))
    return old, new


def _touched(ranges, symbols, other) -> set[str]:
    out = set()
    for lo, hi in ranges:
        for name, (s, e) in symbols.items():
            if s <= hi and lo <= e:
                out.add(name)
        if any(s <= hi and lo <= e for s, e in other):
            out.add(WHOLE)
    return out


def changed_symbols(rel: str, mod: str, ref: str, repo: Path, modules, tracked: bool) -> set[str]:
    """The top-level names a diff touched in one module, grown to what in the module refers to them."""
    path = repo / rel
    if not tracked or not path.exists():
        return {WHOLE}
    old_src = _git("show", f"{ref}:{rel}", repo=repo)
    if not old_src:
        return {WHOLE}
    old_ranges, new_ranges = _hunks(ref, rel, repo)
    new = _tree(repo)[1].get(mod) or _read(path, mod, modules)
    old_symbols, old_other = _toplevel_ranges(ast.parse(old_src)) if _parses(old_src) else ({}, [(1, 10**9)])
    changed = _touched(new_ranges, new.symbols, new.other) | _touched(old_ranges, old_symbols, old_other)
    return _grow(changed, new)


def _parses(src: str) -> bool:
    try:
        ast.parse(src)
        return True
    except SyntaxError:
        return False


def _grow(changed: set[str], py: Py) -> set[str]:
    if WHOLE in changed:
        return {WHOLE}
    grown = set(changed)
    while True:
        more = {n for n, refs in py.sym_refs.items() if n not in grown and refs & grown}
        if not more:
            return grown
        grown |= more


def _hits(used: set[str] | None, changed: set[str]) -> str | None:
    """The changed name a file uses from a module, or None."""
    if not used:
        return None
    if WHOLE in changed:
        return "the module"
    if WHOLE in used:
        return "the module, passed whole"
    both = used & changed
    return sorted(both)[0] if both else None


# --- routes -------------------------------------------------------------------------------------------------------

_ROUTE = re.compile(r"""@\w+\.(?:get|post|put|delete|patch|api_route|websocket)\(\s*["']([^"']+)["']""")
_PREFIX = re.compile(r"""APIRouter\([^)]*prefix\s*=\s*["']([^"']+)["']""")


def _route_paths(text: str, py: Py, names: set[str]) -> list[str]:
    """The static part of each changed endpoint's path in a router module."""
    prefix = (_PREFIX.search(text) or [None, ""])[1]
    out = []
    lines = text.splitlines()
    for name, (s, e) in py.symbols.items():
        if WHOLE not in names and name not in names:
            continue
        for m in _ROUTE.finditer("\n".join(lines[s - 1:e])):
            static = (prefix + m.group(1)).split("{", 1)[0].rstrip("/")
            if len(static) > 3:
                out.append(static)
    return out


# --- the tree -----------------------------------------------------------------------------------------------------


@functools.cache
def _tree(repo: Path):
    """The repository's Python, parsed once per process: modules, each module's reading, each test file's reading."""
    modules = python_modules(repo)
    mods = {name: _read(path, name, modules) for name, path in modules.items()}
    tests = {p.name: _read(p, f"api.tests.{p.stem}", modules) for p in sorted((repo / "api/tests").glob("test_*.py"))}
    return modules, mods, tests


@dataclass
class Selection:
    pytest: dict[str, str] = field(default_factory=dict)
    swift: dict[str, str] = field(default_factory=dict)
    node: dict[str, str] = field(default_factory=dict)
    everything: str = ""

    @staticmethod
    def add(kind: dict[str, str], key: str, why: str) -> None:
        kind.setdefault(key, why)


def select(changed: list[str], repo: Path = REPO, base: str = "origin/dev", ref: str | None = None) -> Selection:
    sel = Selection()
    modules, mods, tests = _tree(repo)
    ref = ref or merge_base(base, repo)
    tracked = set(_git("ls-files", repo=repo).splitlines())
    by_path = {str(p.relative_to(repo)): name for name, p in modules.items()}

    for path in changed:
        if path in EVERYTHING:
            sel.everything = path

    # Python: the names that changed in each module, then one hop to the modules that use them.
    names: dict[str, set[str]] = {}
    for rel in changed:
        if rel.endswith(".py") and not Path(rel).name.startswith("test_"):
            mod = by_path.get(rel) or _module_name(Path(rel))
            names[mod] = changed_symbols(rel, mod, ref, repo, modules, rel in tracked)
    hop: dict[str, set[str]] = {}
    for caller, py in mods.items():
        if caller in HUBS or caller in names:
            continue
        touched = set()
        for mod, changed_names in names.items():
            if mod not in py.imports:
                continue
            for sym, uses in py.sym_uses.items():
                if _hits(uses.get(mod), changed_names):
                    touched.add(sym)
        if touched:
            hop[caller] = _grow(touched, py)

    for test, py in tests.items():
        for mod, changed_names in sorted(names.items()):
            hit = _hits(py.uses.get(mod), changed_names)
            if hit:
                sel.add(sel.pytest, test, f"uses {mod}: {hit}")
                break
        else:
            for mod, changed_names in sorted(hop.items()):
                hit = _hits(py.uses.get(mod), changed_names)
                if hit:
                    sel.add(sel.pytest, test, f"uses {mod}: {hit} (a caller)")
                    break

    for rel in changed:
        p = Path(rel)
        if p.parent == Path("api/tests") and p.name.startswith("test_") and (repo / p).exists():
            sel.add(sel.pytest, p.name, "changed")

    # Routes a changed endpoint serves, for the tests that reach a router only through the app.
    for rel in changed:
        if rel.startswith("api/routers/") and rel.endswith(".py") and (repo / rel).exists():
            mod = by_path.get(rel)
            text = (repo / rel).read_text(encoding="utf-8", errors="replace")
            for route in _route_paths(text, mods[mod], names.get(mod, {WHOLE})) if mod in mods else []:
                for test, py in tests.items():
                    if mod not in py.imports and "api.main" in py.imports and route in py.strings:
                        sel.add(sel.pytest, test, f"calls {route}")

    # Any file a test names in a string.
    for rel in changed:
        p = Path(rel)
        needles = [rel] + ([p.name] if p.name not in COMMON_NAMES and len(p.stem) > 3 else [])
        for test, py in tests.items():
            if any(n in py.strings for n in needles):
                sel.add(sel.pytest, test, f"names {p.name}")

    if any(p.endswith(".py") and p.split("/", 1)[0] in ("api", "mcp") and not p.startswith("api/tests/")
           for p in changed):
        for gate in GATES:
            if gate in tests:
                sel.add(sel.pytest, gate, "a repository-wide gate")

    swift = [p for p in changed if p.endswith(".swift")]
    if swift and (repo / "app/CicadaApp/Tests/CicadaAppTests").is_dir():
        _select_swift(sel, swift, repo)

    if any(p.startswith(("app/CicadaApp/Sources/CicadaApp/Resources/graph/", "app/CicadaApp/Tests/graph/"))
           for p in changed):
        for t in sorted((repo / "app/CicadaApp/Tests/graph").glob("*.test.js")):
            sel.add(sel.node, str(t.relative_to(repo)), "the graph changed")
    return sel


# --- Swift --------------------------------------------------------------------------------------------------------

_DECL = re.compile(r"^\s*(?:@\w+\s+)*(?:(?:public|private|fileprivate|internal|final|open|indirect)\s+)*"
                   r"(?:class|struct|enum|protocol|actor|extension)\s+([A-Z]\w*)", re.M)
_TEST_CLASS = re.compile(r"class\s+(\w+)\s*:\s*XCTestCase")
SWIFT_HUB = 40  # test files naming one type, past which the type is everywhere


def _select_swift(sel: Selection, changed: list[str], repo: Path) -> None:
    tests_root = repo / "app/CicadaApp/Tests/CicadaAppTests"
    sources_root = repo / "app/CicadaApp/Sources"
    texts = {p: p.read_text(encoding="utf-8", errors="replace") for p in tests_root.rglob("*.swift")}
    classes = {p: _TEST_CLASS.findall(t) for p, t in texts.items()}
    declared: set[str] = set()
    for src in sources_root.rglob("*.swift"):
        declared.update(_DECL.findall(src.read_text(encoding="utf-8", errors="replace")))

    source_changed = False
    for rel in changed:
        full = repo / rel
        if full.is_relative_to(tests_root):
            for cls in classes.get(full, []):
                sel.add(sel.swift, cls, "changed")
            continue
        if not full.is_relative_to(sources_root):
            continue
        source_changed = True
        stem = Path(rel).stem
        found = {stem.split("+")[0]} | ({stem} if "+" not in stem else set())
        if full.exists():
            found |= {n for n in _DECL.findall(full.read_text(encoding="utf-8", errors="replace")) if n in declared}
        # An extension file (`Copy+Inbox.swift`) names its own part, not the type everything extends.
        if "+" in stem:
            found.discard(stem.split("+")[0])
            found.add(stem.split("+")[1])
        for name in sorted(found):
            word = re.compile(rf"\b{re.escape(name)}\b")
            named = [t for t, text in texts.items() if word.search(text)]
            if len(named) > SWIFT_HUB:
                # A type most tests touch (`APIClient`, `Copy`): its own test classes, not every test that names it.
                named = [t for t in named if t.stem.startswith(name)]
            for test in named:
                for cls in classes[test]:
                    sel.add(sel.swift, cls, f"names {name}")
    if source_changed:
        for cls_list in classes.values():
            for cls in cls_list:
                if "Lint" in cls:
                    sel.add(sel.swift, cls, "a lint over every source")


def swift_filter(classes) -> str:
    return "|".join(rf"\.{re.escape(c)}/" for c in sorted(classes))


def run(sel: Selection, slow: bool, repo: Path = REPO) -> int:
    """`make test-changed`: the selection's backend files, Swift classes and graph tests, niced, one after another."""
    nice = ["nice", "-n", "10"]
    failed = 0
    files = ["api/tests"] if sel.everything else [f"api/tests/{f}" for f in sorted(sel.pytest)]
    if sel.everything:
        print(f"test-changed: {sel.everything} changed, so every backend test runs", flush=True)
    if files:
        print(f"test-changed: {len(files)} backend test files (`--explain` says why each)", flush=True)
        cmd = [*nice, sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *files]
        if slow:
            cmd[cmd.index("-q"):cmd.index("-q")] = ["-m", "not bench"]
        failed |= subprocess.run(cmd, cwd=repo).returncode
        held = [f for f in files if f != "api/tests" and "@pytest.mark.slow" in (repo / f).read_text(encoding="utf-8")]
        if held and not slow:
            print(f"test-changed: {len(held)} of these files hold `slow` tests, left out; `make test-changed SLOW=1` "
                  f"runs them ({', '.join(Path(h).name for h in held[:5])}{', …' if len(held) > 5 else ''})", flush=True)
    else:
        print("test-changed: no backend test reaches this change", flush=True)
    if sel.swift:
        print(f"test-changed: {len(sel.swift)} Swift test classes", flush=True)
        failed |= subprocess.run([*nice, "swift", "test", "--filter", swift_filter(sel.swift)],
                                 cwd=repo / "app" / "CicadaApp").returncode
    if sel.node:
        failed |= subprocess.run(["node", "--test", *sorted(sel.node)], cwd=repo).returncode
    return 1 if failed else 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", default="origin/dev")
    ap.add_argument("--slow", action="store_true", help="with --run: the `slow` tests of the chosen files too")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--pytest", action="store_true")
    mode.add_argument("--swift-filter", action="store_true")
    mode.add_argument("--node", action="store_true")
    mode.add_argument("--explain", action="store_true")
    args = ap.parse_args(argv)
    sel = select(changed_files(args.base), base=args.base)
    if args.run:
        return run(sel, args.slow)
    if args.pytest:
        print("api/tests" if sel.everything else " ".join(f"api/tests/{f}" for f in sorted(sel.pytest)))
    elif args.swift_filter:
        print(swift_filter(sel.swift))
    elif args.node:
        print(" ".join(sorted(sel.node)))
    else:
        if sel.everything:
            print(f"backend: every test ({sel.everything} changed)")
        print(f"backend: {len(sel.pytest)} files")
        for f, why in sorted(sel.pytest.items()):
            print(f"  {f}  — {why}")
        print(f"swift: {len(sel.swift)} classes")
        for c, why in sorted(sel.swift.items()):
            print(f"  {c}  — {why}")
        print(f"graph js: {len(sel.node)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
