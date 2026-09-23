"""G139 — what Settings → Privacy & data and Advanced can say about the
backend without a value leaving it: the usage ledger's switch, the three
outbound gates, and which env switches are set, by NAME only (R-O21, R-O22)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from api import config, main
from api.services import env_overrides


def _client(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    return TestClient(main.app)


def test_status_reports_the_switches_as_booleans_and_names(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_TELEMETRY", "off")
    monkeypatch.setenv("CICADA_ALLOW_CONNECTOR_FETCH", "off")
    monkeypatch.setenv("CICADA_ALLOW_FEED_FETCH", "1")
    monkeypatch.setenv("CICADA_ALLOW_LOGO_FETCH", "off")
    monkeypatch.setenv("CICADA_LLM_MODE", "byok")
    body = _client(tmp_path, monkeypatch).get("/status").json()
    assert body["telemetry"] == "off"
    assert body["gates"] == {"connectorFetch": False, "feedFetch": True, "logoFetch": False}
    assert "CICADA_LLM_MODE" in body["envOverrides"]
    assert "byok" not in str(body["envOverrides"]), "names only, never values"
    config.get_settings.cache_clear()


def test_env_overrides_reads_presence_not_values():
    env = {"CICADA_API_TOKEN": "secret-value", "PATH": "/usr/bin"}
    names = env_overrides.present(frozenset({"llm_mode"}), environ=env)
    assert names == ["CICADA_LLM_MODE", "CICADA_API_TOKEN"], "KNOWN order, settings-loaded and env-set alike"
    assert all(n.startswith("CICADA_") for n in names)
    assert env_overrides.present(frozenset({"memory_root"}), environ={}) == ["CICADA_MEMORY_PATH"]


def test_unknown_names_are_never_reported():
    assert env_overrides.present(frozenset(), environ={"CICADA_SOMETHING_NEW": "1"}) == []
