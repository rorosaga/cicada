"""F2-back R-B15 — a tunnel installed the normal way is found under launchd's
bare PATH. Detection only: nothing is started, stopped or configured (G135)."""
from __future__ import annotations

from types import SimpleNamespace

from api.remote import reach


def _tool(folder, name, *, executable=True):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    if executable:
        path.chmod(0o755)
    return path


def _stopped(argv, **kw):
    return SimpleNamespace(returncode=1, stdout="", stderr="")


def _bare(monkeypatch, tmp_path, dirs):
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setattr(reach, "TUNNEL_BIN_DIRS", tuple(dirs))
    monkeypatch.setattr(reach, "TAILSCALE_APP_CLI", str(tmp_path / "no-app" / "Tailscale"))


def test_the_standard_folders_are_the_ones_installers_use():
    assert reach.TUNNEL_BIN_DIRS == ("/opt/homebrew/bin", "/usr/local/bin", "~/bin", "~/.local/bin")


def test_ngrok_under_a_bare_path_is_found_in_a_standard_folder(tmp_path, monkeypatch):
    brew = tmp_path / "brew-bin"
    _tool(brew, "ngrok")
    _bare(monkeypatch, tmp_path, [str(brew)])
    found = reach.detect(8765, run=_stopped)
    assert found.ngrok is True and found.tailscale == "missing"


def test_tailscale_from_a_standard_folder_is_asked_for_its_funnel_and_nothing_else(tmp_path, monkeypatch):
    local = tmp_path / "local-bin"
    cli = _tool(local, "tailscale")
    _bare(monkeypatch, tmp_path, [str(local)])
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout="{}", stderr="")

    found = reach.detect(8765, run=run)
    assert calls == [[str(cli), "funnel", "status", "--json"]]
    assert (found.tailscale, found.ngrok) == ("no-funnel", False)


def test_a_home_bin_is_searched_with_the_tilde_expanded(tmp_path, monkeypatch):
    _tool(tmp_path / "bin", "ngrok")
    _bare(monkeypatch, tmp_path, ["~/bin"])
    monkeypatch.setenv("HOME", str(tmp_path))
    assert reach.detect(8765, run=_stopped).ngrok is True


def test_a_file_that_is_not_executable_is_not_a_tool(tmp_path, monkeypatch):
    brew = tmp_path / "brew-bin"
    _tool(brew, "ngrok", executable=False)
    _bare(monkeypatch, tmp_path, [str(brew)])
    assert reach.detect(8765, run=_stopped).ngrok is False
