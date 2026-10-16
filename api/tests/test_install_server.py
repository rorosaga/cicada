"""G181 — the one-line Linux server install (scripts/install-server.sh) and the Homebrew formula's wiring.

The installer is driven against a synthetic Cicada repo (real git, fake install.sh / sync / service / CLI scripts that
only log) with fake `uname`, `systemctl`, `loginctl` and `curl` first on PATH, under a temp HOME: no real systemd, no
network, no real repo. The real end-to-end runs are scripts/dev/test-install-linux.sh and test-install-brew.sh
(Docker); this file holds the orchestration rules so a change to them fails here first.
"""
from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "install-server.sh"
SETUP = ROOT / "scripts" / "cicada-setup.sh"
SYNC = ROOT / "scripts" / "sync-server-env.sh"
FORMULA = ROOT / "Formula" / "cicada.rb"
TOKEN = "tok-SECRET-value-never-printed"


def _exe(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _git(*args: str, cwd: Path) -> str:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args], cwd=cwd,
                          env=env, check=True, capture_output=True, text=True).stdout.strip()


def _commit(src: Path, version: str, tag: str | None = None) -> str:
    (src / "VERSION").write_text(version + "\n")
    _git("add", "-A", cwd=src)
    _git("commit", "-q", "-m", f"v{version}", cwd=src)
    if tag:
        _git("tag", tag, cwd=src)
    return _git("rev-parse", "HEAD", cwd=src)


@pytest.fixture
def world(tmp_path):
    """A served repo with releases v0.3.1, v0.10.0 (newest) and v0.9.0, and fakes for everything systemd and HTTP."""
    log = tmp_path / "calls.log"
    src = tmp_path / "src"
    src.mkdir()
    _git("init", "-q", "-b", "dev", cwd=src)
    _exe(src / "install.sh", f'echo "install.sh $* REPO=$CICADA_REPO" >> "{log}"\n'
                            'case "$*" in *--cli*) mkdir -p "$HOME/.local/bin"; '
                            'ln -sfn "$CICADA_REPO/scripts/cicada" "$HOME/.local/bin/cicada";; esac\n'
                            'mkdir -p "$HOME/.cicada"; printf "' + TOKEN + '" > "$HOME/.cicada/api_token"\n')
    _exe(src / "scripts" / "sync-server-env.sh", f'echo "sync $*" >> "{log}"\n')
    _exe(src / "scripts" / "install-backend-service.sh", f'echo "service $*" >> "{log}"\n')
    _exe(src / "scripts" / "cicada", f'echo "cicada $*" >> "{log}"\n')
    shas = {"v0.3.1": _commit(src, "0.3.1", "v0.3.1"), "v0.10.0": _commit(src, "0.10.0", "v0.10.0")}
    _git("checkout", "-q", "-b", "old", "v0.3.1", cwd=src)
    shas["v0.9.0"] = _commit(src, "0.9.0", "v0.9.0")
    _git("checkout", "-q", "dev", cwd=src)
    served = tmp_path / "cicada.git"
    _git("clone", "-q", "--bare", str(src), str(served), cwd=tmp_path)

    home = tmp_path / "home"
    home.mkdir()
    fake = tmp_path / "fakebin"
    _exe(fake / "uname", 'echo Linux\n')
    _exe(fake / "systemctl", f'echo "systemctl $*" >> "{log}"\nexit 0\n')
    _exe(fake / "loginctl", 'echo yes\n')
    _exe(fake / "curl", f'echo "curl $*" >> "{log}"\necho \'{{"status":"ok"}}\'\n')
    _exe(home / ".local" / "bin" / "uv", 'exit 0\n')
    env = {"HOME": str(home), "PATH": f"{fake}:/usr/bin:/bin", "CICADA_GIT_URL": str(served),
           "CICADA_MEMORY_PATH": str(tmp_path / "memory"), "LC_ALL": "C"}
    return {"env": env, "log": log, "src": src, "served": served, "home": home, "fake": fake, "shas": shas,
            "dir": home / ".local" / "share" / "cicada"}


def _run(env: dict, *args: str, **extra) -> subprocess.CompletedProcess:
    return subprocess.run(["/bin/bash", str(SCRIPT), *args], env={**env, **extra}, capture_output=True, text=True,
                          timeout=60, stdin=subprocess.DEVNULL)


def _calls(world) -> list[str]:
    return world["log"].read_text().splitlines() if world["log"].exists() else []


def test_it_installs_the_newest_release_by_semver_and_runs_the_checkouts_own_installer(world):
    done = _run(world["env"])
    assert done.returncode == 0, done.stdout + done.stderr
    assert "Latest release: v0.10.0" in done.stdout          # not v0.9.0: 10 > 9, numerically
    assert _git("rev-parse", "HEAD", cwd=world["dir"]) == world["shas"]["v0.10.0"]
    calls = _calls(world)
    assert "sync --quiet" in calls
    assert f"install.sh --cli REPO={world['dir']}" in calls
    assert not any(c.startswith("service") for c in calls)   # a fresh install: install.sh starts the unit itself


def test_it_never_prints_the_token_and_says_where_it_lives(world):
    done = _run(world["env"])
    assert TOKEN not in done.stdout + done.stderr
    assert ".cicada/api_token" in done.stdout


def test_a_rerun_of_the_same_ref_changes_nothing(world):
    assert _run(world["env"]).returncode == 0
    world["log"].write_text("")
    again = _run(world["env"])
    assert again.returncode == 0, again.stderr
    assert not any(c.startswith("service") for c in _calls(world))   # no restart


def test_a_newer_release_updates_the_code_and_restarts_the_service(world):
    assert _run(world["env"], CICADA_REF="v0.9.0").returncode == 0
    world["log"].write_text("")
    done = _run(world["env"])
    assert done.returncode == 0, done.stderr
    assert _git("rev-parse", "HEAD", cwd=world["dir"]) == world["shas"]["v0.10.0"]
    assert "service " in _calls(world)                         # rewritten and restarted on the new code


def test_cicada_ref_takes_a_branch_or_a_commit(world):
    assert _run(world["env"], CICADA_REF="old").returncode == 0
    assert _git("rev-parse", "HEAD", cwd=world["dir"]) == world["shas"]["v0.9.0"]
    commit = world["shas"]["v0.3.1"]
    assert _run(world["env"], CICADA_REF=commit[:12]).returncode == 0
    assert _git("rev-parse", "HEAD", cwd=world["dir"]) == commit


@pytest.mark.parametrize("ref", ["--upload-pack=x", "dev; rm -rf ~", "a b"])
def test_a_ref_that_is_not_a_name_is_refused(world, ref):
    done = _run(world["env"], CICADA_REF=ref)
    assert done.returncode == 2
    assert not world["dir"].exists()


def test_an_unknown_ref_is_named(world):
    done = _run(world["env"], CICADA_REF="no-such-branch")
    assert done.returncode == 1
    assert "no branch, tag or commit called 'no-such-branch'" in done.stderr


def test_with_no_release_it_says_how_to_install_a_branch(world, tmp_path):
    bare = tmp_path / "empty.git"
    _git("clone", "-q", "--bare", "--no-tags", str(world["src"]), str(bare), cwd=tmp_path)
    done = _run(world["env"], CICADA_GIT_URL=str(bare))
    assert done.returncode == 1
    assert "CICADA_REF=dev" in done.stderr


def test_every_missing_prerequisite_is_named_at_once_and_nothing_is_installed(world):
    (world["home"] / ".local" / "bin" / "uv").unlink()
    _exe(world["fake"] / "systemctl", "exit 1\n")              # no user manager reachable
    done = _run(world["env"])
    assert done.returncode == 2
    assert "uv is missing — install it with: curl -LsSf https://astral.sh/uv/install.sh | sh" in done.stderr
    assert "systemd's user manager isn't reachable" in done.stderr
    assert "enable-linger" in done.stderr
    assert not world["dir"].exists()


def test_uv_installed_by_its_own_installer_is_found_off_path(world):
    done = _run(world["env"])                                  # uv lives only in ~/.local/bin, not on PATH
    assert done.returncode == 0, done.stderr


def test_on_a_mac_it_points_at_homebrew_and_the_app(world):
    _exe(world["fake"] / "uname", "echo Darwin\n")
    done = _run(world["env"])
    assert done.returncode == 2
    assert "brew tap rorosaga/cicada https://github.com/rorosaga/cicada" in done.stderr
    assert "install-release.sh" in done.stderr


def test_it_refuses_root(world):
    _exe(world["fake"] / "id", 'if [ "$1" = "-u" ]; then echo 0; else /usr/bin/id "$@"; fi\n')
    done = _run(world["env"])
    assert done.returncode == 2
    assert "not as root" in done.stderr


def test_it_never_turns_on_lingering_and_says_how_when_it_is_off(world):
    _exe(world["fake"] / "loginctl", f'echo "loginctl $*" >> "{world["log"]}"\necho no\n')
    done = _run(world["env"])
    assert done.returncode == 0
    assert "sudo loginctl enable-linger" in done.stdout
    assert not any("enable-linger" in c for c in _calls(world))


def test_a_folder_that_is_not_its_checkout_is_left_alone(world):
    world["dir"].mkdir(parents=True)
    (world["dir"] / "notes.txt").write_text("mine")
    for args in ((), ("--uninstall",)):
        done = _run(world["env"], *args)
        assert done.returncode == 1
        assert "left alone" in done.stderr
    assert (world["dir"] / "notes.txt").read_text() == "mine"


def test_local_changes_in_the_checkout_are_never_overwritten(world):
    assert _run(world["env"]).returncode == 0
    (world["dir"] / "VERSION").write_text("edited\n")
    done = _run(world["env"], CICADA_REF="v0.9.0")
    assert done.returncode == 1
    assert "changes of its own" in done.stderr
    assert (world["dir"] / "VERSION").read_text() == "edited\n"


def test_uninstall_removes_the_code_and_command_and_keeps_the_memory(world, tmp_path):
    assert _run(world["env"]).returncode == 0
    memory = Path(world["env"]["CICADA_MEMORY_PATH"])
    memory.mkdir()
    (memory / "page.md").write_text("kept")
    world["log"].write_text("")
    done = _run(world["env"], "--uninstall")
    assert done.returncode == 0, done.stderr
    assert f"install.sh --uninstall REPO={world['dir']}" in _calls(world)
    assert not world["dir"].exists()
    assert not (world["home"] / ".local" / "bin" / "cicada").is_symlink()
    assert (memory / "page.md").read_text() == "kept"
    assert (world["home"] / ".cicada" / "api_token").exists()


def test_the_script_runs_only_once_fully_read_and_children_never_read_the_pipe():
    text = SCRIPT.read_text()
    assert text.rstrip().endswith('main "$@"')
    for line in text.splitlines():
        if re.search(r'bash "\$DIR/(install\.sh|scripts/[a-z-]+\.sh)"', line) or "git clone" in line:
            assert "</dev/null" in line, line


def test_it_binds_nothing_itself_and_creates_no_credential():
    text = SCRIPT.read_text()
    assert "0.0.0.0" not in text
    assert "enable-linger" not in text.replace("sudo loginctl enable-linger", "")
    assert "api_token" in text and not re.search(r"(cat|head|tail|less)\b[^\n]*api_token", text)


# --------------------------------------------------------------------------- the Python environment's set


def test_the_server_set_drops_only_the_larger_models_runtime():
    """sync-server-env.sh prunes sentence-transformers' subtree (torch, CUDA) and nothing the backend needs."""
    def names(*extra: str) -> set[str]:
        out = subprocess.run(["uv", "export", "--frozen", "--no-dev", "--no-emit-project", "--no-hashes", "--quiet",
                              *extra], cwd=ROOT / "api", capture_output=True, text=True, check=True).stdout
        return {m.lower().replace("_", "-") for m in re.findall(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==", out, re.M)}

    if subprocess.run(["which", "uv"], capture_output=True).returncode != 0:
        pytest.skip("uv not on PATH")
    dropped = names() - names("--prune", "sentence-transformers")
    assert {"sentence-transformers", "torch", "transformers"} <= dropped
    assert not any(n.startswith("nvidia-") for n in names("--prune", "sentence-transformers"))
    for needed in ("fastapi", "uvicorn", "onnxruntime", "tokenizers", "sqlite-vec", "litellm", "mcp", "numpy"):
        assert needed not in dropped, needed
    release = [line.split("#")[0].strip() for line in
               (ROOT / "scripts" / "release" / "requirements.in").read_text().splitlines()]
    assert not any(r.startswith(("sentence-transformers", "torch")) for r in release)   # the release app's set agrees


def test_sync_runs_uv_sync_frozen_without_dev(tmp_path):
    text = SYNC.read_text()
    assert "uv sync --frozen --no-dev" in text
    assert "--prune sentence-transformers" in text


# --------------------------------------------------------------------------- Homebrew


def test_the_formula_declares_no_brew_service():
    """install-backend-agent.sh is the one source of the launchd agent; `brew services` must not write another."""
    code = "\n".join(line for line in FORMULA.read_text().splitlines() if not line.lstrip().startswith("#"))
    assert "service do" not in code and "plist" not in code
    assert "cicada-setup.sh" in code


def test_the_formula_tag_is_versions():
    tag = re.search(r'^\s*url\s+"[^"]*",\s*tag:\s*"v([^"]*)"', FORMULA.read_text(), re.M).group(1)
    assert tag == (ROOT / "VERSION").read_text().strip()


def test_cicada_setup_names_the_stable_path_and_restarts_only_its_own_service(tmp_path):
    repo = tmp_path / "opt" / "cicada" / "libexec"
    log = tmp_path / "calls.log"
    _exe(repo / "install.sh", f'echo "install.sh $* REPO=$CICADA_REPO LOG=$CICADA_LOG_DIR" >> "{log}"\n')
    _exe(repo / "scripts" / "install-backend-service.sh", f'echo "service" >> "{log}"\n')
    fake = tmp_path / "bin"
    _exe(fake / "uname", "echo Linux\n")
    _exe(fake / "curl", "echo '{\"status\":\"ok\"}'\n")                 # a backend is already up
    units = tmp_path / "units"
    env = {"HOME": str(tmp_path), "PATH": f"{fake}:/usr/bin:/bin", "CICADA_REPO": str(repo),
           "SYSTEMD_USER_DIR": str(units), "CICADA_LOG_DIR": str(tmp_path / "var-log")}

    def run(*args):
        log.write_text("")
        done = subprocess.run(["/bin/bash", str(SETUP), *args], env=env, capture_output=True, text=True, timeout=30)
        assert done.returncode == 0, done.stderr
        return log.read_text().splitlines()

    assert run() == [f"install.sh  REPO={repo} LOG={tmp_path / 'var-log'}"]        # no unit of ours: no restart
    units.mkdir()
    (units / "cicada-backend.service").write_text("ExecStart=\"/elsewhere/api/.venv/bin/python\" -m uvicorn\n")
    assert "service" not in run()                                          # another Cicada's unit: left alone
    (units / "cicada-backend.service").write_text(f'ExecStart="{repo}/api/.venv/bin/python" -m uvicorn\n')
    assert run()[-1] == "service"                                          # ours, already up: restarted
    assert "service" not in run("--uninstall")


def test_a_ref_older_than_the_server_install_is_named(world, tmp_path):
    src = world["src"]
    _git("checkout", "-q", "-b", "ancient", "v0.3.1", cwd=src)
    (src / "scripts" / "sync-server-env.sh").unlink()
    _commit(src, "0.2.0", "v0.2.0")
    _git("push", "-q", str(world["served"]), "ancient", "--tags", cwd=src)
    done = _run(world["env"], CICADA_REF="v0.2.0")
    assert done.returncode == 1
    assert "older than the server install" in done.stderr
    assert not any(c.startswith("install.sh") for c in _calls(world))


def test_check_version_holds_the_formula_tag_to_version(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("check_version", ROOT / "scripts" / "release" / "check_version.py")
    cv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cv)
    (tmp_path / "api").mkdir()
    (tmp_path / "VERSION").write_text("0.4.0\n")
    (tmp_path / "api" / "pyproject.toml").write_text('[project]\nname = "cicada-api"\nversion = "0.4.0"\n')
    (tmp_path / "api" / "uv.lock").write_text('[[package]]\nname = "cicada-api"\nversion = "0.4.0"\n')
    assert cv.agree(tmp_path) == "0.4.0"                       # no formula: nothing to hold
    (tmp_path / "Formula").mkdir()
    formula = tmp_path / "Formula" / "cicada.rb"
    formula.write_text(FORMULA.read_text().replace(f'tag: "v{(ROOT / "VERSION").read_text().strip()}"',
                                                   'tag: "v0.4.0"'))
    assert cv.agree(tmp_path) == "0.4.0"
    formula.write_text(formula.read_text().replace('tag: "v0.4.0"', 'tag: "v0.3.9"'))
    with pytest.raises(cv.VersionError, match="Formula/cicada.rb"):
        cv.agree(tmp_path)
