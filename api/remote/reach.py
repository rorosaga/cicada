"""How AI apps reach this Mac (G135 R-R32) — detection only; Cicada never starts,
stops or reconfigures a tunnel (G132 (c): the overlay is the person's).

Tailscale: on PATH, in a standard install folder (`TUNNEL_BIN_DIRS`), or the app
bundle's own CLI — an older LaunchAgent's PATH is launchd's bare one, and
`install.sh` never rewrites a plist behind a running backend (F2-back R-B15).
`tailscale funnel status --json`
is read-only; its ServeConfig is searched for an `AllowFunnel` host whose `/`
handler proxies to our port on loopback — anything else (another port, a
sub-path, a serve-only host) is not a door to Cicada. ngrok: presence only. Its
public URL is not auto-detected, because its local API is part of the
inspector we ask people to turn off (`--inspect=false`); the person pastes it.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from urllib.parse import urlparse

from api.remote import catalog

TAILSCALE_APP_CLI = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}


@dataclass(frozen=True)
class Reach:
    tailscale: str  # "missing" | "stopped" | "no-funnel" | "funnel-on"
    funnel_url: str | None
    ngrok: bool


def _proxies_to(proxy: str, port: int) -> bool:
    target = proxy if "://" in proxy else f"http://{proxy}"
    try:
        parsed = urlparse(target)
        return parsed.hostname in _LOOPBACK and parsed.port == port
    except ValueError:
        return False


def _dict(value) -> dict:
    """The ServeConfig is another program's JSON: a key holding a list or a
    string where a map belongs is "no door", never an AttributeError that turns
    `GET /remote/status` into a 500 (G135 final review)."""
    return value if isinstance(value, dict) else {}


def funnel_url_for_port(status: dict, port: int) -> str | None:
    configs = [status] + [v for v in _dict(status.get("Foreground")).values() if isinstance(v, dict)]
    for config in configs:
        allowed = _dict(config.get("AllowFunnel"))
        for hostport, web in _dict(config.get("Web")).items():
            if not allowed.get(hostport):
                continue
            root = _dict(_dict(_dict(web).get("Handlers")).get("/"))
            if _proxies_to(str(root.get("Proxy") or ""), port):
                host, _, public_port = hostport.rpartition(":")
                return f"https://{host}" if public_port in ("443", "") else f"https://{host}:{public_port}"
    return None


#: Where Homebrew (Apple silicon, then Intel) and a hand-installed binary put
#: `ngrok` and `tailscale` (F2-back R-B15). Under an older LaunchAgent's bare
#: PATH, `shutil.which` alone reported ngrok missing on a Mac where it was
#: installed — the same trap `connections.base._CLI_FALLBACK_DIRS` closed for
#: the engine CLIs. Reach keeps its own list so detection stays injectable.
TUNNEL_BIN_DIRS: tuple[str, ...] = ("/opt/homebrew/bin", "/usr/local/bin", "~/bin", "~/.local/bin")


def _is_executable(path: str) -> bool:
    return os.path.isfile(path) and os.access(path, os.X_OK)


def find_tool(name: str, *, which=shutil.which, exists=_is_executable) -> str | None:
    """``name`` on PATH, else in :data:`TUNNEL_BIN_DIRS`. Looks; never runs it."""
    found = which(name)
    if found:
        return found
    for folder in TUNNEL_BIN_DIRS:
        candidate = os.path.join(os.path.expanduser(folder), name)
        if exists(candidate):
            return candidate
    return None


def detect(port: int, *, which=shutil.which, run=subprocess.run, exists=_is_executable) -> Reach:
    ngrok = bool(find_tool("ngrok", which=which, exists=exists))
    tailscale = find_tool("tailscale", which=which, exists=exists) or (
        TAILSCALE_APP_CLI if exists(TAILSCALE_APP_CLI) else None)
    if not tailscale:
        return Reach("missing", None, ngrok)
    try:
        done = run([tailscale, "funnel", "status", "--json"], capture_output=True, text=True, timeout=2.0,
                   check=False)
        status = json.loads(done.stdout or "{}") if done.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        status = None
    if not isinstance(status, dict):
        return Reach("stopped", None, ngrok)
    url = funnel_url_for_port(status, port)
    return Reach("funnel-on" if url else "no-funnel", url, ngrok)


def probe(base_url: str, *, fetch=None, timeout: float = 3.0) -> bool:
    """Is Cicada really answering at ``base_url``? A GET of the public
    protected-resource metadata: no token, no redirects, no proxy env, 3 s.

    A 200 whose body is JSON but not an object (``[]``, ``null``, ``"x"``) is
    "not Cicada", not an AttributeError: this probe is RemoteAccessView's first
    load, and a 500 there left `status` nil — the switch disabled and the
    connectors card hidden, so the person could not turn remote access off
    while the listener stayed up (G135 final review)."""
    base = base_url.rstrip("/")
    url = f"{base}{catalog.PRM_PATH}/mcp"
    try:
        if fetch is None:
            import httpx

            with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client:
                resp = client.get(url)
            status, body = resp.status_code, resp.text[:4096]
        else:
            status, body = fetch(url, timeout)
        data = json.loads(body)
    except Exception:  # noqa: BLE001 — unreachable is an answer, not an error
        return False
    return (status == 200 and isinstance(data, dict) and data.get("resource_name") == "Cicada"
            and data.get("resource") == f"{base}/mcp")
