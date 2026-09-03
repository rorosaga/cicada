"""G60 §2.7 — the MCP surface renders question objects and can resolve them."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def server():
    spec = importlib.util.spec_from_file_location(
        "cicada_mcp_server", REPO_ROOT / "mcp" / "server.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["cicada_mcp_server"] = module
    spec.loader.exec_module(module)
    return module


QUESTION_FM = {
    "kind": "conflict",
    "status": "pending",
    "entity_id": "rodrigo",
    "entity_name": "Rodrigo",
    "title": "Where does Rodrigo work now?",
    "question": "Where does Rodrigo work now?",
    "predicate": "works-at",
    "allow_other": True,
    "allow_defer": True,
    "created_date": "2026-06-18",
    "hint": "You said https://linkedin.example/rodrigo is where to check this",
    "options": [
        {"key": "a", "label": "MongoDB", "observed_at": "2026-02-18",
         "last_referenced": "2026-02-18"},
        {"key": "b", "label": "Supahost", "observed_at": "2026-08-25",
         "last_referenced": "2026-08-25"},
        {"key": "both", "label": "Both are true (different contexts)"},
    ],
}


def test_render_question_lists_keyed_options_with_ages(server):
    out = server.render_question(QUESTION_FM, "Conflicting beliefs.", today="2026-08-30")
    assert "Where does Rodrigo work now?" in out
    assert "a) MongoDB — 6 months ago" in out
    assert "b) Supahost — 5 days ago" in out
    assert "both) Both are true (different contexts)" in out
    assert "Other / Later" in out
    assert "linkedin.example" in out


def test_render_question_falls_back_to_the_body(server):
    fm = {"kind": "clarification", "entity_name": "Franco",
          "uncertainty_type": "who is this", "options": []}
    out = server.render_question(fm, "Who is Franco?", today="2026-08-30")
    assert "Who is Franco?" in out
    assert "Other / Later" not in out  # allow_other/allow_defer are off


def test_check_nudges_hides_deferred_items(server, tmp_path, monkeypatch):
    from api.services import markdown_parser

    memory = tmp_path / "memory"
    (memory / "inbox").mkdir(parents=True)
    markdown_parser.write(memory / "inbox" / "inbox-001.md", dict(QUESTION_FM), "ctx")
    deferred = dict(QUESTION_FM)
    deferred["predicate"] = "uses"
    deferred["remind_after"] = "2099-01-01"
    markdown_parser.write(memory / "inbox" / "inbox-002.md", deferred, "ctx")

    monkeypatch.setattr(server, "get_memory_path", lambda: memory)
    out = server.handle_check_nudges(None)
    assert "inbox-001" in out
    assert "inbox-002" not in out
    assert "Found 1 pending inbox item" in out


def test_resolve_inbox_posts_the_option_key(server, monkeypatch):
    seen = {}

    def fake_post(path: str, payload: dict) -> dict:
        seen["path"] = path
        seen["payload"] = payload
        return {"status": "resolved", "id": "inbox-001"}

    monkeypatch.setattr(server, "_backend_post", fake_post)
    out = server.handle_resolve_inbox("inbox-001", "b", None, False, None)

    assert seen["path"] == "/inbox/inbox-001/resolve"
    assert seen["payload"] == {"action": "resolve", "optionKey": "b"}
    assert "resolved" in out


def test_resolve_inbox_defer_sends_remind_days(server, monkeypatch):
    seen = {}
    monkeypatch.setattr(
        server, "_backend_post",
        lambda path, payload: seen.update(payload) or {"status": "deferred", "remindAfter": "2026-09-29"},
    )
    out = server.handle_resolve_inbox("inbox-001", None, None, True, 30)
    assert seen == {"action": "defer", "remindDays": 30}
    assert "2026-09-29" in out


def test_resolve_inbox_free_text(server, monkeypatch):
    seen = {}
    monkeypatch.setattr(
        server, "_backend_post",
        lambda path, payload: seen.update(payload) or {"status": "resolved"},
    )
    server.handle_resolve_inbox("inbox-001", "neither", "Acme Robotics", False, None)
    assert seen == {"action": "resolve", "optionKey": "neither", "answer": "Acme Robotics"}


def test_resolve_inbox_tool_is_registered(server):
    names = {t["name"] for t in server.TOOLS}
    assert "cicada_resolve_inbox" in names
    tool = next(t for t in server.TOOLS if t["name"] == "cicada_resolve_inbox")
    assert tool["inputSchema"]["required"] == ["id"]
    assert set(tool["inputSchema"]["properties"]) == {
        "id", "option_key", "answer", "defer", "remind_days", "skip",
    }


def test_relevant_inbox_hides_deferred_items(server, tmp_path):
    """L3 — the proactive recall block honours a deferral just like
    `cicada_check_nudges` does: "remind me later" means everywhere.
    """
    from api.services import markdown_parser

    memory = tmp_path / "memory"
    (memory / "inbox").mkdir(parents=True)
    markdown_parser.write(memory / "inbox" / "inbox-001.md", dict(QUESTION_FM), "ctx")
    deferred = dict(QUESTION_FM)
    deferred["remind_after"] = "2099-01-01"
    markdown_parser.write(memory / "inbox" / "inbox-002.md", deferred, "ctx")

    blurbs = server._relevant_inbox(memory, "Rodrigo")
    assert len(blurbs) == 1
    assert all("Rodrigo" in b for b in blurbs)
