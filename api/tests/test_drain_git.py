"""A drain's commits (owner, 2026-09-29). Real git: each batch is one
`Sleep cycle` commit that carries only ITS episodes; the G85 `(decay)` commit
exists once, in the last batch, `cicada`-authored; nothing is left dirty."""
from __future__ import annotations

import asyncio
import re

import pytest

from drain_harness import episode_ids, git, install, seed_bank, settings

from api.services import markdown_parser, sleep_cycle


@pytest.fixture(autouse=True)
def _idle_state():
    s = sleep_cycle.get_sleep_state()
    s.status, s.drain, s.drain_run, s.cancel_requested = "idle", None, False, False
    yield
    s.status, s.drain, s.drain_run, s.cancel_requested = "idle", None, False, False


def _seed_old_page(memory):
    markdown_parser.write(
        memory / "entities" / "old-topic.md",
        {"name": "Old topic", "type": "concept", "status": "active", "confidence": 0.9,
         "created": "2026-01-01", "last_referenced": "2026-01-01", "decay_class": "active",
         "source_episodes": ["ep_2025-01-01_001"], "version": 1},
        "## Summary\nAn old topic nobody mentions.\n",
    )


def test_a_drain_is_one_commit_per_batch_plus_one_decay_commit_in_the_last(tmp_path, monkeypatch):
    ids = episode_ids(7)
    memory = seed_bank(tmp_path, ids, extra=_seed_old_page)
    install(monkeypatch)
    asyncio.run(sleep_cycle.run(
        settings(memory, sleep_max_episodes_per_cycle=3), "sleep_git", user_triggered=True, drain=True))

    log = git(memory, "log", "--format=%H%x1f%s%x1f%an", "--reverse").strip().splitlines()[1:]   # past the seed
    rows = [tuple(line.split("\x1f")) for line in log]
    subjects = [s for _h, s, _a in rows]
    assert [bool(re.match(r"^Sleep cycle \d{4}-\d\d-\d\d \(batch \d of 3\)$", s)) for s in subjects
            if not s.endswith("(decay)")] == [True, True, True]
    assert sum(s.endswith("(decay)") for s in subjects) == 1, "the G85 split appears once"
    assert subjects[-2].endswith("(decay)") and subjects[-1].endswith("(batch 3 of 3)"), \
        "committed before the last batch's own commit"
    decay_hash = [h for h, s, _a in rows if s.endswith("(decay)")][0]
    assert "Cicada-Author: cicada" in git(memory, "log", "-1", "--format=%B", decay_hash)
    assert git(memory, "show", "--name-only", "--format=", decay_hash).split() == ["entities/old-topic.md"]

    # each batch commit carries only its own batch's episodes
    batch_hashes = [h for h, s, _a in rows if "(batch" in s]
    for hash_, batch_ids in zip(batch_hashes, (ids[0:3], ids[3:6], ids[6:7])):
        touched = git(memory, "show", "--name-only", "--format=", hash_).split()
        episodes = {Path.split("/")[-1][:-3] for Path in touched if Path.startswith("episodes/")}
        assert episodes == set(batch_ids), hash_
        body = git(memory, "log", "-1", "--format=%B", hash_)
        assert "Cicada-Session:" in body
    assert git(memory, "status", "--porcelain").strip() == "", "the tree is clean at the end"


def test_a_scheduled_cycle_commits_once_with_the_plain_subject(tmp_path, monkeypatch):
    memory = seed_bank(tmp_path, episode_ids(5))
    install(monkeypatch)
    asyncio.run(sleep_cycle.run(settings(memory, sleep_max_episodes_per_cycle=2), "sleep_sched", user_triggered=False))
    subjects = [s for s in git(memory, "log", "--format=%s").splitlines() if s.startswith("Sleep cycle")]
    assert len(subjects) == 1 and "(batch" not in subjects[0]
