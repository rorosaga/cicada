"""How AI apps reach this Mac (G135 R-R32) — detection only; Cicada never starts,
stops or reconfigures a tunnel (G132 (c): the overlay is the person's).

Tailscale: `shutil.which` (the launchd plist's PATH has /opt/homebrew/bin and
/usr/local/bin) or the app bundle's own CLI. `tailscale funnel status --json`
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


def funnel_url_for_port(status: dict, port: int) -> str | None:
    configs = [status] + [v for v in (status.get("Foreground") or {}).values() if isinstance(v, dict)]
    for config in configs:
        allowed = config.get("AllowFunnel") or {}
        for hostport, web in (config.get("Web") or {}).items():
            if not allowed.get(hostport):
                continue
            root = ((web or {}).get("Handlers") or {}).get("/") or {}
            if _proxies_to(str(root.get("Proxy") or ""), port):
                host, _, public_port = hostport.rpartition(":")
                return f"https://{host}" if public_port in ("443", "") else f"https://{host}:{public_port}"
    return None


def detect(port: int, *, which=shutil.which, run=subprocess.run, exists=os.path.exists) -> Reach:
    ngrok = bool(which("ngrok"))
    tailscale = which("tailscale") or (TAILSCALE_APP_CLI if exists(TAILSCALE_APP_CLI) else None)
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
    protected-resource metadata: no token, no redirects, no proxy env, 3 s."""
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
    return status == 200 and data.get("resource_name") == "Cicada" and data.get("resource") == f"{base}/mcp"
