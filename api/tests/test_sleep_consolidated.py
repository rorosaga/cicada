"""The run card's dropdown (owner 2026-10-26): what one consolidation read and wrote, item by item, from its commits'
own file lists — ``GET /sleep/runs/{id}/items`` and ``GET /sleep/history/{commit}/items`` — and the whole run's
figures on every history entry's ``run``. Synthetic bank only (``drain_harness``)."""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from drain_harness import episode_ids, git, install, seed_bank, settings

from api import main
from api.config import get_settings
from api.services import agent_engine, sleep_consolidated, sleep_cycle, sleep_drain, telemetry


@pytest.fixture(autouse=True)
def _state(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    s = sleep_cycle.get_sleep_state()
    s.status, s.drain, s.drain_run, s.cancel_requested = "idle", None, False, False
    yield
    s.status, s.drain, s.drain_run, s.cancel_requested = "idle", None, False, False
    main.app.dependency_overrides.clear()


def _calls(n):
    cid = agent_engine.cycle_id_from_scope(agent_engine.current_scope())
    for _ in range(n):
        telemetry.record(telemetry.UsageEvent(
            kind="llm_call", stage="extraction", connection="claude-plan", engine="claude-cli", model="model-a",
            billing="subscription", input_tokens=100, output_tokens=20, cost_usd=None, equiv_cost_usd=0.01,
            duration_ms=5, ok=True, refs={"cycle_id": cid, "drain_id": sleep_drain.drain_id_for(cid)}))


def _run(tmp_path, monkeypatch, n=5, cap=2, run_id="sleep_card"):
    ids = episode_ids(n)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch, engine_label="claude-cli")

    async def hook(_batch_no, _episodes):
        _calls(2)

    rig.on_extract = hook
    cfg = settings(memory, sleep_max_episodes_per_cycle=cap)
    asyncio.run(sleep_cycle.run(cfg, run_id, user_triggered=True, drain=True))
    return memory, cfg, ids


def _client(cfg):
    main.app.dependency_overrides[get_settings] = lambda: cfg
    return TestClient(main.app)


def test_a_runs_items_list_every_conversation_it_read_and_every_page_it_made(tmp_path, monkeypatch):
    memory, cfg, ids = _run(tmp_path, monkeypatch)
    body = _client(cfg).get("/sleep/runs/sleep_card/items").json()
    assert len(body["commits"]) == 3, "three batches of at most two"
    assert [c["id"] for c in body["conversations"]] == ids, "each conversation once, oldest first"
    assert all(c["origin"] and c["timestamp"] for c in body["conversations"])
    assert sorted(p["id"] for p in body["created"]) == sorted(f"e-{i}" for i in ids)
    assert all(p["name"] and not p["gone"] for p in body["created"])
    assert body["counts"]["conversations"] == len(ids) and body["counts"]["created"] == len(ids)
    assert body["truncated"] is False


def test_a_page_changed_after_it_was_made_is_listed_as_new_once(tmp_path, monkeypatch):
    memory, cfg, ids = _run(tmp_path, monkeypatch, n=2, cap=2)
    page = memory / "entities" / f"e-{ids[0]}.md"
    page.write_text(page.read_text(encoding="utf-8") + "\nMore.\n", encoding="utf-8")
    git(memory, "add", "-A")
    git(memory, "commit", "-qm", "edit")
    head = git(memory, "rev-parse", "HEAD").strip()
    commits = sleep_consolidated.run_commits(memory, "sleep_card") + [head]
    out = asyncio.run(sleep_consolidated.build(memory, commits))
    assert [p.id for p in out.created].count(f"e-{ids[0]}") == 1
    assert f"e-{ids[0]}" not in [p.id for p in out.updated]


def test_a_plain_cycles_items_and_the_refusals(tmp_path, monkeypatch):
    memory, cfg, ids = _run(tmp_path, monkeypatch, n=2, cap=5)
    client = _client(cfg)
    commit = sleep_consolidated.run_commits(memory, "sleep_card")[0]
    body = client.get(f"/sleep/history/{commit}/items").json()
    assert [c["id"] for c in body["conversations"]] == ids
    assert client.get("/sleep/runs/nope/items").status_code == 404
    assert client.get("/sleep/runs/bad%20id/items").status_code == 404
    assert client.get("/sleep/history/zzzz/items").status_code == 404
    first = git(memory, "rev-list", "--max-parents=0", "HEAD").strip()
    assert client.get(f"/sleep/history/{first}/items").status_code == 404, "not a Sleep commit"


def test_the_items_answer_304_until_the_bank_moves(tmp_path, monkeypatch):
    memory, cfg, ids = _run(tmp_path, monkeypatch, n=2, cap=5)
    client = _client(cfg)
    tag = client.get("/sleep/runs/sleep_card/items").headers["ETag"]
    assert client.get("/sleep/runs/sleep_card/items", headers={"If-None-Match": tag}).status_code == 304
    page = memory / "entities" / f"e-{ids[0]}.md"
    page.write_text(page.read_text(encoding="utf-8").replace(f"name: {ids[0]}", "name: Renamed"), encoding="utf-8")
    fresh = client.get("/sleep/runs/sleep_card/items", headers={"If-None-Match": tag})
    assert fresh.status_code == 200, "a page's name moved, so the tag did"


def test_a_question_raised_then_settled_is_read_from_where_it_lives_now(tmp_path, monkeypatch):
    memory, cfg, _ids = _run(tmp_path, monkeypatch, n=1, cap=5)
    inbox = memory / "inbox"
    inbox.mkdir(exist_ok=True)
    (inbox / "inbox-900.md").write_text("---\nid: inbox-900\nkind: clarification\nstatus: pending\n"
                                        "title: Which alpha-project?\n---\nbody\n", encoding="utf-8")
    git(memory, "add", "-A")
    git(memory, "commit", "-qm", "raise")
    raised = git(memory, "rev-parse", "HEAD").strip()
    (inbox / "settled").mkdir(exist_ok=True)
    git(memory, "mv", "inbox/inbox-900.md", "inbox/settled/inbox-900.md")
    git(memory, "commit", "-qm", "settle")
    settled = git(memory, "rev-parse", "HEAD").strip()
    out = asyncio.run(sleep_consolidated.build(memory, [raised, settled]))
    assert [q.id for q in out.questions_raised] == ["inbox-900"] and out.questions_raised[0].title
    assert [q.id for q in out.questions_settled] == ["inbox-900"]


def test_each_history_entry_carries_the_whole_runs_figures(tmp_path, monkeypatch):
    memory, cfg, ids = _run(tmp_path, monkeypatch)
    rows = _client(cfg).get("/sleep/history", params={"limit": 15}).json()
    runs = [r["run"] for r in rows if r.get("drainId") == "sleep_card"]
    assert runs and all(r == runs[0] for r in runs), "the run's own numbers, the same on every batch"
    run = runs[0]
    assert run["created"] == len(ids) and run["updated"] is not None
    assert run["questionsRaised"] is not None
    assert run["models"] == ["model-a"]
    assert run["usageSummary"]["engine"] == "claude-cli" and run["usageSummary"]["basis"]
