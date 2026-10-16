"""G177 — a refusal because Sleep holds the pages carries a stable code beside its sentence.

The app tells "Sleep is running" from every other 409 by `code == "sleep_writing"`, never by searching the body:
a claims-block 409 can name a page whose id says "sleep". `detail` stays a string for older clients."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api import config, main
from api.services import sleep_cycle, sleep_refusal

API = Path(__file__).resolve().parents[1]
SCANNED = [API / "routers", API / "services"]


@pytest.fixture
def client(tmp_path, monkeypatch):
    (tmp_path / "episodes").mkdir()
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    config.get_settings.cache_clear()
    with TestClient(main.app) as c:
        yield c
    config.get_settings.cache_clear()


def test_a_guarded_route_answers_the_code_and_the_sentence(client, monkeypatch):
    monkeypatch.setattr(sleep_cycle, "is_writing", lambda: True)
    r = client.put("/memory/decay-tuning", json={"project": 1.5})
    assert r.status_code == 409
    body = r.json()
    assert body["code"] == "sleep_writing"
    assert isinstance(body["detail"], str) and body["detail"], "detail stays the person's sentence, a plain string"


def test_the_exception_is_still_an_http_exception_with_a_string_detail():
    exc = sleep_refusal.SleepWriting("Sleep is running — try again when it finishes")
    assert isinstance(exc, HTTPException) and exc.status_code == 409
    assert exc.detail == "Sleep is running — try again when it finishes", "direct callers read .detail as before"


def test_another_conflict_carries_no_code(client, monkeypatch):
    monkeypatch.setattr(sleep_cycle, "is_writing", lambda: False)

    @main.app.get("/__test_conflict_sleep_study")
    async def _conflict():
        raise HTTPException(409, "claims block on sleep-study will not parse")

    try:
        body = client.get("/__test_conflict_sleep_study").json()
    finally:
        main.app.router.routes = [r for r in main.app.router.routes
                                  if getattr(r, "path", "") != "/__test_conflict_sleep_study"]
    assert "code" not in body and body["detail"] == "claims block on sleep-study will not parse"


def _raises_plain_409_under_is_writing(tree: ast.AST) -> list[int]:
    """Line numbers of `if …is_writing()…: raise HTTPException(409, …)` — the shape every guard must not keep."""
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If) or "is_writing" not in ast.unparse(node.test):
            continue
        for stmt in node.body:
            if isinstance(stmt, ast.Raise) and isinstance(stmt.exc, ast.Call) \
                    and ast.unparse(stmt.exc.func).endswith("HTTPException"):
                bad.append(stmt.lineno)
    return bad


def test_every_guard_raises_the_shared_refusal():
    """Routers and services alike (re-review finding 4: the inbox's two checks live in `inbox_service`)."""
    offenders = {}
    for path in sorted(p for d in SCANNED for p in d.rglob("*.py")):
        lines = _raises_plain_409_under_is_writing(ast.parse(path.read_text()))
        if lines:
            offenders[str(path.relative_to(API))] = lines
    assert offenders == {}, "a Sleep-window refusal must raise `sleep_refusal.SleepWriting` (its code is the contract)"
