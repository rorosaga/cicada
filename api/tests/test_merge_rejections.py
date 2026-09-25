"""G113 slice 3b: a rejected merge pair is remembered and never re-proposed."""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest
import yaml

from api.models.schemas import InboxResolveRequest
from api.services import inbox_service, merge_rejections
from api.services.clarification_manager import ClarificationManager


def run(coro):
    # Full-suite order dependency: some earlier test resets the thread's
    # default event loop policy to `None` (e.g. anything that goes through
    # `asyncio.run()`, which unsets it on exit), so a bare
    # `asyncio.get_event_loop()` — the pattern the rest of this suite's
    # sync-wrapper tests use (`test_inbox_resolution_provenance.py`,
    # `test_feedback_ledger.py`) — raises "no current event loop" depending
    # on collection order rather than on anything this file does. Fall back
    # to minting a fresh loop when that happens.
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def _git(memory: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(memory), *args], check=True, capture_output=True, text=True).stdout


def _resolution_commit_body(memory: Path) -> str:
    """Body of the newest ``Inbox resolution`` commit, not HEAD: `resolve()`
    commits the regenerated `_state.md` as `cicada` right after the person's
    commit (G53 final review), so a plain `git log -1` would read the
    projection refresh instead — mirrors `test_inbox_resolution_provenance.py`'s
    own `_resolution_commit` helper."""
    out = _git(memory, "log", "-1", "--grep=^Inbox resolution", "--format=%B")
    return out


class _Settings:
    def __init__(self, memory_path: Path):
        self.memory_path = memory_path
        self.inbox_defer_days = 30
        self.litellm_model = "test-model"
        self.inbox_stale_after_days = 90


def _entity(m: Path, slug: str, name: str) -> None:
    (m / "entities" / f"{slug}.md").write_text(
        "---\ntype: project\nstatus: active\nconfidence: 0.8\ncreated: 2026-01-01\n"
        f"last_referenced: 2026-06-01\ndecay_rate: 0.05\nsource_episodes: []\ntags: []\nrelated: []\nversion: 1\n---\n# {name}\n"
    )


MERGE_ITEM = """---
kind: merge_suggestion
required_input: merge
status: pending
priority: 0.5
entity_id: alpha-project
entity_name: Alpha Project
title: Possible duplicate of Alpha Proj
created_date: 2026-08-02
merge_target_hint: alpha-proj
uncertainty_type: Possible duplicate of Alpha Proj
---
"""


@pytest.fixture
def memory(tmp_path: Path) -> Path:
    m = tmp_path / "memory"
    (m / "entities").mkdir(parents=True)
    (m / "inbox").mkdir()
    _git(m, "init", "-q")
    _git(m, "config", "user.email", "t@example.com")
    _git(m, "config", "user.name", "t")
    _entity(m, "alpha-project", "Alpha Project")
    _entity(m, "alpha-proj", "Alpha Proj")
    (m / "inbox" / "inbox-020.md").write_text(MERGE_ITEM)
    _git(m, "add", ".")
    _git(m, "commit", "-q", "-m", "seed")
    return m


def test_add_and_query_is_order_insensitive(tmp_path):
    m = tmp_path / "m"
    m.mkdir()
    assert not merge_rejections.is_rejected(m, "b", "a")
    merge_rejections.add_rejected(m, "b", "a")
    assert merge_rejections.is_rejected(m, "a", "b")
    assert merge_rejections.load_rejected(m) == {("a", "b")}
    merge_rejections.add_rejected(m, "a", "b")  # idempotent
    data = yaml.safe_load((m / merge_rejections.FILE).read_text())
    assert data == {"rejected": [["a", "b"]]}


def test_reject_resolution_records_pair_and_commits(memory):
    out = run(inbox_service.resolve("inbox-020", InboxResolveRequest(action="reject"), _Settings(memory)))
    assert out["status"] == "resolved"
    assert not (memory / "inbox" / "inbox-020.md").exists()
    assert merge_rejections.is_rejected(memory, "alpha-project", "alpha-proj")
    body = _resolution_commit_body(memory)
    assert "trigger: inbox/merge_suggestion/resolved:reject" in body
    assert "_merge_rejected.yaml" in body
    assert (memory / "entities" / "alpha-project.md").exists() and (memory / "entities" / "alpha-proj.md").exists()


def test_reject_uses_explicit_merge_target_when_no_hint(memory):
    p = memory / "inbox" / "inbox-020.md"
    p.write_text(MERGE_ITEM.replace("merge_target_hint: alpha-proj\n", ""))
    run(inbox_service.resolve("inbox-020", InboxResolveRequest(action="reject", merge_target="Alpha Proj"), _Settings(memory)))
    assert merge_rejections.is_rejected(memory, "alpha-project", "alpha-proj")


def test_reject_on_non_merge_kind_is_400(memory):
    (memory / "inbox" / "inbox-021.md").write_text(MERGE_ITEM.replace("kind: merge_suggestion", "kind: clarification"))
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        run(inbox_service.resolve("inbox-021", InboxResolveRequest(action="reject"), _Settings(memory)))
    assert exc.value.status_code == 400


def test_clarification_manager_skips_rejected_pair(memory):
    merge_rejections.add_rejected(memory, "alpha-project", "alpha-proj")
    (memory / "inbox" / "inbox-020.md").unlink()
    mgr = ClarificationManager(memory)
    # `create`'s real signature (api/services/clarification_manager.py:47-55) is
    # (entity_name, source_episode, uncertainty_type, suggested_classification,
    # suggested_confidence, source_context, source_episode_timestamp=None) — a
    # plan draft with `question=`/`context=` kwargs does not match and raises
    # TypeError. `uncertainty_type` starting "Possible duplicate of Alpha Proj"
    # is what routes this into the merge_suggestion / duplicate-pair path.
    created = mgr.create(
        entity_name="Alpha Project",
        source_episode="ep_2026-08-02_001",
        uncertainty_type="Possible duplicate of Alpha Proj",
        suggested_classification="project",
        suggested_confidence=0.6,
        source_context="",
    )
    assert created is None
    assert list((memory / "inbox").glob("inbox-*.md")) == []


def test_dedup_sweep_skips_rejected_pair(memory):
    from api.services.dedup_sweep import dedup_sweep
    merge_rejections.add_rejected(memory, "alpha-project", "alpha-proj")
    calls = []

    def judge(*a):
        calls.append(a)
        return {"verdict": "same", "confidence": 0.99, "winner": "alpha-project"}

    result = dedup_sweep(memory, _Settings(memory), judge_fn=judge, seed_pairs=[("alpha-project", "alpha-proj")], dry_run=True)
    assert calls == []
    assert result["proposed"] == [] and result["skipped_rejected"] == 1
