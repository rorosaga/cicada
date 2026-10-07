"""G180 — the `cicada` command's output and error contract, through the real entry point.

`--json` (or `--format json`) prints exactly one envelope on stdout and nothing on
stderr in every outcome — success, usage error, refusal, internal error. Global flags
work before or after the subcommand. Unknown and abbreviated flags are rejected, never
ignored. An internal error names the exception class only."""
from __future__ import annotations

import json

import pytest

from _cli import cli_env, envelope, run_cli
from _synthetic_bank import _bank
from api.version import __version__

KEYS = {"schema", "command", "ok", "code", "bank", "data", "text", "warnings", "version"}


@pytest.fixture
def setup(tmp_path):
    memory = _bank(tmp_path, git=False)
    work = tmp_path / "work"
    work.mkdir()
    return cli_env(tmp_path, memory), work


@pytest.mark.parametrize("args", [["--json", "status"], ["status", "--json"], ["--format", "json", "status"],
                                  ["status", "--format", "json"]])
def test_global_json_flag_works_before_or_after_the_subcommand(setup, args):
    env, work = setup
    proc = run_cli(args, env, cwd=work)
    assert proc.returncode == 0, proc.stderr
    env_ = envelope(proc)
    assert set(env_) == KEYS
    assert env_["schema"] == "cicada.cli/1" and env_["command"] == "status" and env_["ok"] is True
    assert env_["code"] is None and env_["version"] == __version__ and env_["bank"]


@pytest.mark.parametrize("args", [
    ["--json", "status", "--nope"],          # unknown flag
    ["--json", "recall", "alpha", "--quer", "x"],  # unknown (would-be abbreviation)
    ["--js", "status"],                     # abbreviated global flag
    ["--json"],                             # no subcommand
    ["--json", "get", "alpha-project"],     # a command this unit does not expose
    ["--json", "recall"],                   # missing positional
    ["--json", "recall", "   "],            # blank query
    ["--format", "xml", "status"],          # bad format value
])
def test_usage_errors_are_one_envelope_with_exit_2_and_empty_stderr(setup, args):
    env, work = setup
    proc = run_cli(args, env, cwd=work)
    assert proc.returncode == 2
    if "--js" in args or ("--format" in args and "xml" in args):
        # The output mode itself could not be parsed: still JSON-free noise is forbidden — text on stderr.
        assert proc.stdout == "" and proc.stderr.strip()
        return
    env_ = envelope(proc)
    assert env_["ok"] is False and env_["code"] == "usage" and env_["data"] is None


def test_usage_error_in_text_mode_goes_to_stderr(setup):
    env, work = setup
    proc = run_cli(["status", "--nope"], env, cwd=work)
    assert proc.returncode == 2 and proc.stdout == "" and "--nope" in proc.stderr


def test_version_text_and_json(setup):
    env, work = setup
    proc = run_cli(["--version"], env, cwd=work)
    assert proc.returncode == 0 and proc.stdout.strip() == __version__
    env_ = envelope(run_cli(["--json", "--version"], env, cwd=work))
    assert env_["command"] == "version" and env_["data"] == {"version": __version__}


def test_help_lists_only_exposed_commands(setup):
    env, work = setup
    proc = run_cli(["--help"], env, cwd=work)
    assert proc.returncode == 0
    for name in ("recall", "status", "commands"):
        assert name in proc.stdout
    assert "claim add" not in proc.stdout and "inbox" not in proc.stdout


def test_commands_catalog_lives_in_the_envelope(setup):
    from api.services import cli_map

    env, work = setup
    env_ = envelope(run_cli(["commands", "--json"], env, cwd=work))
    assert env_["ok"] is True
    assert env_["data"]["commands"] == json.loads(json.dumps(cli_map.catalog()))
    text = run_cli(["commands"], env, cwd=work).stdout
    assert "recall" in text and "cicada_recall" in text and "claim add" in text


@pytest.fixture
def inprocess(monkeypatch):
    """`cli.main` in this process: restore what bootstrap changes process-wide."""
    from api.config import Settings, get_settings

    before = Settings.model_config.get("env_file")
    monkeypatch.setenv("LITELLM_MODE", "PRODUCTION")
    monkeypatch.delenv("CICADA_MEMORY_ROOT", raising=False)
    yield
    Settings.model_config["env_file"] = before
    get_settings.cache_clear()


def test_internal_error_names_the_class_only(tmp_path, monkeypatch, capsys, inprocess):
    from api import cli

    memory = _bank(tmp_path, git=False)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))

    def boom(*_a, **_k):
        raise RuntimeError("alpha-project private words")

    monkeypatch.setitem(cli.COMMANDS, "status", boom)
    code = cli.main(["--json", "status"])
    out = capsys.readouterr()
    assert code == 70 and out.err == ""
    env_ = json.loads(out.out)
    assert env_["code"] == "internal" and env_["ok"] is False
    assert "RuntimeError" in env_["text"] and "private" not in out.out
