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
    # G181 phase 2: a command that reads the memory folder, run on a client of a server (the folder is there).
    "on_server",
    # G199: a tool body's own refusals. The MCP doors answer every code here with `isError: true`
    # (`tool_contract.is_error`), so a code means the same thing on the command line and to an agent.
    "invalid_arguments", "out_of_range", "error",
})

EXIT_CODES = {"usage": 2, "not_found": 1, "empty_graph": 1, "bank_mismatch": 3, "root_mismatch": 3,
              "root_unverified": 3, "demo_bank": 4, "sandbox_denied": 5, "backend_down": 6, "backend_timeout": 6,
              "sleep_writing": 1, "refused": 1, "unauthorized": 1, "person_only": 1, "on_server": 1,
              "invalid_arguments": 2, "out_of_range": 2, "error": 70,
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


@dataclass(frozen=True)
class RemotePin:
    """G181 phase 2: the bank a client command runs in — the server's active bank when the command started, its name
    and id. Every mutating request names both (``X-Cicada-Bank``, ``X-Cicada-Bank-Id``), so a server whose active bank
    moved, or a base that now reaches another memory, refuses before anything is written. No path: the bank is on
    the server."""

    name: str
    id: str | None
    path: None = None
