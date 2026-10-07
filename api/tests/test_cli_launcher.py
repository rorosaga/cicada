"""G180 — `scripts/cicada`, the developer checkout's launcher (never a venv console script, G88).

It resolves its own file symlink chain (relative and absolute links) to find the checkout,
runs the checkout's venv with `-P -m api.cli`, passes `CICADA_CHECKOUT`, and leaves the
caller's working directory alone."""
from __future__ import annotations

import os
import subprocess

from _cli import REPO, cli_env, envelope
from _synthetic_bank import _bank
from api.version import __version__

LAUNCHER = REPO / "scripts" / "cicada"


def _run(cmd, args, env, cwd):
    return subprocess.run([str(cmd), *args], env=env, cwd=str(cwd), capture_output=True, text=True, timeout=120)


def test_the_launcher_is_executable_posix_sh():
    assert os.access(LAUNCHER, os.X_OK)
    assert LAUNCHER.read_text().startswith("#!/bin/sh\n")


def test_a_two_link_chain_resolves_the_checkout_and_keeps_the_cwd(tmp_path):
    memory = _bank(tmp_path, git=False)
    env = cli_env(tmp_path, memory)
    env.pop("PYTHONPATH")
    bindir = tmp_path / "bin dir"          # a space in the path on purpose
    bindir.mkdir()
    hop = tmp_path / "hop"
    hop.mkdir()
    (hop / "cicada").symlink_to(LAUNCHER)                       # absolute link
    (bindir / "cicada").symlink_to(os.path.relpath(hop / "cicada", bindir))   # relative link to a link
    work = tmp_path / "work"
    work.mkdir()

    proc = _run(bindir / "cicada", ["--version"], env, work)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == __version__

    data = envelope(_run(bindir / "cicada", ["status", "--json"], env, work))["data"]
    assert data["distribution"] == "checkout"
    assert data["caller_cwd"] == os.path.realpath(work)
    assert data["root"]["path"] == os.path.realpath(memory)


def test_a_missing_venv_says_how_to_fix_it(tmp_path):
    fake = tmp_path / "checkout"
    (fake / "scripts").mkdir(parents=True)
    (fake / "scripts" / "cicada").write_bytes(LAUNCHER.read_bytes())
    (fake / "scripts" / "cicada").chmod(0o755)
    proc = _run(fake / "scripts" / "cicada", ["--version"], {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}, tmp_path)
    assert proc.returncode == 127 and "install.sh" in proc.stderr
