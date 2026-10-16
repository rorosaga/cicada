"""Fixed-command observer tests: all real git commands use scratch repos."""
import importlib.util
import os
import subprocess
import sys
import time

import pytest

from test_workspace_continuity import repos  # noqa: F401


def observer():
    spec = importlib.util.spec_from_file_location("b2_workspace_observer", "api/hooks/workspace_identity.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_real_pair_handles_subfolders_and_arbitrary_worktrees(tmp_path, repos):
    mod = observer()
    env = {"HOME": str(tmp_path), "PATH": os.environ["PATH"]}
    values = [mod.observe(str(repos[k]), home=tmp_path, environ=env) for k in ("root", "sub", "worker", "lexical")]
    assert [v["repo_root"] for v in values] == [str(repos[k]) for k in ("root", "root", "worker", "lexical")]
    assert {v["common_dir"] for v in values} == {str(repos["common"])}
    assert len({v["scope_hash"] for v in values}) == 1


def test_clones_nested_repos_submodules_and_separate_git_dir(tmp_path, repos):
    mod = observer()
    clone, nested = tmp_path / "clone", repos["root"] / "nested"
    repos["git"]("clone", repos["root"], clone)
    repos["git"]("init", nested)
    checkout, metadata = tmp_path / "separate", tmp_path / "metadata"
    repos["git"]("init", "--separate-git-dir", metadata, checkout)
    submodule = repos["root"] / "module"
    repos["git"]("-C", repos["root"], "-c", "protocol.file.allow=always", "submodule", "add", clone, submodule)
    env = {"HOME": str(tmp_path), "PATH": os.environ["PATH"]}
    paths = [repos["root"], clone, nested, checkout, submodule]
    values = [mod.observe(str(path), home=tmp_path, environ=env) for path in paths]
    assert len({v["common_dir"] for v in values}) == 5
    assert values[3]["common_dir"] == str(metadata)
    assert [v["repo_root"] for v in values] == list(map(str, paths))


def test_fixed_argv_environment_and_shared_pair_deadline(tmp_path, monkeypatch):
    mod = observer()
    monkeypatch.setattr(mod, "_executable", lambda env: "/synthetic/git")
    calls, now = [], [10.0]

    def run(argv, cwd, env, deadline):
        calls.append((argv, cwd, env, deadline))
        now[0] += 0.04
        return b"/synthetic/common\n" if argv[-1] == "--git-common-dir" else b"/synthetic/root\n"

    env = {"PATH": "/synthetic/bin", "HOME": str(tmp_path), "GIT_DIR": "/wrong", "GIT_WORK_TREE": "/wrong",
           "GIT_COMMON_DIR": "/wrong", "GIT_INDEX_FILE": "/wrong", "GIT_OBJECT_DIRECTORY": "/wrong",
           "GIT_ALTERNATE_OBJECT_DIRECTORIES": "/wrong", "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "x",
           "GIT_CONFIG_VALUE_0": "x", "GIT_CONFIG_PARAMETERS": "x", "SECRET_EXAMPLE": "not inherited"}
    value = mod.observe("/synthetic/root/child;$(example)", home=tmp_path, environ=env, run=run, clock=lambda: now[0])
    assert value["repo_root"] == "/synthetic/root"
    assert len(calls) == 2 and calls[0][3] == calls[1][3] == pytest.approx(10.1)
    for argv, cwd, child_env, _ in calls:
        assert argv[0] == "/synthetic/git" and "core.fsmonitor=false" in argv
        assert "rev-parse" in argv and "--path-format=absolute" in argv
        assert cwd == "/synthetic/root/child;$(example)"
        assert child_env["GIT_OPTIONAL_LOCKS"] == "0" and child_env["GIT_CONFIG_GLOBAL"] == os.devnull
        assert "SECRET_EXAMPLE" not in child_env and "GIT_DIR" not in child_env
        assert not any(k.startswith("GIT_CONFIG_KEY_") or k.startswith("GIT_CONFIG_VALUE_") for k in child_env)


@pytest.mark.parametrize("output", [None, b"relative\n", b"/a\n/b\n", b"/a\x00\n", b"\xff\n", b"/" + b"x" * 4096])
def test_failed_or_malformed_pair_returns_only_hash_and_time(tmp_path, monkeypatch, output):
    mod = observer()
    monkeypatch.setattr(mod, "_executable", lambda env: "/synthetic/git")
    value = mod.observe("/synthetic/root", home=tmp_path, environ={}, run=lambda *args: output)
    assert set(value) == {"cwd_hash", "observed_at"}


def test_absent_git_and_denied_cwd_fall_back(tmp_path, monkeypatch):
    mod = observer()
    monkeypatch.setattr(mod, "_executable", lambda env: None)
    assert "repo_root" not in mod.observe(str(tmp_path), home=tmp_path, environ={})
    monkeypatch.setattr(mod, "_executable", lambda env: sys.executable)
    assert "repo_root" not in mod.observe(str(tmp_path / "missing"), home=tmp_path, environ={})


def test_timeout_kills_and_reaps_real_child(tmp_path):
    mod = observer()
    pid_file = tmp_path / "child.pid"
    argv = [sys.executable, "-c", "import os,time,pathlib; pathlib.Path(__import__('sys').argv[1]).write_text(str(os.getpid())); time.sleep(5)", str(pid_file)]
    started = time.monotonic()
    assert mod._run(argv, str(tmp_path), {}, started + 0.1) is None
    assert time.monotonic() - started < 0.2
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), 0)


def test_output_overflow_is_bounded_and_child_reaped(tmp_path):
    mod = observer()
    assert mod._run([sys.executable, "-c", "print('x'*1000000)"], str(tmp_path), {}, time.monotonic() + 0.1) is None


def test_hint_suppresses_repeat_probe_but_reobserves_cwd_change(tmp_path, monkeypatch):
    mod = observer()
    calls = []
    monkeypatch.setattr(mod, "observe", lambda cwd, **kw: calls.append(cwd) or {
        "cwd_hash": mod._hash(cwd), "observed_at": "2026-10-07T10:00:00+00:00"})
    value = mod.observe_if_needed("/synthetic/alpha", home=tmp_path, environ={}, harness="codex", session_id="session-example", startup=True)
    mod.remember(tmp_path, "codex", "session-example", value)
    assert mod.observe_if_needed("/synthetic/alpha", home=tmp_path, environ={}, harness="codex", session_id="session-example") is None
    mod.observe_if_needed("/synthetic/alpha/child", home=tmp_path, environ={}, harness="codex", session_id="session-example")
    assert calls == ["/synthetic/alpha", "/synthetic/alpha/child"]
    for file in tmp_path.rglob("*.json"):
        assert "/synthetic/alpha" not in file.read_text()


def test_mac_executable_never_uses_developer_tools_shim(monkeypatch):
    mod = observer()
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    checked = []
    monkeypatch.setattr(mod.os, "access", lambda path, mode: checked.append(path) or False)
    assert mod._executable({"PATH": "/usr/bin"}) is None
    assert "/usr/bin/git" not in checked


def test_mac_release_falls_back_to_its_bundled_git(monkeypatch):
    mod = observer()
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    monkeypatch.setattr(mod.os, "access", lambda path, mode: path == "/synthetic/runtime/git/bin/git")
    assert mod._executable({"CICADA_BACKEND_DIR": "/synthetic/runtime"}) == "/synthetic/runtime/git/bin/git"


def test_symlink_hint_directory_never_reads_or_writes_a_bank(tmp_path, monkeypatch):
    mod = observer()
    home, bank = tmp_path / "home", tmp_path / "bank"
    home.mkdir()
    bank.mkdir()
    (home / "continuity-hook-hints").symlink_to(bank, target_is_directory=True)
    path = bank / (mod._hash("codex:session-example") + ".json")
    value = {"cwd_hash": mod._hash("/synthetic/alpha"), "observed_at": "2026-10-07T10:00:00+00:00"}
    import json
    path.write_text(json.dumps(value))
    original = path.read_bytes()
    monkeypatch.setattr(mod, "observe", lambda *a, **k: value)
    assert mod.observe_if_needed("/synthetic/alpha", home=home, environ={}, harness="codex", session_id="session-example") == value
    mod.remember(home, "codex", "session-example", {**value, "observed_at": "2026-10-07T11:00:00+00:00"})
    assert path.read_bytes() == original


def test_hint_home_inside_configured_bank_is_refused(tmp_path, monkeypatch):
    mod = observer()
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path))
    home = tmp_path / "cache"
    mod.remember(home, "codex", "session-example", {
        "cwd_hash": mod._hash("/synthetic/alpha"), "observed_at": "2026-10-07T10:00:00+00:00"})
    assert not home.exists()


@pytest.mark.parametrize("code", ["print('/synthetic/root')", "import time; time.sleep(5)"])
def test_every_child_wait_has_a_deadline(tmp_path, monkeypatch, code):
    mod = observer()
    original = mod.subprocess.Popen

    class BoundedWait(original):
        def wait(self, timeout=None):
            assert timeout is not None, "hook must never perform an unbounded child wait"
            return super().wait(timeout=timeout)

    monkeypatch.setattr(mod.subprocess, "Popen", BoundedWait)
    mod._run([sys.executable, "-c", code], str(tmp_path), {}, time.monotonic() + 0.1)
