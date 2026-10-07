"""G180 — the CLI's one bootstrap (PLAN §3.3, closing critic blocker B3 and round-2 R2-B1).

One root, resolved as one field with one precedence, canonicalised once and published to
both the pin and every `get_settings()`; `Settings` reads no dotenv file (not the
caller's project `.env`, not one in `CICADA_HOME`); litellm's import-time dotenv load is
off; the backend's `/healthz` is a cross-check with four honest outcomes."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from _cli import cli_env, envelope, health_server, run_cli
from _synthetic_bank import _bank


@pytest.fixture
def inprocess(monkeypatch):
    from api.config import Settings, get_settings

    before = Settings.model_config.get("env_file")
    yield
    Settings.model_config["env_file"] = before
    get_settings.cache_clear()


# --- root precedence (pure) ---------------------------------------------------------------------

@pytest.mark.parametrize("environ, file_values, expected", [
    ({"CICADA_MEMORY_PATH": "/a"}, {"CICADA_MEMORY_PATH": "/f"}, ("/a", "env")),
    ({"CICADA_MEMORY_ROOT": "/r"}, {"CICADA_MEMORY_PATH": "/f"}, ("/r", "env")),   # caller ROOT beats file PATH
    ({"CICADA_MEMORY_PATH": "/a", "CICADA_MEMORY_ROOT": "/r"}, {}, ("/a", "env")),  # Settings' own alias order
    ({}, {"CICADA_MEMORY_ROOT": "/fr", "CICADA_MEMORY_PATH": "/fp"}, ("/fp", "checkout-env")),
    ({}, {"CICADA_MEMORY_ROOT": "/fr"}, ("/fr", "checkout-env")),
    ({"CICADA_MEMORY_PATH": "  "}, {}, ("~/cicada/memory", "default")),          # empty values are skipped
    ({}, {}, ("~/cicada/memory", "default")),
])
def test_root_precedence_is_one_field(environ, file_values, expected):
    from api import cli

    raw, source = cli.resolve_root(environ, file_values)
    assert (raw, source) == expected


# --- the process-wide effects -----------------------------------------------------------------

def _registry(root: Path, active: str) -> None:
    from api.services import bank_registry

    reg = bank_registry.load_registry(root)
    reg["active"] = active
    bank_registry.save_registry(root, reg)


def test_symlinked_root_keeps_settings_and_the_pin_on_one_bank(tmp_path, monkeypatch, inprocess):
    from api import cli
    from api.config import get_settings
    from api.services import bank_registry

    real = tmp_path / "real-root"
    real.mkdir()
    bank_registry.create_bank(real, "alpha", seed_owner=False)
    bank_registry.create_bank(real, "beta", seed_owner=False)
    _registry(real, "alpha")
    link = tmp_path / "link-root"
    link.symlink_to(real)
    environ = {"CICADA_MEMORY_PATH": str(link), "CICADA_HOME": str(tmp_path / "home"), "HOME": str(tmp_path)}
    monkeypatch.setattr(os, "environ", environ)

    boot = cli.bootstrap(environ)
    try:
        assert boot.root == real.resolve() and boot.root_source == "env"
        assert environ["CICADA_MEMORY_PATH"] == str(real.resolve()) and "CICADA_MEMORY_ROOT" not in environ
        _registry(real, "beta")                       # the person switches banks mid-command
        assert boot.ctx.run(lambda: get_settings().memory_path) == boot.pin.path
        assert boot.pin.name == "alpha" and boot.pin.path.name == "alpha"
    finally:
        bank_registry.unpin()


def test_bootstrap_forces_litellm_production_and_disables_settings_dotenv(tmp_path, monkeypatch, inprocess):
    from api import cli
    from api.config import Settings, get_settings

    memory = _bank(tmp_path, git=False)
    work = tmp_path / "work"
    work.mkdir()
    (work / ".env").write_text(f"CICADA_MEMORY_PATH={tmp_path / 'hostile'}\nCICADA_EMBEDDING_MODE=openai\n")
    monkeypatch.chdir(work)
    environ = {"CICADA_MEMORY_PATH": str(memory), "LITELLM_MODE": "DEV", "HOME": str(tmp_path),
               "CICADA_HOME": str(tmp_path / "home")}
    monkeypatch.setattr(os, "environ", environ)

    boot = cli.bootstrap(environ)
    assert environ["LITELLM_MODE"] == "PRODUCTION"
    assert Settings.model_config["env_file"] is None
    settings = get_settings()
    assert settings.memory_root == memory.resolve()
    assert settings.embedding_mode == "local"           # the caller's .env was never read
    assert boot.caller_cwd == str(work.resolve()) or Path(boot.caller_cwd).resolve() == work.resolve()


# --- the real entry point: hostile dotenv files and the checkout file ----------------------------

def _status(proc) -> dict:
    return envelope(proc)["data"]


def test_a_hostile_project_env_in_the_cwd_changes_nothing(tmp_path):
    env = cli_env(tmp_path, None)
    work = tmp_path / "project"
    work.mkdir()
    (work / ".env").write_text(f"CICADA_MEMORY_PATH={tmp_path / 'hostile'}\nCICADA_MEMORY_ROOT=/elsewhere\n")
    data = _status(run_cli(["status", "--json"], env, cwd=work))
    expected = Path(env["HOME"]) / "cicada" / "memory"
    assert data["root"]["path"] == os.path.realpath(expected) and data["root"]["source"] == "default"


def test_a_hostile_env_file_in_cicada_home_changes_nothing(tmp_path):
    memory = _bank(tmp_path, git=False)
    env = cli_env(tmp_path, memory)
    home = Path(env["CICADA_HOME"])
    (home / ".env").write_text(f"CICADA_MEMORY_PATH={tmp_path / 'hostile'}\n")
    data = _status(run_cli(["status", "--json"], env, cwd=home))
    assert data["root"]["path"] == os.path.realpath(memory) and data["root"]["source"] == "env"


def test_the_checkout_file_supplies_the_root_and_the_callers_alias_still_wins(tmp_path):
    memory = _bank(tmp_path, git=False)
    other = tmp_path / "other"
    other.mkdir()
    checkout = tmp_path / "checkout"
    (checkout / "api").mkdir(parents=True)
    (checkout / "api" / ".env").write_text(f"CICADA_MEMORY_PATH={memory}\n")
    work = tmp_path / "work"
    work.mkdir()

    env = cli_env(tmp_path, None, CICADA_CHECKOUT=str(checkout))
    data = _status(run_cli(["status", "--json"], env, cwd=work))
    assert data["root"] == {"path": os.path.realpath(memory), "source": "checkout-env", "verified": "backend_down"}
    assert data["distribution"] == "checkout"

    env["CICADA_MEMORY_ROOT"] = str(other)
    data = _status(run_cli(["status", "--json"], env, cwd=work))
    assert data["root"]["path"] == os.path.realpath(other) and data["root"]["source"] == "env"


# --- the /healthz cross-check ----------------------------------------------------------------------

def test_probe_outcomes(tmp_path):
    from _cli import free_port
    from api import cli

    root = tmp_path / "root"
    root.mkdir()
    with health_server(memory_root=str(root)) as port:
        assert cli.probe_backend(f"http://127.0.0.1:{port}", root, timeout=2)["state"] == "confirmed"
    with health_server(memory_root=str(tmp_path / "elsewhere")) as port:
        assert cli.probe_backend(f"http://127.0.0.1:{port}", root, timeout=2)["state"] == "mismatch"
    assert cli.probe_backend(f"http://127.0.0.1:{free_port()}", root, timeout=2)["state"] == "backend_down"
    with health_server(memory_root=str(root), delay=0.6) as port:
        assert cli.probe_backend(f"http://127.0.0.1:{port}", root, timeout=0.2)["state"] == "unverified"
    with health_server(memory_root=str(root), status=500) as port:
        assert cli.probe_backend(f"http://127.0.0.1:{port}", root, timeout=2)["state"] == "unverified"


def test_a_symlinked_backend_root_still_confirms(tmp_path):
    from api import cli

    root = tmp_path / "root"
    root.mkdir()
    link = tmp_path / "link"
    link.symlink_to(root)
    with health_server(memory_root=str(link)) as port:
        assert cli.probe_backend(f"http://127.0.0.1:{port}", root.resolve(), timeout=2)["state"] == "confirmed"


def test_a_read_against_a_mismatched_backend_proceeds_with_a_warning(tmp_path):
    memory = _bank(tmp_path, git=False)
    work = tmp_path / "work"
    work.mkdir()
    with health_server(memory_root=str(tmp_path / "elsewhere")) as port:
        env = cli_env(tmp_path, memory, CICADA_PORT=str(port))
        out = envelope(run_cli(["recall", "alpha", "--json"], env, cwd=work))
        assert out["ok"] is True and "root_mismatch" in out["warnings"]
        status = envelope(run_cli(["status", "--json"], env, cwd=work))["data"]
        assert status["root"]["verified"] == "mismatch" and status["backend"]["state"] == "mismatch"
