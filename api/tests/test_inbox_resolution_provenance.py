"""G113 slice 1: a resolution commit's trigger names the action the user took.

Before this, every inbox resolution committed as
``entities/<id>.md: updated (trigger: inbox/<kind>/resolved)`` — ``git log``
could say a user *answered* a question but never *what* they answered, so the
grounded-reward signal (did the user agree with the extractor?) was lost at the
moment it was produced. R1: the trigger gains a ``:label`` suffix that no
reader parses; R2: a decay archive/keep reuses the ``status`` manifest word so
``_infer_change_type`` yields the existing ``statusChange`` enum value.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from api.models.schemas import InboxResolveRequest
from api.services import git_service, inbox_service


def run(coro):
    return asyncio.run(coro)


def _git(memory: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(memory), *args], check=True, capture_output=True, text=True
    ).stdout


class _Settings:
    def __init__(self, memory_path: Path):
        self.memory_path = memory_path
        self.inbox_defer_days = 30
        self.litellm_model = "test-model"
        self.inbox_stale_after_days = 90


@pytest.fixture
def memory(tmp_path: Path) -> Path:
    m = tmp_path / "memory"
    (m / "entities").mkdir(parents=True)
    (m / "inbox").mkdir()
    _git(m, "init", "-q")
    _git(m, "config", "user.email", "t@example.com")
    _git(m, "config", "user.name", "t")
    (m / "entities" / "alpha-project.md").write_text(
        "---\ntype: project\nstatus: active\nconfidence: 0.5\ncreated: 2026-01-01\n"
        "last_referenced: 2026-01-01\ndecay_rate: 0.05\nsource_episodes: []\ntags: []\n"
        "related: []\nversion: 1\n---\n# Alpha Project\n"
    )
    (m / "inbox" / "inbox-001.md").write_text(
        "---\nkind: decay\nrequired_input: choice\nstatus: pending\npriority: 0.3\n"
        "entity_id: alpha-project\nentity_name: Alpha Project\n"
        "title: Still interested in Alpha Project?\ncreated_date: 2026-08-01\n---\n"
    )
    _git(m, "add", ".")
    _git(m, "commit", "-q", "-m", "seed")
    return m


# ---------- _action_label (pure) ----------


def test_action_label_decay_passthrough():
    req = InboxResolveRequest(action="archive")
    assert inbox_service._action_label("decay", req, []) == "archive"
    req = InboxResolveRequest(action="keep_active")
    assert inbox_service._action_label("decay", req, []) == "keep_active"


def test_action_label_conflict_pick_and_special_keys():
    opts = [{"key": "0"}, {"key": "1"}, {"key": "both"}, {"key": "neither"}]
    assert inbox_service._action_label(
        "conflict", InboxResolveRequest(action="resolve", option_key="1"), opts
    ) == "pick:1"
    assert inbox_service._action_label(
        "conflict", InboxResolveRequest(action="resolve", option_key="both"), opts
    ) == "both"
    assert inbox_service._action_label(
        "conflict", InboxResolveRequest(action="resolve", option_key="neither"), opts
    ) == "neither"
    assert inbox_service._action_label(
        "conflict", InboxResolveRequest(action="resolve", answer="free text"), opts
    ) == "answer"
    assert inbox_service._action_label(
        "conflict", InboxResolveRequest(action="dismiss"), opts
    ) == "dismiss"


def test_action_label_clarification_and_merge():
    assert inbox_service._action_label(
        "clarification", InboxResolveRequest(action="answer", answer="x"), []
    ) == "answer"
    assert inbox_service._action_label(
        "clarification", InboxResolveRequest(action="resolve", answer="x"), []
    ) == "answer"
    assert inbox_service._action_label(
        "merge_suggestion", InboxResolveRequest(action="merge", merge_target="b"), []
    ) == "merge"
    assert inbox_service._action_label(
        "merge_suggestion", InboxResolveRequest(action="reject"), []
    ) == "reject"
    assert inbox_service._action_label(
        "merge_suggestion", InboxResolveRequest(action="dismiss"), []
    ) == "dismiss"
    assert inbox_service._action_label(
        "clarification", InboxResolveRequest(action="skip"), []
    ) == "skip"


# ---------- resolve() -> commit_resolution ----------


def _head_entry(memory: Path, entity_id: str):
    head = _git(memory, "rev-parse", "HEAD").strip()
    hist = run(git_service.get_entity_history(entity_id, memory))
    matches = [e for e in hist if e.commit_hash == head]
    assert matches, "resolution commit missing from entity history"
    return matches[0]


def test_decay_archive_commit_trigger_and_status_change(memory: Path):
    settings = _Settings(memory)
    out = run(inbox_service.resolve("inbox-001", InboxResolveRequest(action="archive"), settings))
    assert out["status"] == "resolved"
    body = _git(memory, "log", "-1", "--format=%B")
    assert "entities/alpha-project.md: status archived (trigger: inbox/decay/resolved:archive)" in body
    assert "Inbox resolution (decay)" in body
    assert "Cicada-Author: user" in body
    # R2: the existing ``status`` branch of ``_infer_change_type`` yields the
    # ``statusChange`` enum the app already decodes — no new change type.
    assert _head_entry(memory, "alpha-project").change_type == "statusChange"


def test_decay_keep_active_commit_trigger(memory: Path):
    settings = _Settings(memory)
    run(inbox_service.resolve("inbox-001", InboxResolveRequest(action="keep_active"), settings))
    body = _git(memory, "log", "-1", "--format=%B")
    assert "status active (trigger: inbox/decay/resolved:keep_active)" in body
    assert _head_entry(memory, "alpha-project").change_type == "statusChange"


def test_commit_resolution_change_keyword_default_unchanged(memory: Path):
    (memory / "entities" / "alpha-project.md").write_text(
        (memory / "entities" / "alpha-project.md").read_text() + "\nnote\n"
    )
    run(git_service.commit_resolution(memory, "alpha-project", "inbox/clarification/resolved:answer"))
    body = _git(memory, "log", "-1", "--format=%B")
    assert "entities/alpha-project.md: updated (trigger: inbox/clarification/resolved:answer)" in body
    # R1: the subject's kind still comes from ``trigger.split("/")[1]`` — the
    # ``:label`` suffix is inert to it.
    assert "Inbox resolution (clarification)" in body
    assert _head_entry(memory, "alpha-project").change_type == "updated"
