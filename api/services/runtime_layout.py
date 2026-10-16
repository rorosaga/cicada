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
LAUNCHERS = ("cicada-backend", "cicada-mcp", "cicada-hook", "cicada-python", "cicada")


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


def local_backend_url(environ=os.environ) -> str:
    """This machine's own backend on loopback. What the backend uses to reach itself, whatever a client setting says."""
    return f"http://127.0.0.1:{port(environ)}"


# --- A client of a backend on another machine (G181 phase 2) -----------------------------------------------------
#
# ``CICADA_API_BASE`` names the backend this machine's hooks, stdio MCP server and `cicada` command talk to when it
# is not this machine's own: the address the person's own overlay gives the server (e.g. ``tailscale serve``'s
# https name, or an SSH tunnel's loopback port). Unset, every client keeps today's loopback behaviour byte for byte.
# Set, the machine is a CLIENT: nothing reads or writes a local bank, every call goes to that base with this device's
# own token (``CICADA_API_TOKEN``, else ``$CICADA_HOME/device_token``), which the person issued on the server
# (``cicada device add``) and copied here themselves. No host or address is ever written in code or docs.
#
# Stdlib only: the hooks import this module by path, with no venv guarantee.

API_BASE_ENV = "CICADA_API_BASE"
TOKEN_ENV = "CICADA_API_TOKEN"
DEVICE_TOKEN_FILE = "device_token"
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def is_client(environ=os.environ) -> bool:
    """True when ``CICADA_API_BASE`` is set to anything: an invalid value still means "not this machine's bank", so a
    typo fails loudly at the request (and capture spools) rather than writing into a local bank by accident."""
    return bool((environ.get(API_BASE_ENV) or "").strip())


def api_base(environ=os.environ) -> str:
    """``CICADA_API_BASE`` checked and normalised (no trailing slash). https for any host; plain http only to a
    loopback address (an SSH tunnel's local end), so a bearer token never crosses a network in clear text.
    ``ValueError`` names the rule, never echoes the value."""
    from urllib.parse import urlsplit

    raw = (environ.get(API_BASE_ENV) or "").strip()
    try:
        parts = urlsplit(raw)
        host = parts.hostname
        parts.port  # noqa: B018 - raises ValueError on a malformed port
    except ValueError:
        raise ValueError(f"{API_BASE_ENV} is not a URL") from None
    if parts.scheme not in ("http", "https") or not host:
        raise ValueError(f"{API_BASE_ENV} must be an http(s) address")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError(f"{API_BASE_ENV} must carry no credentials, query or fragment")
    if parts.scheme == "http" and host not in _LOOPBACK_HOSTS:
        raise ValueError(f"{API_BASE_ENV} must use https unless it is a loopback address")
    return f"{parts.scheme}://{parts.netloc}{parts.path.rstrip('/')}"


def client_token(environ=os.environ) -> str:
    """This device's token: ``CICADA_API_TOKEN``, else ``$CICADA_HOME/device_token``; "" when neither holds one.
    Never the server's master token, which never leaves the server (owner ruling 1, 2026-10-16)."""
    token = (environ.get(TOKEN_ENV) or "").strip()
    if token:
        return token
    try:
        return (cicada_home(environ) / DEVICE_TOKEN_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def backend_url(environ=os.environ) -> str:
    """The backend this machine's clients talk to: ``CICADA_API_BASE`` when it is set (a server elsewhere), else this
    machine's own on loopback (``CICADA_PORT``, else 8000). An invalid base raises ``ValueError``."""
    if is_client(environ):
        return api_base(environ)
    return local_backend_url(environ)


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
