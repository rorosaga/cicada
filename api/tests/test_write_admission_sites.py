"""G183 — every guarded writer asks "is Sleep holding the pages?" inside the bank's write admission.

Two halves: the agent surfaces (a stdio tool and the remote runtime) are shown holding admission from their probe
through their commit, and a lint keeps every other module off the bare predicate — `sleep_cycle.is_writing()` is
read only through `write_admission`, and the stale-answer `write_admission.probe()` only where no page is written
under it (each site says why).
"""
from __future__ import annotations

import ast
import subprocess
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


# --- Fix round 1, finding 8: the inventory — every route and tool that can write is classified -----------------------
#
# Absence of an `is_writing` reference proves nothing, so every non-GET backend route and every MCP tool is listed
# here with its class and why. An unlisted one fails; a stale entry fails; ADMITTED/HELD/PER_WRITE are checked in the
# code (a `write_admission.route` marker, or `run_admitted(` / `write_admission.shared(` in the named function).

ADMITTED = "admitted: holds the bank's admission through its commit, 409/refusal while Sleep holds the pages"
HELD = "held: holds admission through its commit, never refused (capture-shaped; its answer changes shape inside)"
PER_WRITE = "per-write: each write takes its own admission (no hold across a model call or fetch)"
PROBE = "probe: a stale early answer only — a long networked job; DISCLOSED in storage.md"
INTAKE = ("intake: creates NEW media pages and episodes in a batch with fetches interleaved, not admitted — a page "
          "written inside Sleep's window can ride a batch commit; DISCLOSED in storage.md (follow-up)")
CAPTURE = "capture: episodes and capture sidecars only (Awake, ungated by rail) — never an entity page"
REGISTRY = "registry: one bank file Sleep never reads or rewrites, committed alone"
OUTSIDE = "outside: writes nothing in the bank (settings, credentials, ledger, caches, the video queue)"
SLEEP = "sleep: Sleep's own controls"
BANKS = "banks: bank lifecycle — refused while a run is pinned to its bank"
NONE = "none: reads or computes; writes nothing"

ROUTES: dict[str, tuple[str, str | None]] = {
    "POST /ask": (NONE, None),
    "POST /inbox/{item_id}/resolve": (ADMITTED, "api.services.inbox_service.resolve"),
    "POST /nudges/{nudge_id}/resolve": (ADMITTED, "api.services.inbox_service.resolve"),
    "POST /clarifications/{clarification_id}": (ADMITTED, "api.services.inbox_service.resolve"),
    "POST /entities/{entity_id}/read": (OUTSIDE, None),
    "POST /entities/{entity_id}/picture": (ADMITTED, None),
    "POST /entities/{entity_id}/picture/initials": (ADMITTED, None),
    "DELETE /entities/{entity_id}/picture": (ADMITTED, None),
    "PUT /entities/{entity_id}/decay": (ADMITTED, None),
    "POST /entities/{entity_id}/repos/observed": (OUTSIDE, None),
    "PATCH /entities/{entity_id}/repos": (ADMITTED, None),
    "POST /entities/{entity_id}/sources": (ADMITTED, None),
    "POST /entities/{entity_id}/sources/change": (ADMITTED, None),
    "DELETE /entities/{entity_id}/sources/{index}": (ADMITTED, None),
    "POST /projects/{project_id}/milestones": (ADMITTED, None),
    "PATCH /projects/{project_id}/milestones/{slug}": (ADMITTED, None),
    "POST /projects/{project_id}/happenings": (ADMITTED, None),
    "POST /projects/{project_id}/threads/{claim_id}": (ADMITTED, None),
    "POST /projects/{project_id}/withdraw": (ADMITTED, None),
    "POST /projects/{project_id}/backlog": (ADMITTED, None),
    "POST /backlog/{project_id}/{item_id}/notes": (ADMITTED, None),
    "PATCH /backlog/{project_id}/{item_id}": (ADMITTED, None),
    "POST /projects/{project_id}/backlog/import": (ADMITTED, None),
    "POST /sleep/trigger": (SLEEP, None),
    "POST /sleep/run/end": (SLEEP, None),
    "POST /sleep/parked/retry": (SLEEP, None),
    "POST /sleep/cancel": (SLEEP, None),
    "PUT /sleep/run-options": (OUTSIDE, None),
    "PUT /sleep/schedule": (OUTSIDE, None),
    "PUT /sleep/engine": (OUTSIDE, None),
    "POST /conversations/upload": (CAPTURE, None),
    "POST /conversations/{conversation_id}/resume": (NONE, None),
    "POST /intake/sniff": (NONE, None),
    "POST /intake/import": (CAPTURE, None),
    "PUT /agent-methods": (HELD, "api.services.skill_pages.ensure"),
    "POST /agent-methods/skills/{skill}/page": (HELD, "api.services.skill_pages.ensure"),
    "POST /sources/save": (ADMITTED, None),
    "POST /sources/upload": (INTAKE, None),
    "POST /sources/rss": (INTAKE, None),
    "POST /sources/sync-bookmarks": (INTAKE, None),
    "POST /sources/sync-safari-tabs": (INTAKE, None),
    "POST /sources/feeds": (REGISTRY, None),
    "DELETE /sources/feeds": (REGISTRY, None),
    "POST /sources/poll-feeds": (INTAKE, None),
    "POST /sources/calendars": (REGISTRY, None),
    "DELETE /sources/calendars": (REGISTRY, None),
    "POST /sources/poll-calendars": (CAPTURE, None),
    "POST /sources/sync-notes": (CAPTURE, None),
    "POST /banks": (BANKS, None),
    "POST /banks/{name}/activate": (BANKS, None),
    "POST /banks/{name}/duplicate": (BANKS, None),
    "POST /banks/{name}/rename": (BANKS, None),
    "DELETE /banks/{name}": (BANKS, None),
    "POST /banks/demo": (BANKS, None),
    "POST /banks/leave-demo": (BANKS, None),
    "POST /banks/{name}/import": (CAPTURE, None),
    "PUT /settings/owner": (ADMITTED, None),
    "POST /sources/folders": (ADMITTED, None),
    "PUT /sources/folders/{folder_id}": (HELD, None),
    "DELETE /sources/folders/{folder_id}": (REGISTRY, None),
    "POST /sources/folders/{folder_id}/sync": (HELD, None),
    "PUT /capture/local-source/wispr-flow/settings": (REGISTRY, None),
    "POST /capture/local-source/wispr-flow": (HELD, None),
    "POST /sources/calendar-local/sync": (CAPTURE, None),
    "POST /sources/tab-groups/sync": (CAPTURE, None),
    "POST /sources/contacts-local/sync": (ADMITTED, None),
    "POST /capture/telegram": (INTAKE, None),
    "POST /capture/transcript": (CAPTURE, None),
    "POST /capture/hook-context": (NONE, None),
    "PUT /sources/connectors/{connector_id}/credentials": (OUTSIDE, None),
    "DELETE /sources/connectors/{connector_id}/credentials": (OUTSIDE, None),
    "POST /sources/connectors/{connector_id}/authorize": (OUTSIDE, None),
    "POST /sources/connectors/{connector_id}/sync": (INTAKE, None),
    "POST /maintenance/dedup-sweep": (PER_WRITE, "api.services.dedup_sweep._merge_and_commit"),
    "POST /maintenance/enrich-links": (PROBE, None),
    "POST /maintenance/link-sources": (ADMITTED, None),
    "POST /maintenance/verify-sites": (PROBE, None),
    "POST /maintenance/search-index/rebuild": (OUTSIDE, None),
    "PUT /memory/decay-tuning": (ADMITTED, None),
    "POST /connections/{connection_id}/login": (OUTSIDE, None),
    "POST /connections/{connection_id}/logout": (OUTSIDE, None),
    "PUT /connections/{connection_id}/key": (OUTSIDE, None),
    "DELETE /connections/{connection_id}/key": (OUTSIDE, None),
    "PUT /connections/{connection_id}/prefs": (OUTSIDE, None),
    "PUT /reading/settings": (OUTSIDE, None),
    "POST /reading/asks": (ADMITTED, "api.services.reading_service.ask"),
    "DELETE /reading/asks/{url_hash}": (OUTSIDE, None),
    "PUT /remote/settings": (OUTSIDE, None),
    "POST /remote/connectors": (OUTSIDE, None),
    "POST /remote/connectors/{connector_id}/rotate": (OUTSIDE, None),
    "DELETE /remote/connectors/{connector_id}": (OUTSIDE, None),
    "PUT /videos/queue/{key}": (OUTSIDE, None),
    "DELETE /videos/queue/{key}": (OUTSIDE, None),
    "POST /videos/queue/{key}/retry": (OUTSIDE, None),
    "POST /videos/run/handoff": (OUTSIDE, None),
    "POST /embeddings/choice": (OUTSIDE, None),
    "POST /embeddings/install": (OUTSIDE, None),
}

#: Every MCP tool (stdio and remote): the mcp_tools function it runs and its class.
TOOLS: dict[str, tuple[str, str | None]] = {
    "cicada_write_claim": (ADMITTED, "write_claim"),            # stdio: in-window write stays uncommitted (DECIDE)
    "cicada_retract_claim": (ADMITTED, "retract_claim"),
    "cicada_note_progress": (ADMITTED, "note_progress"),
    "cicada_add_source": (ADMITTED, "add_source"),
    "cicada_change_source": (ADMITTED, "change_source"),
    "cicada_record_check": (ADMITTED, "record_check"),
    "cicada_record_read": (ADMITTED, "record_read"),
    "cicada_record_watch": (ADMITTED, "record_watch"),
    "cicada_add_backlog_item": (ADMITTED, "add_backlog_item"),
    "cicada_add_backlog_note": (ADMITTED, "add_backlog_note"),
    "cicada_save_url": (ADMITTED, "save_url"),                  # backend up: POST /sources/save admits itself
    "cicada_resolve_inbox": (ADMITTED, None),                   # posts to /inbox/{id}/resolve, which admits
    "cicada_save_episode": (CAPTURE, None),
    "cicada_mark_processed": (CAPTURE, None),                   # an episode's cursor, revision-checked (A01)
    "cicada_video_claim": (OUTSIDE, None),
    **{t: (NONE, None) for t in (
        "cicada_handshake", "cicada_recall", "cicada_recall_detail", "cicada_open_hub", "cicada_get_perspective",
        "cicada_check_nudges", "cicada_timeline", "cicada_project", "cicada_sources", "cicada_ask",
        "cicada_backlog", "cicada_reading_queue", "cicada_video_queue", "cicada_pending", "cicada_repo_context")},
}

#: `write_admission.holding()` is the in-hold question: each site and what holds the bank around it.
HOLDING_SITES = {
    "api/routers/maintenance.py": "the sweep's may_write: asked inside each merge's own hold (and, stale, before a "
                                  "judge call, where nothing is written)",
    "api/routers/local_sources.py": "folder update/sync and Wispr Flow: inside their route()'s hold",
    "api/services/skill_pages.py": "inside ensure()'s run_admitted",
    "api/remote/runtime.py": "the remote gate: inside call()'s hold or a self-admitted tool's own",
    "api/routers/state.py": "GET /state's cursor refresh: inside its run_admitted",
}


def _routes():
    from fastapi.routing import APIRoute

    from api import main

    for r in main.app.routes:
        if isinstance(r, APIRoute):
            for m in sorted(r.methods - {"GET", "HEAD", "OPTIONS"}):
                yield f"{m} {r.path}", r.endpoint


def _src(fn) -> str:
    import inspect

    return inspect.getsource(inspect.unwrap(fn))


def _resolve(dotted: str):
    import importlib

    module, _, name = dotted.rpartition(".")
    return getattr(importlib.import_module(module), name)


def test_every_writing_route_is_classified():
    found = dict(_routes())
    assert sorted(set(found) - set(ROUTES)) == [], "an unclassified route: add it to ROUTES with its class"
    assert sorted(set(ROUTES) - set(found)) == [], "a stale ROUTES entry"


@pytest.mark.parametrize("route", sorted(k for k, (c, _) in ROUTES.items() if c in (ADMITTED, HELD, PER_WRITE)))
def test_an_admitted_route_takes_admission_in_its_code(route):
    endpoint = dict(_routes())[route]
    cls, via = ROUTES[route]
    marker = getattr(endpoint, "__write_admission__", None)
    if marker is not None:
        assert marker == ("admitted" if cls == ADMITTED else "held"), (route, marker)
        return
    src = _src(_resolve(via)) if via else _src(endpoint)
    needle = "write_admission.shared(" if cls == PER_WRITE else "run_admitted("
    assert needle in src, f"{route} is classified {cls.split(':')[0]} but its code takes no admission"
    if cls == ADMITTED and "run_admitted(" in src:
        assert "refuse=" in src, f"{route} is classified admitted but never refuses"


def test_a_probe_route_says_so_in_its_code():
    for route, (cls, _) in ROUTES.items():
        if cls == PROBE:
            assert "write_admission.probe()" in _src(dict(_routes())[route]), route


def test_every_mcp_tool_is_classified_and_admitted_tools_take_admission():
    server = (ROOT / "mcp" / "server.py").read_text()
    import re

    names = set(re.findall(r'"(cicada_[a-z_]+)"', server))
    assert sorted(names - set(TOOLS)) == [], "an unclassified MCP tool"
    assert sorted(set(TOOLS) - names) == [], "a stale TOOLS entry"
    for tool, (cls, fn_name) in TOOLS.items():
        if cls in (ADMITTED, HELD) and fn_name:
            src = _src(getattr(mcp_tools, fn_name))
            assert "@_holding_pages" in src or "write_admission.shared(" in src, f"{tool}: no admission in its code"


def test_holding_is_asked_only_where_a_hold_is_taken():
    sites = sorted({rel for rel, tree in _sources()
                    if any(isinstance(n, ast.Attribute) and n.attr == "holding"
                           and isinstance(n.value, ast.Name) and n.value.id == "write_admission"
                           for n in ast.walk(tree))})
    assert sorted(set(sites) - set(HOLDING_SITES)) == [], "a new holding() site: say what holds the bank there"
    assert sorted(set(HOLDING_SITES) - set(sites)) == [], "a stale HOLDING_SITES entry"


# --- Fix round 2, finding 5: a single link save never writes a page inside an open window ---------------------------


def test_a_save_whose_window_opened_during_its_fetch_is_refused_with_nothing_written(tmp_path, monkeypatch, save_spy):
    seen, bank_of = save_spy
    memory = bank_of["bank"] = _bank(tmp_path)
    state = {"writing": False}
    monkeypatch.setattr(sleep_cycle, "is_writing", lambda: state["writing"])

    def open_window():
        state["writing"] = True
        assert write_admission.wait_for_writers(memory, give_up_after=1) is True

    bank_of["on_fetch"] = open_window
    pages = sorted(p.name for p in (memory / "entities").iterdir())
    try:
        resp = _client_on(memory, monkeypatch).post("/sources/save", json={"url": "https://example.com/a"})
    finally:
        config.get_settings.cache_clear()
    assert resp.status_code == 409, resp.text
    assert seen["write"] == [] and sorted(p.name for p in (memory / "entities").iterdir()) == pages
    assert not (memory / "sources" / "url_index.json").exists()


def test_a_reading_ask_inside_the_window_saves_nothing(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from api.services import reading_service

    memory = _bank(tmp_path)
    monkeypatch.setattr(sleep_cycle, "is_writing", lambda: True)
    monkeypatch.setattr(reading_service.reading_settings, "agent_enabled", lambda: True)
    monkeypatch.setattr(reading_service.reading_hosts, "agent_may_read", lambda url, enabled: SimpleNamespace(
        ok=True, cls="open", reason="", host="example.com", host_class="open"))
    pages = sorted(p.name for p in (memory / "entities").iterdir())
    import asyncio

    with pytest.raises(reading_service.AskRefused) as err:
        asyncio.run(reading_service.ask(memory, "https://example.com/an-article"))
    assert err.value.status == 409
    assert sorted(p.name for p in (memory / "entities").iterdir()) == pages


def test_a_stdio_save_the_backend_refused_is_not_written_directly(tmp_path, monkeypatch, save_spy):
    import io
    import urllib.error
    import urllib.request

    seen, bank_of = save_spy
    memory = bank_of["bank"] = _bank(tmp_path)

    def refuse(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 409, "Conflict", {},
                                     io.BytesIO(b'{"detail": "Sleep is updating your memory"}'))

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    ctx = mcp_tools.ToolContext(memory_path=lambda: memory, session_id="ses_2026-10-06_c0ffee00",
                                harness="claude-code", backend_url="http://127.0.0.1:9")
    out = mcp_tools.save_url(ctx, "https://example.com/a", None)
    assert "Sleep" in out and not out.startswith("Saved")
    assert seen == {"fetch": [], "write": []}, "no fallback write behind the backend's refusal"


# --- Fix round 2, finding 6: GET routes that write are inventoried too; GET /state refreshes only when admitted -----

#: A GET whose code names a write (the pattern below) is listed here with its class. A new one fails until classified.
GET_WRITE_PATTERN = r"commit|markdown_parser\.write|\.save\(|save_|write_|ensure_fresh|record\(|\.write\(|unlink|mkdir"
GET_ROUTES: dict[str, tuple[str, str]] = {
    "GET /state": (HELD, "refreshes and commits _state.md (a cursor) inside admission; skipped while Sleep holds "
                         "the pages — the tail refreshes it then"),
    "GET /inbox": (NONE, "names a commit in a comment only"),
    "GET /entities/{entity_id}/history": (NONE, "reads commits"),
    "GET /entities/{entity_id}/history/{commit_hash}/diff": (NONE, "reads a commit"),
    "GET /entities/{entity_id}/provenance": (NONE, "reads commits"),
    "GET /contributors/commits": (NONE, "reads commits"),
    "GET /contributors/calendar": (NONE, "reads commits"),
    "GET /contributors/top-entities": (NONE, "reads commits"),
    "GET /sleep/history/{commit}": (NONE, "reads a commit"),
    "GET /handshake": (OUTSIDE, "the telemetry ledger row (outside every bank) and the primer cache"),
    "GET /banks/{name}/export": (OUTSIDE, "a temporary archive outside the bank, removed after it is sent"),
    "GET /sources/folders": (NONE, "builds response records"),
    "GET /maintenance/search-index": (OUTSIDE, "the derived search index (never tracked, never a page)"),
}


def test_every_get_route_that_names_a_write_is_classified():
    import re

    from fastapi.routing import APIRoute

    from api import main

    flagged = {f"GET {r.path}" for r in main.app.routes
               if isinstance(r, APIRoute) and "GET" in r.methods
               and re.search(GET_WRITE_PATTERN, _src(r.endpoint))}
    assert sorted(flagged - set(GET_ROUTES)) == [], "a GET that names a write: classify it in GET_ROUTES"
    assert sorted(set(GET_ROUTES) - flagged) == [], "a stale GET_ROUTES entry"
    for route, (cls, _why) in GET_ROUTES.items():
        if cls in (ADMITTED, HELD):
            endpoint = next(r.endpoint for r in main.app.routes
                            if isinstance(r, APIRoute) and f"GET {r.path}" == route)
            assert "run_admitted(" in _src(endpoint), route


def _state_client(tmp_path, monkeypatch):
    from api.services import state_dictionary

    memory = _bank(tmp_path)
    calls: list[int] = []
    real = state_dictionary.refresh_and_commit

    async def refresh_and_commit(memory_path, settings=None, **kw):
        calls.append(write_admission.holders(memory))
        return await real(memory_path, settings, **kw)

    monkeypatch.setattr(state_dictionary, "refresh_and_commit", refresh_and_commit)
    return memory, calls, _client_on(memory, monkeypatch)


def test_get_state_refreshes_inside_admission(tmp_path, monkeypatch):
    memory, calls, client = _state_client(tmp_path, monkeypatch)
    try:
        resp = client.get("/state")
    finally:
        config.get_settings.cache_clear()
    assert resp.status_code == 200, resp.text
    assert calls == [1], "the refresh and its commit hold the bank's admission"


def test_get_state_inside_the_window_serves_the_file_and_writes_nothing(tmp_path, monkeypatch):
    memory, calls, client = _state_client(tmp_path, monkeypatch)
    try:
        assert client.get("/state").status_code == 200       # writes and commits _state.md
        head = subprocess.run(["git", "-C", str(memory), "rev-parse", "HEAD"], capture_output=True,
                                            text=True).stdout
        monkeypatch.setattr(sleep_cycle, "is_writing", lambda: True)
        resp = client.get("/state?refresh=true")
    finally:
        config.get_settings.cache_clear()
    assert resp.status_code == 200, resp.text
    assert calls == [1], "no refresh while Sleep holds the pages"
    assert subprocess.run(["git", "-C", str(memory), "rev-parse", "HEAD"], capture_output=True,
                                        text=True).stdout == head
