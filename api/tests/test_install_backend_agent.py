"""Round-4 D3 (G143) — scripts/install-backend-agent.sh, the one source of the backend's LaunchAgent plist.

Run with a temp HOME, a temp repo whose path has a space and an ampersand, and a fake `launchctl` first on PATH
that logs its argv — the real launchd and the real ~/Library are never touched.
"""
from __future__ import annotations

import os
import plistlib
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "install-backend-agent.sh"
LABEL = "com.cicada.backend"


def _fake_launchctl(bin_dir: Path, log: Path, *, bootout_status: int = 113, bootstrap_failures: int = 0) -> None:
    counter = bin_dir / "bootstrap-count"
    counter.write_text("0")
    script = bin_dir / "launchctl"
    script.write_text(f"""#!/bin/bash
echo "$@" >> "{log}"
if [ "$1" = "bootout" ]; then exit {bootout_status}; fi
if [ "$1" = "bootstrap" ]; then
  n=$(( $(cat "{counter}") + 1 )); echo "$n" > "{counter}"
  if [ "$n" -le {bootstrap_failures} ]; then exit 5; fi
fi
exit 0
""")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)


def _setup(tmp_path: Path, *, venv: bool = True, **fake) -> tuple[dict, Path, Path, Path]:
    home = tmp_path / "home"
    repo = tmp_path / "repo dir & co"
    bin_dir = tmp_path / "bin"
    for d in (home, repo, bin_dir):
        d.mkdir(parents=True)
    if venv:
        py = repo / "api" / ".venv" / "bin" / "python"
        py.parent.mkdir(parents=True)
        py.write_text("#!/bin/sh\nexit 0\n")
        py.chmod(0o755)
    log = tmp_path / "launchctl.log"
    _fake_launchctl(bin_dir, log, **fake)
    agents = home / "Library" / "LaunchAgents"
    env = {"HOME": str(home), "PATH": f"{bin_dir}:/usr/bin:/bin", "CICADA_REPO": str(repo),
           "CICADA_MEMORY_PATH": str(tmp_path / "memory"), "LAUNCH_AGENTS_DIR": str(agents)}
    return env, repo, agents / f"{LABEL}.plist", log


def _run(env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["/bin/bash", str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=30)


def test_it_writes_the_plist_install_sh_wrote_and_bootstraps_it(tmp_path):
    env, repo, plist_path, log = _setup(tmp_path)
    done = _run(env)
    assert done.returncode == 0, done.stderr
    plist = plistlib.loads(plist_path.read_bytes())
    py = str(repo / "api" / ".venv" / "bin" / "python")
    assert plist["Label"] == LABEL
    assert plist["ProgramArguments"] == [py, "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", "8000"]
    assert plist["WorkingDirectory"] == str(repo)
    assert plist["EnvironmentVariables"]["CICADA_MEMORY_PATH"] == env["CICADA_MEMORY_PATH"]
    assert plist["EnvironmentVariables"]["CICADA_ALLOW_FEED_FETCH"] == "1"
    assert plist["EnvironmentVariables"]["PYTHONPATH"] == str(repo)
    assert plist["RunAtLoad"] is True and plist["KeepAlive"] is True
    assert (repo / "logs").is_dir()
    uid = os.getuid()
    assert log.read_text().splitlines() == [f"bootout gui/{uid}/{LABEL}", f"bootstrap gui/{uid} {plist_path}"]


def test_it_is_idempotent(tmp_path):
    env, _, plist_path, log = _setup(tmp_path)
    assert _run(env).returncode == 0
    first = plist_path.read_bytes()
    assert _run(env).returncode == 0
    assert plist_path.read_bytes() == first
    assert sum(line.startswith("bootstrap") for line in log.read_text().splitlines()) == 2


def test_a_bootstrap_that_races_its_bootout_is_retried(tmp_path):
    env, _, _, log = _setup(tmp_path, bootstrap_failures=1)
    assert _run(env).returncode == 0
    assert sum(line.startswith("bootstrap") for line in log.read_text().splitlines()) == 2


def test_a_bootstrap_launchd_keeps_refusing_fails_loudly(tmp_path):
    env, _, _, _ = _setup(tmp_path, bootstrap_failures=9)
    done = _run(env)
    assert done.returncode == 4
    assert "backend.err.log" in done.stderr


def test_a_missing_venv_refuses_before_writing_anything(tmp_path):
    env, _, plist_path, log = _setup(tmp_path, venv=False)
    done = _run(env)
    assert done.returncode == 3
    assert not plist_path.exists()
    assert not log.exists() or log.read_text() == ""


def test_dry_run_writes_nothing(tmp_path):
    env, _, plist_path, log = _setup(tmp_path)
    done = _run(env, "--dry-run")
    assert done.returncode == 0
    assert not plist_path.exists()
    assert not log.exists() or log.read_text() == ""
    assert "bootstrap" in done.stdout


def test_install_sh_has_no_second_copy_of_the_plist():
    install = (ROOT / "install.sh").read_text()
    assert "scripts/install-backend-agent.sh" in install
    assert "<key>ProgramArguments</key>" not in install
    assert SCRIPT.read_text().count("<key>ProgramArguments</key>") == 1
