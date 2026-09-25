"""G149 R-H1/R-H6/R-H7/R-H9/R-H16 — POST /capture/hook-context over a
synthetic bank: the shape, the session window, the budget, the demo rule and
the ledger row. No real bank, no network."""
from __future__ import annotations

import time

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_registry, hook_recall, recall_text, telemetry
from test_hook_recall import _index, _page, bank  # noqa: F401 — the same synthetic bank

URL = "/capture/hook-context"


def _body(prompt: str | None = "How is the Alpha Project going?", *, event="user_prompt_submit", session="s-1",
          harness="claude-code", model=None):
    return {"event": event, "harness": harness, "session_id": session, "cwd": "/home/example/alpha-project",
            "prompt": prompt, "model": model}


@pytest.fixture(autouse=True)
def _clean():
    hook_recall.reset()
    yield
    hook_recall.reset()
    config.get_settings.cache_clear()


@pytest.fixture
def client(bank, monkeypatch):  # noqa: F811
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    return TestClient(main.app)


def test_a_named_page_comes_back_as_the_note(client):
    r = client.post(URL, json=_body())
    assert r.status_code == 200, r.text
    data = r.json()
    assert set(data) == {"additionalContext", "injected", "reason", "latencyMs"}
    assert data["injected"] == ["alpha-project"] and data["reason"] == "injected"
    assert data["additionalContext"].startswith(recall_text.RECALL_HEADER)
    assert isinstance(data["latencyMs"], int) and data["latencyMs"] >= 0


def test_a_miss_is_null_and_says_why(client):
    data = client.post(URL, json=_body("fix the failing test in the parser")).json()
    assert (data["additionalContext"], data["injected"], data["reason"]) == (None, [], "no_match")


def test_the_window_holds_across_requests_and_session_start_resets_it(client):
    assert client.post(URL, json=_body()).json()["reason"] == "injected"
    assert client.post(URL, json=_body("alpha project budget?")).json()["reason"] == "recently_shown"
    assert client.post(URL, json=_body("alpha project?", session="s-2")).json()["reason"] == "injected"
    start = client.post(URL, json=_body(None, event="session_start")).json()
    assert start["reason"] == "primer" and start["injected"] == []
    assert start["additionalContext"].startswith(recall_text.PRIMER_HEADER)
    assert client.post(URL, json=_body("alpha project")).json()["reason"] == "injected"


def test_past_the_budget_nothing_is_injected_and_the_window_is_untouched(client, monkeypatch):
    real = hook_recall.prompt_context

    def slow(*a, **k):
        time.sleep(0.2)
        return real(*a, **k)

    monkeypatch.setattr(hook_recall, "PROMPT_BUDGET_S", 0.05)
    monkeypatch.setattr(hook_recall, "prompt_context", slow)
    data = client.post(URL, json=_body()).json()
    assert (data["additionalContext"], data["reason"]) == (None, "timeout")
    time.sleep(0.25)  # the worker finishes; its answer must not have aged the window
    monkeypatch.setattr(hook_recall, "prompt_context", real)
    monkeypatch.setattr(hook_recall, "PROMPT_BUDGET_S", 0.3)
    assert client.post(URL, json=_body()).json()["reason"] == "injected"


def test_a_failure_is_an_empty_answer_never_a_500(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("anything")

    monkeypatch.setattr(hook_recall, "prompt_context", boom)
    r = client.post(URL, json=_body())
    assert r.status_code == 200 and r.json()["reason"] == "error" and r.json()["additionalContext"] is None


def test_the_body_is_validated(client):
    assert client.post(URL, json=_body(harness="cursor")).status_code == 422
    assert client.post(URL, json=_body(event="stop")).status_code == 422
    assert client.post(URL, json=_body("x" * (hook_recall.PROMPT_MAX_CHARS + 1))).status_code == 422
    assert client.post(URL, json={**_body(), "session_id": ""}).status_code == 422


def test_the_prompt_can_only_travel_in_the_body():
    (route,) = [r for r in main.app.routes if isinstance(r, APIRoute) and r.path == URL]
    assert route.methods == {"POST"} and route.dependant.query_params == []


def test_the_route_needs_the_bearer_token(bank, monkeypatch, tmp_path):  # noqa: F811
    monkeypatch.setenv("CICADA_API_AUTH", "on")
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    monkeypatch.delenv("CICADA_API_TOKEN", raising=False)
    config.get_settings.cache_clear()
    assert TestClient(main.app).post(URL, json=_body()).status_code == 401


def test_the_demo_is_never_read_and_its_real_twin_is(tmp_path, monkeypatch):
    from test_demo_capture import _client, _demo, _open_demo_without_stamps, _root

    root = _root(tmp_path)
    bank_registry.create_bank(root, "work")
    work = bank_registry.bank_dir(root, "work")
    demo = _demo(root)
    for memory, summary in ((work, "The real one."), (demo, "Made-up demo text.")):
        (memory / "entities").mkdir(parents=True, exist_ok=True)
        _page(memory, "alpha-project", "Alpha Project", "project", summary=summary)
        _index(memory)
    bank_registry.activate_bank(root, "work")
    bank_registry.activate_bank(root, "demo")
    data = _client(root, monkeypatch).post(URL, json=_body()).json()
    assert "The real one." in data["additionalContext"] and "Made-up" not in data["additionalContext"]

    other = tmp_path / "other"
    other.mkdir()
    root2 = _root(other)
    bank_registry.create_bank(root2, "work")
    _demo(root2)
    _open_demo_without_stamps(root2)
    data = _client(root2, monkeypatch).post(URL, json=_body()).json()
    assert (data["additionalContext"], data["reason"]) == (None, "no_bank")


def test_one_ledger_row_per_firing_ids_and_enums_only_filed_beside_reads(client, monkeypatch):
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    client.post(URL, json=_body(model="claude-example-1"))
    client.post(URL, json=_body(None, event="session_start", model="not a model id!"))
    rows = [e for e in telemetry.read_events() if e.kind == telemetry.HOOK_RECALL_KIND]
    assert len(rows) == 2
    first = rows[0]
    assert set(first.refs) == {"harness", "event", "reason", "injected", "entity_ids", "inbox", "tokens",
                               "latency", "model"}
    assert first.refs["entity_ids"] == ["alpha-project"] and first.refs["model"] == "claude-example-1"
    assert rows[1].refs["model"] is None, "only an id-shaped model string is kept"
    assert first.stage == "hook_recall" and first.billing == "free" and first.connection is None
    assert telemetry.HOOK_RECALL_KIND in telemetry.NON_SPEND_KINDS
    month = first.ts[:7]
    assert telemetry.HOOK_RECALL_KIND in telemetry.ledger_file(month, kind="read").read_text()
    events = telemetry.ledger_file(month)
    assert not events.exists() or telemetry.HOOK_RECALL_KIND not in events.read_text(), \
        "R-H9: a hook row must never tick the app's consumption domain (G124 M2)"
