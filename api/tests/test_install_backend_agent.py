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


def test_without_the_variable_it_takes_the_memory_path_api_env_names(tmp_path):
    """The app's Install runs this with no environment: the plist must carry the
    bank api/.env names, never the empty default beside it."""
    env, repo, plist_path, _ = _setup(tmp_path)
    del env["CICADA_MEMORY_PATH"]
    (repo / "api" / ".env").write_text('OTHER=1\nCICADA_MEMORY_PATH="~/src/alpha-memory"\n')
    assert _run(env).returncode == 0
    plist = plistlib.loads(plist_path.read_bytes())
    assert plist["EnvironmentVariables"]["CICADA_MEMORY_PATH"] == f"{env['HOME']}/src/alpha-memory"


def test_the_variable_still_wins_and_the_default_stays_last(tmp_path):
    env, repo, plist_path, _ = _setup(tmp_path)
    (repo / "api" / ".env").write_text("CICADA_MEMORY_PATH=/elsewhere/memory\n")
    assert _run(env).returncode == 0
    assert plistlib.loads(plist_path.read_bytes())["EnvironmentVariables"]["CICADA_MEMORY_PATH"] == env["CICADA_MEMORY_PATH"]
    del env["CICADA_MEMORY_PATH"]
    (repo / "api" / ".env").write_text("OTHER=1\n")
    assert _run(env).returncode == 0
    assert plistlib.loads(plist_path.read_bytes())["EnvironmentVariables"]["CICADA_MEMORY_PATH"] == \
        f"{env['HOME']}/cicada/memory"


# --- G182: a release app's copy runs its stable launcher, never a path inside the app ---

def _release_env(tmp_path: Path) -> tuple[dict, Path, Path, Path]:
    env, repo, plist_path, log = _setup(tmp_path, venv=False)
    cicada_home = tmp_path / "cicada home"
    launcher = cicada_home / "bin" / "cicada-backend"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/sh\nexit 0\n")
    launcher.chmod(0o755)
    env.update({"CICADA_BACKEND_PROGRAM": str(launcher), "CICADA_HOME": str(cicada_home), "CICADA_PORT": "18000"})
    return env, cicada_home, plist_path, log


def test_a_release_install_runs_the_launcher_with_logs_under_cicada_home(tmp_path):
    env, cicada_home, plist_path, log = _release_env(tmp_path)
    done = _run(env)
    assert done.returncode == 0, done.stderr
    plist = plistlib.loads(plist_path.read_bytes())
    assert plist["ProgramArguments"] == [env["CICADA_BACKEND_PROGRAM"]]
    assert plist["WorkingDirectory"] == str(cicada_home)
    environment = plist["EnvironmentVariables"]
    assert environment["CICADA_PORT"] == "18000"
    assert environment["CICADA_HOME"] == str(cicada_home)
    assert environment["CICADA_MEMORY_PATH"] == env["CICADA_MEMORY_PATH"]
    assert "PYTHONPATH" not in environment
    assert plist["StandardErrorPath"] == str(cicada_home / "logs" / "backend.err.log")
    assert (cicada_home / "logs").is_dir()
    assert any(line.startswith("bootstrap") for line in log.read_text().splitlines())


def test_a_release_install_without_its_launcher_refuses(tmp_path):
    env, _, plist_path, _ = _release_env(tmp_path)
    Path(env["CICADA_BACKEND_PROGRAM"]).unlink()
    done = _run(env)
    assert done.returncode == 3
    assert "open Cicada once" in done.stderr
    assert not plist_path.exists()


def test_the_label_can_be_a_test_label(tmp_path):
    env, _, plist_path, log = _release_env(tmp_path)
    env["PLIST_LABEL"] = "com.cicada.backend.test"
    assert _run(env).returncode == 0
    assert not plist_path.exists()
    other = plist_path.with_name("com.cicada.backend.test.plist")
    assert plistlib.loads(other.read_bytes())["Label"] == "com.cicada.backend.test"
