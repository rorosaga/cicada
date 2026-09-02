"""G74(a) Task 6 — the commit and the ledger both name what really ran.

Two lies today: `_finalize`'s `engine=` default is never overridden by its one
call site, and `connection_for_model` maps any model containing "claude" to
("byok-anthropic", "usage") — so every plan call is attributed to the
DISCONNECTED BYOK API-key card and billed as real money.

Also G85: a purely-arithmetic `trigger: sleep/decay` entity change used to be
folded into the SAME commit as everything else and stamped with whichever
model ran Stage 1/2 that cycle — 978 such lines across two real cycles,
inflating that model's `GET /contributors` counts for work it never did.
`_finalize` now splits decay-only changes into their own commit, authored the
literal `cicada` (system maintenance, no model/user in the loop).
"""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from api.config import Settings
from api.services import agent_engine, git_service, sleep_cycle, telemetry


@pytest.fixture
def committed(tmp_path, monkeypatch):
    """Capture the commit message and the sleep_run event `_finalize` produces."""
    seen: dict = {}

    async def fake_status(_path):
        return ""

    async def fake_commit(_path, message):
        seen["message"] = message
        return "abc1234"

    monkeypatch.setattr(git_service, "porcelain_status", fake_status)
    monkeypatch.setattr(git_service, "commit_changes", fake_commit)
    seen["events"] = []
    monkeypatch.setattr(telemetry, "record", seen["events"].append)
    return seen


def test_a_plan_cycle_is_never_attributed_to_the_byok_card(tmp_path, committed):
    agent_engine.record_model_used("claude-sonnet-5")
    asyncio.run(sleep_cycle._finalize(
        tmp_path, "sleep_1", [], Settings(llm_mode="agent"),
        engine="claude-cli", connection="claude-plan", billing="subscription",
        authors=agent_engine.models_used(),
    ))
    ev = committed["events"][0]
    assert ev.kind == "sleep_run"
    assert ev.engine == "claude-cli"
    assert ev.connection == "claude-plan"     # NOT byok-anthropic
    assert ev.billing == "subscription"       # NOT usage
    assert ev.model == "claude-sonnet-5"


def test_the_commit_trailers_name_the_models_that_actually_ran(tmp_path, committed):
    asyncio.run(sleep_cycle._finalize(
        tmp_path, "sleep_1", [], Settings(llm_mode="agent"),
        engine="claude-cli", connection="claude-plan", billing="subscription",
        authors=["claude-haiku-4-5", "claude-sonnet-5"],
    ))
    trailers = git_service._parse_authors(committed["message"])
    assert set(trailers) == {"claude-haiku-4-5", "claude-sonnet-5"}


def test_the_byok_path_still_derives_authors_from_settings(tmp_path, committed):
    asyncio.run(sleep_cycle._finalize(
        tmp_path, "sleep_1", [], Settings(litellm_model="gpt-5.4-mini",
                                          litellm_disambiguation_model="gpt-5.4-nano"),
    ))
    ev = committed["events"][0]
    assert ev.engine == "litellm" and ev.connection == "byok-openai"
    assert set(git_service._parse_authors(committed["message"])) == {"gpt-5.4-mini", "gpt-5.4-nano"}


def test_the_five_unlabelled_call_sites_now_carry_a_stage(monkeypatch):
    """`by_stage` in the Usage dashboard groups on this field; five sites fell
    into the "unknown" bucket (providers.py:201 defaults it)."""
    from api.services import providers

    seen: list[str | None] = []
    real = providers.resolve_llm_fn

    def patched(settings, **kw):
        seen.append(kw.get("stage"))
        return real(settings, **kw)

    monkeypatch.setattr(providers, "resolve_llm_fn", patched)

    import inspect

    from api.services import conflict_resolver, dedup_sweep, skill_extractor, source_rewrite

    sources = "\n".join(
        inspect.getsource(mod) for mod in
        (conflict_resolver, dedup_sweep, skill_extractor, source_rewrite)
    )
    # Every resolve_llm_fn call in these four modules names its stage.
    for chunk in sources.split("resolve_llm_fn(")[1:]:
        head = chunk[: chunk.index(")")] if ")" in chunk else chunk
        assert "stage=" in head, f"unlabelled resolve_llm_fn call: {head[:120]}"


def test_no_sleep_stage_reports_unknown(monkeypatch):
    """The ledger's `by_stage` must contain no "unknown" row after a cycle."""
    from api.services import consumption_stats

    events = [
        telemetry.UsageEvent(kind="llm_call", stage=s, connection="claude-plan",
                             engine="claude-cli", model="claude-sonnet-5",
                             input_tokens=10, output_tokens=1)
        for s in ("extraction", "disambiguation", "conflict", "skills", "dedup",
                  "rewrite", "enrichment", "ask")
    ]
    rows = consumption_stats._group(events, "stage", "stage")
    assert "unknown" not in {r["stage"] for r in rows}


# --------------------------------------------------------------------------- #
# G85 — the decay-authorship bug: pure arithmetic must never look model-
# authored, and must never inflate a model's GET /contributors counts.
# --------------------------------------------------------------------------- #


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(repo), check=True, capture_output=True, text=True
    ).stdout


def _init_repo(tmp_path) -> Path:
    repo = tmp_path / "memory"
    (repo / "entities").mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@cicada.local")
    _git(repo, "config", "user.name", "Cicada Test")
    return repo


def test_a_decay_only_change_lands_in_its_own_cicada_authored_commit(tmp_path, monkeypatch):
    """The exact G85 shape: one real entity change (LLM-authored) and one pure
    decay change (no LLM, no episode) in the SAME cycle. They must not share
    a commit or an author."""
    monkeypatch.setenv("CICADA_TELEMETRY", "off")
    repo = _init_repo(tmp_path)
    (repo / "entities" / "cicada.md").write_text("---\nid: cicada\n---\n\n# Cicada\n")
    (repo / "entities" / "stale-tool.md").write_text("---\nid: stale-tool\n---\n\n# Stale Tool\n")

    changes = [
        {"id": "cicada", "action": "created", "source_episode": "ep_1",
         "source_episodes": ["ep_1"], "trigger": "sleep/extraction"},
        {"id": "stale-tool", "action": "archive", "new_confidence": 0.1,
         "new_status": "archived", "source_episode": "", "trigger": "sleep/decay"},
    ]

    asyncio.run(sleep_cycle._finalize(
        repo, "cycle-1", changes, Settings(litellm_model="gpt-5.4-mini"),
    ))

    log = _git(repo, "log", "--format=%H", "--reverse")
    hashes = [h for h in log.splitlines() if h.strip()]
    assert len(hashes) == 2, "the decay change must land in its own, separate commit"

    decay_message = _git(repo, "log", "-1", "--format=%B", hashes[0])
    main_message = _git(repo, "log", "-1", "--format=%B", hashes[1])

    assert "entities/stale-tool.md: archive" in decay_message
    assert git_service._parse_authors(decay_message) == ["cicada"]
    assert "entities/cicada.md" not in decay_message

    assert "entities/cicada.md: created" in main_message
    # settings-derived fallback: main model + Stage-2 disambiguation model
    # (config default "gpt-5.4-nano") when distinct — never "cicada".
    assert git_service._parse_authors(main_message) == ["gpt-5.4-mini", "gpt-5.4-nano"]
    assert "entities/stale-tool.md" not in main_message


def test_a_decay_only_cycle_with_no_other_changes_commits_only_to_cicada(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_TELEMETRY", "off")
    repo = _init_repo(tmp_path)
    (repo / "entities" / "stale-tool.md").write_text("---\nid: stale-tool\n---\n\n# Stale Tool\n")

    changes = [
        {"id": "stale-tool", "action": "decay_nudge", "new_confidence": 0.35,
         "new_status": "decaying", "source_episode": "", "trigger": "sleep/decay"},
    ]
    asyncio.run(sleep_cycle._finalize(repo, "cycle-2", changes, None))

    log = _git(repo, "log", "--format=%H", "--reverse")
    hashes = [h for h in log.splitlines() if h.strip()]
    assert len(hashes) == 1

    message = _git(repo, "log", "-1", "--format=%B", hashes[0])
    assert git_service._parse_authors(message) == ["cicada"]


def test_the_decay_commit_never_gets_an_engine_trailer(tmp_path, monkeypatch):
    """No LLM ran for pure decay arithmetic — the honest answer is no engine
    trailer at all, never a guessed value."""
    monkeypatch.setenv("CICADA_TELEMETRY", "off")
    repo = _init_repo(tmp_path)
    (repo / "entities" / "stale-tool.md").write_text("---\nid: stale-tool\n---\n\n# Stale Tool\n")
    changes = [
        {"id": "stale-tool", "action": "archive", "new_confidence": 0.1,
         "new_status": "archived", "source_episode": "", "trigger": "sleep/decay"},
    ]
    asyncio.run(sleep_cycle._finalize(
        repo, "cycle-3", changes, Settings(llm_mode="agent"), engine="claude-cli",
        authors=["claude-sonnet-5"],
    ))
    message = _git(repo, "log", "-1", "--format=%B")
    assert "Cicada-Engine" not in message


# --------------------------------------------------------------------------- #
# End-to-end: a fake-runner cycle in a temp bank. Drives one real (fake)
# `claude -p` call through the agent seam to prove `agent_engine.models_used()`
# reaches the commit trailers, AND that a decay-only change in the SAME cycle
# is split out and authored `cicada`, AND that the ledger's `by_stage` carries
# no "unknown" row for what actually ran.
# --------------------------------------------------------------------------- #


def test_end_to_end_fake_runner_cycle_names_the_model_and_splits_decay(
    tmp_path, monkeypatch, agent_runner, agent_envelopes,
):
    from api.services import consumption_stats, providers

    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    repo = _init_repo(tmp_path)
    (repo / "entities" / "cicada.md").write_text("---\nid: cicada\n---\n\n# Cicada\n")
    (repo / "entities" / "stale-tool.md").write_text("---\nid: stale-tool\n---\n\n# Stale Tool\n")

    settings = Settings(llm_mode="agent", agent_model="sonnet")

    # One real (fake-subprocess) call through the agent seam, exactly as
    # entity_extractor would make during Stage 1 — records the model used
    # AND emits one llm_call telemetry event labelled stage="extraction".
    fn = providers.resolve_llm_fn(
        settings, stage="extraction", runner=agent_runner(agent_envelopes["success"]),
    )
    fn(messages=[{"role": "user", "content": "extract entities"}])

    changes = [
        {"id": "cicada", "action": "created", "source_episode": "ep_1",
         "source_episodes": ["ep_1"], "trigger": "sleep/extraction"},
        {"id": "stale-tool", "action": "archive", "new_confidence": 0.1,
         "new_status": "archived", "source_episode": "", "trigger": "sleep/decay"},
    ]

    asyncio.run(sleep_cycle._finalize(
        repo, "cycle-e2e", changes, settings,
        engine="claude-cli", connection="claude-plan", billing="subscription",
        authors=agent_engine.models_used(),
    ))

    # (a) the commit trailers name the REAL model the fake runner reported —
    # not settings.litellm_model, which is unset/irrelevant on the agent rung.
    log = _git(repo, "log", "--format=%H", "--reverse")
    hashes = [h for h in log.splitlines() if h.strip()]
    assert len(hashes) == 2
    decay_message = _git(repo, "log", "-1", "--format=%B", hashes[0])
    main_message = _git(repo, "log", "-1", "--format=%B", hashes[1])

    assert git_service._parse_authors(main_message) == ["claude-sonnet-5"]
    assert "Cicada-Engine: claude-cli" in main_message

    # (b) the decay-only change is split out and authored `cicada`.
    assert git_service._parse_authors(decay_message) == ["cicada"]
    assert "entities/stale-tool.md: archive" in decay_message

    # (c) the ledger's by_stage has no "unknown" row.
    events = telemetry.read_events()
    assert events, "the ledger must have recorded something"
    rows = consumption_stats._group(events, "stage", "stage")
    assert "unknown" not in {r["stage"] for r in rows}
    stages = {r["stage"] for r in rows}
    assert "extraction" in stages
    assert "structural" in stages  # the sleep_run event


# --------------------------------------------------------------------------- #
# Fix round 1 — task-6-review.md
#
# M2: the decay-only commit must NEVER be able to take the whole cycle down.
# M1: /sleep/history must not pull every commit's full body just to read one
#     trailer line.
# L2: the settings-derived author fallback must not invent a BYOK model on
#     a non-litellm rung.
# L3: `_MODELS_USED` is process-global — documented at its definition
#     (agent_engine.py), no test needed (same-alias pollution, not a wrong
#     one).
# --------------------------------------------------------------------------- #


def test_a_missing_decay_entity_file_still_lets_the_main_commit_land(tmp_path, monkeypatch):
    """M2: a decay change whose entity file does not exist on disk (a
    stem-derived path gone wrong) must never raise out of `_finalize` — it
    folds into the main commit instead of taking the whole cycle down."""
    monkeypatch.setenv("CICADA_TELEMETRY", "off")
    repo = _init_repo(tmp_path)
    (repo / "entities" / "cicada.md").write_text("---\nid: cicada\n---\n\n# Cicada\n")
    # Deliberately never write entities/ghost.md.

    changes = [
        {"id": "cicada", "action": "created", "source_episode": "ep_1",
         "source_episodes": ["ep_1"], "trigger": "sleep/extraction"},
        {"id": "ghost", "action": "archive", "new_confidence": 0.1,
         "new_status": "archived", "source_episode": "", "trigger": "sleep/decay"},
    ]

    # Must not raise.
    asyncio.run(sleep_cycle._finalize(
        repo, "cycle-missing", changes, Settings(litellm_model="gpt-5.4-mini",
                                                 litellm_disambiguation_model=""),
    ))

    log = _git(repo, "log", "--format=%H", "--reverse")
    hashes = [h for h in log.splitlines() if h.strip()]
    # No file to split out -> everything folds into ONE commit, not two.
    assert len(hashes) == 1, "no decay commit should exist when its only path is missing"

    message = _git(repo, "log", "-1", "--format=%B", hashes[0])
    assert "entities/cicada.md: created" in message
    # The decay line for the missing file still shows up in the manifest —
    # it is not silently dropped, just no longer split into its own commit.
    assert "entities/ghost.md: archive (source: n/a, trigger: sleep/decay)" in message
    assert git_service._parse_authors(message) == ["gpt-5.4-mini"]


def test_a_failing_decay_commit_still_lets_the_main_commit_land(tmp_path, monkeypatch, committed):
    """M2: if `commit_paths` itself raises (corrupt git state, a concurrent
    lock, anything) for a decay change whose file DOES exist, `_finalize`
    must still land the main commit rather than propagating the error and
    committing nothing this cycle."""
    async def boom(_memory_path, _message, _paths):
        raise RuntimeError("simulated git failure")

    monkeypatch.setattr(git_service, "commit_paths", boom)

    changes = [
        {"id": "a", "action": "created", "source_episode": "ep_1",
         "source_episodes": ["ep_1"], "trigger": "sleep/extraction"},
        {"id": "stale", "action": "archive", "new_confidence": 0.1,
         "new_status": "archived", "source_episode": "", "trigger": "sleep/decay"},
    ]
    # `committed` fakes porcelain_status/commit_changes and never checks
    # file existence, so this exercises the try/except path specifically
    # (as opposed to the pre-stage existence filter above).
    (tmp_path / "entities").mkdir()
    (tmp_path / "entities" / "stale.md").write_text("---\nid: stale\n---\n")

    # Must not raise, and the main commit must still happen.
    asyncio.run(sleep_cycle._finalize(tmp_path, "cycle-boom", changes, None))

    assert "message" in committed, "the main commit must still land"
    message = committed["message"]
    assert "entities/a.md: created" in message
    assert "entities/stale.md: archive (source: n/a, trigger: sleep/decay)" in message
    # Telemetry still recorded — the cycle is reported, not swallowed.
    assert committed["events"][0].kind == "sleep_run"


def test_the_author_fallback_never_invents_a_byok_model_on_the_agent_rung(tmp_path, committed):
    """L2: on the agent rung, when the engine recorded NO model (every call
    this cycle failed before reporting one), the settings-derived fallback
    must not step in with `settings.litellm_model` — that model never ran."""
    asyncio.run(sleep_cycle._finalize(
        tmp_path, "sleep_1", [],
        Settings(llm_mode="agent", litellm_model="gpt-5.4-mini"),
        engine="claude-cli", connection="claude-plan", billing="subscription",
        authors=None,  # nothing recorded this cycle
    ))
    assert git_service._parse_authors(committed["message"]) == []
    ev = committed["events"][0]
    assert ev.model is None
    assert ev.connection == "claude-plan"  # the explicit override still wins


def test_the_author_fallback_still_applies_on_the_default_litellm_engine(tmp_path, committed):
    """Regression guard for the L2 fix: the byok/default rung must keep
    falling back to `settings.litellm_model` exactly as before — only the
    non-litellm rungs are excluded."""
    asyncio.run(sleep_cycle._finalize(
        tmp_path, "sleep_1", [], Settings(litellm_model="gpt-5.4-mini",
                                          litellm_disambiguation_model=""),
    ))
    assert git_service._parse_authors(committed["message"]) == ["gpt-5.4-mini"]


# --------------------------------------------------------------------------- #
# M1 — /sleep/history reads the engine trailer via git's own
# %(trailers:...) directive, not a full-body %b pull.
# --------------------------------------------------------------------------- #


def test_get_sleep_history_reports_the_engine_trailer(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "entities" / "a.md").write_text("---\nid: a\n---\n")
    _git(repo, "add", "-A")
    message = git_service.build_commit_message(
        "Sleep cycle 2026-09-01",
        ["entities/a.md: created (source: ep_1, trigger: sleep/extraction)"],
        authors=["claude-sonnet-5"], engine="claude-cli",
    )
    _git(repo, "commit", "-q", "-m", message)

    entries = asyncio.run(git_service.get_sleep_history(repo))
    assert len(entries) == 1
    assert entries[0].engine == "claude-cli"


def test_get_sleep_history_reports_none_for_a_legacy_commit_with_no_engine_trailer(tmp_path):
    """Back-compat (review-verified, must not regress): an old commit
    written before the `Cicada-Engine:` trailer existed still parses fine —
    `engine` is `None`, never a guess, and the row is not dropped."""
    repo = _init_repo(tmp_path)
    (repo / "entities" / "a.md").write_text("---\nid: a\n---\n")
    _git(repo, "add", "-A")
    message = git_service.build_commit_message(
        "Sleep cycle 2026-01-01",
        ["entities/a.md: created (source: ep_1, trigger: sleep/extraction)"],
        authors=["gpt-5.4-mini"],  # no engine= passed at all
    )
    _git(repo, "commit", "-q", "-m", message)

    entries = asyncio.run(git_service.get_sleep_history(repo))
    assert len(entries) == 1
    assert entries[0].engine is None
    assert "entities/a.md" in entries[0].files_changed


def test_get_sleep_history_reports_no_engine_for_the_cicada_decay_commit(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "entities" / "stale.md").write_text("---\nid: stale\n---\n")
    _git(repo, "add", "-A")
    message = git_service.build_commit_message(
        "Sleep cycle 2026-09-01 (decay)",
        ["entities/stale.md: archive (source: n/a, trigger: sleep/decay)"],
        authors=["cicada"],
    )
    _git(repo, "commit", "-q", "-m", message)

    entries = asyncio.run(git_service.get_sleep_history(repo))
    assert len(entries) == 1
    assert entries[0].engine is None


def test_get_sleep_history_payload_does_not_scale_with_commit_body_size(tmp_path):
    """M1: the old `%b` pull made the payload grow with the SIZE of every
    commit message. A giant manifest (hundreds of entity lines, as a real
    Sleep cycle produces) must not appear anywhere in what `get_sleep_history`
    reads back out — only the one trailer value should surface."""
    repo = _init_repo(tmp_path)
    (repo / "entities" / "a.md").write_text("---\nid: a\n---\n")
    _git(repo, "add", "-A")
    huge_lines = [f"entities/entity-{i}.md: updated (trigger: sleep/extraction)" for i in range(500)]
    message = git_service.build_commit_message(
        "Sleep cycle 2026-09-01", huge_lines, authors=["gpt-5.4-mini"], engine="litellm",
    )
    _git(repo, "commit", "-q", "-m", message)

    entries = asyncio.run(git_service.get_sleep_history(repo))
    assert len(entries) == 1
    assert entries[0].engine == "litellm"
    # The huge manifest never had to travel through Python at all for this
    # call — `message` (the commit's `.message`) is just the SUBJECT line.
    assert entries[0].message == "Sleep cycle 2026-09-01"
    assert "entity-499" not in entries[0].message
