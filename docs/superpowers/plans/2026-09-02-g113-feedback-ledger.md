# G113 Feedback Ledger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every user resolution of an inbox item a recorded, machine-readable verdict on the extractor's belief — a grounded-reward stream (Era of Experience) that the system can later learn from — and close the four inbox resolution gaps that currently drop the user's answer on the floor.

**Architecture:** Four slices on one branch. (1) Provenance: the resolution commit's trigger names the action taken so `git log` alone can answer "did the user agree?". (2) Ledger: a `resolution` telemetry event per resolve/defer, plus `audit` (reconcile supersede/reject) and `dedup_verdict` events, all ids/enums only — never claim text — under the existing `~/.cicada/telemetry/` JSONL. (3) Resolution correctness: the two inbox kinds Sleep writes but the API rejects (`divergence`, `normalization`) become real kinds with real resolvers; a merge suggestion can be *rejected* and stays rejected; decay `keep_active` and clarification `answer` write back to the claim layer. (4) Surface: `GET /consumption/feedback` + a fifth Usage tile in the app.

**Tech Stack:** Python 3 / FastAPI / Pydantic (`api/`), YAML frontmatter + git (`memory/`), MCP server (`mcp/server.py`), SwiftUI + XCTest (`app/CicadaApp`).

**Spec:** `docs/goals/memory-evolution.md` row **G113** (the backlog row is the spec; this plan is its argument). The four slices above are that row's four slices.

## Global Constraints

- Work ONLY in `/Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g113` (branch `feat/feedback-ledger`). Every shell command uses absolute paths (`zoxide` hijacks relative `cd`).
- Python tests: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g113 && api/.venv/bin/python -m pytest <files> -q -p no:cacheprovider`. The full suite has **8 pre-existing calendar failures** (`test_calendar*` / `test_sources_calendars*` — network-gated); those are baseline, not yours.
- Swift tests: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g113/app/CicadaApp && swift test` (Tasks 3, 4, 6 touch Swift; every other task must not).
- Never `git add -A`. Stage named files only. Never commit `memory/`, `logs/`, `.claude/settings.json`, `api/.venv`, `*-report.md`.
- No push, no new branches, no PR — the controller does that.
- **Ledger privacy rail:** a telemetry event records ids, enums, counts and confidences ONLY — never a claim's `text`/`object`, an entity's prose, an answer string, or a person's name. `refs` values are ids (`clm_…`, `inbox-NNN`, entity slugs), action labels, or numbers. Test fixtures use neutral placeholder names (`alpha-project`, `bob-example`) — no real people, projects or organisations.
- Nothing learned from the ledger is auto-applied to memory in this PR. The ledger is read only by `GET /consumption/feedback`.
- `telemetry.record()` must never raise into a resolve path — a ledger failure never blocks a user's answer.
- Ignore Devin/automated PR review comments entirely.
- No subagents from inside a task; the controller reviews.
- Read code at the cited `file:line` before editing — line numbers are from base commit `b690b66` and may drift by a few lines as tasks land.

## Rulings (binding — do not re-derive)

- **R1 — trigger encodes the action.** Resolution commits use trigger `inbox/<kind>/resolved:<label>`; `git_service.commit_resolution` keeps deriving the subject's kind from `trigger.split("/")[1]`, and no parser regexes the trigger, so the `:label` suffix is inert to every existing reader. Deferral keeps trigger `inbox/deferred`.
- **R2 — `statusChange` reuse.** A decay `archive`/`keep_active` resolution passes `change="status archived"` / `change="status active"` into the manifest line so `_infer_change_type`'s existing `"status"` branch yields `statusChange` — an enum value the Swift `ChangeType` already decodes. No new change types.
- **R3 — verdict semantics fixed at emit time** (per kind → agreed / overruled / neutral): decay `archive`=agreed, `keep_active`=overruled; conflict pick of the option whose `claim_id` equals the item's `claim_id` (the NEW claim Sleep proposed)=agreed, any other pick / `neither` / free text=overruled, `both`=neutral; clarification `answer`/`merge`=agreed, `dismiss`=overruled; merge_suggestion `merge`=agreed, `reject`=overruled, `dismiss`=neutral; divergence key `1` (update)=agreed, `0` (keep mine)=overruled, `2` (both)=neutral; normalization `0` (correct fold)=agreed, `1` (wrong fold)=overruled; `defer`, `skip`, `remind_later`=neutral. Recorded as a string so a later reader never re-derives it from drifting rules.
- **R4 — no new `InboxKind` beyond the two Sleep already writes.** `divergence` and `normalization` are added because `inbox_generator` has been writing them for months and `load_inbox` silently drops them. Swift `InboxKind` gains the same two cases IN THE SAME TASK (strict decode: an unknown raw value fails the whole inbox array).
- **R5 — merge rejection is a bank file, not a ledger lookup.** `<memory>/_merge_rejected.yaml` (sorted pairs) is consulted by `clarification_manager.create` and `dedup_sweep`. The fuzzy mention resolver in `entity_resolver` is out of scope.
- **R6 — `remind_later` becomes a 7-day defer.** It routes through `_defer` (which already hides the item via `remind_after`) instead of writing a `snooze_until` nothing reads.
- **R7 — feedback rows are excluded from connection/cost rollups.** `consumption_stats.stats()` builds `by_connection` from events whose kind is NOT in `FEEDBACK_KINDS`, so a `resolution` event (connection `None`) never appears as an "unknown" connection. `summary()` already counts only `llm_call`/`ask` — unchanged.

---

## File map

| File | Responsibility |
|---|---|
| `api/services/inbox_service.py` | `_action_label`, `_verdict`, `_emit_resolution`, `_resolve_divergence`, `_resolve_normalization`, reject path, decay/clarification claim write-back, `remind_later` routing |
| `api/services/git_service.py` | `commit_resolution(..., change=)` |
| `api/services/telemetry.py` | `KINDS`, `FEEDBACK_KINDS` |
| `api/services/claim_pipeline.py`, `api/services/agentic_write.py` | emit `audit` events after `reconcile_stage3` |
| `api/services/dedup_sweep.py` | emit `dedup_verdict`; skip rejected pairs |
| `api/services/merge_rejections.py` (new) | `_merge_rejected.yaml` read/write |
| `api/services/clarification_manager.py` | skip rejected duplicate pairs |
| `api/services/claim_reconciler.py`, `api/services/inbox_generator.py` | `raw_predicate` / `canonical_predicate` on normalization items |
| `api/models/schemas.py` | `InboxKind` +2, `ConsumptionFeedback` |
| `api/services/consumption_stats.py`, `api/routers/consumption.py` | `feedback()` + `GET /consumption/feedback` |
| `mcp/server.py` | `cicada_resolve_inbox` gains `reject` |
| `app/CicadaApp/Sources/CicadaApp/Models/InboxItem.swift`, `Theme/CicadaTheme.swift`, `Views/Inbox/InboxCardView.swift` | two kinds, "Keep separate" |
| `app/CicadaApp/Sources/CicadaApp/Models/Consumption*.swift`, `Services/APIClient.swift`, `Views/Usage/UsageSection.swift` | Feedback tile |
| `CLAUDE.md`, `docs/goals/memory-evolution.md`, `docs/goals/TODO.md` | docs |

---

### Task 1: Provenance — the resolution commit names the action

**Files:**
- Modify: `api/services/git_service.py:923-960` (`commit_resolution`)
- Modify: `api/services/inbox_service.py:259-300` (`resolve`)
- Test: `api/tests/test_inbox_resolution_provenance.py` (new)

**Interfaces:**
- Produces: `inbox_service._action_label(kind: str, request: InboxResolveRequest, options: list[dict]) -> str` (pure; Task 2 reuses it for the ledger's `action` ref). `git_service.commit_resolution(memory_path, entity_id, trigger, extra_lines=None, *, change="updated")`.

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_inbox_resolution_provenance.py
"""G113 slice 1: a resolution commit's trigger names the action the user took."""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from api.models.schemas import InboxResolveRequest
from api.services import git_service, inbox_service


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


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


def test_action_label_decay_passthrough():
    req = InboxResolveRequest(action="archive")
    assert inbox_service._action_label("decay", req, []) == "archive"
    req = InboxResolveRequest(action="keep_active")
    assert inbox_service._action_label("decay", req, []) == "keep_active"


def test_action_label_conflict_pick_and_special_keys():
    opts = [{"key": "0"}, {"key": "1"}, {"key": "both"}, {"key": "neither"}]
    assert inbox_service._action_label("conflict", InboxResolveRequest(action="resolve", option_key="1"), opts) == "pick:1"
    assert inbox_service._action_label("conflict", InboxResolveRequest(action="resolve", option_key="both"), opts) == "both"
    assert inbox_service._action_label("conflict", InboxResolveRequest(action="resolve", option_key="neither"), opts) == "neither"
    assert inbox_service._action_label("conflict", InboxResolveRequest(action="resolve", answer="free text"), opts) == "answer"
    assert inbox_service._action_label("conflict", InboxResolveRequest(action="dismiss"), opts) == "dismiss"


def test_action_label_clarification_and_merge():
    assert inbox_service._action_label("clarification", InboxResolveRequest(action="answer", answer="x"), []) == "answer"
    assert inbox_service._action_label("clarification", InboxResolveRequest(action="resolve", answer="x"), []) == "answer"
    assert inbox_service._action_label("merge_suggestion", InboxResolveRequest(action="merge", merge_target="b"), []) == "merge"
    assert inbox_service._action_label("merge_suggestion", InboxResolveRequest(action="reject"), []) == "reject"
    assert inbox_service._action_label("merge_suggestion", InboxResolveRequest(action="dismiss"), []) == "dismiss"
    assert inbox_service._action_label("clarification", InboxResolveRequest(action="skip"), []) == "skip"


def test_decay_archive_commit_trigger_and_status_change(memory: Path):
    settings = _Settings(memory)
    out = run(inbox_service.resolve("inbox-001", InboxResolveRequest(action="archive"), settings))
    assert out["status"] == "resolved"
    body = _git(memory, "log", "-1", "--format=%B")
    assert "entities/alpha-project.md: status archived (trigger: inbox/decay/resolved:archive)" in body
    assert "Cicada-Author: user" in body
    hist = git_service.get_entity_history(memory, "alpha-project")
    assert hist[0]["changeType"] == "statusChange"


def test_decay_keep_active_commit_trigger(memory: Path):
    settings = _Settings(memory)
    run(inbox_service.resolve("inbox-001", InboxResolveRequest(action="keep_active"), settings))
    body = _git(memory, "log", "-1", "--format=%B")
    assert "status active (trigger: inbox/decay/resolved:keep_active)" in body


def test_commit_resolution_change_keyword_default_unchanged(memory: Path):
    (memory / "entities" / "alpha-project.md").write_text(
        (memory / "entities" / "alpha-project.md").read_text() + "\nnote\n"
    )
    run(git_service.commit_resolution(memory, "alpha-project", "inbox/clarification/resolved:answer"))
    body = _git(memory, "log", "-1", "--format=%B")
    assert "entities/alpha-project.md: updated (trigger: inbox/clarification/resolved:answer)" in body
    assert "Inbox resolution (clarification)" in body
```

Check `git_service.get_entity_history`'s exact name and return shape at `api/services/git_service.py` (search `def get_entity_history` / `def entity_history`) and the key name for change type (`changeType` vs `change_type`) before finalising the assertion — read, don't guess. If history is exposed only through a router helper, assert on `git_service._infer_change_type("Inbox resolution (decay) 2026-09-02", body, "alpha-project") == "statusChange"` instead.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g113 && api/.venv/bin/python -m pytest api/tests/test_inbox_resolution_provenance.py -q -p no:cacheprovider`
Expected: FAIL — `AttributeError: module 'api.services.inbox_service' has no attribute '_action_label'`.

- [ ] **Step 3: Implement `_action_label` and thread it into `resolve`**

In `api/services/inbox_service.py`, add above `resolve`:

```python
_SPECIAL_KEYS = {"both", "neither"}


def _action_label(kind: str, request: InboxResolveRequest, options: list[dict]) -> str:
    """Name the action a resolution took, for the commit trigger and the ledger.

    Pure. ``options`` is the item's normalized option list (``{"key": ...}`` dicts)
    so a picked key can be checked against the special ``both``/``neither`` keys.
    """
    action = (request.action or "").strip().lower()
    key = (request.option_key or "").strip()
    if kind == "decay":
        return action or "answer"
    if kind in ("conflict", "divergence", "normalization"):
        if action == "dismiss":
            return "dismiss"
        if action == "skip":
            return "skip"
        if key:
            return key if key in _SPECIAL_KEYS else f"pick:{key}"
        if request.answer:
            return "answer"
        return action or "answer"
    # clarification / merge_suggestion
    if action in ("answer", "resolve"):
        return "answer"
    if action in ("dismiss", "merge", "reject", "skip"):
        return action
    return action or "answer"
```

In `resolve(...)`, after the kind-dispatch produces `entity_id`/`skipped`/`extra_lines` and before the `commit_resolution` call, compute the label from the parsed frontmatter's options (use `inbox_questions.normalize_options(fm.get("options") or [])`) and the `change` string:

```python
    label = _action_label(kind, request, inbox_questions.normalize_options(fm.get("options") or []))
    change = "updated"
    if kind == "decay" and label == "archive":
        change = "status archived"
    elif kind == "decay" and label == "keep_active":
        change = "status active"
    await git_service.commit_resolution(
        settings.memory_path, entity_id, f"inbox/{kind}/resolved:{label}", extra_lines, change=change
    )
```

`fm` must be captured before the branch unlinks the item file — `resolve` already parses the file at the top (`parsed`/`fm`); reuse that, do not re-read after unlink.

- [ ] **Step 4: Add the `change` keyword to `commit_resolution`**

In `api/services/git_service.py` `commit_resolution`, change the signature to `async def commit_resolution(memory_path, entity_id, trigger, extra_lines=None, *, change: str = "updated")` and the manifest line to `f"entities/{entity_id}.md: {change} (trigger: {trigger})"`. Everything else (subject from `trigger.split("/")[1]`, dedup of `extra_lines`, `authors=["user"]`) stays.

- [ ] **Step 5: Run the new tests and the existing inbox tests**

Run: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g113 && api/.venv/bin/python -m pytest api/tests/test_inbox_resolution_provenance.py api/tests/test_inbox_resolve_claims.py api/tests/test_claim_inbox.py api/tests/test_inbox_dedup.py api/tests/test_inbox_questions.py api/tests/test_mcp_inbox_questions.py -q -p no:cacheprovider`
Expected: all PASS. If an existing test asserts the old literal `trigger: inbox/conflict/resolved)` string, update that assertion to the new `:label` form — it is the behaviour this task changes on purpose.

- [ ] **Step 6: Commit**

```bash
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g113 && git add api/services/inbox_service.py api/services/git_service.py api/tests/test_inbox_resolution_provenance.py && git commit -m "feat(inbox): resolution commits name the action taken (G113 slice 1)"
```

---

### Task 2: Ledger — `resolution`, `audit`, `dedup_verdict` telemetry events

**Files:**
- Modify: `api/services/telemetry.py:21` (`KINDS`), add `FEEDBACK_KINDS`
- Modify: `api/services/inbox_service.py` (`resolve`, `_defer`)
- Modify: `api/services/claim_pipeline.py:113`, `api/services/agentic_write.py:374`
- Modify: `api/services/dedup_sweep.py:71-101`
- Modify: `api/services/consumption_stats.py:188-230` (`stats`)
- Test: `api/tests/test_feedback_ledger.py` (new)

**Interfaces:**
- Consumes: `inbox_service._action_label` (Task 1).
- Produces: `telemetry.FEEDBACK_KINDS = ("resolution", "audit", "dedup_verdict")`; `inbox_service._verdict(kind, label, option_key, item_claim_id, options) -> str`; `inbox_service._emit_resolution(fm, item_id, kind, request, label, settings, *, winner=None, losers=(), extractor_confidence=None, extractor_model=None)`; `telemetry.record_audit(entries, *, subject_hint, bank, stage)`; a `dedup_verdict` event per judged pair. Task 6 reads these events.

**Event shapes (ids/enums only):**

```
resolution: kind="resolution", stage="feedback", connection=None, engine=None, model=None,
            bank=telemetry.bank_name(settings), invocations=0, billing="free", ok=True,
            refs={item_id, kind, predicate, entity_id, action, option_key, verdict,
                  winner_claim_id, loser_claim_ids: [..], extractor_confidence,
                  extractor_model, item_age_days}
audit:      kind="audit", stage="reconcile", bank=<memory_path.name>, invocations=0, billing="free",
            refs={action: supersede|rejected, subject, closed, by} | {action, subject, kept, dropped}
dedup_verdict: kind="dedup_verdict", stage="dedup", bank, invocations=0, billing="free",
            refs={a, b, verdict, confidence, winner, applied: merged|proposed|nudged|none}
```

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_feedback_ledger.py
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
from api.services.claims import Claim, write_claims, parse_claims


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def home(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    return tmp_path / "home"


def _events(kind: str) -> list[dict]:
    today = date.today()
    return [e for e in telemetry.read_events(today.replace(day=1), today) if e.get("kind") == kind]


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
```

`dedup_sweep` (`api/services/dedup_sweep.py:49`) is a plain `def`, and `judge_fn` is called as `judge_fn(ap.read_text(), bp.read_text(), a, b)` returning `{"verdict", "confidence", "winner"}` — the `judge` stub above matches. `_group` (`consumption_stats.py:167`) builds rows keyed by the `label` argument, and `stats` passes `"connection"`. Check `api.services.claims` exports `Claim`, `parse_claims`, `write_claims` (they are used by `inbox_service` already — copy its import line).

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g113 && api/.venv/bin/python -m pytest api/tests/test_feedback_ledger.py -q -p no:cacheprovider`
Expected: FAIL — `FEEDBACK_KINDS` missing / `_verdict` missing.

- [ ] **Step 3: `telemetry.py` — kinds and `record_audit`**

```python
KINDS = ("llm_call", "sleep_run", "agentic_write", "ask", "import", "throttle",
         "resolution", "audit", "dedup_verdict")
# G113: grounded-feedback rows. Ids/enums only — never claim text. Excluded from
# connection/cost rollups (consumption_stats.stats) because they carry no spend.
FEEDBACK_KINDS = ("resolution", "audit", "dedup_verdict")


def record_audit(entries, *, subject_hint: str | None, bank: str | None, stage: str = "reconcile") -> None:
    """One ``audit`` event per reconcile audit entry. Never raises."""
    for entry in entries or ():
        try:
            action = entry.get("action")
            if action == "supersede":
                refs = {"action": "supersede", "subject": subject_hint, "closed": entry.get("closed"), "by": entry.get("by")}
            elif action == "rejected":
                refs = {"action": "rejected", "subject": subject_hint, "kept": entry.get("kept"), "dropped": entry.get("dropped")}
            else:
                continue
            record(UsageEvent(kind="audit", stage=stage, bank=bank, invocations=0, billing="free", refs=refs))
        except Exception:  # noqa: BLE001 — a ledger failure never blocks a write
            continue
```

If `subject_hint` is not knowable at a call site, pass the claim's `subject` from the `by`/`closed` id lookup, else `None`.

- [ ] **Step 4: `inbox_service.py` — `_verdict` and `_emit_resolution`**

```python
def _verdict(kind: str, label: str, option_key: str | None, item_claim_id: str | None, options: list[dict]) -> str:
    """R3: did the user agree with what the extractor proposed? agreed|overruled|neutral."""
    if label in ("defer", "skip", "remind_later"):
        return "neutral"
    if kind == "decay":
        return {"archive": "agreed", "keep_active": "overruled"}.get(label, "neutral")
    if kind == "conflict":
        if label == "both":
            return "neutral"
        if label.startswith("pick:"):
            picked = next((o for o in options if str(o.get("key")) == str(option_key)), None)
            return "agreed" if picked and picked.get("claim_id") == item_claim_id else "overruled"
        return "overruled"  # neither / free-text answer / dismiss
    if kind == "divergence":
        return {"1": "agreed", "0": "overruled"}.get(str(option_key), "neutral")
    if kind == "normalization":
        return {"0": "agreed", "1": "overruled"}.get(str(option_key), "neutral")
    if kind == "clarification":
        return {"answer": "agreed", "merge": "agreed", "dismiss": "overruled"}.get(label, "neutral")
    if kind == "merge_suggestion":
        return {"merge": "agreed", "reject": "overruled"}.get(label, "neutral")
    return "neutral"


def _item_age_days(fm: dict, today: date) -> int | None:
    raw = fm.get("created_date")
    try:
        created = raw if isinstance(raw, date) else date.fromisoformat(str(raw)[:10])
    except (TypeError, ValueError):
        return None
    return max(0, (today - created).days)


def _emit_resolution(fm: dict, item_id: str, kind: str, request: InboxResolveRequest, label: str, settings, *,
                     winner: str | None = None, losers=(), extractor_confidence: float | None = None,
                     extractor_model: str | None = None) -> None:
    """Append one ``resolution`` ledger row. Ids/enums/numbers only. Never raises."""
    try:
        options = inbox_questions.normalize_options(fm.get("options") or [])
        verdict = _verdict(kind, label, request.option_key, _opt_str(fm.get("claim_id")), options)
        telemetry.record(telemetry.UsageEvent(
            kind="resolution", stage="feedback", bank=telemetry.bank_name(settings),
            invocations=0, billing="free",
            refs={
                "item_id": item_id, "kind": kind,
                "predicate": _opt_str(fm.get("predicate")), "entity_id": _opt_str(fm.get("entity_id")),
                "action": label, "option_key": request.option_key, "verdict": verdict,
                "winner_claim_id": winner, "loser_claim_ids": list(losers),
                "extractor_confidence": extractor_confidence, "extractor_model": extractor_model,
                "item_age_days": _item_age_days(fm, date.today()),
            },
        ))
    except Exception:  # noqa: BLE001
        logger.debug("resolution ledger write failed", exc_info=True)
```

Import `telemetry` (`from api.services import telemetry`) and `date` if not already imported.

**Winner/loser derivation** — computed BEFORE the resolver unlinks the file, from the item's frontmatter plus the entity's claims block (`parse_claims` on the entity file, which may fail — treat failure as "no claim info"):
- decay: no claims; `extractor_confidence = float(fm.get("priority"))` if present.
- conflict: `pick:<key>` → winner = that option's `claim_id`, losers = every other option `claim_id` that is not None; `both` → winner None, losers []; `neither`/`answer` → winner None, losers = all option claim_ids. `extractor_confidence` / `extractor_model` = the winner claim's `confidence` / `authored_by` (or, when no winner, the item `claim_id`'s claim).
- divergence: option `0` → winner `existing_claim_id`, losers `[claim_id]`; `1` → reverse; `2` → winner None, losers []. Confidence/model from the item `claim_id` claim.
- normalization: winner = item `claim_id`, losers []; confidence/model from that claim.
- clarification / merge_suggestion: no claims; `extractor_confidence = fm.get("suggested_confidence")` when present.

Put that derivation in a helper `_feedback_refs(fm, kind, label, request, memory_path) -> dict(winner=, losers=, extractor_confidence=, extractor_model=)` and call `_emit_resolution(**...)` from `resolve()` after the branch returns (skipped or not — a `skip` is a neutral row) and before `commit_resolution`; and from `_defer` with `label="defer"`. Task 5 later routes `remind_later` through `_defer` — that call must pass `label="remind_later"`, so give `_defer` a keyword `label: str = "defer"`.

- [ ] **Step 5: `audit` at both reconcile call sites**

`api/services/claim_pipeline.py:113` after `reconciled, nudges, audit = reconcile_stage3(...)`:

```python
    telemetry.record_audit(audit, subject_hint=None, bank=memory_path.name, stage="reconcile")
```

(pass the subject when the loop already has one — read the surrounding code; if `reconcile_stage3` runs once per subject there, pass that subject.) Same one-liner in `api/services/agentic_write.py:374` after its `reconcile_stage3` call, with `bank=memory_path.name`.

- [ ] **Step 6: `dedup_verdict` in `dedup_sweep`**

Inside the per-pair loop (`api/services/dedup_sweep.py:71-101`), after the verdict is applied and `applied` is known, add — inside the existing try — :

```python
            telemetry.record(telemetry.UsageEvent(
                kind="dedup_verdict", stage="dedup", bank=memory_path.name, invocations=0, billing="free",
                refs={"a": a, "b": b, "verdict": verdict, "confidence": confidence, "winner": winner, "applied": applied},
            ))
```

where `applied` is `"merged"` (auto-merge performed), `"proposed"` (dry-run would have merged), `"nudged"` (merge suggestion written), or `"none"`. Derive it from the branch the loop already takes — do not add a second judgement.

- [ ] **Step 7: R7 in `consumption_stats.stats`**

Build `by_connection` from `[e for e in events if e.get("kind") not in telemetry.FEEDBACK_KINDS]`. Leave `by_stage` and `by_bank` on all events (a `feedback` stage row is informative there).

- [ ] **Step 8: Run tests**

Run: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g113 && api/.venv/bin/python -m pytest api/tests/test_feedback_ledger.py api/tests/test_telemetry.py api/tests/test_consumption_stats.py api/tests/test_consumption_api.py api/tests/test_dedup_sweep.py api/tests/test_maintenance_dedup_sweep.py api/tests/test_inbox_resolve_claims.py api/tests/test_claim_pipeline.py api/tests/test_agentic_write.py -q -p no:cacheprovider`
Expected: PASS (if `test_claim_pipeline.py`/`test_agentic_write.py` don't exist, drop them; find the reconcile tests with `ls api/tests | grep -i -e reconcile -e claim`).

- [ ] **Step 9: Commit**

```bash
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g113 && git add api/services/telemetry.py api/services/inbox_service.py api/services/claim_pipeline.py api/services/agentic_write.py api/services/dedup_sweep.py api/services/consumption_stats.py api/tests/test_feedback_ledger.py && git commit -m "feat(telemetry): resolution, audit and dedup_verdict feedback events (G113 slice 2)"
```

---

### Task 3: `divergence` and `normalization` become real inbox kinds (API + Swift)

**Files:**
- Modify: `api/models/schemas.py:763` (`InboxKind`)
- Modify: `api/services/inbox_service.py` (`_required_input_for`, `resolve`, new `_resolve_divergence`, `_resolve_normalization`)
- Modify: `api/services/claim_reconciler.py:323-336` (`_normalization_audit_nudge`), `api/services/inbox_generator.py:350-375` (persist two keys)
- Modify: `app/CicadaApp/Sources/CicadaApp/Models/InboxItem.swift` (`InboxKind`), `app/CicadaApp/Sources/CicadaApp/Theme/CicadaTheme.swift` (`Dark.inboxColor`, `Light.inboxColor`)
- Test: `api/tests/test_inbox_divergence_normalization.py` (new), `app/CicadaApp/Tests/CicadaAppTests/InboxKindDecodingTests.swift` (new)

**Interfaces:**
- Consumes: `_action_label`, `_emit_resolution` (Tasks 1–2), `_close_today`, `_user_claim_id` (existing), `predicates.RUNTIME_FILE`, `predicates._slugify_predicate`.
- Produces: `InboxKind.divergence`, `InboxKind.normalization`; normalization items carry `raw_predicate` and `canonical_predicate` frontmatter keys; resolvers return `(entity_id, skipped, extra_lines)` like `_resolve_conflict`.

**Why:** `inbox_generator` writes both kinds every Sleep (`inbox_generator.py:333-338`) but `InboxKind` lacks them, so `_item_from_file` raises and `load_inbox` drops them with a warning — the user never sees them and can never answer them. Option keys are positional (`normalize_options` on the flat lists at `claim_reconciler.py:309-313` / `:331`): divergence `0`=keep mine, `1`=update, `2`=both; normalization `0`=correct fold, `1`=wrong fold.

- [ ] **Step 1: Write the failing API tests**

```python
# api/tests/test_inbox_divergence_normalization.py
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
    return asyncio.get_event_loop().run_until_complete(coro)


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


def test_kinds_exist_and_load(memory):
    assert InboxKind("divergence") and InboxKind("normalization")
    assert inbox_service._required_input_for("divergence") == "choice"
    assert inbox_service._required_input_for("normalization") == "choice"
    items = run(inbox_service.load_inbox(_Settings(memory)))
    kinds = {i.id: i.kind for i in items}
    assert kinds["inbox-010"] == InboxKind.divergence
    assert kinds["inbox-011"] == InboxKind.normalization
    div = next(i for i in items if i.id == "inbox-010")
    assert [o.key for o in div.options] == ["0", "1", "2"]


def test_divergence_keep_mine_closes_new_claim(memory):
    out = run(inbox_service.resolve("inbox-010", InboxResolveRequest(action="resolve", option_key="0"), _Settings(memory)))
    assert out["status"] == "resolved"
    c = _claims(memory)
    assert c["clm_2026-08-01_b2"].valid_to is not None
    assert c["clm_2026-08-01_b2"].superseded_by == "clm_2026-06-01_a1"
    assert c["clm_2026-06-01_a1"].valid_to is None
    assert c["clm_2026-06-01_a1"].confidence >= 0.9
    assert not (memory / "inbox" / "inbox-010.md").exists()
    body = _git(memory, "log", "-1", "--format=%B")
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
    body = _git(memory, "log", "-1", "--format=%B")
    assert "_predicates.yaml" in body


def test_normalization_nudge_carries_raw_and_canonical():
    from api.services.claim_reconciler import _normalization_audit_nudge
    from api.services.claims import Claim
    claim = Claim(id="clm_x", subject="bob-example", predicate="built-with", object="rust",
                  observer="rodrigo", source_trust="inferred", epistemic="fact", confidence=0.6,
                  valid_from="2026-08-01", recorded_at="2026-08-01")
    n = _normalization_audit_nudge("uses stack", "built-with", claim)
    assert n["raw_predicate"] == "uses stack" and n["canonical_predicate"] == "built-with"
```

Check the `Claim` dataclass's required constructor fields in `api/services/claims.py` and trim/extend the `Claim(...)` call in the last test to match (it must construct without error).

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g113 && api/.venv/bin/python -m pytest api/tests/test_inbox_divergence_normalization.py -q -p no:cacheprovider`
Expected: FAIL — `ValueError: 'divergence' is not a valid InboxKind`.

- [ ] **Step 3: Schema + `_required_input_for`**

`api/models/schemas.py` `InboxKind`: add `divergence = "divergence"` and `normalization = "normalization"` after `merge_suggestion`. `inbox_service._required_input_for`: `if kind in ("decay", "conflict", "divergence", "normalization"): return "choice"`. In `_item_from_file`, `allow_other`/`allow_defer` default to `kind in ("conflict", "clarification")` — extend `allow_defer` to include `"divergence"` (a "remind me later" is a sane answer to "I'm reading something different"); leave `allow_other` unchanged.

- [ ] **Step 4: `_resolve_divergence`**

```python
async def _resolve_divergence(path: Path, parsed, request: InboxResolveRequest, settings, item_id: str):
    fm = parsed.frontmatter
    entity_id = _opt_str(fm.get("entity_id")) or ""
    key = (request.option_key or "").strip()
    if request.action in ("skip",):
        return entity_id, True, []
    if request.action == "dismiss" or key not in ("0", "1", "2"):
        path.unlink(missing_ok=True)
        return entity_id, False, []
    entity_path = settings.memory_path / "entities" / f"{entity_id}.md"
    if not entity_path.exists():
        path.unlink(missing_ok=True)
        return entity_id, False, []
    entity = markdown_parser.parse(entity_path)
    try:
        claims = parse_claims(entity.body)
    except MalformedClaimsBlockError as exc:
        raise HTTPException(status_code=409, detail=f"claims block on {entity_id} will not parse: {exc}") from exc
    by_id = {c.id: c for c in claims}
    new = by_id.get(_opt_str(fm.get("claim_id")) or "")
    existing = by_id.get(_opt_str(fm.get("existing_claim_id")) or "")
    today = str(date.today())
    if new is not None and existing is not None:
        if key == "0":  # keep my statement: the new reading loses
            _close_today(new, by=existing, today=today)
            existing.confidence = max(float(existing.confidence or 0), 0.9)
        elif key == "1":  # update: my old statement loses
            _close_today(existing, by=new, today=today)
            new.confidence = max(float(new.confidence or 0), 0.9)
        else:  # both true — different context
            for c in (existing, new):
                if not c.context or c.context == "general":
                    c.context = f"as of {c.valid_from or today}"
        efm = entity.frontmatter
        efm["last_referenced"] = today
        efm["version"] = int(efm.get("version", 1) or 1) + 1
        markdown_parser.write(entity_path, efm, write_claims(entity.body, claims))
    path.unlink(missing_ok=True)
    return entity_id, False, [f"entities/{entity_id}.md: updated (source: {path.stem}, trigger: inbox/divergence/resolved)"]
```

This mirrors `_resolve_conflict` exactly (`inbox_service.py:408-410` imports, `:600-620` write-back): `markdown_parser.parse` → `parse_claims(entity.body)` (strict; 409 on a malformed block) → mutate → `write_claims(entity.body, claims)` → `markdown_parser.write`. Check `_close_today`'s `today` parameter type (`str` vs `date`) at `inbox_service.py:381` and pass what it expects. Read `_resolve_conflict` at `inbox_service.py:393-620` first and use its local imports (`from api.services.claims import Claim, MalformedClaimsBlockError, parse_claims, write_claims`).

- [ ] **Step 5: `_resolve_normalization`**

```python
async def _resolve_normalization(path: Path, parsed, request: InboxResolveRequest, settings, item_id: str):
    fm = parsed.frontmatter
    entity_id = _opt_str(fm.get("entity_id")) or ""
    key = (request.option_key or "").strip()
    if request.action == "skip":
        return entity_id, True, []
    extra: list[str] = []
    if key == "1":  # wrong fold — keep the raw predicate separate
        raw = _opt_str(fm.get("raw_predicate")) or ""
        raw_slug = predicates._slugify_predicate(raw)
        if raw_slug:
            runtime = settings.memory_path / predicates.RUNTIME_FILE
            data = predicates._read_runtime_map(settings.memory_path)
            syn = {str(k): v for k, v in (data.get("synonyms") or {}).items()}
            for k in list(syn):
                if k.strip().lower() in (raw.strip().lower(), raw_slug):
                    syn.pop(k)
            canonical = [str(c) for c in (data.get("canonical") or [])]
            if raw_slug not in canonical:
                canonical.append(raw_slug)
            data["synonyms"], data["canonical"] = syn, canonical
            runtime.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
            extra.append(f"{predicates.RUNTIME_FILE}: updated (source: {path.stem}, trigger: inbox/normalization/resolved)")
            entity_path = settings.memory_path / "entities" / f"{entity_id}.md"
            claim_id = _opt_str(fm.get("claim_id"))
            if entity_path.exists() and claim_id:
                entity = markdown_parser.parse(entity_path)
                try:
                    claims = parse_claims(entity.body)
                except MalformedClaimsBlockError:
                    claims = []
                hit = False
                for c in claims:
                    if c.id == claim_id:
                        c.predicate = raw_slug
                        hit = True
                if hit:
                    efm = entity.frontmatter
                    efm["version"] = int(efm.get("version", 1) or 1) + 1
                    markdown_parser.write(entity_path, efm, write_claims(entity.body, claims))
                    extra.append(f"entities/{entity_id}.md: updated (source: {path.stem}, trigger: inbox/normalization/resolved)")
    path.unlink(missing_ok=True)
    return entity_id, False, extra
```

`from api.services import predicates` and `import yaml` at the top of `inbox_service.py` if absent. Note `_read_runtime_map` is module-private but the same package — import it as shown; do not copy its body.

In `resolve()`, dispatch: `elif kind == "divergence": entity_id, skipped, extra_lines = await _resolve_divergence(...)` and likewise for `normalization`. When `entity_id` is empty and no entity file exists, `commit_resolution` still commits the unlink (it already handles a missing entity file for clarifications — verify by reading `commit_resolution`; if it does not, guard by committing `inbox/` via `commit_paths` as `_defer` does).

- [ ] **Step 6: Persist `raw_predicate`/`canonical_predicate`**

`claim_reconciler._normalization_audit_nudge`: add `"raw_predicate": raw_label, "canonical_predicate": canonical` to the returned dict. `inbox_generator` frontmatter dict: add `"raw_predicate": nudge.get("raw_predicate"), "canonical_predicate": nudge.get("canonical_predicate")`. `markdown_parser.write` drops `None` values? Read it — if it writes `key: null`, only add the keys when present.

- [ ] **Step 7: Swift — the two kinds**

`app/CicadaApp/Sources/CicadaApp/Models/InboxItem.swift`:

```swift
enum InboxKind: String, Codable {
    case decay, conflict, clarification
    case mergeSuggestion = "merge_suggestion"
    case divergence
    case normalization
```

and in its `label` / `icon` switches add `case .divergence: return "Divergence"` / `"arrow.triangle.branch"` and `case .normalization: return "Predicate fold"` / `"arrow.triangle.merge"`; in the `color` switch (and in both `Dark.inboxColor` and `Light.inboxColor` at `Theme/CicadaTheme.swift:240` / `:336`) map `.divergence` to the same colour as `.conflict` and `.normalization` to the same colour as `.clarification`. Add the test:

```swift
// app/CicadaApp/Tests/CicadaAppTests/InboxKindDecodingTests.swift
import XCTest
@testable import CicadaApp

final class InboxKindDecodingTests: XCTestCase {
    func testDecodesNewKinds() throws {
        let json = #"""
        [{"id":"inbox-010","kind":"divergence","requiredInput":"choice","status":"pending","priority":0.5,
          "entityId":"bob-example","entityName":"Bob Example","title":"t","createdDate":"2026-08-02",
          "options":[{"key":"0","label":"Keep"},{"key":"1","label":"Update"},{"key":"2","label":"Both"}]},
         {"id":"inbox-011","kind":"normalization","requiredInput":"choice","status":"pending","priority":0.3,
          "entityId":"bob-example","entityName":"Bob Example","title":"t","createdDate":"2026-08-02",
          "options":[{"key":"0","label":"Correct fold"},{"key":"1","label":"Wrong fold"}]}]
        """#
        let items = try JSONDecoder().decode([InboxItem].self, from: Data(json.utf8))
        XCTAssertEqual(items.map(\.kind), [.divergence, .normalization])
        XCTAssertEqual(InboxKind.divergence.label, "Divergence")
        XCTAssertEqual(InboxKind.normalization.label, "Predicate fold")
    }
}
```

Read `InboxItem.init(from:)` first and match the required JSON keys exactly (camelCase per `CamelModel`; check which are optional). If an existing test file already decodes `InboxItem` fixtures, copy its minimal JSON shape.

- [ ] **Step 8: Run both suites**

Run: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g113 && api/.venv/bin/python -m pytest api/tests/test_inbox_divergence_normalization.py api/tests/test_inbox_resolve_claims.py api/tests/test_claim_inbox.py api/tests/test_inbox_questions.py api/tests/test_claim_reconciler.py api/tests/test_feedback_ledger.py -q -p no:cacheprovider`
Expected: PASS (drop a test file from the list only if it does not exist).
Run: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g113/app/CicadaApp && swift test 2>&1 | tail -20`
Expected: all tests pass, including `InboxKindDecodingTests`.

- [ ] **Step 9: Commit**

```bash
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g113 && git add api/models/schemas.py api/services/inbox_service.py api/services/claim_reconciler.py api/services/inbox_generator.py api/tests/test_inbox_divergence_normalization.py app/CicadaApp/Sources/CicadaApp/Models/InboxItem.swift app/CicadaApp/Sources/CicadaApp/Theme/CicadaTheme.swift app/CicadaApp/Tests/CicadaAppTests/InboxKindDecodingTests.swift && git commit -m "feat(inbox): divergence and normalization are resolvable kinds (G113 slice 3)"
```

---

### Task 4: Merge suggestions can be rejected — and stay rejected

**Files:**
- Create: `api/services/merge_rejections.py`
- Modify: `api/services/inbox_service.py` (`_resolve_clarification` ~:621 — `reject` action)
- Modify: `api/services/clarification_manager.py:55-113` (`create` skips rejected pairs)
- Modify: `api/services/dedup_sweep.py:71-101` (skip rejected pairs; `skipped_rejected` count)
- Modify: `mcp/server.py:347` (tool schema), `:1614` (`handle_resolve_inbox`)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Inbox/InboxCardView.swift:233` (`mergeActions`)
- Test: `api/tests/test_merge_rejections.py` (new)

**Interfaces:**
- Produces: `merge_rejections.load_rejected(memory_path) -> set[tuple[str, str]]`, `is_rejected(memory_path, a, b) -> bool`, `add_rejected(memory_path, a, b) -> Path` (pairs sorted; file `<memory>/_merge_rejected.yaml` = `{"rejected": [[a, b], ...]}`); resolve action `"reject"` on a `merge_suggestion` item; MCP `cicada_resolve_inbox(reject=true)`.

**Why:** today "Dismiss" on a merge suggestion deletes the item, and the next Sleep's `entity_resolver._create_duplicate_clarification` (or a dedup sweep) recreates it. The user's "no" is never remembered.

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_merge_rejections.py
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
    return asyncio.get_event_loop().run_until_complete(coro)


def _git(memory: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(memory), *args], check=True, capture_output=True, text=True).stdout


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
    body = _git(memory, "log", "-1", "--format=%B")
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
    created = mgr.create(
        entity_name="Alpha Project",
        uncertainty_type="Possible duplicate of Alpha Proj",
        question="Are these the same?",
        context="",
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
```

Read `ClarificationManager.create`'s real signature (`api/services/clarification_manager.py:55`) — parameter names and what it returns when it declines to create (the summary says it returns `None` after bumping an open duplicate; a rejected pair must return `None` too, without writing). Fix the `mgr.create(...)` call to match.

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g113 && api/.venv/bin/python -m pytest api/tests/test_merge_rejections.py -q -p no:cacheprovider`
Expected: FAIL — `ImportError: cannot import name 'merge_rejections'`.

- [ ] **Step 3: `merge_rejections.py`**

```python
"""G113 — remembered "these are NOT the same entity" rulings.

``<memory>/_merge_rejected.yaml`` holds sorted ``[a, b]`` slug pairs. A pair the
user rejected is never re-proposed by ``clarification_manager.create`` (Sleep's
duplicate clarifications) or ``dedup_sweep`` (the maintenance sweep). Fuzzy
mention resolution in ``entity_resolver`` is deliberately NOT consulted here —
it resolves mentions to pages, it does not propose merges.
"""
from __future__ import annotations

from pathlib import Path

import yaml

FILE = "_merge_rejected.yaml"


def _pair(a: str, b: str) -> tuple[str, str]:
    x, y = sorted((str(a or "").strip(), str(b or "").strip()))
    return x, y


def load_rejected(memory_path: Path) -> set[tuple[str, str]]:
    p = Path(memory_path) / FILE
    if not p.exists():
        return set()
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return set()
    out: set[tuple[str, str]] = set()
    for row in (data.get("rejected") or []) if isinstance(data, dict) else []:
        if isinstance(row, (list, tuple)) and len(row) == 2:
            out.add(_pair(row[0], row[1]))
    return out


def is_rejected(memory_path: Path, a: str, b: str) -> bool:
    return _pair(a, b) in load_rejected(memory_path)


def add_rejected(memory_path: Path, a: str, b: str) -> Path:
    pairs = load_rejected(memory_path)
    pairs.add(_pair(a, b))
    p = Path(memory_path) / FILE
    p.write_text(
        yaml.safe_dump({"rejected": [list(x) for x in sorted(pairs)]}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return p
```

- [ ] **Step 4: `reject` in `_resolve_clarification`**

At the top of `_resolve_clarification`'s action dispatch (read `inbox_service.py:621+` first), add:

```python
    if request.action == "reject":
        if kind != "merge_suggestion":
            raise HTTPException(status_code=400, detail="reject is only valid on a merge_suggestion item")
        other = _opt_str(fm.get("merge_target_hint")) or (
            sanitize_id(request.merge_target) if request.merge_target else ""
        )
        if not other:
            raise HTTPException(status_code=400, detail="reject needs a merge target (hint or mergeTarget)")
        from api.services import merge_rejections
        merge_rejections.add_rejected(settings.memory_path, entity_id, other)
        path.unlink()
        return entity_id, False, [f"{merge_rejections.FILE}: updated (source: {path.stem}, trigger: inbox/merge_suggestion/rejected)"]
```

`_resolve_clarification` currently returns a 2-tuple `(entity_id, skipped)`; change it to return a 3-tuple `(entity_id, skipped, extra_lines)` everywhere (existing returns append `[]`) and update `resolve()`'s unpacking for the clarification/merge_suggestion branch to `entity_id, skipped, extra_lines = ...`. `resolve()` already passes `extra_lines` to `commit_resolution`, and `commit_resolution` runs `commit_changes` (`git add -A` inside the bank) so `_merge_rejected.yaml` is swept into the same commit.

- [ ] **Step 5: `clarification_manager.create` skips rejected pairs**

In `create(...)` right after `is_duplicate` and `second` are computed (`clarification_manager.py:55-113`), before `find_open`:

```python
        if is_duplicate and second:
            from api.services import merge_rejections
            if merge_rejections.is_rejected(self.memory_path, sanitize_id(entity_name), second):
                logger.info("clarification: merge pair (%s, %s) was rejected by the user — not re-proposing", entity_name, second)
                return None
```

Use the module's existing logger name and whatever `create` already returns on the "already open" path.

- [ ] **Step 6: `dedup_sweep` skips rejected pairs**

Before the `ap, bp = ...` line in the loop:

```python
        if (a, b) in rejected or (b, a) in rejected:
            skipped_rejected += 1
            continue
```

with `rejected = merge_rejections.load_rejected(memory_path)` and `skipped_rejected = 0` initialised above the loop, and `"skipped_rejected": skipped_rejected` added to the returned dict. Check `api/routers/maintenance.py`'s `MaintenanceDedupSweepResponse` (`api/models/schemas.py`) — add `skipped_rejected: int = 0` to it so the router's response model doesn't drop the key.

- [ ] **Step 7: MCP**

`mcp/server.py` `cicada_resolve_inbox` schema (`:347`): add `"reject": {"type": "boolean", "description": "For a merge_suggestion: these are NOT the same entity — remember that and stop proposing it."}`. `handle_resolve_inbox(item_id, option_key, answer, defer, remind_days, reject=False)`: `if reject: payload = {"action": "reject"}` checked before the defer branch; dispatch at `:549` passes `reject=bool(arguments.get("reject"))`. Add a case to `api/tests/test_mcp_inbox_questions.py` mirroring its existing defer test (posting `{"action": "reject"}` to `/inbox/{id}/resolve`).

- [ ] **Step 8: Swift — "Keep separate"**

In `InboxCardView.swift` `mergeActions` (~:233), change the Dismiss button on a merge card to title `"Keep separate"` sending `QuestionResolution(action: "reject")` (keep its role/style; Skip stays). Read `QuestionResolution`'s initialiser to pass only `action:`.

- [ ] **Step 9: Run**

Run: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g113 && api/.venv/bin/python -m pytest api/tests/test_merge_rejections.py api/tests/test_dedup_sweep.py api/tests/test_maintenance_dedup_sweep.py api/tests/test_mcp_inbox_questions.py api/tests/test_inbox_resolve_claims.py api/tests/test_inbox_dedup.py api/tests/test_feedback_ledger.py -q -p no:cacheprovider` → PASS.
Run: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g113/app/CicadaApp && swift build 2>&1 | tail -5` → builds.

- [ ] **Step 10: Commit**

```bash
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g113 && git add api/services/merge_rejections.py api/services/inbox_service.py api/services/clarification_manager.py api/services/dedup_sweep.py api/models/schemas.py mcp/server.py api/tests/test_merge_rejections.py api/tests/test_mcp_inbox_questions.py app/CicadaApp/Sources/CicadaApp/Views/Inbox/InboxCardView.swift && git commit -m "feat(inbox): reject a merge suggestion and remember it (G113 slice 3)"
```

---

### Task 5: Decay and clarification answers reach the claim layer

**Files:**
- Modify: `api/services/inbox_service.py:331-370` (`_resolve_decay`), `:259-300` (`resolve` — `remind_later` routing), `:301-330` (`_defer` default days), `:621-700` (`_resolve_clarification` answer on an existing entity)
- Test: `api/tests/test_inbox_claim_writeback.py` (new)

**Interfaces:**
- Consumes: `_defer(path, parsed, request, settings, item_id, *, label="defer", default_days=None)` (Task 2 added `label`; this task adds `default_days`), `_user_claim_id`, `Claim`, `parse_claims`, `write_claims`.
- Produces: a decay item carrying `claim_id` refreshes that claim on `keep_active`; `remind_later` == a 7-day defer; a clarification `answer` on an existing entity writes a `user_stated` claim beside the prose.

**Why:** `_resolve_decay` (`inbox_service.py:331`) never touches `claim_id` even though claim-decay nudges carry one (`claim_reconciler.py:520-529`) — "still true" leaves the claim faded. `remind_later` writes `status: snoozed`/`snooze_until` that nothing reads, so the item comes straight back. A clarification answer is appended as prose only, invisible to the claim layer.

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_inbox_claim_writeback.py
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
    return asyncio.get_event_loop().run_until_complete(coro)


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
    items = run(inbox_service.load_inbox(_Settings(memory)))
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
```

Check the `Claim` dataclass (`api/services/claims.py`) for the exact attribute names `object_kind`, `origin`, `authored_by`, `valid_to` types (str vs date) and adjust the assertions; `parse_claims` on a page with no claims block returns `[]` — confirm.

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g113 && api/.venv/bin/python -m pytest api/tests/test_inbox_claim_writeback.py -q -p no:cacheprovider`
Expected: FAIL on all five.

- [ ] **Step 3: `remind_later` → `_defer`**

In `resolve()`, replace the defer check with:

```python
    if request.action == "defer" or (kind == "decay" and request.action == "remind_later"):
        label = "remind_later" if request.action == "remind_later" else "defer"
        return await _defer(path, parsed, request, settings, item_id, label=label,
                            default_days=7 if label == "remind_later" else None)
```

`_defer` signature becomes `async def _defer(path, parsed, request, settings, item_id, *, label="defer", default_days=None)` and its day computation `days = request.remind_days or default_days or getattr(settings, "inbox_defer_days", None) or 30`. Delete the `remind_later` branch from `_resolve_decay` (it is now unreachable) and its `snooze_until` writes.

- [ ] **Step 4: `keep_active` refreshes the claim**

In `_resolve_decay`'s `keep_active` branch, after the frontmatter edits and before `markdown_parser.write`:

```python
        claim_id = _opt_str(parsed.frontmatter.get("claim_id"))
        body = entity.body
        if claim_id:
            from api.services.claims import MalformedClaimsBlockError, parse_claims, write_claims
            try:
                claims = parse_claims(body)
            except MalformedClaimsBlockError:
                claims = None
            if claims:
                for c in claims:
                    if c.id == claim_id:
                        c.confidence = max(float(c.confidence or 0), 0.6)
                        if c.valid_to and not c.superseded_by:
                            c.valid_to = None  # faded, not replaced — reopen it
                body = write_claims(body, claims)
        markdown_parser.write(entity_path, entity.frontmatter, body)
```

- [ ] **Step 5: clarification `answer` writes a claim on an existing entity**

In `_resolve_clarification`'s `if action == "answer": ... if entity_path.exists():` branch, replace `body = entity.body.rstrip() + f"\n\n{answer_text}"` with:

```python
            body = entity.body.rstrip() + f"\n\n{answer_text}"
            predicate = _opt_str(parsed.frontmatter.get("predicate")) or "description"
            from api.services.claims import Claim, MalformedClaimsBlockError, parse_claims, write_claims
            try:
                claims = parse_claims(entity.body)
            except MalformedClaimsBlockError:
                claims = None
            if claims is not None:
                claims.append(Claim(
                    id=_user_claim_id(entity_id, predicate, answer_text, today),
                    subject=entity_id, predicate=predicate, object=answer_text, object_kind="literal",
                    observer="rodrigo", source_trust="user_stated", epistemic="fact", origin="clarification",
                    authored_by="user", confidence=0.95, valid_from=today, recorded_at=today,
                ))
                body = write_claims(body, claims)
```

Match `Claim`'s constructor exactly as `_resolve_conflict`'s free-text branch builds one (`inbox_service.py` — search `origin="clarification"`) and reuse its field list; `write_claims` on a body with no block must append one (verify in `claims.py`; if it does not, this is the case to handle by calling whatever helper `_resolve_conflict` uses).

- [ ] **Step 6: Run**

Run: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g113 && api/.venv/bin/python -m pytest api/tests/test_inbox_claim_writeback.py api/tests/test_inbox_resolve_claims.py api/tests/test_inbox_questions.py api/tests/test_inbox_resolution_provenance.py api/tests/test_feedback_ledger.py api/tests/test_nudges.py api/tests/test_inbox_service.py -q -p no:cacheprovider` → PASS (drop a listed file only if it does not exist; find the decay-resolution tests with `grep -ln remind_later api/tests/*.py` and run those too — an existing test asserting `snooze_until` must be updated to the deferral contract, since this task changes that behaviour on purpose).

- [ ] **Step 7: Commit**

```bash
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g113 && git add api/services/inbox_service.py api/tests/test_inbox_claim_writeback.py $(cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g113 && git diff --name-only -- api/tests) && git commit -m "feat(inbox): decay keep_active and clarification answers reach the claim layer (G113 slice 3)"
```

---

### Task 6: Surface — `GET /consumption/feedback` and a fifth Usage tile

**Files:**
- Modify: `api/services/consumption_stats.py` (append `feedback(...)` after `per_connection`, ~line 260)
- Modify: `api/models/schemas.py:1452` (add `ConsumptionFeedback` after `ConsumptionStats`)
- Modify: `api/routers/consumption.py` (import + `GET /feedback` after `/stats`, ~line 95)
- Modify: `app/CicadaApp/Sources/CicadaApp/Models/Consumption.swift:256` (`ConsumptionFeedback`, `ConsumptionBundle.feedback`)
- Modify: `app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift:1274-1291` (`fetchConsumptionFeedback`) and `:1903-1948` (`fetchConsumption` fan-out)
- Modify: `app/CicadaApp/Sources/CicadaApp/ViewModels/UsageViewModel.swift:102` (feedback projection + tile strings)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Usage/UsageView.swift:99-107` (fifth `StatTile`)
- Modify: `app/CicadaApp/Tests/CicadaAppTests/ConsumptionFetchTests.swift:49-63,75-86` (both mock handlers gain a `/consumption/feedback` case)
- Modify: `app/CicadaApp/Tests/CicadaAppTests/ConsumptionDecodingTests.swift` (two new tests)
- Test: `api/tests/test_consumption_feedback.py` (new)

**Interfaces:**
- Consumes: the `resolution` / `audit` / `dedup_verdict` events Task 2 emits — `refs` keys `kind`, `action`, `verdict` (`agreed|overruled|neutral`), `extractor_confidence` (float or None) on `resolution`; `refs.action` (`supersede|rejected`) on `audit`; `refs.verdict` (`same|different|unsure`) and `refs.applied` (`merged|proposed|nudged|none`) on `dedup_verdict`. `telemetry.FEEDBACK_KINDS`.
- Produces: `consumption_stats.feedback(memory_path, *, range_, today) -> dict`; `schemas.ConsumptionFeedback`; `GET /consumption/feedback?range=`; Swift `ConsumptionFeedback`, `ConsumptionBundle.feedback: ConsumptionFeedback?` (defaults nil), `APIClient.fetchConsumptionFeedback(range:)`, `UsageViewModel.feedback / feedbackValue / feedbackFootnote`.

**Shape (the contract Swift decodes):**

```
{
  "range": "month", "since": "2026-09-01",
  "resolutions": 12,          # every resolution event, neutral included
  "corrections": 3,           # verdict == overruled
  "rate": 0.7,                # agreed / (agreed + overruled); null when that denominator is 0
  "agreement":   [{"kind": "conflict", "total": 5, "agreed": 3, "overruled": 1, "rate": 0.75}, ...],   # one row per inbox kind seen, sorted by total desc
  "calibration": [{"bucket": "<0.5", "n": 2, "agreedRate": 0.5}, {"bucket": "0.5–0.7", ...}, {"bucket": "0.7–0.9", ...}, {"bucket": "≥0.9", ...}],  # always all four buckets, in this order; agreedRate null when n == 0
  "byAction":    [{"action": "pick:1", "n": 4}, ...],   # sorted by n desc
  "audits":      {"supersede": 7, "rejected": 2},
  "dedup":       {"same": 1, "different": 3, "unsure": 1, "merged": 1}
}
```

`resolutions` counts neutral verdicts (defer/skip/both) so "how often does the person engage" is visible, but `rate` and every `agreedRate` exclude them — a deferral is not a judgement. Calibration buckets come from `extractor_confidence` on the event; a resolution with no confidence (decay items, clarifications) is left out of the calibration table but still counted everywhere else.

- [ ] **Step 1: Write the failing API tests**

```python
# api/tests/test_consumption_feedback.py
"""G113 slice 4: the feedback ledger becomes numbers on /consumption/feedback."""
from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import consumption_stats as cs
from api.services import telemetry as tm
from api.services.connections import registry

TODAY = date(2026, 9, 2)


def _res(ts: str, kind: str, action: str, verdict: str, conf: float | None = None) -> None:
    tm.record(tm.UsageEvent(ts=ts, kind="resolution", stage="feedback", bank="memory", invocations=0, billing="free",
                            refs={"item_id": "inbox-001", "kind": kind, "predicate": "works-at", "entity_id": "alpha-project",
                                  "action": action, "option_key": None, "verdict": verdict,
                                  "winner_claim_id": None, "loser_claim_ids": [],
                                  "extractor_confidence": conf, "extractor_model": "gpt-5.4-mini", "item_age_days": 3}))


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    repo = tmp_path / "memory"
    (repo / "entities").mkdir(parents=True)
    _res("2026-09-01T10:00:00.000Z", "conflict", "pick:1", "agreed", 0.92)
    _res("2026-09-01T10:01:00.000Z", "conflict", "pick:0", "overruled", 0.55)
    _res("2026-09-01T10:02:00.000Z", "conflict", "defer", "neutral", 0.55)
    _res("2026-09-01T10:03:00.000Z", "decay", "archive", "agreed")
    _res("2026-09-01T10:04:00.000Z", "decay", "keep_active", "overruled")
    _res("2026-08-01T10:00:00.000Z", "clarification", "answer", "agreed", 0.3)  # outside "month"
    tm.record(tm.UsageEvent(ts="2026-09-01T11:00:00.000Z", kind="audit", stage="reconcile", bank="memory", invocations=0,
                            billing="free", refs={"action": "supersede", "subject": "alpha-project", "closed": "c1", "by": "c2"}))
    tm.record(tm.UsageEvent(ts="2026-09-01T11:00:01.000Z", kind="audit", stage="reconcile", bank="memory", invocations=0,
                            billing="free", refs={"action": "rejected", "subject": "alpha-project", "kept": "c1", "dropped": "c3"}))
    tm.record(tm.UsageEvent(ts="2026-09-01T12:00:00.000Z", kind="dedup_verdict", stage="dedup", bank="memory", invocations=0,
                            billing="free", refs={"a": "a", "b": "b", "verdict": "same", "confidence": 0.9, "winner": "a", "applied": "merged"}))
    tm.record(tm.UsageEvent(ts="2026-09-01T12:00:01.000Z", kind="dedup_verdict", stage="dedup", bank="memory", invocations=0,
                            billing="free", refs={"a": "c", "b": "d", "verdict": "unsure", "confidence": 0.4, "winner": None, "applied": "nudged"}))
    # an LLM call in range must not leak into any feedback number
    tm.record(tm.UsageEvent(ts="2026-09-01T09:00:00.000Z", kind="llm_call", stage="extraction", model="gpt-5.4-mini",
                            connection="byok-openai", input_tokens=10, output_tokens=5, cost_usd=0.01, equiv_cost_usd=0.01))
    return repo


def test_feedback_counts_and_rate(ledger: Path):
    fb = asyncio.run(cs.feedback(ledger, range_="month", today=TODAY))
    assert fb["range"] == "month" and fb["since"] == "2026-09-01"
    assert fb["resolutions"] == 5          # the August one is out of range; neutral is counted
    assert fb["corrections"] == 2
    assert fb["rate"] == pytest.approx(2 / 4)   # 2 agreed / (2 agreed + 2 overruled); neutral excluded


def test_feedback_agreement_per_kind(ledger: Path):
    fb = asyncio.run(cs.feedback(ledger, range_="month", today=TODAY))
    rows = {r["kind"]: r for r in fb["agreement"]}
    assert set(rows) == {"conflict", "decay"}
    assert rows["conflict"] == {"kind": "conflict", "total": 3, "agreed": 1, "overruled": 1, "rate": pytest.approx(0.5)}
    assert rows["decay"]["rate"] == pytest.approx(0.5)
    assert [r["kind"] for r in fb["agreement"]] == ["conflict", "decay"]   # sorted by total desc


def test_feedback_calibration_buckets(ledger: Path):
    fb = asyncio.run(cs.feedback(ledger, range_="month", today=TODAY))
    buckets = {b["bucket"]: b for b in fb["calibration"]}
    assert [b["bucket"] for b in fb["calibration"]] == ["<0.5", "0.5–0.7", "0.7–0.9", "≥0.9"]
    assert buckets["≥0.9"] == {"bucket": "≥0.9", "n": 1, "agreed_rate": pytest.approx(1.0)}
    assert buckets["0.5–0.7"] == {"bucket": "0.5–0.7", "n": 1, "agreed_rate": pytest.approx(0.0)}  # the deferral is neutral: not counted
    assert buckets["<0.5"] == {"bucket": "<0.5", "n": 0, "agreed_rate": None}


def test_feedback_actions_audits_dedup(ledger: Path):
    fb = asyncio.run(cs.feedback(ledger, range_="month", today=TODAY))
    assert fb["by_action"][0]["n"] == 1 and {r["action"] for r in fb["by_action"]} == {"pick:1", "pick:0", "defer", "archive", "keep_active"}
    assert fb["audits"] == {"supersede": 1, "rejected": 1}
    assert fb["dedup"] == {"same": 1, "different": 0, "unsure": 1, "merged": 1}


def test_feedback_all_range_and_empty(ledger: Path, tmp_path):
    fb = asyncio.run(cs.feedback(ledger, range_="all", today=TODAY))
    assert fb["resolutions"] == 6 and fb["since"] is None
    empty = asyncio.run(cs.feedback(ledger, range_="1d", today=date(2020, 1, 1)))
    assert empty["resolutions"] == 0 and empty["rate"] is None and empty["agreement"] == []
    assert [b["n"] for b in empty["calibration"]] == [0, 0, 0, 0]
    assert empty["audits"] == {"supersede": 0, "rejected": 0}
    assert empty["dedup"] == {"same": 0, "different": 0, "unsure": 0, "merged": 0}


@pytest.fixture
def client(ledger, tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(ledger))
    config.get_settings.cache_clear()
    registry.reset_registry()
    yield TestClient(main.app)
    registry.reset_registry()
    config.get_settings.cache_clear()


def test_feedback_endpoint_camel_and_etag(client):
    r = client.get("/consumption/feedback?range=all")
    assert r.status_code == 200
    body = r.json()
    assert body["resolutions"] == 6 and body["corrections"] == 2
    assert body["agreement"][0]["kind"] == "conflict"
    assert body["calibration"][3]["agreedRate"] == pytest.approx(1.0)   # rows are camelCased like /stats
    assert body["byAction"] and "n" in body["byAction"][0]
    etag = r.headers["ETag"]
    assert client.get("/consumption/feedback?range=all", headers={"If-None-Match": etag}).status_code == 304
    assert client.get("/consumption/feedback?range=bogus").status_code == 422
```

Note for the implementer: the API test's `client` fixture does not stub `Registry.statuses` because `/feedback` never touches the connections registry — if the app's startup hooks (`main.app` lifespan) need `CICADA_HOME` and a memory path, both are set by the two fixtures. If the TestClient trips on bank migrations for an empty `memory/` dir, copy whatever `api/tests/test_consumption_api.py::client` does beyond what is here (read it; it is 20 lines).

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g113 && api/.venv/bin/python -m pytest api/tests/test_consumption_feedback.py -q -p no:cacheprovider`
Expected: FAIL — `AttributeError: module 'api.services.consumption_stats' has no attribute 'feedback'`.

- [ ] **Step 3: `consumption_stats.feedback`**

Append to `api/services/consumption_stats.py` (after `per_connection`):

```python
_CAL_BUCKETS: tuple[tuple[str, float, float], ...] = (
    ("<0.5", 0.0, 0.5), ("0.5–0.7", 0.5, 0.7), ("0.7–0.9", 0.7, 0.9), ("≥0.9", 0.9, 1.01),
)


def _rate(agreed: int, overruled: int) -> float | None:
    judged = agreed + overruled
    return round(agreed / judged, 4) if judged else None


async def feedback(memory_path: Path, *, range_: str, today: date) -> dict:
    """The grounded-reward ledger (G113) as numbers.

    Reads only the three ``telemetry.FEEDBACK_KINDS`` events. A ``neutral``
    verdict (defer / skip / "both") counts toward ``resolutions`` — it is
    engagement — but never toward a rate: a deferral is not a judgement on
    the extractor. Calibration buckets use the ``extractor_confidence`` ref
    the resolution event carried; events without one (decay, clarification)
    are simply absent from that table. ``memory_path`` is accepted for
    signature parity with the other aggregators; nothing here reads the bank.
    """
    start = resolve_range(range_, today)
    events = [e for e in _events_in(range_, today) if e.kind in telemetry.FEEDBACK_KINDS]
    resolutions = [e for e in events if e.kind == "resolution"]

    per_kind: dict[str, dict] = defaultdict(lambda: {"total": 0, "agreed": 0, "overruled": 0})
    actions: Counter[str] = Counter()
    cal: dict[str, dict] = {name: {"n": 0, "agreed": 0} for name, _, _ in _CAL_BUCKETS}
    agreed = overruled = 0
    for e in resolutions:
        refs = e.refs or {}
        verdict = refs.get("verdict")
        kind = str(refs.get("kind") or "unknown")
        row = per_kind[kind]
        row["total"] += 1
        actions[str(refs.get("action") or "unknown")] += 1
        if verdict not in ("agreed", "overruled"):
            continue
        row[verdict] += 1
        if verdict == "agreed":
            agreed += 1
        else:
            overruled += 1
        conf = refs.get("extractor_confidence")
        if isinstance(conf, (int, float)):
            for name, lo, hi in _CAL_BUCKETS:
                if lo <= float(conf) < hi:
                    cal[name]["n"] += 1
                    cal[name]["agreed"] += verdict == "agreed"
                    break

    agreement = [
        {"kind": k, "total": r["total"], "agreed": r["agreed"], "overruled": r["overruled"],
         "rate": _rate(r["agreed"], r["overruled"])}
        for k, r in per_kind.items()
    ]
    agreement.sort(key=lambda r: (-r["total"], r["kind"]))
    calibration = [
        {"bucket": name, "n": cal[name]["n"],
         "agreed_rate": round(cal[name]["agreed"] / cal[name]["n"], 4) if cal[name]["n"] else None}
        for name, _, _ in _CAL_BUCKETS
    ]
    by_action = [{"action": a, "n": n} for a, n in actions.most_common()]

    audits = Counter(str((e.refs or {}).get("action")) for e in events if e.kind == "audit")
    dedup_events = [e for e in events if e.kind == "dedup_verdict"]
    dedup_verdicts = Counter(str((e.refs or {}).get("verdict")) for e in dedup_events)
    return {
        "range": range_,
        "since": start.isoformat() if start else None,
        "resolutions": len(resolutions),
        "corrections": overruled,
        "rate": _rate(agreed, overruled),
        "agreement": agreement,
        "calibration": calibration,
        "by_action": by_action,
        "audits": {"supersede": audits.get("supersede", 0), "rejected": audits.get("rejected", 0)},
        "dedup": {
            "same": dedup_verdicts.get("same", 0),
            "different": dedup_verdicts.get("different", 0),
            "unsure": dedup_verdicts.get("unsure", 0),
            "merged": sum(1 for e in dedup_events if (e.refs or {}).get("applied") == "merged"),
        },
    }
```

- [ ] **Step 4: Schema + router**

In `api/models/schemas.py`, directly after `class ConsumptionStats`:

```python
class ConsumptionFeedback(CamelModel):
    """G113: the grounded-reward ledger as numbers. Ids/enums-derived counts only."""
    range: str
    since: Optional[str] = None
    resolutions: int = 0
    corrections: int = 0
    rate: Optional[float] = None
    agreement: list[dict] = []
    calibration: list[dict] = []
    by_action: list[dict] = []
    audits: dict = {}
    dedup: dict = {}
```

In `api/routers/consumption.py`: add `ConsumptionFeedback` to the `api.models.schemas` import, then after the `/stats` handler:

```python
@router.get("/feedback", response_model=ConsumptionFeedback)
async def feedback(
    request: Request,
    response: Response,
    range_: str = Depends(_range),
    settings: Settings = Depends(get_settings),
):
    memory_path = settings.memory_path
    today = _utc_today()
    etag = sync_service.etag_for(memory_path, "telemetry", extra=f"feedback:{range_}:{today}")
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    data = await consumption_stats.feedback(memory_path, range_=range_, today=today)
    for key in ("agreement", "calibration", "by_action"):
        data[key] = _camel_rows(data[key])
    return ConsumptionFeedback(**data)
```

`etag_for` with a single component: check its signature at `api/services/sync_service.py` (search `def etag_for`) — if it requires ≥2 components or the `git_head` one, pass `"telemetry", "git_head"` exactly as `/summary` does; a spurious git-head bump only costs a refetch. The `extra=` prefix `feedback:` keeps this ETag distinct from `/summary`'s for the same range and day.

- [ ] **Step 5: Run the API tests**

Run: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g113 && api/.venv/bin/python -m pytest api/tests/test_consumption_feedback.py api/tests/test_consumption_api.py api/tests/test_consumption_stats.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 6: Write the failing Swift tests**

Append to `app/CicadaApp/Tests/CicadaAppTests/ConsumptionDecodingTests.swift` inside the class:

```swift
    /// G113: the feedback section is optional on the wire (an older backend
    /// has no `/consumption/feedback`) and in the disk cache (a bundle
    /// written before this build has no `feedback` key) — both must decode.
    func testBundleWithoutFeedbackDecodesToNil() throws {
        let json = """
        {"summary":{"costUsd":2.5,"range":"month"},
         "calendar":{"days":[],"weeks":53},
         "stats":{"byModel":[],"byStage":[],"byConnection":[],"byBank":[],"hourHistogram":[0],"series":[],"range":"month"},
         "connections":{"connections":[],"range":"month"},
         "harness":{}}
        """.data(using: .utf8)!
        let bundle = try JSONDecoder().decode(ConsumptionBundle.self, from: json)
        XCTAssertNil(bundle.feedback)
    }

    func testFeedbackDecodesWithMissingFieldsAndRoundTrips() throws {
        let sparse = try JSONDecoder().decode(ConsumptionFeedback.self, from: Data(#"{"range":"month"}"#.utf8))
        XCTAssertEqual(sparse.resolutions, 0)
        XCTAssertNil(sparse.rate)
        let full = try JSONDecoder().decode(ConsumptionFeedback.self, from: Data("""
        {"range":"month","since":"2026-09-01","resolutions":12,"corrections":3,"rate":0.7,
         "agreement":[{"kind":"conflict","total":5,"agreed":3,"overruled":1,"rate":0.75}],
         "calibration":[{"bucket":"<0.5","n":0,"agreedRate":null}],
         "byAction":[{"action":"pick:1","n":4}],
         "audits":{"supersede":7,"rejected":2},
         "dedup":{"same":1,"different":3,"unsure":1,"merged":1}}
        """.utf8))
        XCTAssertEqual(full.resolutions, 12)
        XCTAssertEqual(full.corrections, 3)
        XCTAssertEqual(full.rate, 0.7)
        XCTAssertEqual(full.agreement.count, 1)
        let back = try JSONDecoder().decode(ConsumptionFeedback.self, from: JSONEncoder().encode(full))
        XCTAssertEqual(back.rate, 0.7)
        XCTAssertEqual(back.audits["supersede"], 7)
    }
```

In `ConsumptionFetchTests.swift`, add to BOTH `MockURLProtocol.handler` switches (the 304 test at ~line 49 and the all-fresh test at ~line 75) a case before `default:`:

```swift
            case "/consumption/feedback":
                return self.ok(request.url!, #"{"range":"month","resolutions":4,"corrections":1,"rate":0.75}"#)
```

and to the all-fresh test's assertions: `XCTAssertEqual(result.value?.feedback?.rate, 0.75)`. Add a third test that pins the 404 tolerance:

```swift
    /// An older backend without `/consumption/feedback` must not sink the
    /// whole dashboard: the section is nil, everything else still lands.
    func testA404OnFeedbackLeavesTheRestOfTheBundleIntact() async throws {
        MockURLProtocol.handler = { request in
            switch request.url!.path {
            case "/consumption/summary": return self.ok(request.url!, #"{"costUsd":1.5,"range":"month"}"#)
            case "/consumption/calendar": return self.ok(request.url!, #"{"days":[],"weeks":53}"#)
            case "/consumption/stats": return self.ok(request.url!, #"{"byModel":[],"byStage":[],"byConnection":[],"byBank":[],"hourHistogram":[0],"series":[],"range":"month"}"#)
            case "/consumption/connections": return self.ok(request.url!, #"{"connections":[],"range":"month"}"#)
            case "/consumption/harness": return self.ok(request.url!, "{}")
            case "/consumption/feedback":
                return (HTTPURLResponse(url: request.url!, statusCode: 404, httpVersion: nil, headerFields: nil)!, Data())
            default:
                XCTFail("unexpected path \(request.url!.path)")
                throw URLError(.badURL)
            }
        }
        let result = try await APIClient(session: MockURLProtocol.makeSession()).fetchConsumption(etag: nil, current: nil)
        XCTAssertFalse(result.notModified)
        XCTAssertEqual(result.value?.summary.costUsd, 1.5)
        XCTAssertNil(result.value?.feedback)
    }
```

- [ ] **Step 7: Run Swift tests to verify they fail**

Run: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g113/app/CicadaApp && swift test --filter 'ConsumptionDecodingTests|ConsumptionFetchTests' 2>&1 | tail -20`
Expected: build FAILS — `ConsumptionFeedback` / `feedback` undefined.

- [ ] **Step 8: Swift model**

In `Models/Consumption.swift`, before `struct ConsumptionBundle`:

```swift
/// G113 — `GET /consumption/feedback`. Decode-tolerant like the rest of this
/// file: an older backend returns 404 (the bundle carries `nil`), a newer one
/// may add fields. `agreement`/`calibration`/`byAction` are loose rows for
/// the same reason `ConsumptionStats.byModel` is — the tile only needs the
/// scalars; the rows are kept so a future Advanced section can render them
/// without a model change.
struct ConsumptionFeedback: Codable {
    var range: String = "month"
    var since: String?
    var resolutions: Int = 0
    var corrections: Int = 0
    var rate: Double?
    var agreement: [StatsRow] = []
    var calibration: [StatsRow] = []
    var byAction: [StatsRow] = []
    var audits: [String: Int] = [:]
    var dedup: [String: Int] = [:]

    init() {}
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        range = try c.decodeIfPresent(String.self, forKey: .range) ?? "month"
        since = try c.decodeIfPresent(String.self, forKey: .since)
        resolutions = try c.decodeIfPresent(Int.self, forKey: .resolutions) ?? 0
        corrections = try c.decodeIfPresent(Int.self, forKey: .corrections) ?? 0
        rate = try c.decodeIfPresent(Double.self, forKey: .rate)
        agreement = try c.decodeIfPresent([StatsRow].self, forKey: .agreement) ?? []
        calibration = try c.decodeIfPresent([StatsRow].self, forKey: .calibration) ?? []
        byAction = try c.decodeIfPresent([StatsRow].self, forKey: .byAction) ?? []
        audits = try c.decodeIfPresent([String: Int].self, forKey: .audits) ?? [:]
        dedup = try c.decodeIfPresent([String: Int].self, forKey: .dedup) ?? [:]
    }
}
```

`StatsRow` is the loose-dict row type `ConsumptionStats.byModel` already decodes (see `testStatsRowsDecodeLooseDicts` in `ConsumptionDecodingTests.swift` and its declaration in this same file) — confirm its exact name and that it is `Codable` in both directions before using it; if it is decode-only, use the same `[String: LooseValue]`-style dictionary `HarnessStats.claudeCode` uses (declared in this file too). Do not invent a third row type.

Then change `ConsumptionBundle` to:

```swift
struct ConsumptionBundle: Codable {
    let summary: ConsumptionSummary
    let calendar: ConsumptionCalendar
    let stats: ConsumptionStats
    let connections: ConsumptionConnections
    let harness: HarnessStats
    /// G113 — nil when the backend predates `/consumption/feedback` or the
    /// cached bundle predates this build. Defaulted so the four existing
    /// five-argument memberwise call sites (APIClient + three tests) compile.
    var feedback: ConsumptionFeedback? = nil
}
```

Synthesized `Codable` decodes a missing `feedback` key as `nil` for an optional `var` — that is what `testBundleWithoutFeedbackDecodesToNil` pins.

- [ ] **Step 9: APIClient**

Next to `fetchHarnessStats()` (~line 1291):

```swift
    func fetchConsumptionFeedback(range: String) async throws -> ConsumptionFeedback {
        try await get("/consumption/feedback?range=\(range)")
    }
```

In `fetchConsumption(etag:current:)`, add a sixth branch to the fan-out. `/feedback` is ETag'd server-side but the bundle's three-part etag string is a stored contract (`"s|c|st"` pipe-joined, parsed with `(0..<3)`), so do NOT widen it — fetch feedback unconditionally like `/connections`, and swallow a 404 into `nil` per branch (the outer `catch APIError.httpError(404, _)` must keep meaning "no dashboard at all", so this branch must not throw 404 into it):

```swift
            async let fb: ConsumptionFeedback? = {
                do { return try await self.fetchConsumptionFeedback(range: range) }
                catch APIError.httpError(404, _) { return nil }
            }()
            let (summaryResult, calendarResult, statsResult, connections, harness, feedback) = try await (s, c, st, conn, h, fb)
            let bundle = ConsumptionBundle(
                summary: summaryResult.value ?? current?.summary ?? ConsumptionSummary(),
                calendar: calendarResult.value ?? current?.calendar ?? ConsumptionCalendar(days: [], weeks: weeks),
                stats: statsResult.value ?? current?.stats ?? Self.emptyConsumptionStats,
                connections: connections,
                harness: harness,
                feedback: feedback
            )
```

Update the doc comment above it: "Fans out to all six `/consumption/*` endpoints … `/feedback` is fetched unconditionally and a 404 there means only that section is missing (older backend), never that the dashboard is."

- [ ] **Step 10: ViewModel + View**

In `UsageViewModel.swift`, after `var harness` (line 102):

```swift
    /// G113 feedback tile. Only the Store's default "month" view carries the
    /// section — `RangeFetch` is a three-tuple and widening it drags
    /// `UsageRangeTests` along, so other ranges render the tile as a dash
    /// with an honest footnote rather than a stale month number.
    var feedback: ConsumptionFeedback? { range == "month" ? store.consumption.value?.feedback : nil }

    var feedbackValue: String {
        guard let f = feedback else { return "—" }
        guard let r = f.rate else { return f.resolutions == 0 ? "—" : "n/a" }
        return "\(Int((r * 100).rounded()))%"
    }

    var feedbackFootnote: String {
        guard range == "month" else { return "month view only" }
        guard let f = feedback else { return "no feedback ledger" }
        if f.resolutions == 0 { return "no resolutions yet" }
        return "\(UsageFormat.count(f.resolutions)) resolutions · \(UsageFormat.count(f.corrections)) corrections"
    }
```

In `UsageView.swift` after the "Streak" tile (line 106):

```swift
                StatTile(title: "Feedback", value: viewModel.feedbackValue, footnote: viewModel.feedbackFootnote)
```

`"n/a"` is the case where every resolution in the month was neutral (all deferrals): there is engagement but no judgement, and a "—" would read as "nothing happened". Keep the copy exactly this so the tile's three states are distinguishable.

- [ ] **Step 11: Run the Swift tests**

Run: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g113/app/CicadaApp && swift test 2>&1 | tail -15`
Expected: all tests pass (the full suite, not just the filter — `UsageRangeTests` and the `SnapshotCache` tests exercise the memberwise init and the disk round-trip).

- [ ] **Step 12: Commit**

```bash
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g113 && git add api/services/consumption_stats.py api/models/schemas.py api/routers/consumption.py api/tests/test_consumption_feedback.py app/CicadaApp/Sources/CicadaApp/Models/Consumption.swift app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift app/CicadaApp/Sources/CicadaApp/ViewModels/UsageViewModel.swift app/CicadaApp/Sources/CicadaApp/Views/Usage/UsageView.swift app/CicadaApp/Tests/CicadaAppTests/ConsumptionFetchTests.swift app/CicadaApp/Tests/CicadaAppTests/ConsumptionDecodingTests.swift && git commit -m "feat(usage): GET /consumption/feedback + Feedback tile — the grounded-reward ledger as a number (G113 slice 4)"
```

---

### Task 7: Docs — CLAUDE.md, backlog row, TODO handoff

**Files:**
- Modify: `CLAUDE.md:387-388` (telemetry ledger paragraph), `:646` (API list), `:671-672` (inbox kinds), and the "Resolve is claim-aware" paragraph below it
- Modify: `docs/goals/memory-evolution.md:675` (the G113 row — one line; edit with a targeted `python - <<'PY'` string replace, never by hand-retyping a 6 KB line)
- Modify: `docs/goals/TODO.md` (Shipped list, Wave B item 4a, handoff header)

**Interfaces:** none — prose only. Everything asserted below must be true of the branch as committed by Tasks 1–6; if a task changed a name, follow the code, not this text.

- [ ] **Step 1: CLAUDE.md**

1. In the "Telemetry ledger" paragraph (line ~388), after "and MCP `cicada_write_claim`." insert:
   "**Feedback events (G113):** every inbox resolution emits a `resolution` event (`stage: feedback`, `refs` = item id, kind, predicate, entity id, action label, `verdict: agreed|overruled|neutral`, winner/loser claim ids, the extractor's confidence and model — ids and enums only, never claim text), Stage-3 reconcile emits one `audit` event per supersede/reject, and the dedup sweep emits one `dedup_verdict` per judged pair. `telemetry.FEEDBACK_KINDS` names the three; `consumption_stats.stats()` excludes them from `by_connection` so they never show as an "unknown" connection. Nothing learned from the ledger is auto-applied — `GET /consumption/feedback` shows the rates; feeding them back into prompts is G78."
2. In the API list (line ~646) change the `/consumption` line to `GET  /consumption/summary|calendar|stats|connections|harness|feedback → …` and add a sub-line: `                                            /feedback (G113): agreement rate, per-kind rows, confidence calibration, audits, dedup verdicts`.
3. Inbox kinds (line ~672): replace ``(`decay`, `conflict`, `clarification`, `merge_suggestion`)`` with ``(`decay`, `conflict`, `clarification`, `merge_suggestion`, `divergence`, `normalization` — the last two were written by Sleep since G49/G98 but only became loadable and resolvable kinds with G113)``.
4. After the "Resolve is claim-aware" paragraph add one paragraph: "**Every resolution is a verdict (G113).** The commit trigger names the action (`inbox/<kind>/resolved:<label>`; a deferral stays `inbox/deferred`), decay `archive`/`keep_active` land as `statusChange` history entries, a decay `keep_active` and a clarification free-text answer write back to the claim layer, a rejected merge is remembered in `<bank>/_merge_rejected.yaml` so neither `clarification_manager` nor the dedup sweep proposes the pair again, and `remind_later` is a 7-day defer. Each of these also records a `resolution` telemetry event — see Telemetry ledger."

- [ ] **Step 2: Backlog row**

Run from the worktree root (adjust the PR number placeholder ONLY if the PR already exists; otherwise leave `#TBD` — the merge step fixes it):

```bash
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g113 && api/.venv/bin/python - <<'PY'
from pathlib import Path
p = Path("docs/goals/memory-evolution.md")
s = p.read_text()
old_tail = "a compiled skill's `## Evidence` is only trustworthy once verdicts are counted). | 🔲 |"
assert s.count(old_tail) == 1, "G113 row tail not found exactly once"
new_tail = ("a compiled skill's `## Evidence` is only trustworthy once verdicts are counted). "
            "**Shipped 2026-09-02 (PR #TBD, `feat/feedback-ledger`) — slices 1–4:** trigger `inbox/<kind>/resolved:<label>` + "
            "`statusChange` for decay; `resolution`/`audit`/`dedup_verdict` events (`telemetry.FEEDBACK_KINDS`, ids/enums only); "
            "`divergence` + `normalization` resolvable in API and Swift; merge reject persisted in `_merge_rejected.yaml`; "
            "decay `keep_active` and clarification answers reach the claim layer; `remind_later` = 7-day defer; "
            "`GET /consumption/feedback` + Feedback tile. Slice 5 (rates → prompts) stays 💸 DECIDE under G78. | ✅ |")
p.write_text(s.replace(old_tail, new_tail))
print("ok")
PY
```

- [ ] **Step 3: TODO.md**

1. Under `## ✅ Shipped`, add a line in the style of its neighbours: "**G113 grounded-reward ledger (2026-09-02, PR #TBD)** — every inbox verdict is a `resolution` telemetry event; `/consumption/feedback` + Feedback tile; divergence/normalization resolvable; merge reject sticks; keep_active/answers write claims."
2. Remove the Wave B item `4a. **G113 slices 1–4**` (and renumber nothing — the list uses explicit labels).
3. In `## Where things stand`, update the date line and the in-flight PR list to name `feat/feedback-ledger` as open (or merged, if Step 4 of the merge procedure already ran), and in `## Pick up here` replace the G113 bullet with the next item the Wave order names.

- [ ] **Step 4: Verify nothing else references the old kind set**

Run: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g113 && grep -rn "merge_suggestion\`)" CLAUDE.md docs/goals/TODO.md; grep -rn "snooze_until" CLAUDE.md docs/goals/`
Expected: no output (the four-kind tuple is gone from prose; `snooze_until` is not documented anywhere as the remind-later contract).

- [ ] **Step 5: Commit**

```bash
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/g113 && git add CLAUDE.md docs/goals/memory-evolution.md docs/goals/TODO.md && git commit -m "docs(G113): feedback ledger, six inbox kinds, /consumption/feedback; backlog row shipped, TODO handoff refreshed"
```

---

## Self-review notes (for the executor, not a task)

- Task 3 must ship the Swift `InboxKind` cases in the same commit as the API kinds (R4) — a strict enum decode with an unknown case drops the whole `/inbox` payload.
- Task 6's `ConsumptionBundle.feedback` MUST be `var … = nil`; a `let` without a default breaks the four memberwise call sites and the on-disk cache decode.
- The `≥0.9` and `0.5–0.7` bucket labels contain non-ASCII characters on purpose (they are display strings); the Swift test compares them only through `count`, and the Python test compares them exactly — keep them byte-identical between `_CAL_BUCKETS` and the test.
- No task touches `memory/`; the API tests build their own bank under `tmp_path`.
