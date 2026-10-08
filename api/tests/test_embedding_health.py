"""A failing embedding is visible, not silent (fix/dev-embeddings).

A hosted embedder that runs out of credits used to fail every index step of a whole
consolidation run with a raw HTTP error held only in memory — gone at the next restart —
while recall quietly answered on words alone. Now the failure is classified into one
plain sentence, kept per bank outside every bank (ids and enums only), and shown where the
person looks: the Sleep page's Details (through ``indexWarning``), ``/healthz`` and doctor.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import numpy as np
import pytest
import requests
from fastapi.testclient import TestClient

from api import config, main
from api.services import embedding_health, markdown_parser, sleep_cycle, vector_index

ROOT = Path(__file__).resolve().parents[2]
MODEL = "example/hosted-embedder"


def _http_error(status: int, body: str = "") -> requests.HTTPError:
    resp = requests.Response()
    resp.status_code = status
    resp._content = body.encode()
    resp.url = "https://embed.example.com/v1/embeddings"
    return requests.HTTPError(f"{status} Client Error for url: {resp.url}", response=resp)


class _StatusError(Exception):
    """The shape of an SDK error: a ``status_code`` attribute, no ``response``."""

    def __init__(self, status_code, message=""):
        super().__init__(message)
        self.status_code = status_code


@pytest.mark.parametrize("exc,kind", [
    (_http_error(402), "credits"),
    (_http_error(429, '{"error": {"code": "insufficient_quota"}}'), "credits"),
    (_StatusError(429, "You exceeded your current quota"), "credits"),
    (_http_error(429), "rate_limited"),
    (_StatusError(429), "rate_limited"),
    (_http_error(401), "auth"),
    (_StatusError(403), "auth"),
    (requests.ConnectionError("no route"), "unreachable"),
    (requests.Timeout("slow"), "unreachable"),
    (ModuleNotFoundError("No module named 'sentence_transformers'"), "model_missing"),
    (_http_error(503), "unavailable"),
    (RuntimeError("database is locked"), None),
])
def test_failures_are_classified(exc, kind):
    assert embedding_health.classify(exc) == kind


def test_every_sentence_is_plain_and_provider_neutral():
    for kind in embedding_health.KINDS:
        text = embedding_health.sentence(kind)
        assert text and "http" not in text.lower() and "error" not in text.lower()
        for name in ("openai", "openrouter", "gemini", "google", "ollama", "anthropic", "claude"):
            assert name not in text.lower(), (kind, name)


@pytest.fixture
def bank(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path / "memory"))
    monkeypatch.delenv("CICADA_API_TOKEN", raising=False)
    monkeypatch.setenv("CICADA_API_AUTH", "off")
    config.get_settings.cache_clear()
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "episodes").mkdir(parents=True)
    markdown_parser.write(memory / "episodes" / "ep_2026-06-01_001.md",
                          {"id": "ep_2026-06-01_001", "processed": True, "source": "mcp",
                           "timestamp": "2026-06-01T10:00:00"}, "alpha-project planning")
    markdown_parser.write(memory / "entities" / "alpha-project.md",
                          {"name": "Alpha Project", "type": "project", "status": "active", "confidence": 0.8},
                          "A synthetic project.")
    yield memory
    config.get_settings.cache_clear()
    sleep_cycle._state.index_warning = None


def _embedder(monkeypatch, fn):
    monkeypatch.setattr(vector_index, "_resolve_embed_fn", lambda memory_path=None: (fn, MODEL))


def _out_of_credits(texts, *, is_query=False):
    raise _http_error(402)


def _healthy(texts, *, is_query=False):
    return np.ones((len(texts), 4), dtype=np.float32) / 2


def test_an_out_of_credits_run_says_so_once_and_remembers_it(bank, monkeypatch):
    _embedder(monkeypatch, _out_of_credits)
    warnings = sleep_cycle._sync_vector_indexes(bank)
    assert warnings == [embedding_health.sentence("credits")], "one sentence, not three raw HTTP errors"
    assert "example.com" not in warnings[0]
    problem = embedding_health.problem(bank)
    assert problem["kind"] == "credits" and problem["model"] == MODEL
    stored = (bank.parent / "home" / embedding_health.FILE_NAME).read_text()
    assert "alpha" not in stored and "example.com" not in stored, "ids and enums only"

    _embedder(monkeypatch, _healthy)
    assert sleep_cycle._sync_vector_indexes(bank) == []
    assert embedding_health.problem(bank) is None, "a healthy sync clears it"


def test_an_unrecognised_failure_keeps_its_old_warning(bank, monkeypatch):
    def locked(texts, *, is_query=False):
        raise RuntimeError("database is locked")

    _embedder(monkeypatch, locked)
    warnings = sleep_cycle._sync_vector_indexes(bank)
    assert warnings and all("RuntimeError: database is locked" in w for w in warnings)
    assert embedding_health.problem(bank) is None


def test_the_sleep_page_still_shows_it_after_a_restart(bank, monkeypatch):
    embedding_health.record(bank, MODEL, "credits")
    sleep_cycle._state.index_warning = None           # a fresh process: nothing in memory
    with TestClient(main.app) as client:
        body = client.get("/sleep/status").json()
        health = client.get("/healthz").json()
    assert body["indexWarning"] == embedding_health.sentence("credits")
    assert health["embeddingProblem"] == "credits"


def test_a_failed_query_embed_is_recorded(bank, monkeypatch):
    from api.services import search_service

    _embedder(monkeypatch, _healthy)
    vector_index.SqliteVecIndexer(bank).index_entities()

    def throttled(self, q, want):
        raise _http_error(429)

    monkeypatch.setattr(vector_index.SqliteVecIndexer, "search_kinds", throttled)
    result = search_service.search(bank, "alpha project")
    assert result.mode == "lexical", "search still answers, on words"
    assert embedding_health.problem(bank)["kind"] == "rate_limited"


class _Health(BaseHTTPRequestHandler):
    body = b"{}"

    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *_a):
        pass


def _doctor(tmp_path, health: dict) -> str:
    _Health.body = json.dumps(health).encode()
    server = HTTPServer(("127.0.0.1", 0), _Health)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        env = {**os.environ, "CICADA_PORT": str(server.server_port), "HOME": str(tmp_path),
               "CICADA_HOME": str(tmp_path / "home"), "CICADA_MEMORY_PATH": str(tmp_path / "memory"),
               "CLAUDE_CLI": "cicada-no-such-cli", "CLAUDE_SETTINGS": str(tmp_path / "settings.json")}
        done = subprocess.run(["/bin/bash", str(ROOT / "scripts" / "doctor.sh")], capture_output=True, text=True,
                              env=env, timeout=60)
    finally:
        server.shutdown()
    return re.sub(r"\x1b\[[0-9;]*m", "", done.stdout)


def test_doctor_names_a_failing_embedder(tmp_path):
    out = _doctor(tmp_path, {"status": "ok", "embeddingMode": "openrouter", "embeddingModel": MODEL,
                             "embeddingProblem": "credits"})
    assert "✗ Search embeddings" in out and "out of credits" in out


def test_doctor_passes_a_healthy_embedder(tmp_path):
    out = _doctor(tmp_path, {"status": "ok", "embeddingMode": "local", "embeddingModel": "intfloat/x",
                             "embeddingProblem": None})
    assert "✓ Search embeddings" in out and "intfloat/x" in out


def test_the_missing_model_sentence_fits_where_it_runs():
    checkout = embedding_health.sentence("model_missing", {})
    release = embedding_health.sentence("model_missing", {"CICADA_DISTRIBUTION": "release"})
    assert "make embedding-model" in checkout
    assert "make" not in release and "checkout" not in release and "Settings" in release
