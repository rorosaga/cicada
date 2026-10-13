"""The backend reads the developer checkout's `api/.env` on purpose, wherever it starts.

Before: pydantic's `env_file` was `".env"` relative to the cwd (the launchd backend's cwd is the repo root, where
there is none), and the file reached the backend only through litellm's import-time `load_dotenv()`, which walks up
from litellm's own folder — so it worked only when the virtualenv sat inside `api/`, and nothing could tell a value
from the file apart from one in the environment. These tests pin the deliberate path: the file is found from the
package's own folder, never the cwd; the environment wins; litellm's walk-up load is off; `/status` names where each
setting came from and never a value.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from loguru import logger

from api import config, settings_file

REAL_API = Path(__file__).resolve().parents[1]
SECRET = "sk-test-not-a-real-key-7f3a"
TOKEN = "tok-test-not-a-real-token-91c2"


@pytest.fixture
def enabled(monkeypatch):
    """The suite runs with the settings file off (conftest); these tests turn it back on for themselves."""
    monkeypatch.setattr(settings_file, "_disabled", False)
    monkeypatch.setattr(settings_file, "_sources", None)


# --- the lookup ------------------------------------------------------------------------------------------------------

def test_the_file_is_found_beside_the_package_never_in_the_cwd(enabled, tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("CICADA_PAGE_ARTICLES_ENABLED=true\n")
    monkeypatch.chdir(tmp_path)
    found = settings_file.path(environ={})
    assert found == REAL_API / ".env"
    assert found.is_absolute()
    assert settings_file.path(environ={}, package_dir=tmp_path / "api") == tmp_path / "api" / ".env"


def test_a_release_reads_no_settings_file(enabled):
    assert settings_file.path(environ={"CICADA_DISTRIBUTION": "release"}) is None


def test_disabled_reads_no_settings_file(monkeypatch):
    monkeypatch.setattr(settings_file, "_disabled", True)
    assert settings_file.path(environ={}) is None


# --- load ------------------------------------------------------------------------------------------------------------

def test_load_fills_the_environment_and_the_environment_wins(enabled, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "CICADA_AGENT_MAX_CONCURRENCY=10\n"
        "CICADA_SUMMARY_SYNTHESIS_ENABLED=true\n"
        "CICADA_MEMORY_PATH=/somewhere/else\n"
        f"OPENAI_API_KEY={SECRET}\n"
        "LITELLM_MODE=DEV\n"
        "# a comment\n"
    )
    environ = {"CICADA_MEMORY_PATH": "/from/the/plist", "LITELLM_MODE": "DEV", "CICADA_ALLOW_FEED_FETCH": "1"}
    recorded = settings_file.load(environ=environ, file=env_file)

    assert environ["CICADA_AGENT_MAX_CONCURRENCY"] == "10"
    assert environ["CICADA_SUMMARY_SYNTHESIS_ENABLED"] == "true"
    assert environ["CICADA_MEMORY_PATH"] == "/from/the/plist", "the environment wins over the file"
    assert environ["LITELLM_MODE"] == "PRODUCTION", "litellm's walk-up load stays off whatever the file or env says"
    assert environ["OPENAI_API_KEY"] == SECRET, "parity with litellm's load: a provider key reaches litellm"

    assert recorded.file == settings_file.DISPLAY_NAME
    assert recorded.from_file == ("CICADA_AGENT_MAX_CONCURRENCY", "CICADA_SUMMARY_SYNTHESIS_ENABLED")
    assert recorded.from_environment == ("CICADA_ALLOW_FEED_FETCH", "CICADA_MEMORY_PATH")
    assert recorded.replaced_by_environment == ("CICADA_MEMORY_PATH",)
    assert recorded.other_keys_from_file == 1
    assert SECRET not in repr(recorded) and "/somewhere/else" not in repr(recorded)
    assert settings_file.sources() == recorded


def test_an_equal_value_in_the_environment_is_the_files_own_setting(enabled, tmp_path):
    """The launchd plist copies CICADA_MEMORY_PATH from api/.env: same value, so the file's setting is in effect."""
    env_file = tmp_path / ".env"
    env_file.write_text("CICADA_MEMORY_PATH=/the/bank\nCICADA_LLM_MODE=byok\n")
    environ = {"CICADA_MEMORY_PATH": "/the/bank", "CICADA_LLM_MODE": "agent"}
    recorded = settings_file.load(environ=environ, file=env_file)
    assert recorded.from_file == ("CICADA_MEMORY_PATH",)
    assert recorded.replaced_by_environment == ("CICADA_LLM_MODE",), "only a different value replaces the file's"
    assert environ["CICADA_LLM_MODE"] == "agent"


def test_load_with_no_file_still_turns_litellms_load_off(enabled, tmp_path):
    environ = {"LITELLM_MODE": "DEV"}
    recorded = settings_file.load(environ=environ, file=tmp_path / "missing.env")
    assert environ == {"LITELLM_MODE": "PRODUCTION"}
    assert recorded.file is None and recorded.from_file == ()


def test_the_summary_line_names_and_never_values(enabled, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(f"CICADA_API_TOKEN={TOKEN}\nOPENAI_API_KEY={SECRET}\nCICADA_LLM_MODE=byok\n")
    settings_file.load(environ={"CICADA_LLM_MODE": "agent"}, file=env_file)
    lines: list[str] = []
    sink = logger.add(lines.append, format="{message}")
    try:
        settings_file.log_summary()
    finally:
        logger.remove(sink)
    text = "".join(lines)
    assert "CICADA_API_TOKEN" in text and "CICADA_LLM_MODE" in text
    for value in (TOKEN, SECRET, "byok", "agent"):
        assert value not in text


# --- a real process: the checkout's file, never the cwd's ------------------------------------------------------------

def _checkout(tmp_path: Path, env_text: str) -> Path:
    """A scratch checkout whose `api/` links every real module but carries its own `api/.env`."""
    root = tmp_path / "checkout"
    api = root / "api"
    api.mkdir(parents=True)
    for entry in REAL_API.iterdir():
        if entry.name in {".env", ".venv", "tests", "__pycache__", ".pytest_cache"}:
            continue
        (api / entry.name).symlink_to(entry)
    (api / ".env").write_text(env_text)
    return root


def _run(tmp_path, *, cwd: Path, pythonpath: str, code: str, **extra) -> dict:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {
        "PATH": "/usr/bin:/bin", "HOME": str(home), "CICADA_HOME": str(tmp_path / "cicada-home"),
        "CICADA_MEMORY_PATH": str(tmp_path / "memory"), "PYTHONPATH": pythonpath,
        "CICADA_ALLOW_LOGO_FETCH": "off", "CICADA_ALLOW_CONNECTOR_FETCH": "off", "LITELLM_MODE": "PRODUCTION",
        **extra,
    }
    script = tmp_path / "probe.py"
    script.write_text(code)
    done = subprocess.run([sys.executable, str(script)], cwd=cwd, env=env, capture_output=True, text=True,
                          timeout=180)
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


_BACKEND_PROBE = """
import json, os
import api.main  # the backend's entry, as `python -m uvicorn api.main:app` imports it
from api.config import get_settings
from api import settings_file
s = get_settings()
src = settings_file.sources()
print(json.dumps({
    "synthesis": s.summary_synthesis_enabled, "articles": s.page_articles_enabled,
    "concurrency": s.agent_max_concurrency, "resolve": s.sleep_resolve_concurrency,
    "file": src.file, "from_file": list(src.from_file), "replaced": list(src.replaced_by_environment),
    "key_in_environ": "FAKE_PROVIDER_API_KEY" in os.environ,
}))
"""

_FILE = (
    "CICADA_SUMMARY_SYNTHESIS_ENABLED=true\n"
    "CICADA_PAGE_ARTICLES_ENABLED=true\n"
    "CICADA_AGENT_MAX_CONCURRENCY=10\n"
    "CICADA_SLEEP_RESOLVE_CONCURRENCY=10\n"
    "FAKE_PROVIDER_API_KEY=not-a-real-key\n"
)


def test_a_backend_started_at_the_repo_root_reads_the_checkouts_settings_file(tmp_path):
    root = _checkout(tmp_path, _FILE)
    out = _run(tmp_path, cwd=root, pythonpath=str(root), code=_BACKEND_PROBE)
    assert out["synthesis"] is True and out["articles"] is True
    assert out["concurrency"] == 10 and out["resolve"] == 10
    assert out["file"] == "api/.env"
    assert "CICADA_AGENT_MAX_CONCURRENCY" in out["from_file"]
    assert out["key_in_environ"] is True, "the same keys litellm's load put in the environment, no more"


def test_the_environment_wins_over_the_file(tmp_path):
    root = _checkout(tmp_path, _FILE)
    out = _run(tmp_path, cwd=root, pythonpath=str(root), code=_BACKEND_PROBE,
               CICADA_AGENT_MAX_CONCURRENCY="4", CICADA_PAGE_ARTICLES_ENABLED="false")
    assert out["concurrency"] == 4 and out["articles"] is False
    assert out["synthesis"] is True
    assert out["replaced"] == ["CICADA_AGENT_MAX_CONCURRENCY", "CICADA_PAGE_ARTICLES_ENABLED"]


def test_the_app_spawned_developer_backend_reports_the_file_it_copied(tmp_path):
    """`BackendProcess.developerProcess` copies every api/.env key into the child's environment: every one is the file's
    own setting, in effect — never "0 settings read" with all of them replaced."""
    root = _checkout(tmp_path, _FILE)
    copied = dict(line.split("=", 1) for line in _FILE.splitlines())
    out = _run(tmp_path, cwd=root, pythonpath=str(root), code=_BACKEND_PROBE, **copied)
    assert out["from_file"] == ["CICADA_AGENT_MAX_CONCURRENCY", "CICADA_PAGE_ARTICLES_ENABLED",
                                "CICADA_SLEEP_RESOLVE_CONCURRENCY", "CICADA_SUMMARY_SYNTHESIS_ENABLED"]
    assert out["replaced"] == []
    assert out["concurrency"] == 10 and out["synthesis"] is True


def test_an_agent_folders_dotenv_never_steers_settings(tmp_path):
    """An MCP server or hook runs in an agent's project folder and builds `Settings` without the backend's entry."""
    root = _checkout(tmp_path, "CICADA_AGENT_MAX_CONCURRENCY=7\n")
    project = tmp_path / "agent-project"
    project.mkdir()
    (project / ".env").write_text("CICADA_AGENT_MAX_CONCURRENCY=99\nCICADA_PAGE_ARTICLES_ENABLED=true\n")
    code = ("import json\nfrom api.config import Settings\ns = Settings()\n"
            "print(json.dumps({'concurrency': s.agent_max_concurrency, 'articles': s.page_articles_enabled}))\n")
    assert _run(tmp_path, cwd=project, pythonpath=str(root), code=code) == {"concurrency": 7, "articles": False}
    backend = _run(tmp_path, cwd=project, pythonpath=str(root), code=_BACKEND_PROBE)
    assert backend["concurrency"] == 7 and backend["articles"] is False


def test_litellms_walk_up_dotenv_load_is_off_in_the_backend(tmp_path):
    """litellm's `load_dotenv()` walks up from its own folder. A litellm whose walk-up finds a scratch `.env` proves the
    load happens without the backend's entry (the control) and never after it."""
    import litellm

    site = tmp_path / "venv" / "site-packages"
    site.mkdir(parents=True)
    (site / "litellm").symlink_to(Path(litellm.__file__).resolve().parent)
    (tmp_path / "venv" / ".env").write_text("FAKE_WALKUP_KEY=1\nCICADA_PAGE_ARTICLES_ENABLED=true\n")
    root = _checkout(tmp_path, "")
    pythonpath = f"{site}{os.pathsep}{root}"
    control = ("import json, os, litellm\nprint(json.dumps({'loaded': 'FAKE_WALKUP_KEY' in os.environ, "
               "'where': litellm.__file__}))\n")
    seen = _run(tmp_path, cwd=root, pythonpath=pythonpath, code=control, LITELLM_MODE="DEV")
    assert seen["where"].startswith(str(site)) and seen["loaded"] is True, "the control must see the accidental load"

    backend = ("import json, os\nimport api.main\nimport litellm\nfrom api.config import get_settings\n"
               "print(json.dumps({'loaded': 'FAKE_WALKUP_KEY' in os.environ, 'where': litellm.__file__,\n"
               "                  'articles': get_settings().page_articles_enabled}))\n")
    out = _run(tmp_path, cwd=root, pythonpath=pythonpath, code=backend, LITELLM_MODE="DEV")
    assert out["where"].startswith(str(site))
    assert out == {**out, "loaded": False, "articles": False}


# --- /status ---------------------------------------------------------------------------------------------------------

def test_status_names_where_each_setting_came_from_and_never_a_secret(enabled, tmp_path, monkeypatch):
    from api import main

    env_file = tmp_path / ".env"
    env_file.write_text(
        "CICADA_AGENT_MAX_CONCURRENCY=10\nCICADA_PAGE_ARTICLES_ENABLED=true\n"
        f"CICADA_API_TOKEN={TOKEN}\nOPENAI_API_KEY={SECRET}\nCICADA_LLM_MODE=byok\n"
    )
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    environ = {"CICADA_MEMORY_PATH": str(memory), "CICADA_LLM_MODE": "local"}
    settings_file.load(environ=environ, file=env_file)
    for key in ("CICADA_MEMORY_PATH", "CICADA_LLM_MODE", "CICADA_AGENT_MAX_CONCURRENCY",
                "CICADA_PAGE_ARTICLES_ENABLED"):
        monkeypatch.setenv(key, environ[key])
    config.get_settings.cache_clear()
    try:
        response = TestClient(main.app).get("/status")
    finally:
        config.get_settings.cache_clear()
    body = response.json()
    block = body["settings"]
    assert block["file"] == "api/.env"
    assert block["fromFile"] == ["CICADA_AGENT_MAX_CONCURRENCY", "CICADA_API_TOKEN", "CICADA_PAGE_ARTICLES_ENABLED"]
    assert block["fromEnvironment"] == ["CICADA_LLM_MODE", "CICADA_MEMORY_PATH"]
    assert block["replacedByEnvironment"] == ["CICADA_LLM_MODE"]
    assert block["effective"] == {"agentMaxConcurrency": 10, "sleepResolveConcurrency": 3,
                                  "summarySynthesisEnabled": False, "pageArticlesEnabled": True}
    for value in (TOKEN, SECRET, "byok", str(memory)):
        assert value not in response.text
