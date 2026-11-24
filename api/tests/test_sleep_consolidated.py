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


def test_a_page_carries_the_commits_that_changed_it_and_its_span_diff_is_one_change(tmp_path, monkeypatch):
    """Owner 2026-11-23 ("see what page or chunk of page was modified"): each page lists the consolidation's commits
    that touched it, oldest first, and ``?since=`` on its diff route reads the whole span as one before → after."""
    memory, cfg, ids = _run(tmp_path, monkeypatch, n=2, cap=2)
    eid = f"e-{ids[0]}"
    page = memory / "entities" / f"{eid}.md"
    page.write_text(page.read_text(encoding="utf-8") + "\nA later line.\n", encoding="utf-8")
    git(memory, "add", "-A")
    git(memory, "commit", "-qm", "edit")
    head = git(memory, "rev-parse", "HEAD").strip()
    commits = sleep_consolidated.run_commits(memory, "sleep_card") + [head]
    out = asyncio.run(sleep_consolidated.build(memory, commits))
    made = next(p for p in out.created if p.id == eid)
    assert made.commits[-1] == head and len(made.commits) == 2, "the batch that made it, then the edit"
    client = _client(cfg)
    span = client.get(f"/entities/{eid}/history/{head}/diff", params={"since": made.commits[0]}).json()
    added = [ln["text"] for ln in span["lines"] if ln["kind"] == "add"]
    assert "A later line." in added and len(added) > 1, "the page's making and the later edit, in one diff"
    one = client.get(f"/entities/{eid}/history/{head}/diff").json()
    assert [ln["text"] for ln in one["lines"] if ln["kind"] == "add" and ln["text"]] == ["A later line."]
    refused = client.get(f"/entities/{eid}/history/{head}/diff", params={"since": "--output=/tmp/x"}).json()
    assert refused["lines"] == [], "a since that is not a hash never reaches git"


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
    # owner 2026-11-24: the closed card's counts ARE the opened card's
    items = _client(cfg).get("/sleep/runs/sleep_card/items").json()["counts"]
    assert {k: run[k] for k in ("created", "updated", "archived", "removed", "faded")} == \
           {k: items[k] for k in ("created", "updated", "archived", "removed", "faded")}
    assert run["questionsRaised"] is not None
    assert run["models"] == ["model-a"]
    assert run["usageSummary"]["engine"] == "claude-cli" and run["usageSummary"]["basis"]


def _settle(memory, item_id, *, subject, date=None):
    """What `inbox_tend` commits for a settle: the item moved under inbox/settled/, in a commit of its own."""
    import os
    import subprocess

    inbox = memory / "inbox"
    (inbox / "settled").mkdir(parents=True, exist_ok=True)
    (inbox / f"{item_id}.md").write_text(f"---\nid: {item_id}\nkind: clarification\nstatus: pending\n"
                                         f"title: Which alpha-project?\n---\nbody\n", encoding="utf-8")
    git(memory, "add", "-A")
    git(memory, "commit", "-qm", f"raise {item_id}")
    git(memory, "mv", f"inbox/{item_id}.md", f"inbox/settled/{item_id}.md")
    env = {**os.environ, **({"GIT_COMMITTER_DATE": date, "GIT_AUTHOR_DATE": date} if date else {})}
    subprocess.run(["git", "commit", "-qm", subject], cwd=memory, check=True, env=env)


def test_sleeps_own_settles_during_the_run_are_its_settled_questions(tmp_path, monkeypatch):
    """Sleep commits a settle on its own (`Inbox settled by Sleep (<kind>) <date>`), never inside a batch commit: the
    run's settled questions are those commits inside its window — not a person's resolution, not one long after."""
    memory, cfg, _ids = _run(tmp_path, monkeypatch, n=1, cap=5)
    _settle(memory, "inbox-901", subject="Inbox settled by Sleep (clarification) 2026-10-26")
    _settle(memory, "inbox-902", subject="Inbox resolution 2026-10-26")
    _settle(memory, "inbox-903", subject="Inbox settled by Sleep (clarification) 2030-01-01",
            date="2030-01-01T00:00:00+00:00")
    body = _client(cfg).get("/sleep/runs/sleep_card/items").json()
    assert [q["id"] for q in body["questionsSettled"]] == ["inbox-901"]
    assert body["counts"]["questions_settled"] == 1
    commit = sleep_consolidated.run_commits(memory, "sleep_card")[0]
    cycle = _client(cfg).get(f"/sleep/history/{commit}/items").json()
    assert [q["id"] for q in cycle["questionsSettled"]] == ["inbox-901"], "a plain cycle reads the same window"


# --- items-5 (owner 2026-11-24): the pages affected per source -----------------------------------------------------


def _commit(memory, subject, *, date=None):
    import os
    import subprocess

    git(memory, "add", "-A")
    env = {**os.environ, **({"GIT_COMMITTER_DATE": date, "GIT_AUTHOR_DATE": date} if date else {})}
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", subject], cwd=memory, check=True, env=env)
    return git(memory, "rev-parse", "HEAD").strip()


def _put(memory, kind, name, fm, body="Body."):
    from api.services import markdown_parser

    markdown_parser.write(memory / kind / f"{name}.md", fm, body)


def _page(memory, eid, *, status="active", sources=(), name=None, typ="concept"):
    _put(memory, "entities", eid, {"id": eid, "name": name or eid.replace("-", " ").title(), "type": typ,
                                   "status": status, "confidence": 0.8, "source_episodes": list(sources)})


def _processed(memory, ep):
    from api.services import markdown_parser

    fm = markdown_parser.parse(memory / "episodes" / f"{ep}.md").frontmatter
    _put(memory, "episodes", ep, {**fm, "processed": True}, "Body.")


def _set_status(memory, eid, status):
    page = memory / "entities" / f"{eid}.md"
    page.write_text(page.read_text(encoding="utf-8").replace("status: active", f"status: {status}")
                    .replace("status: archived", f"status: {status}"), encoding="utf-8")


def _manifest_message(memory, subject, *, trigger="sleep/extraction", overrides=None, authors=("model-a",)):
    """What `sleep_cycle._finalize` writes: the subject, a manifest line for each entity file the commit is about to
    carry (its trigger: what changed it), the author trailer."""
    from api.services import git_service

    lines = []
    for raw in git(memory, "status", "--porcelain", "--untracked-files=all").splitlines():
        path = raw[3:].strip()
        if not path.startswith("entities/") or not path.endswith(".md"):
            continue
        eid = path[len("entities/"):-3]
        action = "removed" if "D" in raw[:2] else "created" if raw[:2] in ("??", "A ") else "updated"
        lines.append(f"{path}: {action} (source: n/a, trigger: {(overrides or {}).get(eid, trigger)})")
    return git_service.build_commit_message(subject, lines, authors=list(authors))


def synthetic_run(tmp_path, *, tie_decay=True):
    """A bank whose run read four conversations (two origins, a device, a saved link, a meeting) and made two
    batches: pages created, updated, archived (by the batch's own commit and by its decay commit), removed (deleted),
    one fed by two conversations and one with no conversation of this run behind it; a decay commit that also let one
    page fade (its confidence moved by silence) and only stamped another (bookkeeping). The manifests name each page's
    trigger, so a page no conversation fed says which step changed it. Returns ``(memory, commits, decay commit)``."""
    from sleep_changes_synth import DAY, claim_entry, write_page
    memory = seed_bank(tmp_path, [])
    for ep, fm in {
        "ep_2026-10-01_000": {"source": "mcp", "session_id": "ses_a"},
        "ep_2026-10-01_001": {"source": "mcp", "session_id": "ses_b", "device": "device-a"},
        "ep_2026-10-01_002": {"origin": "chrome-bookmark", "url": "https://docs.example.com/guide/alpha-project"},
        "ep_2026-10-01_003": {"origin": "folder", "folder_kind": "meetings", "folder_id": "f1",
                              "meeting": {"recorder": "hex", "app": "call-app", "duration_s": 1800,
                                          "attendees": ["bob-example", "alice-example"]}},
    }.items():
        _put(memory, "episodes", ep, {"id": ep, "processed": False, "timestamp": f"2026-10-01T10:{ep[-1]}0:00",
                                      "title": f"Conversation {int(ep[-1]) + 1}", **fm}, "Body.")
    a, b, c, d = ("ep_2026-10-01_00" + i for i in "0123")
    for eid in ("upd-one", "solo-two", "arch-batch", "arch-decay", "restored", "gone-one", "gone-two"):
        _page(memory, eid, sources=["ep_2026-08-01_000"], typ="person" if eid.startswith("gone") else "concept")
    write_page(memory, "faded-one", [claim_entry("faded-one", 0), claim_entry("faded-one", 1)])
    write_page(memory, "stamp-one", [claim_entry("stamp-one", 0)])
    _commit(memory, "base")
    # the decay commit comes first (arithmetic only), then the batch commit
    _set_status(memory, "arch-decay", "archived")
    _set_status(memory, "restored", "archived")
    write_page(memory, "faded-one", [claim_entry("faded-one", 0, decayed=DAY, confidence=0.4),
                                     claim_entry("faded-one", 1, decayed=DAY)], decayed_through=DAY, confidence=0.4)
    write_page(memory, "stamp-one", [claim_entry("stamp-one", 0, decayed=DAY)], decayed_through=DAY,
               last_referenced=DAY, version=2)
    first_decay = _commit(memory, _manifest_message(memory, "Sleep cycle 2026-10-01 (decay)", trigger="sleep/decay",
                                                    authors=("cicada",)))
    for ep in (a, b):   # batch 1: it reads a and b
        _processed(memory, ep)
    _page(memory, "new-one", sources=[a])
    _page(memory, "new-two", sources=[a, b])                      # fed by two conversations
    _page(memory, "upd-one", sources=["ep_2026-08-01_000", b])    # updated by b
    _page(memory, "solo-two", sources=["ep_2026-08-01_000"], name="Solo Two Edited")  # no conversation of this run
    _set_status(memory, "arch-batch", "archived")                 # a correction archives it in the batch commit
    (memory / "entities" / "gone-one.md").unlink()                # merged away
    _page(memory, "made-then-archived", sources=[c])
    one = _commit(memory, _manifest_message(memory, "Sleep cycle 2026-10-01 (batch 1 of 2)",
                                            overrides={"solo-two": "sleep/conflict_resolution"}))
    # batch 2: reads c and d; restores a page the decay archived; archives what batch 1 created; removes another
    for ep in (c, d):
        _processed(memory, ep)
    _set_status(memory, "restored", "active")
    _set_status(memory, "made-then-archived", "archived")
    (memory / "entities" / "gone-two.md").unlink()
    _page(memory, "new-three", sources=[d])
    two = _commit(memory, _manifest_message(memory, "Sleep cycle 2026-10-01 (batch 2 of 2)"))
    return memory, [one, two], first_decay


def _by_id(rows):
    return {r.id: r for r in rows}


def test_every_page_is_in_one_list_with_its_change_and_the_conversations_that_fed_it(tmp_path):
    memory, commits, _decay = synthetic_run(tmp_path)
    out = asyncio.run(sleep_consolidated.build(memory, commits))
    assert sleep_consolidated.SHAPE == "items-6"
    assert [p.id for p in out.created] == ["new-one", "new-two", "new-three"], "made-then-archived is archived, not new"
    assert sorted(p.id for p in out.updated) == ["restored", "solo-two", "upd-one"]
    assert sorted(p.id for p in out.archived) == ["arch-batch", "arch-decay", "made-then-archived"]
    assert sorted(p.id for p in out.removed) == ["gone-one", "gone-two"]
    listed = [p.id for rows in (out.created, out.updated, out.archived, out.removed) for p in rows]
    assert len(listed) == len(set(listed)), "a page is in exactly one list"
    assert {p.change for p in out.created} == {"created"} and {p.change for p in out.removed} == {"removed"}
    assert {p.change for p in out.archived} == {"archived"} and {p.change for p in out.updated} == {"updated"}
    assert out.counts["created"] == 3 and out.counts["updated"] == 3
    assert out.counts["archived"] == 3 and out.counts["removed"] == 2
    assert [p.id for p in out.faded] == ["faded-one"] and out.counts["faded"] == 1 and out.counts["bookkeeping"] == 1
    assert all("stamp-one" not in [p.id for p in rows] for rows in (out.created, out.updated, out.archived, out.removed,
                                                                      out.faded)), "a stamp is no change"
    steps = {p.id: p.steps for rows in (out.created, out.updated, out.archived, out.removed, out.faded) for p in rows}
    assert steps["solo-two"] == ["conflict"], "no conversation behind it: the step that changed it"
    assert steps["arch-decay"] == ["decay"] and steps["faded-one"] == ["decay"] and steps["new-one"] == ["reading"]


def test_a_page_says_which_of_this_runs_conversations_fed_it_and_never_another_runs(tmp_path):
    memory, commits, _decay = synthetic_run(tmp_path)
    out = asyncio.run(sleep_consolidated.build(memory, commits))
    a, b, c, d = ("ep_2026-10-01_00" + i for i in "0123")
    pages = {**_by_id(out.created), **_by_id(out.updated), **_by_id(out.archived), **_by_id(out.removed)}
    assert pages["new-one"].episodes == [a]
    assert pages["new-two"].episodes == [a, b], "one page fed by two conversations"
    assert pages["upd-one"].episodes == [b], "the earlier run's conversation is not listed"
    assert pages["solo-two"].episodes == [], "no conversation of this run is behind it"
    assert pages["made-then-archived"].episodes == [c]
    convs = _by_id(out.conversations)
    assert convs[a].pages == ["new-one", "new-two"]
    assert convs[b].pages == ["new-two", "upd-one"]
    assert convs[c].pages == ["made-then-archived"] and convs[d].pages == ["new-three"]
    assert all(p in pages for conv in out.conversations for p in conv.pages), "every id resolves in a list"


def test_a_conversation_carries_the_facts_the_waiting_row_carries(tmp_path):
    from api.routers.sleep import _episode_items
    from api.services import sleep_cycle as sc

    memory, commits, _decay = synthetic_run(tmp_path)
    out = asyncio.run(sleep_consolidated.build(memory, commits))
    convs = _by_id(out.conversations)
    a, b, c, d = ("ep_2026-10-01_00" + i for i in "0123")
    assert convs[a].device is None and convs[b].device == "device-a", "none is the home itself"
    assert convs[c].site == "docs.example.com" and convs[a].site is None
    assert convs[d].meeting.app == "call-app" and convs[d].meeting.duration_s == 1800 and convs[d].meeting.attendees == 2
    assert convs[a].meeting is None
    assert convs[d].origin == "hex" and convs[c].origin == "chrome-bookmark" and convs[a].origin != convs[c].origin
    # the same helper as the queue's rows: for every episode the two doors agree (a row of the Waiting list is built
    # from the same header). Re-open one as waiting and compare.
    rows = {r.id: r for r in _episode_items(memory, sc.episode_headers(memory))}
    for cid, conv in convs.items():
        assert (rows[cid].device, rows[cid].site) == (conv.device, conv.site), cid
        assert (rows[cid].meeting.model_dump() if rows[cid].meeting else None) == \
               (conv.meeting.model_dump() if conv.meeting else None), cid


def test_a_removed_page_keeps_its_name_and_type_from_git_and_is_gone(tmp_path):
    memory, commits, _decay = synthetic_run(tmp_path)
    out = asyncio.run(sleep_consolidated.build(memory, commits))
    rm = _by_id(out.removed)
    assert rm["gone-one"].gone is True and rm["gone-one"].name == "Gone One" and rm["gone-one"].type == "person"
    assert rm["gone-one"].commits == [commits[0]] and rm["gone-two"].commits == [commits[1]]


def test_archived_is_read_from_git_in_the_batch_commit_and_in_its_decay_commit(tmp_path):
    memory, commits, decay = synthetic_run(tmp_path)
    out = asyncio.run(sleep_consolidated.build(memory, commits))
    arch = _by_id(out.archived)
    assert arch["arch-batch"].commits == [commits[0]], "a status change inside the run's own commit"
    assert arch["arch-decay"].commits == [decay], "the batch's own (decay) commit, found right before it"
    assert "restored" not in arch, "archived by decay, restored by the next batch: its state at the end counts"
    # the page's status today never decides it: restore the archived page by hand after the run
    _set_status(memory, "arch-decay", "active")
    again = asyncio.run(sleep_consolidated.build(memory, commits))
    assert "arch-decay" in _by_id(again.archived), "read from the commits, not from the page now"


def test_a_decay_commit_another_commit_separates_from_its_batch_is_not_tied(tmp_path):
    memory = seed_bank(tmp_path, [])
    _page(memory, "slow-fade")
    _commit(memory, "base")
    _set_status(memory, "slow-fade", "archived")
    _commit(memory, "Sleep cycle 2026-10-01 (decay)")
    (memory / "notes.txt").write_text("a person's commit in between", encoding="utf-8")
    _commit(memory, "unrelated")
    batch = _commit(memory, "Sleep cycle 2026-10-01 (batch 1 of 1)")
    out = asyncio.run(sleep_consolidated.build(memory, [batch]))
    assert out.archived == [] and out.counts["archived"] == 0, "uncertain: reported nowhere"
    # nor one made long before the batch
    memory2 = seed_bank(tmp_path / "two", [])
    _page(memory2, "old-fade")
    _commit(memory2, "base")
    _set_status(memory2, "old-fade", "archived")
    _commit(memory2, "Sleep cycle 2026-10-01 (decay)", date="2026-10-01T00:00:00+00:00")
    later = _commit(memory2, "Sleep cycle 2026-10-01 (batch 1 of 1)")
    assert asyncio.run(sleep_consolidated.build(memory2, [later])).archived == []


def test_the_state_snapshot_between_decay_and_batch_still_ties(tmp_path):
    memory = seed_bank(tmp_path, [])
    _page(memory, "fade")
    _commit(memory, "base")
    _set_status(memory, "fade", "archived")
    _commit(memory, "Sleep cycle 2026-10-01 (decay)")
    (memory / "_state.md").write_text("state", encoding="utf-8")
    _commit(memory, "State snapshot 2026-10-01")
    batch = _commit(memory, "Sleep cycle 2026-10-01 (batch 1 of 1)")
    assert [p.id for p in asyncio.run(sleep_consolidated.build(memory, [batch])).archived] == ["fade"]


def test_the_cap_and_whole_counts_hold_for_the_new_lists(tmp_path, monkeypatch):
    memory = seed_bank(tmp_path, [])
    for i in range(5):
        _page(memory, f"rm-{i}", typ="person")
    _commit(memory, "base")
    for i in range(5):
        (memory / "entities" / f"rm-{i}.md").unlink()
    batch = _commit(memory, "Sleep cycle 2026-10-01 (batch 1 of 1)")
    monkeypatch.setattr(sleep_consolidated, "CAP", 2)
    out = asyncio.run(sleep_consolidated.build(memory, [batch]))
    assert len(out.removed) == 2 and out.counts["removed"] == 5 and out.truncated is True


def test_the_git_cost_is_a_few_calls_per_commit_plus_one_per_removed_page(tmp_path, monkeypatch):
    from api.services import git_service

    memory, commits, _decay = synthetic_run(tmp_path)
    real, calls = git_service._run_git, []

    async def counting(mp, *args):
        calls.append(args[0])
        return await real(mp, *args)

    monkeypatch.setattr(git_service, "_run_git", counting)
    out = asyncio.run(sleep_consolidated.build(memory, commits))
    assert calls.count("show") == len(out.removed) == 2
    assert len(calls) <= 4 * len(commits) + len(out.removed), calls


def test_the_items_route_answers_the_new_shape(tmp_path, monkeypatch):
    memory, cfg, ids = _run(tmp_path, monkeypatch, n=2, cap=5)
    body = _client(cfg).get("/sleep/runs/sleep_card/items").json()
    assert body["archived"] == [] and body["removed"] == [] and body["counts"]["archived"] == 0
    assert {"device", "site", "meeting", "pages"} <= set(body["conversations"][0])
    assert body["conversations"][0]["pages"] == [f"e-{ids[0]}"]
    assert body["created"][0]["change"] == "created" and body["created"][0]["episodes"] == [ids[0]]


def test_a_page_merged_away_beside_a_look_alike_new_page_still_reads_as_removed(tmp_path):
    """git pairs a deleted file with a similar new one as a rename; the source is a page the run removed."""
    memory = seed_bank(tmp_path, [])
    body = "A long shared paragraph about alpha-project. " * 30
    _put(memory, "entities", "twin-old", {"id": "twin-old", "name": "Twin", "type": "concept", "status": "active"}, body)
    _commit(memory, "base")
    (memory / "entities" / "twin-old.md").unlink()
    _put(memory, "entities", "twin-new", {"id": "twin-new", "name": "Twin", "type": "concept", "status": "active"}, body)
    batch = _commit(memory, "Sleep cycle 2026-10-01 (batch 1 of 1)")
    out = asyncio.run(sleep_consolidated.build(memory, [batch]))
    assert [p.id for p in out.removed] == ["twin-old"] and [p.id for p in out.created] == ["twin-new"]
