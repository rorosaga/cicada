"""A `$NAME` directly followed by a non-ASCII byte is read by bash (3.2 and 5) under a UTF-8 locale as part of
the name, which `set -u` turns into "unbound variable" (G182). Brace it: `${NAME}…`."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BAD = re.compile(r"\$[A-Za-z_0-9][A-Za-z0-9_]*[^\x00-\x7f]")


def _shell_texts():
    names = subprocess.run(["git", "ls-files", "*.sh"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    for n in names:
        if (ROOT / n).is_file():
            yield n, (ROOT / n).read_text(encoding="utf-8")
    install_md = ROOT / "install.md"
    if install_md.is_file():
        blocks = re.findall(r"```(?:sh|bash|shell|zsh)?\n(.*?)```", install_md.read_text(encoding="utf-8"), re.S)
        yield "install.md", "\n".join(blocks)


def test_no_unbraced_expansion_precedes_a_non_ascii_byte():
    hits = [f"{name}:{i}: {line.strip()}" for name, text in _shell_texts()
            for i, line in enumerate(text.splitlines(), 1) if BAD.search(line)]
    assert not hits, "brace the expansion (${NAME}) before a non-ASCII character:\n" + "\n".join(hits)
