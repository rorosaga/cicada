"""The backend runs under launchd with a bare PATH; vendor CLIs must still be found."""
from __future__ import annotations

import os
import stat

from api.services.connections import base


def _fake_cli(dirpath, name="claude"):
    dirpath.mkdir(parents=True, exist_ok=True)
    p = dirpath / name
    p.write_text("#!/bin/sh\necho '{\"loggedIn\": true}'\n")
    p.chmod(p.stat().st_mode | stat.S_IXUSR)
    return p


def test_resolve_binary_falls_back_to_local_bin_when_path_is_bare(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.delenv("CICADA_CLAUDE_CLI", raising=False)
    assert base.resolve_binary("claude") is None
    p = _fake_cli(tmp_path / ".local" / "bin")
    assert base.resolve_binary("claude") == str(p)


def test_env_override_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    p = _fake_cli(tmp_path / "elsewhere", "claude")
    monkeypatch.setenv("CICADA_CLAUDE_CLI", str(p))
    assert base.resolve_binary("claude") == str(p)


def test_argv_head_is_replaced_by_the_resolved_path(tmp_path, monkeypatch):
    # The real runner is guarded by conftest (no test may spawn `claude`), so
    # pin the seam the runner uses instead: argv[0] becomes the absolute path.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.delenv("CICADA_CLAUDE_CLI", raising=False)
    p = _fake_cli(tmp_path / ".local" / "bin")
    assert base._resolve_argv(["claude", "auth", "status", "--json"]) == [str(p), "auth", "status", "--json"]


def test_missing_binary_resolves_to_none(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    assert base._resolve_argv(["definitely-not-a-cli-xyz"]) is None
    assert base.resolve_binary("/nowhere/at/all/claude") is None
