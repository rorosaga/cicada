"""The checkout's own venv, for the tests that run a script the way a person runs it — never collected.

`scripts/cicada`, `scripts/import-backlog.sh`, `scripts/check-census.sh` and `scripts/repair_entity_prose.py` run
`<checkout>/api/.venv/bin/python` (the launcher refuses without it; the shell scripts fall back to a bare `python3`
that has none of the backend's packages). A git worktree has no venv of its own, so there these tests have nothing
to run: they skip and say why rather than fail on an environment that is not the product's.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
VENV_PYTHON = REPO / "api" / ".venv" / "bin" / "python"

needs_checkout_venv = pytest.mark.skipif(
    not VENV_PYTHON.exists(),
    reason=f"no venv in this checkout ({VENV_PYTHON.relative_to(REPO)}): the script under test runs the checkout's "
           "own Python; run ./install.sh here (a git worktree has none)",
)
