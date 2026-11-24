"""Past sleeps, a page's change (owner 2026-11-24: "I don't get why <a page> was modified there, what influenced this
change?" and "render normally, not raw markdown"): one classification of what a run did to a page — bookkeeping is no
change, silence is "faded", the rest is substance — read from the commit's patch and from the claim ledger file too, the
cause of each change (the run's conversations, else the step), the structured change of one page, the closed card's
counts equal to the opened card's, and the speed of it. Synthetic bank only (`sleep_changes_synth`, `drain_harness`)."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from drain_harness import git, seed_bank, settings
from sleep_changes_synth import DAY, DAY_BEFORE, big_run, claim_entry, page_text, write_page

from api import main
from api.config import get_settings
from api.services import (claims, claims_ledger, commit_changes, git_service, markdown_parser, page_change,
                          sleep_consolidated, sleep_local)


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    yield
    main.app.dependency_overrides.clear()


def _commit(memory, message, *, date=None):
    git(memory, "add", "-A")
    env = {**os.environ, **({"GIT_COMMITTER_DATE": date, "GIT_AUTHOR_DATE": date} if date else {})}
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", message], cwd=memory, check=True, env=env)
    return git(memory, "rev-parse", "HEAD").strip()


def _message(subject, paths, *, trigger="sleep/extraction", authors=("model-a",), engine=None):
    lines = [f"{p}: updated (source: n/a, trigger: {trigger})" for p in paths]
    return git_service.build_commit_message(subject, lines, authors=list(authors), engine=engine)


def _run_of(memory, commits, monkeypatch, *, window=None):
    """Hand the routes a run: its commit list (the ledger's) and its window."""
    monkeypatch.setattr(sleep_consolidated, "run_commits", lambda _mp, _drain: list(commits))
    start, end = window or (None, None)
    monkeypatch.setattr(sleep_consolidated, "run_window", lambda _mp, _drain: (start, end))
    main.app.dependency_overrides[get_settings] = lambda: settings(memory)
    return TestClient(main.app)


def _now_window():
    now = datetime.now(timezone.utc)
    return (now - timedelta(hours=1)).isoformat(), now.isoformat()


# --- the classification ---------------------------------------------------------------------------------------------


def _patch_of(old: dict, new: dict, *, prose_old="Words.", prose_new="Words.", **fm):
    """The verdicts of one page changed from ``old`` claims to ``new`` claims, by the fast path and by the full
    comparison — which must agree."""
    fm_old, body_old = page_text("p", old, prose=prose_old)
    fm_new, body_new = page_text("p", new, prose=prose_new, **fm)
    import yaml

    def doc(fm, body):
        return "---\n" + yaml.dump(fm, default_flow_style=False, sort_keys=False) + "---\n\n" + body + "\n"

    a, b = doc(fm_old, body_old), doc(fm_new, body_new)
    slow = page_change.classify(a, b)
    import difflib

    diff = "\n".join(difflib.unified_diff(a.split("\n"), b.split("\n"), lineterm="", n=0))
    patch = page_change.parse_patch("diff --git a/entities/p.md b/entities/p.md\n" + diff).get("p") \
        or page_change.PagePatch()
    patch.fence = {"-": page_change.frontmatter_end(a), "+": page_change.frontmatter_end(b)}
    return page_change.fast_verdict(patch), slow


def test_a_moved_decay_watermark_is_bookkeeping_and_silence_is_fade():
    old = [claim_entry("p", 0), claim_entry("p", 1)]
    book = [claim_entry("p", 0, decayed=DAY), claim_entry("p", 1, decayed=DAY)]
    fast, slow = _patch_of(old, book, decayed_through=DAY, last_referenced=DAY, version=2)
    assert fast.kind == slow.kind == page_change.BOOKKEEPING
    faded = [claim_entry("p", 0, decayed=DAY, confidence=0.4), claim_entry("p", 1, decayed=DAY)]
    fast, slow = _patch_of(old, faded, decayed_through=DAY, confidence=0.4)
    assert fast.kind == slow.kind == page_change.FADE
    # a restated fact moves its confidence AND its sources: that is a change
    said = [claim_entry("p", 0, decayed=DAY, confidence=0.9, source_episodes=["ep_2026-10-01_000"]), old[1]]
    fast, slow = _patch_of(old, said)
    assert fast.kind == slow.kind == page_change.SUBSTANCE


def test_a_fact_added_withdrawn_or_changed_is_substance_and_so_is_prose_and_status():
    old = [claim_entry("p", 0), claim_entry("p", 1)]
    for new in ([old[0]], [*old, claim_entry("p", 2)], [{**old[0], "valid_to": "2026-09-30"}, old[1]],
                [{**old[0], "text": "reworded"}, old[1]]):
        fast, slow = _patch_of(old, new)
        assert fast.kind == slow.kind == page_change.SUBSTANCE, new
    fast, slow = _patch_of(old, old, prose_new="Words, and more.")
    assert fast is None and slow.kind == page_change.SUBSTANCE, "prose is the slow path's"
    fast, slow = _patch_of(old, old, status="archived")
    assert fast.kind == slow.kind == page_change.SUBSTANCE and fast.status == ("active", "archived") == slow.status
    fast, slow = _patch_of(old, old, status="decaying")
    assert fast.kind == slow.kind == page_change.FADE, "active to decaying is silence working"


def test_a_claim_moving_between_the_fence_and_its_ledger_is_no_change():
    withdrawn, new, pairs = page_change.pair_claims([claim_entry("p", 0)], [claim_entry("p", 0)])
    assert (withdrawn, new, pairs) == ([], [], [])
    cut, came, pair = page_change.pair_claims([claim_entry("p", 0)], [claim_entry("p", 0, text="said again")])
    assert cut == came == [] and len(pair) == 1, "the same id is one fact, changed"


# --- one run -------------------------------------------------------------------------------------------------------


def _story(tmp_path):
    """A bank whose run read one conversation: a fed page (a fact added, a fact changed, a paragraph edited, a block
    added, an alias), a faded page, a bookkeeping page, a page whose only change is in its ledger file (the stamp, and
    the watermark of its older claims), a page a tail step changed, and a page the person edited inside the window.
    Returns ``(memory, commits, start, end)``."""
    memory = seed_bank(tmp_path, [])
    ep = "ep_2026-10-02_000"
    (memory / "episodes" / f"{ep}.md").write_text(
        "---\nid: ep_2026-10-02_000\nprocessed: false\ntimestamp: '2026-10-02T09:00:00'\ntitle: A talk about the alpha\n"
        "source: mcp\n---\nThe alpha-project now ships on Fridays.\n", encoding="utf-8")
    prose = ("# Fed Page\n\nIntro paragraph about the alpha-project and its shipping day.\n\n## History\n\n"
             "The first line about the thing.\n\n- item one\n- item two\n")
    write_page(memory, "fed-page", [claim_entry("fed-page", 0), claim_entry("fed-page", 1)], prose=prose)
    write_page(memory, "fade-page", [claim_entry("fade-page", 0), claim_entry("fade-page", 1)])
    write_page(memory, "stamp-page", [claim_entry("stamp-page", 0)])
    write_page(memory, "step-page", [claim_entry("step-page", 0)])
    write_page(memory, "user-page", [claim_entry("user-page", 0)])
    old = [claim_entry("ledger-page", 10 + k) for k in range(3)]
    fm, body = page_text("ledger-page", [claim_entry("ledger-page", 0)])
    fm["claims_ledger"] = {"claims": 3, "hash": claims_ledger._stamp([claims._jsonl_line(e) for e in old])[0]["hash"]}
    markdown_parser.write(memory / "entities" / "ledger-page.md", fm, body)
    (memory / "entities" / "ledger-page.claims.jsonl").write_text(
        "\n".join(claims._jsonl_line(e) for e in old) + "\n", encoding="utf-8")
    _commit(memory, "base")
    # the batch's decay commit (cicada): silence and stamps, one page's ledger
    write_page(memory, "fade-page", [claim_entry("fade-page", 0, decayed=DAY, confidence=0.4),
                                     claim_entry("fade-page", 1, decayed=DAY)], decayed_through=DAY, confidence=0.4)
    write_page(memory, "stamp-page", [claim_entry("stamp-page", 0, decayed=DAY)], decayed_through=DAY,
               last_referenced=DAY, version=2)
    moved = [claim_entry("ledger-page", 10 + k, decayed=DAY) for k in range(3)]
    fm["claims_ledger"] = {"claims": 3, "hash": claims_ledger._stamp([claims._jsonl_line(e) for e in moved])[0]["hash"]}
    markdown_parser.write(memory / "entities" / "ledger-page.md", fm, body)
    (memory / "entities" / "ledger-page.claims.jsonl").write_text(
        "\n".join(claims._jsonl_line(e) for e in moved) + "\n", encoding="utf-8")
    decay_paths = [f"entities/{p}.md" for p in ("fade-page", "stamp-page", "ledger-page")]
    _commit(memory, _message("Sleep cycle 2026-10-02 (decay)", decay_paths, trigger="sleep/decay", authors=["cicada"]))
    # the batch: a conversation fed the page
    markdown_parser.write(memory / "episodes" / f"{ep}.md",
                          {"id": ep, "processed": True, "timestamp": "2026-10-02T09:00:00",
                           "title": "A talk about the alpha", "source": "mcp"}, "The alpha-project now ships on Fridays.\n")
    fed_prose = ("# Fed Page\n\nIntro paragraph about the alpha-project and its shipping day, now on Fridays.\n\n"
                 "## History\n\nThe first line about the thing.\n\nA new paragraph the run wrote.\n\n- item one\n")
    added = claim_entry("fed-page", 2, decayed=DAY, evidence=[{"episode": ep, "start": 0, "end": 10, "kind": "user",
                                                               "hash": "abc"}], source_episodes=[ep])
    changed = claim_entry("fed-page", 1, decayed=DAY, valid_to="2026-09-30", confidence=0.6)
    write_page(memory, "fed-page", [claim_entry("fed-page", 0, decayed=DAY), changed, added], prose=fed_prose,
               source_episodes=["ep_2026-09-01_000", ep], aliases=["The Fed"], decayed_through=DAY, version=2)
    batch = _commit(memory, _message("Sleep cycle 2026-10-02 (batch 1 of 1)",
                                     ["entities/fed-page.md", f"episodes/{ep}.md"]))
    # the tail: a source re-check changed one page (its own commit, authored cicada); the person edited another
    write_page(memory, "step-page", [claim_entry("step-page", 0), claim_entry("step-page", 1)])
    step = _commit(memory, _message("Source refresh 2026-10-02", ["entities/step-page.md"], trigger="sync/source",
                                    authors=["cicada"]))
    write_page(memory, "user-page", [claim_entry("user-page", 0), claim_entry("user-page", 1)])
    _commit(memory, _message("Source refresh 2026-10-02", ["entities/user-page.md"], authors=["user"]))
    start, end = _now_window()
    return memory, [batch], start, end, step


def _items(client):
    return client.get("/sleep/runs/story/items").json()


def test_bookkeeping_is_no_change_and_silence_is_its_own_quiet_list(tmp_path, monkeypatch):
    memory, commits, start, end, _step = _story(tmp_path)
    body = _items(_run_of(memory, commits, monkeypatch, window=(start, end)))
    assert sorted(p["id"] for p in body["updated"]) == ["fed-page", "step-page"]
    assert [p["id"] for p in body["faded"]] == ["fade-page"]
    listed = {p["id"] for k in ("created", "updated", "archived", "removed", "faded") for p in body[k]}
    assert not listed & {"stamp-page", "ledger-page", "user-page"}, "bookkeeping and the person's edit are no change"
    assert body["counts"]["updated"] == 2 and body["counts"]["faded"] == 1 and body["counts"]["bookkeeping"] == 2
    assert body["counts"]["bookkeeping"] == 2, "the stamp page and the page whose only change is in its ledger file"


def test_every_listed_page_says_what_caused_it(tmp_path, monkeypatch):
    memory, commits, start, end, _step = _story(tmp_path)
    body = _items(_run_of(memory, commits, monkeypatch, window=(start, end)))
    rows = {p["id"]: p for k in ("updated", "faded") for p in body[k]}
    assert rows["fed-page"]["episodes"] == ["ep_2026-10-02_000"] and rows["fed-page"]["steps"] == ["reading"]
    assert rows["step-page"]["episodes"] == [] and rows["step-page"]["steps"] == ["source_check"]
    assert rows["fade-page"]["steps"] == ["decay"]
    assert set(rows["fed-page"]["steps"] + rows["step-page"]["steps"]) <= set(page_change.STEPS)


def test_the_persons_own_commit_is_never_a_step_of_the_run(tmp_path, monkeypatch):
    memory, commits, start, end, _step = _story(tmp_path)
    write_page(memory, "agent-page", [claim_entry("agent-page", 0)])
    _commit(memory, _message("Merged pages 2026-10-02", ["entities/agent-page.md"], authors=["claude-code"]))
    settles, steps = asyncio.run(sleep_consolidated.window(memory, start, end))
    assert [s for _sha, s in steps] == ["source_check"], "the person's and an agent harness's commits are left out"


def test_a_step_a_commit_cannot_name_is_other_never_a_guess(tmp_path, monkeypatch):
    memory = seed_bank(tmp_path, [])
    write_page(memory, "odd-page", [claim_entry("odd-page", 0)])
    _commit(memory, "base")
    write_page(memory, "odd-page", [claim_entry("odd-page", 0), claim_entry("odd-page", 1)])
    batch = _commit(memory, _message("Sleep cycle 2026-10-02 (batch 1 of 1)", ["entities/odd-page.md"],
                                     trigger="sleep/something-new"))
    out = asyncio.run(sleep_consolidated.build(memory, [batch]))
    assert out.updated[0].steps == ["other"]
    write_page(memory, "odd-page", [claim_entry("odd-page", 0), claim_entry("odd-page", 1), claim_entry("odd-page", 2)])
    no_manifest = _commit(memory, "Sleep cycle 2026-10-02 (batch 1 of 1)")
    assert asyncio.run(sleep_consolidated.build(memory, [no_manifest])).updated[0].steps == ["other"]


def test_a_conversation_that_named_a_page_is_the_substance_of_its_change(tmp_path):
    memory = seed_bank(tmp_path, [])
    write_page(memory, "fed-only", [claim_entry("fed-only", 0)])
    _commit(memory, "base")
    write_page(memory, "fed-only", [claim_entry("fed-only", 0)], source_episodes=["ep_2026-09-01_000", "ep_2026-10-02_000"])
    batch = _commit(memory, _message("Sleep cycle 2026-10-02 (batch 1 of 1)", ["entities/fed-only.md"]))
    out = asyncio.run(sleep_consolidated.build(memory, [batch]))
    assert [p.id for p in out.updated] == ["fed-only"]


def test_a_removed_ledger_line_or_one_added_is_a_change_though_the_page_file_barely_moves(tmp_path):
    memory = seed_bank(tmp_path, [])
    old = [claim_entry("big", 10 + k) for k in range(3)]
    fm, body = page_text("big", [claim_entry("big", 0)])

    def put(entries):
        fm["claims_ledger"] = {"claims": len(entries), "hash": claims_ledger._stamp(
            [claims._jsonl_line(e) for e in entries])[0]["hash"]}
        markdown_parser.write(memory / "entities" / "big.md", fm, body)
        (memory / "entities" / "big.claims.jsonl").write_text(
            "\n".join(claims._jsonl_line(e) for e in entries) + "\n", encoding="utf-8")

    put(old)
    _commit(memory, "base")
    put(old[:-1])   # one older fact withdrawn from the ledger
    batch = _commit(memory, _message("Sleep cycle 2026-10-02 (batch 1 of 1)", ["entities/big.md"]))
    out = asyncio.run(sleep_consolidated.build(memory, [batch]))
    assert [p.id for p in out.updated] == ["big"], "the ledger file is read, not only the page"
    put([claim_entry("big", 10 + k, decayed=DAY) for k in range(2)])   # and only the watermark of what is left
    quiet = _commit(memory, _message("Sleep cycle 2026-10-02 (batch 1 of 1)", ["entities/big.md"], trigger="sleep/decay"))
    again = asyncio.run(sleep_consolidated.build(memory, [quiet]))
    assert again.updated == [] and again.counts["bookkeeping"] == 1


def test_the_closed_cards_counts_are_the_opened_cards(tmp_path, monkeypatch):
    memory, commits, start, end, _step = _story(tmp_path)
    client = _run_of(memory, commits, monkeypatch, window=(start, end))
    body = _items(client)
    fig = asyncio.run(sleep_consolidated.figures(memory, commits, start, end))
    assert fig == {k: body["counts"][k] for k in ("created", "updated", "archived", "removed", "faded")}
    assert fig["updated"] == 2 and fig["faded"] == 1


def test_a_plain_cycles_history_row_counts_real_changes_not_manifest_lines(tmp_path):
    memory, commit = big_run(tmp_path, pages=120)
    main.app.dependency_overrides[get_settings] = lambda: settings(memory)
    client = TestClient(main.app)
    rows = client.get("/sleep/history", params={"limit": 5}).json()
    row = next(r for r in rows if r["commitHash"] == commit)
    assert row["entitiesUpdated"] == 5, "120 files named in the manifest, 5 pages changed in substance"
    assert row["entitiesFaded"] == 16, "18 pages faded; the first changed in substance, the last had only its stamps"
    items = client.get(f"/sleep/history/{commit}/items").json()
    assert items["counts"]["updated"] == row["entitiesUpdated"] and items["counts"]["faded"] == row["entitiesFaded"]
    assert len(items["updated"]) == 5 and len(items["faded"]) == 16


# --- the page's own change -------------------------------------------------------------------------------------------


def test_the_change_of_a_fed_page_is_its_facts_its_prose_and_its_cause(tmp_path, monkeypatch):
    memory, commits, start, end, _step = _story(tmp_path)
    client = _run_of(memory, commits, monkeypatch, window=(start, end))
    res = client.get("/sleep/runs/story/pages/fed-page/change")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["change"] == "updated" and body["empty"] is False
    assert body["page"]["episodes"] == ["ep_2026-10-02_000"] and body["page"]["steps"] == ["reading"]
    # why first: the run's conversation, with its source facets
    conv = body["conversations"][0]
    assert conv["id"] == "ep_2026-10-02_000" and conv["inRun"] is True and conv["origin"]
    # facts: one added (its own evidence names the conversation), one changed (what moved), none withdrawn
    facts = body["facts"]
    assert [f["claim"]["id"] for f in facts["added"]] == ["fed-page-c2"]
    assert facts["added"][0]["conversation"] == "ep_2026-10-02_000" and facts["added"][0]["inRun"] is True
    assert facts["withdrawn"] == [] and facts["counts"] == {"added": 1, "withdrawn": 0, "changed": 1}
    [changed] = facts["changed"]
    assert changed["claim"]["id"] == "fed-page-c1" and changed["claim"]["confidence"] == 0.6
    moved = {c["field"]: c for c in changed["changes"]}
    assert moved["valid_to"]["before"] is None and moved["valid_to"]["after"] == "2026-09-30"
    assert (moved["confidence"]["before"], moved["confidence"]["after"]) == ("0.8", "0.6")
    assert "decayed_through" not in {c["field"] for c in changed["changes"]}
    assert facts["faded"] == 0 and facts["truncated"] is False
    # prose: blocks of the page's own markdown, with the heading each sits under
    blocks = {b["op"]: [] for b in body["prose"]["blocks"]}
    for b in body["prose"]["blocks"]:
        blocks[b["op"]].append(b)
    [edited] = blocks["edited"]
    assert edited["before"].startswith("Intro paragraph") and edited["after"].endswith("now on Fridays.")
    assert [s["op"] for s in edited["segments"]] == ["equal", "removed", "added"] or \
        {"added"} <= {s["op"] for s in edited["segments"]}
    assert "".join(s["text"] for s in edited["segments"] if s["op"] != "removed") == edited["after"]
    assert "".join(s["text"] for s in edited["segments"] if s["op"] != "added") == edited["before"]
    assert [b["markdown"] for b in blocks["added"]] == ["A new paragraph the run wrote."]
    assert blocks["added"][0]["heading"] == "History"
    assert [b["markdown"] for b in blocks["removed"]] == ["- item two"]
    assert body["prose"]["counts"] == {"added": 1, "removed": 1, "edited": 1}
    # other changes in words
    assert [(o["field"], o["added"]) for o in body["other"]] == [("aliases", ["The Fed"])]
    # nothing a person should not read: no bookkeeping key, no frontmatter, no raw diff
    text = json.dumps(body)
    for leak in ("decayed_through", "last_referenced", "learned_on", "claims_ledger", "enrichment", "@@", "\"version\""):
        assert leak not in text, leak


def test_the_change_of_a_step_page_names_the_step_and_a_faded_page_lists_no_fact(tmp_path, monkeypatch):
    memory, commits, start, end, _step = _story(tmp_path)
    client = _run_of(memory, commits, monkeypatch, window=(start, end))
    step = client.get("/sleep/runs/story/pages/step-page/change").json()
    assert step["page"]["episodes"] == [] and step["page"]["steps"] == ["source_check"]
    assert [f["claim"]["id"] for f in step["facts"]["added"]] == ["step-page-c1"]
    assert step["conversations"] == []
    fade = client.get("/sleep/runs/story/pages/fade-page/change").json()
    assert fade["change"] == "faded" and fade["facts"]["faded"] == 1
    assert fade["facts"]["added"] == fade["facts"]["changed"] == [] and fade["empty"] is True


def test_a_page_with_only_bookkeeping_says_so_in_one_flag_and_an_untouched_page_is_a_404(tmp_path, monkeypatch):
    memory, commits, start, end, _step = _story(tmp_path)
    client = _run_of(memory, commits, monkeypatch, window=(start, end))
    for page in ("stamp-page", "ledger-page"):
        body = client.get(f"/sleep/runs/story/pages/{page}/change").json()
        assert body["change"] == "bookkeeping" and body["empty"] is True and body["prose"]["blocks"] == []
        assert body["facts"]["counts"] == {"added": 0, "withdrawn": 0, "changed": 0}
    assert client.get("/sleep/runs/story/pages/nothing-here/change").status_code == 404
    assert client.get("/sleep/runs/story/pages/user-page/change").status_code == 404, "the person's own edit"
    assert client.get("/sleep/runs/story/pages/..%2Fx/change").status_code == 404


def test_a_created_page_is_its_whole_text_and_a_removed_one_its_last(tmp_path, monkeypatch):
    memory = seed_bank(tmp_path, [])
    write_page(memory, "old-page", [claim_entry("old-page", 0)], prose="# Old\n\nIt was here.")
    _commit(memory, "base")
    (memory / "entities" / "old-page.md").unlink()
    write_page(memory, "new-page", [claim_entry("new-page", 0)], prose="# New\n\nIt is here now.")
    batch = _commit(memory, _message("Sleep cycle 2026-10-02 (batch 1 of 1)", ["entities/new-page.md"]))
    client = _run_of(memory, [batch], monkeypatch)
    made = client.get("/sleep/runs/story/pages/new-page/change").json()
    assert made["change"] == "created" and made["other"] == [] and made["empty"] is False
    assert [f["claim"]["id"] for f in made["facts"]["added"]] == ["new-page-c0"]
    assert {b["op"] for b in made["prose"]["blocks"]} == {"added"}
    gone = client.get("/sleep/runs/story/pages/old-page/change").json()
    assert gone["change"] == "removed" and gone["page"]["gone"] is True and gone["page"]["name"] == "Old Page"
    assert {b["op"] for b in gone["prose"]["blocks"]} == {"removed"}
    assert [f["claim"]["id"] for f in gone["facts"]["withdrawn"]] == ["old-page-c0"]


def test_a_plain_cycles_page_change_is_the_same_change(tmp_path, monkeypatch):
    memory, commits, _start, _end, _step = _story(tmp_path)
    main.app.dependency_overrides[get_settings] = lambda: settings(memory)
    client = TestClient(main.app)
    body = client.get(f"/sleep/history/{commits[0]}/pages/fed-page/change").json()
    assert body["change"] == "updated" and [f["claim"]["id"] for f in body["facts"]["added"]] == ["fed-page-c2"]
    assert client.get(f"/sleep/history/{commits[0]}/pages/nothing/change").status_code == 404
    assert client.get("/sleep/history/zzzz/pages/fed-page/change").status_code == 404


def test_the_change_is_bounded_and_says_when_it_was_cut(tmp_path, monkeypatch):
    from api.services import sleep_page_change

    monkeypatch.setattr(sleep_page_change, "MAX_FACTS", 3)
    monkeypatch.setattr(page_change, "MAX_BLOCKS", 2)
    memory = seed_bank(tmp_path, [])
    write_page(memory, "wide", [claim_entry("wide", 0)], prose="# W\n\n" + "\n\n".join(f"Para {i}." for i in range(8)))
    _commit(memory, "base")
    write_page(memory, "wide", [claim_entry("wide", k) for k in range(8)],
               prose="# W\n\n" + "\n\n".join(f"Changed {i}." for i in range(8)))
    batch = _commit(memory, _message("Sleep cycle 2026-10-02 (batch 1 of 1)", ["entities/wide.md"]))
    body = _run_of(memory, [batch], monkeypatch).get("/sleep/runs/story/pages/wide/change").json()
    assert len(body["facts"]["added"]) == 3 and body["facts"]["counts"]["added"] == 7 and body["facts"]["truncated"]
    assert body["truncated"] is True and body["prose"]["truncated"] is True
    assert sum(1 for b in body["prose"]["blocks"] if b["op"] != "context") == 2


# --- the prose blocks themselves --------------------------------------------------------------------------------------


def test_prose_blocks_keep_a_link_whole_and_a_list_item_a_block():
    old = "Intro with [a link](https://example.com/x) and words.\n\n- one\n- two\n- three"
    new = "Intro with [a better link](https://example.com/x) and words.\n\n- one\n- three\n- four"
    out = page_change.prose_blocks(old, new)
    ops = [(b["op"], b["markdown"]) for b in out["blocks"]]
    assert ("removed", "- two") in ops and ("added", "- four") in ops
    edited = next(b for b in out["blocks"] if b["op"] == "edited")
    texts = [s["text"] for s in edited["segments"]]
    assert "[a link](https://example.com/x)" in texts and "[a better link](https://example.com/x)" in texts
    assert page_change.prose_blocks("Same.", "Same.") == {"blocks": [], "counts": {"added": 0, "removed": 0, "edited": 0},
                                                         "truncated": False}


# --- speed and the cache ---------------------------------------------------------------------------------------------


def test_the_classification_is_remembered_outside_the_bank_and_a_second_read_runs_no_git(tmp_path, monkeypatch):
    memory, commit = big_run(tmp_path, pages=150)
    first = asyncio.run(sleep_consolidated.build(memory, [commit]))
    assert (first.counts["updated"], first.counts["faded"]) == (5, 21 - 1)
    cached = sleep_local.bank_dir(memory, create=False) / "changes" / f"{commit}.json"
    assert cached.is_file() and memory not in cached.parents, "outside every bank"
    assert git(memory, "status", "--porcelain").strip() == "", "never in git"
    stored = cached.read_text()
    assert "claim" not in stored.replace("claims", "") or "text" not in stored, "ids and enums only"
    calls = []
    real = git_service._run_git

    async def counting(mp, *args):
        calls.append(args[0])
        return await real(mp, *args)

    monkeypatch.setattr(git_service, "_run_git", counting)
    again = asyncio.run(sleep_consolidated.build(memory, [commit]))
    assert again.counts == first.counts
    assert calls == [], "everything about the commit came from the remembered answer"


def test_a_damaged_or_stale_cache_is_rebuilt_never_an_error(tmp_path):
    memory, commit = big_run(tmp_path, pages=40)
    asyncio.run(sleep_consolidated.build(memory, [commit]))
    cached = sleep_local.bank_dir(memory, create=False) / "changes" / f"{commit}.json"
    cached.write_text("{ not json")
    assert asyncio.run(sleep_consolidated.build(memory, [commit])).counts["updated"] == 5
    cached.write_text(json.dumps({"v": commit_changes.VERSION + 1, "pages": {}, "files": []}))
    assert asyncio.run(sleep_consolidated.build(memory, [commit])).counts["updated"] == 5


def test_two_thousand_pages_are_classified_without_parsing_them(tmp_path, monkeypatch):
    """Measured on the real run's shape: 2,000 touched pages, ~6,000 claims, a few prose edits. The patch is read as
    lines; only the handful of pages the fast path cannot read are parsed (none of the bookkeeping ones)."""
    memory, commit = big_run(tmp_path, pages=2000)
    parsed = []
    real = page_change.read_version

    def counting(text, ledger=None):
        parsed.append(1)
        return real(text, ledger)

    monkeypatch.setattr(page_change, "read_version", counting)
    out = asyncio.run(sleep_consolidated.build(memory, [commit]))
    assert out.counts["updated"] == 5 and out.counts["faded"] == 285 and out.counts["bookkeeping"] == 1710
    assert len(parsed) <= 2 * 6, f"{len(parsed)} page versions parsed: only the pages with prose or lists, two each"
    assert len(out.faded) == sleep_consolidated.CAP and out.truncated is True


def test_the_git_cost_of_a_cold_run_is_a_few_calls_a_commit(tmp_path, monkeypatch):
    memory, commit = big_run(tmp_path, pages=300, big_ledger=True)
    calls = []
    real = git_service._run_git

    async def counting(mp, *args):
        calls.append(args[0])
        return await real(mp, *args)

    monkeypatch.setattr(git_service, "_run_git", counting)
    asyncio.run(sleep_consolidated.build(memory, [commit]))
    assert len(calls) <= 4, calls   # its file list, its decay tie, one patch (+ blobs through cat-file, not _run_git)


def test_the_fast_path_and_the_full_comparison_agree_on_every_page_of_a_run(tmp_path):
    """The patch-line shortcut is only a shortcut: every page of a synthetic run (its ledger page included) gets the
    verdict a full parse of its two versions gives."""
    memory, commit = big_run(tmp_path, pages=240, big_ledger=True, ledger_claims=60)
    cc = asyncio.run(commit_changes.classify_commit(memory, commit))
    assert len(cc["pages"]) == 240
    disagree = []
    for eid, (kind, was, now) in cc["pages"].items():
        old, new, old_ledger, new_ledger = asyncio.run(commit_changes.versions(memory, f"{commit}^", commit, eid))
        full = page_change.classify(old, new, old_ledger, new_ledger)
        if (full.kind, full.status) != (kind, (was, now) if was or now else None):
            disagree.append((eid, kind, full.kind))
    assert disagree == []


def test_a_prose_rule_line_and_a_legacy_yaml_fence_go_to_the_full_comparison_not_a_wrong_verdict(tmp_path):
    memory = seed_bank(tmp_path, [])
    legacy = ("---\nid: legacy\nname: Legacy\ntype: concept\nstatus: active\nconfidence: 0.8\n---\n\nIntro.\n\n---\n\nAfter the rule.\n\n"
              "```claims\n- id: legacy-c0\n  text: an old fact\n  confidence: 0.8\n  decayed_through: '2026-10-01'\n```\n")
    (memory / "entities" / "legacy.md").write_text(legacy, encoding="utf-8")
    _commit(memory, "base")
    (memory / "entities" / "legacy.md").write_text(
        legacy.replace("'2026-10-01'", "'2026-10-02'").replace("After the rule.", "After the rule, reworded."),
        encoding="utf-8")
    batch = _commit(memory, _message("Sleep cycle 2026-10-02 (batch 1 of 1)", ["entities/legacy.md"]))
    cc = asyncio.run(commit_changes.classify_commit(memory, batch))
    assert cc["pages"]["legacy"][0] == page_change.SUBSTANCE
    (memory / "entities" / "legacy.md").write_text(
        (memory / "entities" / "legacy.md").read_text().replace("'2026-10-02'", "'2026-10-03'"), encoding="utf-8")
    quiet = _commit(memory, _message("Sleep cycle 2026-10-03 (batch 1 of 1)", ["entities/legacy.md"], trigger="sleep/decay"))
    assert asyncio.run(commit_changes.classify_commit(memory, quiet))["pages"]["legacy"][0] == page_change.BOOKKEEPING


def test_a_commit_git_cannot_read_leaves_the_cards_own_number(tmp_path, monkeypatch):
    """A card's page count is never made of a commit nobody could read: the entry keeps the number it had."""
    memory, commit = big_run(tmp_path, pages=40)
    main.app.dependency_overrides[get_settings] = lambda: settings(memory)

    async def unreadable(_mp, _commit):
        return None

    monkeypatch.setattr(commit_changes, "classify_commit", unreadable)
    row = next(r for r in TestClient(main.app).get("/sleep/history", params={"limit": 5}).json()
               if r["commitHash"] == commit)
    assert row["entitiesUpdated"] == 40, "the manifest's own file lines, as before"


def test_a_claim_that_will_not_read_is_left_out_never_a_failed_page_and_the_change_answers_304(tmp_path, monkeypatch):
    memory = seed_bank(tmp_path, [])
    write_page(memory, "ragged", [claim_entry("ragged", 0)])
    _commit(memory, "base")
    write_page(memory, "ragged", [claim_entry("ragged", 0), {**claim_entry("ragged", 1), "confidence": "not-a-number"},
                                  claim_entry("ragged", 2)])
    batch = _commit(memory, _message("Sleep cycle 2026-10-02 (batch 1 of 1)", ["entities/ragged.md"]))
    client = _run_of(memory, [batch], monkeypatch)
    res = client.get("/sleep/runs/story/pages/ragged/change")
    assert res.status_code == 200
    assert [f["claim"]["id"] for f in res.json()["facts"]["added"]] == ["ragged-c2"]
    assert client.get("/sleep/runs/story/pages/ragged/change",
                      headers={"If-None-Match": res.headers["ETag"]}).status_code == 304


# --- review round: what the first build got wrong -------------------------------------------------------------------

SAME_SECOND = "2026-10-02T10:00:00+00:00"


def _facts(body):
    return {k: sorted(f["claim"]["id"] for f in body["facts"][k]) for k in ("added", "withdrawn", "changed")}


def test_commits_made_in_one_second_keep_their_order_and_the_page_opens_with_both_changes(tmp_path, monkeypatch):
    """Two batches (and the decay commit before them) can share a commit-second; the page's change is built from the
    run's own commits in the order the run met them, never from a sort git leaves to its tie-break."""
    memory = seed_bank(tmp_path, [])
    write_page(memory, "tie-page", [claim_entry("tie-page", 0)])
    _commit(memory, "base", date="2026-10-01T10:00:00+00:00")
    write_page(memory, "tie-page", [claim_entry("tie-page", 0), claim_entry("tie-page", 1)])
    first = _commit(memory, _message("Sleep cycle 2026-10-02 (batch 1 of 2)", ["entities/tie-page.md"]), date=SAME_SECOND)
    write_page(memory, "tie-page", [claim_entry("tie-page", 0), claim_entry("tie-page", 1), claim_entry("tie-page", 2)])
    second = _commit(memory, _message("Sleep cycle 2026-10-02 (batch 2 of 2)", ["entities/tie-page.md"]), date=SAME_SECOND)
    client = _run_of(memory, [first, second], monkeypatch)
    body = client.get("/sleep/runs/x/pages/tie-page/change").json()
    assert body["change"] == "updated" and body["empty"] is False
    assert _facts(body)["added"] == ["tie-page-c1", "tie-page-c2"]


def test_a_faded_page_is_told_silence_whatever_trigger_its_commit_names(tmp_path, monkeypatch):
    """Claim-level decay is written back with a generic trigger (`sleep/extraction`); that must not read as "changed
    while Sleep read"."""
    memory = seed_bank(tmp_path, [])
    write_page(memory, "quiet-page", [claim_entry("quiet-page", 0)])
    _commit(memory, "base")
    write_page(memory, "quiet-page", [claim_entry("quiet-page", 0, decayed=DAY, confidence=0.4)], decayed_through=DAY,
               confidence=0.4)
    batch = _commit(memory, _message("Sleep cycle 2026-10-02 (batch 1 of 1)", ["entities/quiet-page.md"],
                                     trigger="sleep/extraction"))
    sv = asyncio.run(sleep_consolidated.survey(memory, [batch]))
    assert sv.faded == ["quiet-page"] and sv.fade_steps == {"quiet-page": ["decay"]}
    out = asyncio.run(sleep_consolidated.build(memory, [batch]))
    assert [(p.id, p.steps) for p in out.faded] == [("quiet-page", ["decay"])]


def _page_doc(fm: dict, body: str = "Words.\n") -> str:
    import yaml

    return "---\n" + yaml.dump(fm, default_flow_style=False, sort_keys=False) + "---\n\n" + body


def test_a_page_that_lost_a_conversation_or_whose_links_moved_is_a_change_but_derived_plumbing_is_not():
    base = {"id": "p", "name": "P", "type": "concept", "status": "active", "source_episodes": ["ep_1", "ep_2"],
            "related": [], "decay_rate": 0.1}
    def kind(**moved):
        return page_change.classify(_page_doc(base), _page_doc({**base, **moved})).kind
    assert kind(source_episodes=["ep_1"]) == page_change.SUBSTANCE, "a revision cascade took a conversation away"
    assert kind(related=["other-page"]) == page_change.SUBSTANCE, "a link on the record"
    assert kind(aliases_removed=["Old Name"]) == page_change.SUBSTANCE, "the person's removal is a decision"
    assert kind(sources_removed=["https://example.test/a"]) == page_change.SUBSTANCE
    assert kind(decay_rate=0.2) == page_change.BOOKKEEPING, "derived from decay_class, which is shown when it moves"
    assert kind(decay_class="durable") == page_change.SUBSTANCE
    # the opened card counts it, with no sentence for it
    d = page_change.compare(page_change.read_version(_page_doc(base)),
                            page_change.read_version(_page_doc({**base, "source_episodes": ["ep_1"]})))
    assert d.unfed == ["ep_2"] and d.details == 1 and d.fed == []


def test_the_page_a_person_edited_between_two_batches_is_not_the_runs_change(tmp_path, monkeypatch):
    memory = seed_bank(tmp_path, [])
    write_page(memory, "shared-page", [claim_entry("shared-page", 0)], prose="Original paragraph.")
    _commit(memory, "base", date="2026-10-01T10:00:00+00:00")
    write_page(memory, "shared-page", [claim_entry("shared-page", 0), claim_entry("shared-page", 1)],
               prose="Original paragraph.")
    one = _commit(memory, _message("Sleep cycle 2026-10-02 (batch 1 of 2)", ["entities/shared-page.md"]),
                  date="2026-10-02T10:00:00+00:00")
    write_page(memory, "shared-page", [claim_entry("shared-page", 0), claim_entry("shared-page", 1)],
               prose="PERSON REWROTE THIS PARAGRAPH.")
    _commit(memory, git_service.build_commit_message("Edited by hand", ["entities/shared-page.md: updated"],
                                                     authors=["user"]), date="2026-10-02T11:00:00+00:00")
    write_page(memory, "shared-page", [claim_entry("shared-page", 0), claim_entry("shared-page", 1),
                                       claim_entry("shared-page", 2)], prose="PERSON REWROTE THIS PARAGRAPH.")
    two = _commit(memory, _message("Sleep cycle 2026-10-02 (batch 2 of 2)", ["entities/shared-page.md"]),
                  date="2026-10-02T12:00:00+00:00")
    body = _run_of(memory, [one, two], monkeypatch).get("/sleep/runs/x/pages/shared-page/change").json()
    assert _facts(body)["added"] == ["shared-page-c1", "shared-page-c2"]
    assert body["prose"]["blocks"] == [] and body["prose"]["counts"] == {"added": 0, "removed": 0, "edited": 0}, \
        "the person's rewrite is theirs, not the run's"


def test_a_page_listed_as_updated_never_opens_as_nothing_though_the_run_took_a_fact_back(tmp_path, monkeypatch):
    memory = seed_bank(tmp_path, [])
    write_page(memory, "undo-page", [claim_entry("undo-page", 0)])
    _commit(memory, "base", date="2026-10-01T10:00:00+00:00")
    write_page(memory, "undo-page", [claim_entry("undo-page", 0), claim_entry("undo-page", 1)])
    one = _commit(memory, _message("Sleep cycle 2026-10-02 (batch 1 of 2)", ["entities/undo-page.md"]),
                  date="2026-10-02T10:00:00+00:00")
    write_page(memory, "undo-page", [claim_entry("undo-page", 0)])
    two = _commit(memory, _message("Sleep cycle 2026-10-02 (batch 2 of 2)", ["entities/undo-page.md"]),
                  date="2026-10-02T11:00:00+00:00")
    client = _run_of(memory, [one, two], monkeypatch)
    assert [p["id"] for p in client.get("/sleep/runs/x/items").json()["updated"]] == ["undo-page"]
    body = client.get("/sleep/runs/x/pages/undo-page/change").json()
    assert body["empty"] is False, "the run made the fact and withdrew it: it did both, and says so"
    assert _facts(body)["added"] == ["undo-page-c1"] and _facts(body)["withdrawn"] == ["undo-page-c1"]


def test_an_edit_made_and_put_back_still_lists_what_the_run_changed(tmp_path, monkeypatch):
    memory = seed_bank(tmp_path, [])
    write_page(memory, "flip-page", [claim_entry("flip-page", 0)], prose="First wording.")
    _commit(memory, "base", date="2026-10-01T10:00:00+00:00")
    write_page(memory, "flip-page", [claim_entry("flip-page", 0, valid_to="2026-09-30")], prose="Second wording.")
    one = _commit(memory, _message("Sleep cycle 2026-10-02 (batch 1 of 2)", ["entities/flip-page.md"]),
                  date="2026-10-02T10:00:00+00:00")
    write_page(memory, "flip-page", [claim_entry("flip-page", 0)], prose="First wording.")
    two = _commit(memory, _message("Sleep cycle 2026-10-02 (batch 2 of 2)", ["entities/flip-page.md"]),
                  date="2026-10-02T11:00:00+00:00")
    body = _run_of(memory, [one, two], monkeypatch).get("/sleep/runs/x/pages/flip-page/change").json()
    assert body["empty"] is False
    assert _facts(body)["changed"] == ["flip-page-c0"] and body["prose"]["blocks"]


def test_a_paragraph_that_reads_like_a_stamp_is_prose_not_bookkeeping(tmp_path):
    """`version: 2 of the plan` in the body is a paragraph. Only a line above the frontmatter's closing fence is a
    stamp; the fast path asks git where that is, and a line below it goes to the full comparison."""
    memory = seed_bank(tmp_path, [])

    def put(body):
        markdown_parser.write(memory / "entities" / "plan-page.md",
                              {"id": "plan-page", "name": "Plan Page", "type": "concept", "status": "active",
                               "version": 1}, body)

    put("Notes.\n\nversion: 1 of the plan\nconfidence: low\n")
    _commit(memory, "base")
    put("Notes.\n\nversion: 2 of the plan\nconfidence: high\n")
    one = _commit(memory, _message("Sleep cycle 2026-10-02 (batch 1 of 2)", ["entities/plan-page.md"]))
    put("Notes.\n\nversion: 3 of the plan\nconfidence: high\n")
    two = _commit(memory, _message("Sleep cycle 2026-10-02 (batch 2 of 2)", ["entities/plan-page.md"]))
    for sha in (one, two):
        assert asyncio.run(commit_changes.classify_commit(memory, sha))["pages"]["plan-page"][0] == page_change.SUBSTANCE
    # the same keys in the header are still bookkeeping and silence, without parsing the page
    markdown_parser.write(memory / "entities" / "plan-page.md",
                          {"id": "plan-page", "name": "Plan Page", "type": "concept", "status": "active",
                           "version": 2}, "Notes.\n\nversion: 3 of the plan\nconfidence: high\n")
    stamp = _commit(memory, _message("Sleep cycle 2026-10-03 (batch 1 of 1)", ["entities/plan-page.md"], trigger="sleep/decay"))
    assert asyncio.run(commit_changes.classify_commit(memory, stamp))["pages"]["plan-page"][0] == page_change.BOOKKEEPING


def test_the_frontmatter_fence_is_found_and_a_line_below_it_is_not_a_stamp():
    text = "---\nid: p\nversion: 1\n---\n\nversion: 2 of the plan\n\n---\n\nAfter the rule.\n"
    assert page_change.frontmatter_end(text) == 4
    assert page_change.frontmatter_end("no header\n") is None and page_change.frontmatter_end(None) is None
    patch = page_change.parse_patch(
        "diff --git a/entities/p.md b/entities/p.md\n--- a/entities/p.md\n+++ b/entities/p.md\n"
        "@@ -3 +3 @@\n-version: 1\n+version: 2\n@@ -6 +6 @@\n-version: 1 of the plan\n+version: 2 of the plan\n")["p"]
    assert patch.numbers == [3, 3, 6, 6]
    patch.fence = {"-": 4, "+": 4}
    assert page_change.fast_verdict(patch) is None, "the second pair sits below the fence"
    patch.lines, patch.numbers = patch.lines[:2], patch.numbers[:2]
    assert page_change.fast_verdict(patch).kind == page_change.BOOKKEEPING
    patch.fence = {}
    assert page_change.fast_verdict(patch) is None, "no fence known: the full comparison decides"
