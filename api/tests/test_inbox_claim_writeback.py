"""G113 slice 3c: decay keep_active refreshes the claim; remind_later defers; clarification answers become claims."""
from __future__ import annotations

import asyncio
import subprocess
from datetime import date, timedelta
from pathlib import Path

import pytest

from api.models.schemas import InboxResolveRequest
from api.services import inbox_service
from api.services.claims import parse_claims


def run(coro):
    return asyncio.run(coro)


def _git(memory: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(memory), *args], check=True, capture_output=True, text=True).stdout


class _Settings:
    def __init__(self, memory_path: Path):
        self.memory_path = memory_path
        self.inbox_defer_days = 30
        self.litellm_model = "test-model"
        self.inbox_stale_after_days = 90


ENTITY = """---
type: person
status: decaying
confidence: 0.35
created: 2026-01-01
last_referenced: 2026-03-01
decay_rate: 0.05
source_episodes: []
tags: []
related: []
version: 1
---
# Bob Example

```claims
- id: clm_2026-03-01_a1
  subject: bob-example
  predicate: works-at
  object: alpha-corp
  observer: rodrigo
  source_trust: inferred
  epistemic: fact
  confidence: 0.3
  valid_from: '2026-03-01'
  valid_to: '2026-08-01'
  recorded_at: '2026-03-01'
  authored_by: gpt-5.4-nano
```
"""

DECAY_WITH_CLAIM = """---
kind: decay
required_input: choice
status: pending
priority: 0.3
entity_id: bob-example
entity_name: Bob Example
title: Is it still true that Bob Example works-at alpha-corp?
created_date: 2026-08-02
claim_id: clm_2026-03-01_a1
trigger: sleep/decay
---
"""

CLARIFICATION = """---
kind: clarification
required_input: freetext
status: pending
priority: 0.5
entity_id: bob-example
entity_name: Bob Example
title: Who is Bob Example?
created_date: 2026-08-02
predicate: role
question: What is Bob Example's role?
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
    (m / "entities" / "bob-example.md").write_text(ENTITY)
    (m / "inbox" / "inbox-030.md").write_text(DECAY_WITH_CLAIM)
    (m / "inbox" / "inbox-031.md").write_text(CLARIFICATION)
    _git(m, "add", ".")
    _git(m, "commit", "-q", "-m", "seed")
    return m


def _claims(memory: Path):
    return {c.id: c for c in parse_claims((memory / "entities" / "bob-example.md").read_text())}


def test_keep_active_refreshes_claim(memory):
    run(inbox_service.resolve("inbox-030", InboxResolveRequest(action="keep_active"), _Settings(memory)))
    c = _claims(memory)["clm_2026-03-01_a1"]
    assert c.confidence >= 0.6
    assert c.valid_to is None  # re-opened: it had faded, not been superseded
    text = (memory / "entities" / "bob-example.md").read_text()
    assert "status: active" in text
    assert not (memory / "inbox" / "inbox-030.md").exists()


def test_keep_active_never_reopens_a_superseded_claim(memory):
    p = memory / "entities" / "bob-example.md"
    p.write_text(p.read_text().replace("  recorded_at: '2026-03-01'\n", "  recorded_at: '2026-03-01'\n  superseded_by: clm_other\n"))
    run(inbox_service.resolve("inbox-030", InboxResolveRequest(action="keep_active"), _Settings(memory)))
    c = _claims(memory)["clm_2026-03-01_a1"]
    assert c.valid_to == "2026-08-01" or str(c.valid_to) == "2026-08-01"
    assert c.confidence >= 0.6


def test_remind_later_is_a_seven_day_defer(memory):
    out = run(inbox_service.resolve("inbox-030", InboxResolveRequest(action="remind_later"), _Settings(memory)))
    assert out["status"] == "deferred"
    assert out["remindAfter"] == str(date.today() + timedelta(days=7))
    text = (memory / "inbox" / "inbox-030.md").read_text()
    assert "remind_after:" in text and "snooze_until" not in text
    items = inbox_service.load_inbox(memory)
    assert all(i.id != "inbox-030" for i in items)
    body = _git(memory, "log", "-1", "--format=%B")
    assert "trigger: inbox/deferred" in body


def test_clarification_answer_writes_user_claim(memory):
    run(inbox_service.resolve("inbox-031", InboxResolveRequest(action="answer", answer="lead engineer"), _Settings(memory)))
    claims = list(_claims(memory).values())
    new = [c for c in claims if c.predicate == "role"]
    assert len(new) == 1
    c = new[0]
    assert c.object == "lead engineer"
    assert c.source_trust == "user_stated" and c.authored_by == "user" and c.origin == "clarification"
    assert getattr(c, "object_kind", "literal") == "literal"
    assert c.confidence == pytest.approx(0.95)
    assert c.id.startswith(f"clm_{date.today()}_user_")
    text = (memory / "entities" / "bob-example.md").read_text()
    assert "lead engineer" in text.split("```claims")[0]  # prose still appended


def test_clarification_answer_without_predicate_uses_description(memory):
    p = memory / "inbox" / "inbox-031.md"
    p.write_text(CLARIFICATION.replace("predicate: role\n", ""))
    run(inbox_service.resolve("inbox-031", InboxResolveRequest(action="answer", answer="a colleague"), _Settings(memory)))
    assert any(c.predicate == "description" and c.object == "a colleague" for c in _claims(memory).values())
