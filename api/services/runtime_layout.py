"""Where this backend runs from: a developer checkout or a release app (G182).

A release app carries its own Python, code and git under
``Cicada.app/Contents/Resources/backend``; its launchers export
``CICADA_DISTRIBUTION=release``. Agents, hooks and the background service never
name a path inside the app: they run the stable launchers the app rewrites in
``$CICADA_HOME/bin`` each time it opens, so moving or updating the app breaks
nothing. A developer checkout (the variable unset) keeps today's
``<repo>/api/.venv/bin/python <script>`` commands byte for byte.

The app holds the same table (``CicadaRuntime.swift``) and runs only argv that
match it (``AgentConnectPolicy``); ``test_runtime_layout.py`` pins both sides'
shapes.
"""
from __future__ import annotations

import os
from pathlib import Path

DISTRIBUTION_ENV = "CICADA_DISTRIBUTION"
DEFAULT_PORT = 8000
#: The launchers the app writes into ``$CICADA_HOME/bin`` (release only).
LAUNCHERS = ("cicada-backend", "cicada-mcp", "cicada-hook", "cicada-python")


def is_release(environ=os.environ) -> bool:
    return (environ.get(DISTRIBUTION_ENV) or "").strip() == "release"


def cicada_home(environ=os.environ) -> Path:
    return Path(environ.get("CICADA_HOME") or (Path.home() / ".cicada")).expanduser()


def bin_dir(environ=os.environ) -> Path:
    return cicada_home(environ) / "bin"


def launcher(name: str, environ=os.environ) -> str:
    if name not in LAUNCHERS:
        raise ValueError(f"not a Cicada launcher: {name}")
    return str(bin_dir(environ) / name)


def port(environ=os.environ) -> int:
    """``CICADA_PORT`` when it is a valid port, else 8000 — the backend, the MCP
    server and the hooks all read the same variable (the launchers export it)."""
    raw = (environ.get("CICADA_PORT") or "").strip()
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_PORT
    return value if 0 < value < 65536 else DEFAULT_PORT


def backend_url(environ=os.environ) -> str:
    return f"http://127.0.0.1:{port(environ)}"


# --- The commands an agent runs (the app's allowlist holds the same shapes) ---

def mcp_argv(python: str, repo: Path, environ=os.environ) -> list[str]:
    """The MCP server's command: the launcher in a release, the venv + script in a checkout."""
    if is_release(environ):
        return [launcher("cicada-mcp", environ)]
    return [python, str(repo / "mcp" / "server.py")]


def registry_argv(python: str, repo: Path, environ=os.environ) -> list[str]:
    """The prefix that runs ``api/hooks/registry.py`` (two elements in both shapes)."""
    if is_release(environ):
        return [launcher("cicada-hook", environ), "registry"]
    return [python, str(repo / "api" / "hooks" / "registry.py")]


def hook_command(kind: str, python: str, repo: Path, harness: str, environ=os.environ) -> str:
    """The string a harness settings file runs for ``capture`` (Stop) or ``recall``.
    The checkout's shape is ``install.sh``'s ``hook_command``, character for character."""
    if kind not in ("capture", "recall"):
        raise ValueError(f"not a Cicada hook: {kind}")
    if is_release(environ):
        return f'"{launcher("cicada-hook", environ)}" {kind} --harness {harness}'
    return f'"{python}" "{repo}/api/hooks/{kind}.py" --harness {harness}'
