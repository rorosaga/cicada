"""The suite can never write under the real home (follow-ups 2026-10-19).

`conftest.py` pins `HOME` and `CICADA_HOME` for the whole process to one session tmp dir before anything is imported,
and each test gets its own `CICADA_HOME` on top. These tests hold that from every angle a write used to escape by —
without ever listing or reading the real `~/.cicada`: they only compare resolved paths.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from api.services import auth, runtime_layout, sleep_local


def _suite_root() -> Path:
    return Path(os.environ["CICADA_SUITE_ROOT"])


def _caller_homes() -> list[Path]:
    return [Path(p) for p in os.environ["CICADA_SUITE_CALLER_HOMES"].split(os.pathsep) if p]


def _assert_isolated(path: Path, *, under: Path) -> None:
    resolved = Path(os.path.realpath(path))
    assert resolved.is_relative_to(Path(os.path.realpath(under))), f"{resolved} is outside {under}"
    for home in _caller_homes():
        real = Path(os.path.realpath(home))
        if _suite_root().is_relative_to(real):
            continue   # a caller's scratch HOME that holds the system tmp dir: the suite root check above decides
        assert not resolved.is_relative_to(real), f"{resolved} resolves under the caller's home {real}"


_MODULE_SETUP_HOME: dict[str, Path] = {}


@pytest.fixture(scope="module")
def _resolved_in_module_setup():
    """A module-scoped fixture runs BEFORE every function fixture — the per-test CICADA_HOME is not set yet. This is
    where the stray `sleep/memory-<hash>/admission.lock` directories came from."""
    _MODULE_SETUP_HOME["auth"] = auth.cicada_home()
    _MODULE_SETUP_HOME["layout"] = runtime_layout.cicada_home()
    _MODULE_SETUP_HOME["home"] = Path.home()
    return _MODULE_SETUP_HOME


def test_the_process_wide_home_is_the_suites_own():
    root = _suite_root()
    assert root.name.startswith("cicada-suite-")
    _assert_isolated(Path(os.environ["HOME"]), under=root)
    _assert_isolated(Path.home(), under=root)


def test_a_test_body_resolves_its_own_tmp_cicada_home(tmp_path):
    _assert_isolated(auth.cicada_home(), under=tmp_path)
    _assert_isolated(runtime_layout.cicada_home(), under=tmp_path)
    _assert_isolated(sleep_local.bank_dir(tmp_path / "memory", create=False), under=tmp_path)


def test_a_module_scoped_fixture_resolves_under_the_suite_root(_resolved_in_module_setup):
    for name, path in _resolved_in_module_setup.items():
        _assert_isolated(path, under=_suite_root())


def test_the_home_default_is_the_suites_when_cicada_home_is_unset(monkeypatch):
    """A test that deletes CICADA_HOME to exercise the `~/.cicada` default lands in the suite's HOME."""
    monkeypatch.delenv("CICADA_HOME", raising=False)
    _assert_isolated(auth.cicada_home(), under=_suite_root())
    _assert_isolated(runtime_layout.cicada_home(), under=_suite_root())
    _assert_isolated(sleep_local.bank_dir(Path("/nonexistent/memory"), create=False), under=_suite_root())


def test_a_child_process_inherits_the_suites_home(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "CICADA_HOME"}   # even a child told nothing of CICADA_HOME
    out = subprocess.run(
        [sys.executable, "-c", "from api.services import runtime_layout; print(runtime_layout.cicada_home())"],
        env=env, capture_output=True, text=True, timeout=60, cwd=str(Path(__file__).resolve().parents[2]),
    )
    assert out.returncode == 0, out.stderr
    _assert_isolated(Path(out.stdout.strip()), under=_suite_root())


def test_after_a_tests_monkeypatch_is_undone_the_suites_home_remains(monkeypatch):
    """What a thread or scheduler job sees once its test's monkeypatch is gone: the session pin, never the real home."""
    monkeypatch.setenv("CICADA_HOME", "/nonexistent-per-test")
    monkeypatch.undo()
    _assert_isolated(Path(os.environ["CICADA_HOME"]), under=_suite_root())
