"""G76 (round 4): `install.md` is the fresh-Mac path a person pastes into an
agent — it names real commands, real Make targets, the README's clone URL and no
machine's paths."""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TEXT = (REPO / "install.md").read_text(encoding="utf-8")


def test_it_names_the_real_steps():
    for command in ("./install.sh", "make install-app", "open ~/Applications/Cicada.app",
                    "http://127.0.0.1:8000/healthz"):
        assert command in TEXT, command
    clone = re.search(r"git clone (\S+)", (REPO / "README.md").read_text(encoding="utf-8")).group(1)
    assert f"git clone {clone}" in TEXT
    targets = set(re.findall(r"^([a-z][a-z-]*):", (REPO / "Makefile").read_text(encoding="utf-8"), re.M))
    for target in re.findall(r"make ([a-z][a-z-]*)", TEXT):
        assert target in targets, target


def test_it_never_loops_the_doctor_and_names_no_machine():
    assert "/Users/" not in TEXT and "/home/" not in TEXT
    assert "in a loop" in TEXT  # the fresh-bank doctor checks fail until the first Sleep (G76 prereq)
