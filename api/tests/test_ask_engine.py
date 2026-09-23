"""R-E23 — Ask follows the engine chosen in Settings → Sleep."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import ask_service
from api.services.connections import base, registry as reg_mod
from api.services.connections.base import CliResult


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path / "memory"))
    config.get_settings.cache_clear()
    reg_mod.reset_registry()

    async def fake_run(argv):
        return CliResult(1, "", "not signed in")

    monkeypatch.setattr(base, "run_cli", fake_run)

    async def no_tags(_url):
        raise ConnectionError("no ollama in tests")

    monkeypatch.setattr(reg_mod, "_ollama_fetch_tags", no_tags)
    yield TestClient(main.app)
    reg_mod.reset_registry()
    config.get_settings.cache_clear()


def test_ask_runs_on_the_settings_engine_and_builds_it_only_when_asked(client, monkeypatch):
    assert client.put("/sleep/engine", json={"mode": "local", "model": "qwen3:8b"}).status_code == 200
    built = []

    def fake_default(settings=None):
        built.append((settings.llm_mode, settings.ollama_model))
        return lambda prompt: json.dumps({"answer": "x"})

    monkeypatch.setattr(ask_service, "_default_llm_fn", fake_default)
    calls = []

    def fake_answer(memory_path, query, top_k=6, *, retrieve_fn=None, llm_fn=None):
        calls.append(query)
        if query == "grounded":
            llm_fn("prompt")
        return {"answer": "x", "confidence": 0.5, "citations": [], "gaps": [], "used_entities": []}

    monkeypatch.setattr(ask_service, "answer_query", fake_answer)
    assert client.post("/ask", json={"query": "nothing to ground"}).status_code == 200
    assert built == []                         # the honest-gap path built no engine
    assert client.post("/ask", json={"query": "grounded"}).status_code == 200
    assert built == [("local", "qwen3:8b")]


def test_a_throttle_in_one_ask_never_blocks_the_next(client, monkeypatch):
    """Final review H1: Ask used to run in the shared ``_unscoped`` breaker
    bucket, which nothing resets — one plan throttle made every later Ask fail
    fast until a restart. Each call now gets its own self-purging scope."""
    from api.services import agent_engine

    assert client.put("/sleep/engine", json={"mode": "local", "model": "qwen3:8b"}).status_code == 200
    scopes = []

    def fake_default(settings=None):
        def call(prompt):
            scope = agent_engine.current_scope()
            scopes.append((scope, agent_engine.breaker_reason()))
            agent_engine.trip_breaker("plan throttled")   # what a 429 does in the seam
            return json.dumps({"answer": "x"})
        return call

    monkeypatch.setattr(ask_service, "_default_llm_fn", fake_default)

    def fake_answer(memory_path, query, top_k=6, *, retrieve_fn=None, llm_fn=None):
        llm_fn("prompt")
        return {"answer": "x", "confidence": 0.5, "citations": [], "gaps": [], "used_entities": []}

    monkeypatch.setattr(ask_service, "answer_query", fake_answer)
    for _ in range(2):
        assert client.post("/ask", json={"query": "grounded"}).status_code == 200
    assert [reason for _, reason in scopes] == [None, None]    # the second call was not blocked
    assert all(s.startswith("ask:") for s, _ in scopes) and scopes[0][0] != scopes[1][0]
    assert agent_engine.breaker_reason(scope=agent_engine.DEFAULT_SCOPE) is None
    assert agent_engine.breaker_reason(scope=scopes[0][0]) is None   # purged on exit
