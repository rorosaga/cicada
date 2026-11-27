"""The gate: no generator expression awaits (2026-11-27).

`any(await f(x) for x in xs)` reads like a loop and is an async generator: `any`, `all`, `sum`, `sorted`, `tuple`, `"".join`
and every other plain consumer raise `TypeError: 'async_generator' object is not iterable` the moment the line runs, whatever
`xs` holds. Inside a step that "never fails a Sleep" that error is caught and counted as a skip, so the step quietly never
runs: the which-one reader (ruling 83) did not read one question on its first real night for exactly this. A list, set or
dict comprehension that awaits is fine (it is evaluated in place); only the parenthesised generator form is refused. Write
a loop, or a list comprehension handed to the consumer.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TREES = ("api", "mcp", "scripts", "benchmarks", "clients", "plugins")
SKIP = {".venv", "node_modules", ".build", "__pycache__"}


def _awaiting_generators(tree: ast.AST) -> list[int]:
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.GeneratorExp):
            continue
        # The first `for`'s iterable is evaluated where the expression is written, so an await there is an ordinary one.
        inner = [node.elt, *(c for g in node.generators for c in g.ifs), *(g.iter for g in node.generators[1:])]
        if any(g.is_async for g in node.generators) or any(isinstance(x, ast.Await) for part in inner for x in ast.walk(part)):
            lines.append(node.lineno)
    return lines


def _python_files():
    for top in TREES:
        for folder, dirs, files in os.walk(ROOT / top):
            dirs[:] = sorted(d for d in dirs if d not in SKIP)   # pruned, never walked: a virtualenv is tens of thousands of files
            yield from (Path(folder) / name for name in sorted(files) if name.endswith(".py"))


def test_no_generator_expression_awaits():
    found = []
    for path in _python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        found += [f"{path.relative_to(ROOT)}:{line}" for line in _awaiting_generators(tree)]
    assert not found, "a generator expression that awaits is an async generator; use a loop or a list comprehension: " + ", ".join(found)


def test_the_scan_sees_the_shape_and_leaves_comprehensions_alone():
    bad = "async def f(xs):\n    return any(await g(x) for x in xs)\n"
    also_bad = "async def f(xs):\n    return sum(x async for x in xs)\n"
    fine = "async def f(xs):\n    return any([await g(x) for x in xs]) or sum(y for y in await h(xs))\n"
    assert _awaiting_generators(ast.parse(bad)) == [2] and _awaiting_generators(ast.parse(also_bad)) == [2]
    assert _awaiting_generators(ast.parse(fine)) == []
