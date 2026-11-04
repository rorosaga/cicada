"""How AI apps reach this Mac (G135 R-R32) — detection only; Cicada never starts,
stops or reconfigures a tunnel (G132 (c): the overlay is the person's) — with two
dated exceptions, each the person's click and each exactly the command shown:
``tailscale serve --bg --https=8443 <port>`` (tailnet only; owner 2026-10-29,
"Yes, one click"; :func:`run_serve`) and, for the connector's own port and no other,
``tailscale funnel --bg --https=<443|10000> <port>`` (ruling 59, owner 2026-11-04;
:func:`run_funnel`), each with the matching off for that one mapping. Never ``up``.

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
import shlex
import shutil
import socket
import subprocess
from dataclasses import dataclass, field, replace
from urllib.parse import urlparse

from api.remote import catalog

TAILSCALE_APP_CLI = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}


#: `GET /remote/status`'s `funnelCommand` when no command is safe to offer. An older app shows this field in a box to
#: copy and an older `cicada setup` prints it, so it stays a non-empty string, and one harmless if pasted: a shell comment
#: (or, in an interactive zsh, "command not found") with no quote, `$`, `;`, `&` or bracket in it.
FUNNEL_COPY_UNKNOWN = "# Tailscale is not answering. Open it, then check again."
FUNNEL_COPY_TAKEN = "# Ports 443 and 10000 are in use. Free one, then check again."
FUNNEL_COPY_PORT = "# The connector shares a port with another part of Cicada. Change CICADA_REMOTE_PORT."


@dataclass(frozen=True)
class Reach:
    tailscale: str  # "missing" | "stopped" | "no-funnel" | "funnel-on"
    funnel_url: str | None
    ngrok: bool
    #: What `funnelCommand` says (ruling 59): never a bare `tailscale funnel --bg <port>`, which means 443 and replaces
    #: whatever holds it. Derived from the same read as the two fields above, so not part of what makes two answers equal.
    funnel_copy: str = field(default=FUNNEL_COPY_UNKNOWN, compare=False)


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
    return Reach("funnel-on" if url else "no-funnel", url, ngrok, funnel_copy_command(status, port))


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
    url; one the ServeConfig also funnels is reported as ``funnelled`` and is never the url — the backend never has a
    public port (G181), so a QR never carries one. Every entry is read (review, 2026-10-29): a tailnet-only serve of
    the port does not hide a funnel of the same port on another https port — both come back, and the caller treats
    ``funnelled`` as the thing to fix first."""
    configs = [status] + [v for v in _dict(status.get("Foreground")).values() if isinstance(v, dict)]
    funnelled = False
    url = None
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
            if host and url is None:
                url = f"https://{host}" if https_port in ("443", "") else f"https://{host}:{https_port}"
    return url, funnelled


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
# overlay; this guide never runs `tailscale up`, `serve` or `funnel` (G132 (c), network.md). The app turns each state into the
# one next step in words, and the command to copy where a command is the step.

#: The guided steps, in the order a person meets them. Hyrum mode A: the words are stable, the app maps each to text.
GUIDE_STEPS = ("install", "open", "sign-in", "turn-on", "serve", "unfunnel", "ready")


@dataclass(frozen=True)
class TailnetState:
    """``tailscale status --json``'s facts the guide needs: is the daemon up and signed in, this node's name, and the
    client's version (ruling 59: an older CLI spells Funnel differently)."""
    tailscale: str            # "missing" | "not-running" | "logged-out" | "stopped" | "running"
    dns_name: str | None = None
    version: str | None = None


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
    return TailnetState("running", name or None, str(_dict(status).get("Version") or "") or None)


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
    if backend.public:
        # First, even beside a tailnet-only serve: the backend is open to the internet (G181: it never has a public
        # port). Nothing is offered for a QR until the funnel is closed.
        return {**out, "step": "unfunnel", "command": funnel_stop_command(backend.public_port or 443)}
    if backend.url:
        # The matching off for that one mapping (owner 2026-10-29): shown before a click may run it.
        return {**out, "step": "ready", "url": backend.url, "stopCommand": stop_command(backend.url)}
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


# ── G212 amendment (owner 2026-10-29, "Yes, one click"): serve the backend to the tailnet from a click ─────────────
# The one exception to "Cicada never starts, stops or reconfigures a tunnel" (G132 (c), network.md): a click in
# Settings → Devices may run EXACTLY ``tailscale serve --bg --https=8443 <port>`` (tailnet only) — the argv shown before
# the click — and the matching off for that one mapping, then re-read the state. Never ``funnel``, never ``up``, never
# a shell, never a command a request names (the argv is built here, from the backend's own port and the person's own
# ServeConfig); 10 s cap; stdin closed, so nothing can wait on a prompt; every failure is a sentence.

SERVE_TIMEOUT = 10.0
SERVE_ACTIONS = ("serve", "stop")


def serve_argv(tailscale: str, port: int) -> list[str]:
    """The serve the click runs — :func:`serve_command`'s words, with the resolved binary."""
    return [tailscale, "serve", "--bg", f"--https={BACKEND_SERVE_HTTPS_PORT}", str(int(port))]


def _https_port(url: str | None) -> int | None:
    if not url:
        return None
    try:
        return urlparse(url).port or 443
    except ValueError:
        return None


def stop_command(url: str | None) -> str | None:
    """The off for the one tailnet-only mapping that serves the backend (``ready``): its https port and its ``/``, nothing
    else. With no ``--set-path`` the CLI deletes every handler on the port (`serve_v2.go`, ``removeWebServe``)."""
    port = _https_port(url)
    return f"tailscale serve --https={port} --set-path=/ off" if port else None


def stop_argv(tailscale: str, url: str | None) -> list[str] | None:
    port = _https_port(url)
    return [tailscale, "serve", f"--https={port}", "--set-path=/", "off"] if port else None


#: Tailscale prints a URL to visit when Serve or HTTPS certificates are not enabled for the tailnet yet, and waits.
_ENABLE_HINTS = ("login.tailscale.com", "/admin/", "not enabled", "enable https", "enable serve")


def _failure(stdout: str, stderr: str) -> str:
    text = " ".join(f"{stderr or ''} {stdout or ''}".split())
    lower = text.lower()
    if "access denied" in lower or "permission denied" in lower or "--operator" in lower:
        return ("Tailscale refused: this user may not change Tailscale's settings. Run the command yourself in a "
                "terminal.")
    if any(h in lower for h in _ENABLE_HINTS):
        url = next((w.rstrip(".,)") for w in text.split() if w.startswith("https://")), None)
        where = f" at {url}" if url else " in the Tailscale admin console"
        return f"Serve isn't on for your tailnet yet: turn it on{where}, then try again."
    return "Tailscale did not do it. Run the command yourself in a terminal to see why."


def _text(value) -> str:
    return value.decode(errors="replace") if isinstance(value, bytes) else (value or "")


def run_serve(action: str, port: int, *, which=shutil.which, run=subprocess.run, exists=_is_executable) -> dict:
    """Run the click's one command — ``serve`` (only on the ``serve`` step) or ``stop`` (only on ``ready``) — and
    re-read where the machine stands. ``{ok, message, ran, guide}``: ``ran`` the command as words (the binary shown as
    ``tailscale``), ``guide`` :func:`guide`'s fresh answer. On any other step it runs nothing and says why."""
    if action not in SERVE_ACTIONS:
        raise ValueError(f"action must be one of {', '.join(SERVE_ACTIONS)}")
    before = guide(port, which=which, run=run, exists=exists)
    tailscale = find_tool("tailscale", which=which, exists=exists) or (
        TAILSCALE_APP_CLI if exists(TAILSCALE_APP_CLI) else None)
    if action == "serve":
        argv = serve_argv(tailscale, port) if tailscale and before["step"] == "serve" else None
        refusal = "Nothing to serve right now: " + {
            "ready": "this Mac is already reachable on your tailnet.",
            "unfunnel": "close the public funnel first, with the command shown.",
        }.get(before["step"], "finish the step shown first.")
    else:
        argv = stop_argv(tailscale, before.get("url")) if tailscale and before["step"] == "ready" else None
        refusal = "This Mac is not being served to your tailnet, so there is nothing to stop."
    if argv is None:
        return {"ok": False, "message": refusal, "ran": None, "guide": before}
    ran = " ".join(["tailscale", *argv[1:]])
    try:
        done = run(argv, capture_output=True, text=True, timeout=SERVE_TIMEOUT, check=False,
                   stdin=subprocess.DEVNULL)
        ok = done.returncode == 0
        message = None if ok else _failure(done.stdout, done.stderr)
    except subprocess.TimeoutExpired as exc:
        out, err = _text(exc.stdout), _text(exc.stderr)
        ok = False
        message = (_failure(out, err) if any(h in f"{out} {err}".lower() for h in _ENABLE_HINTS)
                   else "Tailscale did not answer within 10 seconds. Run the command yourself in a terminal.")
    except OSError:
        ok, message = False, "Tailscale could not be started. Run the command yourself in a terminal."
    return {"ok": ok, "message": message, "ran": ran, "guide": guide(port, which=which, run=run, exists=exists)}


# ── Ruling 59 (owner 2026-11-04): one click opens the connector's own port to the internet ──────────────────────────
# claude.ai and the phone apps relay through the G135 listener (ruling 32, 57) and can only reach a public address. The
# person's click may run EXACTLY ``tailscale funnel --bg --https=<443|10000> <the connector's port>`` — the command shown
# before the click — and that one mapping's off. Same seam as the serve above: the argv is built here from the
# connector's own port and the person's own ServeConfig, never from a request; argv only, 10 s cap, stdin closed; never
# ``up``, never a login. Nothing about it is stored: every answer is read back from Tailscale.
#
# Three things the CLI does that this code exists to prevent (read from cmd/tailscale/cli/serve_v2.go, v1.104):
# - a funnel on a port that already serves something REPLACES its ``/`` handler without asking, and opens every other
#   path on that port to the internet — so a port holding anything is never used, and 8443 (the tailnet-only mapping of
#   the backend) is not even a candidate;
# - ``funnel --https=<p> off`` with no ``--set-path`` deletes EVERY handler on the port — so the off names ``/``;
# - with Funnel not yet allowed it prints a URL and either waits or EXITS 0 having changed nothing — so a return code
#   never decides success: only the ServeConfig read back does.
#
# A `--bg` mapping outlives the listener: it names a port, and when the connector is down anyone local may hold that port,
# with no auth. So a mapping with no listener behind it is asked about, never assumed dead (`port_accepts`); the switch
# closes the mapping as it stops the listener (`routers/remote.py`); and any other public mapping on this machine is
# reported with its own off to copy, since Cicada cannot prove it made one and never removes the person's own.

#: The public ports the click may use, in order. Funnel allows 443, 8443 and 10000; 443 is the clean address and where
#: the docs have always put it, 10000 only when the person's own mapping holds 443 (`headless.md` suggests one).
FUNNEL_HTTPS_PORTS = (443, 10000)
FUNNEL_TIMEOUT = 10.0
FUNNEL_ACTIONS = ("on", "off")
#: `--bg`, `--https` and `--set-path` on `tailscale funnel` arrived in 1.52; older spellings differ and are not guessed.
FUNNEL_MIN_VERSION = (1, 52)
#: Hyrum mode A: the words are stable. ``off`` is the one step a click may turn on; ``on`` the one it may turn off.
FUNNEL_STEPS = ("install", "open", "sign-in", "turn-on", "update", "port", "unknown", "address", "taken", "terminal",
                "off", "on")

#: Tailscale's docs name `console.tailscale.com` as the admin console; a CLI may still print `login.tailscale.com`.
_ENABLE_HOSTS = ("console.tailscale.com", "login.tailscale.com")
_FIX_HOSTS = (*_ENABLE_HOSTS, "tailscale.com")
_HTTPS_FIX = "https://console.tailscale.com/admin/dns"
_POLICY_FIX = "https://console.tailscale.com/admin/acls"
#: Said before the click that can publish it, and it cannot be taken back: a certificate log is public and append-only.
CERT_LOG_WORDS = ("Turning on HTTPS publishes this machine's name and your tailnet's name on a public certificate log, "
                  "and that can't be undone.")
_FUNNEL_WORDS = {
    "install": "Install Tailscale on this machine.",
    "open": "Open Tailscale on this machine.",
    "sign-in": "Sign in to Tailscale on this machine.",
    "turn-on": "Tailscale is off on this machine. Turn it on.",
    "update": "This Tailscale is too old for this. Update it, then try again.",
    "port": "The connector's port is also used by another part of Cicada, so it can't be opened. Change "
            "CICADA_REMOTE_PORT.",
    "unknown": "Tailscale did not answer. Try again.",
    "address": "You saved your own address for this machine. Clear it first.",
    "taken": "Ports 443 and 10000 already carry your other Tailscale mappings, and Cicada won't replace them. Free one "
             "(tailscale funnel status lists them), then try again.",
    "terminal": "This was opened from a terminal. Close it there with Ctrl+C.",
}


@dataclass(frozen=True)
class FunnelOther:
    """A public handler on this machine that is not the connector's own door: left on an old port, the person's own, or
    the API's. Shown with the command that closes that one mapping, to copy: Cicada never runs it."""
    url: str
    local_port: int
    message: str
    command: str | None
    kind: str  # "api" | "other"


@dataclass(frozen=True)
class FunnelState:
    """Where the connector's public door stands, read from Tailscale. ``mapped_url`` is what the ServeConfig says, which
    is not yet a claim that it answers: only :func:`funnel_wire` with a passed probe puts an address on the wire."""
    step: str
    message: str | None = None
    command: str | None = None
    stop_command: str | None = None
    mapped_url: str | None = None
    others: tuple[FunnelOther, ...] = ()


def _configs(status: dict) -> list[dict]:
    return [status] + [v for v in _dict(status.get("Foreground")).values() if isinstance(v, dict)]


def _hostport_port(hostport: str) -> str:
    return str(hostport).rpartition(":")[2]


def funnel_port_taken(status: dict, https_port: int) -> bool:
    """Does anything at all hold this port, in any config, foreground ones included? ``TCP`` carries every listener, a
    web one too; ``Web`` and ``AllowFunnel`` are read as well, in case another writer left only those."""
    wanted = str(https_port)
    for config in _configs(status):
        if wanted in _dict(config.get("TCP")):
            return True
        if any(_hostport_port(h) == wanted for h in (*_dict(config.get("Web")), *_dict(config.get("AllowFunnel")))):
            return True
    return False


def port_accepts(port: int, *, timeout: float = 0.3) -> bool:
    """Does anything accept on this loopback port? Connect and close, nothing sent: with the listener down, whatever is
    here is what a public mapping of this port serves to the internet."""
    for host in ("127.0.0.1", "::1"):
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            continue
    return False


def _loopback_port(proxy: str) -> int | None:
    target = proxy if "://" in proxy else f"http://{proxy}"
    try:
        parsed = urlparse(target)
        return parsed.port if parsed.hostname in _LOOPBACK else None
    except ValueError:
        return None


def funnel_others(status: dict, port: int, *, closed_ports: tuple[int, ...] = ()) -> tuple[FunnelOther, ...]:
    """Every funnelled handler proxying to a loopback port, but for the connector's own ``/``. Reported, never removed: a
    mapping on the connector's old port and the person's own site look exactly alike from here."""
    found = []
    for config in _configs(status):
        foreground = config is not status
        allowed = _dict(config.get("AllowFunnel"))
        for hostport, web in _dict(config.get("Web")).items():
            if not allowed.get(hostport):
                continue
            host, _, https = str(hostport).rpartition(":")
            if not https.isdigit():
                continue
            for mount, handler in _dict(_dict(web).get("Handlers")).items():
                local = _loopback_port(str(_dict(handler).get("Proxy") or ""))
                if local is None or (local == port and mount == "/"):
                    continue
                url = (f"https://{host}" if https == "443" else f"https://{host}:{https}") + (
                    "" if mount == "/" else str(mount))
                api = local in closed_ports
                words = (f"Cicada's own API is reachable from the internet at {url}. Close it now." if api else
                         f"Also public from this machine: {url}, which reaches local port {local}, not the connector.")
                command = None if foreground else (
                    f"tailscale funnel --https={https} --set-path={shlex.quote(str(mount))} off")
                if foreground:
                    words += " It was opened from a terminal: close it there with Ctrl+C."
                found.append(FunnelOther(url, local, words, command, "api" if api else "other"))
    return tuple(found)


def _foreground_funnel(status: dict, port: int) -> bool:
    return any(funnel_url_for_port(c, port) for c in _dict(status.get("Foreground")).values() if isinstance(c, dict))


def funnel_command(https_port: int, port: int) -> str:
    return f"tailscale funnel --bg --https={https_port} {port}"


def funnel_stop_command(https_port: int) -> str:
    return f"tailscale funnel --https={https_port} --set-path=/ off"


def funnel_copy_command(status: dict | None, port: int) -> str:
    """`GET /remote/status`'s `funnelCommand`: a command safe to paste on this machine as it stands, or words. The same
    rule as the click: the port it already holds, else the first free one, never one holding something else."""
    if not isinstance(status, dict):
        return FUNNEL_COPY_UNKNOWN
    url = funnel_url_for_port(status, port)
    if url:
        return funnel_command(_https_port(url) or 443, port)
    free = next((p for p in FUNNEL_HTTPS_PORTS if not funnel_port_taken(status, p)), None)
    return funnel_command(free, port) if free is not None else FUNNEL_COPY_TAKEN


def funnel_argv(tailscale: str, https_port: int, port: int) -> list[str]:
    """The one place an argv that opens anything to the internet is built."""
    if https_port not in FUNNEL_HTTPS_PORTS:
        raise ValueError("not a port the click may use")
    return [tailscale, "funnel", "--bg", f"--https={https_port}", str(int(port))]


def funnel_stop_argv(tailscale: str, https_port: int) -> list[str]:
    return [tailscale, "funnel", f"--https={https_port}", "--set-path=/", "off"]


def _version_ok(version: str | None) -> bool:
    """Too old only when the version parses and says so: an unknown one is left to the command's own answer."""
    parts = str(version or "").split("-", 1)[0].split(".")
    try:
        return (int(parts[0]), int(parts[1])) >= FUNNEL_MIN_VERSION
    except (IndexError, ValueError):
        return True


def _read_serve_config(tailscale: str, run) -> dict | None:
    try:
        done = run([tailscale, "funnel", "status", "--json"], capture_output=True, text=True, timeout=2.0, check=False)
        status = json.loads(done.stdout or "{}") if done.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        status = None
    return status if isinstance(status, dict) else None


def _stopped_at(step: str) -> FunnelState:
    return FunnelState(step, _FUNNEL_WORDS[step])


def funnel_state(port: int, *, closed_ports: tuple[int, ...] = (), saved_url: str | None = None, which=shutil.which,
                 run=subprocess.run, exists=_is_executable) -> FunnelState:
    """Two bounded read-only answers, nothing changed. ``closed_ports`` are the ports that are never public, however the
    connector's port was configured: the backend's API and the door (ruling 51f)."""
    if port <= 0 or port in closed_ports:
        return _stopped_at("port")
    state = tailnet_state(which=which, run=run, exists=exists)
    steps = {"missing": "install", "not-running": "open", "logged-out": "sign-in", "stopped": "turn-on"}
    if state.tailscale in steps:
        return _stopped_at(steps[state.tailscale])
    if not _version_ok(state.version):
        return _stopped_at("update")
    tailscale = find_tool("tailscale", which=which, exists=exists) or TAILSCALE_APP_CLI
    status = _read_serve_config(tailscale, run)
    if status is None:
        return _stopped_at("unknown")
    others = funnel_others(status, port, closed_ports=closed_ports)
    url = funnel_url_for_port(status, port)
    if url:
        if _foreground_funnel(status, port):
            return FunnelState("terminal", _FUNNEL_WORDS["terminal"], mapped_url=url, others=others)
        return FunnelState("on", stop_command=funnel_stop_command(_https_port(url) or 443), mapped_url=url,
                           others=others)
    free = next((p for p in FUNNEL_HTTPS_PORTS if not funnel_port_taken(status, p)), None)
    if free is None:
        return replace(_stopped_at("taken"), others=others)
    if saved_url and state.dns_name:
        would_be = f"https://{state.dns_name}" + ("" if free == 443 else f":{free}")
        if saved_url.rstrip("/") != would_be:
            return replace(_stopped_at("address"), others=others)
    return FunnelState("off", CERT_LOG_WORDS, command=funnel_command(free, port), others=others)


#: What the public address reaches when the listener is down, asked of the port (`port_accepts`), never assumed.
FUNNEL_OTHER_PROGRAM = ("Another program on this machine is on the connector's port, and this address makes it reachable "
                        "from the internet.")
FUNNEL_OPEN_NOTHING_BEHIND = ("This address is still open and nothing answers it now, but any program that takes the "
                              "connector's port will be public. Turn it off.")


def funnel_wire(state: FunnelState, *, answers: bool | None = None, listener_up: bool = True,
                other_program: bool = False, fix_url: str | None = None) -> dict:
    """The answer both clients read. ``url`` only when a probe through that address just passed (never the ServeConfig's
    say-so); a mapping that does not answer says why, in words, and says so when something else is answering."""
    message = state.message
    if state.step in ("on", "terminal") and other_program:
        message = FUNNEL_OTHER_PROGRAM + (" Turn it off." if state.step == "on" else f" {state.message}")
    elif state.step == "on" and answers is False:
        message = (FUNNEL_OPEN_NOTHING_BEHIND if not listener_up else
                   "Set, not answering yet. The first time can take up to 10 minutes.")
    return {"step": state.step, "message": message, "command": state.command, "stopCommand": state.stop_command,
            "url": state.mapped_url if state.step == "on" and answers is True else None, "answers": answers,
            "otherProgram": other_program, "fixUrl": fix_url,
            "others": [{"url": o.url, "port": o.local_port, "message": o.message, "command": o.command, "kind": o.kind}
                       for o in state.others]}


def _fix_url(text: str) -> str | None:
    """The address Tailscale printed for the person to enable it — only a Tailscale address is ever offered as a link."""
    for word in text.split():
        candidate = word.rstrip(".,)")
        if not candidate.startswith("https://"):
            continue
        try:
            host = urlparse(candidate).hostname
        except ValueError:
            continue
        if host in _FIX_HOSTS:
            return candidate
    return None


def _funnel_failure(stdout: str, stderr: str, command: str) -> tuple[str, str | None]:
    """``(sentence, link)``: what the person does next, in words, with the exact place to do it."""
    text = " ".join(f"{stderr or ''} {stdout or ''}".split())
    lower = text.lower()
    if "access denied" in lower or "permission denied" in lower or "--operator" in lower:
        return ("Tailscale refused: this user may not change its settings. Run sudo tailscale set --operator=$USER, "
                "then try again."), None
    if "https must be enabled" in lower:
        return "HTTPS certificates are off for your tailnet. Turn them on, then try again.", _HTTPS_FIX
    if "node attribute not set" in lower or "s/no-funnel" in lower:
        return "Your tailnet's policy doesn't allow Funnel. Add Funnel to your policy, then try again.", _POLICY_FIX
    if "not allowed for funnel" in lower:
        return "Your tailnet's policy doesn't allow Funnel on this port. Allow it in nodeAttrs.", _POLICY_FIX
    fix = _fix_url(text)
    if fix and urlparse(fix).hostname in _ENABLE_HOSTS:
        return "Funnel isn't on for your tailnet yet. Turn it on there, then try again.", fix
    if "changing the serve config" in lower:
        return "Something else was changing Tailscale's settings. Try again.", None
    if "flag provided but not defined" in lower:
        return _FUNNEL_WORDS["update"], None
    return f"Tailscale did not do it. Run this in a terminal to see why: {command}", None


def run_funnel(action: str, port: int, *, shown: str | None = None, listener_up: bool = False,
               closed_ports: tuple[int, ...] = (), saved_url: str | None = None, which=shutil.which,
               run=subprocess.run, exists=_is_executable) -> dict:
    """The click's one command, then the state read back: ``{ok, message, fixUrl, ran, state}``. ``ok`` is what the
    ServeConfig says afterwards, never the return code. ``shown`` is compared, never run: if the machine changed since
    the person read the command, nothing runs and they read it again. Anything but the matching step runs nothing."""
    if action not in FUNNEL_ACTIONS:
        raise ValueError(f"action must be one of {', '.join(FUNNEL_ACTIONS)}")

    def read() -> FunnelState:
        return funnel_state(port, closed_ports=closed_ports, saved_url=saved_url, which=which, run=run, exists=exists)

    def nothing(message: str | None, state: FunnelState) -> dict:
        return {"ok": False, "message": message, "fixUrl": None, "ran": None, "state": state}

    before = read()
    tailscale = find_tool("tailscale", which=which, exists=exists) or TAILSCALE_APP_CLI
    if action == "on":
        if before.step == "on":
            return nothing("The connector is already open to the internet.", before)
        if before.step != "off":
            return nothing(before.message, before)
        if shown != before.command:
            return nothing("That command is out of date. Look at the one shown now.", before)
        if not listener_up:
            return nothing("The connector isn't running, so nothing was opened.", before)
        https_port = int(before.command.split("--https=", 1)[1].split()[0])
        argv, command = funnel_argv(tailscale, https_port, port), before.command
    else:
        if before.step in ("off", "taken", "address"):
            words = "The connector isn't open to the internet, so there is nothing to close."
            if before.others:
                words += " Another public address is listed with the command that closes it."
            return nothing(words, before)
        if before.step != "on":
            return nothing(before.message, before)
        https_port = _https_port(before.mapped_url) or 443
        argv, command = funnel_stop_argv(tailscale, https_port), before.stop_command
    out, err, timed_out = "", "", False
    try:
        done = run(argv, capture_output=True, text=True, timeout=FUNNEL_TIMEOUT, check=False, stdin=subprocess.DEVNULL)
        out, err = _text(done.stdout), _text(done.stderr)
    except subprocess.TimeoutExpired as exc:
        out, err, timed_out = _text(exc.stdout), _text(exc.stderr), True
    except OSError:
        return {"ok": False, "message": f"Tailscale could not be started. Run this in a terminal: {command}",
                "fixUrl": None, "ran": command, "state": read()}
    after = read()
    if action == "on":
        ok = after.step == "on" and _https_port(after.mapped_url) == https_port
    else:
        ok = after.step in ("off", "taken", "address") or (
            after.step == "on" and _https_port(after.mapped_url) != https_port)
    if ok:
        return {"ok": True, "message": None, "fixUrl": None, "ran": command, "state": after}
    message, fix = _funnel_failure(out, err, command)
    if timed_out and fix is None and message.startswith("Tailscale did not do it"):
        message = f"Tailscale did not answer within 10 seconds. Run this in a terminal: {command}"
    return {"ok": False, "message": message, "fixUrl": fix, "ran": command, "state": after}
