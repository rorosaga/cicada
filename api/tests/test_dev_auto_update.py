"""scripts/dev/auto-update.sh must not move code or restart the backend under a running Sleep,
and must restart the backend only when backend runtime code moved.

Every test runs a COPY of the script inside a scratch git repo, with stub `launchctl`, `curl`,
`uv`, `pgrep` and installer executables first on PATH that record their calls. The real script,
launchctl and installer are never run.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "dev" / "auto-update.sh"


def _git(cwd: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout.strip()


def _stub(path: Path, body: str) -> None:
    path.write_text("#!/bin/bash\n" + textwrap.dedent(body))
    path.chmod(0o755)


class Rig:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.origin = tmp / "origin.git"
        self.repo = tmp / "repo"
        self.bin = tmp / "bin"
        self.home = tmp / "home"
        self.calls = tmp / "calls.log"
        self.status_file = tmp / "status.json"
        self.bin.mkdir()
        self.home.mkdir()
        self.calls.write_text("")
        _git(tmp, "init", "-q", "--bare", "-b", "dev", str(self.origin))
        _git(tmp, "clone", "-q", str(self.origin), str(self.repo))
        _git(self.repo, "checkout", "-q", "-b", "dev")
        (self.repo / "scripts/dev").mkdir(parents=True)
        shutil.copy(SCRIPT, self.repo / "scripts/dev/auto-update.sh")
        for rel in ("api/app.py", "api/tests/test_x.py", "mcp/server.py", "benchmarks/b.py", "docs/a.md",
                    "app/CicadaApp/x.swift"):
            self.write(rel, "v1")
        (self.repo / "logs").mkdir()
        (self.repo / "logs/.gitignore").write_text("*\n")
        _stub(self.repo / "app/CicadaApp/install_app.sh", 'echo "install_app $*" >> "$CALLS"\n')
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "base")
        _git(self.repo, "push", "-q", "origin", "dev")
        self.base = _git(self.repo, "rev-parse", "HEAD")
        (self.repo / "logs/.auto-update-installed").write_text(self.base + "\n")
        _stub(self.bin / "launchctl", 'echo "launchctl $*" >> "$CALLS"\nexit 0\n')
        _stub(self.bin / "uv", 'echo "uv $*" >> "$CALLS"\nexit 0\n')
        _stub(self.bin / "pgrep", "exit 1\n")
        _stub(self.bin / "curl", '''
            echo "curl $*" >> "$CALLS"
            [ -f "$STATUS_FILE" ] || exit 7
            cat "$STATUS_FILE"
            ''')

    def write(self, rel: str, text: str) -> None:
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def push_change(self, rel: str) -> str:
        """Commit a change to `rel` on origin/dev only (a second clone), leaving this checkout behind."""
        other = self.tmp / "other"
        if not other.exists():
            _git(self.tmp, "clone", "-q", "-b", "dev", str(self.origin), str(other))
        p = other / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("v2-" + rel)
        _git(other, "add", "-A")
        _git(other, "commit", "-q", "-m", f"change {rel}")
        _git(other, "push", "-q", "origin", "dev")
        return _git(other, "rev-parse", "HEAD")

    def sleep_status(self, **body) -> None:
        self.status_file.write_text(json.dumps({"status": "idle", "writing": False, **body}))
        (self.home / "api_token").write_text("tok\n")

    def run(self, **extra_env: str) -> subprocess.CompletedProcess:
        env = {**os.environ, "PATH": f"{self.bin}:/usr/bin:/bin:/usr/sbin:/sbin:{os.environ['PATH']}",
               "CALLS": str(self.calls), "STATUS_FILE": str(self.status_file), "CICADA_HOME": str(self.home),
               "CICADA_PORT": "49177", **extra_env}
        env.pop("CICADA_AUTOUPDATE_FORCE", None) if "CICADA_AUTOUPDATE_FORCE" not in extra_env else None
        return subprocess.run(["bash", str(self.repo / "scripts/dev/auto-update.sh")], cwd=self.repo, env=env,
                              capture_output=True, text=True, timeout=60)

    def called(self) -> str:
        return self.calls.read_text()

    def log(self) -> str:
        return (self.repo / "logs/auto-update.log").read_text()

    def head(self) -> str:
        return _git(self.repo, "rev-parse", "HEAD")

    def stamp(self) -> str:
        return (self.repo / "logs/.auto-update-installed").read_text().strip()


@pytest.fixture
def rig(tmp_path):
    return Rig(tmp_path)


def _assert_deferred(rig: Rig) -> None:
    out = rig.run()
    assert out.returncode == 0, out.stderr
    assert "deferred: Sleep is running" in rig.log()
    assert rig.head() == rig.base, "the checkout must not move under a running Sleep"
    assert rig.stamp() == rig.base
    assert "kickstart" not in rig.called()
    assert "install_app" not in rig.called()


def test_busy_running_defers_everything(rig):
    rig.push_change("api/app.py")
    rig.sleep_status(status="running")
    _assert_deferred(rig)


# The real route shape of a paused run (api/routers/sleep.py, test_sleep_paused.py): idle, not writing,
# an inactive unfinished drain (or none after a restart) and a top-level `paused` block.
PAUSED = {"runId": "sleep_pz", "reason": "plan_window", "filed": 3, "frozen": 9, "canContinue": True}


def test_active_unfinished_drain_defers(rig):
    rig.push_change("api/app.py")
    rig.sleep_status(drain={"active": True, "finished": False})
    _assert_deferred(rig)


def test_in_process_pause_defers(rig):
    rig.push_change("api/app.py")
    rig.sleep_status(drain={"active": False, "finished": False}, paused=PAUSED)
    _assert_deferred(rig)


def test_recovered_pause_without_a_drain_defers(rig):
    rig.push_change("api/app.py")
    rig.sleep_status(drain=None, paused=PAUSED)
    _assert_deferred(rig)


@pytest.mark.parametrize("drain", [{"active": False, "finished": True}, {"active": False, "finished": False}, None])
def test_finished_or_failed_run_without_a_pause_is_eligible(rig, drain):
    new = rig.push_change("api/app.py")
    rig.sleep_status(drain=drain, paused=None)
    assert rig.run().returncode == 0
    assert rig.head() == new


def test_writing_defers(rig):
    rig.push_change("api/app.py")
    rig.sleep_status(writing=True)
    _assert_deferred(rig)


def test_finished_drain_is_not_busy(rig):
    new = rig.push_change("api/app.py")
    rig.sleep_status(drain={"active": True, "finished": True})
    assert rig.run().returncode == 0
    assert rig.head() == new
    assert "kickstart" in rig.called()


def test_status_call_is_bounded_and_authenticated(rig):
    rig.sleep_status()
    rig.run()
    curl = [ln for ln in rig.called().splitlines() if ln.startswith("curl")][0]
    assert "-m 3" in curl and "127.0.0.1:49177/sleep/status" in curl and "Bearer tok" in curl


def test_idle_proceeds_and_restarts_for_api_runtime_change(rig):
    new = rig.push_change("api/app.py")
    rig.sleep_status()
    assert rig.run().returncode == 0
    assert rig.head() == new
    assert "kickstart -k" in rig.called()
    assert "backend restarted" in rig.log()


def test_unreachable_backend_proceeds(rig):
    new = rig.push_change("api/app.py")
    (rig.home / "api_token").write_text("tok\n")   # a token, but no status file: the curl stub exits 7
    assert rig.run().returncode == 0
    assert "curl" in rig.called()
    assert rig.head() == new
    assert "kickstart -k" in rig.called()


def test_unparseable_status_proceeds(rig):
    new = rig.push_change("api/app.py")
    rig.status_file.write_text("<html>not json")
    (rig.home / "api_token").write_text("tok\n")
    assert rig.run().returncode == 0
    assert rig.head() == new


def test_missing_token_file_proceeds_without_asking(rig):
    new = rig.push_change("api/app.py")
    rig.status_file.write_text(json.dumps({"status": "running"}))   # busy, but we cannot ask
    assert rig.run().returncode == 0
    assert rig.head() == new
    assert "curl" not in rig.called()


def test_force_skips_the_check(rig):
    new = rig.push_change("api/app.py")
    rig.sleep_status(status="running")
    assert rig.run(CICADA_AUTOUPDATE_FORCE="1").returncode == 0
    assert rig.head() == new
    assert "kickstart -k" in rig.called()


@pytest.mark.parametrize("rel", ["api/tests/test_y.py", "benchmarks/b2.py", "docs/b.md"])
def test_non_runtime_merge_never_restarts_the_backend(rig, rel):
    new = rig.push_change(rel)
    rig.sleep_status()
    assert rig.run().returncode == 0
    assert rig.head() == new
    assert "kickstart" not in rig.called()
    assert rig.stamp() == new


def test_mcp_change_restarts(rig):
    rig.push_change("mcp/server.py")
    rig.sleep_status()
    rig.run()
    assert "kickstart -k" in rig.called()


def test_dependency_file_change_restarts(rig):
    rig.push_change("api/uv.lock")
    rig.sleep_status()
    rig.run()
    assert "uv sync" in rig.called()
    assert "kickstart -k" in rig.called()
