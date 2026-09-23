"""G135 R-R2 / R-R14 — one tool implementation behind a ToolContext; the stdio
server keeps only its transport, its schema and the three never-remote tools."""
from __future__ import annotations

from pathlib import Path

from _stdio_server import stdio_server
from _synthetic_bank import _bank
from api.services import mcp_tools

REPO = Path(__file__).resolve().parents[2]
MOVED = ("recall", "recall_detail", "open_hub", "sources", "write_claim", "get_perspective",
         "check_nudges", "resolve_inbox", "save_episode", "save_url", "ask", "timeline",
         "retract_claim", "record_watch")


def test_every_remote_capable_body_lives_in_mcp_tools():
    for name in MOVED:
        assert callable(getattr(mcp_tools, name)), name


def test_the_never_remote_three_stay_in_the_stdio_server():
    source = (REPO / "api" / "services" / "mcp_tools.py").read_text(encoding="utf-8")
    for needle in ("resolve_repo_context", "mark_episodes_processed", "list_unprocessed_episodes"):
        assert needle not in source, needle
    server = stdio_server()
    for name in ("handle_pending", "handle_mark_processed", "handle_repo_context", "TOOLS"):
        assert hasattr(server, name)


def test_mcp_tools_never_imports_the_sdk():
    source = (REPO / "api" / "services" / "mcp_tools.py").read_text(encoding="utf-8")
    assert "import mcp" not in source and "from mcp" not in source


def test_the_stdio_context_is_rebuilt_from_the_module_globals_on_every_call(monkeypatch, tmp_path):
    server = stdio_server()
    memory = _bank(tmp_path)
    skipped = {"inbox-009"}
    monkeypatch.setattr(server, "SESSION", server.SessionIdentity("ses_ctx_1", "codex", "/tmp/p"))
    monkeypatch.setattr(server, "_SKIPPED_INBOX_IDS", skipped)
    monkeypatch.setattr(server, "get_memory_path", lambda: memory)
    ctx = server._ctx()
    assert (ctx.session_id, ctx.harness, ctx.project_dir) == ("ses_ctx_1", "codex", "/tmp/p")
    assert ctx.skipped_inbox_ids is skipped and ctx.memory_path() == memory
    assert ctx.session_frontmatter() == {"session_id": "ses_ctx_1", "harness": "codex", "project_dir": "/tmp/p"}


def test_a_context_resolves_the_bank_on_every_call(tmp_path):
    first, second = _bank(tmp_path / "a"), _bank(tmp_path / "b")
    (second / "entities" / "only-in-b.md").write_text("---\nname: Only In B\ntype: concept\n---\nB\n")
    banks = iter([first, second])
    ctx = mcp_tools.ToolContext(memory_path=lambda: next(banks), session_id="s", harness="codex")
    assert "not found" in mcp_tools.recall_detail(ctx, "only-in-b")
    assert "Only In B" in mcp_tools.recall_detail(ctx, "only-in-b")
