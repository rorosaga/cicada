"""G132 phase 3a — the relay as the process a container runs (``python -m cicada_relay``), and the container itself on
localhost when Docker answers (skipped cleanly otherwise). Two devices exchange an encrypted frame through each; the
container and its image are removed afterwards."""
from __future__ import annotations

import asyncio
import os
import shutil
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from api.services.sync_relay_client import RelayClient
from api.services.sync_relay_crypto import Endpoint, Home, Keys

REPO = Path(__file__).resolve().parents[2]
MARKER = b"PLAINTEXT-MARKER-process"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_healthy(check, seconds=60) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.2)
    raise AssertionError("relay never became healthy")


async def exchange(port: int) -> None:
    home = Home.create()
    keys = Keys.generate()
    join = home.add_device(keys.public())
    laptop = Endpoint(keys=keys, mailbox=home.mailbox, home=home.me)
    laptop.open(join)
    hc = RelayClient(f"ws://127.0.0.1:{port}", home, create=join)
    await hc.connect()
    assert (await hc.send(home.seal("delta", MARKER, meta={"seq": 1})))[0]["t"] == "ok"
    await hc.close()
    lc = RelayClient(f"ws://127.0.0.1:{port}", laptop)
    await lc.connect()
    got = []
    while not got:
        _, raw = await lc.recv(10)
        msg = laptop.open(raw)
        if msg is not None and msg.kind == "delta":
            got.append(msg.payload)
    assert got == [MARKER]
    await lc.close()


def test_the_relay_runs_as_its_own_process_and_stops_on_sigterm(tmp_path):
    port = free_port()
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "RELAY_PORT": str(port), "RELAY_HOST": "127.0.0.1",
           "RELAY_DB_PATH": str(tmp_path / "relay.db"), "PYTHONPATH": str(REPO / "relay")}
    proc = subprocess.Popen([sys.executable, "-m", "cicada_relay"], env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)
    try:
        health = [sys.executable, "-m", "cicada_relay.health"]
        wait_healthy(lambda: subprocess.run(health, env=env, capture_output=True).returncode == 0)
        asyncio.run(asyncio.wait_for(exchange(port), 30))
    finally:
        proc.terminate()
        out, _ = proc.communicate(timeout=10)
    assert proc.returncode == 0
    assert b"frame mb=" in out and MARKER not in out and b"127.0.0.1:" not in out
    assert MARKER not in b"".join(p.read_bytes() for p in tmp_path.glob("relay.db*"))


def _docker_ready() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=8).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def test_the_container_runs_non_root_on_localhost_and_is_removed(tmp_path):
    if not _docker_ready():   # probed here, not at collection: a daemon that hangs costs only this test
        pytest.skip("Docker is not installed or its daemon does not answer")
    tag = f"cicada-relay-test:{uuid.uuid4().hex[:8]}"
    name = f"cicada-relay-test-{uuid.uuid4().hex[:8]}"
    port = free_port()
    try:
        subprocess.run(["docker", "build", "-q", "-t", tag, str(REPO / "relay")], check=True, capture_output=True,
                       timeout=600)
        subprocess.run(["docker", "run", "-d", "--name", name, "-p", f"127.0.0.1:{port}:8443", "--read-only",
                        "--cap-drop", "ALL", "--security-opt", "no-new-privileges", tag], check=True,
                       capture_output=True, timeout=60)
        user = subprocess.run(["docker", "exec", name, "id", "-u"], capture_output=True, text=True, timeout=30)
        assert user.stdout.strip() == "10001"

        def healthy():
            out = subprocess.run(["docker", "inspect", "-f", "{{.State.Health.Status}}", name], capture_output=True,
                                 text=True, timeout=10).stdout.strip()
            ok = subprocess.run(["docker", "exec", name, "python", "-m", "cicada_relay.health"],
                                capture_output=True, timeout=10).returncode == 0
            return ok or out == "healthy"
        wait_healthy(healthy)
        asyncio.run(asyncio.wait_for(exchange(port), 30))
        logs = subprocess.run(["docker", "logs", name], capture_output=True, timeout=30)
        assert MARKER not in logs.stdout + logs.stderr
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=60)
        subprocess.run(["docker", "rmi", "-f", tag], capture_output=True, timeout=60)
