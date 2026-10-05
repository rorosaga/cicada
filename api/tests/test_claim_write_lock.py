"""Audit 2026-10-05 P1-2: two concurrent claim writes must both survive.

`markdown_parser.write` is atomic, so a single write never tears — but a claim
write is read → reconcile → write, and two writers that both read before
either writes each report `written` while the second replaces the first. The
writers are an MCP stdio process and the backend (or two MCP processes), so the
guard must hold across processes, and it must cover the page's commit too.
Synthetic bank only.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

from _stdio_server import stdio_server
from _synthetic_bank import _bank
from api.services import agent_commits, agentic_write, markdown_parser, page_lock
from api.services.claims import parse_claims

REPO = Path(__file__).resolve().parents[2]


def _objects(memory: Path, eid: str = "alpha-project") -> set[str]:
    body = markdown_parser.parse(memory / "entities" / f"{eid}.md").body
    return {c.object for c in parse_claims(body) if c.predicate == "uses"}


def test_two_threads_writing_one_page_both_survive(tmp_path, monkeypatch):
    memory = _bank(tmp_path, git=False)
    real = agentic_write.reconcile_stage3
    # Without a lock both writers read the page before either writes: the
    # barrier releases them together. With one, the second cannot read until
    # the first has written, so the first waits out the barrier alone.
    barrier = threading.Barrier(2, timeout=1.0)

    def slow_reconcile(*a, **k):
        try:
            barrier.wait()
        except threading.BrokenBarrierError:
            pass
        return real(*a, **k)

    monkeypatch.setattr(agentic_write, "reconcile_stage3", slow_reconcile)
    results = []

    def write(obj):
        results.append(agentic_write.write_claim(memory, "alpha-project", "uses", obj, observer="agent"))

    threads = [threading.Thread(target=write, args=(o,)) for o in ("sqlite-vec", "fastapi")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert sorted(r["action"] for r in results) == ["written", "written"]
    assert _objects(memory) == {"sqlite-vec", "fastapi"}


def test_the_lock_holds_across_processes(tmp_path):
    memory = _bank(tmp_path, git=False)
    ready = tmp_path / "ready"
    holder = subprocess.Popen([sys.executable, "-c", textwrap.dedent(f"""
        import time, pathlib
        from api.services import page_lock
        with page_lock.page_lock(pathlib.Path({str(memory)!r})):
            pathlib.Path({str(ready)!r}).write_text("1")
            time.sleep(1.0)
    """)], cwd=str(REPO), env={**os.environ, "PYTHONPATH": str(REPO)})
    try:
        deadline = time.monotonic() + 20
        while not ready.exists():
            assert time.monotonic() < deadline, "the holder never took the lock"
            time.sleep(0.02)
        t0 = time.monotonic()
        out = agentic_write.write_claim(memory, "alpha-project", "uses", "sqlite-vec", observer="agent")
        waited = time.monotonic() - t0
    finally:
        holder.wait(20)
    assert out["action"] == "written"
    assert waited >= 0.5, f"the write did not wait for the other process ({waited:.2f}s)"


def test_the_mcp_write_commits_inside_the_lock(tmp_path, monkeypatch):
    srv = stdio_server()
    memory = _bank(tmp_path)
    monkeypatch.setattr(srv, "get_memory_path", lambda: memory)
    seen = []
    real = agent_commits.commit_write

    def spy(memory_path, **kw):
        seen.append(page_lock.held(memory_path))
        return real(memory_path, **kw)

    monkeypatch.setattr(agent_commits, "commit_write", spy)
    out = srv.handle_write_claim("alpha-project", "uses", "sqlite-vec", None, None, None, None)
    assert out.startswith("Recorded")
    assert seen == [True]
    assert not page_lock.held(memory)


def test_a_retraction_and_a_write_on_one_page_both_survive(tmp_path, monkeypatch):
    memory = _bank(tmp_path, git=False)
    first = agentic_write.write_claim(memory, "alpha-project", "uses", "sqlite-vec", observer="agent",
                                      authored_by="claude-code", origin="mcp")
    real = agentic_write.write_claims
    barrier = threading.Barrier(2, timeout=1.0)

    def slow_write_claims(*a, **k):
        try:
            barrier.wait()
        except threading.BrokenBarrierError:
            pass
        return real(*a, **k)

    monkeypatch.setattr(agentic_write, "write_claims", slow_write_claims)
    out = {}
    t1 = threading.Thread(target=lambda: out.setdefault("r", agentic_write.retract_claim(
        memory, "alpha-project", first["claim_id"], reason="wrong tool", author="claude-code", origin="mcp")))
    t2 = threading.Thread(target=lambda: out.setdefault("w", agentic_write.write_claim(
        memory, "alpha-project", "uses", "fastapi", observer="agent")))
    t1.start(); t2.start(); t1.join(10); t2.join(10)
    assert out["r"]["action"] == "retracted" and out["w"]["action"] == "written"
    claims = parse_claims(markdown_parser.parse(memory / "entities" / "alpha-project.md").body)
    assert any(c.object == "fastapi" for c in claims)
    assert any(c.id == first["claim_id"] and c.valid_to for c in claims)


def test_no_network_call_runs_under_the_lock(tmp_path, monkeypatch):
    """A backend route on the event loop may wait on this lock, so `record_watch`'s
    link save (a loopback POST, then a direct save) and the Sleep probe run outside it."""
    from api.services import mcp_tools

    memory = _bank(tmp_path)
    seen = []
    monkeypatch.setattr(mcp_tools, "save_url", lambda ctx, url, note: seen.append(page_lock.held(memory)) or "Error: x")
    monkeypatch.setattr(mcp_tools, "_backend_sleep_running",
                        lambda url, headers: seen.append(page_lock.held(memory)) or False)
    ctx = mcp_tools.ToolContext(memory_path=lambda: memory, session_id="s", harness="codex")
    assert mcp_tools.record_watch(ctx, "https://example.com/v/1", "a summary").startswith("Error")
    out = mcp_tools.write_claim(ctx, "alpha-project", "uses", "sqlite-vec", None, None, None, None)
    assert out.startswith("Recorded")
    assert seen and not any(seen)


def test_a_merge_holds_the_lock(tmp_path):
    from api.services import entity_merge

    memory = _bank(tmp_path, git=False)
    held = []
    real = entity_merge.repoint_references

    def spy(*a, **k):
        held.append(page_lock.held(memory))
        return real(*a, **k)

    entity_merge.repoint_references, saved = spy, entity_merge.repoint_references
    try:
        entity_merge.merge_entities(memory, loser_id="beta-project", winner_id="alpha-project")
    finally:
        entity_merge.repoint_references = saved
    assert held == [True]
