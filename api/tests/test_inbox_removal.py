"""G129 slice 2: a bookmark-removal proposal is a resolvable inbox kind.

Follows the exact end-to-end template G113 slice 3 used for `divergence`/
`normalization` (docs/superpowers/plans/2026-09-02-g113-feedback-ledger.md
Task 3): schema enum, `_required_input_for`, a `_resolve_*` function, the
`resolve()` dispatch, and the ledger's `_verdict`/`recommended_key` tables.
"""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException

from api.models.schemas import InboxKind, InboxResolveRequest
from api.services import inbox_service
from api.services.markdown_parser import parse


def run(coro):
    return asyncio.run(coro)


def _git(memory: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(memory), *args], check=True, capture_output=True, text=True
    ).stdout


def _resolution_commit(memory: Path) -> str:
    """Body of the newest ``Inbox resolution`` commit. Not HEAD: `resolve()`
    commits the regenerated ``_state.md`` as ``cicada`` right after the
    person's commit (final review, 2026-09-03 — see G53), so a naive
    ``git log -1`` on a fresh bank sees the state-snapshot commit instead of
    the resolution. Mirrors the identically-named helper in
    `test_inbox_divergence_normalization.py`, kept local rather than imported
    to avoid coupling one test module's fixtures to another's."""
    return _git(memory, "log", "-1", "--grep=^Inbox resolution", "--format=%B")


class _Settings:
    def __init__(self, memory_path: Path):
        self.memory_path = memory_path
        self.inbox_defer_days = 30
        self.litellm_model = "test-model"
        self.inbox_stale_after_days = 90


def _media_entity(origin: str) -> str:
    return f"""---
type: media
status: active
confidence: 0.9
created: 2026-06-01
last_referenced: 2026-06-01
decay_class: evergreen
decay_rate: 0.0
source_episodes: []
tags: []
related: []
version: 1
origin: {origin}
---
# Example Article
"""


def _removal_item(hint: str | None) -> str:
    hint_line = f"hint: {hint}" if hint else "hint: null"
    return f"""---
kind: removal
required_input: choice
status: pending
priority: 0.4
entity_id: example-article
entity_name: Example Article
title: Still keep Example Article?
created_date: 2026-09-05
question: It was removed from Chrome.
options:
  - key: keep
    label: Keep
  - key: remove
    label: Remove
allow_other: false
allow_defer: true
channel: chrome-bookmarks
browser: Chrome
url: https://example.com/article
synced_at: '2026-09-05T10:00:00Z'
{hint_line}
trigger: sync/bookmark_removal
---
Example Article was removed from Chrome.
"""


@pytest.fixture
def memory(tmp_path: Path) -> Path:
    m = tmp_path / "memory"
    (m / "entities").mkdir(parents=True)
    (m / "inbox").mkdir()
    _git(m, "init", "-q")
    _git(m, "config", "user.email", "t@example.com")
    _git(m, "config", "user.name", "t")
    (m / "entities" / "example-article.md").write_text(_media_entity("chrome-bookmark"))
    (m / "inbox" / "inbox-001.md").write_text(_removal_item(None))
    _git(m, "add", ".")
    _git(m, "commit", "-q", "-m", "seed")
    return m


def test_removal_loads_as_a_choice_item_keep_first_no_recommendation(memory):
    items = inbox_service.load_inbox(memory)
    assert len(items) == 1
    item = items[0]
    assert item.kind == InboxKind.removal
    assert item.required_input.value == "choice"
    assert [o.key for o in item.options] == ["keep", "remove"]
    assert item.allow_other is False
    assert item.allow_defer is True
    assert item.recommended_key is None
    assert all(not o.recommended for o in item.options)
    assert item.channel == "chrome-bookmarks"


def test_removal_cause_is_tier_item_with_the_sync_timestamp(memory):
    item = inbox_service.load_inbox(memory)[0]
    assert item.cause is not None
    assert item.cause.tier == "item"
    assert item.cause.timestamp == "2026-09-05T10:00:00Z"
    assert "Chrome" in item.cause.excerpt


def test_removal_keep_closes_the_item_without_touching_the_entity(memory):
    out = run(inbox_service.resolve(
        "inbox-001", InboxResolveRequest(action="resolve", option_key="keep"), _Settings(memory)
    ))
    assert out["status"] == "resolved"
    assert not (memory / "inbox" / "inbox-001.md").exists()
    fm = parse(memory / "entities" / "example-article.md").frontmatter
    assert fm["status"] == "active"


def test_removal_remove_archives_never_deletes(memory):
    out = run(inbox_service.resolve(
        "inbox-001", InboxResolveRequest(action="resolve", option_key="remove"), _Settings(memory)
    ))
    assert out["status"] == "resolved"
    assert (memory / "entities" / "example-article.md").exists()
    fm = parse(memory / "entities" / "example-article.md").frontmatter
    assert fm["status"] == "archived"
    body = _resolution_commit(memory)
    assert "trigger: inbox/removal/resolved:remove" in body
    assert "status archived" in body
    assert "Cicada-Author: user" in body


def test_removal_bad_option_key_400s(memory):
    with pytest.raises(HTTPException):
        run(inbox_service.resolve(
            "inbox-001", InboxResolveRequest(action="resolve", option_key="archive"), _Settings(memory)
        ))


def test_removal_verdict_is_neutral_for_both_answers():
    assert inbox_service._verdict("removal", "keep", "keep", None, []) == "neutral"
    assert inbox_service._verdict("removal", "remove", "remove", None, []) == "neutral"


def test_removal_never_recommended():
    assert inbox_service.recommended_key("removal", {}, [
        {"key": "keep"}, {"key": "remove"},
    ]) is None


def test_removal_hint_passes_through_when_saved_elsewhere(tmp_path):
    m = tmp_path / "memory"
    (m / "entities").mkdir(parents=True)
    (m / "inbox").mkdir()
    _git(m, "init", "-q"); _git(m, "config", "user.email", "t@example.com"); _git(m, "config", "user.name", "t")
    (m / "entities" / "example-article.md").write_text(_media_entity("safari-bookmark"))
    (m / "inbox" / "inbox-001.md").write_text(_removal_item("Also saved via safari-bookmark"))
    _git(m, "add", "."); _git(m, "commit", "-q", "-m", "seed")
    item = inbox_service.load_inbox(m)[0]
    assert item.hint == "Also saved via safari-bookmark"
