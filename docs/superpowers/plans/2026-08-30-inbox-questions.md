# Inbox Questions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Cicada's inbox conflict/clarification/merge items into time-aware, deduplicated **question objects** (Claude Code `AskUserQuestion` shape) whose resolution actually closes claims, plus a minimal `sources:` "where to check this fact" layer on entity pages.

**Architecture:** Every generated inbox item of kind `conflict` / `clarification` / `merge_suggestion` gains a `question` string and a structured `options: [{key,label,description,claim_id,observed_at,last_referenced}]` list written at generation time, with staleness (`humanize_age`) baked into each description. `inbox_generator.find_open` makes generation idempotent per `(entity_id, predicate)` — a second competing value **merges** into the open item as a new option instead of writing a duplicate file. A new Stage-3 step `refresh_open_questions` re-scores open questions each Sleep (bump/re-order, auto-resolve organically, escalate stale ones, keep deferred ones hidden). `inbox_service._resolve_conflict` becomes claim-aware: it supersedes losing claims bi-temporally, writes a `user_stated` claim for free text, and defers via `remind_after`. The SwiftUI card collapses its three per-kind branches into one `QuestionView` driven by a pure, unit-testable `QuestionSelection` model.

**Tech Stack:** Python 3.12 / FastAPI / pydantic v2 (`CamelModel`) / PyYAML / pytest (`api/.venv/bin/python -m pytest api/tests -q`); Swift 6 / SwiftUI / SwiftPM (`cd app/CicadaApp && swift test`); MCP JSON-RPC stdio server (`mcp/server.py`, stdlib-only handlers).

**Spec:** `docs/superpowers/specs/2026-08-30-inbox-questions-design.md`

## Global Constraints

- **Never touch `.claude/settings.json`** — it is modified in the working tree and is not part of this work.
- **Never `git add -A`** in the *project* repo. Every commit step lists explicit paths. (The memory-bank repo's own `git_service.commit_changes` already does `add -A` inside `<memory>/`; that is pre-existing and out of scope.)
- **Memory bank contents under `memory/` are never part of a branch.** Every test builds a throwaway workspace with `tmp_path`; no test may read or write the live `memory/` directory.
- **Every project commit ends with these two trailer lines** (blank line before them):
  ```
  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
  ```
- **Cicada writes triggered by a user action get `Cicada-Author: user`** trailers, built via `git_service.build_commit_message(subject, body_lines, authors=["user"])`.
- **Keep the legacy flat `options: [str]` readable.** `inbox_service._item_from_file` upgrades a flat list to `{"key": str(i), "label": s}`; the Swift decoder accepts both shapes. New writes always emit the object form.
- **`api/routers/nudges.py` and `api/routers/clarifications.py` deprecated shims must keep working** — they project the unified store into the old response shapes and set `Deprecation: true`.
- **Swift view models are projections over `Store`** (`app/CicadaApp/Sources/CicadaApp/Sync/Store.swift`); writes go through the `Mutation` protocol (`Sync/Mutations.swift`), never a direct `APIClient` call from a view.
- **All new Swift logic that can be pure goes in a testable type** (e.g. `QuestionSelection`), not inside a `View`'s body.
- Run the full Python suite with `api/.venv/bin/python -m pytest api/tests -q` and the Swift suite with `cd app/CicadaApp && swift test` before each commit step that touches that side.

---

## File Structure

**New Python files**
- `api/services/inbox_questions.py` — `humanize_age`, `age_days`, `option_from_claim`, `normalize_options`, `is_deferred`, `refresh_open_questions`. Pure date/dict logic + one filesystem sweep. No LLM.
- `api/services/fact_sources.py` — the G61 `sources:` frontmatter layer (`infer_kind`, `list_sources`, `add_source`, `delete_source`, `hint_for`). **Named `fact_sources`, not `entity_sources`** — `api/services/entity_sources.py` already exists and means something else (episode→conversation provenance).

**Modified Python files**
- `api/services/predicates.py` — add `PREDICATE_QUESTIONS` + `predicate_question(predicate, name)`.
- `api/services/claim_reconciler.py:221-239` — `_conflict_nudge` emits the question object.
- `api/services/inbox_generator.py` — `find_open`, `dedup_key`, `merge_options_into`; conflict/clarification/merge writes go through them.
- `api/services/inbox_migration.py` — `dedup_open_items(memory_path)` one-shot migration.
- `api/services/conflict_resolver.py:598-640` — `_CONTRADICTION_PROMPT` asks for `question` + per-option `description`; template fallback.
- `api/services/inbox_service.py` — `_item_from_file` upgrade, `load_inbox` hides deferred, `_resolve_conflict` rewrite, `defer` action.
- `api/services/sleep_cycle.py` — call `refresh_open_questions` in Stage 5.56; new `SleepState` counters.
- `api/services/agentic_write.py` — `write_claim(..., sources=[...])`.
- `api/models/schemas.py` — `InboxOption`, `InboxItem` new fields, `InboxResolveRequest.option_key/remind_days`, `EntitySource`/`EntitySourceCreate`/`EntitySourceList`, `SleepStatusResponse` counters.
- `api/routers/entities.py` — `GET/POST/DELETE /entities/{id}/sources`.
- `api/config.py` — `inbox_stale_after_days`, `inbox_defer_days`.
- `api/main.py` — run `dedup_open_items` at startup after `migrate_to_inbox`.
- `mcp/server.py` — question rendering in `_format_inbox_blurb` / `handle_check_nudges`; `cicada_resolve_inbox` tool; `sources` arg on `cicada_write_claim`.

**New Swift files**
- `Sources/CicadaApp/Models/QuestionSelection.swift` — pure keyboard-selection model.
- `Sources/CicadaApp/Views/Inbox/QuestionView.swift` — the one question renderer.
- `Tests/CicadaAppTests/InboxQuestionTests.swift` — decoding + selection + mutation tests.

**Modified Swift files**
- `Models/InboxItem.swift`, `ViewModels/InboxViewModel.swift`, `Sync/Mutations.swift`, `Sync/SyncAPI.swift`, `Services/APIClient.swift`, `Views/Inbox/InboxCardView.swift`, `Views/Inbox/InboxListView.swift`, `Views/Graph/EntityDetailCard.swift`, `Tests/CicadaAppTests/StoreTests.swift` (FakeSyncAPI signature).

---

### Task 1: Question-object schema, `humanize_age`, and the legacy-options upgrade

**Files:**
- Create: `api/services/inbox_questions.py`
- Modify: `api/models/schemas.py:561-589` (`InboxItem`, `InboxResolveRequest`)
- Modify: `api/services/inbox_service.py:44-66` (`_item_from_file`)
- Test: `api/tests/test_inbox_questions.py`

**Interfaces:**
- Consumes: `api.services.markdown_parser.parse/write`, `api.models.schemas.CamelModel`.
- Produces:
  - `inbox_questions.humanize_age(observed: str | None, today: str) -> str`
  - `inbox_questions.age_days(observed: str | None, today: str) -> int | None`
  - `inbox_questions.normalize_options(raw: object) -> list[dict]` — upgrades a flat `[str]` to `[{"key": "0", "label": s}]`, passes dict lists through, returns `[]` for `None`.
  - `schemas.InboxOption(key, label, description, claim_id, observed_at, last_referenced, age_days)`
  - `schemas.InboxItem.question/options/allow_other/allow_defer/predicate/hint/remind_after/updated_date`
  - `schemas.InboxResolveRequest.option_key: str | None`, `.remind_days: int | None`

- [ ] **Step 1: Write the failing test for `humanize_age` and `normalize_options`**

Create `api/tests/test_inbox_questions.py`:

```python
"""G60 — question-object helpers: age phrasing + legacy flat-options upgrade."""

from __future__ import annotations

from api.services import inbox_questions


def test_humanize_age_phrases():
    today = "2026-08-30"
    assert inbox_questions.humanize_age("2026-08-30", today) == "today"
    assert inbox_questions.humanize_age("2026-08-29", today) == "yesterday"
    assert inbox_questions.humanize_age("2026-08-27", today) == "3 days ago"
    assert inbox_questions.humanize_age("2026-08-09", today) == "3 weeks ago"
    assert inbox_questions.humanize_age("2026-02-18", today) == "6 months ago"
    assert inbox_questions.humanize_age("2025-07-01", today) == "a year ago"
    assert inbox_questions.humanize_age("2023-07-01", today) == "3 years ago"
    assert inbox_questions.humanize_age(None, today) == "unknown"


def test_age_days_handles_missing_and_iso_timestamps():
    assert inbox_questions.age_days("2026-08-27", "2026-08-30") == 3
    assert inbox_questions.age_days("2026-08-27T09:00:00Z", "2026-08-30") == 3
    assert inbox_questions.age_days(None, "2026-08-30") is None
    assert inbox_questions.age_days("not-a-date", "2026-08-30") is None


def test_normalize_options_upgrades_legacy_flat_list():
    upgraded = inbox_questions.normalize_options(["MongoDB", "Supahost"])
    assert upgraded == [
        {"key": "0", "label": "MongoDB"},
        {"key": "1", "label": "Supahost"},
    ]


def test_normalize_options_passes_object_form_through_and_fills_keys():
    raw = [{"label": "MongoDB", "claim_id": "clm_1"}, {"key": "b", "label": "Supahost"}]
    out = inbox_questions.normalize_options(raw)
    assert out[0]["key"] == "0"
    assert out[0]["claim_id"] == "clm_1"
    assert out[1]["key"] == "b"


def test_normalize_options_empty_inputs():
    assert inbox_questions.normalize_options(None) == []
    assert inbox_questions.normalize_options([]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_inbox_questions.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.services.inbox_questions'`

- [ ] **Step 3: Write `api/services/inbox_questions.py` (helpers only)**

```python
"""G60 — the inbox *question object*: age phrasing, option normalization,
defer visibility, and the Stage-3 re-scoring sweep.

Every inbox item of kind ``conflict`` / ``clarification`` / ``merge_suggestion``
carries a question (one sentence) and a list of option objects modelled on
Claude Code's ``AskUserQuestion``. This module owns the pure helpers that build
and read that shape; ``inbox_generator`` writes it and ``inbox_service`` reads it.

``age_days`` is DERIVED at read time (never persisted) so a stored item never
goes stale-by-arithmetic.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

_UNKNOWN_AGE = "unknown"


def _as_date(value: str | None) -> date | None:
    """Parse a plain ``YYYY-MM-DD`` or a full ISO timestamp into a date."""
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if "T" in text:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def age_days(observed: str | None, today: str) -> int | None:
    """Whole days between ``observed`` and ``today``; ``None`` if unparseable."""
    a = _as_date(observed)
    b = _as_date(today)
    if a is None or b is None:
        return None
    return max(0, (b - a).days)


def humanize_age(observed: str | None, today: str) -> str:
    """A short human age phrase: today / yesterday / N days|weeks|months|years ago."""
    days = age_days(observed, today)
    if days is None:
        return _UNKNOWN_AGE
    if days == 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 14:
        return f"{days} days ago"
    if days < 60:
        weeks = round(days / 7)
        return "a week ago" if weeks == 1 else f"{weeks} weeks ago"
    if days < 365:
        months = round(days / 30)
        return "a month ago" if months == 1 else f"{months} months ago"
    years = round(days / 365)
    return "a year ago" if years == 1 else f"{years} years ago"


def normalize_options(raw: object) -> list[dict]:
    """Coerce whatever is in ``options:`` into the object form.

    - ``None`` / ``[]``            -> ``[]``
    - legacy ``["A", "B"]``        -> ``[{"key": "0", "label": "A"}, ...]``
    - object form                  -> passed through, with a positional ``key``
                                      filled in when one is missing.
    """
    if not raw or not isinstance(raw, list):
        return []
    out: list[dict] = []
    for i, item in enumerate(raw):
        if isinstance(item, dict):
            opt = dict(item)
            if not str(opt.get("key", "") or "").strip():
                opt["key"] = str(i)
            opt["label"] = str(opt.get("label", "") or "")
            out.append(opt)
        else:
            out.append({"key": str(i), "label": str(item)})
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `api/.venv/bin/python -m pytest api/tests/test_inbox_questions.py -q`
Expected: PASS (5 tests)

- [ ] **Step 5: Write the failing test for the wire schema + `_item_from_file`**

Append to `api/tests/test_inbox_questions.py`:

```python
from pathlib import Path

from api.models.schemas import InboxResolveRequest
from api.services import inbox_service, markdown_parser


def _write_item(memory: Path, item_id: str, fm: dict, body: str = "context") -> Path:
    inbox = memory / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / f"{item_id}.md"
    markdown_parser.write(path, fm, body)
    return path


def test_item_from_file_upgrades_legacy_flat_options(tmp_path):
    path = _write_item(
        tmp_path,
        "inbox-001",
        {
            "kind": "conflict",
            "required_input": "choice",
            "status": "pending",
            "entity_id": "rodrigo",
            "entity_name": "Rodrigo",
            "title": "Conflicting beliefs about Rodrigo",
            "created_date": "2026-06-18",
            "options": ["mongodb", "supahost", "Both are true (different contexts)"],
        },
    )
    item = inbox_service._item_from_file(path)
    assert [o.key for o in item.options] == ["0", "1", "2"]
    assert item.options[0].label == "mongodb"
    assert item.question is None
    assert item.allow_other is False


def test_item_from_file_reads_question_object_and_derives_age(tmp_path):
    path = _write_item(
        tmp_path,
        "inbox-002",
        {
            "kind": "conflict",
            "required_input": "choice",
            "status": "pending",
            "entity_id": "rodrigo",
            "entity_name": "Rodrigo",
            "title": "Where does Rodrigo work now?",
            "created_date": "2026-06-18",
            "predicate": "works-at",
            "question": "Where does Rodrigo work now?",
            "allow_other": True,
            "allow_defer": True,
            "hint": "You said https://example.com/me is where to check this",
            "options": [
                {
                    "key": "a",
                    "label": "MongoDB",
                    "description": "Last mentioned 2026-02-18 · 6 months ago",
                    "claim_id": "clm_a",
                    "observed_at": "2026-02-18",
                    "last_referenced": "2026-02-18",
                }
            ],
        },
    )
    item = inbox_service._item_from_file(path, today="2026-08-30")
    assert item.question == "Where does Rodrigo work now?"
    assert item.predicate == "works-at"
    assert item.allow_other is True and item.allow_defer is True
    assert item.hint.startswith("You said")
    assert item.options[0].claim_id == "clm_a"
    assert item.options[0].age_days == 193


def test_resolve_request_accepts_option_key_and_remind_days():
    req = InboxResolveRequest(action="resolve", optionKey="b", remindDays=14)
    assert req.option_key == "b"
    assert req.remind_days == 14
    assert InboxResolveRequest(action="skip").option_key is None
```

- [ ] **Step 6: Run test to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_inbox_questions.py -q`
Expected: FAIL — `TypeError: _item_from_file() got an unexpected keyword argument 'today'` / `InboxItem` has no `question`.

- [ ] **Step 7: Add the schema models**

In `api/models/schemas.py`, insert `InboxOption` immediately **before** `class InboxItem` (currently line 561) and extend the two models:

```python
class InboxOption(CamelModel):
    """One answerable option on an inbox question (AskUserQuestion shape).

    ``age_days`` is derived at read time from ``last_referenced`` (falling back
    to ``observed_at``) — it is never persisted into the item file.
    """

    key: str
    label: str
    description: Optional[str] = None
    claim_id: Optional[str] = None
    observed_at: Optional[str] = None
    last_referenced: Optional[str] = None
    age_days: Optional[int] = None


class InboxItem(CamelModel):
    id: str
    kind: InboxKind
    required_input: RequiredInput
    status: str = "pending"
    priority: float = 0.0
    entity_id: str = ""
    entity_name: str = ""
    title: str
    body: str
    options: list[InboxOption] = []
    created_date: str = ""
    # G60 question object
    question: Optional[str] = None
    allow_other: bool = False
    allow_defer: bool = False
    predicate: Optional[str] = None
    hint: Optional[str] = None
    remind_after: Optional[str] = None
    updated_date: Optional[str] = None
    # clarification/merge extras (only populated for those kinds)
    uncertainty_type: Optional[str] = None
    suggested_classification: Optional[str] = None
    suggested_confidence: Optional[float] = None
    merge_target_hint: Optional[str] = None


class InboxResolveRequest(CamelModel):
    action: str
    answer: Optional[str] = None
    # G60: the stable key of the chosen option ("a", "b", "both", "neither").
    # ``answer`` stays the free-text channel; both may be sent together when the
    # user picks "neither" AND types what is actually true.
    option_key: Optional[str] = None
    # G60 defer: how far out to push `remind_after` (default: settings).
    remind_days: Optional[int] = None
    merge_target: Optional[str] = None
    # #1 merge direction: the id/name the user wants to KEEP as the canonical
    # survivor. When absent (or equal to ``merge_target``), the legacy behavior
    # holds — the clarified mention is absorbed INTO the existing ``merge_target``.
    # When it names the cleaner mention instead, the surviving file is renamed to
    # the survivor's slug so a merge can go either direction.
    merge_survivor: Optional[str] = None
```

Note: `options` changed from `Optional[list[str]]` to `list[InboxOption]` (default `[]`). `api/routers/nudges.py` and `api/routers/clarifications.py` project this into their legacy shapes — Step 9 fixes them.

- [ ] **Step 8: Rewrite `_item_from_file` to build the question object**

Replace `api/services/inbox_service.py:44-66` with:

```python
def _item_from_file(filepath: Path, *, today: str | None = None) -> InboxItem:
    parsed = markdown_parser.parse(filepath)
    fm = parsed.frontmatter
    kind = str(fm.get("kind", "decay"))
    required_input = str(fm.get("required_input", "") or _required_input_for(kind))
    now = today or str(date.today())

    options: list[InboxOption] = []
    for raw in inbox_questions.normalize_options(fm.get("options")):
        observed = _opt_str(raw.get("observed_at"))
        last_ref = _opt_str(raw.get("last_referenced")) or observed
        options.append(
            InboxOption(
                key=str(raw.get("key", "")),
                label=str(raw.get("label", "")),
                description=_opt_str(raw.get("description")),
                claim_id=_opt_str(raw.get("claim_id")),
                observed_at=observed,
                last_referenced=last_ref,
                age_days=inbox_questions.age_days(last_ref, now),
            )
        )

    return InboxItem(
        id=filepath.stem,
        kind=kind,
        required_input=required_input,
        status=str(fm.get("status", "pending") or "pending"),
        priority=float(fm.get("priority", 0.0) or 0.0),
        entity_id=str(fm.get("entity_id", "") or ""),
        entity_name=str(fm.get("entity_name", "") or ""),
        title=str(fm.get("title", "") or fm.get("entity_name", "") or ""),
        body=parsed.body,
        options=options,
        created_date=str(fm.get("created_date", "") or ""),
        question=_opt_str(fm.get("question")),
        allow_other=bool(fm.get("allow_other", False)),
        allow_defer=bool(fm.get("allow_defer", False)),
        predicate=_opt_str(fm.get("predicate")),
        hint=_opt_str(fm.get("hint")),
        remind_after=_opt_str(fm.get("remind_after")),
        updated_date=_opt_str(fm.get("updated_date")),
        uncertainty_type=fm.get("uncertainty_type"),
        suggested_classification=fm.get("suggested_classification"),
        suggested_confidence=fm.get("suggested_confidence"),
        merge_target_hint=fm.get("merge_target_hint"),
    )


def _opt_str(value: object) -> str | None:
    """Normalize an optional YAML scalar to ``str`` (YAML may parse dates)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None
```

Update the imports at the top of `api/services/inbox_service.py`:

```python
from api.models.schemas import InboxItem, InboxOption, InboxResolveRequest
from api.services import inbox_questions, markdown_parser
```

- [ ] **Step 9: Keep the deprecated shims compiling**

`api/routers/nudges.py` and `api/routers/clarifications.py` read `item.options`. Grep them:

Run: `grep -n "options" api/routers/nudges.py api/routers/clarifications.py`

Wherever a shim passes `item.options` into a legacy `list[str]` field, replace it with `[o.label for o in item.options]`. If a shim writes `options=item.options or None`, use `options=[o.label for o in item.options] or None`.

- [ ] **Step 10: Run the tests**

Run: `api/.venv/bin/python -m pytest api/tests/test_inbox_questions.py api/tests/test_claim_inbox.py api/tests/test_merge_direction_and_location.py -q`
Expected: PASS

Then the whole suite: `api/.venv/bin/python -m pytest api/tests -q`
Expected: PASS (fix any shim/test that still assumes `options: list[str]` by mapping to `.label`).

- [ ] **Step 11: Commit**

```bash
git add api/services/inbox_questions.py api/models/schemas.py api/services/inbox_service.py api/routers/nudges.py api/routers/clarifications.py api/tests/test_inbox_questions.py
git commit -m "$(cat <<'EOF'
feat(inbox): question-object schema + humanize_age + legacy options upgrade (G60)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

### Task 2: `find_open` dedup + merge-on-collision, and the generated conflict question

**Files:**
- Modify: `api/services/predicates.py` (append `PREDICATE_QUESTIONS` + `predicate_question`)
- Modify: `api/services/claim_reconciler.py:221-239` (`_conflict_nudge`), `:362-376` (call site)
- Modify: `api/services/inbox_generator.py` (add `dedup_key`, `find_open`, `merge_options_into`; rewrite the `conflict_nudge` branches)
- Modify: `api/services/clarification_manager.py:45-66` (`create`'s duplicate guard uses `find_open` and bumps `updated_date`)
- Test: `api/tests/test_inbox_dedup.py`

**Interfaces:**
- Consumes: `inbox_questions.humanize_age/normalize_options` (Task 1).
- Produces:
  - `predicates.predicate_question(predicate: str, name: str) -> str`
  - `inbox_generator.dedup_key(kind: str, fm: dict) -> tuple[str, str]`
  - `inbox_generator.find_open(memory_path: Path, kind: str, entity_id: str, predicate: str | None = None) -> Path | None`
  - `inbox_generator.merge_options_into(path: Path, new_options: list[dict], today: str) -> bool`
  - `claim_reconciler._conflict_nudge(existing, new, today)` now returns `question`, `predicate`, `allow_other`, `allow_defer` and an **object-form** `options` list.

- [ ] **Step 1: Write the failing test for the predicate question table**

Create `api/tests/test_inbox_dedup.py`:

```python
"""G60 — dedup key, find_open, merge-on-collision, and question generation."""

from __future__ import annotations

from pathlib import Path

from api.services import inbox_generator, markdown_parser, predicates
from api.services.claim_reconciler import _conflict_nudge
from api.services.claims import Claim


def test_predicate_question_uses_the_table_then_falls_back():
    assert predicates.predicate_question("works-at", "Rodrigo") == "Where does Rodrigo work now?"
    assert predicates.predicate_question("located-in", "Cicada") == "Where is Cicada located now?"
    assert predicates.predicate_question("uses", "Cicada") == "What does Cicada use now?"
    assert (
        predicates.predicate_question("wears-hat-of", "Rodrigo")
        == "Which is true about Rodrigo (wears-hat-of)?"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_inbox_dedup.py -q`
Expected: FAIL with `AttributeError: module 'api.services.predicates' has no attribute 'predicate_question'`

- [ ] **Step 3: Add the question table to `predicates.py`**

Append to `api/services/predicates.py`:

```python
# --------------------------------------------------------------------------- #
# G60 — predicate -> user-facing question template
# --------------------------------------------------------------------------- #

# Hand-written question phrasings for the canonical predicates that actually
# produce single-valued conflicts (see ``single_valued`` in predicates-seed.yaml)
# plus a few high-frequency multi-valued ones. Keyed by canonical predicate;
# ``{name}`` is the entity's display name. Anything absent falls back to the
# generic template — under-specifying is safe, a wrong verb is not.
PREDICATE_QUESTIONS: dict[str, str] = {
    "works-at": "Where does {name} work now?",
    "works-on": "What is {name} working on now?",
    "works-with": "Who does {name} work with now?",
    "located-in": "Where is {name} located now?",
    "takes-place-in": "Where does {name} take place?",
    "uses": "What does {name} use now?",
    "runs-on": "What does {name} run on now?",
    "depends-on": "What does {name} depend on now?",
    "part-of": "What is {name} part of now?",
    "is-a": "What kind of thing is {name}?",
    "implements": "What does {name} implement now?",
    "hosts": "What does {name} host now?",
    "provides": "What does {name} provide now?",
    "prefers": "What does {name} prefer now?",
    "description": "What is currently true about {name}?",
}

_GENERIC_QUESTION = "Which is true about {name} ({predicate})?"


def predicate_question(predicate: str, name: str) -> str:
    """One-sentence question for a ``(name, predicate)`` conflict.

    Template-only by design (§3 of the spec: no LLM call on the claim path).
    An unknown predicate gets the generic phrasing rather than a guessed verb.
    """
    key = (predicate or "").strip().lower()
    template = PREDICATE_QUESTIONS.get(key)
    if template:
        return template.format(name=name)
    return _GENERIC_QUESTION.format(name=name, predicate=key or "unknown")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `api/.venv/bin/python -m pytest api/tests/test_inbox_dedup.py -q`
Expected: PASS

- [ ] **Step 5: Write the failing test for `_conflict_nudge`'s question object**

Append to `api/tests/test_inbox_dedup.py`:

```python
def _claim(cid: str, obj: str, valid_from: str, episode: str = "") -> Claim:
    return Claim(
        id=cid,
        text=f"Rodrigo works at {obj}",
        subject="rodrigo-sagastegui",
        predicate="works-at",
        object=obj,
        valid_from=valid_from,
        recorded_at=valid_from,
        source_episodes=[episode] if episode else [],
    )


def test_conflict_nudge_emits_a_question_object_with_age_descriptions():
    old = _claim("clm_a", "mongodb", "2026-02-18", "ep_2026-02-18_004")
    new = _claim("clm_b", "supahost", "2026-02-18")

    nudge = _conflict_nudge(old, new, today="2026-08-30")

    assert nudge["action"] == "conflict_nudge"
    assert nudge["predicate"] == "works-at"
    assert nudge["question"] == "Where does Rodrigo Sagastegui work now?"
    assert nudge["allow_other"] is True
    assert nudge["allow_defer"] is True

    opts = nudge["options"]
    assert [o["key"] for o in opts] == ["a", "b", "both"]
    assert opts[0]["label"] == "mongodb"
    assert opts[0]["claim_id"] == "clm_a"
    assert opts[0]["observed_at"] == "2026-02-18"
    assert opts[0]["last_referenced"] == "2026-02-18"
    # Description leads with the age phrase so staleness is visible first.
    assert "6 months ago" in opts[0]["description"]
    assert "ep_2026-02-18_004" in opts[0]["description"]
    assert opts[2]["claim_id"] is None
```

- [ ] **Step 6: Run test to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_inbox_dedup.py -q`
Expected: FAIL — `_conflict_nudge() got an unexpected keyword argument 'today'`

- [ ] **Step 7: Rewrite `_conflict_nudge`**

Replace `api/services/claim_reconciler.py:221-239` with:

```python
def _claim_option(key: str, claim: Claim, today: str) -> dict:
    """One question option backed by a claim, description led by its age."""
    observed = claim.valid_from or claim.recorded_at
    parts = [f"Last mentioned {observed or 'unknown'}", inbox_questions.humanize_age(observed, today)]
    episode = (claim.source_episodes or [""])[0]
    if episode:
        parts.append(f"extracted from {episode}")
    return {
        "key": key,
        "label": claim.object,
        "description": " · ".join(parts),
        "claim_id": claim.id,
        "observed_at": observed,
        "last_referenced": observed,
    }


def _conflict_nudge(existing: Claim, new: Claim, today: str) -> dict:
    """A conflict nudge carrying the G60 question object.

    ``today`` is the reconciliation reference date, so the age phrases in each
    option's description are computed once at generation time (``age_days`` is
    re-derived at read time by ``inbox_service``).
    """
    name = _entity_name(new)
    return {
        "id": new.subject,
        "action": "conflict_nudge",
        "entity": {"name": name},
        "predicate": new.predicate,
        "question": predicates.predicate_question(new.predicate, name),
        "allow_other": True,
        "allow_defer": True,
        "conflict_context": (
            f"Conflicting beliefs about {name} "
            f"({new.predicate}): '{existing.object}' vs '{new.object}'."
        ),
        "options": [
            _claim_option("a", existing, today),
            _claim_option("b", new, today),
            {
                "key": "both",
                "label": "Both are true (different contexts)",
                "description": "Keep both claims, each tagged with its context",
                "claim_id": None,
            },
        ],
        "source_episode": (new.source_episodes or [""])[0],
        "trigger": "sleep/conflict_resolution",
        "claim_id": new.id,
        "existing_claim_id": existing.id,
    }
```

Add the import at the top of `api/services/claim_reconciler.py` (next to `from api.services import predicates`):

```python
from api.services import inbox_questions, predicates
```

Update the call site at `api/services/claim_reconciler.py:371`:

```python
        elif action == "CONFLICT_NUDGE":
            nudges.append(_conflict_nudge(existing, new, today))
```

- [ ] **Step 8: Run test to verify it passes**

Run: `api/.venv/bin/python -m pytest api/tests/test_inbox_dedup.py api/tests/test_claim_reconciler.py -q`
Expected: PASS

- [ ] **Step 9: Write the failing test for `find_open` + merge-on-collision**

Append to `api/tests/test_inbox_dedup.py`:

```python
def _write_conflict(memory: Path, item_id: str, entity_id: str, predicate: str,
                    options: list[dict], status: str = "pending",
                    created: str = "2026-06-18") -> Path:
    inbox = memory / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / f"{item_id}.md"
    markdown_parser.write(
        path,
        {
            "kind": "conflict",
            "required_input": "choice",
            "status": status,
            "priority": 0.8,
            "entity_id": entity_id,
            "entity_name": entity_id.replace("-", " ").title(),
            "title": "Conflicting beliefs",
            "created_date": created,
            "predicate": predicate,
            "question": "Where does Rodrigo work now?",
            "allow_other": True,
            "allow_defer": True,
            "options": options,
        },
        "context",
    )
    return path


def test_dedup_key_per_kind():
    assert inbox_generator.dedup_key(
        "conflict", {"entity_id": "rodrigo", "predicate": "works-at"}
    ) == ("rodrigo", "works-at")
    # entity-path conflicts have no predicate -> "description"
    assert inbox_generator.dedup_key("conflict", {"entity_id": "rodrigo"}) == (
        "rodrigo",
        "description",
    )
    assert inbox_generator.dedup_key(
        "clarification", {"entity_id": "franco", "uncertainty_type": "who is this"}
    ) == ("franco", "who is this")
    # merge_suggestion: the sorted pair, so direction never matters
    assert inbox_generator.dedup_key(
        "merge_suggestion", {"entity_id": "zeta", "merge_target_hint": "alpha"}
    ) == ("alpha", "zeta")


def test_find_open_matches_only_pending_same_key(tmp_path):
    memory = tmp_path / "memory"
    _write_conflict(memory, "inbox-001", "rodrigo", "works-at", [{"key": "a", "label": "mongodb"}])
    _write_conflict(memory, "inbox-002", "rodrigo", "uses", [{"key": "a", "label": "vim"}])
    _write_conflict(
        memory, "inbox-003", "rodrigo", "lives-in", [{"key": "a", "label": "madrid"}],
        status="resolved",
    )

    assert inbox_generator.find_open(memory, "conflict", "rodrigo", "works-at").stem == "inbox-001"
    assert inbox_generator.find_open(memory, "conflict", "rodrigo", "uses").stem == "inbox-002"
    # resolved items are invisible to dedup
    assert inbox_generator.find_open(memory, "conflict", "rodrigo", "lives-in") is None
    assert inbox_generator.find_open(memory, "conflict", "someone-else", "works-at") is None


def test_merge_options_into_appends_new_value_and_bumps_existing(tmp_path):
    memory = tmp_path / "memory"
    path = _write_conflict(
        memory, "inbox-001", "rodrigo", "works-at",
        [
            {"key": "a", "label": "mongodb", "claim_id": "clm_a",
             "observed_at": "2026-02-18", "last_referenced": "2026-02-18"},
            {"key": "both", "label": "Both are true (different contexts)"},
        ],
    )

    changed = inbox_generator.merge_options_into(
        path,
        [
            # already present -> bumps last_referenced only
            {"key": "a", "label": "mongodb", "claim_id": "clm_a",
             "observed_at": "2026-08-01", "last_referenced": "2026-08-01"},
            # new value -> appended with a fresh key, before the synthetic rows
            {"key": "b", "label": "supahost", "claim_id": "clm_b",
             "observed_at": "2026-08-01", "last_referenced": "2026-08-01",
             "description": "Last mentioned 2026-08-01 · 4 weeks ago"},
        ],
        today="2026-08-30",
    )

    assert changed is True
    fm = markdown_parser.parse(path).frontmatter
    labels = [o["label"] for o in fm["options"]]
    assert labels == ["mongodb", "supahost", "Both are true (different contexts)"]
    assert fm["options"][0]["last_referenced"] == "2026-08-01"
    assert fm["options"][1]["claim_id"] == "clm_b"
    # keys stay unique
    assert len({o["key"] for o in fm["options"]}) == 3
    # created_date is preserved; updated_date is new
    assert fm["created_date"] == "2026-06-18"
    assert fm["updated_date"] == "2026-08-30"


def test_write_claim_nudges_merges_instead_of_duplicating(tmp_path):
    memory = tmp_path / "memory"
    (memory / "inbox").mkdir(parents=True)
    (memory / "entities").mkdir(parents=True)

    def nudge(obj: str, claim_id: str, observed: str) -> dict:
        return {
            "id": "rodrigo",
            "action": "conflict_nudge",
            "entity": {"name": "Rodrigo"},
            "predicate": "works-at",
            "question": "Where does Rodrigo work now?",
            "allow_other": True,
            "allow_defer": True,
            "conflict_context": "conflict",
            "options": [
                {"key": "a", "label": "mongodb", "claim_id": "clm_a",
                 "observed_at": "2026-02-18", "last_referenced": "2026-02-18"},
                {"key": "b", "label": obj, "claim_id": claim_id,
                 "observed_at": observed, "last_referenced": observed},
                {"key": "both", "label": "Both are true (different contexts)"},
            ],
            "claim_id": claim_id,
            "existing_claim_id": "clm_a",
        }

    inbox_generator.write_claim_nudges([nudge("supahost", "clm_b", "2026-02-18")], memory)
    inbox_generator.write_claim_nudges([nudge("acme", "clm_c", "2026-08-20")], memory)

    files = sorted((memory / "inbox").glob("inbox-*.md"))
    assert len(files) == 1, "a second conflict on the same key must MERGE, not duplicate"
    fm = markdown_parser.parse(files[0]).frontmatter
    assert [o["label"] for o in fm["options"]] == [
        "mongodb", "supahost", "acme", "Both are true (different contexts)",
    ]
```

- [ ] **Step 10: Run test to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_inbox_dedup.py -q`
Expected: FAIL — `module 'api.services.inbox_generator' has no attribute 'dedup_key'`

- [ ] **Step 11: Add `dedup_key` / `find_open` / `merge_options_into` to `inbox_generator.py`**

Add near the top of `api/services/inbox_generator.py` (after the imports), and add `from api.services import inbox_questions` to the import block:

```python
# Options with no claim behind them (the synthetic "both"/"neither" rows) always
# sort last, so a merged-in competing value lands among the real answers.
_SYNTHETIC_KEYS = {"both", "neither"}


def dedup_key(kind: str, fm: dict) -> tuple[str, str]:
    """The open-item identity for a kind (§2.2).

    - ``conflict``          -> ``(entity_id, predicate)``; entity-path conflicts
      carry no predicate and key on the literal ``"description"``.
    - ``clarification``     -> ``(entity_id, uncertainty_type)``
    - ``merge_suggestion``  -> the **sorted** pair of entity ids, so the same
      duplicate pair keys identically regardless of which side was seen first.
    - anything else         -> ``(entity_id, "")``
    """
    entity_id = str(fm.get("entity_id", "") or "")
    if kind == "conflict":
        return (entity_id, str(fm.get("predicate", "") or "description"))
    if kind == "clarification":
        return (entity_id, str(fm.get("uncertainty_type", "") or ""))
    if kind == "merge_suggestion":
        other = str(fm.get("merge_target_hint", "") or "")
        pair = sorted([entity_id, other])
        return (pair[0], pair[1])
    return (entity_id, "")


def find_open(
    memory_path: Path, kind: str, entity_id: str, predicate: str | None = None
) -> Path | None:
    """Return the open (``status: pending``) item of ``kind`` on the same key.

    ``predicate`` carries the second key component for every kind: the
    predicate for conflicts, the uncertainty type for clarifications, the OTHER
    entity id for merge suggestions. Returns the OLDEST match (lowest inbox
    number) so a collision always merges into the original question.
    """
    inbox_dir = memory_path / "inbox"
    if not inbox_dir.exists():
        return None
    target = dedup_key(
        kind,
        {
            "entity_id": entity_id,
            "predicate": predicate,
            "uncertainty_type": predicate,
            "merge_target_hint": predicate,
        },
    )
    for filepath in sorted(inbox_dir.glob("inbox-*.md")):
        try:
            fm = markdown_parser.parse(filepath).frontmatter
        except Exception:
            continue
        if str(fm.get("kind", "")) != kind:
            continue
        if str(fm.get("status", "pending") or "pending") != "pending":
            continue
        if dedup_key(kind, fm) == target:
            return filepath
    return None


def merge_options_into(path: Path, new_options: list[dict], today: str) -> bool:
    """Merge competing values into an already-open question (§2.2).

    A value already present (matched case-insensitively on ``label``) has its
    ``last_referenced`` bumped and its ``claim_id`` refreshed; a value not
    present is appended with a fresh unique key, ahead of the synthetic
    ``both``/``neither`` rows. ``question`` and ``created_date`` are preserved;
    ``updated_date`` is set to ``today``. Returns whether anything changed.
    """
    parsed = markdown_parser.parse(path)
    fm = parsed.frontmatter
    existing = inbox_questions.normalize_options(fm.get("options"))
    by_label = {str(o.get("label", "")).strip().lower(): o for o in existing}
    used_keys = {str(o.get("key", "")) for o in existing}
    changed = False

    for incoming in inbox_questions.normalize_options(new_options):
        label = str(incoming.get("label", "")).strip()
        if not label:
            continue
        current = by_label.get(label.lower())
        if current is not None:
            bumped = incoming.get("last_referenced") or incoming.get("observed_at")
            if bumped and str(bumped) > str(current.get("last_referenced") or ""):
                current["last_referenced"] = str(bumped)
                changed = True
            if incoming.get("claim_id") and not current.get("claim_id"):
                current["claim_id"] = incoming["claim_id"]
                changed = True
            continue
        option = dict(incoming)
        key = str(option.get("key", "")) or "x"
        while key in used_keys:
            key += "x"
        option["key"] = key
        used_keys.add(key)
        existing.append(option)
        by_label[label.lower()] = option
        changed = True

    if not changed:
        return False

    real = [o for o in existing if str(o.get("key")) not in _SYNTHETIC_KEYS]
    synthetic = [o for o in existing if str(o.get("key")) in _SYNTHETIC_KEYS]
    fm["options"] = real + synthetic
    fm["updated_date"] = today
    markdown_parser.write(path, fm, parsed.body)
    return True
```

- [ ] **Step 12: Route the two conflict writers through `find_open`**

In `write_claim_nudges`, replace the plain write for the `conflict_nudge` branch. After `entity_name` is resolved and before `item_id` is allocated, insert:

```python
        predicate = str(nudge.get("predicate", "") or "description")
        if action == "conflict_nudge":
            open_path = find_open(memory_path, "conflict", entity_id, predicate)
            if open_path is not None:
                merge_options_into(open_path, nudge.get("options") or [], str(date.today()))
                continue
```

and extend the frontmatter dict written in the same function with the question-object keys:

```python
        frontmatter = {
            "kind": kind,
            "required_input": required,
            "status": "pending",
            "priority": priority,
            "entity_id": entity_id,
            "entity_name": entity_name,
            "title": nudge.get("question") or title,
            "created_date": str(date.today()),
            "options": nudge.get("options"),
            # G60 question object (present on conflicts; absent elsewhere).
            "predicate": nudge.get("predicate"),
            "question": nudge.get("question"),
            "allow_other": bool(nudge.get("allow_other", False)),
            "allow_defer": bool(nudge.get("allow_defer", False)),
            # claim provenance so the companion app can resolve a specific belief.
            "claim_id": nudge.get("claim_id"),
            "existing_claim_id": nudge.get("existing_claim_id"),
            "trigger": nudge.get("trigger", "sleep/conflict_resolution"),
        }
```

Do the same in `generate`'s `elif action == "conflict_nudge":` branch (the entity path), which has no predicate:

```python
        elif action == "conflict_nudge":
            entity_id = change["id"]
            entity_name = change.get("entity", {}).get("name", entity_id.replace("-", " ").title())
            open_path = find_open(memory_path, "conflict", entity_id, "description")
            if open_path is not None:
                merge_options_into(open_path, change.get("options") or [], str(date.today()))
                continue
            item_id = f"inbox-{next_num:03d}"
            next_num += 1
            frontmatter = {
                "kind": "conflict",
                "required_input": "choice",
                "status": "pending",
                "priority": 0.8,
                "entity_id": entity_id,
                "entity_name": entity_name,
                "title": change.get("question") or f"Conflicting information about {entity_name}",
                "created_date": str(date.today()),
                "options": change.get("options", []),
                "predicate": "description",
                "question": change.get("question"),
                "allow_other": True,
                "allow_defer": True,
            }
            body = change.get("conflict_context", f"New information conflicts with existing data for {entity_name}.")
            markdown_parser.write(inbox_dir / f"{item_id}.md", frontmatter, body)
```

- [ ] **Step 13: Route clarification / merge_suggestion dedup through `find_open` too**

`api/services/clarification_manager.py:65-66` already refuses a duplicate via
`_existing_for(entity_name)` (fuzzy on the mention) but silently drops it. §2.2 says the
collision must **bump `updated_date`** on the open item so its freshness is honest, and the
key must be `(entity_id, uncertainty_type)` — a *different* uncertainty about the same
mention is a different question.

First, the failing test — append to `api/tests/test_inbox_dedup.py`:

```python
def test_clarification_collision_bumps_updated_date_instead_of_duplicating(tmp_path):
    from api.services.clarification_manager import ClarificationManager

    memory = tmp_path / "memory"
    (memory / "inbox").mkdir(parents=True)
    manager = ClarificationManager(memory)

    first = manager.create(
        entity_name="Franco", source_episode="ep_1",
        uncertainty_type="unclear who this is",
        suggested_classification="person", suggested_confidence=0.5,
        source_context="Franco came up.",
    )
    assert first == "inbox-001"

    again = manager.create(
        entity_name="Franco", source_episode="ep_2",
        uncertainty_type="unclear who this is",
        suggested_classification="person", suggested_confidence=0.5,
        source_context="Franco came up again.",
    )
    assert again is None
    assert len(list((memory / "inbox").glob("inbox-*.md"))) == 1
    fm = markdown_parser.parse(memory / "inbox" / "inbox-001.md").frontmatter
    assert fm["updated_date"] == str(__import__("datetime").date.today())


def test_a_different_uncertainty_about_the_same_mention_is_a_new_question(tmp_path):
    from api.services.clarification_manager import ClarificationManager

    memory = tmp_path / "memory"
    (memory / "inbox").mkdir(parents=True)
    manager = ClarificationManager(memory)

    manager.create(
        entity_name="Franco", source_episode="ep_1",
        uncertainty_type="unclear who this is",
        suggested_classification="person", suggested_confidence=0.5,
        source_context="ctx",
    )
    second = manager.create(
        entity_name="Franco", source_episode="ep_2",
        uncertainty_type="Possible duplicate of Franco Rossi",
        suggested_classification="person", suggested_confidence=0.5,
        source_context="ctx",
    )
    assert second == "inbox-002"
    assert len(list((memory / "inbox").glob("inbox-*.md"))) == 2
```

Run: `api/.venv/bin/python -m pytest api/tests/test_inbox_dedup.py -q`
Expected: FAIL — `KeyError: 'updated_date'` on the first, and the second returns `None`.

Then replace the duplicate guard at the top of `ClarificationManager.create`
(`if self._existing_for(entity_name): return None`) with:

```python
        from api.services.inbox_generator import find_open

        is_duplicate = (uncertainty_type or "").strip().lower().startswith(
            _DUPLICATE_PREFIX
        )
        kind = "merge_suggestion" if is_duplicate else "clarification"
        # §2.2 dedup key: (entity_id, uncertainty_type) for a clarification,
        # the sorted entity pair for a merge suggestion. A collision is a
        # RE-ASK of the same question — bump `updated_date` and write nothing.
        second = (
            self._merge_target_hint(uncertainty_type) or ""
            if is_duplicate
            else (uncertainty_type or "")
        )
        open_path = find_open(self.memory_path, kind, sanitize_id(entity_name), second)
        if open_path is not None:
            parsed = markdown_parser.parse(open_path)
            parsed.frontmatter["updated_date"] = str(date.today())
            markdown_parser.write(open_path, parsed.frontmatter, parsed.body)
            return None
```

and delete the now-duplicated `is_duplicate` / `kind` lines further down in `create`
(they are recomputed there today; keep the single definition above). `_existing_for` and
`_same_mention` stay — they are still used by `check_organic_resolution`.

Run: `api/.venv/bin/python -m pytest api/tests/test_inbox_dedup.py -q`
Expected: PASS

- [ ] **Step 14: Run the tests**

Run: `api/.venv/bin/python -m pytest api/tests/test_inbox_dedup.py api/tests/test_claim_inbox.py api/tests/test_claim_reconciler.py api/tests/test_claim_pipeline.py -q`
Expected: PASS

Run: `api/.venv/bin/python -m pytest api/tests -q`
Expected: PASS

- [ ] **Step 15: Commit**

```bash
git add api/services/predicates.py api/services/claim_reconciler.py api/services/inbox_generator.py api/services/clarification_manager.py api/tests/test_inbox_dedup.py
git commit -m "$(cat <<'EOF'
feat(inbox): dedup conflicts by (entity, predicate) with merge-on-collision (G60)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

### Task 3: Entity-path LLM question + template fallback

**Files:**
- Modify: `api/services/conflict_resolver.py:598-640` (`_CONTRADICTION_PROMPT`, `_detect_contradiction`)
- Modify: `api/services/conflict_resolver.py:88-99` (the `conflict_nudge` change built in `resolve_and_prune`)
- Test: `api/tests/test_conflict_question.py`

**Interfaces:**
- Consumes: `predicates.predicate_question(predicate, name)` (Task 2), `inbox_questions.humanize_age` (Task 1), `conflict_resolver._days_since_last_referenced(last_referenced, now)` (existing, line 505).
- Produces: `conflict_resolver.build_entity_question(entity_name, raw: dict | None, today: str) -> dict` returning `{"question": str, "options": list[dict]}` in the object form Task 2's writer expects (`predicate` is always `"description"` on this path).

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_conflict_question.py`:

```python
"""G60 — the entity path (conflict_resolver) also emits a question object.

The LLM is asked for `question` + per-option `description`; a parse failure or
a key-less response falls back to the deterministic template, so this path
never regresses to a bare option list.
"""

from __future__ import annotations

from api.services import conflict_resolver


def test_build_entity_question_uses_the_llm_payload_when_complete():
    raw = {
        "has_unresolvable_contradiction": True,
        "contradiction": "Two stacks are described.",
        "question": "Which database is Cicada on now?",
        "options": [
            {"label": "Postgres", "description": "Described in the older page body"},
            {"label": "SQLite", "description": "Described in the newer extraction"},
            {"label": "Both are true (different contexts)"},
        ],
    }
    out = conflict_resolver.build_entity_question("Cicada", raw, today="2026-08-30")
    assert out["question"] == "Which database is Cicada on now?"
    assert [o["key"] for o in out["options"]] == ["a", "b", "both"]
    assert out["options"][0]["label"] == "Postgres"
    assert out["options"][0]["description"] == "Described in the older page body"
    assert out["options"][2]["key"] == "both"
    assert out["options"][0]["claim_id"] is None


def test_build_entity_question_falls_back_to_the_template():
    raw = {
        "has_unresolvable_contradiction": True,
        "contradiction": "Two stacks.",
        "options": ["Postgres", "SQLite"],
    }
    out = conflict_resolver.build_entity_question("Cicada", raw, today="2026-08-30")
    assert out["question"] == "What is currently true about Cicada?"
    assert [o["label"] for o in out["options"]] == [
        "Postgres", "SQLite", "Both are true (different contexts)",
    ]
    # The template always adds a description so the card is never blank.
    assert out["options"][0]["description"]


def test_build_entity_question_survives_a_null_payload():
    out = conflict_resolver.build_entity_question("Cicada", None, today="2026-08-30")
    assert out["question"] == "What is currently true about Cicada?"
    assert [o["key"] for o in out["options"]] == ["both"]


def test_contradiction_prompt_asks_for_question_and_descriptions():
    assert '"question"' in conflict_resolver._CONTRADICTION_PROMPT
    assert '"description"' in conflict_resolver._CONTRADICTION_PROMPT
```

- [ ] **Step 2: Run test to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_conflict_question.py -q`
Expected: FAIL — `module 'api.services.conflict_resolver' has no attribute 'build_entity_question'`

- [ ] **Step 3: Extend the prompt and add `build_entity_question`**

Replace `_CONTRADICTION_PROMPT` in `api/services/conflict_resolver.py:598` with:

```python
_CONTRADICTION_PROMPT = """You are checking whether two descriptions of the same entity contain an unresolvable contradiction.

A contradiction is unresolvable when newer information alone does not make it obvious which statement is currently true. For example: two different stacks mentioned across two conversations with no date cue, or two different roles for the same person.

ENTITY: {entity_name}

EXISTING DESCRIPTION:
{existing_body}

NEW DESCRIPTION:
{new_description}

Respond with JSON only:
{{
  "has_unresolvable_contradiction": true | false,
  "contradiction": "one-sentence description of the contradiction, or empty",
  "question": "ONE short question, in the user's voice, that resolves it (e.g. 'Where does Rodrigo work now?'). Empty when there is no contradiction.",
  "options": [
    {{"label": "the existing claim, 1-4 words", "description": "one short clause saying where this came from and when"}},
    {{"label": "the new claim, 1-4 words", "description": "one short clause saying where this came from and when"}},
    {{"label": "Both are true (different contexts)", "description": "Keep both, each tagged with its context"}}
  ]
}}

If there is no contradiction, set has_unresolvable_contradiction to false, question to "", and options to []."""
```

Add, immediately after `_CONTRADICTION_PROMPT`:

```python
_BOTH_OPTION = {
    "key": "both",
    "label": "Both are true (different contexts)",
    "description": "Keep both claims, each tagged with its context",
    "claim_id": None,
}


def build_entity_question(entity_name: str, raw: dict | None, today: str) -> dict:
    """Normalize an LLM contradiction payload into the G60 question object.

    The entity path has no claims behind its options (it compares page bodies),
    so every option carries ``claim_id: None`` and the item keys on the literal
    predicate ``"description"``. A missing/blank ``question`` or a flat
    ``options: [str]`` payload degrades to the deterministic template rather
    than producing a card with no question — under-specifying is safe here.
    """
    from api.services import predicates

    raw = raw or {}
    question = str(raw.get("question", "") or "").strip()
    if not question:
        question = predicates.predicate_question("description", entity_name)

    options: list[dict] = []
    for key, item in zip(("a", "b"), raw.get("options") or []):
        if isinstance(item, dict):
            label = str(item.get("label", "") or "").strip()
            description = str(item.get("description", "") or "").strip()
        else:
            label = str(item).strip()
            description = ""
        if not label or label == _BOTH_OPTION["label"]:
            continue
        options.append({
            "key": key,
            "label": label,
            "description": description or f"Described on the page as of {today}",
            "claim_id": None,
            "observed_at": today,
            "last_referenced": today,
        })

    options.append(dict(_BOTH_OPTION))
    return {"question": question, "options": options}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `api/.venv/bin/python -m pytest api/tests/test_conflict_question.py -q`
Expected: PASS

- [ ] **Step 5: Wire it into `resolve_and_prune`**

Replace the `changes.append({...})` block at `api/services/conflict_resolver.py:88-99` with:

```python
        if contradiction and contradiction.get("has_unresolvable_contradiction"):
            conflicts_found += 1
            progress.set_postfix_str(f"conflicts={conflicts_found}", refresh=False)
            today_str = str(date.today())
            built = build_entity_question(entity_name, contradiction, today_str)
            changes.append({
                "id": entity_id,
                "action": "conflict_nudge",
                "entity": new_entity,
                "conflict_context": contradiction.get("contradiction", ""),
                "predicate": "description",
                "question": built["question"],
                "options": built["options"],
                "allow_other": True,
                "allow_defer": True,
                "source_episode": change.get("source_episode", ""),
                "trigger": "sleep/conflict_resolution",
            })
```

(`date` is already imported at `api/services/conflict_resolver.py:4`.)

- [ ] **Step 6: Run the suite**

Run: `api/.venv/bin/python -m pytest api/tests -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add api/services/conflict_resolver.py api/tests/test_conflict_question.py
git commit -m "$(cat <<'EOF'
feat(inbox): entity-path conflicts emit a question object (LLM + template fallback) (G60)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

### Task 4: `dedup_open_items` startup migration

**Files:**
- Modify: `api/services/inbox_migration.py` (append `dedup_open_items` + its commit helper)
- Modify: `api/main.py:104-108` (lifespan, right after `migrate_to_inbox`)
- Test: `api/tests/test_inbox_dedup_migration.py`

**Interfaces:**
- Consumes: `inbox_generator.dedup_key`, `inbox_generator.merge_options_into` (Task 2).
- Produces: `inbox_migration.dedup_open_items(memory_path: Path) -> int` — number of duplicate files removed. Idempotent via the `inbox/.deduped` marker; never raises.

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_inbox_dedup_migration.py`:

```python
"""G60 — one-shot startup collapse of already-written duplicate open items."""

from __future__ import annotations

import subprocess
from pathlib import Path

from api.services import inbox_migration, markdown_parser


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(repo), check=True, capture_output=True, text=True
    ).stdout


def _init_memory(tmp_path: Path) -> Path:
    repo = tmp_path / "memory"
    (repo / "inbox").mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@cicada.local")
    _git(repo, "config", "user.name", "Cicada Test")
    return repo


def _conflict(repo: Path, item_id: str, created: str, labels: list[str]) -> None:
    markdown_parser.write(
        repo / "inbox" / f"{item_id}.md",
        {
            "kind": "conflict",
            "required_input": "choice",
            "status": "pending",
            "priority": 0.8,
            "entity_id": "rodrigo-sagastegui",
            "entity_name": "Rodrigo Sagastegui",
            "title": "Conflicting beliefs about Rodrigo Sagastegui",
            "created_date": created,
            "predicate": "works-at",
            "options": [
                {"key": chr(ord("a") + i), "label": label, "observed_at": "2026-02-18",
                 "last_referenced": "2026-02-18"}
                for i, label in enumerate(labels)
            ],
        },
        "Conflicting beliefs.",
    )


def test_dedup_collapses_duplicates_into_the_oldest_and_commits(tmp_path):
    repo = _init_memory(tmp_path)
    _conflict(repo, "inbox-011", "2026-06-18", ["mongodb", "supahost"])
    _conflict(repo, "inbox-042", "2026-07-02", ["mongodb", "acme"])
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed")

    removed = inbox_migration.dedup_open_items(repo)

    assert removed == 1
    remaining = sorted(p.stem for p in (repo / "inbox").glob("inbox-*.md"))
    assert remaining == ["inbox-011"], "the OLDEST item survives"

    fm = markdown_parser.parse(repo / "inbox" / "inbox-011.md").frontmatter
    assert [o["label"] for o in fm["options"]] == ["mongodb", "supahost", "acme"]
    assert fm["created_date"] == "2026-06-18"

    log = _git(repo, "log", "--format=%s%n%b")
    assert "inbox/dedup" in log


def test_dedup_is_idempotent_and_marker_short_circuits(tmp_path):
    repo = _init_memory(tmp_path)
    _conflict(repo, "inbox-011", "2026-06-18", ["mongodb"])
    _conflict(repo, "inbox-042", "2026-07-02", ["supahost"])
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed")

    assert inbox_migration.dedup_open_items(repo) == 1
    assert (repo / "inbox" / ".deduped").exists()
    assert inbox_migration.dedup_open_items(repo) == 0


def test_dedup_leaves_distinct_keys_and_resolved_items_alone(tmp_path):
    repo = _init_memory(tmp_path)
    _conflict(repo, "inbox-001", "2026-06-18", ["mongodb"])
    markdown_parser.write(
        repo / "inbox" / "inbox-002.md",
        {"kind": "conflict", "status": "pending", "entity_id": "rodrigo-sagastegui",
         "predicate": "uses", "created_date": "2026-06-19", "options": []},
        "other predicate",
    )
    markdown_parser.write(
        repo / "inbox" / "inbox-003.md",
        {"kind": "conflict", "status": "resolved", "entity_id": "rodrigo-sagastegui",
         "predicate": "works-at", "created_date": "2026-06-20", "options": []},
        "already resolved",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed")

    assert inbox_migration.dedup_open_items(repo) == 0
    assert len(list((repo / "inbox").glob("inbox-*.md"))) == 3


def test_dedup_never_raises_on_a_non_repo(tmp_path):
    plain = tmp_path / "no-git"
    (plain / "inbox").mkdir(parents=True)
    _conflict(plain, "inbox-001", "2026-06-18", ["mongodb"])
    _conflict(plain, "inbox-002", "2026-06-19", ["supahost"])
    # Files still collapse on disk; only the commit is skipped.
    assert inbox_migration.dedup_open_items(plain) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_inbox_dedup_migration.py -q`
Expected: FAIL — `module 'api.services.inbox_migration' has no attribute 'dedup_open_items'`

- [ ] **Step 3: Implement `dedup_open_items`**

Append to `api/services/inbox_migration.py`:

```python
_DEDUP_MARKER = ".deduped"


def dedup_open_items(memory_path: Path) -> int:
    """Collapse pre-existing duplicate OPEN inbox items (G60 §2.2). Idempotent.

    Groups every ``status: pending`` item by ``(kind, dedup_key)``, keeps the
    one with the lowest inbox number (the oldest question, so ``created_date``
    and any user-visible history survive), merges every other member's options
    into it with :func:`inbox_generator.merge_options_into`, and deletes the
    rest. Commits scoped to ``inbox/`` only — never ``git add -A``.

    Never raises: a failure is logged and boot continues. Returns the number of
    duplicate files removed.
    """
    from api.services.inbox_generator import dedup_key, merge_options_into

    memory_path = Path(memory_path)
    inbox = memory_path / "inbox"
    if not inbox.exists():
        return 0
    marker = inbox / _DEDUP_MARKER
    if marker.exists():
        return 0

    try:
        groups: dict[tuple[str, tuple[str, str]], list[Path]] = {}
        for filepath in sorted(inbox.glob("inbox-*.md")):
            try:
                fm = markdown_parser.parse(filepath).frontmatter
            except Exception:
                continue
            if str(fm.get("status", "pending") or "pending") != "pending":
                continue
            kind = str(fm.get("kind", "") or "")
            if kind not in ("conflict", "clarification", "merge_suggestion"):
                continue
            groups.setdefault((kind, dedup_key(kind, fm)), []).append(filepath)

        removed = 0
        today = str(date.today())
        for (kind, _key), members in groups.items():
            if len(members) < 2:
                continue
            survivor, duplicates = members[0], members[1:]
            for dup in duplicates:
                try:
                    dup_fm = markdown_parser.parse(dup).frontmatter
                except Exception:
                    dup_fm = {}
                if kind == "conflict":
                    merge_options_into(survivor, dup_fm.get("options") or [], today)
                else:
                    parsed = markdown_parser.parse(survivor)
                    parsed.frontmatter["updated_date"] = today
                    markdown_parser.write(survivor, parsed.frontmatter, parsed.body)
                dup.unlink()
                removed += 1
    except Exception as e:
        logger.error(f"Inbox dedup FAILED — leaving inbox/ untouched: {e}")
        return 0

    if removed:
        try:
            _commit_dedup(memory_path, removed)
        except Exception as e:
            # Files are collapsed on disk but the commit failed (or this isn't
            # a git repo). Do NOT write the marker so a later boot retries; the
            # collapse itself is idempotent (0 duplicates left => 0 next time).
            logger.warning(f"Inbox dedup commit skipped: {e}")
            return removed

    marker.write_text("v1")
    return removed


def _commit_dedup(memory_path: Path, removed: int) -> None:
    """Commit the dedup scoped to ONLY inbox/ (never ``git add -A``)."""
    subprocess.run(["git", "add", "--", "inbox"], cwd=str(memory_path), check=True)
    status = subprocess.run(
        ["git", "status", "--porcelain", "--", "inbox"],
        cwd=str(memory_path), check=True, capture_output=True, text=True,
    )
    if not status.stdout.strip():
        return
    message = (
        "Collapse duplicate open inbox questions\n\n"
        f"inbox/: {removed} duplicate item(s) merged into their oldest sibling "
        "(trigger: inbox/dedup)\n\n"
        "Cicada-Author: user"
    )
    subprocess.run(
        ["git", "commit", "-m", message, "--", "inbox"],
        cwd=str(memory_path), check=True,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `api/.venv/bin/python -m pytest api/tests/test_inbox_dedup_migration.py -q`
Expected: PASS

- [ ] **Step 5: Wire it into startup**

In `api/main.py`, change the import line:

```python
from api.services.inbox_migration import dedup_open_items, migrate_to_inbox
```

and extend the lifespan block that currently reads
`moved = migrate_to_inbox(settings.memory_path)`:

```python
    # One-time idempotent migration of legacy nudges/clarifications into inbox/.
    # Never crashes boot — a failure logs loudly and leaves legacy dirs intact.
    moved = migrate_to_inbox(settings.memory_path)
    if moved:
        logger.info(f"Migrated {moved} legacy items into inbox/")

    # G60: one-time collapse of duplicate open questions written before dedup
    # existed. Same never-crash-boot contract; marker-guarded.
    deduped = dedup_open_items(settings.memory_path)
    if deduped:
        logger.info(f"Collapsed {deduped} duplicate open inbox item(s)")
```

- [ ] **Step 6: Run the suite**

Run: `api/.venv/bin/python -m pytest api/tests -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add api/services/inbox_migration.py api/main.py api/tests/test_inbox_dedup_migration.py
git commit -m "$(cat <<'EOF'
feat(inbox): one-shot dedup_open_items migration at backend start (G60)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

### Task 5: `refresh_open_questions` — Stage-3 re-scoring, organic resolution, stale escalation, defer hiding

**Files:**
- Modify: `api/services/inbox_questions.py` (append `is_deferred`, `refresh_open_questions`)
- Modify: `api/services/inbox_service.py` (`load_inbox` hides deferred)
- Modify: `api/config.py` (two settings), `api/services/sleep_cycle.py` (`SleepState` counters + Stage 5.56 call), `api/models/schemas.py` (`SleepStatusResponse` counters), `api/routers/sleep.py` (pass them through)
- Test: `api/tests/test_inbox_refresh.py`

**Interfaces:**
- Consumes: `claim_pipeline._load_existing_claims_by_subject(memory_path) -> dict[str, list[Claim]]`, `inbox_generator.dedup_key`, `claims.Claim` (fields `id/predicate/object/valid_from/valid_to/recorded_at/source_trust/subject`).
- Produces:
  - `inbox_questions.is_deferred(fm: dict, today: str) -> bool`
  - `inbox_questions.refresh_open_questions(memory_path: Path, claims_by_subject: dict[str, list[Claim]], today: str, *, stale_after_days: int = 90) -> dict` returning `{"bumped": int, "organic_resolutions": int, "escalated": int}`
  - `Settings.inbox_stale_after_days: int = 90`, `Settings.inbox_defer_days: int = 30`
  - `SleepState.organic_resolutions: int`, `SleepState.questions_refreshed: int`

- [ ] **Step 1: Write the failing test for `is_deferred` and `load_inbox` hiding**

Create `api/tests/test_inbox_refresh.py`:

```python
"""G60 §2.3 — Stage-3 re-scoring of open questions + defer visibility."""

from __future__ import annotations

from pathlib import Path

from api.services import inbox_questions, inbox_service, markdown_parser
from api.services.claims import Claim


def _write_conflict(memory: Path, item_id: str, *, entity_id: str = "rodrigo",
                    predicate: str = "works-at", options: list[dict] | None = None,
                    created: str = "2026-02-20", priority: float = 0.8,
                    extra: dict | None = None) -> Path:
    inbox = memory / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    fm = {
        "kind": "conflict",
        "required_input": "choice",
        "status": "pending",
        "priority": priority,
        "entity_id": entity_id,
        "entity_name": "Rodrigo",
        "title": "Where does Rodrigo work now?",
        "question": "Where does Rodrigo work now?",
        "created_date": created,
        "predicate": predicate,
        "allow_other": True,
        "allow_defer": True,
        "options": options if options is not None else [
            {"key": "a", "label": "mongodb", "claim_id": "clm_a",
             "observed_at": "2026-02-18", "last_referenced": "2026-02-18"},
            {"key": "b", "label": "supahost", "claim_id": "clm_b",
             "observed_at": "2026-02-18", "last_referenced": "2026-02-18"},
            {"key": "both", "label": "Both are true (different contexts)"},
        ],
    }
    fm.update(extra or {})
    path = inbox / f"{item_id}.md"
    markdown_parser.write(path, fm, "Conflicting beliefs.")
    return path


def _claim(cid: str, obj: str, *, valid_from: str, valid_to: str | None = None,
           source_trust: str = "agent_extracted", recorded_at: str | None = None) -> Claim:
    return Claim(
        id=cid, text=f"Rodrigo works at {obj}", subject="rodrigo",
        predicate="works-at", object=obj, source_trust=source_trust,
        valid_from=valid_from, valid_to=valid_to,
        recorded_at=recorded_at or valid_from,
    )


def test_is_deferred_only_while_remind_after_is_in_the_future():
    assert inbox_questions.is_deferred({"remind_after": "2026-09-30"}, "2026-08-30") is True
    assert inbox_questions.is_deferred({"remind_after": "2026-08-30"}, "2026-08-30") is False
    assert inbox_questions.is_deferred({"remind_after": "2026-01-01"}, "2026-08-30") is False
    assert inbox_questions.is_deferred({}, "2026-08-30") is False
    assert inbox_questions.is_deferred({"remind_after": None}, "2026-08-30") is False


def test_load_inbox_hides_deferred_items_but_they_stay_on_disk(tmp_path):
    memory = tmp_path / "memory"
    _write_conflict(memory, "inbox-001")
    _write_conflict(memory, "inbox-002", predicate="uses",
                    extra={"remind_after": "2099-01-01"})

    visible = inbox_service.load_inbox(memory)
    assert [i.id for i in visible] == ["inbox-001"]

    everything = inbox_service.load_inbox(memory, include_deferred=True)
    assert {i.id for i in everything} == {"inbox-001", "inbox-002"}
    assert (memory / "inbox" / "inbox-002.md").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_inbox_refresh.py -q`
Expected: FAIL — `module 'api.services.inbox_questions' has no attribute 'is_deferred'`

- [ ] **Step 3: Add `is_deferred` and the `load_inbox` filter**

Append to `api/services/inbox_questions.py`:

```python
def is_deferred(fm: dict, today: str) -> bool:
    """True while a deferred item's ``remind_after`` is still in the future.

    A deferred item is hidden from ``GET /inbox`` and ``cicada_check_nudges``;
    the file stays on disk and reappears the day the date passes.
    """
    remind = _as_date(fm.get("remind_after"))
    now = _as_date(today)
    if remind is None or now is None:
        return False
    return remind > now
```

In `api/services/inbox_service.py`, replace `load_inbox`:

```python
def load_inbox(memory_path: Path, *, include_deferred: bool = False) -> list[InboxItem]:
    """Load inbox items, sorted: pending first, then priority desc, date desc.

    Deferred items (``remind_after`` still in the future, §2.3-4) are hidden by
    default — the file stays on disk and the card returns on its own the day the
    date passes. ``include_deferred=True`` is for maintenance callers.
    """
    inbox_dir = _inbox_dir(memory_path)
    today = str(date.today())
    items: list[InboxItem] = []
    for filepath in sorted(inbox_dir.glob("inbox-*.md")):
        try:
            item = _item_from_file(filepath, today=today)
        except Exception:
            continue
        if not include_deferred and item.remind_after and inbox_questions.is_deferred(
            {"remind_after": item.remind_after}, today
        ):
            continue
        items.append(item)
    items.sort(
        key=lambda i: (
            0 if i.status == "pending" else 1,
            -i.priority,
            _neg_date_key(i.created_date),
        )
    )
    return items
```

- [ ] **Step 4: Run test to verify it passes**

Run: `api/.venv/bin/python -m pytest api/tests/test_inbox_refresh.py -q`
Expected: PASS (2 tests)

- [ ] **Step 5: Write the failing tests for `refresh_open_questions`**

Append to `api/tests/test_inbox_refresh.py`:

```python
def test_refresh_bumps_and_reorders_a_reinforced_option(tmp_path):
    memory = tmp_path / "memory"
    path = _write_conflict(memory, "inbox-001")
    claims = {"rodrigo": [
        _claim("clm_a", "mongodb", valid_from="2026-02-18"),
        _claim("clm_b", "supahost", valid_from="2026-02-18", recorded_at="2026-08-25"),
    ]}

    result = inbox_questions.refresh_open_questions(memory, claims, "2026-08-30")

    assert result["bumped"] == 1
    assert result["organic_resolutions"] == 0
    fm = markdown_parser.parse(path).frontmatter
    # The freshly-reinforced value sorts first; the synthetic row stays last.
    assert [o["label"] for o in fm["options"]] == [
        "supahost", "mongodb", "Both are true (different contexts)",
    ]
    assert fm["options"][0]["last_referenced"] == "2026-08-25"
    assert fm["updated_date"] == "2026-08-30"


def test_refresh_resolves_organically_on_a_user_stated_claim(tmp_path):
    memory = tmp_path / "memory"
    path = _write_conflict(memory, "inbox-001")
    claims = {"rodrigo": [
        _claim("clm_a", "mongodb", valid_from="2026-02-18"),
        _claim("clm_b", "supahost", valid_from="2026-02-18"),
        _claim("clm_user", "acme", valid_from="2026-08-28",
               source_trust="user_stated"),
    ]}

    result = inbox_questions.refresh_open_questions(memory, claims, "2026-08-30")

    assert result["organic_resolutions"] == 1
    assert not path.exists(), "a human answer in conversation closes the question"


def test_refresh_resolves_organically_when_an_option_claim_was_superseded(tmp_path):
    memory = tmp_path / "memory"
    path = _write_conflict(memory, "inbox-001")
    claims = {"rodrigo": [
        _claim("clm_a", "mongodb", valid_from="2026-02-18", valid_to="2026-08-20"),
        _claim("clm_b", "supahost", valid_from="2026-02-18"),
    ]}

    result = inbox_questions.refresh_open_questions(memory, claims, "2026-08-30")

    assert result["organic_resolutions"] == 1
    assert not path.exists()


def test_refresh_escalates_a_stale_question_and_inserts_neither(tmp_path):
    memory = tmp_path / "memory"
    path = _write_conflict(memory, "inbox-001")
    claims = {"rodrigo": [
        _claim("clm_a", "mongodb", valid_from="2026-02-18"),
        _claim("clm_b", "supahost", valid_from="2026-02-18"),
    ]}

    result = inbox_questions.refresh_open_questions(
        memory, claims, "2026-08-30", stale_after_days=90
    )

    assert result["escalated"] == 1
    fm = markdown_parser.parse(path).frontmatter
    assert fm["options"][0]["key"] == "neither"
    assert fm["options"][0]["label"] == "Neither anymore"
    assert "Close both" in fm["options"][0]["description"]
    assert fm["priority"] == 0.6
    assert "6 months" in fm["question"]
    assert "Rodrigo" in fm["question"]

    # Escalation is idempotent — a second pass must not stack a second `neither`.
    again = inbox_questions.refresh_open_questions(
        memory, claims, "2026-08-30", stale_after_days=90
    )
    assert again["escalated"] == 0
    fm2 = markdown_parser.parse(path).frontmatter
    assert [o["key"] for o in fm2["options"]].count("neither") == 1


def test_refresh_skips_deferred_items(tmp_path):
    memory = tmp_path / "memory"
    path = _write_conflict(memory, "inbox-001", extra={"remind_after": "2099-01-01"})
    claims = {"rodrigo": [_claim("clm_user", "acme", valid_from="2026-08-28",
                                 source_trust="user_stated")]}

    result = inbox_questions.refresh_open_questions(memory, claims, "2026-08-30")

    assert result == {"bumped": 0, "organic_resolutions": 0, "escalated": 0}
    assert path.exists()


def test_refresh_ignores_non_conflict_kinds(tmp_path):
    memory = tmp_path / "memory"
    inbox = memory / "inbox"
    inbox.mkdir(parents=True)
    markdown_parser.write(
        inbox / "inbox-001.md",
        {"kind": "decay", "status": "pending", "entity_id": "rodrigo",
         "created_date": "2026-02-20", "options": None},
        "decaying",
    )
    result = inbox_questions.refresh_open_questions(memory, {}, "2026-08-30")
    assert result == {"bumped": 0, "organic_resolutions": 0, "escalated": 0}
    assert (inbox / "inbox-001.md").exists()
```

- [ ] **Step 6: Run test to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_inbox_refresh.py -q`
Expected: FAIL — `module 'api.services.inbox_questions' has no attribute 'refresh_open_questions'`

- [ ] **Step 7: Implement `refresh_open_questions`**

Append to `api/services/inbox_questions.py`:

```python
_NEITHER_OPTION = {
    "key": "neither",
    "label": "Neither anymore",
    "description": "Close both; tell me what's current below",
    "claim_id": None,
}

_STALE_PRIORITY = 0.6


def _stale_question(name: str, age_phrase: str) -> str:
    return (
        f"It's been {age_phrase.replace(' ago', '')} since either came up. "
        f"Is {name} still at one of these?"
    )


def refresh_open_questions(
    memory_path: Path,
    claims_by_subject: dict,
    today: str,
    *,
    stale_after_days: int = 90,
) -> dict:
    """Re-score every open conflict question against this cycle's claims (§2.3).

    1. **Bump + re-order.** An option whose claim was reinforced since the option
       was last referenced gets ``last_referenced`` bumped; options are then
       re-sorted most-recent-first (synthetic rows always stay last).
    2. **Organic resolution.** If a ``user_stated`` claim now exists on the same
       ``(subject, predicate)``, or one of the option claims has been closed
       (``valid_to`` set) by the reconciler, the question is answered — the item
       file is removed. The caller commits with trigger ``inbox/organic_resolution``.
    3. **Stale escalation.** When EVERY option is older than ``stale_after_days``,
       the question is rewritten to the stale template, a ``neither`` option is
       inserted first, and priority drops to 0.6 so fresh conflicts sort above it.
       Idempotent: an item that already carries ``neither`` is not re-escalated.
    4. Deferred items are skipped entirely.

    Returns ``{"bumped": n, "organic_resolutions": n, "escalated": n}``.
    """
    from api.services import markdown_parser

    inbox = Path(memory_path) / "inbox"
    counts = {"bumped": 0, "organic_resolutions": 0, "escalated": 0}
    if not inbox.exists():
        return counts

    for filepath in sorted(inbox.glob("inbox-*.md")):
        try:
            parsed = markdown_parser.parse(filepath)
        except Exception:
            continue
        fm = parsed.frontmatter
        if str(fm.get("kind", "")) != "conflict":
            continue
        if str(fm.get("status", "pending") or "pending") != "pending":
            continue
        if is_deferred(fm, today):
            continue

        subject = str(fm.get("entity_id", "") or "")
        predicate = str(fm.get("predicate", "") or "description")
        subject_claims = list(claims_by_subject.get(subject, []) or [])
        by_id = {c.id: c for c in subject_claims}
        options = normalize_options(fm.get("options"))
        option_claim_ids = [
            str(o["claim_id"]) for o in options if o.get("claim_id")
        ]

        # --- 2. organic resolution -----------------------------------------
        human_answer = any(
            c.predicate == predicate
            and c.source_trust == "user_stated"
            and c.valid_to is None
            and str(c.valid_from or "") > str(fm.get("created_date", "") or "")
            for c in subject_claims
        )
        superseded = any(
            by_id.get(cid) is not None and by_id[cid].valid_to is not None
            for cid in option_claim_ids
        )
        if human_answer or (option_claim_ids and superseded):
            filepath.unlink()
            counts["organic_resolutions"] += 1
            continue

        changed = False

        # --- 1. bump + re-order --------------------------------------------
        bumped_any = False
        for option in options:
            claim = by_id.get(str(option.get("claim_id") or ""))
            if claim is None:
                continue
            seen = str(claim.recorded_at or claim.valid_from or "")
            current = str(option.get("last_referenced") or option.get("observed_at") or "")
            if seen and seen > current:
                option["last_referenced"] = seen
                bumped_any = True
        if bumped_any:
            counts["bumped"] += 1
            changed = True

        real = [o for o in options if str(o.get("key")) not in {"both", "neither"}]
        synthetic = [o for o in options if str(o.get("key")) in {"both", "neither"}]
        real.sort(
            key=lambda o: str(o.get("last_referenced") or o.get("observed_at") or ""),
            reverse=True,
        )
        neither = [o for o in synthetic if str(o.get("key")) == "neither"]
        both = [o for o in synthetic if str(o.get("key")) == "both"]
        options = neither + real + both

        # --- 3. stale escalation -------------------------------------------
        already_escalated = bool(neither)
        answerable = [o for o in options if str(o.get("key")) not in {"both", "neither"}]
        ages = [
            age_days(o.get("last_referenced") or o.get("observed_at"), today)
            for o in answerable
        ]
        all_stale = bool(ages) and all(a is not None and a >= stale_after_days for a in ages)
        if all_stale and not already_escalated:
            # Phrase the window from the FRESHEST option — "it's been 6 months
            # since EITHER came up" must be true of the most recent one.
            freshest = min((a for a in ages if a is not None), default=None)
            phrase = humanize_age(
                None if freshest is None else _shift(today, freshest), today
            )
            fm["question"] = _stale_question(
                str(fm.get("entity_name", "") or subject), phrase
            )
            fm["title"] = fm["question"]
            fm["priority"] = _STALE_PRIORITY
            options = [dict(_NEITHER_OPTION)] + options
            counts["escalated"] += 1
            changed = True

        if changed:
            fm["options"] = options
            fm["updated_date"] = today
            markdown_parser.write(filepath, fm, parsed.body)

    return counts


def _shift(today: str, days: int) -> str:
    """``today`` minus ``days``, as an ISO date string (helper for age phrasing)."""
    base = _as_date(today)
    if base is None:
        return today
    from datetime import timedelta

    return (base - timedelta(days=days)).isoformat()
```

- [ ] **Step 8: Run test to verify it passes**

Run: `api/.venv/bin/python -m pytest api/tests/test_inbox_refresh.py -q`
Expected: PASS (8 tests)

- [ ] **Step 9: Add the settings**

In `api/config.py`, under the `# Sleep cycle thresholds` block, add:

```python
    # G60 — open-question re-scoring. An open conflict every one of whose
    # options has been silent for this many days is escalated (question
    # rewritten, a "Neither anymore" option inserted, priority dropped).
    inbox_stale_after_days: int = 90     # CICADA_INBOX_STALE_AFTER_DAYS
    # How far out a "Not sure — remind me later" pushes `remind_after` when the
    # request does not name a number of days.
    inbox_defer_days: int = 30           # CICADA_INBOX_DEFER_DAYS
```

- [ ] **Step 10: Write the failing test for the Sleep wiring**

Append to `api/tests/test_inbox_refresh.py`:

```python
def test_sleep_state_carries_the_new_counters():
    from api.services.sleep_cycle import SleepState

    state = SleepState()
    assert state.organic_resolutions == 0
    assert state.questions_refreshed == 0
```

- [ ] **Step 11: Run test to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_inbox_refresh.py::test_sleep_state_carries_the_new_counters -q`
Expected: FAIL with `AttributeError: 'SleepState' object has no attribute 'organic_resolutions'`

- [ ] **Step 12: Wire the counters and the Stage 5.56 call**

In `api/services/sleep_cycle.py`, add to the `SleepState` dataclass (after `episodes_requeued`):

```python
    # G60 — open-question re-scoring (Stage 5.56). ``questions_refreshed`` counts
    # items whose options were bumped or escalated; ``organic_resolutions`` counts
    # questions answered by later conversation and closed without the user acting.
    questions_refreshed: int = 0
    organic_resolutions: int = 0
```

Inside the Stage 5.56 `try:` block, after `n_nudges = write_claim_nudges(...)` and before the `logger.info`:

```python
            # G60 §2.3 — re-score the OPEN questions against the freshly-written
            # claims (bump/re-order, organic resolution, stale escalation). Runs
            # AFTER write_claim_nudges so this cycle's new competing values are
            # already merged into their open question.
            from api.services import inbox_questions
            from api.services.claim_pipeline import _load_existing_claims_by_subject

            refresh = inbox_questions.refresh_open_questions(
                memory_path,
                _load_existing_claims_by_subject(memory_path),
                str(datetime.now().date()),
                stale_after_days=settings.inbox_stale_after_days,
            )
            _state.questions_refreshed = refresh["bumped"] + refresh["escalated"]
            _state.organic_resolutions = refresh["organic_resolutions"]
            logger.info(
                f"Stage 5.56: refreshed {refresh['bumped']} question(s), "
                f"escalated {refresh['escalated']}, "
                f"organically resolved {refresh['organic_resolutions']}"
            )
```

In `api/models/schemas.py`, add to `SleepStatusResponse` (after `episodes_requeued`):

```python
    # G60 — open-question re-scoring outcomes for the Sleep dashboard.
    questions_refreshed: int = 0
    organic_resolutions: int = 0
```

Then check `api/routers/sleep.py` builds `SleepStatusResponse` field-by-field:

Run: `grep -n "SleepStatusResponse(" -A 25 api/routers/sleep.py`

If it enumerates fields, add `questions_refreshed=state.questions_refreshed,` and `organic_resolutions=state.organic_resolutions,`.

- [ ] **Step 13: Run the suite**

Run: `api/.venv/bin/python -m pytest api/tests -q`
Expected: PASS

- [ ] **Step 14: Commit**

```bash
git add api/services/inbox_questions.py api/services/inbox_service.py api/services/sleep_cycle.py api/models/schemas.py api/routers/sleep.py api/config.py api/tests/test_inbox_refresh.py
git commit -m "$(cat <<'EOF'
feat(sleep): refresh_open_questions — bump, organic resolution, stale escalation, defer (G60)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

### Task 6: Claim-aware `_resolve_conflict` + the `defer` action

**Files:**
- Modify: `api/services/inbox_service.py` (`resolve` dispatch, `_resolve_conflict`)
- Modify: `api/services/git_service.py:531-555` (`commit_resolution` gains `extra_lines`)
- Test: `api/tests/test_inbox_resolve_claims.py`

**Interfaces:**
- Consumes: `claims.parse_claims(body, strict=True)`, `claims.write_claims(body, claims)`, `claims.Claim`, `claim_reconciler._close(old, by=new)`, `conflict_resolver._synthesize_entity_update(...)`, `predicates.load_normalizer`, `Settings.inbox_defer_days` (Task 5).
- Produces:
  - `git_service.commit_resolution(memory_path, entity_id, trigger, extra_lines: list[str] | None = None)`
  - `inbox_service._resolve_conflict(path, parsed, request, settings) -> tuple[str, bool, list[str]]`
  - `inbox_service.resolve` handles `action == "defer"` for every kind, returning `{"status": "deferred", "id": item_id, "remindAfter": "<iso date>"}`.

**Resolve semantics (§2.4), implemented exactly:**

| `action` / `option_key` | claims | entity page |
|---|---|---|
| `resolve` + a claim-backed key | winner `confidence = max(conf, 0.9)`; every OTHER option claim closed via `_close(old, by=winner)` | `last_referenced = today`, `version += 1`, body resynthesized from `"<name> <predicate> <label> (confirmed by user on <today>)"` |
| `resolve` + `both` | all option claims stay open; each `context == "general"` becomes `f"as of {observed_at}"` | as above with `"Both are true: A and B"` |
| `resolve` + `neither`, or free-text `answer` | a NEW `user_stated` claim (`origin: clarification`, `authored_by: user`, `confidence: 0.95`) closes every option claim. Empty answer + `neither` ⇒ close only, no new claim | as above with the user's sentence |
| `defer` | none | `remind_after = today + remind_days` written to the item; item stays |
| `skip` | none | none |

- [ ] **Step 1: Write the failing tests**

Create `api/tests/test_inbox_resolve_claims.py`:

```python
"""G60 §2.4 — resolving a conflict actually moves the claim layer."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from api.models.schemas import InboxResolveRequest
from api.services import inbox_service, markdown_parser
from api.services.claims import parse_claims


def run(coro):
    return asyncio.run(coro)


class _Settings:
    def __init__(self, memory_path: Path):
        self.memory_path = memory_path
        self.inbox_defer_days = 30
        self.litellm_model = "test-model"
        self.litellm_disambiguation_model = ""
        self.consolidation_model = ""
        self.llm_mode = "byok"

    @property
    def effective_consolidation_model(self) -> str:
        return self.litellm_model


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(repo), check=True, capture_output=True, text=True
    ).stdout


ENTITY_BODY = """Rodrigo is a student.

```claims
- id: clm_a
  text: Rodrigo works at mongodb
  subject: rodrigo
  predicate: works-at
  object: mongodb
  observer: agent
  context: general
  source_trust: agent_extracted
  confidence: 0.6
  valid_from: '2026-02-18'
  recorded_at: '2026-02-18'
- id: clm_b
  text: Rodrigo works at supahost
  subject: rodrigo
  predicate: works-at
  object: supahost
  observer: agent
  context: general
  source_trust: agent_extracted
  confidence: 0.6
  valid_from: '2026-02-18'
  recorded_at: '2026-02-18'
```
"""


def _workspace(tmp_path: Path) -> Path:
    repo = tmp_path / "memory"
    (repo / "entities").mkdir(parents=True)
    (repo / "inbox").mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@cicada.local")
    _git(repo, "config", "user.name", "Cicada Test")

    markdown_parser.write(
        repo / "entities" / "rodrigo.md",
        {"name": "Rodrigo", "type": "person", "status": "active", "confidence": 0.8,
         "created": "2026-01-01", "last_referenced": "2026-02-18", "decay_rate": 0.05,
         "source_episodes": [], "tags": [], "related": [], "version": 3},
        ENTITY_BODY,
    )
    markdown_parser.write(
        repo / "inbox" / "inbox-001.md",
        {"kind": "conflict", "required_input": "choice", "status": "pending",
         "priority": 0.8, "entity_id": "rodrigo", "entity_name": "Rodrigo",
         "title": "Where does Rodrigo work now?",
         "question": "Where does Rodrigo work now?",
         "created_date": "2026-06-18", "predicate": "works-at",
         "allow_other": True, "allow_defer": True,
         "options": [
             {"key": "a", "label": "mongodb", "claim_id": "clm_a",
              "observed_at": "2026-02-18", "last_referenced": "2026-02-18"},
             {"key": "b", "label": "supahost", "claim_id": "clm_b",
              "observed_at": "2026-02-18", "last_referenced": "2026-02-18"},
             {"key": "both", "label": "Both are true (different contexts)"},
         ]},
        "Conflicting beliefs about Rodrigo.",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed")
    return repo


def _claims(repo: Path) -> dict:
    body = markdown_parser.parse(repo / "entities" / "rodrigo.md").body
    return {c.id: c for c in parse_claims(body)}


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    """The body rewrite goes through the LLM; make it deterministic + offline."""
    async def _fake(**kwargs):
        return f"{kwargs['new_description']}"

    monkeypatch.setattr(
        "api.services.conflict_resolver._synthesize_entity_update", _fake
    )


def test_picking_an_option_supersedes_every_other_option_claim(tmp_path):
    repo = _workspace(tmp_path)
    settings = _Settings(repo)

    out = run(inbox_service.resolve(
        "inbox-001", InboxResolveRequest(action="resolve", optionKey="b"), settings
    ))

    assert out["status"] == "resolved"
    claims = _claims(repo)
    assert claims["clm_b"].valid_to is None
    assert claims["clm_b"].confidence >= 0.9
    assert claims["clm_a"].valid_to is not None
    assert claims["clm_a"].superseded_by == "clm_b"
    assert claims["clm_b"].supersedes == "clm_a"

    fm = markdown_parser.parse(repo / "entities" / "rodrigo.md").frontmatter
    assert fm["version"] == 4
    assert not (repo / "inbox" / "inbox-001.md").exists()

    log = _git(repo, "log", "--format=%s%n%b")
    assert "Cicada-Author: user" in log
    assert "inbox/conflict/resolved" in log


def test_both_keeps_claims_open_and_qualifies_their_context(tmp_path):
    repo = _workspace(tmp_path)
    run(inbox_service.resolve(
        "inbox-001", InboxResolveRequest(action="resolve", optionKey="both"), _Settings(repo)
    ))

    claims = _claims(repo)
    assert claims["clm_a"].valid_to is None
    assert claims["clm_b"].valid_to is None
    assert claims["clm_a"].context == "as of 2026-02-18"
    assert claims["clm_b"].context == "as of 2026-02-18"


def test_neither_with_free_text_writes_a_user_claim_and_closes_both(tmp_path):
    repo = _workspace(tmp_path)
    run(inbox_service.resolve(
        "inbox-001",
        InboxResolveRequest(action="resolve", optionKey="neither", answer="Acme Robotics"),
        _Settings(repo),
    ))

    claims = _claims(repo)
    assert claims["clm_a"].valid_to is not None
    assert claims["clm_b"].valid_to is not None

    new = [c for c in claims.values() if c.object == "Acme Robotics"]
    assert len(new) == 1
    user_claim = new[0]
    assert user_claim.source_trust == "user_stated"
    assert user_claim.origin == "clarification"
    assert user_claim.authored_by == "user"
    assert user_claim.confidence == 0.95
    assert user_claim.predicate == "works-at"
    assert user_claim.valid_to is None
    # It closed them, so both point at it.
    assert claims["clm_a"].superseded_by == user_claim.id


def test_neither_without_text_only_closes(tmp_path):
    repo = _workspace(tmp_path)
    run(inbox_service.resolve(
        "inbox-001",
        InboxResolveRequest(action="resolve", optionKey="neither"),
        _Settings(repo),
    ))

    claims = _claims(repo)
    assert claims["clm_a"].valid_to is not None
    assert claims["clm_b"].valid_to is not None
    assert len(claims) == 2, "no new claim is written when there is nothing to say"


def test_free_text_without_an_option_key_behaves_like_neither(tmp_path):
    repo = _workspace(tmp_path)
    run(inbox_service.resolve(
        "inbox-001",
        InboxResolveRequest(action="resolve", answer="Acme Robotics"),
        _Settings(repo),
    ))
    claims = _claims(repo)
    assert any(c.object == "Acme Robotics" and c.source_trust == "user_stated"
               for c in claims.values())


def test_defer_writes_remind_after_and_keeps_the_item(tmp_path):
    repo = _workspace(tmp_path)
    out = run(inbox_service.resolve(
        "inbox-001", InboxResolveRequest(action="defer", remindDays=14), _Settings(repo)
    ))

    assert out["status"] == "deferred"
    path = repo / "inbox" / "inbox-001.md"
    assert path.exists()
    fm = markdown_parser.parse(path).frontmatter
    assert fm["remind_after"] == out["remindAfter"]
    # Claims untouched.
    claims = _claims(repo)
    assert claims["clm_a"].valid_to is None and claims["clm_b"].valid_to is None


def test_defer_defaults_to_the_settings_window(tmp_path):
    repo = _workspace(tmp_path)
    settings = _Settings(repo)
    settings.inbox_defer_days = 30
    out = run(inbox_service.resolve(
        "inbox-001", InboxResolveRequest(action="defer"), settings
    ))
    from datetime import date, timedelta

    assert out["remindAfter"] == str(date.today() + timedelta(days=30))


def test_skip_leaves_everything_untouched(tmp_path):
    repo = _workspace(tmp_path)
    out = run(inbox_service.resolve(
        "inbox-001", InboxResolveRequest(action="skip"), _Settings(repo)
    ))
    assert out["status"] == "skipped"
    assert (repo / "inbox" / "inbox-001.md").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_inbox_resolve_claims.py -q`
Expected: FAIL — the old `_resolve_conflict` ignores `option_key`, writes no claims, and `defer` raises/deletes.

- [ ] **Step 3: Let `commit_resolution` carry extra manifest lines**

Replace `api/services/git_service.py:531-555`:

```python
async def commit_resolution(
    memory_path: Path,
    entity_id: str,
    trigger: str,
    extra_lines: list[str] | None = None,
) -> None:
    """Commit after an inbox (nudge/clarification/conflict) resolution.

    Emits a structured "Inbox resolution <date>" subject so the resolution
    surfaces in ``get_sleep_history`` (the Sleep dashboard) — the old
    single-line subject was never matched by the history filter. ``extra_lines``
    appends further per-file manifest lines (G60: one per closed claim's page).
    """
    date_str = date.today().isoformat()
    # trigger is "inbox/<kind>/resolved" — tag the kind into the subject so the
    # dashboard can distinguish a conflict adjudication from a decay archive.
    kind = ""
    parts = trigger.split("/")
    if len(parts) >= 2 and parts[0] == "inbox":
        kind = parts[1]
    subject = (
        f"Inbox resolution ({kind}) {date_str}" if kind
        else f"Inbox resolution {date_str}"
    )
    body_lines = [f"entities/{entity_id}.md: updated (trigger: {trigger})"]
    body_lines.extend(extra_lines or [])
    # An inbox resolution is a user/companion-app action -> attribute to "user".
    message = build_commit_message(subject, body_lines, authors=["user"])
    await commit_changes(memory_path, message)
```

- [ ] **Step 4: Rewrite the dispatch in `inbox_service.resolve`**

Replace the body of `resolve` in `api/services/inbox_service.py`:

```python
async def resolve(
    item_id: str, request: InboxResolveRequest, settings: Settings
) -> dict:
    """Resolve an inbox item by routing on its ``kind``. Returns a status dict."""
    path = _inbox_dir(settings.memory_path) / f"{item_id}.md"
    if not path.exists():
        raise HTTPException(404, f"Inbox item {item_id} not found")

    parsed = markdown_parser.parse(path)
    kind = str(parsed.frontmatter.get("kind", "decay"))

    # G60 §2.4 — `defer` is kind-agnostic: it never touches claims or the entity
    # page, it just pushes the item out of sight until `remind_after`.
    if request.action == "defer":
        return _defer(path, parsed, request, settings, item_id)

    extra_lines: list[str] = []
    if kind == "decay":
        entity_id, skipped = await _resolve_decay(path, parsed, request, settings)
    elif kind == "conflict":
        entity_id, skipped, extra_lines = await _resolve_conflict(
            path, parsed, request, settings
        )
    elif kind in ("clarification", "merge_suggestion"):
        entity_id, skipped = await _resolve_clarification(
            path, parsed, request, settings
        )
    else:
        raise HTTPException(400, f"Unknown kind {kind}")

    if skipped:
        return {"status": "skipped", "id": item_id}

    # Avoid the local import becoming a hard module-load dependency cycle.
    from api.services import git_service

    await git_service.commit_resolution(
        settings.memory_path, entity_id, f"inbox/{kind}/resolved", extra_lines
    )
    return {"status": "resolved", "id": item_id}


def _defer(path, parsed, request, settings, item_id: str) -> dict:
    """Push an item's ``remind_after`` into the future; the file stays."""
    days = request.remind_days
    if days is None:
        days = int(getattr(settings, "inbox_defer_days", 30) or 30)
    remind_after = str(date.today() + timedelta(days=max(1, int(days))))
    parsed.frontmatter["remind_after"] = remind_after
    parsed.frontmatter["updated_date"] = str(date.today())
    markdown_parser.write(path, parsed.frontmatter, parsed.body)
    return {"status": "deferred", "id": item_id, "remindAfter": remind_after}
```

- [ ] **Step 5: Rewrite `_resolve_conflict`**

Replace `_resolve_conflict` in `api/services/inbox_service.py`:

```python
def _user_claim_id(entity_id: str, predicate: str, obj: str, today: str) -> str:
    """Stable id for a user-authored resolution claim (mirrors agentic_write)."""
    import hashlib

    digest = hashlib.sha1(
        f"{entity_id}\x00{predicate}\x00{obj}\x00user\x00{today}".encode("utf-8")
    ).hexdigest()[:8]
    return f"clm_{today}_user_{digest}"


async def _resolve_conflict(path, parsed, request, settings) -> tuple[str, bool, list[str]]:
    """Claim-aware conflict adjudication (§2.4).

    The chosen option decides what happens in the ``claims`` block FIRST — a
    winning claim is reinforced and every loser is bi-temporally closed, "both"
    keeps them all open with a context qualifier, and "neither"/free text writes
    a ``user_stated`` claim that closes them. Only then is a full sentence (not
    a raw button label — the old bug) fed to the LLM body rewrite.
    """
    from api.services.claim_reconciler import _close
    from api.services.claims import Claim, parse_claims, write_claims
    from api.services.conflict_resolver import _synthesize_entity_update

    fm_item = parsed.frontmatter
    entity_id = str(fm_item.get("entity_id", "") or "")
    predicate = str(fm_item.get("predicate", "") or "description")
    entity_path = settings.memory_path / "entities" / f"{entity_id}.md"
    options = inbox_questions.normalize_options(fm_item.get("options"))
    option_key = (request.option_key or "").strip()
    answer = (request.answer or "").strip()
    today = str(date.today())
    extra_lines: list[str] = []

    if not entity_path.exists():
        # Nothing to write into; clear the question rather than stranding it.
        path.unlink()
        return entity_id, False, extra_lines

    entity = markdown_parser.parse(entity_path)
    fm = entity.frontmatter
    name = str(fm.get("name", entity_id) or entity_id)
    verb = predicate.replace("-", " ")

    try:
        claim_list = parse_claims(entity.body, strict=True)
    except Exception:
        # A corrupt claims block must never be silently overwritten.
        claim_list = None

    by_id = {c.id: c for c in (claim_list or [])}
    option_claims = [
        by_id[str(o["claim_id"])]
        for o in options
        if o.get("claim_id") and str(o["claim_id"]) in by_id
    ]
    chosen = next((o for o in options if str(o.get("key")) == option_key), None)

    sentence = answer or ""

    if claim_list is not None:
        if chosen is not None and chosen.get("claim_id") and option_key not in ("both", "neither"):
            winner = by_id[str(chosen["claim_id"])]
            winner.confidence = max(winner.confidence, 0.9)
            for loser in option_claims:
                if loser.id != winner.id and loser.valid_to is None:
                    _close(loser, by=winner)
                    extra_lines.append(
                        f"entities/{entity_id}.md: updated "
                        f"(source: {path.stem}, trigger: inbox/conflict/resolved)"
                    )
            sentence = f"{name} {verb} {chosen['label']} (confirmed by user on {today})."

        elif option_key == "both":
            labels = []
            for claim in option_claims:
                if claim.context == "general":
                    claim.context = f"as of {claim.valid_from or today}"
                labels.append(claim.object)
            sentence = (
                f"Both are true: {' and '.join(labels)} (confirmed by user on {today})."
                if labels else sentence
            )

        else:
            # `neither`, or free text with no option key.
            if answer:
                new_claim = Claim(
                    id=_user_claim_id(entity_id, predicate, answer, today),
                    text=f"{name} {verb} {answer}.",
                    subject=entity_id,
                    predicate=predicate,
                    object=answer,
                    # Keep the SAME belief slot (observer) as the claims being
                    # replaced so future reconciliation sees one lineage.
                    observer=option_claims[0].observer if option_claims else "rodrigo",
                    context=option_claims[0].context if option_claims else "general",
                    source_trust="user_stated",
                    origin="clarification",
                    authored_by="user",
                    confidence=0.95,
                    valid_from=today,
                    recorded_at=today,
                )
                for loser in option_claims:
                    if loser.valid_to is None:
                        _close(loser, by=new_claim)
                claim_list.append(new_claim)
                sentence = f"{name} {verb} {answer} (stated by user on {today})."
            else:
                for loser in option_claims:
                    if loser.valid_to is None:
                        loser.valid_to = today
                sentence = (
                    f"None of the previously recorded values for "
                    f"'{verb}' are current as of {today}."
                )

        entity.body = write_claims(entity.body, claim_list)

    new_body = None
    if sentence:
        try:
            new_body = await _synthesize_entity_update(
                entity_name=name,
                entity_type=fm.get("type", "concept"),
                existing_body=entity.body,
                new_description=sentence,
                new_history_entries=[],
                source_reference_date=today,
                settings=settings,
            )
        except Exception:
            new_body = None
        if not new_body:
            # Safe fallback: dedup guard instead of blind append.
            new_body = (
                entity.body.rstrip() + f"\n\n{sentence}"
                if sentence not in entity.body
                else entity.body
            )

    if claim_list is not None and new_body is not None:
        # The synthesizer only ever returns prose; re-attach the machine layer
        # so an LLM rewrite can never drop the claims block.
        new_body = write_claims(new_body, claim_list)

    fm["last_referenced"] = today
    fm["version"] = int(fm.get("version", 1) or 1) + 1
    markdown_parser.write(entity_path, fm, new_body or entity.body)

    path.unlink()
    return entity_id, False, extra_lines
```

- [ ] **Step 6: Run test to verify it passes**

Run: `api/.venv/bin/python -m pytest api/tests/test_inbox_resolve_claims.py -q`
Expected: PASS (8 tests)

- [ ] **Step 7: Run the suite**

Run: `api/.venv/bin/python -m pytest api/tests -q`
Expected: PASS (`test_merge_direction_and_location.py` still passes — the clarification path returns a 2-tuple as before).

- [ ] **Step 8: Commit**

```bash
git add api/services/inbox_service.py api/services/git_service.py api/tests/test_inbox_resolve_claims.py
git commit -m "$(cat <<'EOF'
feat(inbox): claim-aware conflict resolution + defer action (G60)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

### Task 7: Fact sources (G61) — `sources:` frontmatter, CRUD endpoints, and the conflict `hint`

**Files:**
- Create: `api/services/fact_sources.py` — **not** `entity_sources.py`, which already exists and means episode→conversation provenance.
- Modify: `api/models/schemas.py` (`EntitySource`, `EntitySourceCreate`, `EntitySourceList`)
- Modify: `api/routers/entities.py` (3 endpoints)
- Modify: `api/services/inbox_generator.py` (`hint` on generated conflicts)
- Modify: `api/services/agentic_write.py` (`write_claim(..., sources=[...])`)
- Test: `api/tests/test_fact_sources.py`

**Interfaces:**
- Produces:
  - `fact_sources.infer_kind(ref: str) -> str` — `"url" | "path" | "note"`
  - `fact_sources.list_sources(memory_path: Path, entity_id: str) -> list[dict]`
  - `fact_sources.add_source(memory_path, entity_id, ref, *, kind=None, predicate=None, added_by="user", added_at=None) -> dict`
  - `fact_sources.delete_source(memory_path, entity_id, index: int) -> bool`
  - `fact_sources.hint_for(memory_path, entity_id, predicate) -> str | None`
  - `schemas.EntitySource(ref, kind, predicate, added_by, added_at)`, `EntitySourceCreate(ref, kind, predicate)`, `EntitySourceList(entity_id, sources)`
  - `agentic_write.write_claim(..., sources: list[str] | None = None)`

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_fact_sources.py`:

```python
"""G61 — `sources:` frontmatter (where to look a fact up), minimal slice."""

from __future__ import annotations

from pathlib import Path

from api.services import fact_sources, markdown_parser


def _entity(tmp_path: Path, fm_extra: dict | None = None) -> Path:
    ents = tmp_path / "entities"
    ents.mkdir(parents=True, exist_ok=True)
    fm = {"name": "Rodrigo", "type": "person", "status": "active", "confidence": 0.8,
          "created": "2026-01-01", "last_referenced": "2026-08-30", "decay_rate": 0.05,
          "source_episodes": [], "tags": [], "related": [], "version": 1}
    fm.update(fm_extra or {})
    markdown_parser.write(ents / "rodrigo.md", fm, "Body.")
    return tmp_path


def test_infer_kind():
    assert fact_sources.infer_kind("https://www.linkedin.com/in/rodrigo") == "url"
    assert fact_sources.infer_kind("http://example.com") == "url"
    assert fact_sources.infer_kind("/Users/rodrigo/cv.pdf") == "path"
    assert fact_sources.infer_kind("~/Documents/cv.pdf") == "path"
    assert fact_sources.infer_kind("Ask me — I always announce a job change") == "note"
    assert fact_sources.infer_kind("") == "note"


def test_add_list_and_delete_round_trip(tmp_path):
    memory = _entity(tmp_path)

    added = fact_sources.add_source(
        memory, "rodrigo", "https://www.linkedin.com/in/rodrigo",
        predicate="works-at", added_by="user", added_at="2026-08-30",
    )
    assert added == {
        "ref": "https://www.linkedin.com/in/rodrigo",
        "kind": "url",
        "predicate": "works-at",
        "added_by": "user",
        "added_at": "2026-08-30",
    }

    fact_sources.add_source(
        memory, "rodrigo", "Ask me — I announce job changes",
        added_by="gpt-5.4-mini", added_at="2026-08-30",
    )

    listed = fact_sources.list_sources(memory, "rodrigo")
    assert [s["kind"] for s in listed] == ["url", "note"]
    assert listed[1]["added_by"] == "gpt-5.4-mini"
    assert "predicate" not in listed[1]

    assert fact_sources.delete_source(memory, "rodrigo", 0) is True
    assert [s["kind"] for s in fact_sources.list_sources(memory, "rodrigo")] == ["note"]
    assert fact_sources.delete_source(memory, "rodrigo", 7) is False


def test_add_is_idempotent_on_an_identical_ref(tmp_path):
    memory = _entity(tmp_path)
    fact_sources.add_source(memory, "rodrigo", "https://example.com", added_at="2026-08-30")
    fact_sources.add_source(memory, "rodrigo", "https://example.com", added_at="2026-08-31")
    assert len(fact_sources.list_sources(memory, "rodrigo")) == 1


def test_empty_key_is_never_written(tmp_path):
    memory = _entity(tmp_path)
    fact_sources.add_source(memory, "rodrigo", "  ", added_at="2026-08-30")
    fm = markdown_parser.parse(memory / "entities" / "rodrigo.md").frontmatter
    assert "sources" not in fm


def test_hint_for_prefers_a_predicate_match_then_any_url(tmp_path):
    memory = _entity(tmp_path, {"sources": [
        {"ref": "https://generic.example", "kind": "url"},
        {"ref": "https://linkedin.example/rodrigo", "kind": "url", "predicate": "works-at"},
        {"ref": "just a note", "kind": "note"},
    ]})

    hint = fact_sources.hint_for(memory, "rodrigo", "works-at")
    assert hint == "You said https://linkedin.example/rodrigo is where to check this"

    # No predicate match -> the first url-kind source
    assert fact_sources.hint_for(memory, "rodrigo", "uses") == (
        "You said https://generic.example is where to check this"
    )


def test_hint_for_returns_none_without_sources(tmp_path):
    memory = _entity(tmp_path)
    assert fact_sources.hint_for(memory, "rodrigo", "works-at") is None
    assert fact_sources.hint_for(memory, "nobody", "works-at") is None


def test_hint_for_ignores_note_only_sources_when_no_predicate_matches(tmp_path):
    memory = _entity(tmp_path, {"sources": [{"ref": "ask me", "kind": "note"}]})
    assert fact_sources.hint_for(memory, "rodrigo", "works-at") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_fact_sources.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.services.fact_sources'`

- [ ] **Step 3: Write `api/services/fact_sources.py`**

```python
"""G61 — the entity ``sources:`` key: *where to look a fact up*.

Distinct from two neighbours it is easy to confuse:

- ``source_episodes`` (frontmatter) is **provenance** — where a belief CAME from.
- ``api/services/entity_sources.py`` resolves those episodes back to whole
  conversations. Different concept, different module; this one is ``fact_sources``.
- The body's ``## Links`` section is a loose bookmark list.

A *source* is a cheat-sheet for REFRESHING a specific fact: a URL, a local path,
or a plain-English instruction ("ask me — I announce job changes"). Stored as::

    sources:
      - ref: https://www.linkedin.com/in/rodrigo
        kind: url              # url | path | note
        predicate: works-at    # optional — which fact this refreshes
        added_by: user         # model id, or "user"
        added_at: '2026-08-30'

This slice never FETCHES anything (that is the G61 follow-up); it stores, lists,
deletes, and produces the conflict-card ``hint``.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from api.services import markdown_parser

KIND_URL = "url"
KIND_PATH = "path"
KIND_NOTE = "note"


def infer_kind(ref: str) -> str:
    """``http(s)://`` -> url; a leading ``/`` or ``~`` -> path; else note."""
    text = (ref or "").strip()
    if text.startswith(("http://", "https://")):
        return KIND_URL
    if text.startswith(("/", "~")):
        return KIND_PATH
    return KIND_NOTE


def _entity_path(memory_path: Path, entity_id: str) -> Path:
    return Path(memory_path) / "entities" / f"{entity_id}.md"


def list_sources(memory_path: Path, entity_id: str) -> list[dict]:
    """The entity's declared sources, in file order. ``[]`` when absent."""
    path = _entity_path(memory_path, entity_id)
    if not path.exists():
        return []
    try:
        fm = markdown_parser.parse(path).frontmatter
    except Exception:
        return []
    raw = fm.get("sources") or []
    return [dict(s) for s in raw if isinstance(s, dict) and s.get("ref")]


def add_source(
    memory_path: Path,
    entity_id: str,
    ref: str,
    *,
    kind: str | None = None,
    predicate: str | None = None,
    added_by: str = "user",
    added_at: str | None = None,
) -> dict | None:
    """Append one source to the entity's ``sources:`` key. Idempotent on ``ref``.

    Returns the stored dict, or ``None`` when the ref is blank or the entity
    does not exist. Every other frontmatter key and the body are untouched.
    """
    text = (ref or "").strip()
    if not text:
        return None
    path = _entity_path(memory_path, entity_id)
    if not path.exists():
        return None

    parsed = markdown_parser.parse(path)
    fm = parsed.frontmatter
    existing = [s for s in (fm.get("sources") or []) if isinstance(s, dict)]
    for source in existing:
        if str(source.get("ref", "")).strip() == text:
            return dict(source)

    entry: dict = {
        "ref": text,
        "kind": (kind or infer_kind(text)),
        "added_by": added_by or "user",
        "added_at": added_at or str(date.today()),
    }
    if predicate:
        # `predicate` sits between kind and added_by for readability.
        entry = {
            "ref": entry["ref"],
            "kind": entry["kind"],
            "predicate": predicate,
            "added_by": entry["added_by"],
            "added_at": entry["added_at"],
        }

    fm["sources"] = existing + [entry]
    markdown_parser.write(path, fm, parsed.body)
    return entry


def delete_source(memory_path: Path, entity_id: str, index: int) -> bool:
    """Remove the source at ``index``. Returns whether anything was removed.

    Removing the last source drops the ``sources:`` key entirely, so an entity
    that never had one stays byte-identical.
    """
    path = _entity_path(memory_path, entity_id)
    if not path.exists():
        return False
    parsed = markdown_parser.parse(path)
    fm = parsed.frontmatter
    existing = [s for s in (fm.get("sources") or []) if isinstance(s, dict)]
    if index < 0 or index >= len(existing):
        return False
    existing.pop(index)
    if existing:
        fm["sources"] = existing
    else:
        fm.pop("sources", None)
    markdown_parser.write(path, fm, parsed.body)
    return True


def hint_for(memory_path: Path, entity_id: str, predicate: str | None) -> str | None:
    """The conflict-card hint: which source refreshes this fact (§2.5).

    Prefers a source whose ``predicate`` matches; otherwise the first ``url``
    source. ``note``-only sources produce no hint — there is nothing to open.
    """
    sources = list_sources(memory_path, entity_id)
    if not sources:
        return None
    want = (predicate or "").strip().lower()
    match = next(
        (s for s in sources if str(s.get("predicate", "") or "").strip().lower() == want and want),
        None,
    )
    if match is None:
        match = next((s for s in sources if s.get("kind") == KIND_URL), None)
    if match is None:
        return None
    return f"You said {match['ref']} is where to check this"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `api/.venv/bin/python -m pytest api/tests/test_fact_sources.py -q`
Expected: PASS (7 tests)

- [ ] **Step 5: Write the failing test for the endpoints and the conflict hint**

Append to `api/tests/test_fact_sources.py`:

```python
import asyncio
import subprocess

import pytest
from fastapi import HTTPException

from api.models.schemas import EntitySourceCreate
from api.routers import entities as entities_router
from api.services import inbox_generator


def run(coro):
    return asyncio.run(coro)


class _FakeSettings:
    def __init__(self, memory_path: Path):
        self.memory_path = memory_path


def _git_memory(tmp_path: Path) -> Path:
    repo = tmp_path / "memory"
    _entity(repo)
    subprocess.run(["git", "init", "-q"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.email", "t@c.local"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=str(repo), check=True)
    subprocess.run(["git", "add", "-A"], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=str(repo), check=True)
    return repo


def test_sources_endpoints_round_trip_and_commit(tmp_path):
    repo = _git_memory(tmp_path)
    settings = _FakeSettings(repo)

    empty = run(entities_router.get_entity_sources("rodrigo", settings=settings))
    assert empty.entity_id == "rodrigo" and empty.sources == []

    created = run(entities_router.add_entity_source(
        "rodrigo",
        EntitySourceCreate(ref="https://linkedin.example/rodrigo", predicate="works-at"),
        settings=settings,
    ))
    assert [s.kind for s in created.sources] == ["url"]
    assert created.sources[0].predicate == "works-at"
    assert created.sources[0].added_by == "user"

    log = subprocess.run(
        ["git", "log", "--format=%s%n%b"], cwd=str(repo),
        check=True, capture_output=True, text=True,
    ).stdout
    assert "user/companion_app" in log
    assert "Cicada-Author: user" in log

    after = run(entities_router.delete_entity_source("rodrigo", 0, settings=settings))
    assert after.sources == []


def test_sources_endpoints_404_on_a_missing_entity(tmp_path):
    repo = _git_memory(tmp_path)
    with pytest.raises(HTTPException) as exc:
        run(entities_router.get_entity_sources("nobody", settings=_FakeSettings(repo)))
    assert exc.value.status_code == 404


def test_delete_out_of_range_is_404(tmp_path):
    repo = _git_memory(tmp_path)
    with pytest.raises(HTTPException) as exc:
        run(entities_router.delete_entity_source("rodrigo", 3, settings=_FakeSettings(repo)))
    assert exc.value.status_code == 404


def test_generated_conflict_carries_the_source_hint(tmp_path):
    memory = tmp_path / "memory"
    _entity(memory, {"sources": [
        {"ref": "https://linkedin.example/rodrigo", "kind": "url", "predicate": "works-at"},
    ]})
    (memory / "inbox").mkdir(parents=True)

    inbox_generator.write_claim_nudges([{
        "id": "rodrigo",
        "action": "conflict_nudge",
        "entity": {"name": "Rodrigo"},
        "predicate": "works-at",
        "question": "Where does Rodrigo work now?",
        "allow_other": True,
        "allow_defer": True,
        "conflict_context": "conflict",
        "options": [{"key": "a", "label": "mongodb", "claim_id": "clm_a"}],
        "claim_id": "clm_a",
    }], memory)

    fm = markdown_parser.parse(memory / "inbox" / "inbox-001.md").frontmatter
    assert fm["hint"] == "You said https://linkedin.example/rodrigo is where to check this"
```

- [ ] **Step 6: Run test to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_fact_sources.py -q`
Expected: FAIL — `cannot import name 'EntitySourceCreate'`

- [ ] **Step 7: Add the schemas**

In `api/models/schemas.py`, after `class LocationListing` (around line 204):

```python
# --- Fact sources (G61 — "where to look this up") ---


class EntitySource(CamelModel):
    """One declared refresh source on an entity page's ``sources:`` key."""

    ref: str
    kind: str = "note"          # url | path | note
    predicate: Optional[str] = None
    added_by: str = "user"      # model id, or "user"
    added_at: str = ""


class EntitySourceCreate(CamelModel):
    """``POST /entities/{id}/sources`` body. ``kind`` is inferred when omitted."""

    ref: str
    kind: Optional[str] = None
    predicate: Optional[str] = None


class EntitySourceList(CamelModel):
    entity_id: str
    sources: list[EntitySource] = []
```

- [ ] **Step 8: Add the three endpoints**

In `api/routers/entities.py`, add `EntitySource, EntitySourceCreate, EntitySourceList` to the `from api.models.schemas import (...)` block and `fact_sources` to `from api.services import ...`. Then append after `update_entity_repos`:

```python
def _sources_payload(memory_path: Path, entity_id: str) -> EntitySourceList:
    return EntitySourceList(
        entity_id=entity_id,
        sources=[EntitySource(**s) for s in fact_sources.list_sources(memory_path, entity_id)],
    )


async def _commit_sources(memory_path: Path, entity_id: str, verb: str) -> None:
    message = git_service.build_commit_message(
        f"{verb} fact source {date.today().isoformat()}",
        [f"entities/{entity_id}.md: updated (trigger: user/companion_app)"],
        authors=["user"],
    )
    await git_service.commit_changes(memory_path, message)


@router.get("/entities/{entity_id}/sources", response_model=EntitySourceList)
async def get_entity_sources(
    entity_id: str,
    settings: Settings = Depends(get_settings),
):
    """List an entity's declared refresh sources (G61).

    404 only when the entity file itself is missing; an entity with no
    ``sources:`` key returns ``sources: []`` at 200.
    """
    entity_path = settings.memory_path / "entities" / f"{entity_id}.md"
    if not entity_path.exists():
        raise HTTPException(404, f"Entity {entity_id} not found")
    return _sources_payload(settings.memory_path, entity_id)


@router.post("/entities/{entity_id}/sources", response_model=EntitySourceList)
async def add_entity_source(
    entity_id: str,
    request: EntitySourceCreate,
    settings: Settings = Depends(get_settings),
):
    """Append one source. ``kind`` is inferred from ``ref`` when not supplied."""
    entity_path = settings.memory_path / "entities" / f"{entity_id}.md"
    if not entity_path.exists():
        raise HTTPException(404, f"Entity {entity_id} not found")
    if not (request.ref or "").strip():
        raise HTTPException(400, "ref is required")

    fact_sources.add_source(
        settings.memory_path,
        entity_id,
        request.ref,
        kind=request.kind,
        predicate=request.predicate,
        added_by="user",
    )
    await _commit_sources(settings.memory_path, entity_id, "Add")
    return _sources_payload(settings.memory_path, entity_id)


@router.delete("/entities/{entity_id}/sources/{index}", response_model=EntitySourceList)
async def delete_entity_source(
    entity_id: str,
    index: int,
    settings: Settings = Depends(get_settings),
):
    """Remove the source at ``index`` (0-based, file order)."""
    entity_path = settings.memory_path / "entities" / f"{entity_id}.md"
    if not entity_path.exists():
        raise HTTPException(404, f"Entity {entity_id} not found")
    if not fact_sources.delete_source(settings.memory_path, entity_id, index):
        raise HTTPException(404, f"No source at index {index} on {entity_id}")
    await _commit_sources(settings.memory_path, entity_id, "Remove")
    return _sources_payload(settings.memory_path, entity_id)
```

- [ ] **Step 9: Add the hint to generated conflicts**

In `api/services/inbox_generator.py`, inside `write_claim_nudges`, right after the `find_open`/merge short-circuit added in Task 2:

```python
        hint = None
        if action == "conflict_nudge":
            try:
                from api.services import fact_sources

                hint = fact_sources.hint_for(memory_path, entity_id, predicate)
            except Exception:
                hint = None
```

and add `"hint": hint,` to the frontmatter dict.

- [ ] **Step 10: Add `sources=` to `agentic_write.write_claim`**

In `api/services/agentic_write.py`, add the parameter to the signature (after `force_new_entity: bool = False`):

```python
    sources: list[str] | None = None,
```

and, just before the success `return` (after the claim has been written and `entity_id` is known), insert:

```python
    # G61 — "here's where to check this fact". Attributed to the same author
    # the claim carries, so the entity page records WHO said to look there.
    if sources:
        from api.services import fact_sources

        for ref in sources:
            fact_sources.add_source(
                memory_path,
                entity_id,
                ref,
                predicate=predicate_slug,
                added_by=(claim.authored_by or "agent"),
            )
```

Adjust `predicate_slug` / `claim` to whatever the local variable names are at that point — run `grep -n "predicate_slug\|authored_by\|entity_id =" api/services/agentic_write.py` first and use the existing names.

- [ ] **Step 11: Run the tests**

Run: `api/.venv/bin/python -m pytest api/tests/test_fact_sources.py api/tests/test_agentic_write.py -q`
Expected: PASS

Run: `api/.venv/bin/python -m pytest api/tests -q`
Expected: PASS

- [ ] **Step 12: Commit**

```bash
git add api/services/fact_sources.py api/models/schemas.py api/routers/entities.py api/services/inbox_generator.py api/services/agentic_write.py api/tests/test_fact_sources.py
git commit -m "$(cat <<'EOF'
feat(entities): fact sources — sources: frontmatter, CRUD endpoints, conflict hint (G61)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

### Task 8: MCP surface — question rendering + `cicada_resolve_inbox`

**Files:**
- Modify: `mcp/server.py` (`TOOLS` list, `handle_tool`, `_format_inbox_blurb`, `handle_check_nudges`, `handle_write_claim`, new `handle_resolve_inbox`)
- Test: `api/tests/test_mcp_inbox_questions.py`

**Interfaces:**
- Consumes: `mcp.server._backend_headers()` (line 399), `mcp.server.parse_frontmatter(content) -> (dict, str)` (line 561), `mcp.server._inbox_files(memory_path)` (line 1338), `inbox_questions.is_deferred/normalize_options/humanize_age` (Tasks 1 & 5).
- Produces:
  - `mcp.server.render_question(fm: dict, body: str, today: str) -> str` — the shared question renderer.
  - `mcp.server.handle_resolve_inbox(item_id, option_key, answer, defer, remind_days) -> str`
  - A `cicada_resolve_inbox` entry in `TOOLS` and a branch in `handle_tool`.

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_mcp_inbox_questions.py`:

```python
"""G60 §2.7 — the MCP surface renders question objects and can resolve them."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def server():
    spec = importlib.util.spec_from_file_location(
        "cicada_mcp_server", REPO_ROOT / "mcp" / "server.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["cicada_mcp_server"] = module
    spec.loader.exec_module(module)
    return module


QUESTION_FM = {
    "kind": "conflict",
    "status": "pending",
    "entity_id": "rodrigo",
    "entity_name": "Rodrigo",
    "title": "Where does Rodrigo work now?",
    "question": "Where does Rodrigo work now?",
    "predicate": "works-at",
    "allow_other": True,
    "allow_defer": True,
    "created_date": "2026-06-18",
    "hint": "You said https://linkedin.example/rodrigo is where to check this",
    "options": [
        {"key": "a", "label": "MongoDB", "observed_at": "2026-02-18",
         "last_referenced": "2026-02-18"},
        {"key": "b", "label": "Supahost", "observed_at": "2026-08-25",
         "last_referenced": "2026-08-25"},
        {"key": "both", "label": "Both are true (different contexts)"},
    ],
}


def test_render_question_lists_keyed_options_with_ages(server):
    out = server.render_question(QUESTION_FM, "Conflicting beliefs.", today="2026-08-30")
    assert "Where does Rodrigo work now?" in out
    assert "a) MongoDB — 6 months ago" in out
    assert "b) Supahost — 5 days ago" in out
    assert "both) Both are true (different contexts)" in out
    assert "Other / Later" in out
    assert "linkedin.example" in out


def test_render_question_falls_back_to_the_body(server):
    fm = {"kind": "clarification", "entity_name": "Franco",
          "uncertainty_type": "who is this", "options": []}
    out = server.render_question(fm, "Who is Franco?", today="2026-08-30")
    assert "Who is Franco?" in out
    assert "Other / Later" not in out  # allow_other/allow_defer are off


def test_check_nudges_hides_deferred_items(server, tmp_path, monkeypatch):
    from api.services import markdown_parser

    memory = tmp_path / "memory"
    (memory / "inbox").mkdir(parents=True)
    markdown_parser.write(memory / "inbox" / "inbox-001.md", dict(QUESTION_FM), "ctx")
    deferred = dict(QUESTION_FM)
    deferred["predicate"] = "uses"
    deferred["remind_after"] = "2099-01-01"
    markdown_parser.write(memory / "inbox" / "inbox-002.md", deferred, "ctx")

    monkeypatch.setattr(server, "get_memory_path", lambda: memory)
    out = server.handle_check_nudges(None)
    assert "inbox-001" in out
    assert "inbox-002" not in out
    assert "Found 1 pending inbox item" in out


def test_resolve_inbox_posts_the_option_key(server, monkeypatch):
    seen = {}

    def fake_post(path: str, payload: dict) -> dict:
        seen["path"] = path
        seen["payload"] = payload
        return {"status": "resolved", "id": "inbox-001"}

    monkeypatch.setattr(server, "_backend_post", fake_post)
    out = server.handle_resolve_inbox("inbox-001", "b", None, False, None)

    assert seen["path"] == "/inbox/inbox-001/resolve"
    assert seen["payload"] == {"action": "resolve", "optionKey": "b"}
    assert "resolved" in out


def test_resolve_inbox_defer_sends_remind_days(server, monkeypatch):
    seen = {}
    monkeypatch.setattr(
        server, "_backend_post",
        lambda path, payload: seen.update(payload) or {"status": "deferred", "remindAfter": "2026-09-29"},
    )
    out = server.handle_resolve_inbox("inbox-001", None, None, True, 30)
    assert seen == {"action": "defer", "remindDays": 30}
    assert "2026-09-29" in out


def test_resolve_inbox_free_text(server, monkeypatch):
    seen = {}
    monkeypatch.setattr(
        server, "_backend_post",
        lambda path, payload: seen.update(payload) or {"status": "resolved"},
    )
    server.handle_resolve_inbox("inbox-001", "neither", "Acme Robotics", False, None)
    assert seen == {"action": "resolve", "optionKey": "neither", "answer": "Acme Robotics"}


def test_resolve_inbox_tool_is_registered(server):
    names = {t["name"] for t in server.TOOLS}
    assert "cicada_resolve_inbox" in names
    tool = next(t for t in server.TOOLS if t["name"] == "cicada_resolve_inbox")
    assert tool["inputSchema"]["required"] == ["id"]
    assert set(tool["inputSchema"]["properties"]) == {
        "id", "option_key", "answer", "defer", "remind_days",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_mcp_inbox_questions.py -q`
Expected: FAIL — `module 'cicada_mcp_server' has no attribute 'render_question'`

- [ ] **Step 3: Add `render_question` and `_backend_post` to `mcp/server.py`**

Insert after `_format_inbox_blurb` (around line 1360):

```python
def render_question(fm: dict, body: str, today: str | None = None) -> str:
    """Render an inbox item's question object for an agent to ask in-flow (§2.7).

    Shape:

        Where does Rodrigo work now?
          a) MongoDB — 6 months ago
          b) Supahost — 5 days ago
          both) Both are true (different contexts)
          Other / Later — reply with any other answer, or ask to be reminded later
          Source to check: https://…

    Falls back to the item body when there is no question, so legacy items still
    render something an agent can read out.
    """
    from datetime import date as _date

    from api.services import inbox_questions

    now = today or str(_date.today())
    lines = [str(fm.get("question") or fm.get("title") or "").strip() or (body or "").strip()]

    for option in inbox_questions.normalize_options(fm.get("options")):
        age = inbox_questions.humanize_age(
            option.get("last_referenced") or option.get("observed_at"), now
        )
        suffix = f" — {age}" if age != "unknown" else ""
        lines.append(f"  {option.get('key')}) {option.get('label')}{suffix}")

    if fm.get("allow_other") or fm.get("allow_defer"):
        lines.append(
            "  Other / Later — reply with any other answer, "
            "or ask to be reminded later"
        )
    if fm.get("hint"):
        lines.append(f"  Source to check: {fm['hint']}")
    return "\n".join(line for line in lines if line.strip())


def _backend_post(path: str, payload: dict) -> dict:
    """POST JSON to the local backend and return the decoded response."""
    import urllib.request

    req = urllib.request.Request(
        f"http://127.0.0.1:8000{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers=_backend_headers(),
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read().decode("utf-8"))


def handle_resolve_inbox(
    item_id: str,
    option_key: str | None,
    answer: str | None,
    defer: bool,
    remind_days,
) -> str:
    """Resolve (or defer) one inbox item through the backend (§2.7)."""
    item_id = (item_id or "").strip()
    if not item_id:
        return "Error: id is required (e.g. 'inbox-001')."

    if defer:
        payload: dict = {"action": "defer"}
        if remind_days is not None:
            payload["remindDays"] = int(remind_days)
    else:
        payload = {"action": "resolve"}
        if option_key:
            payload["optionKey"] = str(option_key)
        if answer:
            payload["answer"] = str(answer)
        if not option_key and not answer:
            return "Error: pass option_key, answer, or defer=true."

    try:
        result = _backend_post(f"/inbox/{item_id}/resolve", payload)
    except Exception as e:
        return (
            f"Could not resolve {item_id} ({type(e).__name__}: {e}). "
            "Is the Cicada backend running on 127.0.0.1:8000?"
        )

    status = result.get("status", "unknown")
    if status == "deferred":
        return f"Deferred {item_id} until {result.get('remindAfter', 'later')}."
    return f"Inbox item {item_id}: {status}."
```

- [ ] **Step 4: Use the renderer in the two proactive surfaces**

Replace `_format_inbox_blurb`'s conflict/decay tail so a question object wins over the flat title:

```python
def _format_inbox_blurb(fm: dict, body: str) -> str:
    kind = str(fm.get("kind", fm.get("type", "")) or "")
    ename = fm.get("entity_name", fm.get("entity_mention", "Unknown"))
    if fm.get("question"):
        return f"- [{kind or 'item'}] **{ename}**\n" + render_question(fm, body)
    if kind in ("clarification", "merge_suggestion"):
        utype = fm.get("uncertainty_type", "unknown")
        suggestion = fm.get("suggested_classification", "unknown")
        return f"- **{ename}** (uncertain: {utype}, suggested: {suggestion})"
    # decay/conflict (and legacy nudges where kind lived in "type")
    if not kind and fm.get("uncertainty_type"):
        utype = fm.get("uncertainty_type", "unknown")
        suggestion = fm.get("suggested_classification", "unknown")
        return f"- **{ename}** (uncertain: {utype}, suggested: {suggestion})"
    title = fm.get("title", fm.get("short_description", ""))
    label = kind or "item"
    return f"- [{label}] **{ename}** — {title}"
```

In `handle_check_nudges`, skip deferred items and render questions. Replace the loop body's tail (everything from `kind = str(fm.get("kind", ...` to the `results.append(...)` calls):

```python
        from api.services import inbox_questions

        if inbox_questions.is_deferred(fm, str(date.today())):
            continue

        kind = str(fm.get("kind", fm.get("type", "")) or "")
        ename = fm.get("entity_name", fm.get("entity_mention", "Unknown"))
        if fm.get("question"):
            results.append(
                f"**{(kind or 'Item').title()}** `{filepath.stem}`: {ename}\n"
                + render_question(fm, body)
                + f"\n  Resolve with cicada_resolve_inbox(id=\"{filepath.stem}\", option_key=…)"
            )
        elif kind in ("clarification", "merge_suggestion") or (
            not kind and fm.get("uncertainty_type")
        ):
            results.append(
                f"**Clarification** `{filepath.stem}`: {ename} — "
                f"{fm.get('uncertainty_type', '')}\n  {body[:200]}"
            )
        else:
            title = fm.get("title", fm.get("short_description", ""))
            results.append(
                f"**{kind or 'Item'}** `{filepath.stem}`: {ename} — {title}\n  {body[:200]}"
            )
```

Add `from datetime import date` to `mcp/server.py`'s top-level imports if it is not already there (check with `grep -n "^from datetime" mcp/server.py`).

- [ ] **Step 5: Register the tool**

Append to the `TOOLS` list in `mcp/server.py` (before the closing `]`):

```python
    {
        "name": "cicada_resolve_inbox",
        "description": "Answer a pending Cicada inbox question on the user's behalf, after they told you the answer in conversation. Use ONLY with an answer the user actually gave — never guess. Pass the option_key shown by cicada_check_nudges (e.g. 'a', 'b', 'both', 'neither'), or `answer` with free text when none of the options is right (this records a user-stated, trust-protected claim and closes the competing ones), or defer=true when the user says they're not sure and want to be asked later.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "The inbox item id, e.g. 'inbox-001' (shown by cicada_check_nudges).",
                },
                "option_key": {
                    "type": "string",
                    "description": "The key of the option the user chose ('a', 'b', 'both', 'neither', …).",
                },
                "answer": {
                    "type": "string",
                    "description": "Free-text answer, when none of the options is correct. Recorded as a user-stated claim.",
                },
                "defer": {
                    "type": "boolean",
                    "description": "True when the user wants to be asked again later. Default false.",
                },
                "remind_days": {
                    "type": "integer",
                    "description": "With defer=true: how many days out to ask again (default 30).",
                },
            },
            "required": ["id"],
        },
    },
```

and add the branch in `handle_tool`, before the `else: raise ValueError`:

```python
    elif name == "cicada_resolve_inbox":
        return handle_resolve_inbox(
            arguments.get("id", ""),
            arguments.get("option_key"),
            arguments.get("answer"),
            bool(arguments.get("defer", False)),
            arguments.get("remind_days"),
        )
```

- [ ] **Step 6: Add `sources` to `cicada_write_claim`**

In the `cicada_write_claim` tool schema's `properties`, add:

```python
                "sources": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional 'where to check this fact' references the user gave you — a URL, a file path, or a plain-English instruction ('ask me, I announce job changes'). Stored on the subject's entity page, attributed to you.",
                },
```

In `handle_tool`'s `cicada_write_claim` branch, pass `arguments.get("sources")` as a new last argument, and in `handle_write_claim` add the parameter `sources: list | None = None` and forward it: `sources=sources,` in the `agentic_write.write_claim(...)` call.

- [ ] **Step 7: Run the tests**

Run: `api/.venv/bin/python -m pytest api/tests/test_mcp_inbox_questions.py api/tests/test_mcp_tool_descriptions.py -q`
Expected: PASS

Run: `api/.venv/bin/python -m pytest api/tests -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add mcp/server.py api/tests/test_mcp_inbox_questions.py
git commit -m "$(cat <<'EOF'
feat(mcp): render inbox questions + cicada_resolve_inbox tool (G60)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

### Task 9: Swift models, view model, and the `InboxResolve` mutation

**Files:**
- Modify: `app/CicadaApp/Sources/CicadaApp/Models/InboxItem.swift`
- Modify: `app/CicadaApp/Sources/CicadaApp/Sync/Mutations.swift:50-75` (`InboxResolve`)
- Modify: `app/CicadaApp/Sources/CicadaApp/Sync/SyncAPI.swift:64-65` (protocol method)
- Modify: `app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift:935-947` and `:1480-1484`
- Modify: `app/CicadaApp/Sources/CicadaApp/ViewModels/InboxViewModel.swift` (`resolve`)
- Modify: `app/CicadaApp/Tests/CicadaAppTests/StoreTests.swift` (`FakeSyncAPI.resolveInbox`)
- Test: `app/CicadaApp/Tests/CicadaAppTests/InboxQuestionTests.swift`

**Interfaces:**
- Consumes: the wire shape from Task 1 (`question`, `options: [InboxOption]`, `allowOther`, `allowDefer`, `predicate`, `hint`, `remindAfter`, `updatedDate`; `InboxResolveRequest.optionKey`/`remindDays`).
- Produces:
  - `struct InboxOption: Codable, Identifiable, Hashable { key, label, description, claimId, observedAt, lastReferenced, ageDays }` with `var id: String { key }` and `var ageCapsule: String?` ("6 mo", "5 d", "2 y").
  - `InboxItem.options: [InboxOption]` (never optional), plus the new fields; the decoder accepts a legacy `[String]`.
  - `InboxResolve(id:action:answer:optionKey:remindDays:mergeTarget:mergeSurvivor:)`
  - `SyncAPI.resolveInbox(id:action:answer:optionKey:remindDays:mergeTarget:mergeSurvivor:)`
  - `InboxViewModel.resolve(id:action:answer:optionKey:remindDays:mergeTarget:mergeSurvivor:) async -> Bool`

- [ ] **Step 1: Write the failing tests**

Create `app/CicadaApp/Tests/CicadaAppTests/InboxQuestionTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// G60 — the question object on the wire, and the resolve mutation carrying
/// `optionKey` / `remindDays` through to the API.
@MainActor
final class InboxQuestionTests: XCTestCase {

    private func decode(_ json: String) throws -> InboxItem {
        try JSONDecoder().decode(InboxItem.self, from: Data(json.utf8))
    }

    // MARK: - Decoding

    func testDecodesTheNewOptionObjectShape() throws {
        let item = try decode("""
        {"id":"inbox-001","kind":"conflict","requiredInput":"choice",
         "title":"Where does Rodrigo work now?","body":"Conflicting beliefs.",
         "question":"Where does Rodrigo work now?","predicate":"works-at",
         "allowOther":true,"allowDefer":true,
         "hint":"You said https://x.example is where to check this",
         "remindAfter":null,"updatedDate":"2026-08-30",
         "options":[
           {"key":"a","label":"MongoDB","description":"6 months ago",
            "claimId":"clm_a","observedAt":"2026-02-18",
            "lastReferenced":"2026-02-18","ageDays":193},
           {"key":"both","label":"Both are true (different contexts)"}]}
        """)

        XCTAssertEqual(item.question, "Where does Rodrigo work now?")
        XCTAssertEqual(item.predicate, "works-at")
        XCTAssertTrue(item.allowOther)
        XCTAssertTrue(item.allowDefer)
        XCTAssertEqual(item.hint, "You said https://x.example is where to check this")
        XCTAssertNil(item.remindAfter)
        XCTAssertEqual(item.updatedDate, "2026-08-30")
        XCTAssertEqual(item.options.map(\.key), ["a", "both"])
        XCTAssertEqual(item.options[0].claimId, "clm_a")
        XCTAssertEqual(item.options[0].ageDays, 193)
        XCTAssertNil(item.options[1].claimId)
    }

    func testDecodesTheLegacyFlatStringOptions() throws {
        let item = try decode("""
        {"id":"inbox-009","kind":"conflict","requiredInput":"choice",
         "title":"Conflicting information","body":"ctx",
         "options":["mongodb","supahost","Both are true (different contexts)"]}
        """)

        XCTAssertEqual(item.options.map(\.key), ["0", "1", "2"])
        XCTAssertEqual(item.options.map(\.label),
                       ["mongodb", "supahost", "Both are true (different contexts)"])
        XCTAssertNil(item.question)
        XCTAssertFalse(item.allowOther)
        XCTAssertFalse(item.allowDefer)
    }

    func testDecodesWithNoOptionsAtAll() throws {
        let item = try decode("""
        {"id":"inbox-010","kind":"decay","requiredInput":"choice",
         "title":"No recent mentions","body":"ctx"}
        """)
        XCTAssertTrue(item.options.isEmpty)
    }

    func testQuestionTextFallsBackToTitleThenBody() throws {
        let withQuestion = try decode("""
        {"id":"a","kind":"conflict","requiredInput":"choice","title":"T","body":"B",
         "question":"Q?"}
        """)
        XCTAssertEqual(withQuestion.questionText, "Q?")

        let withoutQuestion = try decode("""
        {"id":"b","kind":"conflict","requiredInput":"choice","title":"T","body":"B"}
        """)
        XCTAssertEqual(withoutQuestion.questionText, "T")

        let titleless = try decode("""
        {"id":"c","kind":"conflict","requiredInput":"choice","title":"","body":"B"}
        """)
        XCTAssertEqual(titleless.questionText, "B")
    }

    func testAgeCapsuleIsShort() throws {
        func capsule(_ days: Int?) -> String? {
            InboxOption(key: "k", label: "L", description: nil, claimId: nil,
                        observedAt: nil, lastReferenced: nil, ageDays: days).ageCapsule
        }
        XCTAssertNil(capsule(nil))
        XCTAssertEqual(capsule(0), "today")
        XCTAssertEqual(capsule(5), "5 d")
        XCTAssertEqual(capsule(20), "3 wk")
        XCTAssertEqual(capsule(193), "6 mo")
        XCTAssertEqual(capsule(800), "2 y")
    }

    // MARK: - Mutation

    func testResolvePassesOptionKeyAndRemindDaysThrough() async throws {
        let api = FakeSyncAPI()
        let store = Store(cache: SnapshotCache(
            root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        ), api: api)
        api.replies[.inbox] = .notModified

        let vm = InboxViewModel(store: store)
        let ok = await vm.resolve(id: "inbox-001", action: "resolve", optionKey: "b")

        XCTAssertTrue(ok)
        XCTAssertTrue(api.writes.contains("resolveInbox:inbox-001:resolve:b:nil"))
    }

    func testDeferPassesRemindDaysAndHidesTheCard() async throws {
        let api = FakeSyncAPI()
        let store = Store(cache: SnapshotCache(
            root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        ), api: api)
        api.replies[.inbox] = .notModified

        let vm = InboxViewModel(store: store)
        let ok = await vm.resolve(id: "inbox-001", action: "defer", remindDays: 14)

        XCTAssertTrue(ok)
        XCTAssertTrue(api.writes.contains("resolveInbox:inbox-001:defer:nil:14"))
    }
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd app/CicadaApp && swift test --filter InboxQuestionTests`
Expected: FAIL to compile — `cannot find 'InboxOption' in scope`.

- [ ] **Step 3: Rewrite `Models/InboxItem.swift`**

Replace the `InboxItem` struct (keeping `InboxKind` and `RequiredInput` unchanged) with:

```swift
/// One answerable option on an inbox question. Matches `InboxOption` in
/// `api/models/schemas.py`. `ageDays` is derived server-side at read time.
struct InboxOption: Identifiable, Codable, Hashable {
    var key: String
    var label: String
    var description: String?
    var claimId: String?
    var observedAt: String?
    var lastReferenced: String?
    var ageDays: Int?

    var id: String { key }

    /// A trailing muted capsule: "today", "5 d", "3 wk", "6 mo", "2 y".
    /// `nil` when the option has no claim behind it (the synthetic rows).
    var ageCapsule: String? {
        guard let days = ageDays else { return nil }
        if days == 0 { return "today" }
        if days < 14 { return "\(days) d" }
        if days < 60 { return "\(Int((Double(days) / 7).rounded())) wk" }
        if days < 365 { return "\(Int((Double(days) / 30).rounded())) mo" }
        return "\(Int((Double(days) / 365).rounded())) y"
    }
}

/// One unified inbox item. Decodes the camelCase payload from `GET /inbox`
/// (`api/routers/inbox.py` → `InboxItem`). `options` decodes both the current
/// object form and the legacy flat `[String]`, so an item written before G60
/// still renders.
struct InboxItem: Identifiable, Codable {
    let id: String
    var kind: InboxKind
    var requiredInput: RequiredInput
    var status: String
    var priority: Double
    var entityId: String
    var entityName: String
    var title: String
    var body: String
    var options: [InboxOption]
    var createdDate: String
    // G60 question object
    var question: String?
    var allowOther: Bool
    var allowDefer: Bool
    var predicate: String?
    var hint: String?
    var remindAfter: String?
    var updatedDate: String?
    // clarification / merge extras
    var uncertaintyType: String?
    var suggestedClassification: String?
    var suggestedConfidence: Double?
    var mergeTargetHint: String?

    enum CodingKeys: String, CodingKey {
        case id, kind, requiredInput, status, priority
        case entityId, entityName, title, body, options, createdDate
        case question, allowOther, allowDefer, predicate, hint, remindAfter, updatedDate
        case uncertaintyType, suggestedClassification, suggestedConfidence, mergeTargetHint
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        kind = try c.decode(InboxKind.self, forKey: .kind)
        requiredInput = try c.decode(RequiredInput.self, forKey: .requiredInput)
        status = try c.decodeIfPresent(String.self, forKey: .status) ?? "pending"
        priority = try c.decodeIfPresent(Double.self, forKey: .priority) ?? 0
        entityId = try c.decodeIfPresent(String.self, forKey: .entityId) ?? ""
        entityName = try c.decodeIfPresent(String.self, forKey: .entityName) ?? ""
        title = try c.decode(String.self, forKey: .title)
        body = try c.decodeIfPresent(String.self, forKey: .body) ?? ""
        // Object form first; a server or cached payload from before G60 hands
        // back `["A","B"]`, which becomes positionally-keyed options.
        if let objects = try? c.decodeIfPresent([InboxOption].self, forKey: .options) {
            options = objects ?? []
        } else if let labels = try c.decodeIfPresent([String].self, forKey: .options) {
            options = labels.enumerated().map {
                InboxOption(key: "\($0.offset)", label: $0.element, description: nil,
                            claimId: nil, observedAt: nil, lastReferenced: nil, ageDays: nil)
            }
        } else {
            options = []
        }
        createdDate = try c.decodeIfPresent(String.self, forKey: .createdDate) ?? ""
        question = try c.decodeIfPresent(String.self, forKey: .question)
        allowOther = try c.decodeIfPresent(Bool.self, forKey: .allowOther) ?? false
        allowDefer = try c.decodeIfPresent(Bool.self, forKey: .allowDefer) ?? false
        predicate = try c.decodeIfPresent(String.self, forKey: .predicate)
        hint = try c.decodeIfPresent(String.self, forKey: .hint)
        remindAfter = try c.decodeIfPresent(String.self, forKey: .remindAfter)
        updatedDate = try c.decodeIfPresent(String.self, forKey: .updatedDate)
        uncertaintyType = try c.decodeIfPresent(String.self, forKey: .uncertaintyType)
        suggestedClassification = try c.decodeIfPresent(String.self, forKey: .suggestedClassification)
        suggestedConfidence = try c.decodeIfPresent(Double.self, forKey: .suggestedConfidence)
        mergeTargetHint = try c.decodeIfPresent(String.self, forKey: .mergeTargetHint)
    }

    /// Display name for the card header, falling back to the title when no
    /// entity name is attached (pure clarification with no entity yet).
    var displayName: String {
        entityName.isEmpty ? title : entityName
    }

    /// What `QuestionView` shows as the question line.
    var questionText: String {
        if let question, !question.isEmpty { return question }
        return title.isEmpty ? body : title
    }

    var createdDateValue: Date {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        return f.date(from: createdDate) ?? .now
    }
}
```

- [ ] **Step 4: Thread `optionKey` / `remindDays` through the write path**

`Sync/SyncAPI.swift:64-65`:

```swift
    func resolveInbox(id: String, action: String, answer: String?,
                      optionKey: String?, remindDays: Int?,
                      mergeTarget: String?, mergeSurvivor: String?) async throws
```

`Services/APIClient.swift:935-947`:

```swift
    func resolveInboxItem(
        id: String,
        action: String,
        answer: String? = nil,
        optionKey: String? = nil,
        remindDays: Int? = nil,
        mergeTarget: String? = nil,
        mergeSurvivor: String? = nil
    ) async throws {
        var body: [String: Any] = ["action": action]
        if let answer { body["answer"] = answer }
        if let optionKey { body["optionKey"] = optionKey }
        if let remindDays { body["remindDays"] = remindDays }
        if let mergeTarget { body["mergeTarget"] = mergeTarget }
        if let mergeSurvivor { body["mergeSurvivor"] = mergeSurvivor }
        try await post("/inbox/\(id)/resolve", body: body)
    }
```

`Services/APIClient.swift:1480-1484` (the `SyncAPI` conformance):

```swift
    func resolveInbox(id: String, action: String, answer: String?,
                      optionKey: String?, remindDays: Int?,
                      mergeTarget: String?, mergeSurvivor: String?) async throws {
        try await resolveInboxItem(id: id, action: action, answer: answer,
                                   optionKey: optionKey, remindDays: remindDays,
                                   mergeTarget: mergeTarget, mergeSurvivor: mergeSurvivor)
    }
```

`Sync/Mutations.swift:50-75`:

```swift
struct InboxResolve: Mutation {
    let id: String
    let action: String
    var answer: String? = nil
    /// G60: the key of the option the user picked ("a", "b", "both", "neither").
    var optionKey: String? = nil
    /// G60: with `action == "defer"`, how far out to push the reminder.
    var remindDays: Int? = nil
    var mergeTarget: String? = nil
    var mergeSurvivor: String? = nil

    /// `skip` deliberately keeps the item in the queue — nothing to hide.
    /// `defer` DOES hide: the server sets `remind_after`, so the card is gone
    /// from the pending list either way.
    private var hides: Bool { action != "skip" }

    func optimistic(_ store: Store) async {
        if hides { store.hiddenInboxIds.insert(id) }
    }

    func request(_ api: any SyncAPI) async throws {
        try await api.resolveInbox(id: id, action: action, answer: answer,
                                   optionKey: optionKey, remindDays: remindDays,
                                   mergeTarget: mergeTarget, mergeSurvivor: mergeSurvivor)
    }

    func rollback(_ store: Store) async {
        store.hiddenInboxIds.remove(id)
    }

    var failureMessage: String { "Couldn't resolve that item — reverted" }
    var refreshDomains: Set<SyncDomain> { [.inbox] }
}
```

`ViewModels/InboxViewModel.swift` — replace `resolve`:

```swift
    @discardableResult
    func resolve(
        id: String,
        action: String,
        answer: String? = nil,
        optionKey: String? = nil,
        remindDays: Int? = nil,
        mergeTarget: String? = nil,
        mergeSurvivor: String? = nil
    ) async -> Bool {
        errorMessage = nil
        let ok = await store.perform(InboxResolve(
            id: id, action: action, answer: answer,
            optionKey: optionKey, remindDays: remindDays,
            mergeTarget: mergeTarget, mergeSurvivor: mergeSurvivor
        ))
        if ok {
            // Keep the menu-bar badge in lockstep with the resolve.
            await onResolved?()
        } else {
            errorMessage = store.toast
        }
        return ok
    }
```

`Tests/CicadaAppTests/StoreTests.swift:114-117` (`FakeSyncAPI`) — record the new arguments so the assertions in Step 1 can see them:

```swift
    func resolveInbox(id: String, action: String, answer: String?,
                      optionKey: String?, remindDays: Int?,
                      mergeTarget: String?, mergeSurvivor: String?) async throws {
        try await record(
            "resolveInbox:\(id):\(action):\(optionKey ?? "nil"):\(remindDays.map(String.init) ?? "nil")"
        )
    }
```

`MutationTests.swift` asserts on `"resolveInbox:a:archive"` style strings — update any such assertion to the new four-part form (`grep -n "resolveInbox:" Tests/CicadaAppTests/MutationTests.swift`).

- [ ] **Step 5: Fix the two call sites of `item.options`**

`Views/Inbox/InboxCardView.swift`'s `choiceActions` currently does `ForEach(item.options ?? [], id: \.self)`. Change it to compile now (Task 10 replaces this branch entirely):

```swift
                ForEach(item.options) { option in
                    InboxActionButton(
                        title: option.label, icon: "arrow.right.circle",
                        color: 0x7C8FFF, fullWidth: true
                    ) {
                        fire("resolve", answer: option.label)
                    }
                }
```

Then `grep -rn "\.options" app/CicadaApp/Sources` and fix any other optional-chained use.

`InboxListView.swift:35-41` — widen the closure to the new arity (Task 10 finalises the signature; for now):

```swift
                            InboxCardView(item: item) { action, answer, mergeTarget, mergeSurvivor in
                                await viewModel.resolve(
                                    id: item.id, action: action,
                                    answer: answer,
                                    mergeTarget: mergeTarget,
                                    mergeSurvivor: mergeSurvivor
                                )
                            }
```

- [ ] **Step 6: Run the tests**

Run: `cd app/CicadaApp && swift test`
Expected: PASS (all suites, including the updated `MutationTests`).

- [ ] **Step 7: Commit**

```bash
git add app/CicadaApp/Sources/CicadaApp/Models/InboxItem.swift app/CicadaApp/Sources/CicadaApp/Sync/Mutations.swift app/CicadaApp/Sources/CicadaApp/Sync/SyncAPI.swift app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift app/CicadaApp/Sources/CicadaApp/ViewModels/InboxViewModel.swift app/CicadaApp/Sources/CicadaApp/Views/Inbox/InboxCardView.swift app/CicadaApp/Sources/CicadaApp/Views/Inbox/InboxListView.swift app/CicadaApp/Tests/CicadaAppTests/InboxQuestionTests.swift app/CicadaApp/Tests/CicadaAppTests/StoreTests.swift app/CicadaApp/Tests/CicadaAppTests/MutationTests.swift
git commit -m "$(cat <<'EOF'
feat(app): decode inbox question objects; optionKey/remindDays through InboxResolve (G60)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

### Task 10: `QuestionView` + `QuestionSelection`, and the Sources section

**Files:**
- Create: `app/CicadaApp/Sources/CicadaApp/Models/QuestionSelection.swift`
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Inbox/QuestionView.swift`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Inbox/InboxCardView.swift` (header title + `actionRow`), `InboxListView.swift` (closure arity)
- Modify: `app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift` (3 source calls), `Views/Graph/EntityDetailCard.swift` (Sources section)
- Create: `app/CicadaApp/Sources/CicadaApp/Models/EntitySource.swift`
- Test: append to `app/CicadaApp/Tests/CicadaAppTests/InboxQuestionTests.swift`

**Interfaces:**
- Consumes: `InboxItem.questionText/options/allowOther/allowDefer/hint` (Task 9), `InboxViewModel.resolve(id:action:answer:optionKey:remindDays:mergeTarget:mergeSurvivor:)` (Task 9), `GET/POST/DELETE /entities/{id}/sources` (Task 7).
- Produces:
  - `struct QuestionSelection` — pure keyboard model: `init(optionCount:allowOther:)`, `moveDown()`, `moveUp()`, `openOther()`, `activate() -> Action?`, `isOtherRow`, `index`, `rowCount`; `enum Action { case pick(Int), openOther }`.
  - `struct QuestionResolution { let action: String; let answer: String?; let optionKey: String?; let remindDays: Int? }` — what `QuestionView` hands back.
  - `struct EntitySource: Codable, Identifiable` + `APIClient.fetchEntitySources/addEntitySource/deleteEntitySource`.
  - `InboxCardView.onResolve: (QuestionResolution) async -> Bool` (the four-positional-argument closure is replaced by one value).

- [ ] **Step 1: Write the failing tests for `QuestionSelection`**

Append to `app/CicadaApp/Tests/CicadaAppTests/InboxQuestionTests.swift`:

```swift
final class QuestionSelectionTests: XCTestCase {

    func testStartsOnTheFirstOption() {
        let s = QuestionSelection(optionCount: 3, allowOther: true)
        XCTAssertEqual(s.index, 0)
        XCTAssertEqual(s.rowCount, 4)   // 3 options + the Other… row
        XCTAssertFalse(s.isOtherRow)
    }

    func testMoveDownAndUpWrapAround() {
        var s = QuestionSelection(optionCount: 3, allowOther: false)
        s.moveDown(); s.moveDown()
        XCTAssertEqual(s.index, 2)
        s.moveDown()
        XCTAssertEqual(s.index, 0, "wraps to the top")
        s.moveUp()
        XCTAssertEqual(s.index, 2, "wraps to the bottom")
    }

    func testTheOtherRowIsTheLastRowWhenAllowed() {
        var s = QuestionSelection(optionCount: 2, allowOther: true)
        s.moveDown(); s.moveDown()
        XCTAssertTrue(s.isOtherRow)
        XCTAssertEqual(s.activate(), .openOther)
        XCTAssertTrue(s.otherExpanded)
    }

    func testActivateOnAnOptionPicksIt() {
        var s = QuestionSelection(optionCount: 3, allowOther: true)
        s.moveDown()
        XCTAssertEqual(s.activate(), .pick(1))
        XCTAssertFalse(s.otherExpanded)
    }

    func testOpenOtherJumpsToTheOtherRow() {
        var s = QuestionSelection(optionCount: 3, allowOther: true)
        s.openOther()
        XCTAssertTrue(s.isOtherRow)
        XCTAssertTrue(s.otherExpanded)
    }

    func testOpenOtherIsANoOpWhenNotAllowed() {
        var s = QuestionSelection(optionCount: 3, allowOther: false)
        s.openOther()
        XCTAssertFalse(s.otherExpanded)
        XCTAssertEqual(s.index, 0)
    }

    func testNoOptionsAndNoOtherIsInert() {
        var s = QuestionSelection(optionCount: 0, allowOther: false)
        XCTAssertEqual(s.rowCount, 0)
        s.moveDown()
        XCTAssertEqual(s.index, 0)
        XCTAssertNil(s.activate())
    }
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd app/CicadaApp && swift test --filter QuestionSelectionTests`
Expected: FAIL to compile — `cannot find 'QuestionSelection' in scope`.

- [ ] **Step 3: Write `Models/QuestionSelection.swift`**

```swift
import Foundation

/// Pure keyboard-navigation model for `QuestionView` (G60 §2.6).
///
/// Rows are the options, followed by the "Other…" row when `allowOther`.
/// Kept out of the `View` so the ↑/↓/⏎/`o` behaviour is unit-testable — every
/// piece of new inbox logic that CAN be pure lives here rather than in a body.
struct QuestionSelection: Equatable {
    let optionCount: Int
    let allowOther: Bool

    private(set) var index: Int = 0
    /// True once the user has opened the free-text row (via ⏎ on it, or `o`).
    private(set) var otherExpanded: Bool = false

    enum Action: Equatable {
        case pick(Int)
        case openOther
    }

    init(optionCount: Int, allowOther: Bool) {
        self.optionCount = max(0, optionCount)
        self.allowOther = allowOther
    }

    /// Options + the optional Other… row.
    var rowCount: Int { optionCount + (allowOther ? 1 : 0) }

    var isOtherRow: Bool { allowOther && index == optionCount }

    mutating func moveDown() {
        guard rowCount > 0 else { return }
        index = (index + 1) % rowCount
    }

    mutating func moveUp() {
        guard rowCount > 0 else { return }
        index = (index - 1 + rowCount) % rowCount
    }

    /// Jump straight to the free-text row (the `o` shortcut).
    mutating func openOther() {
        guard allowOther else { return }
        index = optionCount
        otherExpanded = true
    }

    /// ⏎ on the highlighted row. `nil` when there is nothing to activate.
    mutating func activate() -> Action? {
        guard rowCount > 0 else { return nil }
        if isOtherRow {
            otherExpanded = true
            return .openOther
        }
        return .pick(index)
    }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd app/CicadaApp && swift test --filter QuestionSelectionTests`
Expected: PASS (7 tests)

- [ ] **Step 5: Write `Views/Inbox/QuestionView.swift`**

```swift
import SwiftUI

/// What a `QuestionView` interaction resolves to — one value instead of four
/// positional arguments, so adding a channel (option key, remind window) never
/// churns every call site again.
struct QuestionResolution {
    let action: String
    var answer: String? = nil
    var optionKey: String? = nil
    var remindDays: Int? = nil
    var mergeTarget: String? = nil
    var mergeSurvivor: String? = nil
}

/// The single renderer for every question-carrying inbox kind (conflict,
/// clarification, merge_suggestion) — modelled on Claude Code's
/// `AskUserQuestion`: the question, an option list with descriptions and a
/// muted age capsule, an "Other…" free-text row, and a "remind me later" footer.
///
/// Keyboard: ↑/↓ move, ⏎ picks, `o` opens Other. All of that lives in
/// `QuestionSelection`; this view only paints it.
struct QuestionView: View {
    let item: InboxItem
    let onResolve: (QuestionResolution) -> Void

    @State private var selection: QuestionSelection
    @State private var otherText = ""
    @FocusState private var otherFocused: Bool

    init(item: InboxItem, onResolve: @escaping (QuestionResolution) -> Void) {
        self.item = item
        self.onResolve = onResolve
        _selection = State(initialValue: QuestionSelection(
            optionCount: item.options.count, allowOther: item.allowOther
        ))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Text(item.questionText)
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(CicadaTheme.textPrimary)
                .fixedSize(horizontal: false, vertical: true)

            if let hint = item.hint, !hint.isEmpty {
                hintRow(hint)
            }

            VStack(spacing: CicadaTheme.spacingXS) {
                ForEach(Array(item.options.enumerated()), id: \.element.id) { pair in
                    optionRow(pair.element, highlighted: selection.index == pair.offset)
                        .onTapGesture { pick(pair.offset) }
                }

                if item.allowOther {
                    otherRow
                }
            }

            if item.allowDefer {
                HStack {
                    Spacer()
                    InboxActionButton(title: "Not sure — remind me later",
                                      icon: "clock", color: 0xF59E0B) {
                        onResolve(QuestionResolution(action: "defer"))
                    }
                }
            }
        }
        .onMoveCommand { direction in
            switch direction {
            case .down: selection.moveDown()
            case .up: selection.moveUp()
            default: break
            }
        }
        .onExitCommand { otherFocused = false }
        .focusable()
        .onKeyPress(.return) { activate(); return .handled }
        .onKeyPress(KeyEquivalent("o")) {
            guard !otherFocused else { return .ignored }
            selection.openOther()
            otherFocused = true
            return .handled
        }
    }

    // MARK: - Rows

    private func hintRow(_ hint: String) -> some View {
        HStack(spacing: CicadaTheme.spacingXS) {
            Image(systemName: "link")
                .font(.system(size: 10))
                .foregroundStyle(CicadaTheme.textTertiary)
            Text(hint)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .lineLimit(2)
            if let url = firstURL(in: hint) {
                Spacer()
                Button {
                    NSWorkspace.shared.open(url)
                } label: {
                    Image(systemName: "arrow.up.right.square")
                        .font(.system(size: 11))
                        .foregroundStyle(CicadaTheme.accent)
                }
                .buttonStyle(.plain)
                .help("Open source")
            }
        }
        .padding(.vertical, 2)
    }

    private func optionRow(_ option: InboxOption, highlighted: Bool) -> some View {
        HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
            VStack(alignment: .leading, spacing: 2) {
                Text(option.label)
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(CicadaTheme.textPrimary)
                if let description = option.description, !description.isEmpty {
                    Text(description)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            Spacer(minLength: CicadaTheme.spacingSM)
            if let capsule = option.ageCapsule {
                Text(capsule)
                    .font(.system(size: 10, design: .monospaced))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .padding(.horizontal, 6)
                    .padding(.vertical, 2)
                    .background(CicadaTheme.surfaceHover)
                    .clipShape(Capsule())
            }
        }
        .padding(CicadaTheme.spacingMD)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                .fill(highlighted ? CicadaTheme.accent.opacity(0.12) : CicadaTheme.surface.opacity(0.5))
        )
        .overlay(
            RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                .stroke(highlighted ? CicadaTheme.accent.opacity(0.5) : CicadaTheme.border, lineWidth: 1)
        )
        .contentShape(Rectangle())
    }

    private var otherRow: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            if selection.otherExpanded {
                HStack(spacing: CicadaTheme.spacingSM) {
                    TextField("What's actually true?", text: $otherText)
                        .textFieldStyle(.plain)
                        .font(CicadaTheme.bodyFont)
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .focused($otherFocused)
                        .onSubmit(submitOther)
                    InboxActionButton(title: "Submit", icon: "paperplane", color: 0x22C55E,
                                      disabled: otherText.trimmedText.isEmpty,
                                      action: submitOther)
                }
                .padding(CicadaTheme.spacingMD)
                .background(CicadaTheme.surface)
                .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
                .overlay(
                    RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                        .stroke(CicadaTheme.accent.opacity(0.5), lineWidth: 1)
                )
            } else {
                HStack {
                    Image(systemName: "pencil")
                        .font(.system(size: 11))
                        .foregroundStyle(CicadaTheme.textTertiary)
                    Text("Other…")
                        .font(.system(size: 12))
                        .foregroundStyle(CicadaTheme.textSecondary)
                    Spacer()
                }
                .padding(CicadaTheme.spacingMD)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(
                    RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                        .fill(selection.isOtherRow ? CicadaTheme.accent.opacity(0.12)
                                                   : CicadaTheme.surface.opacity(0.5))
                )
                .overlay(
                    RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                        .stroke(selection.isOtherRow ? CicadaTheme.accent.opacity(0.5)
                                                     : CicadaTheme.border, lineWidth: 1)
                )
                .contentShape(Rectangle())
                .onTapGesture {
                    selection.openOther()
                    otherFocused = true
                }
            }
        }
    }

    // MARK: - Actions

    private func activate() {
        guard let action = selection.activate() else { return }
        switch action {
        case .pick(let i): pick(i)
        case .openOther: otherFocused = true
        }
    }

    private func pick(_ i: Int) {
        guard item.options.indices.contains(i) else { return }
        onResolve(QuestionResolution(action: "resolve", optionKey: item.options[i].key))
    }

    private func submitOther() {
        let text = otherText.trimmedText
        guard !text.isEmpty else { return }
        // Free text answers the question outright; the backend closes every
        // option claim and records a user-stated claim.
        onResolve(QuestionResolution(action: "resolve", answer: text,
                                     optionKey: item.options.contains(where: { $0.key == "neither" })
                                        ? "neither" : nil))
    }

    private func firstURL(in text: String) -> URL? {
        guard let detector = try? NSDataDetector(types: NSTextCheckingResult.CheckingType.link.rawValue)
        else { return nil }
        let range = NSRange(text.startIndex..., in: text)
        return detector.firstMatch(in: text, range: range)?.url
    }
}

private extension String {
    var trimmedText: String { trimmingCharacters(in: .whitespacesAndNewlines) }
}
```

- [ ] **Step 6: Fold `QuestionView` into `InboxCardView`**

In `Views/Inbox/InboxCardView.swift`:

1. Change the callback type:
```swift
    /// One resolution value (action + answer/optionKey/remindDays/merge fields),
    /// forwarded to `InboxViewModel.resolve`. Returns whether the resolve
    /// succeeded — `fire()` uses this to reset `resolving` on failure.
    let onResolve: (QuestionResolution) async -> Bool
```

2. Header title line — conflicts show the question, the entity name becomes the subtitle:
```swift
            VStack(alignment: .leading, spacing: 3) {
                Text(item.kind == .conflict ? item.questionText : item.displayName)
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(isExpanded ? nil : 1)

                Text(item.kind == .conflict ? item.displayName : item.title)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .lineLimit(isExpanded ? nil : 1)
            }
```

3. Replace `actionRow` so decay keeps its three buttons and everything else with a question goes to `QuestionView`:
```swift
    @ViewBuilder
    private var actionRow: some View {
        if item.kind == .decay {
            decayActions
        } else if !item.options.isEmpty || item.question != nil {
            QuestionView(item: item) { resolution in
                fire(resolution)
            }
        } else {
            switch item.requiredInput {
            case .freetext: freetextActions
            case .merge: mergeActions
            default:
                HStack {
                    Spacer()
                    InboxActionButton(title: "Dismiss", icon: "xmark", color: 0x6B7280) {
                        fire(QuestionResolution(action: "dismiss"))
                    }
                }
            }
        }
    }

    /// Decay keeps its three buttons verbatim (out of scope for G60 §3).
    private var decayActions: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            InboxActionButton(title: "Keep Active", icon: "checkmark", color: 0x22C55E) {
                fire(QuestionResolution(action: "keep_active"))
            }
            InboxActionButton(title: "Archive", icon: "archivebox", color: 0x6B7280) {
                fire(QuestionResolution(action: "archive"))
            }
            InboxActionButton(title: "Remind Later", icon: "clock", color: 0xF59E0B) {
                fire(QuestionResolution(action: "remind_later"))
            }
        }
    }
```
Delete the now-unused `choiceActions`.

4. Rewrite `fire` to take one value, and update the `freetextActions` / `mergeActions` call sites accordingly (`fire(QuestionResolution(action: "answer", answer: answerText.trimmed))`, `fire(QuestionResolution(action: "merge", mergeTarget: mergeText.trimmed, mergeSurvivor: survivor))`, …):
```swift
    private func fire(_ resolution: QuestionResolution) {
        if resolution.action != "skip" {
            withAnimation(.spring(duration: 0.2)) { resolving = true }
        }
        Task {
            let succeeded = await onResolve(resolution)
            if !succeeded {
                withAnimation(.spring(duration: 0.2)) { resolving = false }
            }
        }
    }
```

`Views/Inbox/InboxListView.swift:35-41`:

```swift
                            InboxCardView(item: item) { resolution in
                                await viewModel.resolve(
                                    id: item.id,
                                    action: resolution.action,
                                    answer: resolution.answer,
                                    optionKey: resolution.optionKey,
                                    remindDays: resolution.remindDays,
                                    mergeTarget: resolution.mergeTarget,
                                    mergeSurvivor: resolution.mergeSurvivor
                                )
                            }
```

- [ ] **Step 7: Add the entity Sources section**

Create `app/CicadaApp/Sources/CicadaApp/Models/EntitySource.swift`:

```swift
import Foundation

/// One "where to look this fact up" reference on an entity page (G61).
/// Matches `EntitySource` in `api/models/schemas.py`.
struct EntitySource: Codable, Identifiable, Hashable {
    var ref: String
    var kind: String        // url | path | note
    var predicate: String?
    var addedBy: String
    var addedAt: String

    /// Stable within one payload — the backend addresses sources by index.
    var id: String { "\(kind)|\(ref)" }

    var url: URL? { kind == "url" ? URL(string: ref) : nil }

    var icon: String {
        switch kind {
        case "url": "link"
        case "path": "folder"
        default: "text.quote"
        }
    }
}

struct EntitySourceList: Codable {
    var entityId: String
    var sources: [EntitySource]
}
```

In `Services/APIClient.swift`, next to `fetchEntityRepos`:

```swift
    // MARK: - Fact sources (G61)

    func fetchEntitySources(entityId: String) async throws -> [EntitySource] {
        let payload: EntitySourceList = try await get("/entities/\(entityId)/sources")
        return payload.sources
    }

    func addEntitySource(entityId: String, ref: String, predicate: String? = nil) async throws -> [EntitySource] {
        var body: [String: Any] = ["ref": ref]
        if let predicate { body["predicate"] = predicate }
        let data = try await post("/entities/\(entityId)/sources", body: body)
        return try JSONDecoder().decode(EntitySourceList.self, from: data).sources
    }

    func deleteEntitySource(entityId: String, index: Int) async throws -> [EntitySource] {
        let data = try await delete("/entities/\(entityId)/sources/\(index)")
        return try JSONDecoder().decode(EntitySourceList.self, from: data).sources
    }
```

In `Views/Graph/EntityDetailCard.swift`, add `@State private var sources: [EntitySource] = []` and `@State private var newSourceRef = ""` next to `repoContexts` (line 24), render the section in `contentTab` after the repository section:

```swift
            Divider().background(CicadaTheme.border)
            sourcesSection
```

and load it in the existing `.task(id: entity.id)` block, alongside `repoContexts = []`:

```swift
            sources = []
            newSourceRef = ""
            sources = (try? await APIClient.shared.fetchEntitySources(entityId: entity.id)) ?? []
```

Then add the section itself (place it beside `repositorySection`):

```swift
    // MARK: - Sources Section (G61)

    /// "Where to look this fact up" — a URL, a path, or a plain-English note.
    /// Distinct from `source_episodes` (where a belief came from): a source is
    /// a cheat-sheet for REFRESHING a fact.
    private var sourcesSection: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Text("Sources")
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)

            ForEach(Array(sources.enumerated()), id: \.element.id) { pair in
                sourceRow(pair.element, index: pair.offset)
            }

            HStack(spacing: CicadaTheme.spacingSM) {
                Image(systemName: "plus.circle")
                    .font(.system(size: 11))
                    .foregroundStyle(CicadaTheme.textTertiary)
                TextField("Add a URL, a path, or a note…", text: $newSourceRef)
                    .textFieldStyle(.plain)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .onSubmit {
                        let ref = newSourceRef.trimmingCharacters(in: .whitespacesAndNewlines)
                        guard !ref.isEmpty else { return }
                        newSourceRef = ""
                        Task {
                            if let updated = try? await APIClient.shared.addEntitySource(
                                entityId: entity.id, ref: ref
                            ) {
                                sources = updated
                            }
                        }
                    }
            }
            .padding(CicadaTheme.spacingSM)
            .background(CicadaTheme.surface)
            .clipShape(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall))
            .overlay(
                RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                    .stroke(CicadaTheme.border, lineWidth: 1)
            )
        }
    }

    private func sourceRow(_ source: EntitySource, index: Int) -> some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Image(systemName: source.icon)
                .font(.system(size: 11))
                .foregroundStyle(CicadaTheme.textTertiary)
            VStack(alignment: .leading, spacing: 1) {
                Text(source.ref)
                    .font(.system(size: 12))
                    .foregroundStyle(source.url == nil ? CicadaTheme.textSecondary : CicadaTheme.accent)
                    .lineLimit(2)
                Text([source.predicate, "added by \(source.addedBy)", source.addedAt]
                        .compactMap { $0 }.joined(separator: " · "))
                    .font(.system(size: 10))
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
            Spacer()
            if let url = source.url {
                Button { NSWorkspace.shared.open(url) } label: {
                    Image(systemName: "arrow.up.right.square")
                        .font(.system(size: 11))
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
                .buttonStyle(.plain)
                .help("Open")
            }
            Button {
                Task {
                    if let updated = try? await APIClient.shared.deleteEntitySource(
                        entityId: entity.id, index: index
                    ) {
                        sources = updated
                    }
                }
            } label: {
                Image(systemName: "trash")
                    .font(.system(size: 11))
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
            .buttonStyle(.plain)
            .help("Remove source")
        }
        .padding(.vertical, 2)
    }
```

- [ ] **Step 8: Run the Swift suite**

Run: `cd app/CicadaApp && swift test`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add app/CicadaApp/Sources/CicadaApp/Models/QuestionSelection.swift app/CicadaApp/Sources/CicadaApp/Models/EntitySource.swift app/CicadaApp/Sources/CicadaApp/Views/Inbox/QuestionView.swift app/CicadaApp/Sources/CicadaApp/Views/Inbox/InboxCardView.swift app/CicadaApp/Sources/CicadaApp/Views/Inbox/InboxListView.swift app/CicadaApp/Sources/CicadaApp/Views/Graph/EntityDetailCard.swift app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift app/CicadaApp/Tests/CicadaAppTests/InboxQuestionTests.swift
git commit -m "$(cat <<'EOF'
feat(app): QuestionView + QuestionSelection + entity Sources section (G60, G61)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

### Task 11: Docs — CLAUDE.md API list and the backlog rows

**Files:**
- Modify: `CLAUDE.md` (API Design endpoint list, Nudge Inbox section)
- Modify: `docs/goals/memory-evolution.md:579-580` (G60, G61 status cells)

**Interfaces:**
- Consumes: everything shipped in Tasks 1–10. No code changes.

- [ ] **Step 1: Add the new endpoints to the CLAUDE.md API list**

In `CLAUDE.md`, inside the fenced endpoint block, after the `GET /entities/{entity_id}/repos` / `PATCH …/repos` lines add:

```
GET  /entities/{id}/sources               → declared "where to check this fact" sources (G61)
POST /entities/{id}/sources               → append a source {ref, kind?, predicate?}; kind inferred
DELETE /entities/{id}/sources/{index}     → remove one source
```

and update the resolve line:

```
POST /inbox/{id}/resolve                  → resolve a pending inbox item (accepts optionKey / answer / remindDays; action "defer" hides it until remind_after)
```

- [ ] **Step 2: Document the question object in the Inbox feature section**

In `CLAUDE.md`, under "### 2. Nudge Inbox & 3. Clarification Queue — unified `memory/inbox/`", replace the "Quick-action buttons per kind" bullet list's Conflict line and append two bullets:

```markdown
- **Question object (G60):** every `conflict` / `clarification` / `merge_suggestion` item carries
  `question` (one sentence), `options: [{key, label, description, claim_id, observed_at,
  last_referenced}]`, `allow_other`, `allow_defer`, `predicate`, and an optional `hint`
  (from the entity's `sources:`). Descriptions lead with the age phrase ("6 months ago") so
  staleness is visible before choosing; `age_days` is derived at read time, never stored.
  Legacy flat `options: [str]` items still render — they are upgraded to `{key, label}` on read.
- **Dedup + time:** items are keyed `(entity_id, predicate)` (clarifications by
  `(entity_id, uncertainty_type)`, merges by the sorted entity pair). A second competing value
  **merges** into the open item as another option instead of writing a duplicate file. Each Sleep,
  `inbox_questions.refresh_open_questions` bumps re-mentioned options, auto-resolves a question the
  user answered organically in conversation, escalates a question every option of which has been
  silent for `inbox_stale_after_days` (default 90) by inserting a "Neither anymore" option, and
  keeps deferred items (`remind_after` in the future) out of `GET /inbox` and `cicada_check_nudges`.
- **Resolve is claim-aware:** picking an option supersedes every losing claim (`valid_to` +
  `superseded_by`); "both" keeps them open with a `context` qualifier; "neither"/free text writes a
  `user_stated` claim that closes them; `defer` writes `remind_after`. All four commit with
  `Cicada-Author: user`.
```

- [ ] **Step 3: Document `sources:` in the Storage Layer section**

In `CLAUDE.md`, right after the "### Repo links" subsection, add:

```markdown
### Fact sources (G61)
Entity pages may carry an optional `sources:` frontmatter key — *where to look a fact up*,
distinct from `source_episodes` (where a belief came from) and from the body's `## Links`:

```yaml
sources:
  - ref: https://www.linkedin.com/in/rodrigosagastegui
    kind: url            # url | path | note (inferred from `ref` when not given)
    predicate: works-at  # optional — which fact this source refreshes
    added_by: user       # model id, or "user"
    added_at: '2026-08-30'
```

Read/written by `api/services/fact_sources.py` behind `GET/POST/DELETE /entities/{id}/sources`
(note: `api/services/entity_sources.py` is a *different* module — it resolves an entity's episodes
back to whole conversations). `cicada_write_claim` accepts `sources: [str]`, attributed to the
model that wrote the claim. Conflict generation consults them: a matching source becomes the
card's "Source to check" hint. Nothing is fetched in this slice.
```

- [ ] **Step 4: Flip the backlog rows**

In `docs/goals/memory-evolution.md`, change the trailing status cell of the **G60** row (line 579) and the **G61** row (line 580) from `| 🔲 |` to `| ✅ |`, and append to each row's description, before the status cell:

- G60: ` **Shipped 2026-08-30:** question objects (`inbox_questions.py`), `(entity, predicate)` dedup with merge-on-collision (`inbox_generator.find_open`), `refresh_open_questions` in Stage 5.56, claim-aware resolve + defer (`inbox_service`), `QuestionView`/`QuestionSelection` in the app, `cicada_resolve_inbox` on MCP.`
- G61: ` **Shipped 2026-08-30 (minimal slice):** `sources:` frontmatter via `api/services/fact_sources.py`, `GET/POST/DELETE /entities/{id}/sources`, `cicada_write_claim(sources=)`, the conflict-card `hint`, and the app's entity Sources section. Fetching/"check now" remains a follow-up.`

- [ ] **Step 5: Verify both suites one last time**

Run: `api/.venv/bin/python -m pytest api/tests -q`
Expected: PASS

Run: `cd app/CicadaApp && swift test`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md docs/goals/memory-evolution.md
git commit -m "$(cat <<'EOF'
docs: inbox question objects + fact sources (G60, G61)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01WvpJcHz2oRsYKqWTZNpjDj
EOF
)"
```

---

## Manual verification (after Task 11, on the `claude-chats` bank)

The spec's §4 live check. Not a task — run it before opening a PR.

1. Start the backend: `api/.venv/bin/python -m uvicorn api.main:app --port 8000`. The startup log should say `Collapsed N duplicate open inbox item(s)`.
2. `curl -s -H "Authorization: Bearer $(cat ~/.cicada/api_token)" localhost:8000/inbox | python3 -m json.tool | grep -c '"kind": "conflict"'` — the two "Rodrigo Sagastegui (works-at)" cards must have collapsed to one.
3. Open the app's Inbox: the card title reads the question, each option shows its age capsule, and there is an "Other…" row plus "Not sure — remind me later".
4. Pick "Neither anymore", type the current employer, Submit. Then check:
   - `grep -A4 'source_trust: user_stated' memory/banks/claude-chats/entities/rodrigo-sagastegui.md` shows the new claim.
   - Both old claims carry `valid_to` and `superseded_by`.
   - `git -C memory/banks/claude-chats log -1 --format='%s%n%b'` shows `Inbox resolution (conflict)` with `Cicada-Author: user`.
