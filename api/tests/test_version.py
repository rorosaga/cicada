"""G182 — one VERSION file at the repo root, read by every surface that reports a version.

`bundle.sh` stamps it as the app's `CFBundleShortVersionString`; the API reports it as
FastAPI's `app.version` (so `/healthz`) and the MCP server as `serverInfo.version`.
`make release` bumps the file and `api/pyproject.toml` together.
"""
from __future__ import annotations

import importlib.util
import re
import tomllib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.version import UNKNOWN, VERSION_FILE, __version__, read_version

REPO_ROOT = Path(__file__).resolve().parents[2]
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def test_the_version_file_is_plain_semver_at_the_repo_root():
    assert VERSION_FILE == REPO_ROOT / "VERSION"
    text = VERSION_FILE.read_text(encoding="utf-8")
    assert text.endswith("\n") and text.count("\n") == 1, "one line, newline-terminated"
    assert SEMVER.match(text.strip())
    assert __version__ == text.strip()


def test_pyproject_carries_the_same_version():
    project = tomllib.loads((REPO_ROOT / "api" / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["version"] == __version__


def test_a_missing_or_malformed_file_reads_unknown_never_raises(tmp_path):
    assert read_version(tmp_path / "nope") == UNKNOWN
    bad = tmp_path / "VERSION"
    bad.write_text("not a version\n", encoding="utf-8")
    assert read_version(bad) == UNKNOWN
    bad.write_text("1.2.3-rc.1\n", encoding="utf-8")
    assert read_version(bad) == "1.2.3-rc.1"


def test_healthz_reports_the_version(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path / "memory"))
    monkeypatch.setenv("CICADA_API_AUTH", "off")
    config.get_settings.cache_clear()
    try:
        with TestClient(main.app) as client:
            assert client.get("/healthz").json()["version"] == __version__
    finally:
        config.get_settings.cache_clear()
    assert main.app.version == __version__


def test_mcp_server_info_reports_the_version():
    spec = importlib.util.spec_from_file_location("cicada_mcp_server_version", REPO_ROOT / "mcp" / "server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = (REPO_ROOT / "mcp" / "server.py").read_text(encoding="utf-8")
    assert '"version": __version__}' in source
    assert module.__version__ == __version__


@pytest.mark.parametrize("literal", ["<string>0.2</string>", '"0.1.0"'])
def test_no_surface_hardcodes_an_old_version(literal):
    for path in [REPO_ROOT / "app" / "CicadaApp" / "bundle.sh", REPO_ROOT / "api" / "main.py",
                 REPO_ROOT / "mcp" / "server.py"]:
        assert literal not in path.read_text(encoding="utf-8"), path


def test_bundle_sh_stamps_the_version_and_a_distinct_build_number():
    text = (REPO_ROOT / "app" / "CicadaApp" / "bundle.sh").read_text(encoding="utf-8")
    assert 'VERSION_FILE="$(cd ../.. && pwd)/VERSION"' in text
    assert "plutil -replace CFBundleShortVersionString -string \"$APP_VERSION\"" in text
    assert "plutil -replace CFBundleVersion -string \"$BUILD_NUMBER\"" in text
    assert 'BUILD_NUMBER="${CICADA_BUILD_NUMBER:-$(git rev-list --count HEAD' in text
