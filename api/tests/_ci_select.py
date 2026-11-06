"""Which backend test files a CI shard runs (2026-11-06).

A merge put an `UnboundLocalError` on `dev` that 27 tests could see, and no CI job ran any of them: CI ran only the crucial
tier. The whole suite is too slow for every PR, so a PR runs the test files that name what it changed, and a push to
`dev` runs them all, split across shards.

"Names" is one word in a test file's text, the changed file's stem. It's wider than an import on purpose: it also finds a
lazy import, a monkeypatch path and a gate that reads a source file. An import closure is no use here: 756 of 827 test
files reach `claim_reconciler` that way, and only 27 name it.

Run as a script, it prints one shard's files. `--all` selects every test file, `--changed-from REF` selects by the
diff from REF to HEAD."""
from __future__ import annotations

import argparse
import re
import subprocess
import zlib
from pathlib import Path

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parents[1]

# A change to one of these changes how every test runs, or which ones do.
EVERYTHING = {
    "api/tests/conftest.py",
    "api/tests/_ci_select.py",
    "api/pyproject.toml",
    "api/uv.lock",
    "Makefile",
    ".github/workflows/dev-ci.yml",
}
# Prose: every PR touches these, and a test naming one reads it for a reason its own gate covers.
SKIPPED_SUFFIXES = {".md"}


def all_test_files(tests: Path = TESTS) -> list[str]:
    return sorted(p.name for p in tests.glob("test_*.py"))


def word_of(changed: str) -> str | None:
    """The word a test would use for a changed file, or None for a file no test's selection follows."""
    path = Path(changed)
    if path.suffix in SKIPPED_SUFFIXES:
        return None
    return path.parent.name if path.stem == "__init__" else path.stem


def select(changed: list[str], tests: Path = TESTS) -> list[str]:
    """The test files a diff touches: every one, or those it changed plus those naming what it changed."""
    every = all_test_files(tests)
    if any(c in EVERYTHING for c in changed):
        return every
    selected = set()
    words = set()
    for c in changed:
        if c.startswith("api/tests/") and Path(c).name in every:
            selected.add(Path(c).name)
        elif (word := word_of(c)) and word != "conftest":
            words.add(word)
    if words:
        pattern = re.compile(r"(?<![A-Za-z0-9_-])(?:" + "|".join(map(re.escape, sorted(words))) + r")(?![A-Za-z0-9_-])")
        for name in every:
            if name not in selected and pattern.search((tests / name).read_text(encoding="utf-8", errors="replace")):
                selected.add(name)
    return sorted(selected)


def shard(files: list[str], index: int, total: int, tests: Path = TESTS) -> list[str]:
    """Shard `index` of `total` (from 1): biggest file first into the lightest shard, by size, the best cheap guess at time."""
    def size(name: str) -> int:
        return (tests / name).stat().st_size

    bins: list[list[str]] = [[] for _ in range(total)]
    loads = [0] * total
    for name in sorted(files, key=lambda n: (-size(n), zlib.crc32(n.encode()))):
        lightest = loads.index(min(loads))
        bins[lightest].append(name)
        loads[lightest] += size(name)
    return sorted(bins[index - 1])


def changed_since(ref: str) -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--name-only", "--no-renames", ref, "HEAD"],
        cwd=ROOT, check=True, capture_output=True, text=True,
    ).stdout
    return [line for line in out.splitlines() if line]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shard", required=True, help="index/total, from 1, like 2/6")
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--all", action="store_true")
    which.add_argument("--changed-from", metavar="REF")
    args = parser.parse_args()
    index, total = map(int, args.shard.split("/"))
    files = all_test_files() if args.all else select(changed_since(args.changed_from))
    for name in shard(files, index, total):
        print(f"api/tests/{name}")


if __name__ == "__main__":
    main()
