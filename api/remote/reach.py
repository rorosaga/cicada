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


@dataclass(frozen=True)
class TailnetBackend:
    """Where a device on the person's tailnet reaches the BACKEND (G212, owner 2026-10-22) — read from the same one
    ServeConfig read as :func:`detect`, never by starting or changing anything."""
    tailscale: str            # "missing" | "stopped" | "running"
    url: str | None           # an https serve of the backend port, tailnet-only (never a funnelled one)
    public: bool = False      # the backend port is FUNNELLED: a public door the headless rail forbids; never used
    #: The funnelled address's https port (2026-10-29), so the guide can name the command that closes it.
    public_port: int | None = None


#: The https port Cicada suggests for serving the backend to the tailnet: 443 is where the G135 listener's funnel goes
#: (a port is either served or funnelled, never both), and 8443 is free for a tailnet-only serve.
BACKEND_SERVE_HTTPS_PORT = 8443


def serve_command(port: int) -> str:
    """The command the PERSON runs to give their tailnet the backend (Cicada never runs it, G132 (c))."""
    return f"tailscale serve --bg --https={BACKEND_SERVE_HTTPS_PORT} {port}"


def serve_url_for_port(status: dict, port: int) -> tuple[str | None, bool]:
    """``(url, funnelled)``: an https serve whose ``/`` proxies to ``port`` on loopback. A tailnet-only serve is the
    url; one the ServeConfig also funnels is reported as ``funnelled`` with no url — the backend never has a public
    port (G181), so a QR never carries one."""
    configs = [status] + [v for v in _dict(status.get("Foreground")).values() if isinstance(v, dict)]
    funnelled = False
    for config in configs:
        allowed = _dict(config.get("AllowFunnel"))
        for hostport, web in _dict(config.get("Web")).items():
            root = _dict(_dict(_dict(web).get("Handlers")).get("/"))
            if not _proxies_to(str(root.get("Proxy") or ""), port):
                continue
            if allowed.get(hostport):
                funnelled = True
                continue
            host, _, https_port = hostport.rpartition(":")
            if host:
                return (f"https://{host}" if https_port in ("443", "") else f"https://{host}:{https_port}"), False
    return None, funnelled


def tailnet_backend(port: int, *, which=shutil.which, run=subprocess.run, exists=_is_executable) -> TailnetBackend:
    """One bounded, read-only ``tailscale funnel status --json`` (2 s) — the local daemon's own ServeConfig, the read
    :func:`detect` already makes for `GET /remote/status`. No second command and no LocalAPI socket: the ServeConfig is
    the only answer that proves a URL actually reaches the backend, and the self DNS name alone would put an address
    in a QR that leads nowhere until the person serves the port."""
    tailscale = find_tool("tailscale", which=which, exists=exists) or (
        TAILSCALE_APP_CLI if exists(TAILSCALE_APP_CLI) else None)
    if not tailscale:
        return TailnetBackend("missing", None)
    try:
        done = run([tailscale, "funnel", "status", "--json"], capture_output=True, text=True, timeout=2.0,
                   check=False)
        status = json.loads(done.stdout or "{}") if done.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        status = None
    if not isinstance(status, dict):
        return TailnetBackend("stopped", None)
    url, funnelled = serve_url_for_port(status, port)
    public_port = None
    if funnelled:
        public = funnel_url_for_port(status, port)
        public_port = (urlparse(public).port or 443) if public else None
    return TailnetBackend("running", url, funnelled, public_port)


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


# ── G212 (owner 2026-10-29): the guided reach setup and its live check ───────────────────────────────────────────────
# Settings → Devices walks the person through making this machine reachable on their own overlay. The backend only
# LOOKS (two bounded, read-only CLI reads) and, on the person's ask, fetches its own served `/healthz` through that
# overlay; it never runs `tailscale up`, `serve` or `funnel` (G132 (c), network.md). The app turns each state into the
# one next step in words, and the command to copy where a command is the step.

#: The guided steps, in the order a person meets them. Hyrum mode A: the words are stable, the app maps each to text.
GUIDE_STEPS = ("install", "open", "sign-in", "turn-on", "serve", "unfunnel", "ready")


@dataclass(frozen=True)
class TailnetState:
    """``tailscale status --json``'s two facts the guide needs: is the daemon up and signed in, and this node's name."""
    tailscale: str            # "missing" | "not-running" | "logged-out" | "stopped" | "running"
    dns_name: str | None = None


def tailnet_state(*, which=shutil.which, run=subprocess.run, exists=_is_executable) -> TailnetState:
    """One bounded (2 s), read-only ``tailscale status --json``: ``BackendState`` (``Running``, ``Stopped``,
    ``NeedsLogin``, ``NeedsMachineAuth``) and ``Self.DNSName``. A daemon that does not answer (the app not open, the
    service not started) is ``not-running``. Peers, keys and every other field are read past and never kept."""
    tailscale = find_tool("tailscale", which=which, exists=exists) or (
        TAILSCALE_APP_CLI if exists(TAILSCALE_APP_CLI) else None)
    if not tailscale:
        return TailnetState("missing")
    try:
        done = run([tailscale, "status", "--json"], capture_output=True, text=True, timeout=2.0, check=False)
        status = json.loads(done.stdout or "{}")
    except (OSError, subprocess.TimeoutExpired, ValueError):
        status = None
    # `tailscale status` exits non-zero when stopped or logged out, yet still prints the JSON; the state is in it.
    backend = str(_dict(status).get("BackendState") or "")
    if backend in ("NeedsLogin", "NeedsMachineAuth"):
        return TailnetState("logged-out")
    if backend == "Stopped":
        return TailnetState("stopped")
    if backend != "Running":
        return TailnetState("not-running")
    name = str(_dict(_dict(status).get("Self")).get("DNSName") or "").rstrip(".")
    return TailnetState("running", name or None)


def guide(port: int, *, state: TailnetState | None = None, backend: TailnetBackend | None = None,
          which=shutil.which, run=subprocess.run, exists=_is_executable) -> dict:
    """Where this machine stands on the person's overlay, and the one next step. ``step`` is one of
    :data:`GUIDE_STEPS`; ``command`` is the exact command to copy when a command is the step (a serve, or closing a
    funnel), else None; ``url`` is the address a QR may carry (``ready`` only)."""
    state = state or tailnet_state(which=which, run=run, exists=exists)
    out = {"tailscale": state.tailscale, "dnsName": state.dns_name, "url": None, "command": None}
    steps = {"missing": "install", "not-running": "open", "logged-out": "sign-in", "stopped": "turn-on"}
    if state.tailscale in steps:
        return {**out, "step": steps[state.tailscale]}
    backend = backend or tailnet_backend(port, which=which, run=run, exists=exists)
    if backend.url:
        return {**out, "step": "ready", "url": backend.url}
    if backend.public:
        # The funnelled address is never offered (G181: the backend has no public port); the step closes it.
        return {**out, "step": "unfunnel", "command": f"tailscale funnel --https={backend.public_port or 443} off"}
    return {**out, "step": "serve", "command": serve_command(port)}


#: Where a live check of the served address stopped. ``dns``: the name does not resolve (MagicDNS off, or Tailscale
#: down on this end); ``overlay``: it resolves but nothing answers (the overlay is down, or its HTTPS certificate is
#: not there yet); ``backend``: the overlay answers but the backend behind it does not (the serve proxy's 502);
#: ``not-cicada``: something else answers there; ``other-cicada``: a Cicada, but not this one.
CHECK_FAILURES = ("dns", "overlay", "backend", "not-cicada", "other-cicada")


def self_check(url: str, *, version: str, bank_id: str | None, resolve=None, fetch=None,
               timeout: float = 3.0) -> dict:
    """Fetch this machine's own served ``/healthz`` through the person's overlay, the way a phone would, and name the
    first step that fails. No token is sent (the open answer is enough to know it is this Cicada: its version and
    memory id); no redirect is followed; no proxy from the environment. ``{ok, failed, ms}``, ``failed`` one of
    :data:`CHECK_FAILURES` or None. The URL comes from the person's own ServeConfig, never from a request."""
    import socket
    import time
    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as FutureTimeout

    started = time.perf_counter()

    def done(failed: str | None) -> dict:
        return {"ok": failed is None, "failed": failed, "ms": int((time.perf_counter() - started) * 1000)}

    parts = urlparse(url)
    host = parts.hostname
    if not host:
        return done("dns")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    resolver = resolve or socket.getaddrinfo
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        pool.submit(resolver, host, port).result(timeout=timeout)
    except (OSError, FutureTimeout):
        return done("dns")
    finally:
        pool.shutdown(wait=False)
    target = f"{url.rstrip('/')}/healthz"
    try:
        if fetch is None:
            import httpx

            with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client:
                resp = client.get(target)
            status, body = resp.status_code, resp.text[:4096]
        else:
            status, body = fetch(target, timeout)
    except Exception:  # noqa: BLE001 — refused, timed out, a TLS failure: the overlay did not carry it
        return done("overlay")
    if status in (502, 503, 504):
        return done("backend")
    try:
        data = json.loads(body)
    except ValueError:
        return done("not-cicada")
    if status != 200 or not isinstance(data, dict) or data.get("status") != "ok" or not data.get("version"):
        return done("not-cicada")
    if data.get("version") != version or (bank_id and data.get("bankId") != bank_id):
        return done("other-cicada")
    return done(None)
