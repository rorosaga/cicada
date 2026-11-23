"""G104 slice 3 (T4): the Corrections record — what a run's corrections reached, folded per batch into the run summary,
drawn by ``GET /sleep/runs/{id}``, one dated History line on each page touched, and the Sleep commit body.

Ids, counts and enums only; synthetic names throughout."""
from __future__ import annotations

import asyncio
import json
import subprocess
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api import main
from api.config import get_settings
from api.services import (
    corrections_record as cr, git_service, markdown_parser, sleep_cycle, sleep_drain, sleep_run_detail, sleep_runs,
)
from api.tests import test_revision_cascade_sleep as cs

CASCADE = {
    "revised": ["ep_2026-11-03_001"],
    "pages_archived": [{"page": "zed-unknown", "episode": "ep_2026-11-03_001", "claims": ["c1", "c2"]}],
    "pages_kept": [{"page": "gamma-board", "episode": "ep_2026-11-03_001", "support": "other_conversation",
                    "claims": ["c3"]}],
    "aliases_dropped": [{"page": "alpha-project", "episode": "ep_2026-11-03_001", "count": 2}],
    "held": {"lines_removed": 1, "episodes_left": 0, "claims_dropped": 2, "claims_withdrawn": 1},
    "questions": [{"item": "inbox-050", "kind": "clarification", "episode": "ep_2026-11-03_001", "why": "name_gone"}],
    "paths": [], "counts": {},
}


# --------------------------------------------------------------------------- the pure record


def test_a_batch_entry_holds_ids_counts_and_enums_only():
    entry = cr.batch_entry(CASCADE, withdrawn=3, superseded=2, rewritten=4)
    assert entry == {
        "revised": ["ep_2026-11-03_001"], "claims_withdrawn": 3, "claims_superseded": 2, "passages_rewritten": 4,
        "pages_archived": [{"page": "zed-unknown", "episode": "ep_2026-11-03_001"}],
        "pages_kept": [{"page": "gamma-board", "episode": "ep_2026-11-03_001", "support": "other_conversation"}],
        "aliases_dropped": 2, "held_dropped": 3, "questions_withdrawn": 1}


def test_no_revision_is_no_entry_never_zeros():
    assert cr.batch_entry(None, withdrawn=0, superseded=0, rewritten=0) is None
    assert cr.batch_entry({"revised": [], "held": {}}, withdrawn=0, superseded=0, rewritten=0) is None
    assert cr.merge(None, None) is None and cr.public(None) is None and cr.public({}) is None


def test_a_claim_the_revision_replaced_alone_is_a_correction_too():
    entry = cr.batch_entry({"revised": [], "held": {}}, withdrawn=0, superseded=1, rewritten=0,
                           revised_out={"c1": "ep_2026-11-03_001"})
    assert entry["revised"] == ["ep_2026-11-03_001"] and entry["claims_superseded"] == 1


def test_batches_sum_and_a_page_is_listed_once():
    a = cr.batch_entry(CASCADE, withdrawn=3, superseded=2, rewritten=4)
    b = cr.batch_entry({**CASCADE, "revised": ["ep_2026-11-04_001"],
                        "pages_archived": [{"page": "zed-unknown", "episode": "ep_2026-11-04_001", "claims": []},
                                           {"page": "beta-site", "episode": "ep_2026-11-04_001", "claims": []}]},
                       withdrawn=1, superseded=0, rewritten=1)
    total = cr.merge(a, b)
    assert total["revised"] == ["ep_2026-11-03_001", "ep_2026-11-04_001"]
    assert (total["claims_withdrawn"], total["claims_superseded"], total["passages_rewritten"]) == (4, 2, 5)
    assert [p["page"] for p in total["pages_archived"]] == ["zed-unknown", "beta-site"]
    assert total["aliases_dropped"] == 4 and total["questions_withdrawn"] == 2
    assert cr.merge(None, a) == a and cr.merge(a, None) == a


def test_the_commit_lines_name_the_episodes_and_the_pages_and_match_no_manifest_line():
    lines = cr.commit_lines(cr.batch_entry(CASCADE, withdrawn=0, superseded=0, rewritten=0))
    assert lines == ["corrections: revised ep_2026-11-03_001", "corrections: archived zed-unknown"]
    assert cr.commit_lines(None) == []
    body = "Sleep cycle\n\n" + "\n".join(lines) + "\nentities/zed-unknown.md: updated (source: n/a, trigger: x)"
    manifest = git_service._parse_cycle_body(body) if hasattr(git_service, "_parse_cycle_body") else None
    if manifest is not None:
        assert manifest.files == ["entities/zed-unknown.md"]


# --------------------------------------------------------------------------- History


def _page(memory, page, body="## History\n- 2026-11-01: First said.\n", **fm):
    (memory / "entities").mkdir(exist_ok=True)
    markdown_parser.write(memory / "entities" / f"{page}.md", {"id": page, "name": page, "type": "concept", **fm},
                          f"# {page}\n\n{body}")


def test_every_page_a_correction_touched_gets_one_dated_line_naming_the_conversation(tmp_path):
    for p in ("zed-unknown", "gamma-board", "alpha-project", "untouched"):
        _page(tmp_path, p)
    paths = cr.write_history(tmp_path, CASCADE, today="2026-11-23")
    assert sorted(paths) == ["entities/alpha-project.md", "entities/gamma-board.md", "entities/zed-unknown.md"]
    for p in ("zed-unknown", "gamma-board", "alpha-project"):
        body = markdown_parser.parse(tmp_path / "entities" / f"{p}.md").body
        lines = [ln for ln in body.splitlines() if "ep_2026-11-03_001" in ln]
        assert len(lines) == 1 and lines[0].startswith("- 2026-11-23:"), (p, lines)
    assert "ep_2026" not in markdown_parser.parse(tmp_path / "entities" / "untouched.md").body
    # Run again: the same fold writes nothing new.
    assert cr.write_history(tmp_path, CASCADE, today="2026-11-23") == []


def test_a_page_revision_prose_already_wrote_a_line_for_is_not_given_a_second():
    # skip names (page, episode); the other page still gets its line.
    assert cr.history_events(CASCADE, skip={"zed-unknown": {"ep_2026-11-03_001"}}).keys() == {
        "gamma-board", "alpha-project"}


def test_a_kept_page_that_lost_nothing_has_no_line():
    cascade = {**CASCADE, "pages_archived": [], "aliases_dropped": [],
               "pages_kept": [{"page": "gamma-board", "episode": "ep_2026-11-03_001", "support": "owner", "claims": []}]}
    assert cr.history_events(cascade) == {}


# --------------------------------------------------------------------------- the run summary


def _ds(corrections, drain_id="run_x"):
    ds = sleep_drain.DrainState(drain_id=drain_id)
    ds.corrections = corrections
    return ds


def test_legs_fold_into_the_run_without_counting_a_leg_twice(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    a = cr.batch_entry(CASCADE, withdrawn=3, superseded=2, rewritten=4)
    ds1 = _ds(a)
    sleep_runs.record_leg(tmp_path, ds1, state="running")
    sleep_runs.record_leg(tmp_path, ds1, state="paused")             # the same leg again: no double count
    assert sleep_runs.get(tmp_path, "run_x")["corrections"]["claims_withdrawn"] == 3
    ds2 = _ds(cr.batch_entry(CASCADE, withdrawn=1, superseded=0, rewritten=0))   # a Continue: a fresh state
    sleep_runs.record_leg(tmp_path, ds2, state="running")
    sleep_runs.record_leg(tmp_path, ds2, state="finished")
    assert sleep_runs.get(tmp_path, "run_x")["corrections"]["claims_withdrawn"] == 4


def test_a_run_with_no_revision_records_no_corrections(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    sleep_runs.record_leg(tmp_path, _ds(None), state="finished")
    assert sleep_runs.get(tmp_path, "run_x").get("corrections") is None


def test_the_run_detail_carries_the_corrections_and_which_pages_can_still_be_restored(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_TELEMETRY", "off")
    _page(tmp_path, "zed-unknown", status="archived", archived_by={"reason": "revision", "episode": "ep_2026-11-03_001"})
    _page(tmp_path, "beta-site", status="active")      # restored since
    entry = cr.batch_entry({**CASCADE, "pages_archived": [
        {"page": "zed-unknown", "episode": "ep_2026-11-03_001", "claims": []},
        {"page": "beta-site", "episode": "ep_2026-11-03_001", "claims": []}]}, withdrawn=3, superseded=2, rewritten=4)
    sleep_runs.record_leg(tmp_path, _ds(entry), state="finished")
    detail = asyncio.run(sleep_run_detail.build(tmp_path, "run_x"))
    c = detail.corrections
    assert (c.conversations_revised, c.claims_withdrawn, c.claims_superseded, c.passages_rewritten) == (1, 3, 2, 4)
    assert [(p.page, p.restorable) for p in c.pages_archived] == [("zed-unknown", True), ("beta-site", False)]
    assert c.pages_kept[0].support == "other_conversation" and c.aliases_dropped == 2 and c.questions_withdrawn == 1
    assert c.held_dropped == 3
    sleep_runs.record_leg(tmp_path, _ds(None, "run_y"), state="finished")
    assert asyncio.run(sleep_run_detail.build(tmp_path, "run_y")).corrections is None


def test_the_route_serves_corrections_camel_cased_under_a_new_shape(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_TELEMETRY", "off")
    (tmp_path / "entities").mkdir()
    sleep_runs.record_leg(tmp_path, _ds(cr.batch_entry(CASCADE, withdrawn=3, superseded=2, rewritten=4)),
                          state="finished")
    main.app.dependency_overrides[get_settings] = lambda: SimpleNamespace(memory_path=tmp_path)
    try:
        r = TestClient(main.app).get("/sleep/runs/run_x")
    finally:
        main.app.dependency_overrides.clear()
    assert r.status_code == 200
    body = r.json()["corrections"]
    assert body["conversationsRevised"] == 1 and body["claimsWithdrawn"] == 3 and body["passagesRewritten"] == 4
    assert body["pagesArchived"][0]["page"] == "zed-unknown" and "claims" not in body["pagesArchived"][0]
    assert sleep_run_detail.SHAPE != "plan-share-1"


# --------------------------------------------------------------------------- end to end through the cycle


def _commit_messages(monkeypatch) -> list[str]:
    seen: list[str] = []
    real = git_service.build_commit_message

    def capture(*args, **kwargs):
        message = real(*args, **kwargs)
        seen.append(message)
        return message

    monkeypatch.setattr(git_service, "build_commit_message", capture)
    return seen


def test_a_correction_is_in_the_batch_record_the_page_history_and_the_commit_body(tmp_path, monkeypatch):
    memory = cs._meeting_bank(tmp_path, monkeypatch)
    messages = _commit_messages(monkeypatch)
    cs._revise(memory, cs.EP_MEET, cs.MEET_V1, cs.MEET_V2)
    cs._run(memory, monkeypatch, cs._meet_answer)
    batch = sleep_cycle._state.corrections_batch
    assert batch["revised"] == [cs.EP_MEET]
    assert [p["page"] for p in batch["pages_archived"]] == ["zed-unknown"]
    assert batch["claims_withdrawn"] >= 1
    page = markdown_parser.parse(memory / "entities" / "zed-unknown.md")
    lines = [ln for ln in page.body.splitlines() if ln.startswith("- ") and cs.EP_MEET in ln]
    assert len(lines) == 1, page.body
    message = next(m for m in messages if m.startswith("Sleep cycle"))
    assert f"corrections: revised {cs.EP_MEET}" in message and "corrections: archived zed-unknown" in message
    head, _, trailers = message.rpartition("\n\n")
    assert trailers.splitlines() and all(t.startswith("Cicada-") for t in trailers.splitlines())
    assert "corrections:" in head


def test_a_page_kept_by_another_conversation_still_says_it_was_corrected(tmp_path, monkeypatch):
    memory = cs._meeting_bank(tmp_path, monkeypatch, lunch=True)
    cs._revise(memory, cs.EP_MEET, cs.MEET_V1, cs.MEET_V2)
    cs._run(memory, monkeypatch, cs._meet_answer)
    batch = sleep_cycle._state.corrections_batch
    assert batch["pages_archived"] == [] and batch["pages_kept"][0]["support"] == "other_conversation"
    page = markdown_parser.parse(memory / "entities" / "zed-unknown.md")
    assert len([ln for ln in page.body.splitlines() if ln.startswith("- ") and cs.EP_MEET in ln]) == 1


def test_a_batch_with_no_revision_has_no_record(tmp_path, monkeypatch):
    memory = cs._meeting_bank(tmp_path, monkeypatch)
    cs._write(memory, "ep_2026-11-05_001", "user: Nothing here.", processed=False)
    cs._run(memory, monkeypatch, cs._meet_answer)
    assert sleep_cycle._state.corrections_batch is None


def test_a_drain_sums_its_batches_corrections_into_the_run_and_a_plain_run_has_none(tmp_path, monkeypatch):
    memory = cs._meeting_bank(tmp_path, monkeypatch)
    cs._revise(memory, cs.EP_MEET, cs.MEET_V1, cs.MEET_V2)
    real_run = sleep_cycle.run

    async def as_drain(settings, cycle_id, **kw):
        return await real_run(settings, cycle_id, user_triggered=True, drain=True)

    monkeypatch.setattr(sleep_cycle, "run", as_drain)
    cs._run(memory, monkeypatch, cs._meet_answer)
    summary = sleep_runs.get(memory, "g104_cascade")
    c = summary["corrections"]
    assert c["revised"] == [cs.EP_MEET] and [p["page"] for p in c["pages_archived"]] == ["zed-unknown"]
    assert c["claims_withdrawn"] >= 1
    assert json.dumps(c).count("Zed") == 0                    # ids, counts and enums: no name, no words


def test_a_drain_with_no_revision_has_no_corrections(tmp_path, monkeypatch):
    memory = cs._meeting_bank(tmp_path, monkeypatch)
    cs._write(memory, "ep_2026-11-05_001", "user: Nothing here.")
    real_run = sleep_cycle.run

    async def as_drain(settings, cycle_id, **kw):
        return await real_run(settings, cycle_id, user_triggered=True, drain=True)

    monkeypatch.setattr(sleep_cycle, "run", as_drain)
    cs._run(memory, monkeypatch, cs._meet_answer)
    assert sleep_runs.get(memory, "g104_cascade")["corrections"] is None


def test_a_page_revision_prose_wrote_history_for_gets_no_second_line_for_that_conversation(tmp_path, monkeypatch):
    from api.services import revision_prose
    from api.tests import test_revision_prose as rp

    memory, _first, _before = rp._setup(tmp_path, monkeypatch)
    reports: list = []
    real = revision_prose.run

    async def spy(*a, **kw):
        reports.append(await real(*a, **kw))
        return reports[-1]

    monkeypatch.setattr(revision_prose, "run", spy)
    rp._run(memory, monkeypatch, [])
    (report,) = reports
    assert report.history_pages.get("alpha-project"), "prose wrote a History line for this page"
    history = rp._history(rp._prose(memory))
    for episode in report.history_pages["alpha-project"]:
        assert not [ln for ln in history if episode in ln and "was corrected" in ln], (episode, history)
    assert sleep_cycle._state.corrections_batch is not None      # the record itself still exists
