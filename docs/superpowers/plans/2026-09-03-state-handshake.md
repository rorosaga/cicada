# G53 + G75 — Live State Dictionary and the Connection Handshake

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An agent arrives, is told what Cicada is and how to use it, sees the *now* view of the bank, and can start contributing with provenance — without a model call, without a human, and on any harness. Two files carry it: `<bank>/_state.md` (G53, the state dictionary: a cursor into the graph, regenerated deterministically) and the generated handshake primer (G75, `_state.md` + the interaction contract, keyed off `clientInfo`), delivered on the MCP `initialize` response, as a `cicada_handshake` tool, and as `GET /handshake`.

**Architecture:** One pure builder (`api/services/state_dictionary.py`) renders `_state.md` from frontmatter the bank already holds (`bank_index`, `session_stats`, `repo_context`, `engine_select`, `sleep_scheduler`) — no LLM, bounded git probes, write-if-changed. One pure formatter (`api/services/handshake.py`) turns the parsed state plus a fixed contract into ≤ 1,800 tokens of primer text, cached under `$CICADA_HOME/handshake/`. Sleep's engine-independent tail regenerates and commits the state file as `cicada`; `_finalize` never lets it ride in a model-authored commit; `GET /state` refreshes lazily; the MCP server only ever *reads* it. Recall's `cicada-hints` carries a one-shot compact `state` block for harnesses that drop `instructions`.

**Tech Stack:** Python 3 / FastAPI / Pydantic (`api/`), YAML frontmatter + git (`memory/`), MCP server (`mcp/server.py`). No Swift in this track.

**Spec:** `docs/goals/memory-evolution.md` rows **G53** (`:605`) and **G75** (`:637`); G48 (`:573`, session identity — the `resumable`-never-persisted rail), G115 (`:677`, the inbox discipline the primer quotes), G118 slice 1 (`:680`, spans + `GET /episodes/{id}/span`), G121 (`:683`, world facts are a cache — one sentence in the primer).

## Global Constraints

- Work ONLY in `<worktree>/` (branch `feat/state-handshake`, based on `dev @ 076bb8c`). Every shell command is `cd <worktree>/ && …` with the absolute path (`zoxide` hijacks relative `cd`; ignore its stderr warning). No `grep --include=*.ext` (zsh globbing breaks it).
- NEVER read `<repo>/memory` (any bank), `~/.cicada`, `~/Library/Safari`, or `~/.claude/projects` — real personal data. Every fixture in this plan is synthetic (`alpha-project`, `bob-example`, `example.com`).
- Python tests: `cd <worktree>/ && api/.venv/bin/python -m pytest <files> -q -p no:cacheprovider`. Full suite baseline: exactly 8 date-dependent failures in `test_calendar_registry.py` plus `test_agent_provenance.py::test_a_decay_only_change_lands_in_its_own_cicada_authored_commit` (order-dependent, pre-existing). Everything else must be green after every task.
- Never `git add -A`. Stage named files only. Never commit `memory/`, `logs/`, `.claude/settings.json`, `api/.venv`, `*-report.md`. No push, no new branches/worktrees, no subagents, ignore Devin/PR comments.
- **Zero LLM anywhere in this track.** Nothing here imports `providers`, `agent_engine`, or `litellm`; a test in Task 1 monkeypatches `providers.resolve_llm_fn` to raise and runs the builder.
- **Privacy rails.** `_state.md` carries ids, names already on entity pages, one-liners derived from entity bodies (`hub_builder._one_line_summary`), conversation titles (bank-internal), counts and enums — never claim text, never transcript content, never a secret (engine *model names* and connection *ids* only: no keys, no account emails). Repo probes are read-only `git` under a total 2 s budget. The telemetry `handshake` event is ids/enums only.
- **Portability.** No owner name anywhere (the owner entity is referenced by id only when `settings.observer_owner` — a NEW empty-default setting added in Task 1, `CICADA_OBSERVER_OWNER`; nothing in the codebase carries an owner id today — names an entity id whose page exists); no author-machine path in code, docs, or tests. Repo paths inside `_state.md` are the user's own declared `repos:` values, verbatim.
- **Degrade, never block.** No `_state.md` yet → the handshake is the static contract plus a one-line "no state yet" note. A stale `_state.md` is still served (it says `generated_at`). A git/repo probe failure degrades one field, never the file.
- Cicada docstrings explain WHY, citing the G-row or review that motivated a rule — match that density.
- Read code at the cited `file:line` before editing — line numbers are from `076bb8c` and drift a few lines as tasks land.

## Rulings (binding — do not re-derive)

- **R1 — Two schedulers of regeneration, one writer.** `state_dictionary.refresh()` is the only function that writes `_state.md`. It is *debounced by inputs*: the frontmatter carries `inputs_version`, a digest of the `sync_service.components()` keys `entities`, `inbox`, `episodes`, `bank` — **not `git_head`**: the file's own `State snapshot` commit moves HEAD, so a digest over HEAD would invalidate itself every cycle and commit forever; `sleep.last_at` only changes with a `Sleep cycle` commit, which never lands without an entity/episode/inbox change. `refresh(force=False)` returns without touching the file when the digest is unchanged; a rebuild writes only when the rendering differs from the existing file with `generated_at`, `repos_probed_at` and `inputs_version` masked (a forced rebuild whose only difference is a newer digest re-stamps the digest, so the read path stays cheap). Consequence: two runs on an unchanged bank are byte-identical (the determinism test), and an idle Sleep night makes no commit.
- **R2 — Sleep owns the commit; the tail runs the refresh first.** `_run_engine_independent_tail` (`sleep_cycle.py:624`) calls `_refresh_state_safely` as its FIRST step — before the connector/feed/calendar polls, whose commits are `git add -A` (`feed_registry._commit_poll`, `calendar_registry._commit_poll`, `git_service.commit_changes`): a `_state.md` left dirty by an API-side refresh would otherwise be swept into a `Sources ingest` / `Feed poll` commit under the wrong trigger and author. (The H1 guard does NOT protect it — `_tree_is_clean` is only consulted once `_state.write_started` is set, `:665`.) `force=True` (repos re-probed nightly) and commits the file alone through `git_service.commit_paths`, subject `State snapshot <date>`, manifest line `_state.md: updated (trigger: sleep/state)`, `Cicada-Author: cicada`, no engine trailer (no LLM ran — same contract as the G85 decay commit). Runs on every exit path including an idle or cancelled cycle, so a bank with an engine outage still has a fresh now-view. **Disclosed consequence:** the tail's later steps (a connector ingest, `_refresh_questions_safely` escalating a question) can change an input AFTER the snapshot, leaving the file one read behind until `GET /state`'s lazy refresh (R4) or the next night — acceptable for a projection whose every field has a live twin. `connected` comes from the same cache-only helper on both writers (`state_dictionary.cached_connected_ids`, R7), so the nightly file and a read-side rebuild never disagree on content for a reason no input explains.
- **R3 — A model commit never carries the projection.** `_finalize` (`sleep_cycle.py:1446`) splits a dirty `_state.md` into its own `cicada` commit before the main `git add -A` commit, mirroring the G85 decay split. `_infer_trigger_for_path` (`:1731`) maps `_state.md` → `sleep/state` so the fallback (split failed) still names the trigger honestly.
- **R4 — Reads regenerate lazily; the MCP never writes it.** `GET /state` calls `refresh(force=False, probe_repos=False)` in a threadpool (an inbox resolution or agentic write changed an input, so the next read rebuilds — cheap: frontmatter cache + top-N bodies, repo blocks carried over from the previous file); `GET /state?refresh=true` forces a rebuild with live repo probes. `inbox_service.resolve` runs the same cheap refresh best-effort after its commit (a human action, rare). `initialize`, `cicada_handshake`, and recall's hint block READ the file as it is (stale allowed, stated via `generated_at`) — connect latency stays one file read, and the MCP process never dirties the bank with a projection.
- **R5 — `resumable` is never persisted (G48).** `_state.md` conversations carry `{id, harness, title, last_seen, episode_count}` only. `GET /state` adds `resumable` per request through `conversations.transcript_exists` (the same injectable seam `GET /conversations/recent` uses). The handshake states resume *availability* as a capability ("Claude Code sessions resume with `claude --resume <id>`; other harnesses group but do not resume") and never asserts a transcript exists.
- **R6 — Ranking is `confidence × 1/(1 + days_since_last_referenced/30)`**, ties broken by id; `today` is a parameter so tests are date-stable. Archived/dropped entities are excluded; top-N defaults: projects 7, people 7, preferences (skills) 5, conversations 5 — configurable via `Settings.state_projects`, `state_people`, `state_preferences`, `state_conversations`.
- **R7 — Engine block is configuration, not a probe.** `mode = settings.llm_mode`, `engine = engine_select.engine_label(settings)`, `model` = `agent_model` (agent) / `ollama/<ollama_model>` (local) / `effective_consolidation_model` (byok/auto); `connected` = sorted ids from `Registry.cached_statuses()` via `state_dictionary.cached_connected_ids(settings)` (cache-only, never shells out; empty when cold or when `settings` is a test stand-in the registry rejects) — `refresh()` fills it in when the caller passes none, so Sleep's tail and `GET /state` agree. Every read is `getattr` with a default so the hermetic `SimpleNamespace` settings the Sleep tests pass keep working.
- **R8 — `sleep.last_at` is one bounded sync `git log -1 --grep='^Sleep cycle' --format=%aI`** (2 s, `check=False`, never raises); `sleep.next_at` is `sleep_scheduler.next_run_at(memory_path, now=)` — moved out of `api/routers/status.py:182` (a service must not import a router); `status.py` re-points to it.
- **R9 — `GET /state` ETag = `etag_for(mp, "entities", "inbox", "episodes", "git_head", extra=f"state={mtime_ns}")`.** No new `sync_service` component (that would change the version vector the Swift `VersionVector` diffs, and no Swift ships in this track). `GET /handshake` carries no ETag — ≤ 7 KB and self-describing, the same reasoning as G118's span endpoint.
- **R10 — Token budget is measured as `len(text) // 4 ≤ 1800`.** No tokenizer: `tiktoken` fetches its BPE files over the network on first use and the suite is offline. `_state.md` is capped at 6,144 bytes; the builder trims in a fixed order — conversation titles are truncated to `TITLE_LIMIT` first, then whole rows are dropped people → preferences → conversations → projects — until it fits; the projects list is what a cursor exists for, so it is given up last.
- **R11 — Three variants, one contract.** `handshake.variant_for(client_name)`: a name containing `claude` → `claude-code`; containing `codex` → `codex`; else `generic`. The variant is 2–3 lines under the header; the contract, state block and capability notes are identical. Cache: `$CICADA_HOME/handshake/<bank>.<variant>.json` = `{"key", "text"}`, key = `f"{CONTRACT_VERSION}:{variant}:{state mtime_ns}:{state size}"` (or `…:absent`).
- **R12 — `cicada_check_nudges` accepts `entity_ids` today.** The G75 row's discipline says `cicada_check_nudges(entity_ids=<recall ids>)` verbatim; a primer that names an argument the tool schema rejects is a bug. Task 4 adds `entity_ids: string[]` to the input schema and an exact-match filter on `fm.entity_id` in `handle_check_nudges`. The G115 Phase 2 gate (`mode`, vector score, asked set, cap) is NOT built here.
- **R13 — Recall's `state` hint rides once per MCP process and only inside an emitted hints block.** `_hints_block` returns `""` when there is nothing to suggest (`mcp/server.py:1030`); that contract is kept — the cursor is added to a block that exists, and the `_STATE_HINT_SENT` flag flips only when it was actually sent.
- **R14 — The ledger gets a `handshake` kind.** G105 measured 0 MCP invocations in 12 days; whether agents receive the primer at all is the same class of question. `refs = {delivery: initialize|tool|http, variant, state_present, state_age_hours, harness, client_name}`, `connection=None`, `billing="free"`, `stage="handshake"` (its own label — every existing `stage` value is a Sleep/ask stage name, and `consumption_stats.stats()` groups `by_stage` over ALL events, so borrowing `driver` would mislabel the row). Added to a new `telemetry.NON_SPEND_KINDS = FEEDBACK_KINDS + ("handshake",)`, which `consumption_stats.stats()` (`:213`) uses in place of `FEEDBACK_KINDS` so a handshake never shows as an "unknown" connection (G113 R7's reasoning).
- **R15 — One prose source for the contract.** `SKILL.md` stops restating when-to-recall/check-nudges rules and instead says "call `cicada_handshake` (or read the `instructions` your harness received) — that text is the contract"; `skills/cicada-librarian/SKILL.md` gets the same one-line pointer. `handshake.HOOK_POINTER` is the single line a SessionStart hook or AGENTS.md would inject (the hook itself is G49/G76).

---

## File map

| File | Responsibility |
|---|---|
| `api/services/state_dictionary.py` (new) | build / render / refresh `_state.md`; `WORLD_FACTS_NOTE`; bounded repo + git probes |
| `api/services/sleep_scheduler.py` | `next_run_at(memory_path, now=None)` (moved from `status.py`) |
| `api/config.py:192-194` | `state_projects`, `state_people`, `state_preferences`, `state_conversations`, `observer_owner` beside the hub settings |
| `api/routers/status.py:182-190` | `_next_sleep_at` delegates to `sleep_scheduler.next_run_at` |
| `api/services/sleep_cycle.py:620-693, 1446-1690, 1731-1747` | `_refresh_state_safely` first in the tail; `_finalize` `_state.md` split; `sleep/state` trigger |
| `api/routers/state.py` (new), `api/main.py:154-176` | `GET /state` (+ETag, `?refresh`), `GET /handshake` |
| `api/services/inbox_service.py:531-549` | best-effort cheap refresh after a resolution commit |
| `api/services/handshake.py` (new) | contract text, variants, cache, `HOOK_POINTER`, `record()` |
| `api/services/telemetry.py:21-31`, `api/services/consumption_stats.py:213` | `handshake` kind, `NON_SPEND_KINDS` |
| `mcp/server.py:93-95, 136-413, 433-452, 525-580, 1020-1037, 1793-1844` | `initialize_result()` with `instructions`; `cicada_handshake` tool; `entity_ids` on `cicada_check_nudges`; recall `state` hint |
| `SKILL.md`, `skills/cicada-librarian/SKILL.md` | point at the generated handshake |
| `CLAUDE.md`, `docs/goals/memory-evolution.md`, `docs/goals/TODO.md` | docs |

Tests (all new, all synthetic): `api/tests/_synthetic_bank.py` (shared fixture helpers, not collected), `api/tests/test_state_dictionary.py`, `api/tests/test_state_wiring.py`, `api/tests/test_handshake.py`, `api/tests/test_mcp_handshake.py`.

---

### Task 1: `_state.md` — the builder

**Files:**
- Create: `api/services/state_dictionary.py`
- Modify: `api/services/sleep_scheduler.py` (add `next_run_at`), `api/routers/status.py:182-190`, `api/config.py:192-194`
- Create: `api/tests/_synthetic_bank.py` (shared synthetic fixture helpers — underscore-prefixed so pytest never collects it; `api/tests` has no `__init__.py`, so sibling tests import it as `from _synthetic_bank import …` via pytest's rootdir-prepend import mode)
- Test: `api/tests/test_state_dictionary.py` (new)

**Interfaces:**
- `state_dictionary.build(memory_path, settings=None, *, today=None, now=None, probe_repos=True, previous=None, repo_resolver=None, git_runner=None, connected_ids=None, repo_budget_s=None) -> tuple[dict, str]` — pure given its injected seams; returns `(frontmatter, body)`.
- `state_dictionary.cached_connected_ids(settings) -> list[str]` — the registry's status cache, never a probe; `[]` on any failure.
- `state_dictionary.refresh(memory_path, settings=None, *, force=False, probe_repos=None, today=None, now=None, repo_resolver=None, connected_ids=None) -> dict` — `{"written": bool, "reason": str, "path": str}`. Never raises on a normal bank.
- `state_dictionary.read_state(memory_path) -> dict | None` — parsed frontmatter (+ `"body"`), `None` when absent/unparseable.
- `state_dictionary.inputs_version(memory_path) -> str`.
- `sleep_scheduler.next_run_at(memory_path, now: datetime | None = None) -> str | None`.

- [ ] **Step 1: Write the fixture helper and the failing tests**

```python
# api/tests/_synthetic_bank.py
"""Shared synthetic bank for the G53/G75 tests — never collected by pytest
(underscore prefix), imported by sibling test files as `from _synthetic_bank
import …`. Every name here is a placeholder (alpha-project, bob-example,
example.com); nothing reads a real bank, `~/.cicada`, or the network."""
from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

from api.services import markdown_parser, predicates


def _entity(memory: Path, eid: str, **fm):
    body = fm.pop("body", f"## Summary\n{eid.replace('-', ' ').title()} is a synthetic fixture.\n")
    base = {"name": eid.replace("-", " ").title(), "type": "concept", "status": "active",
            "confidence": 0.5, "created": "2026-01-01", "last_referenced": "2026-09-01",
            "decay_rate": 0.05, "source_episodes": [], "tags": [], "related": [], "version": 1}
    base.update(fm)
    markdown_parser.write(memory / "entities" / f"{eid}.md", base, body)


def _bank(tmp_path: Path, *, git: bool = True) -> Path:
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox", "hubs"):
        (memory / sub).mkdir(parents=True)
    predicates.install_predicate_map(memory)
    _entity(memory, "alpha-project", type="project", confidence=0.9, last_referenced="2026-09-02",
            repos=[{"path": "~/src/alpha-project", "default_branch": "main"}])
    _entity(memory, "beta-project", type="project", confidence=0.4, last_referenced="2026-03-01")
    _entity(memory, "gamma-project", type="project", status="archived", confidence=0.9)
    _entity(memory, "bob-example", type="person", confidence=0.8, last_referenced="2026-09-01")
    _entity(memory, "concise-summaries", type="skill", confidence=0.7, decay_class="durable",
            body="## Summary\nPrefers concise summaries over long reports.\n")
    markdown_parser.write(memory / "episodes" / "ep_2026-09-01_001.md",
                          {"id": "ep_2026-09-01_001", "timestamp": "2026-09-01T09:00:00+00:00",
                           "processed": False, "session_id": "ses_2026-09-01_abcd1234",
                           "harness": "codex", "title": "Planning alpha"}, "user: plan alpha")
    markdown_parser.write(memory / "episodes" / "ep_2026-09-02_001.md",
                          {"id": "ep_2026-09-02_001", "timestamp": "2026-09-02T09:00:00+00:00",
                           "processed": True, "session_id": "11111111-2222-4333-8444-555555555555",
                           "harness": "claude-code", "project_dir": "/tmp/alpha",
                           "title": "Shipping alpha"}, "user: ship alpha")
    markdown_parser.write(memory / "inbox" / "inbox-001.md",
                          {"kind": "decay", "status": "pending", "entity_id": "beta-project",
                           "entity_name": "Beta Project", "title": "Still tracking Beta?",
                           "created_date": "2026-08-01"}, "ctx")
    markdown_parser.write(memory / "inbox" / "inbox-002.md",
                          {"kind": "conflict", "status": "pending", "entity_id": "alpha-project",
                           "entity_name": "Alpha Project", "title": "Which db?", "remind_after": "2099-01-01",
                           "created_date": "2026-08-01"}, "ctx")
    if git:
        for args in (["init", "-q"], ["config", "user.email", "t@example.com"],
                     ["config", "user.name", "t"], ["add", "."],
                     ["commit", "-q", "-m", "Sleep cycle 2026-09-02\n\nentities/alpha-project.md: updated (source: n/a, trigger: sleep/extraction)\n\nCicada-Author: cicada"]):
            subprocess.run(["git", "-C", str(memory), *args], check=True, capture_output=True)
    return memory


def _settings(memory: Path, **over):
    base = dict(memory_path=memory, llm_mode="byok", litellm_model="gpt-5.4-mini",
                consolidation_model="", agent_model="sonnet", ollama_model="llama3.1",
                state_projects=7, state_people=7, state_preferences=5, state_conversations=5)
    base.update(over)
    ns = SimpleNamespace(**base)
    ns.effective_consolidation_model = (ns.consolidation_model or "").strip() or ns.litellm_model
    return ns


def _ok_repo(decl, *, timeout_s=2.0):
    return {"path": decl["path"], "status": "ok", "current_branch": "feat/x", "dirty_files": 2,
            "ahead": 1, "behind": 0, "worktrees": [], "last_commit": None}
```

```python
# api/tests/test_state_dictionary.py
"""G53 — `_state.md`, the live state dictionary.

A cursor into the graph, regenerated deterministically: ids, names and
one-liners already on entity pages, counts and enums — never claim text,
never a transcript, never a secret. Fixtures are synthetic (alpha-project,
bob-example, example.com); no test reads a real bank or the network.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from _synthetic_bank import _bank, _entity, _ok_repo, _settings

from api.services import markdown_parser, state_dictionary

TODAY = date(2026, 9, 3)
NOW = datetime(2026, 9, 3, 10, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _tmp_home(tmp_path, monkeypatch):
    # `inputs_version` goes through `sync_service.components()`, which stats
    # `cicada_home()` (logo index + telemetry file) — keep that under tmp so
    # no test creates or reads anything in the real `~/.cicada`.
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))


def test_build_schema_and_ranking(tmp_path):
    memory = _bank(tmp_path)
    fm, body = state_dictionary.build(memory, _settings(memory), today=TODAY, now=NOW,
                                      repo_resolver=_ok_repo)
    assert fm["type"] == "state" and fm["schema_version"] == 1
    assert fm["generated_at"] == NOW.isoformat()
    assert fm["bank"] == "memory" and "owner_id" not in fm
    assert fm["engine"] == {"mode": "byok", "engine": "litellm", "model": "gpt-5.4-mini", "connected": []}
    assert fm["sleep"]["last_at"].startswith("20") and fm["sleep"]["queue_depth"] == 1
    assert fm["sleep"]["next_at"] is None
    # the deferred conflict is hidden from the pending count, like GET /inbox
    assert fm["inbox"] == {"pending": 1, "by_kind": {"decay": 1}}
    # recency × confidence, archived excluded
    assert [p["id"] for p in fm["projects"]] == ["alpha-project", "beta-project"]
    alpha = fm["projects"][0]
    assert alpha["name"] == "Alpha Project" and alpha["one_liner"].startswith("Alpha Project is a synthetic")
    assert alpha["repos"] == [{"path": "~/src/alpha-project", "branch": "feat/x", "dirty": 2,
                               "ahead_behind": "1/0", "state": "ok"}]
    assert [p["id"] for p in fm["people"]] == ["bob-example"]
    assert fm["conversations"][0]["id"] == "11111111-2222-4333-8444-555555555555"
    assert fm["conversations"][0]["harness"] == "claude-code"
    assert "resumable" not in fm["conversations"][0] and "project_dir" not in fm["conversations"][0]
    assert fm["preferences"] == [{"id": "concise-summaries", "name": "Concise Summaries",
                                  "one_liner": "Prefers concise summaries over long reports."}]
    assert fm["world_facts_note"] == state_dictionary.WORLD_FACTS_NOTE
    assert "[[Alpha Project]]" in body and "`alpha-project`" in body
    assert "## Projects" in body and "## Recent conversations" in body


def test_body_is_a_cursor_not_a_copy(tmp_path):
    memory = _bank(tmp_path)
    _entity(memory, "delta-project", type="project", confidence=0.6,
            body="## Summary\nDelta.\n\n" + "`" * 3 + "claims\n- id: c1\n  text: secret claim text\n" + "`" * 3 + "\n")
    fm, body = state_dictionary.build(memory, _settings(memory), today=TODAY, now=NOW, repo_resolver=_ok_repo)
    text = body + str(fm)
    assert "secret claim text" not in text
    assert "user: plan alpha" not in text  # never transcript content


def test_refresh_is_deterministic_and_debounced(tmp_path):
    memory = _bank(tmp_path)
    settings = _settings(memory)
    first = state_dictionary.refresh(memory, settings, force=True, today=TODAY, now=NOW, repo_resolver=_ok_repo)
    assert first["written"] is True
    path = memory / "_state.md"
    before = path.read_bytes()
    later = NOW.replace(hour=11)
    second = state_dictionary.refresh(memory, settings, force=False, today=TODAY, now=later, repo_resolver=_ok_repo)
    assert second["written"] is False and second["reason"] == "inputs unchanged"
    assert path.read_bytes() == before
    third = state_dictionary.refresh(memory, settings, force=True, today=TODAY, now=later, repo_resolver=_ok_repo)
    assert third["written"] is False and third["reason"] == "content unchanged"
    assert path.read_bytes() == before  # generated_at alone never rewrites the file


def test_refresh_rebuilds_when_an_input_changes(tmp_path):
    memory = _bank(tmp_path)
    settings = _settings(memory)
    state_dictionary.refresh(memory, settings, force=True, today=TODAY, now=NOW, repo_resolver=_ok_repo)
    (memory / "inbox" / "inbox-001.md").unlink()
    out = state_dictionary.refresh(memory, settings, force=False, today=TODAY, now=NOW, repo_resolver=_ok_repo)
    assert out["written"] is True
    assert state_dictionary.read_state(memory)["inbox"]["pending"] == 0


def test_size_cap_trims_deterministically(tmp_path):
    memory = _bank(tmp_path)
    for i in range(60):
        _entity(memory, f"person-{i:02d}", type="person", confidence=0.9,
                body="## Summary\n" + ("Long summary sentence " * 12) + ".\n")
    for i in range(30):
        markdown_parser.write(memory / "episodes" / f"ep_2026-08-{i + 1:02d}_001.md",
                              {"id": f"ep_2026-08-{i + 1:02d}_001", "timestamp": f"2026-08-{i + 1:02d}T09:00:00+00:00",
                               "processed": True, "session_id": f"ses_2026-08-{i + 1:02d}_deadbeef",
                               "title": "T" * 300}, "x")
    settings = _settings(memory, state_people=60, state_conversations=30)
    fm, body = state_dictionary.build(memory, settings, today=TODAY, now=NOW, repo_resolver=_ok_repo)
    rendered = state_dictionary.render(fm, body)
    assert len(rendered.encode("utf-8")) <= state_dictionary.MAX_BYTES
    assert len(fm["projects"]) == 2, "projects are trimmed last"
    assert all(len(c["title"]) <= state_dictionary.TITLE_LIMIT for c in fm["conversations"])


def test_repo_budget_degrades_to_unavailable(tmp_path):
    memory = _bank(tmp_path)
    # Must outrank alpha-project (0.99 vs 0.9 / (1 + 1/30) ≈ 0.871): repos are
    # probed in ranking order, and alpha's own declared repo would otherwise
    # spend the whole budget before `~/src/a` is reached.
    _entity(memory, "eps-project", type="project", confidence=0.99, last_referenced="2026-09-03",
            repos=[{"path": "~/src/a"}, {"path": "~/src/b"}, {"path": "~/src/c"}])
    calls: list[float] = []

    def slow(decl, *, timeout_s=2.0):
        calls.append(timeout_s)
        # spend the whole allowance the caller gave this probe
        state_dictionary._sleep_for_tests(timeout_s)
        return {"path": decl["path"], "status": "timeout"}

    fm, _ = state_dictionary.build(memory, _settings(memory), today=TODAY, now=NOW,
                                   repo_resolver=slow, repo_budget_s=0.3)
    repos = {r["path"]: r["state"] for p in fm["projects"] for r in p["repos"]}
    assert repos["~/src/a"] == "timeout"
    assert repos["~/src/c"] == "unavailable", "a repo past the budget is never probed"
    assert all(t <= 0.3 for t in calls) and sum(calls) <= 0.31


def test_probe_repos_false_carries_previous_blocks_over(tmp_path):
    memory = _bank(tmp_path)
    settings = _settings(memory)
    state_dictionary.refresh(memory, settings, force=True, today=TODAY, now=NOW, repo_resolver=_ok_repo)

    def boom(decl, *, timeout_s=2.0):
        raise AssertionError("must not probe")

    (memory / "inbox" / "inbox-001.md").unlink()
    out = state_dictionary.refresh(memory, settings, force=False, probe_repos=False, today=TODAY, now=NOW,
                                   repo_resolver=boom)
    assert out["written"] is True
    state = state_dictionary.read_state(memory)
    assert state["projects"][0]["repos"][0]["branch"] == "feat/x"
    assert state["repos_probed_at"] == NOW.isoformat()


def test_no_git_and_no_settings_still_builds(tmp_path):
    memory = _bank(tmp_path, git=False)
    fm, body = state_dictionary.build(memory, None, today=TODAY, now=NOW, repo_resolver=_ok_repo)
    assert fm["sleep"]["last_at"] is None
    assert fm["engine"]["mode"] == "byok" and fm["engine"]["engine"] == "litellm"


def test_engine_block_by_mode(tmp_path):
    memory = _bank(tmp_path)
    fm, _ = state_dictionary.build(memory, _settings(memory, llm_mode="agent"), today=TODAY, now=NOW, repo_resolver=_ok_repo)
    assert fm["engine"]["engine"] == "claude-cli" and fm["engine"]["model"] == "sonnet"
    fm, _ = state_dictionary.build(memory, _settings(memory, llm_mode="local"), today=TODAY, now=NOW, repo_resolver=_ok_repo)
    assert fm["engine"]["engine"] == "ollama" and fm["engine"]["model"] == "ollama/llama3.1"
    fm, _ = state_dictionary.build(memory, _settings(memory), today=TODAY, now=NOW, repo_resolver=_ok_repo,
                                   connected_ids=["claude-plan"])
    assert fm["engine"]["connected"] == ["claude-plan"]


def test_owner_id_only_when_configured_and_present(tmp_path):
    memory = _bank(tmp_path)
    fm, _ = state_dictionary.build(memory, _settings(memory, observer_owner="bob-example"), today=TODAY, now=NOW, repo_resolver=_ok_repo)
    assert fm["owner_id"] == "bob-example"
    fm, _ = state_dictionary.build(memory, _settings(memory, observer_owner="nobody"), today=TODAY, now=NOW, repo_resolver=_ok_repo)
    assert "owner_id" not in fm


def test_builder_never_touches_the_llm_seam(tmp_path, monkeypatch):
    from api.services import providers

    def boom(*a, **k):
        raise AssertionError("LLM seam touched by the state builder")

    monkeypatch.setattr(providers, "resolve_llm_fn", boom)
    memory = _bank(tmp_path)
    state_dictionary.refresh(memory, _settings(memory), force=True, today=TODAY, now=NOW, repo_resolver=_ok_repo)
    assert (memory / "_state.md").exists()


def test_next_run_at_moved_to_scheduler(tmp_path):
    from api.models.schemas import ScheduleConfig
    from api.routers import status
    from api.services import sleep_scheduler

    memory = _bank(tmp_path)
    assert sleep_scheduler.next_run_at(memory) is None
    sleep_scheduler.save_schedule(memory, ScheduleConfig(enabled=True, hour=3, minute=0))
    now = datetime(2026, 9, 3, 12, 0)
    assert sleep_scheduler.next_run_at(memory, now=now) == "2026-09-04T03:00:00"
    assert status._next_sleep_at(memory).startswith("20")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd <worktree>/ && api/.venv/bin/python -m pytest api/tests/test_state_dictionary.py -q -p no:cacheprovider`
Expected: FAIL — `ImportError: cannot import name 'state_dictionary'`.

- [ ] **Step 3: Settings + scheduler**

In `api/config.py` after `hub_member_cap` (line 194) add:

```python
    # G53 — live state dictionary (`<bank>/_state.md`): how many of each
    # list the cursor carries. Small on purpose: the file is a pointer into
    # the graph (ids + one-liners), never a copy of it, and is capped at
    # `state_dictionary.MAX_BYTES` regardless of these.
    state_projects: int = 7           # CICADA_STATE_PROJECTS
    state_people: int = 7             # CICADA_STATE_PEOPLE
    state_preferences: int = 5        # CICADA_STATE_PREFERENCES
    state_conversations: int = 5      # CICADA_STATE_CONVERSATIONS
    # G53 — the owner's own entity id (e.g. `bob-example`), so `_state.md` can
    # point an agent at "the person's page" without a name in code (the
    # portability rail: no owner name anywhere). Empty = unset; the builder
    # additionally requires `entities/<id>.md` to exist before it writes
    # `owner_id`. Distinct from the claim layer's `observer=` seam in
    # `agentic_write` — that names who asserted a claim, not whose bank it is.
    observer_owner: str = ""          # CICADA_OBSERVER_OWNER
```

In `api/services/sleep_scheduler.py` add after `save_schedule` (line 58):

```python
def next_run_at(memory_path: Path, now: datetime | None = None) -> str | None:
    """Next occurrence of the persisted schedule as a naive local ISO string,
    or ``None`` when the schedule is disabled.

    Lived in ``api/routers/status.py`` until G53: the state dictionary (a
    service) needs the same answer and a service must not import a router.
    ``now`` is injectable so the state builder's determinism tests are
    date-stable.
    """
    from datetime import timedelta

    cfg = load_schedule(memory_path)
    if not cfg.enabled:
        return None
    current = now or datetime.now()
    candidate = current.replace(hour=cfg.hour, minute=cfg.minute, second=0, microsecond=0)
    if candidate <= current:
        candidate += timedelta(days=1)
    return candidate.isoformat()
```

In `api/routers/status.py:182-190` replace the body of `_next_sleep_at` with `return sleep_scheduler.next_run_at(memory_path)` (keep the function — the status route and its tests call it); drop the now-unused `timedelta` import if `datetime`/`timedelta` are no longer referenced elsewhere in the file (check with grep before removing).

- [ ] **Step 4: Implement `api/services/state_dictionary.py`**

```python
"""``<bank>/_state.md`` — the live state dictionary (G53).

MHS's state-dictionary idea, ported: one small, documented, *live* object a
fresh agent reads at session start. Cicada's version is a **cursor into the
graph** — ids, names, one-liners already on entity pages, counts and enums —
never a copy of it (G53: "not a cache of entity pages"). Everything here is
derived from frontmatter the bank already holds, so regeneration is zero-LLM
and cheap enough to run on every Sleep tail and lazily on every read.

Three rails, each from a review that cost something:

* **Deterministic and debounced (R1).** ``inputs_version`` digests the
  ``sync_service`` components the file is built from; ``refresh`` skips a
  rebuild when nothing changed, and a forced rebuild writes only when the
  rendering differs with ``generated_at`` masked. An idle night therefore
  makes no commit, and two runs on a still bank are byte-identical.
* **Bounded probes.** Repo state is live (``repo_context``) but under one
  total budget (``REPO_BUDGET_S``); a repo past the budget is recorded as
  ``state: unavailable`` and never probed. ``sleep.last_at`` is one
  ``git log`` with a timeout, ``check=False``, never raising.
* **Never persisted: ``resumable`` (G48) or anything not already on a page.**
  Conversations carry id/harness/title/last_seen/episode_count; the API adds
  ``resumable`` per request. No transcript content, no claim text, no secret
  (engine *model names* and connection *ids* only).

The file is a projection, never a source of truth: a reader that finds it
stale (``generated_at``) must still work, and every field has a live twin
(``/status``, ``/inbox``, ``/conversations/recent``, ``cicada_repo_context``).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

from loguru import logger

from api.services import bank_index, inbox_service, markdown_parser, session_stats, sync_service
from api.services.claims import strip_claims_block
from api.services.hub_builder import _one_line_summary

STATE_FILENAME = "_state.md"
SCHEMA_VERSION = 1
MAX_BYTES = 6 * 1024
TITLE_LIMIT = 60
ONE_LINER_LIMIT = 120
REPO_BUDGET_S = 2.0
GIT_TIMEOUT_S = 2.0
# The sync components the file is a function of. `bank` is included so a
# bank switch can never serve another bank's cursor from a stale digest.
# `git_head` is deliberately NOT: this file's own `State snapshot` commit
# moves HEAD, so a digest over it would invalidate itself every cycle (R1).
INPUT_COMPONENTS = ("entities", "inbox", "episodes", "bank")
# G121 in one sentence — the handshake carries this verbatim (single source).
WORLD_FACTS_NOTE = (
    "Personal facts (what the person said, did or decided) are authoritative; "
    "world facts on a page are a dated cache — verify before acting on them."
)
_ARCHIVED = {"archived", "dropped"}
_DEFAULTS = {"state_projects": 7, "state_people": 7, "state_preferences": 5, "state_conversations": 5}

RepoResolver = Callable[..., dict]


def state_path(memory_path: Path) -> Path:
    return Path(memory_path) / STATE_FILENAME


def inputs_version(memory_path: Path) -> str:
    comps = sync_service.components(Path(memory_path))
    parts = {k: comps.get(k, "") for k in INPUT_COMPONENTS}
    return hashlib.sha1(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:16]


def read_state(memory_path: Path) -> dict | None:
    """Parsed frontmatter plus ``body``; ``None`` when absent or unparseable."""
    path = state_path(memory_path)
    if not path.exists():
        return None
    try:
        parsed = markdown_parser.parse(path)
    except Exception as exc:
        logger.warning(f"_state.md unreadable: {type(exc).__name__}: {exc}")
        return None
    if parsed.frontmatter.get("type") != "state":
        return None
    out = dict(parsed.frontmatter)
    out["body"] = parsed.body
    return out


# --- ranking ----------------------------------------------------------------


def _days_since(value: Any, today: date) -> float:
    try:
        d = date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return 365.0
    return max(0.0, float((today - d).days))


def _score(fm: dict, today: date) -> float:
    try:
        confidence = float(fm.get("confidence", 0.5) or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    return confidence / (1.0 + _days_since(fm.get("last_referenced"), today) / 30.0)


def _ranked(memory_path: Path, etype: str, today: date, n: int) -> list[bank_index.IndexedFile]:
    rows = []
    for f in bank_index.files(memory_path, "entities"):
        fm = f.frontmatter
        if str(fm.get("type", "") or "") != etype:
            continue
        if str(fm.get("status", "active") or "active").lower() in _ARCHIVED:
            continue
        rows.append((-_score(fm, today), f.stem, f))
    rows.sort(key=lambda r: (r[0], r[1]))
    return [r[2] for r in rows[: max(0, n)]]


def _name(f: bank_index.IndexedFile) -> str:
    return str(f.frontmatter.get("name") or f.stem.replace("-", " ").title())


def _one_liner(f: bank_index.IndexedFile) -> str:
    """First sentence of ``## Summary`` with the claims fence stripped FIRST
    (``claims.strip_claims_block``): ``parse_sections`` runs a section to EOF,
    so on a page whose fence follows the summary the fence sits inside it —
    the "never claim text" rail must not rest on a first-sentence split."""
    try:
        return _one_line_summary(strip_claims_block(f.body()), limit=ONE_LINER_LIMIT)
    except Exception:
        return ""


# --- blocks -----------------------------------------------------------------


def _repo_blocks(
    declared: list, *, resolver: RepoResolver, budget: list[float], previous: dict[str, dict] | None,
) -> list[dict]:
    """One block per declared repo, live-probed under the shared budget.

    ``budget`` is a one-element list (remaining seconds) shared across every
    project so the WHOLE file costs at most ``REPO_BUDGET_S`` of git. A repo
    that would start past the budget is recorded ``unavailable`` — the
    honest answer, and cheaper than a timeout. With ``resolver=None`` the
    previous file's block for that path is carried over (R4: a read-side
    refresh never pays for git).
    """
    out: list[dict] = []
    for decl in declared or []:
        if not isinstance(decl, dict) or not decl.get("path"):
            continue
        path = str(decl["path"])
        if resolver is None:
            prev = (previous or {}).get(path)
            out.append(prev or {"path": path, "branch": None, "dirty": None, "ahead_behind": None, "state": "unavailable"})
            continue
        remaining = budget[0]
        if remaining <= 0.05:
            out.append({"path": path, "branch": None, "dirty": None, "ahead_behind": None, "state": "unavailable"})
            continue
        started = time.monotonic()
        try:
            ctx = resolver(decl, timeout_s=min(remaining, 2.0))
        except Exception as exc:  # a probe must degrade one block, never the file
            logger.warning(f"repo probe failed for a declared repo: {type(exc).__name__}")
            ctx = {"path": path, "status": "git_unavailable"}
        budget[0] -= time.monotonic() - started
        status = str(ctx.get("status") or "unavailable")
        if status == "ok":
            ahead, behind = ctx.get("ahead"), ctx.get("behind")
            out.append({
                "path": path,
                "branch": ctx.get("current_branch"),
                "dirty": ctx.get("dirty_files"),
                "ahead_behind": None if ahead is None and behind is None else f"{ahead or 0}/{behind or 0}",
                "state": "ok",
            })
        else:
            out.append({"path": path, "branch": None, "dirty": None, "ahead_behind": None, "state": status})
    return out


def _engine_block(settings, connected_ids: list[str] | None) -> dict:
    """Configuration, never a probe (R7) — the registry's cached ids are the
    only 'live' part, and they are cache-only."""
    from api.services import engine_select

    mode = str(getattr(settings, "llm_mode", None) or "byok").strip().lower()
    engine = engine_select.engine_label(settings) if settings is not None else "litellm"
    if mode == "agent":
        model = getattr(settings, "agent_model", None)
    elif mode == "local":
        model = f"ollama/{getattr(settings, 'ollama_model', 'llama3.1')}"
    else:
        model = getattr(settings, "effective_consolidation_model", None) or getattr(settings, "litellm_model", None)
    return {"mode": mode, "engine": engine, "model": model or None, "connected": list(connected_ids or [])}


def _default_git_runner(memory_path: Path, args: list[str]) -> str | None:
    try:
        proc = subprocess.run(["git", *args], cwd=str(memory_path), capture_output=True, text=True,
                              timeout=GIT_TIMEOUT_S, check=False)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    return proc.stdout if proc.returncode == 0 else None


def _sleep_block(memory_path: Path, git_runner, now: datetime) -> dict:
    out = git_runner(memory_path, ["log", "-1", "--grep=^Sleep cycle", "--format=%aI"])
    last_at = (out or "").strip() or None
    queue = sum(1 for f in bank_index.files(memory_path, "episodes") if not f.frontmatter.get("processed", False))
    from api.services import sleep_scheduler

    try:
        next_at = sleep_scheduler.next_run_at(memory_path, now=now.replace(tzinfo=None))
    except Exception:
        next_at = None
    return {"last_at": last_at, "queue_depth": queue, "next_at": next_at}


def _inbox_block(memory_path: Path) -> dict:
    """Exactly what ``GET /inbox`` would show. ``inbox_service.load_inbox``
    hides deferred items AND (G98) items whose subject is archived/dropped/
    gone, so the cursor never advertises a question the app would not.
    ``load_inbox`` reads the wall clock for deferral; the ``inbox`` sync
    component folds today's date in whenever a deferral is pending
    (sync_service.py:145), so the digest and this count move together."""
    by_kind: Counter = Counter()
    for item in inbox_service.load_inbox(memory_path):
        if item.status != "pending":
            continue
        by_kind[str(item.kind or "decay")] += 1
    return {"pending": sum(by_kind.values()), "by_kind": dict(sorted(by_kind.items()))}


def cached_connected_ids(settings) -> list[str]:
    """Connection ids from the registry's status cache — cache-only, never a
    vendor-CLI shell-out (R7). ``[]`` when the cache is cold or when
    ``settings`` is a hermetic stand-in the registry cannot take. Shared by
    Sleep's tail and ``GET /state`` so the two writers agree on content."""
    try:
        from api.services.connections.registry import get_registry

        return sorted(c.id for c in get_registry(settings).cached_statuses() if c.connected)
    except Exception:
        return []


def _conversations(memory_path: Path, n: int) -> list[dict]:
    rows = session_stats.aggregate_conversations(memory_path, limit=max(1, n), transcript_exists=lambda *_: False)
    return [{"id": r["conversation_id"], "harness": r["harness"], "title": r["title"][:TITLE_LIMIT],
             "last_seen": r["last_seen"], "episode_count": r["episode_count"]} for r in rows]


# --- build / render -----------------------------------------------------------


def _limit(settings, key: str) -> int:
    try:
        return int(getattr(settings, key, _DEFAULTS[key]) or _DEFAULTS[key])
    except (TypeError, ValueError):
        return _DEFAULTS[key]


def build(
    memory_path: Path,
    settings=None,
    *,
    today: date | None = None,
    now: datetime | None = None,
    probe_repos: bool = True,
    previous: dict | None = None,
    repo_resolver: RepoResolver | None = None,
    git_runner=None,
    connected_ids: list[str] | None = None,
    repo_budget_s: float | None = None,
) -> tuple[dict, str]:
    """Render the state dictionary. Pure given its seams; never calls an LLM."""
    memory_path = Path(memory_path)
    today = today or date.today()
    now = now or datetime.now(timezone.utc)
    git_runner = git_runner or _default_git_runner
    if probe_repos and repo_resolver is None:
        from api.services.repo_context import resolve_repo_context
        repo_resolver = resolve_repo_context
    resolver = repo_resolver if probe_repos else None
    prev_repos: dict[str, dict] = {}
    for p in (previous or {}).get("projects", []) or []:
        for r in p.get("repos", []) or []:
            if r.get("path"):
                prev_repos[str(r["path"])] = dict(r)
    # Read the module constant at call time (not as a default-arg binding) so
    # a test can monkeypatch `REPO_BUDGET_S` to 0.0 and probe nothing.
    budget = [float(REPO_BUDGET_S if repo_budget_s is None else repo_budget_s)]

    projects = []
    for f in _ranked(memory_path, "project", today, _limit(settings, "state_projects")):
        projects.append({
            "id": f.stem, "name": _name(f), "one_liner": _one_liner(f),
            "confidence": round(float(f.frontmatter.get("confidence", 0.5) or 0.0), 2),
            "last_referenced": str(f.frontmatter.get("last_referenced") or "")[:10] or None,
            "repos": _repo_blocks(f.frontmatter.get("repos") or [], resolver=resolver, budget=budget, previous=prev_repos),
        })
    people = [{"id": f.stem, "name": _name(f), "one_liner": _one_liner(f),
               "last_referenced": str(f.frontmatter.get("last_referenced") or "")[:10] or None}
              for f in _ranked(memory_path, "person", today, _limit(settings, "state_people"))]
    preferences = [{"id": f.stem, "name": _name(f), "one_liner": _one_liner(f)}
                   for f in _ranked(memory_path, "skill", today, _limit(settings, "state_preferences"))]

    fm: dict = {
        "type": "state",
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.isoformat(),
        "inputs_version": inputs_version(memory_path),
        "bank": memory_path.name,
    }
    owner = str(getattr(settings, "observer_owner", "") or "").strip()
    if owner and (memory_path / "entities" / f"{owner}.md").exists():
        fm["owner_id"] = owner
    fm.update({
        "engine": _engine_block(settings, connected_ids),
        "sleep": _sleep_block(memory_path, git_runner, now),
        "inbox": _inbox_block(memory_path),
        "projects": projects,
        "people": people,
        "conversations": _conversations(memory_path, _limit(settings, "state_conversations")),
        "preferences": preferences,
        "repos_probed_at": now.isoformat() if resolver is not None else (previous or {}).get("repos_probed_at"),
        "world_facts_note": WORLD_FACTS_NOTE,
    })
    _fit(fm)
    return fm, render_body(fm)


def render_body(fm: dict) -> str:
    """The human-readable half: a cursor (wikilinks + ids), never entity bodies."""
    lines = ["# Cicada — now", "",
             f"Bank `{fm['bank']}` · engine {fm['engine']['engine']} ({fm['engine']['model'] or 'unset'}) · "
             f"inbox {fm['inbox']['pending']} pending · queue {fm['sleep']['queue_depth']} · "
             f"last Sleep {fm['sleep']['last_at'] or 'never'} · as of {fm['generated_at']}",
             "", "## Projects"]
    for p in fm["projects"]:
        repo_bits = ", ".join(
            f"{r['path']}@{r['branch']}" + (f" (dirty {r['dirty']})" if r.get("dirty") else "")
            if r.get("state") == "ok" else f"{r['path']} ({r.get('state')})" for r in p.get("repos", [])
        )
        tail = f" — {p['one_liner']}" if p.get("one_liner") else ""
        lines.append(f"- [[{p['name']}]] (`{p['id']}`){tail}" + (f" — repo: {repo_bits}" if repo_bits else ""))
    if not fm["projects"]:
        lines.append("- (no active projects yet)")
    lines += ["", "## People"]
    lines += [f"- [[{p['name']}]] (`{p['id']}`)" + (f" — {p['one_liner']}" if p.get("one_liner") else "") for p in fm["people"]] or ["- (none yet)"]
    lines += ["", "## Recent conversations"]
    lines += [f"- `{c['id']}` · {c['harness'] or 'unknown'} · {c['title']} · {c['last_seen'][:10]}" for c in fm["conversations"]] or ["- (none recorded)"]
    lines += ["", "## Preferences"]
    lines += [f"- [[{p['name']}]] (`{p['id']}`)" + (f" — {p['one_liner']}" if p.get("one_liner") else "") for p in fm["preferences"]] or ["- (none extracted yet)"]
    lines += ["", "## Rules for agents",
              f"- {fm['world_facts_note']}",
              "- This file is a cursor: open `entities/<id>.md` (or `cicada_recall_detail`) for the page; `_index.md` is the map.",
              "- Never edit entity files directly — write through `cicada_write_claim` / `cicada_save_episode`."]
    return "\n".join(lines)


def render(fm: dict, body: str) -> str:
    import yaml

    fm_str = yaml.dump(fm, default_flow_style=False, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{fm_str}\n---\n\n{body}\n"


def _fit(fm: dict) -> None:
    """Trim until the rendering fits MAX_BYTES, in a fixed order (R10)."""
    def size() -> int:
        return len(render(fm, render_body(fm)).encode("utf-8"))

    for c in fm["conversations"]:
        c["title"] = c["title"][:TITLE_LIMIT]
    if size() <= MAX_BYTES:
        return
    # Whole rows go people → preferences → conversations → projects: the
    # projects list is what a cursor exists for, so it is given up last (R10).
    for key in ("people", "preferences", "conversations", "projects"):
        while fm[key] and size() > MAX_BYTES:
            fm[key].pop()


_VOLATILE_KEYS = ("generated_at:", "repos_probed_at:", "inputs_version:")


def _masked(text: str) -> str:
    """The document with its clock and digest lines removed — what "content
    unchanged" means (R1). The body's `as of` line is the same clock."""
    return "\n".join(
        l for l in text.splitlines()
        if not l.startswith(_VOLATILE_KEYS) and " · as of " not in l
    )


def refresh(
    memory_path: Path,
    settings=None,
    *,
    force: bool = False,
    probe_repos: bool | None = None,
    today: date | None = None,
    now: datetime | None = None,
    repo_resolver: RepoResolver | None = None,
    connected_ids: list[str] | None = None,
) -> dict:
    """Regenerate ``_state.md`` when its inputs changed (or ``force``).

    ``probe_repos`` defaults to ``force``: Sleep pays for git nightly, a
    read-side refresh carries the previous blocks over. ``connected_ids``
    defaults to the registry's cache (``cached_connected_ids``). Returns
    ``{"written", "reason", "path"}``; never raises on a normal bank.
    """
    memory_path = Path(memory_path)
    path = state_path(memory_path)
    previous = read_state(memory_path)
    if probe_repos is None:
        probe_repos = force
    if not force and previous is not None and previous.get("inputs_version") == inputs_version(memory_path):
        return {"written": False, "reason": "inputs unchanged", "path": str(path)}
    if connected_ids is None:
        connected_ids = cached_connected_ids(settings)
    fm, body = build(memory_path, settings, today=today, now=now, probe_repos=probe_repos, previous=previous,
                     repo_resolver=repo_resolver, connected_ids=connected_ids)
    text = render(fm, body)
    if path.exists() and _masked(path.read_text(encoding="utf-8")) == _masked(text):
        if force and (previous or {}).get("inputs_version") != fm["inputs_version"]:
            # Same content, newer inputs: re-stamp the digest so the read
            # path's debounce is cheap again. Sleep commits the one-line diff.
            path.write_text(text, encoding="utf-8")
            return {"written": True, "reason": "version stamped", "path": str(path)}
        return {"written": False, "reason": "content unchanged", "path": str(path)}
    path.write_text(text, encoding="utf-8")
    return {"written": True, "reason": "rebuilt", "path": str(path)}


def _sleep_for_tests(seconds: float) -> None:  # pragma: no cover - a test seam
    time.sleep(seconds)
```

`_one_line_summary` (`hub_builder.py:43`) already accepts `limit=`. If a `yaml.dump` of `None` values renders `null` — that is fine and intended (the schema documents nullable fields).

- [ ] **Step 5: Run the tests**

Run: `cd <worktree>/ && api/.venv/bin/python -m pytest api/tests/test_state_dictionary.py api/tests/test_sleep_scheduler.py api/tests/test_healthz_memory_root.py -q -p no:cacheprovider`
Expected: all PASS. If `test_size_cap_trims_deterministically` finds the file already under the cap with 60 people, raise the person count in the fixture until the trim engages (the assertion is about the ORDER, and `projects == 2` proves projects survived).

- [ ] **Step 6: Commit**

```bash
cd <worktree>/ && git add api/services/state_dictionary.py api/services/sleep_scheduler.py api/routers/status.py api/config.py api/tests/_synthetic_bank.py api/tests/test_state_dictionary.py && git commit -m "feat(state): _state.md live state dictionary — deterministic, bounded, zero-LLM (G53)"
```

---

### Task 2: Wiring — Sleep tail, `_finalize` split, `GET /state`, inbox hook

**Files:**
- Modify: `api/services/sleep_cycle.py:620-693` (tail), `:1446-1690` (`_finalize`), `:1731-1747` (`_infer_trigger_for_path`)
- Create: `api/routers/state.py`
- Modify: `api/main.py:9-36, 154-176` (import + mount), `api/services/inbox_service.py:531-549`
- Test: `api/tests/test_state_wiring.py` (new)

**Interfaces:**
- `sleep_cycle._refresh_state_safely(memory_path, settings) -> None` (async; first line of the tail).
- `GET /state` → the on-disk frontmatter verbatim (snake_case — one schema, two surfaces) plus `conversations[].resumable` (per request) and `stale: bool` (`inputs_version` ≠ current). `?refresh=true` forces a rebuild with live repo probes. 404 when the bank has no `_state.md` and the lazy refresh could not produce one.
- `GET /handshake` is added in Task 3 to the same router (this task creates the file with `/state` only).

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_state_wiring.py
"""G53 wiring: Sleep's tail regenerates + commits `_state.md` as `cicada`,
`_finalize` never lets it ride in a model commit, `GET /state` refreshes
lazily with an ETag, and an inbox resolution refreshes it best-effort.
Real git in a tmp bank (mirrors test_agent_provenance.py); no model."""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.config import Settings
from api.services import git_service, markdown_parser, predicates, sleep_cycle, state_dictionary


def _git(memory: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(memory), *args], check=True, capture_output=True, text=True).stdout


def _bank(tmp_path: Path) -> Path:
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox", "hubs"):
        (memory / sub).mkdir(parents=True)
    predicates.install_predicate_map(memory)
    markdown_parser.write(memory / "entities" / "alpha-project.md",
                          {"name": "Alpha Project", "type": "project", "status": "active", "confidence": 0.9,
                           "created": "2026-01-01", "last_referenced": "2026-09-01", "decay_rate": 0.05,
                           "source_episodes": [], "tags": [], "related": [], "version": 1},
                          "## Summary\nAlpha.\n")
    _git(memory, "init", "-q")
    _git(memory, "config", "user.email", "t@example.com")
    _git(memory, "config", "user.name", "t")
    _git(memory, "add", ".")
    _git(memory, "commit", "-q", "-m", "seed")
    return memory


def _settings(memory: Path):
    return SimpleNamespace(memory_path=memory, litellm_model="gpt-5.4-mini",
                           litellm_disambiguation_model="gpt-5.4-nano", archive_threshold=0.2,
                           decay_nudge_threshold=0.4, link_enrich_enabled=False, inbox_stale_after_days=90)


@pytest.fixture(autouse=True)
def _tmp_home(tmp_path, monkeypatch):
    # `inputs_version` -> `sync_service.components()` stats `cicada_home()`;
    # never let a test create or read anything under the real `~/.cicada`.
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))


def _quiet_tail(monkeypatch):
    async def none(*a, **k):
        return None
    for name in ("_poll_connectors_safely", "_poll_feeds_and_calendars_safely",
                 "_backfill_links_safely", "_warm_logos_safely", "_refresh_questions_safely"):
        monkeypatch.setattr(sleep_cycle, name, none)


def test_idle_cycle_writes_and_commits_the_state_as_cicada(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    _quiet_tail(monkeypatch)
    monkeypatch.setattr(state_dictionary, "REPO_BUDGET_S", 0.0)  # no git probes of user repos here

    asyncio.run(sleep_cycle.run(_settings(memory), "cycle-state"))

    assert (memory / "_state.md").exists()
    assert _git(memory, "status", "--porcelain").strip() == "", "the tail commits its own projection"
    body = _git(memory, "log", "-1", "--format=%B")
    assert body.startswith("State snapshot ")
    assert "_state.md: updated (trigger: sleep/state)" in body
    assert git_service._parse_authors(body) == ["cicada"]
    assert "Cicada-Engine:" not in body


def test_second_idle_cycle_makes_no_commit(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    _quiet_tail(monkeypatch)
    monkeypatch.setattr(state_dictionary, "REPO_BUDGET_S", 0.0)
    asyncio.run(sleep_cycle.run(_settings(memory), "cycle-a"))
    head = _git(memory, "rev-parse", "HEAD")
    asyncio.run(sleep_cycle.run(_settings(memory), "cycle-b"))
    assert _git(memory, "rev-parse", "HEAD") == head


def test_finalize_splits_a_dirty_state_file_out_of_the_model_commit(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_TELEMETRY", "off")
    memory = _bank(tmp_path)
    (memory / "_state.md").write_text("---\ntype: state\n---\n\nstale projection\n", encoding="utf-8")
    (memory / "entities" / "alpha-project.md").write_text(
        (memory / "entities" / "alpha-project.md").read_text() + "\nmore\n")
    changes = [{"id": "alpha-project", "action": "updated", "source_episode": "ep_1",
                "source_episodes": ["ep_1"], "trigger": "sleep/extraction"}]

    asyncio.run(sleep_cycle._finalize(memory, "cycle-1", changes, Settings(litellm_model="gpt-5.4-mini")))

    hashes = [h for h in _git(memory, "log", "--format=%H", "--reverse").splitlines() if h.strip()]
    assert len(hashes) == 3  # seed, state split, main
    state_msg = _git(memory, "log", "-1", "--format=%B", hashes[1])
    main_msg = _git(memory, "log", "-1", "--format=%B", hashes[2])
    assert "_state.md: updated (trigger: sleep/state)" in state_msg
    assert git_service._parse_authors(state_msg) == ["cicada"]
    assert "_state.md" not in main_msg
    assert "entities/alpha-project.md: updated" in main_msg


def test_infer_trigger_names_the_state_file():
    assert sleep_cycle._infer_trigger_for_path("_state.md") == "sleep/state"


@pytest.fixture
def api_bank(tmp_path: Path, monkeypatch) -> Path:
    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.delenv("CICADA_API_TOKEN", raising=False)
    monkeypatch.setattr(state_dictionary, "REPO_BUDGET_S", 0.0)
    config.get_settings.cache_clear()
    yield memory
    config.get_settings.cache_clear()


def test_get_state_builds_lazily_and_serves_etag(api_bank):
    with TestClient(main.app) as client:
        r = client.get("/state")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["schema_version"] == 1 and data["bank"] == "memory"
        assert data["projects"][0]["id"] == "alpha-project"
        assert data["stale"] is False and data["conversations"] == []
        assert (api_bank / "_state.md").exists()
        etag = r.headers["ETag"]
        assert client.get("/state", headers={"If-None-Match": etag}).status_code == 304
        # an input change flips the ETag and the lazy refresh rebuilds
        markdown_parser.write(api_bank / "inbox" / "inbox-001.md",
                              {"kind": "decay", "status": "pending", "entity_id": "alpha-project",
                               "entity_name": "Alpha Project", "title": "Still?", "created_date": "2026-08-01"}, "c")
        r2 = client.get("/state", headers={"If-None-Match": etag})
        assert r2.status_code == 200 and r2.json()["inbox"]["pending"] == 1


def test_get_state_refresh_true_forces_a_rebuild_with_probes(api_bank, monkeypatch):
    from api.routers import state as state_router

    probes: list = []

    def fake_resolver(decl, *, timeout_s=2.0):
        probes.append(decl["path"])
        return {"path": decl["path"], "status": "ok", "current_branch": "main", "dirty_files": 0, "ahead": 0, "behind": 0}

    fm = markdown_parser.parse(api_bank / "entities" / "alpha-project.md")
    fm.frontmatter["repos"] = [{"path": "~/src/alpha"}]
    markdown_parser.write(api_bank / "entities" / "alpha-project.md", fm.frontmatter, fm.body)
    monkeypatch.setattr(state_dictionary, "REPO_BUDGET_S", 2.0)
    monkeypatch.setattr(state_router, "repo_resolver", fake_resolver)
    with TestClient(main.app) as client:
        assert client.get("/state").status_code == 200
        assert probes == [], "a lazy read never probes git"
        r = client.get("/state", params={"refresh": "true"})
        assert r.status_code == 200 and probes == ["~/src/alpha"]
        assert r.json()["projects"][0]["repos"][0]["branch"] == "main"


def test_get_state_adds_resumable_per_request_and_never_persists_it(api_bank, monkeypatch):
    from api.routers import conversations
    markdown_parser.write(api_bank / "episodes" / "ep_2026-09-02_001.md",
                          {"id": "ep_2026-09-02_001", "timestamp": "2026-09-02T09:00:00+00:00", "processed": True,
                           "session_id": "11111111-2222-4333-8444-555555555555", "harness": "claude-code",
                           "project_dir": "/tmp/alpha", "title": "Shipping alpha"}, "user: ship")
    monkeypatch.setattr(conversations, "transcript_exists", lambda project_dir, sid: True)
    with TestClient(main.app) as client:
        data = client.get("/state").json()
    assert data["conversations"][0]["resumable"] is True
    assert "resumable" not in (api_bank / "_state.md").read_text()
    assert "project_dir" not in (api_bank / "_state.md").read_text()


def test_inbox_resolution_refreshes_the_state_best_effort(api_bank, monkeypatch):
    from api.models.schemas import InboxResolveRequest
    from api.services import inbox_service
    markdown_parser.write(api_bank / "inbox" / "inbox-001.md",
                          {"kind": "decay", "status": "pending", "entity_id": "alpha-project",
                           "entity_name": "Alpha Project", "title": "Still?", "created_date": "2026-08-01"}, "c")
    settings = config.get_settings()
    state_dictionary.refresh(api_bank, settings, force=True)
    assert state_dictionary.read_state(api_bank)["inbox"]["pending"] == 1
    asyncio.run(inbox_service.resolve("inbox-001", InboxResolveRequest(action="keep_active"), settings))
    assert state_dictionary.read_state(api_bank)["inbox"]["pending"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd <worktree>/ && api/.venv/bin/python -m pytest api/tests/test_state_wiring.py -q -p no:cacheprovider`
Expected: FAIL — `AttributeError: module 'api.services.sleep_cycle' has no attribute '_refresh_state_safely'` on the first test; the `/state` tests 404.

- [ ] **Step 3: Sleep tail + `_finalize` split + trigger**

In `api/services/sleep_cycle.py`, add above `_run_engine_independent_tail` (line ~620):

```python
async def _refresh_state_safely(memory_path: Path, settings: Settings) -> None:
    """G53 — regenerate `_state.md` and commit it alone as `cicada`.

    FIRST step of the engine-independent tail, on every exit path — an idle
    night, a cancelled cycle and an engine outage all still get a fresh
    now-view. Runs BEFORE the connector/feed/calendar polls: their commits
    are `git add -A`, so a projection left dirty by a read-side refresh
    (`GET /state`) would otherwise be swept into a `Sources ingest` /
    `Feed poll` commit under the wrong trigger and author (R2 — the H1
    guard does not cover this: it only consults the tree once
    `_state.write_started` is set). `force=True`:
    Sleep is the one place the file pays for live repo probes (R2).
    `commit_paths`, never `git add -A`, so on a half-written cycle only the
    projection lands here and the dirty entity pages stay untouched. The
    commit carries no engine trailer — no LLM ran — exactly like the G85
    decay commit. Unchanged content writes nothing and commits nothing.
    """
    from api.services import state_dictionary

    try:
        result = await asyncio.to_thread(state_dictionary.refresh, memory_path, settings, force=True)
    except Exception as exc:
        logger.warning(f"State snapshot failed: {type(exc).__name__}: {exc}")
        return
    if not result.get("written"):
        logger.info(f"State snapshot: {result.get('reason', 'unchanged')}")
        return
    message = git_service.build_commit_message(
        f"State snapshot {datetime.now().strftime('%Y-%m-%d')}",
        [f"{state_dictionary.STATE_FILENAME}: updated (trigger: sleep/state)"],
        authors=["cicada"],
    )
    try:
        async with _lock:
            await git_service.commit_paths(memory_path, message, [state_dictionary.STATE_FILENAME])
        logger.info("State snapshot: _state.md regenerated and committed")
    except Exception as exc:
        logger.warning(f"State snapshot commit failed (file written, will be split out next cycle): {type(exc).__name__}: {exc}")
```

Check the module already imports `asyncio` and `datetime` (grep the top of the file; add `import asyncio` if absent). `_lock` is the module-level lock used at `:1597`.

Then make it the first statement of `_run_engine_independent_tail` (before the `if outcome.committed or …` branch at `:665`):

```python
    await _refresh_state_safely(memory_path, settings)
```

Append to that function's docstring: "G53: `_refresh_state_safely` runs FIRST and unconditionally — it commits only `_state.md` via `commit_paths`, so it is safe on a dirty tree, and running it before the polls means their `git add -A` can never sweep a projection dirtied by `GET /state` into a poll commit. Anything the polls or the question refresh change afterwards leaves the file one read behind (R2, disclosed)."

In `_finalize`, after the decay-split block (immediately before `# --- Entity lines from structured change data`, line ~1607) add:

```python
    # G53 (R3) — the live state dictionary is a projection, regenerated by
    # the tail and authored `cicada`. A read-side refresh (`GET /state`) can
    # leave it dirty here; without this split the main commit's `git add -A`
    # would stamp a model's name on arithmetic it never touched — the exact
    # G85 smear, on a different file. Same degrade contract as the decay
    # split: if this fails the file rides in the main commit under the
    # honest `sleep/state` trigger from `_infer_trigger_for_path`.
    from api.services import state_dictionary

    if (memory_path / state_dictionary.STATE_FILENAME).exists():
        try:
            porcelain = await git_service.porcelain_status(memory_path)
            if any(line[3:].strip() == state_dictionary.STATE_FILENAME for line in porcelain.splitlines()):
                state_message = git_service.build_commit_message(
                    f"State snapshot {date_str}",
                    [f"{state_dictionary.STATE_FILENAME}: updated (trigger: sleep/state)"],
                    authors=["cicada"],
                )
                async with _lock:
                    await git_service.commit_paths(memory_path, state_message, [state_dictionary.STATE_FILENAME])
        except Exception as exc:
            logger.warning(f"G53 state split failed — folding _state.md into the main commit: {type(exc).__name__}: {exc}")
```

In `_infer_trigger_for_path` (`:1731`) add before the `hubs/` line: `if path == "_state.md": return "sleep/state"`.

- [ ] **Step 4: `api/routers/state.py` and the mount**

```python
"""``GET /state`` — the live state dictionary as an object (G53).

The on-disk frontmatter of ``<bank>/_state.md`` is the wire shape, verbatim
and snake_case: one documented schema, read the same way by the API, the MCP
server and any harness that ``cat``s the file. Two things are added per
request and never persisted: ``resumable`` on each conversation (G48 — a
transcript can be retention-cleaned behind our back, so it is an ``isfile``
per request through the same seam ``/conversations/recent`` uses) and
``stale`` (the file's ``inputs_version`` no longer matches the bank).

Reads regenerate lazily (R4): an inbox resolution or an agentic write
changed an input, so the first read afterwards rebuilds — cheaply, carrying
the previous repo blocks over. ``?refresh=true`` forces a rebuild with live
repo probes (bounded, ``state_dictionary.REPO_BUDGET_S``). Neither read
commits: Sleep's tail owns the ``cicada`` commit (R2), and ``_finalize``
splits a dirty projection out of any model commit (R3).

ETag (R9): the same components the file is built from plus the file's own
mtime, so a 304 is exactly "nothing you would see has changed". Bearer-gated
like every route outside ``auth._OPEN_PATHS``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.services import state_dictionary, sync_service
from api.services.repo_context import resolve_repo_context

router = APIRouter()

# Injectable seam (tests): the live git prober behind `?refresh=true`.
repo_resolver = resolve_repo_context


def _state_mtime_ns(settings: Settings) -> int:
    try:
        return state_dictionary.state_path(settings.memory_path).stat().st_mtime_ns
    except OSError:
        return 0


@router.get("/state")
async def get_state(
    request: Request,
    response: Response,
    refresh: bool = Query(False),
    settings: Settings = Depends(get_settings),
):
    memory_path = settings.memory_path
    # `connected` is filled by `refresh` from the registry's cache (R7) —
    # the same helper Sleep's tail uses, so a read never rewrites the file
    # just because the two writers named different connection lists.
    await run_in_threadpool(
        state_dictionary.refresh, memory_path, settings,
        force=refresh, probe_repos=refresh, repo_resolver=repo_resolver if refresh else None,
    )
    etag = sync_service.etag_for(
        memory_path, "entities", "inbox", "episodes", "git_head", extra=f"state={_state_mtime_ns(settings)}"
    )
    if (early := sync_service.conditional(request, response, etag)) is not None:
        return early
    state = await run_in_threadpool(state_dictionary.read_state, memory_path)
    if state is None:
        raise HTTPException(404, "this bank has no _state.md yet and it could not be generated")

    from api.routers import conversations as conv
    from api.services import session_stats

    project_dirs = {
        cid: group.get("project_dir")
        for cid, group in (await run_in_threadpool(session_stats._group, memory_path)).items()
    } if state.get("conversations") else {}
    for row in state.get("conversations", []) or []:
        row["resumable"] = bool(conv.transcript_exists(project_dirs.get(row["id"]), row["id"]))
    state["stale"] = state.get("inputs_version") != state_dictionary.inputs_version(memory_path)
    state.pop("body", None)
    return state
```

`session_stats._group` is the existing private grouper (`session_stats.py:75`) that returns `project_dir` — the resume endpoint reads it the same way; it is never serialised (the loop only feeds the `isfile` probe).

In `api/main.py`: add `state,` to the `from api.routers import (…)` list (alphabetical, after `sources`) and `app.include_router(state.router, tags=["state"])` after the `sources` line (`:168`).

- [ ] **Step 5: Inbox hook**

In `api/services/inbox_service.py` `resolve`, after the `await git_service.commit_resolution(...)` call (`:542-548`) and before `return {"status": "resolved", "id": item_id}`:

```python
    # G53 (R4) — the pending count just changed; refresh the projection
    # cheaply (no repo probes, previous blocks carried over). Best-effort:
    # a projection failure never fails a person's answer.
    try:
        from starlette.concurrency import run_in_threadpool

        from api.services import state_dictionary

        await run_in_threadpool(state_dictionary.refresh, settings.memory_path, settings, probe_repos=False)
    except Exception as exc:
        logger.warning(f"state refresh after resolution skipped: {type(exc).__name__}: {exc}")
```

`inbox_service.py` imports stdlib `logging`, not loguru (`:10-18`): add `from loguru import logger` beside the other imports — every other service logs through loguru, and the tail test's loguru sink pattern is how a warning here would be asserted.

**Superseded by the final review (2026-09-03):** the disclosure below was reproduced to be the wrong call — the dirty projection landed in the NEXT resolution's `Cicada-Author: user` commit (13 lines of `_state.md`), not in Sleep's tail. Every regeneration now commits itself via `state_dictionary.refresh_and_commit`; the paragraph is kept as the record of what was measured. ~~**Disclosed, not fixed (same class as G85's path-granular asymmetry):**~~ `commit_resolution` is `git add -A` by contract (`inbox_service.py:231`), so a projection left dirty by an earlier `GET /state` rides in that `Cicada-Author: user` commit; and this refresh runs AFTER the commit, so its own rewrite stays dirty until Sleep's tail commits it as `cicada` (R2). A projection in a user-action commit carries no belief and the R3 rail is about MODEL commits — accepted rather than reordered, because running the refresh before the commit would attribute the projection to the person's answer instead.

- [ ] **Step 6: Run the new tests, then every Sleep/provenance/inbox suite that inspects commits**

Run: `cd <worktree>/ && api/.venv/bin/python -m pytest api/tests/test_state_wiring.py api/tests/test_state_dictionary.py api/tests/test_sleep_connector_poll.py api/tests/test_sleep_feed_poll.py api/tests/test_sleep_cycle_logo_warmup.py api/tests/test_sleep_engine_state.py api/tests/test_sleep_link_backfill.py api/tests/test_agent_provenance.py api/tests/test_sleep_control.py api/tests/test_sleep_resumable.py api/tests/test_inbox_resolve_claims.py api/tests/test_inbox_resolution_provenance.py api/tests/test_feedback_ledger.py api/tests/test_sync.py api/tests/test_auth.py -q -p no:cacheprovider`
Expected: all PASS except the one pre-existing order-dependent `test_agent_provenance` failure (confirm it fails identically on `git stash`; it must not be a new failure). Exactly two existing tests assert an EXACT commit count after a full `sleep_cycle.run` on a real-git bank and now see one extra `State snapshot` commit — the intended behaviour change; update these two (and only these) and say so in the commit body:
- `api/tests/test_sleep_control.py:173` (a cancelled cycle): `== 1` → `== 2`, and add `assert _git(memory, "log", "-1", "--format=%s").startswith("State snapshot ")` — the tree stays clean because `commit_paths` stages only the projection, so the `status --porcelain` assertion above it is unchanged.
- `api/tests/test_sleep_connector_poll.py:240-241`: `== 3` → `== 4` (message: `seed + Sleep cycle + State snapshot + Sources ingest`) and unpack `_seed_hash, sleep_hash, _state_hash, sources_hash = hashes` — the snapshot lands between the Sleep commit and the connector's because the tail refreshes FIRST (R2); the later `sleep_message`/`sources_message` assertions are untouched.
`api/tests/test_sleep_cycle_logo_warmup.py:104` is unaffected: the question refresh still commits last and both commits are `cicada`. A test whose bank is not a git repo is unaffected (`commit_paths` raises, the tail logs and continues).

- [ ] **Step 7: Commit**

```bash
cd <worktree>/ && git add api/services/sleep_cycle.py api/routers/state.py api/main.py api/services/inbox_service.py api/tests/test_state_wiring.py && git commit -m "feat(state): Sleep tail regenerates+commits _state.md as cicada, _finalize split, GET /state with lazy refresh (G53)"
```

---

### Task 3: The handshake — `handshake.py`, `GET /handshake`, telemetry kind

**Files:**
- Create: `api/services/handshake.py`
- Modify: `api/services/telemetry.py:21-31`, `api/services/consumption_stats.py:213`, `api/routers/state.py` (add `/handshake`)
- Test: `api/tests/test_handshake.py` (new)

**Interfaces:**
- `handshake.variant_for(client_name: str | None) -> str` (`claude-code | codex | generic`).
- `handshake.build(state: dict | None, *, variant: str, bank: str) -> str` — pure.
- `handshake.load_or_build(memory_path, client_name=None, *, cache_dir=None) -> tuple[str, dict]` — text + `meta {variant, state_present, state_age_hours, cached}`; reads `_state.md` as-is (never refreshes), caches under `$CICADA_HOME/handshake/`.
- `handshake.record(delivery, meta, *, bank, harness=None, client_name=None) -> None` — the ledger event (R14); never raises.
- `handshake.HOOK_POINTER: str` — one line.
- `handshake.CONTRACT_VERSION = 1`, `handshake.MAX_TOKENS = 1800`.
- `GET /handshake?client=<name>` → `{"text", "variant", "state_present", "hook_pointer"}`.

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_handshake.py
"""G75 — the connection handshake: what Cicada is, the contract, the now-view.

Generated from `_state.md` plus a fixed contract, no LLM, ≤ 1,800 tokens by
the chars/4 proxy (R10), cached under a tmp CICADA_HOME, and honest when
there is no state yet. Fixtures synthetic; no owner name anywhere."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from _synthetic_bank import _bank, _ok_repo, _settings

from api import config, main
from api.services import handshake, state_dictionary, telemetry

TODAY = date(2026, 9, 3)
NOW = datetime(2026, 9, 3, 10, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _tmp_home(tmp_path, monkeypatch):
    # `_with_state` -> `inputs_version` -> `sync_service.components()` stats
    # `cicada_home()`; the tests below that need the ledger re-set it
    # themselves to the same directory. Never the real `~/.cicada`.
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))


def _with_state(tmp_path):
    memory = _bank(tmp_path)
    state_dictionary.refresh(memory, _settings(memory), force=True, today=TODAY, now=NOW, repo_resolver=_ok_repo)
    return memory


def test_variant_for():
    assert handshake.variant_for("claude-code") == "claude-code"
    assert handshake.variant_for("Claude Code") == "claude-code"
    assert handshake.variant_for("codex-cli") == "codex"
    assert handshake.variant_for("cursor") == "generic"
    assert handshake.variant_for(None) == "generic"


def test_build_carries_contract_state_and_capabilities(tmp_path):
    memory = _with_state(tmp_path)
    state = state_dictionary.read_state(memory)
    text = handshake.build(state, variant="claude-code", bank="memory")
    # what Cicada is + the contract
    assert text.startswith("# Cicada")
    assert "cicada_recall" in text and "cicada_check_nudges(entity_ids=" in text
    assert "at most one question per turn" in text and "skip=true" in text
    assert "Recommended" in text and "Cause" in text and "normalization" in text
    assert "cicada_write_claim" in text and "evidence" in text and "sources" in text
    assert state_dictionary.WORLD_FACTS_NOTE in text
    # the now-view
    assert "`alpha-project`" in text and "feat/x" in text
    assert "inbox: 1 pending" in text
    assert "11111111-2222-4333-8444-555555555555" in text and "claude --resume" in text
    # capability notes
    assert "decay_class" in text and "/episodes/{id}/span" in text
    assert "resum" in text.lower()
    # budget
    assert len(text) // 4 <= handshake.MAX_TOKENS, len(text)


def test_variants_share_the_contract_and_differ_only_in_the_prelude(tmp_path):
    memory = _with_state(tmp_path)
    state = state_dictionary.read_state(memory)
    texts = {v: handshake.build(state, variant=v, bank="memory") for v in handshake.VARIANTS}
    contracts = {v: t.split("## Contract", 1)[1] for v, t in texts.items()}
    assert len(set(contracts.values())) == 1
    assert "CICADA_SESSION_ID" in texts["codex"] and "CICADA_SESSION_ID" in texts["generic"]
    assert "~/.claude/skills/cicada" in texts["claude-code"]
    for t in texts.values():
        assert len(t) // 4 <= handshake.MAX_TOKENS


def test_no_state_degrades_to_the_static_contract(tmp_path):
    text = handshake.build(None, variant="generic", bank="memory")
    assert "## Contract" in text and "no `_state.md` yet" in text
    assert "GET /state?refresh=true" in text
    assert len(text) // 4 <= handshake.MAX_TOKENS


def test_never_secrets_never_transcripts(tmp_path, monkeypatch):
    memory = _with_state(tmp_path)
    text = handshake.build(state_dictionary.read_state(memory), variant="generic", bank="memory")
    assert "user: plan alpha" not in text
    assert "sk-" not in text and "@" not in text.replace("@feat/x", "")


def test_load_or_build_caches_on_state_mtime(tmp_path, monkeypatch):
    memory = _with_state(tmp_path)
    cache = tmp_path / "home" / "handshake"
    text1, meta1 = handshake.load_or_build(memory, "claude-code", cache_dir=cache)
    assert meta1["cached"] is False and meta1["state_present"] is True and meta1["variant"] == "claude-code"
    assert (cache / "memory.claude-code.json").exists()
    text2, meta2 = handshake.load_or_build(memory, "claude-code", cache_dir=cache)
    assert meta2["cached"] is True and text2 == text1
    # a rebuilt state invalidates
    (memory / "inbox" / "inbox-001.md").unlink()
    state_dictionary.refresh(memory, _settings(memory), force=True, today=TODAY, now=NOW.replace(hour=12), repo_resolver=_ok_repo)
    text3, meta3 = handshake.load_or_build(memory, "claude-code", cache_dir=cache)
    assert meta3["cached"] is False and "inbox: 0 pending" in text3


def test_hook_pointer_is_one_portable_line():
    assert "\n" not in handshake.HOOK_POINTER and len(handshake.HOOK_POINTER) < 300
    assert "cicada_handshake" in handshake.HOOK_POINTER and "/handshake" in handshake.HOOK_POINTER
    assert "/Users/" not in handshake.HOOK_POINTER


def test_record_is_ids_and_enums_only(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    handshake.record("tool", {"variant": "codex", "state_present": True, "state_age_hours": 3},
                     bank="memory", harness="codex", client_name="codex-cli")
    events = telemetry.read_events()
    assert len(events) == 1 and events[0].kind == "handshake"
    ev = events[0]
    assert ev.connection is None and ev.billing == "free" and ev.bank == "memory"
    assert ev.stage == "handshake"  # its own by_stage row, never a borrowed Sleep stage name
    assert ev.refs == {"delivery": "tool", "variant": "codex", "state_present": True,
                       "state_age_hours": 3, "harness": "codex", "client_name": "codex-cli"}
    assert "handshake" in telemetry.KINDS and "handshake" in telemetry.NON_SPEND_KINDS


def test_handshake_events_never_show_as_an_unknown_connection(tmp_path, monkeypatch):
    """R14 — the same reasoning as G113 R7: a `handshake` row has no
    connection and no spend, so `by_connection` must not invent "unknown"."""
    import asyncio

    from api.services import consumption_stats
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    handshake.record("http", {"variant": "generic", "state_present": False, "state_age_hours": None}, bank="memory")
    out = asyncio.run(consumption_stats.stats(tmp_path / "memory", range_="30d", today=date.today()))
    assert out["by_connection"] == []
    assert [row["bank"] for row in out["by_bank"]] == ["memory"]  # still visible where it is informative


@pytest.fixture
def api_bank(tmp_path: Path, monkeypatch) -> Path:
    memory = _with_state(tmp_path)
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.delenv("CICADA_API_TOKEN", raising=False)
    monkeypatch.setattr(state_dictionary, "REPO_BUDGET_S", 0.0)
    config.get_settings.cache_clear()
    yield memory
    config.get_settings.cache_clear()


def test_get_handshake_route(api_bank):
    with TestClient(main.app) as client:
        r = client.get("/handshake", params={"client": "codex"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["variant"] == "codex" and data["state_present"] is True
    assert data["text"].startswith("# Cicada") and data["hook_pointer"] == handshake.HOOK_POINTER
```

`consumption_stats.stats(memory_path, *, range_, today)` (`consumption_stats.py:188`) is async and groups `by_connection` from `spend` (`:213`) with `_group`'s `"unknown"` fallback for a `None` key (`:170`) — the assertion above is exactly what R14's `NON_SPEND_KINDS` change makes true.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd <worktree>/ && api/.venv/bin/python -m pytest api/tests/test_handshake.py -q -p no:cacheprovider`
Expected: FAIL — `ImportError: cannot import name 'handshake'`.

- [ ] **Step 3: Telemetry kind**

In `api/services/telemetry.py:21-31`:

```python
KINDS = (
    "llm_call", "sleep_run", "agentic_write", "ask", "import", "throttle",
    "resolution", "audit", "dedup_verdict", "handshake",
)
# …(existing FEEDBACK_KINDS comment + tuple unchanged)…
# G75: whether an agent ever RECEIVED the primer is the same class of
# question G105 asked about capture (0 MCP invocations in 12 days). A
# `handshake` row is ids/enums only (delivery, variant, state_present,
# state_age_hours, harness, client_name) and carries no spend, so it joins
# the feedback kinds in being excluded from connection/cost rollups.
NON_SPEND_KINDS = FEEDBACK_KINDS + ("handshake",)
```

In `api/services/consumption_stats.py:213` change `telemetry.FEEDBACK_KINDS` → `telemetry.NON_SPEND_KINDS` and extend the comment above it with "(and `handshake`, G75)".

- [ ] **Step 4: Implement `api/services/handshake.py`**

```python
"""The connection handshake (G75): Cicada teaches an agent how to use it.

The MCP ``initialize`` result carries an optional ``instructions`` string
("a hint to the model … MAY be added to the system prompt" — MCP schema
2024-11-05 and later). Until G75 Cicada returned none; G48 only captured
the INBOUND ``clientInfo``. This module builds the outbound half, and the
same text is served by the ``cicada_handshake`` tool (harnesses that drop
``instructions``) and ``GET /handshake`` (the app, AGENTS.md pointers, the
G49/G76 SessionStart hook — out of scope here beyond ``HOOK_POINTER``).

Shape: what Cicada is (3 lines) → a 2–3 line per-harness prelude (R11) →
the contract → the now-view from ``_state.md`` → capability notes. The
contract's inbox paragraph is FIXED BY G115 (quoted verbatim from the G75
row); the G121 sentence comes from ``state_dictionary.WORLD_FACTS_NOTE`` so
there is exactly one source. Zero LLM, ≤ ``MAX_TOKENS`` by the chars/4
proxy (R10 — no tokenizer, the suite is offline), cached under
``$CICADA_HOME/handshake/<bank>.<variant>.json`` keyed on the state file's
mtime+size and ``CONTRACT_VERSION``. Reads ``_state.md`` as it is (R4): a
stale file is served with its ``generated_at``; no file at all degrades to
the static contract plus a one-line "no state yet" note.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from api.services import state_dictionary

CONTRACT_VERSION = 1
MAX_TOKENS = 1800
VARIANTS = ("claude-code", "codex", "generic")

HOOK_POINTER = (
    "Cicada memory is connected: before anything else call the `cicada_handshake` MCP tool "
    "(or GET http://127.0.0.1:8000/handshake with the bearer token in $CICADA_HOME/api_token) "
    "and follow the contract it returns."
)

_WHAT = (
    "# Cicada — personal memory for this person\n"
    "Cicada is a git-versioned markdown knowledge graph of what this person said, did and decided, "
    "consolidated nightly from captured conversations (Sleep) and readable now through these tools. "
    "Beliefs carry provenance (who observed it, from which conversation, which model wrote it) and fade "
    "when unmentioned — silence is a signal, not an error."
)

_PRELUDE = {
    "claude-code": (
        "## Claude Code\n"
        "- Your session id is stamped on every episode you save; this conversation is resumable later with "
        "`claude --resume <id>`.\n"
        "- The `cicada` skill (~/.claude/skills/cicada) is the long-form policy; this text is the contract."
    ),
    "codex": (
        "## Codex\n"
        "- Set `CICADA_SESSION_ID` (and `CICADA_SESSION_HARNESS=codex`) in the MCP env so your episodes group as "
        "one conversation; Codex sessions are not resumable from Cicada.\n"
        "- AGENTS.md points here; there is no separate policy file."
    ),
    "generic": (
        "## Your harness\n"
        "- Set `CICADA_SESSION_ID` (and `CICADA_SESSION_HARNESS`) in the MCP env so your episodes group as one "
        "conversation; without it Cicada mints a per-process id that never resumes.\n"
        "- The tools are the whole interface; nothing needs a file on disk."
    ),
}

# G115 discipline — verbatim from the G75 row. Copy, not filter: the server-
# side gate is G115 Phase 2 and does not depend on this being read.
_CONTRACT = (
    "## Contract\n"
    "1. Recall first: `cicada_recall(query)` at the start of a topic, `cicada_recall_detail(id)` for a page, "
    "`cicada_ask` for a direct factual question. State only what the tools returned.\n"
    "2. After `cicada_recall`, call `cicada_check_nudges(entity_ids=<recall ids>)`; at most one question per "
    "turn, after the user's request is done; quote the Cause line; Recommended first; never a blocking question "
    "at the end of an unrelated turn; `skip=true` when unanswered and never re-ask that session; resolve only "
    "with the person's own answer; say what changed in one line; `normalization` items are app-only and the "
    "ask path never returns them.\n"
    "3. Save as you learn: `cicada_save_episode(content, title)` for a decision, plan or fact worth keeping; "
    "`cicada_save_url` for a link.\n"
    "4. Write facts as claims: `cicada_write_claim(subject, predicate, object, evidence=[{episode, quote}], "
    "sources=[url])` — quote the exact words you relied on, and give `sources` for anything you looked up.\n"
    f"5. {state_dictionary.WORLD_FACTS_NOTE}\n"
    "6. Ask before assuming: a pending clarification on an entity you are about to use means the person has "
    "not settled it — ask in flow, do not guess.\n"
    "7. Never edit `entities/`, `hubs/` or `_index.md` directly; every write goes through a tool so provenance "
    "and dedup hold."
)

_CAPABILITIES = (
    "## Capabilities\n"
    "- Resume: Claude Code sessions resume with `claude --resume <id>` (POST /conversations/{id}/resume "
    "validates it); other harnesses group but do not resume.\n"
    "- Decay: every entity has a `decay_class` (evergreen | durable | active | volatile); a claim's evidence is a "
    "span, readable via GET /episodes/{id}/span?start=&end=&hash=.\n"
    "- Repos: `cicada_repo_context(entity_id|path)` returns live git state on demand; the branches below are as "
    "of `repos_probed_at`.\n"
    "- Map: `cicada_open_hub('projects')` etc. walks `_index.md` → hubs → entities without search."
)


def variant_for(client_name: str | None) -> str:
    name = (client_name or "").strip().lower()
    if "claude" in name:
        return "claude-code"
    if "codex" in name:
        return "codex"
    return "generic"


def _now_block(state: dict | None, bank: str) -> str:
    if state is None:
        return (
            "## Now\n"
            f"- Bank `{bank}` has no `_state.md` yet — run a Sleep cycle or `GET /state?refresh=true` "
            "to generate the now-view; the contract above still applies."
        )
    eng = state.get("engine") or {}
    slp = state.get("sleep") or {}
    inb = state.get("inbox") or {}
    lines = [
        "## Now",
        f"- Bank `{state.get('bank', bank)}` · engine {eng.get('engine')} ({eng.get('model') or 'unset'}) · "
        f"inbox: {inb.get('pending', 0)} pending · Sleep queue {slp.get('queue_depth', 0)} · "
        f"last Sleep {slp.get('last_at') or 'never'} · as of {state.get('generated_at')}",
    ]
    if state.get("owner_id"):
        lines.append(f"- The person's own entity: `{state['owner_id']}`.")
    projects = state.get("projects") or []
    lines.append("- Current projects:" if projects else "- No active projects recorded yet.")
    for p in projects:
        repos = ", ".join(
            f"{r['path']}@{r.get('branch')}" + (f" dirty {r['dirty']}" if r.get("dirty") else "")
            for r in p.get("repos", []) if r.get("state") == "ok"
        )
        tail = f" — {p['one_liner']}" if p.get("one_liner") else ""
        lines.append(f"  - `{p['id']}` {p['name']}{tail}" + (f" [{repos}]" if repos else ""))
    people = state.get("people") or []
    if people:
        lines.append("- People recently in play: " + ", ".join(f"`{p['id']}`" for p in people))
    convs = state.get("conversations") or []
    if convs:
        lines.append("- Recent conversations (id · harness · title):")
        for c in convs:
            lines.append(f"  - `{c['id']}` · {c.get('harness') or 'unknown'} · {c.get('title', '')}")
    prefs = state.get("preferences") or []
    if prefs:
        lines.append("- Standing preferences: " + "; ".join(p.get("one_liner") or p["name"] for p in prefs))
    return "\n".join(lines)


def build(state: dict | None, *, variant: str, bank: str) -> str:
    variant = variant if variant in VARIANTS else "generic"
    parts = [_WHAT, _PRELUDE[variant], _CONTRACT, _now_block(state, bank), _CAPABILITIES]
    text = "\n\n".join(parts)
    if len(text) // 4 > MAX_TOKENS and state is not None:
        # The state block is the only elastic part: drop people, then
        # preferences, then conversations, then project one-liners.
        slim = dict(state)
        for key in ("people", "preferences", "conversations"):
            slim[key] = []
            text = "\n\n".join([_WHAT, _PRELUDE[variant], _CONTRACT, _now_block(slim, bank), _CAPABILITIES])
            if len(text) // 4 <= MAX_TOKENS:
                return text
        slim["projects"] = [{**p, "one_liner": ""} for p in slim.get("projects", [])]
        text = "\n\n".join([_WHAT, _PRELUDE[variant], _CONTRACT, _now_block(slim, bank), _CAPABILITIES])
    return text


def _cache_dir() -> Path:
    from api.services.auth import cicada_home

    return cicada_home() / "handshake"


def _state_age_hours(state: dict | None) -> int | None:
    if not state or not state.get("generated_at"):
        return None
    try:
        then = datetime.fromisoformat(str(state["generated_at"]))
        if then.tzinfo is None:
            then = then.replace(tzinfo=timezone.utc)
        return max(0, int((datetime.now(timezone.utc) - then).total_seconds() // 3600))
    except ValueError:
        return None


def load_or_build(memory_path: Path, client_name: str | None = None, *, cache_dir: Path | None = None) -> tuple[str, dict]:
    """The primer for this bank + client, from cache when the state file is unchanged.

    Never refreshes `_state.md` (R4). A cache failure of any kind falls back
    to a fresh build — the cache is a convenience, never a dependency.
    """
    memory_path = Path(memory_path)
    variant = variant_for(client_name)
    path = state_dictionary.state_path(memory_path)
    try:
        st = path.stat()
        key = f"{CONTRACT_VERSION}:{variant}:{st.st_mtime_ns}:{st.st_size}"
    except OSError:
        key = f"{CONTRACT_VERSION}:{variant}:absent"
    cache_dir = Path(cache_dir) if cache_dir is not None else _cache_dir()
    cache_file = cache_dir / f"{memory_path.name}.{variant}.json"
    state = state_dictionary.read_state(memory_path)
    meta = {"variant": variant, "state_present": state is not None, "state_age_hours": _state_age_hours(state), "cached": False}
    try:
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        if cached.get("key") == key and isinstance(cached.get("text"), str):
            meta["cached"] = True
            return cached["text"], meta
    except (OSError, ValueError):
        pass
    text = build(state, variant=variant, bank=memory_path.name)
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps({"key": key, "text": text}), encoding="utf-8")
    except OSError as exc:
        logger.debug(f"handshake cache write skipped: {exc}")
    return text, meta


def record(delivery: str, meta: dict, *, bank: str, harness: str | None = None, client_name: str | None = None) -> None:
    """One `handshake` ledger row — ids/enums only (R14). Never raises."""
    try:
        from api.services import telemetry

        telemetry.record(telemetry.UsageEvent(
            kind="handshake", stage="handshake", connection=None, engine=None, model=None, bank=bank,
            billing="free", invocations=1,
            refs={"delivery": delivery, "variant": meta.get("variant"), "state_present": bool(meta.get("state_present")),
                  "state_age_hours": meta.get("state_age_hours"), "harness": harness, "client_name": client_name},
        ))
    except Exception as exc:  # the ledger never blocks a connect
        logger.debug(f"handshake telemetry skipped: {exc}")
```

Then add to `api/routers/state.py`:

```python
@router.get("/handshake")
async def get_handshake(
    client: str | None = Query(None, max_length=64),
    settings: Settings = Depends(get_settings),
):
    """The same primer the MCP `initialize` response carries (G75), for the
    app and for AGENTS.md / SessionStart-hook pointers. `client` picks the
    per-harness prelude; the contract never varies."""
    from api.services import handshake

    text, meta = await run_in_threadpool(handshake.load_or_build, settings.memory_path, client)
    handshake.record("http", meta, bank=settings.memory_path.name, client_name=client)
    return {"text": text, "variant": meta["variant"], "state_present": meta["state_present"],
            "hook_pointer": handshake.HOOK_POINTER}
```

- [ ] **Step 5: Run the tests**

Run: `cd <worktree>/ && api/.venv/bin/python -m pytest api/tests/test_handshake.py api/tests/test_state_wiring.py api/tests/test_telemetry.py api/tests/test_consumption_stats.py api/tests/test_consumption_api.py api/tests/test_feedback_ledger.py -q -p no:cacheprovider`
Expected: all PASS. If `test_build_carries_contract_state_and_capabilities` fails the ≤ 1,800-token check, shorten `_WHAT`/`_CAPABILITIES` copy — never the G115 paragraph, which is verbatim by ruling.

- [ ] **Step 6: Commit**

```bash
cd <worktree>/ && git add api/services/handshake.py api/services/telemetry.py api/services/consumption_stats.py api/routers/state.py api/tests/test_handshake.py && git commit -m "feat(handshake): generated primer from _state.md + the contract, GET /handshake, handshake ledger kind (G75)"
```

---

### Task 4: MCP delivery — `initialize.instructions`, `cicada_handshake`, recall's `state` hint, `entity_ids`

**Files:**
- Modify: `mcp/server.py:93-95` (globals), `:184-195` (`cicada_check_nudges` schema), `:397-413` (append the tool), `:433-452` (initialize), `:525-580` (dispatch), `:1020-1037` (`_hints_block`), `:826-935` (`handle_recall`), `:1793-1844` (`handle_check_nudges`)
- Test: `api/tests/test_mcp_handshake.py` (new)

**Interfaces:**
- `server.initialize_result(params: dict) -> dict` — pure given `get_memory_path`; captures `CLIENT_INFO` (unchanged behaviour) and returns the result dict WITH `instructions`.
- `server.handle_handshake() -> str`.
- `server._hints_block(suggested, hub, members, state=None)` — `state` is an optional compact dict added under key `"state"`.
- `server._state_hint(memory_path) -> dict | None` — `{engine, pending, projects, as_of}` from `_state.md`; `None` when absent.
- `server._STATE_HINT_SENT: bool` — process flag (R13).
- `server.handle_check_nudges(topic, entity_ids=None)`.

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_mcp_handshake.py
"""G75 on the MCP surface: `initialize` returns `instructions`, the
`cicada_handshake` tool returns the same text, recall's hints carry the
now-view once per process, and `cicada_check_nudges` accepts `entity_ids`
(R12). Loads mcp/server.py the way test_mcp_inbox_questions.py does."""
from __future__ import annotations

import importlib.util
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from _synthetic_bank import _bank, _ok_repo, _settings

from api.services import markdown_parser, state_dictionary

REPO_ROOT = Path(__file__).resolve().parents[2]
TODAY = date(2026, 9, 3)
NOW = datetime(2026, 9, 3, 10, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def server():
    spec = importlib.util.spec_from_file_location("cicada_mcp_server_g75", REPO_ROOT / "mcp" / "server.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["cicada_mcp_server_g75"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def bank(tmp_path, monkeypatch, server):
    memory = _bank(tmp_path)
    state_dictionary.refresh(memory, _settings(memory), force=True, today=TODAY, now=NOW, repo_resolver=_ok_repo)
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_TELEMETRY", "off")
    monkeypatch.setattr(server, "get_memory_path", lambda: memory)
    monkeypatch.setattr(server, "_STATE_HINT_SENT", False)
    server.CLIENT_INFO.clear()
    return memory


def test_initialize_returns_instructions_and_captures_client_info(server, bank):
    result = server.initialize_result({"clientInfo": {"name": "claude-code", "version": "2.1"}})
    assert result["protocolVersion"] == "2024-11-05"
    assert result["serverInfo"]["name"] == "cicada-bookworm"
    assert server.CLIENT_INFO == {"name": "claude-code", "version": "2.1"}
    text = result["instructions"]
    assert text.startswith("# Cicada") and "## Claude Code" in text
    assert "`alpha-project`" in text and "cicada_check_nudges(entity_ids=" in text
    assert len(text) // 4 <= 1800


def test_initialize_without_client_info_is_generic(server, bank):
    result = server.initialize_result({})
    assert "## Your harness" in result["instructions"]


def test_initialize_with_no_state_file_still_answers(server, bank):
    (bank / "_state.md").unlink()
    result = server.initialize_result({"clientInfo": {"name": "codex-cli"}})
    assert "## Contract" in result["instructions"] and "no `_state.md` yet" in result["instructions"]


def test_handshake_tool_returns_the_same_text(server, bank):
    server.initialize_result({"clientInfo": {"name": "codex-cli"}})
    via_init = server.initialize_result({"clientInfo": {"name": "codex-cli"}})["instructions"]
    assert server.handle_tool("cicada_handshake", {}) == via_init
    tools = {t["name"]: t for t in server.TOOLS}
    assert "cicada_handshake" in tools and "instructions" in tools["cicada_handshake"]["description"]


def test_recall_hints_carry_the_state_once_per_process(server, bank, monkeypatch):
    monkeypatch.setattr(server, "_leann_search_entities", lambda *a, **k: [])
    monkeypatch.setattr(server, "_leann_search_episodes", lambda *a, **k: [])
    first = server.handle_recall("alpha project")
    assert "`" * 3 + "cicada-hints" in first
    assert '"state"' in first and '"alpha-project"' in first and '"pending": 1' in first
    second = server.handle_recall("alpha project")
    assert '"state"' not in second, "the cursor rides once per conversation"


def test_recall_with_nothing_to_suggest_emits_no_hints_block(server, bank, monkeypatch):
    monkeypatch.setattr(server, "_leann_search_entities", lambda *a, **k: [])
    monkeypatch.setattr(server, "_leann_search_episodes", lambda *a, **k: [])
    out = server.handle_recall("zzzz-nothing-matches-this")
    assert "`" * 3 + "cicada-hints" not in out
    assert server._STATE_HINT_SENT is False, "an unsent cursor is not consumed"


def test_check_nudges_accepts_entity_ids(server, bank):
    markdown_parser.write(bank / "inbox" / "inbox-003.md",
                          {"kind": "decay", "status": "pending", "entity_id": "bob-example",
                           "entity_name": "Bob Example", "title": "Still in touch with Bob?", "created_date": "2026-08-01"}, "c")
    out = server.handle_tool("cicada_check_nudges", {"entity_ids": ["bob-example"]})
    assert "inbox-003" in out and "inbox-001" not in out
    schema = {t["name"]: t for t in server.TOOLS}["cicada_check_nudges"]["inputSchema"]
    assert schema["properties"]["entity_ids"]["type"] == "array"
    both = server.handle_tool("cicada_check_nudges", {})
    assert "inbox-001" in both and "inbox-003" in both
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd <worktree>/ && api/.venv/bin/python -m pytest api/tests/test_mcp_handshake.py -q -p no:cacheprovider`
Expected: FAIL — `AttributeError: module has no attribute 'initialize_result'`.

- [ ] **Step 3: Implement**

1. Below `CLIENT_INFO: dict = {}` (`mcp/server.py:95`) add:

```python
# G53/G75 (R13): recall's `cicada-hints` carries the now-view ONCE per
# process — stdio MCP is one process per conversation (G48), so a module
# flag IS "once per conversation", the same shape G115's ask gate uses.
_STATE_HINT_SENT: bool = False
```

2. Append to `TOOLS` (after the `cicada_repo_context` entry, `:413`):

```python
    {
        "name": "cicada_handshake",
        "description": "Return Cicada's connection primer: what Cicada is, the interaction contract (recall first, check nudges after recall, save episodes as you learn, write claims with evidence and sources, world facts are a cache), the bank's now-view (engine, current projects with live branches, pending inbox count, recent conversations with resume handles) and capability notes. Identical to the `instructions` field of the MCP initialize response — call it once at the start of a conversation if your harness does not surface server instructions. No arguments.",
        "inputSchema": {"type": "object", "properties": {}},
    },
```

3. In the `cicada_check_nudges` tool (`:184-195`) add to `properties`:

```python
                "entity_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional entity ids (the `suggested_entities` from cicada_recall's hints) — only items whose entity_id is in this list are returned. Combine with topic freely.",
                },
```

and extend the description with: " After `cicada_recall`, pass its suggested entity ids as `entity_ids`."

4. Replace the `initialize` branch of `main()` (`:433-452`) body with `respond(req_id, initialize_result(params))` and add, above `main()`:

```python
def initialize_result(params: dict) -> dict:
    """The MCP `initialize` result — G48's inbound capture plus G75's outbound primer.

    `instructions` is the spec's optional hint-to-the-model field (schema
    2024-11-05: "MAY be added to the system prompt"). It is the SAME text
    `cicada_handshake` returns, built from `_state.md` as it is on disk —
    never refreshed here (R4): connect latency is one file read, and a
    stale now-view says so via its `generated_at`. Any failure to build it
    degrades to no `instructions` at all rather than a failed connect.
    """
    client = params.get("clientInfo")
    if isinstance(client, dict):
        CLIENT_INFO.clear()
        CLIENT_INFO.update({
            "name": str(client.get("name") or "")[:64],
            "version": str(client.get("version") or "")[:32],
        })
    result = {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "cicada-bookworm", "version": "0.1.0"},
    }
    try:
        result["instructions"] = _handshake_text(delivery="initialize")
    except Exception as exc:  # never fail a connect over a primer
        print(f"cicada-mcp: handshake unavailable: {exc}", file=sys.stderr)
    return result


def _handshake_text(*, delivery: str) -> str:
    from api.services import handshake

    memory_path = get_memory_path()
    text, meta = handshake.load_or_build(memory_path, CLIENT_INFO.get("name"))
    handshake.record(delivery, meta, bank=memory_path.name, harness=SESSION.harness,
                     client_name=CLIENT_INFO.get("name") or None)
    return text


def handle_handshake() -> str:
    """`cicada_handshake` — the primer for harnesses that drop `instructions`."""
    return _handshake_text(delivery="tool")
```

5. In `handle_tool` (`:525`): `elif name == "cicada_handshake": return handle_handshake()`, and change the `cicada_check_nudges` branch to `return handle_check_nudges(arguments.get("topic"), arguments.get("entity_ids"))`.

6. `handle_check_nudges(topic: str | None, entity_ids: list | None = None)` (`:1793`): normalise `wanted = {str(e).strip() for e in (entity_ids or []) if str(e).strip()}` and, inside the loop right after `fm, body = parse_frontmatter(content)`, add `if wanted and str(fm.get("entity_id") or "") not in wanted: continue`. Update the docstring: "`entity_ids` (G75 R12) is an exact-match filter on `entity_id` so the primer's `cicada_check_nudges(entity_ids=<recall ids>)` is executable today; the G115 Phase 2 gate (mode, vector score, asked set, cap) is not this."

7. `_hints_block(suggested_entities, relevant_hub, hub_members, state=None)` (`:1020`): keep the early `return ""`; add `if state: payload["state"] = state` before the `return`. Add:

```python
def _state_hint(memory_path: Path) -> dict | None:
    """Compact now-view for `cicada-hints.state` (G53): engine, pending count,
    current project ids, and when it was generated. Read-only — never
    regenerates (R4)."""
    from api.services import state_dictionary

    state = state_dictionary.read_state(memory_path)
    if not state:
        return None
    return {
        "engine": (state.get("engine") or {}).get("engine"),
        "pending": (state.get("inbox") or {}).get("pending", 0),
        "projects": [p["id"] for p in state.get("projects") or []],
        "as_of": state.get("generated_at"),
        "next_tool": "cicada_handshake",
    }
```

In `handle_recall` (`:864-870`), replace the two hint lines with:

```python
    global _STATE_HINT_SENT
    state_hint = None if _STATE_HINT_SENT else _state_hint(memory_path)
    hints_block = _hints_block(suggested, relevant_hub, hub_member_ids, state=state_hint)
    if hints_block:
        output_parts.append(hints_block)
        if state_hint is not None:
            _STATE_HINT_SENT = True
```

- [ ] **Step 4: Run the MCP suites**

Run: `cd <worktree>/ && api/.venv/bin/python -m pytest api/tests/test_mcp_handshake.py api/tests/test_mcp_inbox_questions.py api/tests/test_mcp_tool_descriptions.py api/tests/test_mcp_recall_fusion.py api/tests/test_mcp_recall_episode_fallback.py api/tests/test_mcp_sources_tool.py api/tests/test_mcp_perspective.py api/tests/test_session_identity.py api/tests/test_evidence_agent_writes.py -q -p no:cacheprovider`
Expected: all PASS. `test_mcp_recall_fusion` asserts on the hints JSON — a `state` key is additive; if a test compares the whole payload for equality, its bank has no `_state.md`, so `state` is absent and the comparison still holds.

- [ ] **Step 5: Smoke the real stdio loop once (no bank read: an empty tmp bank)**

```bash
cd <worktree>/ && mkdir -p "$TMPDIR/cicada-hs-smoke/entities" && CICADA_MEMORY_PATH="$TMPDIR/cicada-hs-smoke" CICADA_HOME="$TMPDIR/cicada-hs-home" CICADA_TELEMETRY=off printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}' | api/.venv/bin/python mcp/server.py | api/.venv/bin/python -c "import json,sys; r=json.loads(sys.stdin.readline())['result']; assert r['instructions'].startswith('# Cicada'), r; print('instructions ok', len(r['instructions'])//4, 'tokens')"
```
Expected: `instructions ok <n> tokens` with `n ≤ 1800`.

- [ ] **Step 6: Commit**

```bash
cd <worktree>/ && git add mcp/server.py api/tests/test_mcp_handshake.py && git commit -m "feat(mcp): initialize returns instructions, cicada_handshake tool, one-shot state cursor in recall hints, entity_ids on check_nudges (G75)"
```

---

### Task 5: Docs and skills — CLAUDE.md, backlog rows, TODO handoff, SKILL.md

**Files:**
- Modify: `CLAUDE.md` (new section before `### Save-with-reason (G71)` at `:394`; API list near `:702`; MCP section `:595`; trigger-types line and the `cicada` author paragraph in `### Git (Versioning & Provenance)` `:504+`)
- Modify: `docs/goals/memory-evolution.md:605` (G53), `:637` (G75) — targeted string replace, never retyped
- Modify: `docs/goals/TODO.md` (Where things stand, Shipped, Wave C item 10, Pick up here item 5, `_Last synced_`)
- Modify: `SKILL.md:15-22`, `skills/cicada-librarian/SKILL.md` (one pointer line)

**Interfaces:** prose only. Everything asserted must be true of Tasks 1–4 as committed; follow the code if a name drifted.

- [ ] **Step 1: CLAUDE.md**

1. Insert before `### Save-with-reason (G71)`:

```markdown
### Live state + handshake (G53 / G75)
**`<bank>/_state.md` is the live state dictionary** — a *cursor* into the graph, never a copy of it:
YAML frontmatter (`schema_version`, `generated_at`, `inputs_version`, `bank`, optional `owner_id` (only when
`CICADA_OBSERVER_OWNER` names an entity id whose page exists — never a name in code),
`engine {mode, engine, model, connected}`, `sleep {last_at, queue_depth, next_at}`, `inbox {pending, by_kind}`,
`projects[] {id, name, one_liner, confidence, last_referenced, repos[] {path, branch, dirty, ahead_behind, state}}`,
`people[]`, `conversations[] {id, harness, title, last_seen, episode_count}`, `preferences[]` (top skill
entities), `repos_probed_at`, `world_facts_note`) plus a short wikilinked body. Written only by
`api/services/state_dictionary.refresh` — zero LLM, ≤ 6 KB, deterministic (a digest of the `entities`/`inbox`/
`episodes`/`bank` sync components — never `git_head`, whose own `State snapshot` commit would self-invalidate — is
stored as `inputs_version`; unchanged inputs mean no write, and even a forced rebuild writes only when the content
differs with `generated_at`/`repos_probed_at`/`inputs_version` masked), repo probes read-only under a
2 s total budget (`state: unavailable` past it). **Who regenerates it:** Sleep's engine-independent tail, first
step, every exit path, `force=True`, committed alone as `State snapshot <date>` / `Cicada-Author: cicada` /
trigger `sleep/state` (no engine trailer — no LLM ran); `_finalize` splits a dirty `_state.md` out of the main
commit the way G85 splits decay; `GET /state` refreshes lazily (no repo probes, previous blocks carried over) and
`?refresh=true` forces live probes; an inbox resolution refreshes best-effort. The MCP server only ever *reads*
it. `resumable` is never persisted (G48) — `GET /state` adds it per request. A reader that finds the file stale
or absent must still work: every field has a live twin (`/status`, `/inbox`, `/conversations/recent`,
`cicada_repo_context`).

**The handshake (`api/services/handshake.py`)** turns `_state.md` + a fixed contract into ≤ 1,800 tokens
(chars/4) of primer: what Cicada is, a 2–3 line per-harness prelude keyed off `clientInfo` (`claude-code` /
`codex` / `generic` — the contract never varies), the contract (recall first; `cicada_check_nudges(entity_ids=…)`
after recall with the G115 discipline verbatim; save episodes as you learn; `cicada_write_claim` with `evidence`
and `sources`; the G121 sentence from `state_dictionary.WORLD_FACTS_NOTE`; ask before assuming; never hand-edit
pages), the now-view, and capability notes (resume availability, decay classes, the span endpoint, repo context).
Cached at `$CICADA_HOME/handshake/<bank>.<variant>.json` keyed on the state file's mtime+size. **Delivered
three ways:** the MCP `initialize` result's `instructions` field (`mcp/server.py::initialize_result`), the
`cicada_handshake` tool (harnesses that drop `instructions`), and `GET /handshake?client=`. Recall's
`cicada-hints` also carries a compact `state` block once per MCP process. `handshake.HOOK_POINTER` is the one
line a SessionStart hook or AGENTS.md injects (the hook itself is G49/G76). A `handshake` telemetry row
(ids/enums only; `telemetry.NON_SPEND_KINDS`) records each delivery. `SKILL.md` points at the generated text
rather than restating the contract — one prose source.
```

2. API list (after the `GET /episodes/{id}/span` block, `:702-704`):

```
GET  /state                               → the parsed _state.md (snake_case, the on-disk schema) + per-request
                                            `resumable` and `stale`; lazy refresh; `?refresh=true` probes repos;
                                            ETag over entities/inbox/episodes/git_head + the file mtime (G53)
GET  /handshake?client=                   → {text, variant, state_present, hook_pointer} — the primer (G75)
```

3. MCP section (`:595`, the numbered list): add a line 0: "On `initialize` the server returns `instructions` — the G75 handshake — and `cicada_handshake` returns the same text on demand."

4. `**Trigger types:**` line: append `sleep/state`. In the `cicada` author paragraph (the sentence listing the maintenance writes), append ", and, every Sleep cycle, the `State snapshot` commit of `_state.md` (G53)".

- [ ] **Step 2: Backlog rows**

```bash
cd <worktree>/ && api/.venv/bin/python - <<'PY'
from pathlib import Path
p = Path("docs/goals/memory-evolution.md")
s = p.read_text()
old53 = "relates to G48, G49 (primer hook), G13, G50, context-passport roadmap. | 🔲 |"
old75 = "which G115 Phase 2 routes through the same gate. | 🔲 |"
assert s.count(old53) == 1 and s.count(old75) == 1
new53 = ("relates to G48, G49 (primer hook), G13, G50, context-passport roadmap. "
         "**Shipped 2026-09-03 (PR #TBD, `feat/state-handshake`):** `api/services/state_dictionary.py` writes `<bank>/_state.md` "
         "(schema v1: engine, sleep, inbox counts, top-N projects with bounded live repo state, people, conversations sans `resumable`, "
         "skill one-liners, the G121 sentence; ≤ 6 KB, `inputs_version`-debounced, write-if-changed); regenerated by the Sleep tail "
         "(own `cicada` commit, trigger `sleep/state`, `_finalize` split), lazily by `GET /state`, best-effort after an inbox "
         "resolution; `GET /state?refresh=true`. OPEN: G13 open tasks/ideas are not a section yet (no producer); the app's Store does "
         "not fetch `/state`. | ✅ |")
new75 = ("which G115 Phase 2 routes through the same gate. "
         "**Shipped 2026-09-03 (PR #TBD, `feat/state-handshake`):** `api/services/handshake.py` — ≤ 1,800 tokens, three variants "
         "(`claude-code`/`codex`/`generic`) over one contract, cached under `$CICADA_HOME/handshake/`; delivered as `initialize.instructions`, "
         "`cicada_handshake`, `GET /handshake`; recall hints carry a one-shot `state` block; `cicada_check_nudges` gained `entity_ids` so the "
         "discipline is executable; `handshake` ledger kind. OPEN: the SessionStart hook / plugin (G49/G76 — `handshake.HOOK_POINTER` is the "
         "line it injects); per-harness variants beyond the three; G115 Phase 2's server-side gate. | ✅ |")
p.write_text(s.replace(old53, new53).replace(old75, new75))
print("ok")
PY
```

- [ ] **Step 3: TODO.md**

1. `## Where things stand`: add a paragraph "**G53 + G75 — live state + handshake — is on `feat/state-handshake` (worktree `.worktrees/handshake`), awaiting a PR against `dev`:** `_state.md` (deterministic, `cicada`-committed by the Sleep tail), `GET /state`, `GET /handshake`, `initialize.instructions`, `cicada_handshake`. No Swift change. First thing to check on the live bank after merge: `curl -s -H "Authorization: Bearer $(cat ~/.cicada/api_token)" 'http://127.0.0.1:8000/state?refresh=true' | head -c 600` — the owner should eyeball that the projects list is the right seven."
2. `## ✅ Shipped` → **Provenance** line: append " · **G53 + G75 live state + handshake (2026-09-03, PR #TBD)** — `_state.md` cursor, `initialize.instructions`, `cicada_handshake`, `/state`, `/handshake`".
3. Wave C item `10. **G53 + G75** …` → strike (`~~…~~`) with "— shipped PR #TBD; open: SessionStart hook (G49/G76), Store fetch of `/state`".
4. `## Pick up here` item 5 → "**G105**, then **G115 Phase 2** (G53 + G75 shipped)"; item 6's "build G53/G75 and see whether the fork want survives" now has its data point — note "G53/G75 shipped; re-read G110 against the handshake before starting it".
5. Worktrees paragraph: add `.worktrees/handshake` (`feat/state-handshake`).
6. `_Last synced:` → prefix "2026-09-03 (G53+G75 on `feat/state-handshake`, PR pending); ".

- [ ] **Step 4: SKILL.md and the librarian skill**

In `SKILL.md`, replace the `## When to recall` section (`:15-22`) with:

```markdown
## Handshake first
The contract lives in one generated text: the `instructions` your harness received
from the Cicada MCP server on connect, or `cicada_handshake()` if it did not surface
them. Read it once per conversation — it carries what Cicada is, when to recall,
how to check nudges after a recall, how to save and write with evidence, the
bank's current projects and pending questions, and which conversations resume.
This file only adds the traversal notes below.
```

Keep the rest (two-pass recall, grounding, hubs, saving, never hand-edit, layout — add `_state.md   the live now-view (cursor: ids + one-liners; GET /state for the object)` to the layout block). In `skills/cicada-librarian/SKILL.md` add after the first paragraph: "The interaction contract is the generated handshake (`cicada_handshake` / the server's `instructions`); this skill covers only the consolidation loop."

- [ ] **Step 5: Verify the privacy rule and the pointers**

Run: `cd <worktree>/ && grep -rn "rorosaga\|/Users/" api/services/state_dictionary.py api/services/handshake.py api/routers/state.py api/tests/test_state_dictionary.py api/tests/test_state_wiring.py api/tests/test_handshake.py api/tests/test_mcp_handshake.py SKILL.md; grep -n "cicada_handshake" SKILL.md skills/cicada-librarian/SKILL.md CLAUDE.md | head`
Expected: the first grep prints nothing; the second prints at least one hit per file.

- [ ] **Step 6: Commit**

```bash
cd <worktree>/ && git add CLAUDE.md docs/goals/memory-evolution.md docs/goals/TODO.md SKILL.md skills/cicada-librarian/SKILL.md && git commit -m "docs(G53/G75): live state + handshake section, rows shipped, TODO handoff, SKILL.md points at the generated contract"
```

---

## Not in scope

- The Claude Code plugin / SessionStart hook / AGENTS.md generator (G49, G76) — only `handshake.HOOK_POINTER` and the `GET /handshake` route they will call.
- Any Swift: no Store fetch of `/state`, no UI, no `VersionVector` component (R9).
- G105 deterministic capture; G115 Phase 2's server-side ask gate (`mode`, vector score, asked set, cap) — R12 adds only the `entity_ids` filter.
- Any change to inbox *resolution* semantics (the hook in Task 2 is a post-commit projection refresh only).
- G13 open tasks/ideas in the state (no producer exists yet); `_preferences.md` injection; a `model` on conversation rows (G49).
- Backfilling `_state.md` into existing banks' history; a tokenizer-exact budget.

## Verification (the orchestrator runs this at the end)

```bash
cd <worktree>/ && git status --porcelain -uall
# expect: nothing tracked-and-dirty; only the pre-existing untracked api/.venv symlink (never staged)

cd <worktree>/ && git log --oneline dev..HEAD
# expect: exactly 5 commits, Task 1 → Task 5

cd <worktree>/ && api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider 2>&1 | tail -15
# expect: only the 8 date-dependent test_calendar_registry.py failures plus
# test_agent_provenance.py::test_a_decay_only_change_lands_in_its_own_cicada_authored_commit (order-dependent, pre-existing);
# everything else green, including the four new files (test_state_dictionary, test_state_wiring, test_handshake, test_mcp_handshake)

cd <worktree>/ && api/.venv/bin/python -m pytest api/tests/test_state_dictionary.py api/tests/test_state_wiring.py api/tests/test_handshake.py api/tests/test_mcp_handshake.py -q -p no:cacheprovider
# expect: all pass, twice in a row (determinism), under ~20 s

cd <worktree>/ && grep -rn "resolve_llm_fn\|litellm\|agent_engine" api/services/state_dictionary.py api/services/handshake.py api/routers/state.py
# expect: no output — zero LLM in the track

cd <worktree>/ && git diff dev..HEAD --stat -- app/ memory/ .claude/ | cat
# expect: empty — no Swift, no bank, no settings touched

# MCP stdio smoke (Task 4 Step 5) — instructions present and ≤ 1800 tokens on an empty tmp bank.
```

Then a diff read of `mcp/server.py` and `sleep_cycle.py` against the rulings: the tail's first statement is `_refresh_state_safely`; `_finalize`'s split precedes the porcelain scan; `initialize_result` never calls `refresh`.

## Self-review notes (for the executor, not a task)

- `state_dictionary.build` reads `bank_index.files(memory_path, "entities")` (frontmatter cache) and parses bodies only for the top-N rows; do not "simplify" it to `hub_builder._load_active_entities`, which parses every page.
- The G115 paragraph in `handshake._CONTRACT` is verbatim from the G75 row — shorten anything else to meet the token budget, never that.
- `_refresh_state_safely` must stay the FIRST statement of the tail (R2) — moving it inside the guarded branch re-creates the "dirty projection skips the connector poll" trap it exists to prevent.
- `GET /state` returns the on-disk keys unchanged (snake_case). Do not wrap it in a `CamelModel`; the schema is the file.
- Every new test bank is under `tmp_path`; nothing in this plan opens `memory/`, `~/.cicada`, or `~/.claude`.
