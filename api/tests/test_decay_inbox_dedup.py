"""Track B — a decay question is asked once, refreshed while open, and capped.

Before this, every Sleep cycle wrote a new "Still tracking X?" item for every
page still below the nudge threshold (and one per fading claim), so a long
multi-cycle drain buried the inbox in copies of the same question. The rules:

* an entity with an OPEN decay item (pending or deferred) is refreshed, never
  given a second one — the entity path and the claim path share the key;
* one batch of claim nudges on a page opens at most one item;
* a cycle opens at most ``decay_inbox_cap_per_cycle`` NEW items, lowest
  confidence first, and the overflow is counted, never silently dropped.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
from types import SimpleNamespace

from api.services import inbox_generator, markdown_parser, sleep_cycle
from api.services.inbox_generator import DecayBudget


def _bank(tmp_path, entities=()):
    memory = tmp_path / "memory"
    (memory / "inbox").mkdir(parents=True)
    (memory / "entities").mkdir(parents=True)
    for eid in entities:
        markdown_parser.write(
            memory / "entities" / f"{eid}.md",
            {"name": eid.title(), "type": "tool", "status": "decaying", "confidence": 0.35},
            "body",
        )
    return memory


def _entity_nudge(eid, conf=0.35):
    return {"id": eid, "action": "decay_nudge", "new_confidence": conf, "new_status": "decaying",
            "source_episode": "", "trigger": "sleep/decay"}


def _claim_nudge(eid, claim_id, conf):
    return {"id": eid, "action": "decay_nudge", "entity": {"name": eid.title()},
            "new_confidence": conf, "claim_id": claim_id, "source_episode": "ep_2026-01-01_001",
            "trigger": "sleep/decay"}


def _items(memory):
    out = []
    for p in sorted((memory / "inbox").glob("inbox-*.md")):
        out.append((p, markdown_parser.parse(p).frontmatter))
    return out


def _generate(memory, changes, budget=None):
    asyncio.run(inbox_generator.generate(changes, [], memory, decay_budget=budget))


def test_a_repeated_entity_decay_nudge_refreshes_the_open_item(tmp_path):
    memory = _bank(tmp_path, ["alpha-tool"])
    _generate(memory, [_entity_nudge("alpha-tool", 0.38)])
    ((first, fm1),) = _items(memory)
    assert fm1["kind"] == "decay" and fm1["priority"] == 0.38
    fm1_created = fm1["created_date"]

    budget = DecayBudget()
    _generate(memory, [_entity_nudge("alpha-tool", 0.33)], budget)
    ((second, fm2),) = _items(memory)          # still exactly one item
    assert second == first
    assert fm2["priority"] == 0.33             # follows the page
    assert fm2["created_date"] == fm1_created  # keeps its age
    assert budget.written == 0 and not budget.deferred


def test_a_refresh_that_changes_nothing_writes_nothing(tmp_path):
    memory = _bank(tmp_path, ["alpha-tool"])
    _generate(memory, [_entity_nudge("alpha-tool", 0.38)])
    _generate(memory, [_entity_nudge("alpha-tool", 0.38)])   # stamps updated_date once
    (path, _fm) = _items(memory)[0]
    os.utime(path, (1, 1))
    budget = DecayBudget()
    _generate(memory, [_entity_nudge("alpha-tool", 0.38)], budget)
    assert path.stat().st_mtime == 1
    assert budget.refreshed == 0


def test_an_answered_decay_item_lets_the_next_cycle_ask_again(tmp_path):
    memory = _bank(tmp_path, ["alpha-tool"])
    _generate(memory, [_entity_nudge("alpha-tool")])
    ((path, fm),) = _items(memory)
    fm["status"] = "resolved"
    markdown_parser.write(path, fm, "")
    _generate(memory, [_entity_nudge("alpha-tool")])
    assert len(_items(memory)) == 2, "only an OPEN item suppresses the question"


def test_a_deferred_item_is_still_open(tmp_path):
    memory = _bank(tmp_path, ["alpha-tool"])
    _generate(memory, [_entity_nudge("alpha-tool")])
    ((path, fm),) = _items(memory)
    fm["remind_after"] = "2099-01-01"        # status stays `pending`
    markdown_parser.write(path, fm, "")
    _generate(memory, [_entity_nudge("alpha-tool")])
    assert len(_items(memory)) == 1


def test_claim_nudges_on_one_page_open_a_single_item_keyed_to_the_lowest(tmp_path):
    memory = _bank(tmp_path, ["alpha-tool"])
    nudges = [_claim_nudge("alpha-tool", f"clm_{i}", c) for i, c in enumerate([0.39, 0.31, 0.36, 0.37])]
    budget = DecayBudget()
    out = inbox_generator.write_claim_nudges(nudges, memory, decay_budget=budget)
    ((_p, fm),) = _items(memory)
    assert out["written"] == 1 and budget.written == 1
    assert fm["priority"] == 0.31
    assert fm["claim_id"] == "clm_1", "the lowest-confidence claim opened it"

    # A later cycle's claim nudges refresh that item; none is added.
    again = inbox_generator.write_claim_nudges([_claim_nudge("alpha-tool", "clm_9", 0.29)], memory)
    assert again["written"] == 0
    ((_p, fm),) = _items(memory)
    assert fm["priority"] == 0.29


def test_entity_and_claim_paths_share_the_open_item(tmp_path):
    memory = _bank(tmp_path, ["alpha-tool"])
    _generate(memory, [_entity_nudge("alpha-tool", 0.38)])
    budget = DecayBudget()
    inbox_generator.write_claim_nudges([_claim_nudge("alpha-tool", "clm_1", 0.30)], memory,
                                       decay_budget=budget)
    assert len(_items(memory)) == 1
    assert budget.refreshed == 1 and budget.written == 0


def test_the_cap_opens_the_lowest_confidence_first_and_counts_the_overflow(tmp_path):
    ids = [f"tool-{i:02d}" for i in range(15)]
    memory = _bank(tmp_path, ids)
    # tool-00 is the healthiest (0.39), tool-14 the most decayed (0.25).
    changes = [_entity_nudge(eid, round(0.39 - 0.01 * i, 2)) for i, eid in enumerate(ids)]
    budget = DecayBudget(10)
    _generate(memory, changes, budget)
    opened = {fm["entity_id"] for _p, fm in _items(memory)}
    assert len(opened) == 10 and budget.written == 10
    assert opened == set(ids[5:]), "the ten most decayed pages win the slots"
    assert budget.deferred == set(ids[:5]), "the overflow is counted by name, not dropped"

    # Next cycle: the open ones refresh for free, the five deferred now fit.
    budget2 = DecayBudget(10)
    _generate(memory, changes, budget2)
    assert {fm["entity_id"] for _p, fm in _items(memory)} == set(ids)
    assert budget2.written == 5 and not budget2.deferred


def test_the_cap_is_shared_between_the_entity_and_claim_paths(tmp_path):
    memory = _bank(tmp_path, ["one", "two", "three", "four"])
    budget = DecayBudget(3)
    _generate(memory, [_entity_nudge("one", 0.30), _entity_nudge("two", 0.31)], budget)
    out = inbox_generator.write_claim_nudges(
        [_claim_nudge("three", "clm_3", 0.32), _claim_nudge("four", "clm_4", 0.33)],
        memory, decay_budget=budget,
    )
    assert out["written"] == 1 and budget.written == 3
    assert budget.deferred == {"four"}


def test_a_zero_cap_defers_everything_and_writes_no_decay_item(tmp_path):
    memory = _bank(tmp_path, ["one"])
    budget = DecayBudget(0)
    _generate(memory, [_entity_nudge("one")], budget)
    assert _items(memory) == [] and budget.deferred == {"one"}


def test_no_budget_means_unlimited_but_still_deduplicated(tmp_path):
    ids = [f"tool-{i:02d}" for i in range(12)]
    memory = _bank(tmp_path, ids)
    changes = [_entity_nudge(eid) for eid in ids]
    _generate(memory, changes)
    _generate(memory, changes)
    assert len(_items(memory)) == 12


def test_conflict_nudges_are_not_capped(tmp_path):
    memory = _bank(tmp_path, ["one"])
    conflict = {"id": "one", "action": "conflict_nudge", "entity": {"name": "One"},
                "options": [{"key": "a", "label": "x"}], "question": "Which?"}
    _generate(memory, [conflict], DecayBudget(0))
    assert [fm["kind"] for _p, fm in _items(memory)] == ["conflict"]


# --- the wired cycle ---------------------------------------------------------


def test_the_cycle_applies_the_cap_and_reports_the_overflow(tmp_path, monkeypatch):
    from test_sleep_cycle_claims_wired import _patch_boundaries, _seed_bank, _settings

    memory = _seed_bank(tmp_path)
    ids = [f"tool-{i}" for i in range(5)]
    for eid in ids:
        markdown_parser.write(
            memory / "entities" / f"{eid}.md",
            {"name": eid, "type": "tool", "status": "active", "confidence": 0.5,
             "last_referenced": "2026-05-01", "created": "2026-01-01"}, "body",
        )
    resolved = [_entity_nudge(eid, 0.39 - 0.01 * i) for i, eid in enumerate(ids)]
    extracted = [{
        "episode_id": "ep_2026-06-17_001", "episode_timestamp": "2026-06-17T10:00:00",
        "origin": "claude-code", "relationships": [],
        "entities": [{"name": "Tool 0", "type": "tool", "source_episode": "ep_2026-06-17_001"}],
    }]
    _patch_boundaries(monkeypatch, memory, extracted=extracted, resolved_changes=resolved,
                      resolved_edges=[])
    settings = _settings(memory)
    settings.decay_inbox_cap_per_cycle = 2
    settings.inbox_stale_after_days = 90

    asyncio.run(sleep_cycle.run(settings, cycle_id="2026-06-17_decay_cap"))
    assert len([1 for _p, fm in _items(memory) if fm["kind"] == "decay"]) == 2
    assert sleep_cycle._state.decay_nudges_deferred == 3

    markdown_parser.write(
        memory / "episodes" / "ep_2026-06-18_001.md",
        {"id": "ep_2026-06-18_001", "processed": False, "source": "mcp",
         "timestamp": "2026-06-18T10:00:00"}, "More talk.",
    )
    asyncio.run(sleep_cycle.run(settings, cycle_id="2026-06-18_decay_cap"))
    kinds = [fm["kind"] for _p, fm in _items(memory)]
    assert kinds.count("decay") == 4, "a second cycle opens the next two; the first two only refresh"
    assert sleep_cycle._state.decay_nudges_deferred == 1


def test_the_sleep_run_row_carries_the_decay_counts(tmp_path, monkeypatch):
    from api.config import Settings
    from api.services import git_service, telemetry

    events: list = []

    async def fake_status(_path):
        return ""

    async def fake_commit(_path, _message):
        return "abc1234"

    monkeypatch.setattr(git_service, "porcelain_status", fake_status)
    monkeypatch.setattr(git_service, "commit_changes", fake_commit)
    monkeypatch.setattr(telemetry, "record", events.append)
    monkeypatch.setattr(sleep_cycle._state, "decay_nudges_deferred", 4)
    monkeypatch.setattr(sleep_cycle._state, "decay_nudges_refreshed", 6)
    asyncio.run(sleep_cycle._finalize(
        tmp_path, "sleep_1", [], Settings(llm_mode="agent"),
        engine="claude-cli", connection="claude-plan", billing="subscription", authors=["claude-sonnet-5"],
    ))
    (row,) = [e for e in events if e.kind == "sleep_run"]
    assert (row.refs["decay_nudges_deferred"], row.refs["decay_nudges_refreshed"]) == (4, 6)


# --- one item, every claim it covered (review) --------------------------------


def _claims_page(memory, eid, claim_ids):
    from api.services.claims import Claim, write_claims

    claims = [
        Claim(id=cid, subject=eid, predicate="uses", text=f"thing {cid}", confidence=0.2,
              valid_from="2026-01-01", valid_to="2026-06-01")
        for cid in claim_ids
    ]
    markdown_parser.write(
        memory / "entities" / f"{eid}.md",
        {"name": eid.title(), "type": "tool", "status": "decaying", "confidence": 0.3},
        write_claims("body", claims),
    )


def test_refreshes_record_every_fading_claim_on_the_item(tmp_path):
    memory = _bank(tmp_path, ["alpha-tool"])
    inbox_generator.write_claim_nudges(
        [_claim_nudge("alpha-tool", "clm_1", 0.31), _claim_nudge("alpha-tool", "clm_2", 0.36)], memory
    )
    inbox_generator.write_claim_nudges([_claim_nudge("alpha-tool", "clm_3", 0.30)], memory)
    ((_p, fm),) = _items(memory)
    assert fm["claim_id"] == "clm_1"
    assert inbox_generator.decay_claim_ids(fm) == ["clm_1", "clm_2", "clm_3"]

    # A refresh naming a claim already covered changes nothing.
    os.utime(_p, (1, 1))
    inbox_generator.write_claim_nudges([_claim_nudge("alpha-tool", "clm_2", 0.30)], memory)
    assert _p.stat().st_mtime == 1


def test_an_entity_path_item_takes_its_first_claim_from_a_later_nudge(tmp_path):
    memory = _bank(tmp_path, ["alpha-tool"])
    _generate(memory, [_entity_nudge("alpha-tool", 0.38)])
    inbox_generator.write_claim_nudges([_claim_nudge("alpha-tool", "clm_7", 0.30)], memory)
    ((_p, fm),) = _items(memory)
    assert inbox_generator.decay_claim_ids(fm) == ["clm_7"]


def test_keep_reaches_every_claim_the_item_covered(tmp_path):
    from api.models.schemas import InboxResolveRequest
    from api.services import inbox_service
    from api.services.claims import parse_claims

    memory = _bank(tmp_path)
    _claims_page(memory, "alpha-tool", ["clm_1", "clm_2", "clm_3"])
    inbox_generator.write_claim_nudges(
        [_claim_nudge("alpha-tool", "clm_1", 0.31), _claim_nudge("alpha-tool", "clm_2", 0.36)], memory
    )
    ((_p, fm),) = _items(memory)
    settings = SimpleNamespace(memory_path=memory, inbox_defer_days=30, litellm_model="test-model",
                               inbox_stale_after_days=90)
    for args in (("init", "-q"), ("config", "user.email", "t@example.com"), ("config", "user.name", "t"),
                 ("add", "-A"), ("commit", "-q", "-m", "seed")):
        subprocess.run(["git", *args], cwd=memory, check=True, capture_output=True)
    asyncio.run(inbox_service.resolve(fm.get("id") or _p.stem, InboxResolveRequest(action="keep_active"), settings))

    page = markdown_parser.parse(memory / "entities" / "alpha-tool.md")
    by_id = {c.id: c for c in parse_claims(page.body)}
    assert by_id["clm_1"].valid_to is None and by_id["clm_2"].valid_to is None
    assert by_id["clm_1"].confidence >= 0.6 and by_id["clm_2"].confidence >= 0.6
    assert by_id["clm_3"].valid_to == "2026-06-01", "a claim the item never covered is untouched"
