"""G113 slice 2: user resolutions, reconcile audits and dedup verdicts land in the telemetry ledger."""
from __future__ import annotations

import asyncio
import json
import subprocess
from datetime import date
from pathlib import Path

import pytest

from api.models.schemas import InboxResolveRequest
from api.services import inbox_service, telemetry


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def home(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    return tmp_path / "home"


def _events(kind: str) -> list[dict]:
    """Ledger rows of one kind as plain dicts (``read_events`` yields dataclasses)."""
    today = date.today()
    rows = [json.loads(e.to_json()) for e in telemetry.read_events(today.replace(day=1), today)]
    return [e for e in rows if e.get("kind") == kind]


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
status: active
confidence: 0.7
created: 2026-01-01
last_referenced: 2026-06-01
decay_rate: 0.05
source_episodes: []
tags: []
related: []
version: 1
---
# Bob Example

```claims
- id: clm_2026-06-01_a1
  subject: bob-example
  predicate: works-at
  object: alpha-corp
  observer: rodrigo
  source_trust: user_stated
  epistemic: fact
  confidence: 0.9
  valid_from: '2026-06-01'
  recorded_at: '2026-06-01'
  authored_by: gpt-5.4-mini
- id: clm_2026-08-01_b2
  subject: bob-example
  predicate: works-at
  object: beta-corp
  observer: rodrigo
  source_trust: inferred
  epistemic: fact
  confidence: 0.6
  valid_from: '2026-08-01'
  recorded_at: '2026-08-01'
  authored_by: gpt-5.4-nano
```
"""

CONFLICT_ITEM = """---
kind: conflict
required_input: choice
status: pending
priority: 0.6
entity_id: bob-example
entity_name: Bob Example
title: Where does Bob Example work?
created_date: 2026-08-02
predicate: works-at
question: Which is current?
claim_id: clm_2026-08-01_b2
existing_claim_id: clm_2026-06-01_a1
options:
  - key: '0'
    label: alpha-corp
    claim_id: clm_2026-06-01_a1
  - key: '1'
    label: beta-corp
    claim_id: clm_2026-08-01_b2
allow_other: true
allow_defer: true
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
    (m / "inbox" / "inbox-007.md").write_text(CONFLICT_ITEM)
    _git(m, "add", ".")
    _git(m, "commit", "-q", "-m", "seed")
    return m


def test_feedback_kinds_registered():
    for k in ("resolution", "audit", "dedup_verdict"):
        assert k in telemetry.KINDS
        assert k in telemetry.FEEDBACK_KINDS
    assert "llm_call" not in telemetry.FEEDBACK_KINDS


def test_verdict_table():
    v = inbox_service._verdict
    assert v("decay", "archive", None, None, []) == "agreed"
    assert v("decay", "keep_active", None, None, []) == "overruled"
    assert v("decay", "remind_later", None, None, []) == "neutral"
    opts = [{"key": "0", "claim_id": "old"}, {"key": "1", "claim_id": "new"}]
    assert v("conflict", "pick:1", "1", "new", opts) == "agreed"
    assert v("conflict", "pick:0", "0", "new", opts) == "overruled"
    assert v("conflict", "both", "both", "new", opts) == "neutral"
    assert v("conflict", "neither", "neither", "new", opts) == "overruled"
    assert v("conflict", "answer", None, "new", opts) == "overruled"
    assert v("clarification", "answer", None, None, []) == "agreed"
    assert v("clarification", "dismiss", None, None, []) == "overruled"
    assert v("merge_suggestion", "merge", None, None, []) == "agreed"
    assert v("merge_suggestion", "reject", None, None, []) == "overruled"
    assert v("merge_suggestion", "dismiss", None, None, []) == "neutral"
    assert v("divergence", "pick:1", "1", None, []) == "agreed"
    assert v("divergence", "pick:0", "0", None, []) == "overruled"
    assert v("divergence", "pick:2", "2", None, []) == "neutral"
    assert v("normalization", "pick:0", "0", None, []) == "agreed"
    assert v("normalization", "pick:1", "1", None, []) == "overruled"
    assert v("conflict", "defer", None, None, []) == "neutral"
    assert v("clarification", "skip", None, None, []) == "neutral"


def test_conflict_pick_emits_resolution_event(home, memory):
    settings = _Settings(memory)
    run(inbox_service.resolve("inbox-007", InboxResolveRequest(action="resolve", option_key="1"), settings))
    evs = _events("resolution")
    assert len(evs) == 1
    e = evs[0]
    assert e["stage"] == "feedback" and e["billing"] == "free" and e["invocations"] == 0
    assert e["bank"] == "memory"
    r = e["refs"]
    assert r["item_id"] == "inbox-007" and r["kind"] == "conflict" and r["predicate"] == "works-at"
    assert r["entity_id"] == "bob-example" and r["action"] == "pick:1" and r["option_key"] == "1"
    assert r["verdict"] == "agreed"
    assert r["winner_claim_id"] == "clm_2026-08-01_b2"
    assert r["loser_claim_ids"] == ["clm_2026-06-01_a1"]
    assert r["extractor_confidence"] == pytest.approx(0.6)
    assert r["extractor_model"] == "gpt-5.4-nano"
    assert isinstance(r["item_age_days"], int) and r["item_age_days"] >= 0
    # privacy rail: no claim text / labels in the event
    blob = json.dumps(e)
    assert "alpha-corp" not in blob and "beta-corp" not in blob and "Bob Example" not in blob


def test_defer_emits_neutral_resolution_event(home, memory):
    settings = _Settings(memory)
    run(inbox_service.resolve("inbox-007", InboxResolveRequest(action="defer", remind_days=5), settings))
    evs = _events("resolution")
    assert len(evs) == 1
    assert evs[0]["refs"]["action"] == "defer" and evs[0]["refs"]["verdict"] == "neutral"


def test_ledger_off_never_blocks_resolve(memory, monkeypatch, tmp_path):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "h"))
    monkeypatch.setenv("CICADA_TELEMETRY", "off")
    settings = _Settings(memory)
    out = run(inbox_service.resolve("inbox-007", InboxResolveRequest(action="resolve", option_key="0"), settings))
    assert out["status"] == "resolved"


def test_audit_events_from_reconcile(home, tmp_path):
    from api.services.telemetry import record_audit
    record_audit(
        [{"action": "supersede", "closed": "clm_a", "by": "clm_b"},
         {"action": "rejected", "kept": "clm_a", "dropped": "clm_c"}],
        subject_hint="bob-example", bank="memory", stage="reconcile",
    )
    evs = _events("audit")
    assert [e["refs"]["action"] for e in evs] == ["supersede", "rejected"]
    assert evs[0]["refs"] == {"action": "supersede", "subject": "bob-example", "closed": "clm_a", "by": "clm_b"}
    assert evs[1]["refs"] == {"action": "rejected", "subject": "bob-example", "kept": "clm_a", "dropped": "clm_c"}
    assert all(e["stage"] == "reconcile" and e["billing"] == "free" for e in evs)


def test_dedup_sweep_emits_verdict_per_pair(home, tmp_path):
    from api.services.dedup_sweep import dedup_sweep
    m = tmp_path / "memory"
    (m / "entities").mkdir(parents=True)
    (m / "inbox").mkdir()
    _git(m, "init", "-q")
    _git(m, "config", "user.email", "t@example.com")
    _git(m, "config", "user.name", "t")
    for slug, name in (("alpha-project", "Alpha Project"), ("alpha-proj", "Alpha Proj")):
        (m / "entities" / f"{slug}.md").write_text(
            "---\ntype: project\nstatus: active\nconfidence: 0.8\ncreated: 2026-01-01\n"
            f"last_referenced: 2026-06-01\ndecay_rate: 0.05\nsource_episodes: []\ntags: []\nrelated: []\nversion: 1\n---\n# {name}\n"
        )
    _git(m, "add", ".")
    _git(m, "commit", "-q", "-m", "seed")

    def judge(*_a, **_k):
        return {"verdict": "unsure", "confidence": 0.4, "winner": None}

    # dedup_sweep is synchronous (api/services/dedup_sweep.py:49); judge_fn(a_text, b_text, a, b) -> dict
    result = dedup_sweep(m, _Settings(m), judge_fn=judge, seed_pairs=[("alpha-project", "alpha-proj")], dry_run=True)
    assert result["nudged"] == [("alpha-project", "alpha-proj")]
    evs = _events("dedup_verdict")
    assert len(evs) == 1
    r = evs[0]["refs"]
    assert {r["a"], r["b"]} == {"alpha-project", "alpha-proj"}
    assert r["verdict"] == "unsure" and r["confidence"] == pytest.approx(0.4) and r["applied"] == "nudged"


def test_stats_by_connection_excludes_feedback_rows(home):
    from api.services.consumption_stats import stats
    telemetry.record(telemetry.UsageEvent(kind="llm_call", stage="extract", connection="anthropic", engine="litellm",
                                          model="m", bank="memory", input_tokens=10, output_tokens=5, cost_usd=0.01))
    telemetry.record(telemetry.UsageEvent(kind="resolution", stage="feedback", bank="memory", invocations=0,
                                          billing="free", refs={"item_id": "inbox-001"}))
    # stats is async: stats(memory_path, *, range_, today) (consumption_stats.py:188); rows are {"connection": name, ...}
    out = run(stats(Path("/nonexistent"), range_="month", today=date.today()))
    names = [row["connection"] for row in out["by_connection"]]
    assert names == ["anthropic"]
    assert any(row["stage"] == "feedback" for row in out["by_stage"])
