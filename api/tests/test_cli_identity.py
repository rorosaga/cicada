"""G180 / TODO ruling 21 — one place parses a harness's identity; two policies use it.

The stdio MCP mints a per-process id when the harness gives none (a stdio process IS one
conversation). The `cicada` command never mints: one process is one command, and a minted
id would fragment the stream (G104) — it omits the session instead, and keeps a harness
named without an id."""
from __future__ import annotations

import re

import pytest

from _stdio_server import stdio_server
from api.services import session_identity as si

UUID = "11111111-2222-4333-8444-555555555555"
MINTED = re.compile(r"^ses_\d{4}-\d{2}-\d{2}_[0-9a-f]{8}$")


@pytest.mark.parametrize("env, expected", [
    ({"CLAUDE_CODE_SESSION_ID": UUID, "CLAUDE_PROJECT_DIR": "/p"}, (UUID, "claude-code", "/p")),
    ({"CLAUDE_CODE_SESSION_ID": UUID}, (UUID, "claude-code", None)),
    ({"CICADA_SESSION_ID": "abc", "CICADA_SESSION_HARNESS": "codex"}, ("abc", "codex", None)),
    ({"CICADA_SESSION_ID": "abc"}, ("abc", "unknown", None)),
])
def test_stdio_identity_is_unchanged_when_the_harness_names_itself(env, expected):
    ident = si.stdio_identity(env)
    assert (ident.session_id, ident.harness, ident.project_dir) == expected


@pytest.mark.parametrize("env", [{}, {"CLAUDE_CODE_SESSION_ID": "not-a-uuid"}, {"CICADA_SESSION_HARNESS": "codex"}])
def test_stdio_identity_still_mints_one_id_per_process(env):
    ident = si.stdio_identity(env)
    assert MINTED.match(ident.session_id) and ident.harness == "unknown"


def test_the_server_reexports_the_one_implementation():
    server = stdio_server()
    assert server.resolve_session_identity is si.stdio_identity
    assert server.SessionIdentity is si.SessionIdentity


@pytest.mark.parametrize("env, expected", [
    ({"CLAUDE_CODE_SESSION_ID": UUID}, (UUID, "claude-code")),
    ({"CICADA_SESSION_ID": "abc", "CICADA_SESSION_HARNESS": "codex"}, ("abc", "codex")),
    ({"CICADA_SESSION_HARNESS": "codex"}, (None, "codex")),        # a harness named without an id is kept
    ({"CLAUDE_CODE_SESSION_ID": "not-a-uuid"}, (None, None)),
    ({}, (None, None)),                                            # never minted
])
def test_cli_identity_never_mints(env, expected):
    ident = si.cli_identity(env)
    assert (ident.session_id, ident.harness) == expected
