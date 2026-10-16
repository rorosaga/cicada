"""G181 phase 2 — what the `cicada` command says on a client when the setup is wrong (QA 2026-10-16).

A first-time client gets three things wrong most often: the address (plain http to a tailnet IP, no scheme), the token
(not copied yet) and where a device command runs (`cicada device add` on the laptop). Each answer names the fix; none
blames a revocation that never happened or prints an exception's class name. Synthetic values only.
"""
from __future__ import annotations

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
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

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
