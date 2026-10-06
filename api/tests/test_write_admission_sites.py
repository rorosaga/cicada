"""G183 — every guarded writer asks "is Sleep holding the pages?" inside the bank's write admission.

Two halves: the agent surfaces (a stdio tool and the remote runtime) are shown holding admission from their probe
through their commit, and a lint keeps every other module off the bare predicate — `sleep_cycle.is_writing()` is
read only through `write_admission`, and the stale-answer `write_admission.probe()` only where no page is written
under it (each site says why).
"""
from __future__ import annotations

import ast
import time
from pathlib import Path

import pytest

from _stdio_server import stdio_server
from _synthetic_bank import _bank
from api import config
from api.remote import catalog
from api.remote.runtime import BUSY_TEXT, RemoteRuntime
from api.services import agent_commits, mcp_tools, write_admission

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def server(tmp_path, monkeypatch):
    srv = stdio_server()
    memory = _bank(tmp_path)
    monkeypatch.setattr(srv, "get_memory_path", lambda: memory)
    monkeypatch.setattr(srv, "SESSION", srv.SessionIdentity("ses_2026-10-06_c0ffee00", "claude-code", None))
    return srv, memory


def test_a_stdio_claim_holds_admission_from_its_probe_through_its_commit(server, monkeypatch):
    srv, memory = server
    seen: dict[str, int] = {}
    monkeypatch.setattr(mcp_tools, "_backend_sleep_running",
                        lambda url, headers: seen.setdefault("probe", write_admission.holders(memory)) and False)
    real = agent_commits.commit_write

    def commit(memory_path, **kw):
        seen["commit"] = write_admission.holders(memory)
        return real(memory_path, **kw)

    monkeypatch.setattr(agent_commits, "commit_write", commit)
    out = srv.handle_write_claim("alpha-project", "uses", "sqlite-vec", None, None, None, None)
    assert out.startswith("Recorded")
    assert seen == {"probe": 1, "commit": 1}
    assert write_admission.holders(memory) == 0


def test_a_stdio_backlog_item_asks_sleep_inside_admission(server, monkeypatch):
    srv, memory = server
    seen = []
    monkeypatch.setattr(mcp_tools, "_backend_sleep_running",
                        lambda url, headers: seen.append(write_admission.holders(memory)) or True)
    ctx = mcp_tools.ToolContext(memory_path=lambda: memory, session_id="ses_2026-10-06_c0ffee00",
                                harness="claude-code")
    out = mcp_tools.add_backlog_item(ctx, "alpha-project", "An idea", "the reasoning")
    assert out == mcp_tools.BACKLOG_SLEEPING
    assert seen == [1]


def test_a_remote_write_answers_busy_inside_admission(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    seen = []
    try:
        runtime = RemoteRuntime(post=lambda p, d: {},
                                sleep_running=lambda: seen.append(write_admission.holders(memory)) or True)
        connector = catalog.Connector(id="ab12cd34", label="Phone", app="claude", scopes=catalog.DEFAULT_SCOPES,
                                      created_at="2026-09-01T00:00:00+00:00", last_client="claude-ai")
        assert runtime.call(connector, "cicada_save_episode", {"content": "x"}) == (BUSY_TEXT, "busy")
        assert seen == [1]
        assert write_admission.holders(memory) == 0
    finally:
        config.get_settings.cache_clear()


# --- The lint ------------------------------------------------------------------------------------------------------

#: The only modules that may read `sleep_cycle.is_writing` itself: its home, the admission that wraps it, and the
#: status route that serves it as `writing` (the stdio probe's answer — read inside the caller's own admission).
IS_WRITING_HOMES = {
    "api/services/sleep_cycle.py",
    "api/services/write_admission.py",
    "api/routers/sleep.py",
}

#: Where a stale answer is enough — nothing below writes a page on it.
PROBE_SITES = {
    "api/routers/maintenance.py": "the dedup sweep's and the long networked jobs' early 409s (each merge admits "
                                  "itself; enrich-links and verify-sites are disclosed), and the derived search index",
    "api/routers/embeddings.py": "the search model choice — a derived index, never a page",
    "api/routers/videos.py": "the video queue's lease judgement — the queue lives outside every bank",
    "api/services/video_queue.py": "the same lease judgement and the sync stamp",
    "api/services/inbox_service.py": "the early 409 before an answer's model call; the admitted write asks again",
    "api/services/paper_metadata.py": "a long networked run's stop check; its writes are left to the tail (disclosed)",
}


def _sources():
    for base in ("api", "mcp"):
        for path in sorted((ROOT / base).rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            if "/tests/" in rel or "/.venv/" in rel or rel.startswith("api/.venv"):
                continue
            yield rel, ast.parse(path.read_text(), filename=rel)


def _attribute_uses(tree, name: str):
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == name:
            yield node
        elif isinstance(node, ast.ImportFrom) and any(a.name == name for a in node.names):
            yield node


def test_only_the_admission_reads_the_sleep_predicate():
    offenders = sorted({rel for rel, tree in _sources()
                        if any(_attribute_uses(tree, "is_writing")) and rel not in IS_WRITING_HOMES})
    assert offenders == [], ("a writer must ask through write_admission.admitted()/shared() + holding(), "
                             f"held through its commit (G183): {offenders}")


def test_the_stale_probe_is_used_only_where_no_page_rides_on_it():
    sites = sorted({rel for rel, tree in _sources()
                    if any(isinstance(n, ast.Attribute) and n.attr == "probe"
                           and isinstance(n.value, ast.Name) and n.value.id == "write_admission"
                           for n in ast.walk(tree))})
    assert sorted(set(sites) - set(PROBE_SITES)) == [], "a new probe site: use admitted() or add it here with why"
    assert sorted(set(PROBE_SITES) - set(sites)) == [], "a stale allowlist entry"


def test_the_lint_catches_a_bare_check():
    tree = ast.parse("from api.services import sleep_cycle\nif sleep_cycle.is_writing():\n    pass\n")
    assert any(_attribute_uses(tree, "is_writing"))


# --- Fix round 1, finding 4: a remote write admits, gates and writes ONE bank -----------------------------------------


def _two_banks(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    return _bank(a), _bank(b)


def _connector():
    return catalog.Connector(id="ab12cd34", label="Phone", app="claude", scopes=catalog.DEFAULT_SCOPES,
                             created_at="2026-09-01T00:00:00+00:00", last_client="claude-ai")


def test_a_remote_write_lands_in_the_bank_it_was_admitted_on(tmp_path, monkeypatch):
    import threading

    bank_a, bank_b = _two_banks(tmp_path)
    active = {"bank": bank_a}
    runtime = RemoteRuntime(memory_path=lambda: active["bank"], post=lambda p, d: {},
                            sleep_running=write_admission.holding)
    monkeypatch.setattr(mcp_tools, "_backend_sleep_running", lambda url, headers: False)
    result: dict = {}
    # Another remote write holds the runtime's write lock: this call is admitted and gated on A, then waits.
    runtime._write_lock.acquire()
    t = threading.Thread(target=lambda: result.update(out=runtime.call(
        _connector(), "cicada_add_backlog_item",
        {"project": "alpha-project", "title": "An idea", "description": "the reasoning"})))
    t.start()
    try:
        deadline = time.monotonic() + 10
        while write_admission.holders(bank_a) == 0:
            assert time.monotonic() < deadline
            time.sleep(0.01)
        active["bank"] = bank_b                                   # the person switches banks meanwhile
        assert write_admission.wait_for_writers(bank_b, give_up_after=1) is True, "B has no holder: Sleep may open"
    finally:
        runtime._write_lock.release()
    t.join(10)
    assert result["out"][1] == "ok", result
    assert list((bank_a / "backlog").rglob("*.md")), "written where it was admitted"
    assert not (bank_b / "backlog").exists(), "never in the bank Sleep may have opened"


# --- Fix round 1, findings 3 and 8: a link save fetches outside admission and writes its page inside -----------------

from api.services import media_ingestor, sleep_cycle


@pytest.fixture
def save_spy(monkeypatch):
    seen: dict[str, list] = {"fetch": [], "write": []}
    bank_of: dict = {}

    async def enrich(url, client, from_bookmark_file=False):
        seen["fetch"].append(write_admission.holders(bank_of["bank"]))
        if bank_of.get("on_fetch"):
            bank_of["on_fetch"]()
        return media_ingestor.MediaMeta(title="Example page", description="", site="example.com", media_type="url")

    real = media_ingestor.write_media_entity

    def write_media_entity(*a, **k):
        seen["write"].append(write_admission.holders(bank_of["bank"]))
        return real(*a, **k)

    monkeypatch.setattr(media_ingestor, "enrich", enrich)
    monkeypatch.setattr(media_ingestor, "write_media_entity", write_media_entity)
    return seen, bank_of


def test_the_save_route_fetches_outside_admission_and_writes_inside(tmp_path, monkeypatch, save_spy):
    from fastapi.testclient import TestClient

    from api import main

    seen, bank_of = save_spy
    memory = bank_of["bank"] = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    try:
        resp = TestClient(main.app).post("/sources/save", json={"url": "https://example.com/a"})
    finally:
        config.get_settings.cache_clear()
    assert resp.status_code == 200, resp.text
    assert seen == {"fetch": [0], "write": [1]}


def test_a_remote_save_fetches_outside_admission_and_writes_inside(tmp_path, monkeypatch, save_spy):
    seen, bank_of = save_spy
    memory = bank_of["bank"] = _bank(tmp_path)
    runtime = RemoteRuntime(memory_path=lambda: memory, post=lambda p, d: {}, sleep_running=write_admission.holding)
    text, status = runtime.call(_connector(), "cicada_save_url", {"url": "https://example.com/a"})
    assert status == "ok", text
    assert seen == {"fetch": [0], "write": [1]}


def test_a_window_opening_during_a_remote_save_fetch_refuses_the_write(tmp_path, monkeypatch, save_spy):
    seen, bank_of = save_spy
    memory = bank_of["bank"] = _bank(tmp_path)
    state = {"writing": False}
    monkeypatch.setattr(sleep_cycle, "is_writing", lambda: state["writing"])

    def open_window():
        state["writing"] = True
        assert write_admission.wait_for_writers(memory, give_up_after=1) is True, "the fetch holds nothing"

    bank_of["on_fetch"] = open_window
    pages = sorted(p.name for p in (memory / "entities").iterdir())
    runtime = RemoteRuntime(memory_path=lambda: memory, post=lambda p, d: {}, sleep_running=write_admission.holding)
    assert runtime.call(_connector(), "cicada_save_url", {"url": "https://example.com/a"}) == (BUSY_TEXT, "busy")
    assert seen["write"] == [] and sorted(p.name for p in (memory / "entities").iterdir()) == pages


def test_a_stdio_save_with_the_backend_down_fetches_outside_admission_and_writes_inside(tmp_path, save_spy):
    seen, bank_of = save_spy
    memory = bank_of["bank"] = _bank(tmp_path)
    ctx = mcp_tools.ToolContext(memory_path=lambda: memory, session_id="ses_2026-10-06_c0ffee00",
                                harness="claude-code", backend_url="http://127.0.0.1:9")
    out = mcp_tools.save_url(ctx, "https://example.com/a", None)
    assert not out.startswith("Error"), out
    assert seen == {"fetch": [0], "write": [1]}


# --- Fix round 1, finding 8: the owner page and the reading ask's save are admitted page writers --------------------


def _client_on(memory, monkeypatch):
    from fastapi.testclient import TestClient

    from api import main

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    return TestClient(main.app)


def test_the_owner_page_write_is_refused_inside_the_window(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    monkeypatch.setattr(sleep_cycle, "is_writing", lambda: True)
    before = sorted(p.name for p in (memory / "entities").iterdir())
    try:
        resp = _client_on(memory, monkeypatch).put("/settings/owner", json={"name": "Alex Example"})
    finally:
        config.get_settings.cache_clear()
    assert resp.status_code == 409, resp.text
    assert sorted(p.name for p in (memory / "entities").iterdir()) == before


def test_the_owner_page_write_holds_admission_through_its_commit(tmp_path, monkeypatch):
    from api.services import git_service

    memory = _bank(tmp_path)
    seen = []
    real = git_service.commit_paths

    async def commit_paths(memory_path, message, paths):
        seen.append(write_admission.holders(memory))
        return await real(memory_path, message, paths)

    monkeypatch.setattr(git_service, "commit_paths", commit_paths)
    try:
        resp = _client_on(memory, monkeypatch).put("/settings/owner", json={"name": "Alex Example"})
    finally:
        config.get_settings.cache_clear()
    assert resp.status_code == 200, resp.text
    assert seen == [1]


def test_a_reading_ask_saves_its_link_inside_admission(tmp_path, monkeypatch):
    from api.services import reading_service

    memory = _bank(tmp_path)
    seen = []
    real = media_ingestor.write_media_entity
    monkeypatch.setattr(media_ingestor, "write_media_entity",
                        lambda *a, **k: seen.append(write_admission.holders(memory)) or real(*a, **k))
    monkeypatch.setattr(reading_service.reading_settings, "agent_enabled", lambda: True)
    from types import SimpleNamespace

    monkeypatch.setattr(reading_service.reading_hosts, "agent_may_read", lambda url, enabled: SimpleNamespace(
        ok=True, cls="open", reason="", host="example.com", host_class="open"))
    import asyncio

    out = asyncio.run(reading_service.ask(memory, "https://example.com/an-article"))
    assert out["saved"] is True
    assert seen == [1]
