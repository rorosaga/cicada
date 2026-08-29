from __future__ import annotations

import os
import stat

import pytest

from api.services.connections import secrets as sec


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path))
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    return tmp_path


def test_set_secret_writes_0600_and_exports(home):
    sec.set_secret("OPENAI_API_KEY", "sk-test")
    path = home / sec.SECRETS_FILE_NAME
    assert path.read_text() == "OPENAI_API_KEY=sk-test\n"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert os.environ["OPENAI_API_KEY"] == "sk-test"
    assert sec.has_secret("OPENAI_API_KEY")


def test_set_secret_replaces_existing_line(home):
    sec.set_secret("OPENAI_API_KEY", "one")
    sec.set_secret("ANTHROPIC_API_KEY", "two")
    sec.set_secret("OPENAI_API_KEY", "three")
    assert sec.load_secrets() == {"OPENAI_API_KEY": "three", "ANTHROPIC_API_KEY": "two"}
    assert os.environ["OPENAI_API_KEY"] == "three"


def test_remove_secret_drops_line_and_env(home):
    sec.set_secret("OPENAI_API_KEY", "one")
    sec.remove_secret("OPENAI_API_KEY")
    assert sec.load_secrets() == {}
    assert "OPENAI_API_KEY" not in os.environ
    assert not sec.has_secret("OPENAI_API_KEY")


def test_load_does_not_override_shell_export(home, monkeypatch):
    (home / sec.SECRETS_FILE_NAME).write_text("OPENAI_API_KEY=from-file\n")
    monkeypatch.setenv("OPENAI_API_KEY", "from-shell")
    sec.load_secrets()
    assert os.environ["OPENAI_API_KEY"] == "from-shell"
    sec.load_secrets(override=True)
    assert os.environ["OPENAI_API_KEY"] == "from-file"


def test_rejects_bad_names_and_newlines(home):
    with pytest.raises(ValueError):
        sec.set_secret("bad name", "x")
    with pytest.raises(ValueError):
        sec.set_secret("OPENAI_API_KEY", "x\ny")
