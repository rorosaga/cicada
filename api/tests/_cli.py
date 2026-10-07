"""Shared helpers for the `cicada` CLI tests (G180) — never collected (underscore prefix).

`run_cli` starts the real entry point (`python -P -m api.cli`) as a subprocess with an
isolated HOME and CICADA_HOME, telemetry off and the backend port pointed at a port
nothing listens on, so no test can reach a running backend or a real bank.
`health_server` serves a synthetic `/healthz` (and `/sleep/status`) on an ephemeral
loopback port — never 8000.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PYTHON = sys.executable


def free_port() -> int:
    """A loopback port nothing listens on (bound, then released)."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def cli_env(tmp_path: Path, memory: Path | None, **extra: str) -> dict[str, str]:
    home = tmp_path / "home"
    (home / ".cicada").mkdir(parents=True, exist_ok=True)
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "CICADA_HOME": str(home / ".cicada"),
        "CICADA_TELEMETRY": "off",
        "CICADA_PORT": str(free_port()),
        "PYTHONPATH": str(REPO),
    }
    if memory is not None:
        env["CICADA_MEMORY_PATH"] = str(memory)
    env.update(extra)
    return env


def run_cli(args: list[str], env: dict[str, str], *, cwd: Path, stdin: str | None = None,
            command: list[str] | None = None, timeout: float = 120) -> subprocess.CompletedProcess:
    argv = (command or [PYTHON, "-P", "-m", "api.cli"]) + list(args)
    return subprocess.run(argv, env=env, cwd=str(cwd), input=stdin, capture_output=True, text=True,
                          timeout=timeout)


def envelope(proc: subprocess.CompletedProcess) -> dict:
    """The one JSON object a `--json` run prints, and nothing else on either stream."""
    assert proc.stderr == "", proc.stderr
    lines = proc.stdout.splitlines()
    assert len(lines) == 1, proc.stdout
    return json.loads(lines[0])


@contextmanager
def health_server(*, memory_root: str, version: str = "9.9.9", delay: float = 0.0, status: int = 200,
                  writing: bool = False):
    """A synthetic backend on an ephemeral loopback port answering `/healthz` and `/sleep/status`."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - http.server API
            if delay:
                time.sleep(delay)
            if self.path == "/healthz":
                body = {"status": "ok", "version": version, "memoryRoot": memory_root,
                        "memoryPath": memory_root, "entityCount": 0, "episodeCount": 0,
                        "embeddingMode": "local", "leannPresent": False}
            elif self.path == "/sleep/status":
                body = {"status": "running" if writing else "idle", "writing": writing}
            else:
                body = {}
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):  # silence
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
