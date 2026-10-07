"""Who is calling: a harness's conversation identity, parsed in one place (G48, G180).

Two policies use the one parse:

- ``stdio_identity`` — the stdio MCP server's, unchanged from G48: a stdio process IS one
  conversation, so when the harness names none it mints ``ses_<date>_<hex>`` once per
  process (it groups that conversation's episodes; it never resumes).
- ``cli_identity`` — the ``cicada`` command's (TODO ruling 21): one process is one
  command, so it NEVER mints — a per-command id would fragment the stream (G104). With no
  id from the harness the session is omitted, and a harness named without an id is kept.

Ranked by reliability (the G48 spec): ``CLAUDE_CODE_SESSION_ID`` (strict UUID; Claude Code
injects it into its MCP servers and its shell commands) with ``CLAUDE_PROJECT_DIR``; then
``CICADA_SESSION_ID`` / ``CICADA_SESSION_HARNESS``, the explicit override for any harness.
NOTHING here reads a transcript.
"""
from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from datetime import date

SESSION_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


@dataclass(frozen=True)
class SessionIdentity:
    session_id: str
    harness: str
    project_dir: str | None = None


@dataclass(frozen=True)
class Parsed:
    session_id: str | None
    harness: str | None
    project_dir: str | None


def parse(env=None) -> Parsed:
    """What the environment says, and nothing more. Pure — pass ``env`` in tests."""
    env = os.environ if env is None else env
    project_dir = (env.get("CLAUDE_PROJECT_DIR") or "").strip() or None
    claude_id = (env.get("CLAUDE_CODE_SESSION_ID") or "").strip()
    if SESSION_UUID_RE.match(claude_id):
        return Parsed(claude_id, "claude-code", project_dir)
    explicit = (env.get("CICADA_SESSION_ID") or "").strip() or None
    harness = (env.get("CICADA_SESSION_HARNESS") or "").strip() or None
    return Parsed(explicit, harness, project_dir)


def stdio_identity(env=None) -> SessionIdentity:
    """The stdio MCP server's identity (G48): a harness-named id, else one minted per process."""
    p = parse(env)
    if p.harness == "claude-code" and p.session_id:
        return SessionIdentity(p.session_id, "claude-code", p.project_dir)
    if p.session_id:
        return SessionIdentity(p.session_id, p.harness or "unknown", p.project_dir)
    return SessionIdentity(f"ses_{date.today().isoformat()}_{uuid.uuid4().hex[:8]}", "unknown", None)


def cli_identity(env=None) -> Parsed:
    """The ``cicada`` command's identity: exactly what the harness gave, never a minted id."""
    return parse(env)
