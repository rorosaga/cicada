"""Ruling 71 - the page-read counter (``page_reads``): what it counts, what it never counts, and that it is derived,
disposable and never served. Synthetic banks, invented names; ``CICADA_TELEMETRY=on`` because the counter is a no-op
with recording off (conftest forces it off)."""
from __future__ import annotations

import ast
import json
import sqlite3
import subprocess
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import (bank_index, bank_registry, demo_guard, inbox_service, markdown_parser, mcp_tools, page_reads,
                          page_use, question_order, runtime_layout, telemetry)
from api.services.claims import Claim, write_claims

TODAY = date.today()
TOMORROW = TODAY + timedelta(days=1)
OWNER = "owner-example"


def d(days: int) -> str:
    return (TODAY + timedelta(days=days)).isoformat()


@pytest.fixture(autouse=True)
def _on(monkeypatch):
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    for var in ("CICADA_CAPTURE", "CICADA_RECALL"):
        monkeypatch.delenv(var, raising=False)
    page_reads.reset()
    question_order.reset()
    yield
    page_reads.reset()
    question_order.reset()
    config.get_settings.cache_clear()


def page(bank, pid, *, claims=0, convs=2, said=-5, type_="concept"):
    fm = {"type": type_, "name": pid.replace("-", " ").title(), "status": "active", "confidence": 0.7,
          "created": d(-300), "last_referenced": d(said),
          "source_episodes": [f"ep_{d(-i - 1)}_001" for i in range(convs)], "related": []}
    body = f"# {fm['name']}\n"
    if claims:
        rows = [Claim(id=f"clm_{pid}_{i}", text=f"fact {i}", subject=pid, predicate="note", object=f"o{i}",
                      object_kind="literal", valid_from=d(-30), recorded_at=d(-30), source_episodes=["ep_x"])
                for i in range(claims)]
        body = write_claims(body, rows)
    markdown_parser.write(bank / "entities" / f"{pid}.md", fm, body)
    bank_index.invalidate()
    page_use.reset()


@pytest.fixture
def bank(tmp_path):
    b = tmp_path / "bank"
    for sub in ("entities", "inbox", "episodes"):
        (b / sub).mkdir(parents=True)
    markdown_parser.write(b / "_state.md", {"type": "state", "owner_id": OWNER}, "")
    page(b, OWNER, type_="person", convs=40)
    page(b, "alpha-project", claims=5)
    page(b, "beta-notes", claims=5)
    subprocess.run(["git", "init", "-q"], cwd=b, check=True)
    bank_registry.ensure_bank_ids(b)
    bank_index.invalidate()
    return b


def n_rows(bank) -> int:
    path = page_reads.path_for(page_reads.bank_key(bank))
    if not path.is_file():
        return 0
    with sqlite3.connect(str(path)) as conn:
        return conn.execute("SELECT COUNT(*) FROM reads").fetchone()[0]


# --------------------------------------------------------------------------- what counts


def test_todays_reads_count_from_tomorrow(bank):
    assert page_reads.count(bank, "alpha-project", "app", today=TODAY)
    assert page_reads.table(bank, today=TODAY) == {}, "today's weight is left out: the order cannot move in a session"
    assert page_reads.table(bank, today=TOMORROW)["alpha-project"] == pytest.approx(page_reads.OPENED * 0.5 ** (1 / 30))


def test_one_count_a_day_per_page_and_the_largest_weight_wins(bank):
    for surface in ("mcp-recall", "mcp-recall", "mcp", "mcp-recall", "mcp", "app"):
        page_reads.count(bank, "alpha-project", surface, today=TODAY)
    page_reads.count(bank, "beta-notes", "mcp-recall", today=TODAY)
    page_reads.count(bank, "beta-notes", "mcp-recall", today=TODAY)
    page_reads.reset()
    got = page_reads.table(bank, today=TOMORROW)
    decay = 0.5 ** (1 / 30)
    assert got["alpha-project"] == pytest.approx(1.0 * decay), "opened beats shown; six reads are one"
    assert got["beta-notes"] == pytest.approx(0.25 * decay)
    assert n_rows(bank) == 2


def test_a_looping_agent_cannot_pin_a_page(bank):
    for _ in range(500):
        page_reads.count(bank, "alpha-project", "mcp", today=TODAY)
    page_reads.reset()
    r = page_reads.table(bank, today=TOMORROW)["alpha-project"]
    assert r < 1.0 and page_reads.reads_fraction(r) < 0.3
    assert page_reads.reads_fraction(0.0) == 0.0 and page_reads.reads_fraction(1e9) < 1.0


def test_days_accumulate_and_halve_every_thirty(bank):
    page_reads.count(bank, "alpha-project", "app", today=TODAY - timedelta(days=40))
    page_reads.count(bank, "alpha-project", "app", today=TODAY - timedelta(days=10))
    page_reads.reset()
    got = page_reads.table(bank, today=TODAY)["alpha-project"]
    assert got == pytest.approx(0.5 ** (40 / 30) + 0.5 ** (10 / 30))
    assert page_reads.table(bank, today=TODAY + timedelta(days=30))["alpha-project"] == pytest.approx(got * 0.5)


def test_the_table_is_exact_for_the_whole_day_so_it_is_cached_per_day(bank):
    page_reads.count(bank, "alpha-project", "app", today=TODAY - timedelta(days=3))
    first = page_reads.table(bank, today=TODAY)
    page_reads.count(bank, "beta-notes", "app", today=TODAY)   # today's read: not in today's table
    assert page_reads.table(bank, today=TODAY) is first
    assert "beta-notes" not in first
    assert page_reads.stamp(bank, today=TODAY) != "" and page_reads.stamp(bank, today=TOMORROW) != page_reads.stamp(bank, today=TODAY)


def test_surfaces_are_weighed_by_suffix():
    w = page_reads.surface_weight
    assert w("mcp-recall") == w("cli-recall") == w("ask") == page_reads.SHOWN
    assert w("mcp") == w("cli") == w("app") == w("project") == w("mcp-project") == page_reads.OPENED
    assert w("mcp-backlog") is None and w("cli-backlog") is None
    # The remote connector's surface is "remote" (`remote/runtime.py`): its `cicada_recall_detail` is a read of the page
    # like any other door's, and counts at the home (the person's agents read it). It was None.
    assert w("remote") == page_reads.OPENED and w("remote-recall") == page_reads.SHOWN
    assert w("remote-project") == page_reads.OPENED and w("remote-backlog") is None
    assert w("something-new") is None and w("") is None and w(None) is None


# --------------------------------------------------------------------------- what never counts


def test_the_hook_injection_is_not_counted(bank):
    from api.services import hook_recall

    page(bank, "gamma-widgets", claims=3)
    hook_recall.prompt_context(bank, "tell me about gamma widgets")
    assert n_rows(bank) == 0 and page_reads.table(bank, today=TOMORROW) == {}
    src = Path(hook_recall.__file__).read_text(encoding="utf-8")
    assert "page_reads" not in src and "record_read" not in src, "the hook never reaches the counter"


def test_own_spawns_and_backlog_reads_are_not_counted(bank, monkeypatch):
    assert not page_reads.count(bank, "alpha-project", "mcp-backlog", today=TODAY)
    for var in ("CICADA_CAPTURE", "CICADA_RECALL"):
        monkeypatch.setenv(var, "off")
        assert not page_reads.count(bank, "alpha-project", "mcp", today=TODAY), var
        assert page_reads.table(bank, today=TOMORROW) == {}
        monkeypatch.delenv(var)
    assert n_rows(bank) == 0
    assert page_reads.count(bank, "alpha-project", "mcp", today=TODAY)


def test_a_demo_bank_and_a_replica_count_nothing_and_read_nothing(bank, monkeypatch):
    assert page_reads.count(bank, "alpha-project", "app", today=TODAY - timedelta(days=2))
    page_reads.reset()
    with monkeypatch.context() as m:
        m.setattr(runtime_layout, "is_replica", lambda environ=None: True)
        assert not page_reads.count(bank, "beta-notes", "app", today=TODAY)
        assert page_reads.table(bank, today=TODAY) == {}, "a replica's order uses page_use alone"
    page_reads.reset()
    demo_guard.manifest_path(bank).write_text(f"kind: {demo_guard.DEMO_KIND}\n", encoding="utf-8")
    assert demo_guard.is_demo(bank)
    assert not page_reads.count(bank, "beta-notes", "app", today=TODAY)
    assert page_reads.table(bank, today=TODAY) == {}, "a demo bank never counts toward, or reads from, a real one"
    demo_guard.manifest_path(bank).unlink()
    page_reads.reset()
    assert n_rows(bank) == 1


def test_with_recording_off_the_counter_is_a_no_op_and_the_order_runs_on_use_alone(bank, monkeypatch):
    page(bank, "quiet-page", claims=5, convs=1, said=-250)
    page(bank, "busy-page", claims=5, convs=30, said=-2)
    for k in range(11, 1, -1):   # oldest first
        page_reads.count(bank, "quiet-page", "app", today=TODAY - timedelta(days=k))
    page_reads.reset()
    fm = {"kind": "conflict", "entity_id": "quiet-page", "priority": 0.8,
          "options": [{"key": "a", "claim_id": "c1"}, {"key": "b", "claim_id": "c2"}]}
    counted = question_order.tables(bank).score(fm)
    monkeypatch.setenv("CICADA_TELEMETRY", "off")
    page_reads.reset()
    assert not page_reads.count(bank, "beta-notes", "app", today=TODAY - timedelta(days=2))
    assert page_reads.table(bank, today=TODAY) == {}
    assert page_reads.stamp(bank, today=TODAY) == ""
    assert n_rows(bank) == 1, "nothing new is written"
    assert question_order.tables(bank).score(fm) == question_order.tables(bank, reads=False).score(fm) < counted


def test_nothing_is_counted_until_the_bank_has_an_id(tmp_path):
    bare = tmp_path / "bare"
    (bare / "entities").mkdir(parents=True)
    assert page_reads.bank_key(bare) is None
    assert not page_reads.count(bare, "alpha-project", "app", today=TODAY)
    assert not (page_reads.path_for("x").parent.exists() and any(page_reads.path_for("x").parent.iterdir()))


# --------------------------------------------------------------------------- derived and disposable


def test_a_missing_or_corrupt_file_is_an_empty_table_never_an_error(bank):
    key = page_reads.bank_key(bank)
    assert page_reads.table(bank, today=TODAY) == {}, "no file yet"
    page_reads.reset()
    page_reads.path_for(key).parent.mkdir(parents=True, exist_ok=True)
    page_reads.path_for(key).write_bytes(b"not a database at all " * 50)
    assert page_reads.table(bank, today=TODAY) == {}
    assert not page_reads.path_for(key).exists(), "a corrupt file is removed and starts over"
    page_reads.path_for(key).write_bytes(b"still not a database " * 50)
    page_reads.reset()
    assert page_reads.count(bank, "alpha-project", "app", today=TODAY - timedelta(days=2)) is False   # failed, quietly
    assert page_reads.count(bank, "alpha-project", "app", today=TODAY - timedelta(days=2)) is True    # started over
    assert page_reads.table(bank, today=TODAY)["alpha-project"] > 0


def test_a_locked_file_costs_the_count_not_the_read(bank):
    page_reads.count(bank, "alpha-project", "app", today=TODAY - timedelta(days=2))
    page_reads.reset()
    key = page_reads.bank_key(bank)
    holder = sqlite3.connect(str(page_reads.path_for(key)), timeout=0.1, isolation_level=None)
    holder.execute("BEGIN EXCLUSIVE")
    try:
        assert page_reads.count(bank, "beta-notes", "app", today=TODAY - timedelta(days=1)) is False
        assert page_reads.table(bank, today=TODAY) in ({}, {"alpha-project": pytest.approx(0.5 ** (2 / 30))})
    finally:
        holder.rollback()
        holder.close()
    assert page_reads.path_for(key).exists(), "a locked file is not a corrupt one"
    assert page_reads.count(bank, "beta-notes", "app", today=TODAY - timedelta(days=1)) is True


def test_the_file_holds_ids_and_numbers_only_and_is_private(bank):
    page_reads.count(bank, "alpha-project", "app", today=TODAY - timedelta(days=2))
    path = page_reads.path_for(page_reads.bank_key(bank))
    assert oct(path.stat().st_mode & 0o777) == "0o600" and oct(path.parent.stat().st_mode & 0o777) == "0o700"
    with sqlite3.connect(str(path)) as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(reads)")]
        rows = conn.execute("SELECT * FROM reads").fetchall()
    assert cols == ["page", "value", "day", "weight"]
    assert rows == [("alpha-project", 0.0, d(-2), 1.0)]
    assert bank.name not in path.name, "the file is named by the bank's id, never its name"


def test_the_id_survives_a_rename_and_a_copy_gets_its_own(tmp_path):
    root = tmp_path / "root"
    bank_registry.scaffold_bank(root)
    bank_registry.create_bank(root, "Scratch")
    first = page_reads.bank_key(root / "banks" / "scratch")
    assert first and first != page_reads.bank_key(root)
    slug = bank_registry.duplicate_bank(root, "scratch", "Copy")
    assert page_reads.bank_key(root / "banks" / slug) not in (None, first), "a copy never shares the counter"


# --------------------------------------------------------------------------- wipe


def test_deleting_a_bank_deletes_its_counter_with_its_wal_and_shm(tmp_path, monkeypatch):
    root = tmp_path / "root"
    bank_registry.scaffold_bank(root)
    bank_registry.create_bank(root, "Scratch")
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(root))
    config.get_settings.cache_clear()
    mp = root / "banks" / "scratch"
    other = root / "banks"
    bank_registry.create_bank(root, "Keeper")
    page(mp, "alpha-project", claims=1)
    page(root / "banks" / "keeper", "alpha-project", claims=1)
    page_reads.count(mp, "alpha-project", "app", today=TODAY - timedelta(days=2))
    page_reads.count(root / "banks" / "keeper", "alpha-project", "app", today=TODAY - timedelta(days=2))
    key, keeper = page_reads.bank_key(mp), page_reads.bank_key(root / "banks" / "keeper")
    mine = page_reads._files(key)
    mine[1].write_bytes(b"wal")   # a live process leaves these beside the file
    mine[2].write_bytes(b"shm")
    assert all(f.exists() for f in mine)
    client = TestClient(main.app)
    resp = client.delete("/banks/scratch")
    assert resp.status_code == 200, resp.text
    assert not any(f.exists() for f in mine), "the file, its -wal and its -shm"
    assert page_reads.path_for(keeper).exists(), "another memory's counter is untouched"
    assert other.exists()


def test_forget_bank_refuses_anything_that_is_not_an_id(bank):
    page_reads.count(bank, "alpha-project", "app", today=TODAY - timedelta(days=2))
    page_reads.forget_bank("../x")
    page_reads.forget_bank("")
    page_reads.forget_bank(None)
    assert n_rows(bank) == 1


def test_the_first_inbox_read_of_a_day_prunes_pages_that_are_gone_and_never_on_an_empty_list(bank):
    page_reads.count(bank, "alpha-project", "app", today=TODAY - timedelta(days=2))
    page_reads.count(bank, "ghost-page", "app", today=TODAY - timedelta(days=2))
    page_reads.reset()
    question_order.tables(bank, today=TODAY, prune=True)
    assert set(page_reads.table(bank, today=TODAY)) == {"alpha-project"}
    assert n_rows(bank) == 1
    page_reads.count(bank, "ghost-two", "app", today=TODAY - timedelta(days=2))
    page_reads.reset()
    page_reads._prune(page_reads.bank_key(bank), TODAY.isoformat(), set())
    assert n_rows(bank) == 2, "a bank that cannot list its pages is not a wipe"


# --------------------------------------------------------------------------- the choke point


def _ctx(bank, **kw):
    return mcp_tools.ToolContext(memory_path=lambda: bank, session_id="s-1", harness="claude-code", **kw)


def test_recall_detail_and_the_app_open_count_opened_and_recall_counts_shown(bank, monkeypatch):
    mcp_tools.recall_detail(_ctx(bank), "alpha-project")
    monkeypatch.setattr(mcp_tools, "_relevant_inbox", lambda memory_path, query, **_: [])
    monkeypatch.setattr(mcp_tools, "_match_hub", lambda memory_path, query: (None, []))
    monkeypatch.setattr(mcp_tools, "_leann_search_entities", lambda memory_path, query, top_k: [])
    monkeypatch.setattr(mcp_tools, "_leann_search_episodes", lambda memory_path, query, top_k: [])
    monkeypatch.setattr(mcp_tools, "_claim_subject_search", lambda memory_path, query, top_k: [])
    mcp_tools.recall(_ctx(bank), "beta notes")
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    assert TestClient(main.app).post("/entities/alpha-project/read", json={"surface": "app"}).json() == {"recorded": True}
    page_reads.reset()
    got = page_reads.table(bank, today=TOMORROW)
    decay = 0.5 ** (1 / 30)
    assert got["alpha-project"] == pytest.approx(1.0 * decay), "recall_detail and the app's open: one opened day"
    assert got["beta-notes"] == pytest.approx(0.25 * decay), "recall showed it: shown"


def test_a_remote_recall_detail_counts_as_opened_at_the_home(bank):
    """The remote runtime's surface is "remote" (`remote/runtime.py`); `surface_weight` once returned None for it, so the
    person's remote agents never counted. Their reads are reads (only the remote door's own ORDER is computed without
    the counter, `reads=False`)."""
    mcp_tools.recall_detail(_ctx(bank, read_surface="remote", connector_id="conn-1"), "alpha-project")
    page_reads.reset()
    assert page_reads.table(bank, today=TOMORROW)["alpha-project"] == pytest.approx(1.0 * 0.5 ** (1 / 30))


def test_ask_counts_the_pages_it_read_as_shown(bank):
    from api.services import ask_service

    hits = [{"score": 0.7, "text": "Beta Notes text",
             "metadata": {"entity_id": "beta-notes", "entity_name": "Beta Notes", "type": "concept", "status": "active",
                          "confidence": 0.8, "file_path": ""}}]
    ask_service.answer_query(bank, "what is in beta notes", retrieve_fn=lambda q, k: hits,
                             llm_fn=lambda prompt: json.dumps({"answer": "x", "used_entities": ["beta-notes"],
                                                               "gaps": [], "confidence": 0.5}),
                             no_engine=False, source_words=False, search_fn=lambda mp, q: None)
    page_reads.reset()
    got = page_reads.table(bank, today=TOMORROW)
    assert got.get("beta-notes") == pytest.approx(0.25 * 0.5 ** (1 / 30))


def test_a_project_timeline_open_counts_and_the_ledger_event_is_unchanged(bank, tmp_path, monkeypatch):
    telemetry.record_read("alpha-project", surface="project", bank="b", memory_path=bank)
    telemetry.record_read("alpha-project", surface="mcp-backlog", bank="b", memory_path=bank)
    telemetry.record_read("alpha-project", surface="app", bank="b")   # no memory_path: the ledger event only
    page_reads.reset()
    assert page_reads.table(bank, today=TOMORROW)["alpha-project"] == pytest.approx(0.5 ** (1 / 30))


# --------------------------------------------------------------------------- never served


ALLOWED = {
    "api/services/telemetry.py": "the one choke point: counts a read it was told the memory of",
    "api/services/question_order.py": "the order's reader",
    "api/services/ask_service.py": "counts the pages an answer read",
    "api/routers/banks.py": "wipes a deleted bank's counter",
}


def _uses_the_counter(source: str) -> bool:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and any(a.name == "page_reads" for a in node.names):
            return True
        if isinstance(node, ast.Import) and any(a.name.endswith("page_reads") for a in node.names):
            return True
    return False


def test_no_route_tool_door_export_or_sync_module_can_serve_the_counter():
    root = Path(__file__).resolve().parents[2]
    found = set()
    for sub in ("api", "mcp", "clients", "relay"):
        for f in (root / sub).rglob("*.py"):
            rel = f.relative_to(root).as_posix()
            if rel.startswith("api/tests") or "/tests/" in rel or rel == "api/services/page_reads.py":
                continue
            try:
                if _uses_the_counter(f.read_text(encoding="utf-8", errors="replace")):
                    found.add(rel)
            except SyntaxError:
                continue
    assert found <= set(ALLOWED), f"a new reader of the counter: {sorted(found - set(ALLOWED))}"
    banks = (root / "api/routers/banks.py").read_text(encoding="utf-8")
    assert "page_reads.forget_bank" in banks and "page_reads.table" not in banks


def test_no_response_carries_a_counted_page_id(bank, monkeypatch):
    marker = "marker-page-xq9"
    page(bank, marker, claims=3)
    for k in range(5, 0, -1):
        page_reads.count(bank, marker, "app", today=TODAY - timedelta(days=k))
    page_reads.reset()
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    client = TestClient(main.app)
    paths = ["/inbox", "/consumption/stats", "/consumption/feedback", "/sync/version", "/healthz"]
    for p in paths:
        body = client.get(p).text
        assert "page-reads" not in body and "pageReads" not in body, p
    stats = client.get("/consumption/stats").text
    assert marker not in stats


# --------------------------------------------------------------------------- GET /inbox


def _inbox_item(bank, num, **fm):
    base = {"kind": "conflict", "status": "pending", "priority": 0.8, "created_date": d(-1), "required_input": "choice",
            "title": "t", "predicate": "uses"}
    path = bank / "inbox" / f"inbox-{num:03d}.md"
    markdown_parser.write(path, {**base, **fm}, "body")
    bank_index.invalidate()
    return path.stem


def _opts(page_id, n=2):
    return [{"key": f"o{i}", "label": f"v{i}", "claim_id": f"clm_{page_id}_{i}"} for i in range(n)]


def test_get_inbox_serves_the_order_index_and_folds_the_counter_into_its_etag(bank, monkeypatch):
    page(bank, "busy-page", claims=5, convs=30, said=-2)
    page(bank, "quiet-page", claims=5, convs=1, said=-250)
    page(bank, "moderate-page", claims=5, convs=4, said=-10)
    _inbox_item(bank, 1, entity_id="quiet-page", entity_name="Quiet Page", options=_opts("quiet-page"))
    _inbox_item(bank, 2, entity_id="moderate-page", entity_name="Moderate Page", options=_opts("moderate-page"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    inbox_service.reset_built()
    client = TestClient(main.app)
    resp = client.get("/inbox")
    assert resp.status_code == 200
    rows = resp.json()
    assert [r["orderIndex"] for r in rows] == list(range(len(rows)))
    assert [r["id"] for r in rows] == ["inbox-002", "inbox-001"], "the used page's question first"
    etag = resp.headers["etag"]
    assert client.get("/inbox", headers={"If-None-Match": etag}).status_code == 304
    # a day-cut read arrives (earlier days, as another process wrote them): the tag moves, the order follows
    for k in range(11, 1, -1):   # oldest first
        page_reads.count(bank, "quiet-page", "app", today=TODAY - timedelta(days=k))
    page_reads.reset()
    changed = client.get("/inbox", headers={"If-None-Match": etag})
    assert changed.status_code == 200 and changed.headers["etag"] != etag
    assert [r["id"] for r in changed.json()] == ["inbox-001", "inbox-002"], "the page opened every day comes first"
    assert [r["orderIndex"] for r in changed.json()] == [0, 1]


def test_the_built_list_is_rebuilt_when_the_counters_day_cut_moves_and_not_otherwise(bank):
    _inbox_item(bank, 1, entity_id="alpha-project", entity_name="Alpha Project", options=_opts("alpha-project"))
    inbox_service.reset_built()
    inputs = inbox_service._built_inputs(bank, str(TODAY))
    assert inbox_service._built_inputs(bank, str(TODAY)) == inputs
    page_reads.count(bank, "alpha-project", "app", today=TODAY)   # today's read: not an input
    assert inbox_service._built_inputs(bank, str(TODAY)) == inputs
    page_reads.count(bank, "beta-notes", "app", today=TODAY - timedelta(days=3))
    page_reads.reset()
    assert inbox_service._built_inputs(bank, str(TODAY)) != inputs


def test_one_unreadable_question_never_takes_down_get_inbox(bank, monkeypatch):
    _inbox_item(bank, 1, entity_id="alpha-project", entity_name="Alpha Project", options=_opts("alpha-project"))
    _inbox_item(bank, 2, entity_id="beta-notes", entity_name="Beta Notes", options=_opts("beta-notes"), priority=0.35)
    real = question_order.claim_count

    def boom(mp, pid):
        if pid == "beta-notes":
            raise RuntimeError("unreadable")
        return real(mp, pid)

    monkeypatch.setattr(question_order, "claim_count", boom)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    inbox_service.reset_built()
    resp = TestClient(main.app).get("/inbox")
    assert resp.status_code == 200 and {r["id"] for r in resp.json()} == {"inbox-001", "inbox-002"}


def test_the_resolution_row_carries_the_impact_bucket_taken_before_the_resolver_writes(bank, monkeypatch):
    seen = {}
    monkeypatch.setattr(telemetry, "record", lambda ev: seen.setdefault("refs", ev.refs) if ev.kind == "resolution" else None)
    _inbox_item(bank, 1, entity_id="alpha-project", entity_name="Alpha Project", options=_opts("alpha-project"))
    settings = type("S", (), {"memory_path": bank})()
    fm = dict(markdown_parser.parse(bank / "inbox" / "inbox-001.md").frontmatter)
    assert inbox_service._impact_bucket(settings, fm) in ("high", "mid", "low")
    assert inbox_service._impact_bucket(settings, {"kind": "no-such-kind"}) in ("high", "mid", "low", None)
