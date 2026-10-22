"""The crucial tier's two lists (owner 2026-10-19): `crucial.txt` here for the backend, `app/CicadaApp/Tests/
crucial-tests.txt` for the Swift tests. `conftest.py` marks what the backend list names; `make test-crucial` runs both;
`test_crucial_tier.py` holds every line to a real test.

Run as a script, it prints what the Makefile needs: `--files` the backend files, `--swift-filter` one `swift test
--filter` regex."""
from __future__ import annotations

import re
import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parent
BACKEND_LIST = TESTS / "crucial.txt"
SWIFT_LIST = TESTS.parents[1] / "app" / "CicadaApp" / "Tests" / "crucial-tests.txt"


def lines(path: Path) -> list[str]:
    """Every entry of a list, without comments, headings or blanks."""
    out = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            out.append(line)
    return out


def backend_entries(path: Path = BACKEND_LIST) -> list[tuple[str, tuple[str, ...]]]:
    """`(file name, test path inside it)` per line; an empty path is the whole file."""
    out = []
    for line in lines(path):
        file, *rest = line.split("::")
        out.append((file, tuple(rest)))
    return out


def backend_files(path: Path = BACKEND_LIST) -> list[str]:
    return list(dict.fromkeys(file for file, _ in backend_entries(path)))


def is_crucial(file_name: str, test_path: tuple[str, ...], entries) -> bool:
    """Whether a collected test (`test_x.py`, `("Class", "test_y")` with any `[param]` dropped) is on the list."""
    for file, path in entries:
        if file == file_name and (not path or tuple(test_path[: len(path)]) == path):
            return True
    return False


def swift_filter(path: Path = SWIFT_LIST) -> str:
    """One regex over `Module.Class/testMethod` names: a class line matches its every test, a method line itself."""
    parts = []
    for line in lines(path):
        cls, _, method = line.partition("/")
        parts.append(rf"\.{re.escape(cls)}/{re.escape(method)}$" if method else rf"\.{re.escape(cls)}/")
    return "|".join(parts)


if __name__ == "__main__":
    if sys.argv[1:] == ["--files"]:
        print(" ".join(f"api/tests/{f}" for f in backend_files()))
    elif sys.argv[1:] == ["--swift-filter"]:
        print(swift_filter())
    else:
        sys.exit("usage: _crucial.py --files | --swift-filter")
