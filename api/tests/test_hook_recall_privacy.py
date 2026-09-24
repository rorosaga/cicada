"""G149 R-H10 — after a hit, a miss, a primer, an internal failure whose
message carries the prompt and a 422, the prompt appears in NO log (loguru at
DEBUG with diagnose on, the stdlib loggers), no file under CICADA_HOME (ledger,
handshake cache) and no byte under the bank (derived indexes included).
Task 3 appends the hook script's end-to-end round trip (recall.log included),
because `api/hooks/recall.py` does not exist until then."""
from __future__ import annotations

import io
import logging
import os
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient
from loguru import logger

from api import config, main
from api.services import hook_recall, search_index
from test_hook_recall import bank  # noqa: F401

SENTINEL = "zqxsentinel"
PROMPT = f"How is the Alpha Project going? {SENTINEL} {SENTINEL}7f3a"


def _files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*") if p.is_file()]


def test_the_prompt_never_reaches_a_log_the_ledger_or_the_bank(bank, monkeypatch, caplog):  # noqa: F811
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    home = Path(os.environ["CICADA_HOME"])
    sink = io.StringIO()
    handler = logger.add(sink, level="DEBUG", backtrace=True, diagnose=True)
    caplog.set_level(logging.DEBUG)
    try:
        client = TestClient(main.app)
        body = {"event": "user_prompt_submit", "harness": "claude-code", "session_id": "s-priv",
                "cwd": None, "prompt": PROMPT, "model": None}
        assert client.post("/capture/hook-context", json=body).json()["reason"] == "injected"
        assert client.post("/capture/hook-context",
                           json={**body, "prompt": f"{SENTINEL} nothing named"}).json()["reason"] == "no_match"
        client.post("/capture/hook-context", json={**body, "event": "session_start", "prompt": None})

        def fail(self, terms, limit):
            raise sqlite3.OperationalError(f'fts5: syntax error near "{SENTINEL}"')

        monkeypatch.setattr(search_index.Reader, "name_candidates", fail)
        hook_recall.reset()
        assert client.post("/capture/hook-context", json=body).json()["reason"] == "error"
        assert client.post("/capture/hook-context",
                           json={**body, "prompt": "x" * hook_recall.PROMPT_MAX_CHARS + SENTINEL}).status_code == 422
    finally:
        logger.remove(handler)
        config.get_settings.cache_clear()
    assert SENTINEL not in sink.getvalue(), "loguru (diagnose on) saw the prompt"
    assert SENTINEL not in caplog.text, "a stdlib logger saw the prompt"
    written = _files(home)
    assert any(p.name.startswith("reads-") for p in written), "the ledger row was written, so this checked it"
    for path in written + _files(bank):
        assert SENTINEL.encode() not in path.read_bytes(), path
