"""G181 phase 2 — what the `cicada` command says on a client when the setup is wrong (QA 2026-10-16).

A first-time client gets three things wrong most often: the address (plain http to a tailnet IP, no scheme), the token
(not copied yet) and where a device command runs (`cicada device add` on the laptop). Each answer names the fix; none
blames a revocation that never happened or prints an exception's class name. Synthetic values only.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _cli(tmp_path: Path, *argv: str, **env_extra) -> subprocess.CompletedProcess:
    home = tmp_path / "home"
    (home / ".cicada").mkdir(parents=True, exist_ok=True)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home), "CICADA_HOME": str(home / ".cicada"),
           "CICADA_MEMORY_PATH": str(tmp_path / "memory"), "PYTHONPATH": str(REPO), "LANG": "C.UTF-8", **env_extra}
    return subprocess.run([sys.executable, "-m", "api.cli", *argv], cwd=REPO, env=env, capture_output=True, text=True,
                          timeout=60)


@pytest.mark.parametrize("base, rule", [
    ("http://192.0.2.10:8000", "must use https unless it is a loopback address"),
    ("192.0.2.10:8000", "must be an http(s) address"),
])
def test_a_bad_server_address_names_the_rule_it_broke(tmp_path, base, rule):
    done = _cli(tmp_path, "status", CICADA_API_BASE=base)
    assert done.returncode != 0
    assert rule in done.stderr, done.stderr
    assert "(BootstrapError)" not in done.stderr
    assert "192.0.2.10" not in done.stderr          # the rule, never the value


class _Server:
    """A stand-in Cicada server: `/healthz` open, everything else refused like a real one without a valid token."""

    def __init__(self):
        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if self.path == "/healthz":
                    body, code = {"status": "ok", "version": "0.0.0", "bankId": "b1", "bankIds": ["b1"]}, 200
                else:
                    body, code = {"detail": "missing or invalid bearer token"}, 401
                raw = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server():
    s = _Server()
    try:
        yield s
    finally:
        s.close()


def test_no_token_says_so_and_never_blames_a_revocation(tmp_path, server):
    status = _cli(tmp_path, "status", CICADA_API_BASE=server.url)
    assert "this device has no token" in status.stdout, status.stdout + status.stderr
    assert "server_no_token" in status.stderr
    done = _cli(tmp_path, "recall", "alpha-project", CICADA_API_BASE=server.url)
    assert done.returncode == 1
    assert "This device has no Cicada token" in done.stderr, done.stderr
    assert "revoked" not in done.stderr


def test_a_device_command_only_the_server_may_run_says_where_to_run_it(monkeypatch):
    """A 403 is the server saying "a device's token never may" (master-only paths, e.g. `cicada device add`), not
    "your token was refused": the token works, and the fix is to run the command on the server."""
    import urllib.error

    from api import cli_app
    from api.cli_types import Refusal

    monkeypatch.setenv("CICADA_API_BASE", "https://cicada.example.invalid")
    body = io.BytesIO(json.dumps({"detail": "only the server's own token may do this"}).encode())
    err = urllib.error.HTTPError("https://cicada.example.invalid/devices", 403, "Forbidden", {}, body)
    with pytest.raises(Refusal) as refused:
        cli_app._raise_for(err)
    assert refused.value.code == "unauthorized"
    assert "Run it in a terminal on the server" in str(refused.value)
    assert "revoked" not in str(refused.value)


def test_a_server_whose_backend_stopped_is_told_how_to_start_it_not_to_open_an_app(monkeypatch):
    """On Linux there is no app to open: the fix is the systemd user unit install.sh installed."""
    from api import cli_app
    from api.cli_types import Refusal

    assert "systemctl --user start cicada-backend.service" in cli_app.down_text("linux")
    assert "Open Cicada" not in cli_app.down_text("linux")
    assert "Open Cicada" in cli_app.down_text("darwin")                  # a Mac keeps its words
    monkeypatch.setattr(sys, "platform", "linux")
    boot = type("B", (), {"probe": {"state": "backend_down"}})()
    with pytest.raises(Refusal) as refused:
        cli_app.call(boot, "POST", "/sleep/trigger")
    assert refused.value.code == "backend_down"
    assert "systemctl --user start" in str(refused.value)
