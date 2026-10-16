"""G181 phase 1 — Cicada on a headless Linux server: the systemd user unit (scripts/install-backend-service.sh) and
a bank that can commit on a machine with no git identity.

Every run uses a temp HOME, a temp repo whose path has a space, a percent sign and an ampersand, and fake
`systemctl`, `loginctl` and `uname` first on PATH that log their argv: the real systemd, the real ~/.config and
the real network are never touched. Git runs with `user.useConfigOnly`, so it never guesses an identity from the
hostname, on Linux or on a Mac.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from api.services import bank_registry, git_service

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "install-backend-service.sh"
UNIT = "cicada-backend.service"


# --------------------------------------------------------------------------- the systemd user unit


def _fake(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _setup(tmp_path: Path, *, venv: bool = True, linger: str = "yes", os_name: str = "Linux",
           systemctl_fails: str = "") -> tuple[dict, Path, Path, Path]:
    home = tmp_path / "home"
    repo = tmp_path / "repo dir 100% & co"
    bin_dir = tmp_path / "bin"
    for d in (home, repo, bin_dir):
        d.mkdir(parents=True)
    if venv:
        py = repo / "api" / ".venv" / "bin" / "python"
        py.parent.mkdir(parents=True)
        py.write_text("#!/bin/sh\nexit 0\n")
        py.chmod(0o755)
    log = tmp_path / "calls.log"
    fail = f'if [ "$2" = "{systemctl_fails}" ]; then exit 1; fi\n' if systemctl_fails else ""
    _fake(bin_dir, "systemctl", f'echo "systemctl $@" >> "{log}"\n{fail}exit 0\n')
    _fake(bin_dir, "loginctl", f'echo "loginctl $@" >> "{log}"\necho {linger}\n')
    _fake(bin_dir, "uname", f'echo {os_name}\n')
    units = home / ".config" / "systemd" / "user"
    env = {"HOME": str(home), "PATH": f"{bin_dir}:/usr/bin:/bin", "CICADA_REPO": str(repo),
           "CICADA_MEMORY_PATH": str(tmp_path / "memory bank"), "CICADA_HOME": str(home / ".cicada"),
           "SYSTEMD_USER_DIR": str(units)}
    return env, repo, units / UNIT, log


def _run(env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["/bin/bash", str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=30)


def _directives(unit: Path) -> list[tuple[str, str]]:
    out = []
    for line in unit.read_text().splitlines():
        if line and not line.startswith(("#", "[")) and "=" in line:
            key, value = line.split("=", 1)
            out.append((key, value))
    return out


def test_it_writes_a_user_unit_bound_to_loopback_and_starts_it(tmp_path):
    env, repo, unit, log = _setup(tmp_path)
    done = _run(env)
    assert done.returncode == 0, done.stderr
    d = _directives(unit)
    py = repo / "api" / ".venv" / "bin" / "python"
    exec_start = dict(d)["ExecStart"]
    assert exec_start == f'"{str(py).replace("%", "%%")}" -m uvicorn api.main:app --host 127.0.0.1 --port 8000'
    environment = [v for k, v in d if k == "Environment"]
    assert f'"CICADA_MEMORY_PATH={env["CICADA_MEMORY_PATH"]}"' in environment
    assert f'"CICADA_HOME={env["CICADA_HOME"]}"' in environment
    assert f'"PYTHONPATH={str(repo).replace("%", "%%")}"' in environment
    assert "CICADA_ALLOW_FEED_FETCH=1" in environment
    assert dict(d)["WorkingDirectory"] == str(repo).replace("%", "%%")
    assert dict(d)["UMask"] == "0077" and dict(d)["Restart"] == "always"
    assert dict(d)["WantedBy"] == "default.target"
    assert log.read_text().splitlines()[:3] == [
        "systemctl --user daemon-reload", f"systemctl --user enable {UNIT}", f"systemctl --user restart {UNIT}"]
    assert (repo / "logs").is_dir()
    cicada_home = Path(env["CICADA_HOME"])
    assert stat.S_IMODE(cicada_home.stat().st_mode) == 0o700


def test_nothing_listens_beyond_this_machine(tmp_path):
    """The unit binds loopback only. Reaching it from another machine is an overlay the person runs."""
    env, _, unit, _ = _setup(tmp_path)
    env["CICADA_HOST"] = "0.0.0.0"  # not an input this script reads
    assert _run(env).returncode == 0
    text = unit.read_text()
    assert "0.0.0.0" not in text and "--host 127.0.0.1" in text
    assert "tailscale" not in text.lower()


def test_it_creates_no_credential(tmp_path):
    env, _, _, _ = _setup(tmp_path)
    assert _run(env).returncode == 0
    made = sorted(p.name for p in Path(env["CICADA_HOME"]).rglob("*"))
    assert made == [], "the backend writes its own api_token; secrets.env is the person's"


def test_it_is_idempotent(tmp_path):
    env, _, unit, _ = _setup(tmp_path)
    assert _run(env).returncode == 0
    first = unit.read_bytes()
    assert _run(env).returncode == 0
    assert unit.read_bytes() == first
    assert not [p for p in unit.parent.iterdir() if p.name.startswith(".")], "no temp unit left behind"


def test_the_port_and_unit_name_follow_the_environment(tmp_path):
    env, _, unit, _ = _setup(tmp_path)
    env.update({"CICADA_PORT": "18731", "UNIT_NAME": "cicada-test.service"})
    assert _run(env).returncode == 0
    other = unit.parent / "cicada-test.service"
    assert "--port 18731" in other.read_text() and not unit.exists()
    env["CICADA_PORT"] = "80; rm -rf /"
    bad = _run(env)
    assert bad.returncode == 2 and "must be a number" in bad.stderr


def test_dry_run_writes_and_starts_nothing(tmp_path):
    env, _, unit, log = _setup(tmp_path)
    done = _run(env, "--dry-run")
    assert done.returncode == 0
    assert "127.0.0.1:8000" in done.stdout and f"systemctl --user restart {UNIT}" in done.stdout
    assert not unit.exists() and not log.exists()


def test_no_start_writes_the_unit_only(tmp_path):
    env, _, unit, log = _setup(tmp_path)
    assert _run(env, "--no-start").returncode == 0
    assert unit.exists()
    assert log.read_text().splitlines()[0] == "systemctl --user daemon-reload"
    assert "restart" not in log.read_text()


def test_without_a_venv_it_says_run_install(tmp_path):
    env, _, unit, _ = _setup(tmp_path, venv=False)
    done = _run(env)
    assert done.returncode == 3 and "./install.sh" in done.stderr
    assert not unit.exists()


def test_on_a_mac_it_points_at_the_launchd_agent(tmp_path):
    env, _, unit, log = _setup(tmp_path, os_name="Darwin")
    done = _run(env)
    assert done.returncode == 5 and "install-backend-agent.sh" in done.stderr
    assert not unit.exists() and not log.exists()


def test_a_refused_start_says_where_to_look(tmp_path):
    env, _, _, _ = _setup(tmp_path, systemctl_fails="restart")
    done = _run(env)
    assert done.returncode == 4 and "journalctl --user -u" in done.stderr


def test_lingering_is_checked_and_never_changed(tmp_path):
    env, _, _, log = _setup(tmp_path, linger="no")
    done = _run(env)
    assert done.returncode == 0
    assert "sudo loginctl enable-linger" in done.stdout
    assert not [line for line in log.read_text().splitlines() if line.startswith("loginctl enable")]
    env2, _, _, _ = _setup(tmp_path / "again", linger="yes")
    assert "enable-linger" not in _run(env2).stdout


def test_a_path_with_a_quote_is_refused(tmp_path):
    env, _, unit, _ = _setup(tmp_path)
    env["CICADA_MEMORY_PATH"] = str(tmp_path / 'say "hi"')
    done = _run(env)
    assert done.returncode == 2 and not unit.exists()


def test_uninstall_removes_the_unit_and_keeps_the_memory(tmp_path):
    env, _, unit, log = _setup(tmp_path)
    memory = Path(env["CICADA_MEMORY_PATH"])
    memory.mkdir()
    (memory / "keep.md").write_text("kept")
    assert _run(env).returncode == 0
    done = _run(env, "--uninstall")
    assert done.returncode == 0 and not unit.exists()
    assert (memory / "keep.md").read_text() == "kept"
    assert f"systemctl --user disable --now {UNIT}" in log.read_text()


@pytest.mark.skipif(shutil.which("systemd-analyze") is None, reason="needs systemd-analyze")
def test_systemd_accepts_the_unit(tmp_path):
    """systemd's own parser reads the unit. A planted bad line proves the check can fail here, so it never passes
    without having looked (a user-mode verify needs a session's runtime dir; the system-mode parse needs none)."""
    env, _, unit, _ = _setup(tmp_path)
    assert _run(env, "--no-start").returncode == 0

    def problems(path: Path) -> list[str]:
        done = subprocess.run(["systemd-analyze", "verify", str(path)], capture_output=True, text=True, timeout=60,
                              env={k: v for k, v in os.environ.items() if k != "SYSTEMD_UNIT_PATH"})
        return [line for line in done.stderr.splitlines() if str(path) in line]

    control = tmp_path / "control.service"
    control.write_text(unit.read_text().replace("UMask=0077", "UMask=not-a-mask"))
    if not problems(control):
        pytest.skip("systemd-analyze cannot parse unit files in this environment")
    assert not problems(unit)


# --------------------------------------------------------------------------- a bank commits with no git identity


@pytest.fixture
def no_identity(tmp_path, monkeypatch):
    """A machine like a fresh server: no ~/.gitconfig, no system config, and git told never to guess."""
    home = tmp_path / "nohome"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / "gitconfig-absent"))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "user.useConfigOnly")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "true")
    for var in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "EMAIL"):
        monkeypatch.delenv(var, raising=False)
    return home


def _git(path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(path), capture_output=True, text=True)


def test_a_new_bank_commits_on_a_machine_with_no_identity(tmp_path, no_identity):
    bank = tmp_path / "bank"
    bank_registry.scaffold_bank(bank)
    (bank / "entities" / "alpha-project.md").write_text("# alpha-project\n")
    assert _git(bank, "add", "-A").returncode == 0
    done = _git(bank, "commit", "-m", "first")
    assert done.returncode == 0, done.stderr
    assert _git(bank, "log", "-1", "--format=%an <%ae>").stdout.strip() == "Cicada <cicada@localhost>"


def test_an_identity_that_resolves_is_never_overridden(tmp_path, no_identity, monkeypatch):
    monkeypatch.setenv("GIT_AUTHOR_NAME", "alice-example")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "alice@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "alice-example")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "alice@example.com")
    bank = tmp_path / "bank"
    bank_registry.scaffold_bank(bank)
    assert _git(bank, "config", "--local", "--get", "user.name").returncode != 0
    assert git_service.ensure_commit_identity_sync(bank) is False


def test_a_global_identity_is_used_and_never_written(tmp_path, no_identity, monkeypatch):
    global_cfg = no_identity / "gitconfig"
    global_cfg.write_text("[user]\n\tname = bob-example\n\temail = bob@example.com\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_cfg))
    bank = tmp_path / "bank"
    bank_registry.scaffold_bank(bank)
    assert git_service.ensure_commit_identity_sync(bank) is False
    assert "Cicada" not in global_cfg.read_text()
    assert _git(bank, "config", "--local", "--get", "user.name").returncode != 0


def test_it_sets_the_identity_once_and_only_in_the_bank(tmp_path, no_identity):
    bank = tmp_path / "bank"
    bank_registry.scaffold_bank(bank, git_init=False)
    assert git_service.ensure_commit_identity_sync(bank) is False, "not a git repo: nothing to do"
    _git(bank, "init", "-q")
    assert git_service.ensure_commit_identity_sync(bank) is True
    assert git_service.ensure_commit_identity_sync(bank) is False
    assert _git(bank, "config", "--local", "user.email").stdout.strip() == "cicada@localhost"
    assert not (no_identity / "gitconfig-absent").exists()


# --------------------------------------------------------------------------- install.sh picks the service by platform


def _install_dry_run(tmp_path: Path, os_name: str, api_base: str = "") -> tuple[subprocess.CompletedProcess, Path]:
    import re

    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    home.mkdir()
    bin_dir.mkdir()
    if api_base:
        (home / ".cicada").mkdir()
        (home / ".cicada" / "api_base").write_text(api_base + "\n")
    _fake(bin_dir, "uname", f'if [ "$1" = "-m" ]; then echo x86_64; else echo {os_name}; fi\n')
    _fake(bin_dir, "uv", "exit 0\n")
    # install.sh probes a fixed :8000 and skips step 6 when a backend answers; on a developer's Mac one does.
    _fake(bin_dir, "curl", "exit 7\n")
    env = {"HOME": str(home), "PATH": f"{bin_dir}:/usr/bin:/bin", "CICADA_MEMORY_PATH": str(tmp_path / "memory"),
           "CLAUDE_CLI": "cicada-no-such-cli", "CICADA_PORT": "1", "CICADA_RECALL": "off"}
    done = subprocess.run(["/bin/bash", str(ROOT / "install.sh"), "--dry-run"], env=env, capture_output=True,
                          text=True, timeout=120)
    done.stdout = re.sub(r"\x1b\[[0-9;]*m", "", done.stdout)
    return done, home


def test_install_on_linux_installs_the_systemd_unit(tmp_path):
    done, home = _install_dry_run(tmp_path, "Linux")
    assert done.returncode == 0, done.stderr + done.stdout[-2000:]
    assert "6. Backend service (systemd user unit)" in done.stdout
    assert "systemctl --user restart cicada-backend.service" in done.stdout
    assert "127.0.0.1:8000" in done.stdout and "launchctl" not in done.stdout
    assert "service:       " in done.stdout and "(systemd --user; 127.0.0.1:8000 only)" in done.stdout
    assert "user.email cicada@localhost" in done.stdout, "the first commit works on a machine with no identity"
    assert not any(home.iterdir()), "a dry run writes nothing"


def test_install_on_a_mac_keeps_launchd(tmp_path):
    done, _ = _install_dry_run(tmp_path, "Darwin")
    assert done.returncode == 0, done.stderr + done.stdout[-2000:]
    assert "6. Backend service (launchd)" in done.stdout and "launchctl bootstrap" in done.stdout
    assert "systemctl" not in done.stdout


@pytest.mark.parametrize("os_name", ["Darwin", "Linux"])
def test_install_on_a_server_client_installs_no_local_backend(tmp_path, os_name):
    """#313: a machine whose memory lives on a server (the app's api_base) runs no backend of its own."""
    done, _ = _install_dry_run(tmp_path, os_name, api_base="https://server.example.invalid")
    assert done.returncode == 0, done.stderr + done.stdout[-2000:]
    assert "memory lives on a server" in done.stdout
    assert "launchctl bootstrap" not in done.stdout and "systemctl --user restart" not in done.stdout
    # QA 2026-10-16: the summary named a unit and a master token that a client never gets.
    assert "service:       none" in done.stdout
    assert "api_token" not in done.stdout and "device_token" in done.stdout
    assert "cicada-backend.service" not in done.stdout and "com.cicada.backend.plist" not in done.stdout
    # Owner decision 4 (2026-10-16): a client holds no bank, so it gets no empty memory folder either — no mkdir,
    # no git init, no CICADA_MEMORY_PATH in api/.env or the MCP entry.
    memory = str(tmp_path / "memory")
    assert "no local memory folder" in done.stdout
    assert f"mkdir -p {memory}" not in done.stdout and "git init" not in done.stdout
    assert f"CICADA_MEMORY_PATH={memory}" not in done.stdout
    assert "memory:        on the server" in done.stdout


def test_the_next_step_names_doctor_without_make_where_make_is_missing(tmp_path):
    """Headless QA: a minimal Linux server has no make (and a Homebrew keg no Makefile). install.sh's own
    `doctor_hint`, run with and without a `make` on PATH and a Makefile in the repo."""
    import re

    text = (ROOT / "install.sh").read_text()
    body = re.search(r"^doctor_hint\(\) \{.*?^\}$", text, re.S | re.M).group(0)
    empty, with_make, repo = tmp_path / "empty", tmp_path / "make-bin", tmp_path / "repo"
    for d in (empty, with_make, repo):
        d.mkdir()
    _fake(with_make, "make", "exit 0\n")

    def hint(path_dir: Path, makefile: bool) -> str:
        (repo / "Makefile").unlink(missing_ok=True)
        if makefile:
            (repo / "Makefile").write_text("doctor:\n")
        return subprocess.run(["/bin/bash", "-c", f"REPO='{repo}'\n{body}\ndoctor_hint"], env={"PATH": str(path_dir)},
                              capture_output=True, text=True, timeout=30).stdout

    assert hint(empty, True) == f"bash '{repo}/scripts/doctor.sh'"
    assert hint(with_make, False) == f"bash '{repo}/scripts/doctor.sh'"
    assert hint(with_make, True) == f"make -C '{repo}' doctor"
    assert "Next: run $(doctor_hint)" in text and "Next: run 'make doctor'" not in text


def test_doctor_checks_the_service_of_its_platform():
    text = (ROOT / "scripts" / "doctor.sh").read_text()
    assert "systemctl --user is-active --quiet cicada-backend.service" in text
    assert 'launchctl print "gui/$(id -u)/com.cicada.backend"' in text


def test_a_bank_with_the_fallback_identity_is_never_taken_for_a_demo(tmp_path, no_identity):
    """demo_guard reads a generator email in .git/config; the fallback must never match it, or every server bank
    would refuse capture as a demo."""
    from api.services import demo_guard

    bank = tmp_path / "bank"
    bank_registry.scaffold_bank(bank)
    assert _git(bank, "config", "--local", "user.email").stdout.strip() == "cicada@localhost"
    assert git_service.FALLBACK_IDENTITY[1] != demo_guard.GENERATOR_EMAIL
    assert demo_guard.is_demo(bank) is False
