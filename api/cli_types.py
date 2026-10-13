"""The `cicada` command's shared outcome types (G180): one copy, imported by `api.cli` and `api.cli_app`.

They live apart from `api/cli.py` because `python -m api.cli` runs that file as `__main__`: a second module
importing `api.cli` would get a second copy of every class, and `except Refusal` would stop matching. Pure:
no service import (the bootstrap must run before any).
"""
from __future__ import annotations

from dataclasses import dataclass, field

#: A typed refusal → not ok. Each has an exit code in ``EXIT_CODES``.
REFUSAL_CODES = frozenset({
    "not_found", "empty_graph", "demo_bank",
    # A command that acts on the running backend (Sleep, the search model, settings it owns, bank switches).
    "backend_down", "backend_timeout", "backend_error", "unauthorized", "sleep_writing", "refused",
    # A command that changes the memory as the person, run from a shell that names an agent's session.
    "person_only",
})

EXIT_CODES = {"usage": 2, "not_found": 1, "empty_graph": 1, "bank_mismatch": 3, "root_mismatch": 3,
              "root_unverified": 3, "demo_bank": 4, "sandbox_denied": 5, "backend_down": 6, "backend_timeout": 6,
              "sleep_writing": 1, "refused": 1, "unauthorized": 1, "person_only": 1,
              "backend_error": 70, "internal": 70, "bootstrap": 70}


class UsageError(Exception):
    """A malformed command line: exit 2."""


class Refusal(Exception):
    """A rule said no before anything was read or written. ``warnings`` ride on the refusal's envelope (the root
    cross-check's ``root_unverified`` above all, so a refused write still says why it could not be checked)."""

    def __init__(self, code: str, message: str, warnings: list[str] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.warnings = list(warnings or [])


@dataclass
class Result:
    text: str
    data: dict | None
    warnings: list[str] = field(default_factory=list)
    code: str | None = None

    @property
    def ok(self) -> bool:
        return self.code not in REFUSAL_CODES
