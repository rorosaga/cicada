"""G180 unit 3 — packaging and the portable usage skill.

- The release app's launcher table, the Swift table and the release build all name `cicada`.
- `scripts/release/write-launchers.sh` (factored out of `build-backend.sh`) writes the real launchers, so a
  synthetic bundle can run `bin/cicada` end to end: the release environment, the caller's working folder kept,
  `-P` (the caller's folder never on `sys.path`).
- `scripts/install-cli.sh` (behind `make cli` / `install.sh --cli`) links `~/.local/bin/cicada` to the checkout's
  launcher with the same rules as the app's Settings button: never replaces a working link or a file.
- `SKILL.md`'s CLI block is generated from the CLI↔MCP table (drift fails), every command in it parses, and the
  MCP instructions kept beside it still name only real tool arguments (R12, both halves).

Every path is under `tmp_path` with a scratch HOME; nothing touches the person's `~/.local/bin` or `~/.cicada`."""
from __future__ import annotations

import os
import re
import shlex
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from _cli import cli_env, envelope
from _stdio_server import stdio_server
from _synthetic_bank import _bank
from api.services import cli_map, runtime_layout
from api.version import __version__

REPO = Path(__file__).resolve().parents[2]
WRITE_LAUNCHERS = REPO / "scripts" / "release" / "write-launchers.sh"
INSTALL_CLI = REPO / "scripts" / "install-cli.sh"
SWIFT_RUNTIME = REPO / "app" / "CicadaApp" / "Sources" / "CicadaApp" / "Support" / "CicadaRuntime.swift"
TICKED = re.compile(r"`(cicada [^`]*)`")


# --- the launcher tables ------------------------------------------------------------------------

def test_every_launcher_table_names_cicada():
    assert "cicada" in runtime_layout.LAUNCHERS
    swift = re.search(r"static let launcherNames = \[([^\]]*)\]", SWIFT_RUNTIME.read_text(encoding="utf-8")).group(1)
    assert [s.strip().strip('"') for s in swift.split(",")] == list(runtime_layout.LAUNCHERS)
    build = (REPO / "scripts" / "release" / "build-backend.sh").read_text(encoding="utf-8")
    assert "write-launchers.sh" in build and 'cat > "$OUT/bin/cicada-mcp"' not in build


# --- the release launcher, run for real in a synthetic bundle -----------------------------------

@pytest.fixture
def bundle_backend(tmp_path):
    """`<bundle>/Contents/Resources/backend` with the real launchers, a `python3.12` that is this venv's
    interpreter, and `app` pointing at this checkout — the release layout `cicada-env` expects."""
    backend = tmp_path / "Cicada Test.app" / "Contents" / "Resources" / "backend"
    (backend / "python" / "bin").mkdir(parents=True)
    proc = subprocess.run(["/bin/bash", str(WRITE_LAUNCHERS), str(backend / "bin")], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    py = backend / "python" / "bin" / "python3.12"
    py.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    py.chmod(0o755)
    (backend / "app").symlink_to(REPO)
    return backend


def test_write_launchers_writes_every_launcher_executable(bundle_backend):
    bindir = bundle_backend / "bin"
    for name in (*runtime_layout.LAUNCHERS, "git"):
        mode = (bindir / name).stat().st_mode
        assert mode & stat.S_IXUSR, name
    assert not (bindir / "cicada-env").stat().st_mode & stat.S_IXUSR
    text = (bindir / "cicada").read_text()
    assert '. "$(dirname "$0")/cicada-env"' in text and '-P -m api.cli "$@"' in text and "\ncd " not in text


def test_the_release_launcher_runs_the_cli_and_keeps_the_callers_folder(tmp_path, bundle_backend):
    memory = _bank(tmp_path, git=False)
    env = cli_env(tmp_path, memory)
    env.pop("PYTHONPATH")
    work = tmp_path / "a project with spaces"
    work.mkdir()
    (work / ".env").write_text(f"CICADA_MEMORY_PATH={tmp_path / 'hostile'}\n")
    launcher = bundle_backend / "bin" / "cicada"
    version = subprocess.run([str(launcher), "--version"], env=env, cwd=str(work), capture_output=True, text=True,
                             timeout=120)
    assert version.returncode == 0, version.stderr
    assert version.stdout.strip() == __version__
    proc = subprocess.run([str(launcher), "status", "--json"], env=env, cwd=str(work), capture_output=True,
                          text=True, timeout=120)
    data = envelope(proc)["data"]
    assert data["distribution"] == "release"
    assert data["caller_cwd"] == os.path.realpath(work)
    assert data["root"]["path"] == os.path.realpath(memory)


# --- install-cli.sh (make cli / install.sh --cli) -----------------------------------------------

def _install(home: Path, *args):
    env = {"PATH": "/usr/bin:/bin", "HOME": str(home)}
    return subprocess.run(["/bin/bash", str(INSTALL_CLI), *args], env=env, capture_output=True, text=True)


def test_install_cli_links_the_checkout_launcher_into_local_bin(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    proc = _install(home)
    assert proc.returncode == 0, proc.stderr
    link = home / ".local" / "bin" / "cicada"
    assert link.is_symlink() and link.resolve() == (REPO / "scripts" / "cicada").resolve()
    again = _install(home)                                   # idempotent
    assert again.returncode == 0 and link.resolve() == (REPO / "scripts" / "cicada").resolve()


def test_install_cli_replaces_only_a_dangling_link(tmp_path):
    home = tmp_path / "home"
    local = home / ".local" / "bin"
    local.mkdir(parents=True)
    (local / "cicada").symlink_to(tmp_path / "gone")
    assert _install(home).returncode == 0
    assert (local / "cicada").resolve() == (REPO / "scripts" / "cicada").resolve()


@pytest.mark.parametrize("kind", ["working-link-elsewhere", "file"])
def test_install_cli_never_replaces_something_that_works_or_is_not_a_link(tmp_path, kind):
    home = tmp_path / "home"
    local = home / ".local" / "bin"
    local.mkdir(parents=True)
    other = tmp_path / "other-cicada"
    other.write_text("#!/bin/sh\necho other\n")
    other.chmod(0o755)
    if kind == "file":
        (local / "cicada").write_text("not ours\n")
    else:
        (local / "cicada").symlink_to(other)
    before = os.readlink(local / "cicada") if kind != "file" else (local / "cicada").read_text()
    proc = _install(home)
    assert proc.returncode != 0 and "left it alone" in proc.stderr
    after = os.readlink(local / "cicada") if kind != "file" else (local / "cicada").read_text()
    assert after == before


# --- the usage skill block ------------------------------------------------------------------------

SKILL = REPO / "SKILL.md"


def _block(text: str) -> str:
    m = re.search(r"<!-- cicada-cli:begin.*?-->\n(.*?)<!-- cicada-cli:end -->", text, re.S)
    assert m, "SKILL.md has no generated CLI block"
    return m.group(1)


def test_the_skill_block_is_generated_from_the_table():
    assert _block(SKILL.read_text(encoding="utf-8")) == cli_map.skill_block(), (
        "SKILL.md's CLI block drifted: rewrite it with "
        "`api/.venv/bin/python -c 'from api.services import cli_map; cli_map.write_skill_block(\"SKILL.md\")'`")


def test_every_command_in_the_skill_block_parses_and_is_held():
    from api import cli

    block = cli_map.skill_block()
    seen = set()
    for span in TICKED.findall(block):
        words = ["x" if re.fullmatch(r"<[^>]+>", w) else w for w in shlex.split(span)]
        try:
            args = cli.build_parser().parse_args(words[1:])
            seen.add(" ".join(w for w in (args.command, getattr(args, "verb", None)) if w))
        except cli._HelpShown:
            pass
    assert seen == {r.name for r in cli_map.exposed()}            # every held command taught, none other
    for word in ("--json", "Exit codes", "${CICADA_HOME:-$HOME/.cicada}/bin/cicada"):
        assert word in block
    for code in ("0", "1", "2", "3", "4", "5", "70"):
        assert re.search(rf"\b{code}\b", block)


def test_the_mcp_half_of_the_skill_still_names_only_real_tool_arguments():
    from test_handshake_r12 import CALL, _args

    schemas = {t["name"]: set(t["inputSchema"].get("properties", {})) for t in stdio_server().TOOLS}
    text = SKILL.read_text(encoding="utf-8")
    outside = text.replace(_block(text), "")
    for tool, arglist in CALL.findall(outside):
        assert tool in schemas, tool
        for arg in _args(arglist):
            assert arg in schemas[tool], (tool, arg)


def test_the_skill_names_no_provider_and_no_owner_path():
    block = cli_map.skill_block()
    for word in ("Claude", "Codex", "ChatGPT", "Ollama", "/Users/"):
        assert word not in block, word


def test_the_cli_primer_still_fits_and_parses(tmp_path):
    from _synthetic_bank import _ok_repo, _settings
    from api.services import handshake, state_dictionary

    memory = _bank(tmp_path, git=False)
    state_dictionary.refresh(memory, _settings(memory), force=True, repo_resolver=_ok_repo)
    text = handshake.build_cli(state_dictionary.read_state(memory),
                               commands=frozenset(r.name for r in cli_map.exposed()), bank="memory")
    assert len(text) // 4 <= handshake.MAX_TOKENS and "cicada_" not in text
    assert "${CICADA_HOME:-$HOME/.cicada}/bin/cicada" in text
