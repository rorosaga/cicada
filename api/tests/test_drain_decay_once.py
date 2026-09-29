"""Decay is charged once per DRAIN, not once per batch (TODO ruling 1; owner,
2026-09-29). Real Stage 3 (entity decay) and real claim reconciliation — only the
LLM boundaries are faked — over a page nothing in the run mentions, sixty days
old: one drain of three batches must charge what ONE cycle charges, where three
separate cycles charge three weeks."""
from __future__ import annotations

import asyncio
from datetime import date, timedelta

import pytest

from drain_harness import episode_ids, install, seed_bank, settings

from api.services import markdown_parser, sleep_cycle
from api.services.claims import Claim, parse_claims, write_claims

OLD = (date.today() - timedelta(days=60)).isoformat()


@pytest.fixture(autouse=True)
def _idle_state():
    s = sleep_cycle.get_sleep_state()
    s.status, s.drain, s.drain_run, s.cancel_requested = "idle", None, False, False
    yield
    s.status, s.drain, s.drain_run, s.cancel_requested = "idle", None, False, False


def _seed_old_page(memory):
    claim = Claim(
        id="clm_old", text="Old topic uses a thing.", subject="old-topic", predicate="uses",
        object="a-thing", observer="agent", confidence=0.9, valid_from=OLD, recorded_at=OLD,
        source_trust="agent_extracted", source_episodes=["ep_2025-01-01_001"],
    )
    body = write_claims("## Summary\nAn old topic nobody mentions.\n", [claim])
    markdown_parser.write(
        memory / "entities" / "old-topic.md",
        {"name": "Old topic", "type": "concept", "status": "active", "confidence": 0.9,
         "created": OLD, "last_referenced": OLD, "decay_class": "active",
         "source_episodes": ["ep_2025-01-01_001"], "version": 1},
        body,
    )


def _bank(tmp_path, name, n=5):
    root = tmp_path / name
    root.mkdir()
    return seed_bank(root, episode_ids(n), extra=_seed_old_page)


def _readings(memory):
    parsed = markdown_parser.parse(memory / "entities" / "old-topic.md")
    claim = [c for c in parse_claims(parsed.body) if c.id == "clm_old"][0]
    return round(float(parsed.frontmatter["confidence"]), 6), round(float(claim.confidence), 6)


def _run(memory, *, drain, cap, times=1):
    for i in range(times):
        asyncio.run(sleep_cycle.run(
            settings(memory, sleep_max_episodes_per_cycle=cap), f"sleep_decay_{i}",
            user_triggered=True, drain=drain))


def test_a_three_batch_drain_charges_one_weeks_decay_where_three_cycles_charge_three(tmp_path, monkeypatch):
    install(monkeypatch)
    one_cycle = _bank(tmp_path, "one-cycle")
    drained = _bank(tmp_path, "drained")
    three_cycles = _bank(tmp_path, "three-cycles")
    before = _readings(one_cycle)
    assert before == (0.9, 0.9)

    _run(one_cycle, drain=False, cap=25)                      # the baseline: one cycle, one charge
    _run(drained, drain=True, cap=2)                          # 5 episodes, 3 batches
    _run(three_cycles, drain=False, cap=2, times=3)           # what per-batch decay would have done

    charged = _readings(one_cycle)
    assert charged[0] < before[0] and charged[1] < before[1], "the baseline really decays both engines"
    assert _readings(drained) == charged, "one drain, one charge — entities and claims alike"
    assert _readings(three_cycles)[0] < charged[0] and _readings(three_cycles)[1] < charged[1]


def test_pages_created_in_earlier_batches_are_not_decayed_by_the_last_one(tmp_path, monkeypatch):
    install(monkeypatch)
    memory = _bank(tmp_path, "fresh")
    _run(memory, drain=True, cap=2)
    for ep in episode_ids(5):
        fm = markdown_parser.parse(memory / "entities" / f"e-{ep}.md").frontmatter
        assert float(fm["confidence"]) == pytest.approx(0.7), ep
        assert fm.get("status", "active") == "active"
