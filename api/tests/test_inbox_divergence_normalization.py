"""G113 slice 3: divergence and normalization inbox items load and resolve."""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest
import yaml

from api.models.schemas import InboxKind, InboxResolveRequest
from api.services import inbox_service
from api.services.claims import parse_claims
from api.services.predicates import RUNTIME_FILE, load_normalizer


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
  authored_by: user
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
- id: clm_2026-08-01_c3
  subject: bob-example
  predicate: built-with
  object: rust
  observer: rodrigo
  source_trust: inferred
  epistemic: fact
  confidence: 0.6
  valid_from: '2026-08-01'
  recorded_at: '2026-08-01'
  authored_by: gpt-5.4-nano
```
"""

DIVERGENCE = """---
kind: divergence
required_input: choice
status: pending
priority: 0.5
entity_id: bob-example
entity_name: Bob Example
title: I'm reading something different about Bob Example
created_date: 2026-08-02
options:
  - Keep my statement (alpha-corp)
  - Update to beta-corp
  - Both true — different context
claim_id: clm_2026-08-01_b2
existing_claim_id: clm_2026-06-01_a1
trigger: sleep/conflict_resolution
---
You said Bob Example works-at 'alpha-corp'; I'm now reading 'beta-corp'. Keep your statement?
"""

NORMALIZATION = """---
kind: normalization
required_input: choice
status: pending
priority: 0.3
entity_id: bob-example
entity_name: Bob Example
title: Confirm a predicate fold for Bob Example
created_date: 2026-08-02
options:
  - Correct fold
  - Wrong fold — keep separate
claim_id: clm_2026-08-01_c3
raw_predicate: uses stack
canonical_predicate: built-with
trigger: sleep/conflict_resolution
---
Predicate 'uses stack' was auto-folded to canonical 'built-with'. Confirm this fold is correct.
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
    (m / "inbox" / "inbox-010.md").write_text(DIVERGENCE)
    (m / "inbox" / "inbox-011.md").write_text(NORMALIZATION)
    (m / RUNTIME_FILE).write_text(yaml.safe_dump(
        {"synonyms": {"uses stack": "built-with", "uses-stack": "built-with"}, "canonical": ["built-with", "works-at"]}
    ))
    _git(m, "add", ".")
    _git(m, "commit", "-q", "-m", "seed")
    return m


def _claims(memory: Path) -> dict[str, object]:
    text = (memory / "entities" / "bob-example.md").read_text()
    return {c.id: c for c in parse_claims(text)}


def _resolution_commit(memory: Path) -> str:
    """Body of the newest ``Inbox resolution`` commit. Not HEAD: `resolve()`
    commits the regenerated ``_state.md`` as ``cicada`` right after the
    person's commit (final review, 2026-09-03 — see G53), so a naive
    ``git log -1`` on a fresh bank sees the state-snapshot commit instead of
    the resolution. Mirrors the ``_resolution_commit`` helper already used in
    `test_inbox_resolution_provenance.py`, kept local here rather than
    imported to avoid coupling one test module's fixtures to another's.
    """
    out = _git(memory, "log", "-1", "--grep=^Inbox resolution", "--format=%B")
    return out


def test_kinds_exist_and_load(memory):
    assert InboxKind("divergence") and InboxKind("normalization")
    assert inbox_service._required_input_for("divergence") == "choice"
    assert inbox_service._required_input_for("normalization") == "choice"
    items = inbox_service.load_inbox(memory)
    kinds = {i.id: i.kind for i in items}
    assert kinds["inbox-010"] == InboxKind.divergence
    assert kinds["inbox-011"] == InboxKind.normalization
    div = next(i for i in items if i.id == "inbox-010")
    # G115 R6 (already shipped, ahead of this task): the item's initial
    # highlight is Sleep's own proposal, reordered to the front by
    # `_item_from_file`'s `recommended_key` call — R3 grades divergence key
    # "1" ("update") `agreed`, so it leads even though the file on disk lists
    # "0" first. The file itself is untouched (this is a read-time
    # projection); `{o.key for o in ...}` below is the on-disk-order-agnostic
    # assertion this task actually cares about.
    assert [o.key for o in div.options] == ["1", "0", "2"]
    assert {o.key for o in div.options} == {"0", "1", "2"}


def test_divergence_keep_mine_closes_new_claim(memory):
    out = run(inbox_service.resolve("inbox-010", InboxResolveRequest(action="resolve", option_key="0"), _Settings(memory)))
    assert out["status"] == "resolved"
    c = _claims(memory)
    assert c["clm_2026-08-01_b2"].valid_to is not None
    assert c["clm_2026-08-01_b2"].superseded_by == "clm_2026-06-01_a1"
    assert c["clm_2026-06-01_a1"].valid_to is None
    assert c["clm_2026-06-01_a1"].confidence >= 0.9
    assert not (memory / "inbox" / "inbox-010.md").exists()
    body = _resolution_commit(memory)
    assert "trigger: inbox/divergence/resolved:pick:0" in body


def test_divergence_update_closes_existing_claim(memory):
    run(inbox_service.resolve("inbox-010", InboxResolveRequest(action="resolve", option_key="1"), _Settings(memory)))
    c = _claims(memory)
    assert c["clm_2026-06-01_a1"].valid_to is not None
    assert c["clm_2026-06-01_a1"].superseded_by == "clm_2026-08-01_b2"
    assert c["clm_2026-08-01_b2"].valid_to is None
    assert c["clm_2026-08-01_b2"].confidence >= 0.9


def test_divergence_both_keeps_both_with_context(memory):
    run(inbox_service.resolve("inbox-010", InboxResolveRequest(action="resolve", option_key="2"), _Settings(memory)))
    c = _claims(memory)
    assert c["clm_2026-06-01_a1"].valid_to is None and c["clm_2026-08-01_b2"].valid_to is None
    assert c["clm_2026-06-01_a1"].context and c["clm_2026-06-01_a1"].context != "general"
    assert c["clm_2026-08-01_b2"].context and c["clm_2026-08-01_b2"].context != "general"


def test_normalization_correct_fold_only_unlinks(memory):
    before = (memory / RUNTIME_FILE).read_text()
    run(inbox_service.resolve("inbox-011", InboxResolveRequest(action="resolve", option_key="0"), _Settings(memory)))
    assert not (memory / "inbox" / "inbox-011.md").exists()
    assert (memory / RUNTIME_FILE).read_text() == before
    assert _claims(memory)["clm_2026-08-01_c3"].predicate == "built-with"


def test_normalization_wrong_fold_splits_predicate(memory):
    run(inbox_service.resolve("inbox-011", InboxResolveRequest(action="resolve", option_key="1"), _Settings(memory)))
    data = yaml.safe_load((memory / RUNTIME_FILE).read_text())
    assert "uses stack" not in data["synonyms"] and "uses-stack" not in data["synonyms"]
    assert "uses-stack" in data["canonical"]
    assert load_normalizer(memory)("uses stack") == "uses-stack"
    assert _claims(memory)["clm_2026-08-01_c3"].predicate == "uses-stack"
    body = _resolution_commit(memory)
    assert "_predicates.yaml" in body


def test_normalization_nudge_carries_raw_and_canonical():
    from api.services.claim_reconciler import _normalization_audit_nudge
    from api.services.claims import Claim
    # `text` has no default on the Claim dataclass (it sits right after `id`
    # with no `= ...`) — every direct `Claim(...)` construction in this repo
    # passes it; a plan draft that omits it raises TypeError at collection time.
    claim = Claim(id="clm_x", text="bob-example built-with rust.", subject="bob-example",
                  predicate="built-with", object="rust",
                  observer="rodrigo", source_trust="inferred", epistemic="fact", confidence=0.6,
                  valid_from="2026-08-01", recorded_at="2026-08-01")
    n = _normalization_audit_nudge("uses stack", "built-with", claim)
    assert n["raw_predicate"] == "uses stack" and n["canonical_predicate"] == "built-with"
