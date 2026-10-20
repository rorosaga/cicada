"""The nightly link backfill rides the Sleep cycle's engine-independent tail
(G102 cheap slice) — in the SAME clean-tree-guarded branch as the connector
and feed polls, on idle nights too. Hermetic: `link_enrichment.backfill` is a
spy; no network, no real model, no real git except where noted."""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from api.config import Settings
from api.services import engine_select, git_service, link_enrichment, predicates, sleep_cycle


def _empty_memory(tmp_path):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "episodes").mkdir(parents=True)
    predicates.install_predicate_map(memory)
    return memory


def _settings(memory, **over):
    base = dict(memory_path=memory, litellm_model="gpt-5.4-mini", litellm_disambiguation_model="gpt-5.4-nano",
                archive_threshold=0.2, decay_nudge_threshold=0.4, link_enrich_enabled=True,
                link_enrich_backfill_per_cycle=20, link_recon_max_per_cycle=40, inbox_stale_after_days=90)
    base.update(over)
    return SimpleNamespace(**base)


def _spy(monkeypatch, *, scan=None):
    calls = []

    async def fake_backfill(memory_path, settings, **kwargs):
        calls.append((memory_path, settings, kwargs))
        return link_enrichment.BackfillReport()

    monkeypatch.setattr(link_enrichment, "backfill", fake_backfill)
    if scan is not None:
        monkeypatch.setattr(link_enrichment, "scan_backfill", lambda *a, **k: scan)
        monkeypatch.setattr("api.services.link_recon.scan_recon", lambda *a, **k: [])
    return calls


def _quiet_peers(monkeypatch):
    async def quiet(*a, **k):
        return None

    for name in ("_poll_connectors_safely", "_poll_feeds_and_calendars_safely", "_warm_logos_safely", "_refresh_questions_safely"):
        monkeypatch.setattr(sleep_cycle, name, quiet)


def test_backfill_runs_on_the_idle_early_return_with_the_per_cycle_cap(tmp_path, monkeypatch):
    memory = _empty_memory(tmp_path)
    # One junk page owed: the step must call the driver. (A fully empty scan
    # is the "nothing owed" early return, covered below.)
    calls = _spy(monkeypatch, scan=link_enrichment._Scan(junk=[(Path("x"), "interstitial")]))
    _quiet_peers(monkeypatch)
    asyncio.run(sleep_cycle.run(_settings(memory, link_enrich_backfill_per_cycle=7), "cycle-empty"))
    (path, _, kwargs), = calls
    assert path == memory and kwargs["limit"] == 7
    assert sleep_cycle.get_sleep_state().status == "idle"


def test_zero_llm_work_never_resolves_the_engine(tmp_path, monkeypatch):
    """R10: a scan with only §2a reuse candidates (free) must not touch the
    connections registry — fix round 1, M1's idle-cycle rule stands."""
    memory = _empty_memory(tmp_path)
    scan = link_enrichment._Scan(reuse=[link_enrichment._Candidate(Path("x"), "media-x", "X", "https://x.example", "", "d", "2026")])
    calls = _spy(monkeypatch, scan=scan)
    _quiet_peers(monkeypatch)

    async def boom(*a, **k):
        raise AssertionError("resolve_settings must not run for zero-LLM work")

    monkeypatch.setattr(engine_select, "resolve_settings", boom)
    asyncio.run(sleep_cycle._backfill_links_safely(memory, _settings(memory), user_triggered=True))
    (_, _, kwargs), = calls
    assert kwargs["summarize_fn"] is None and kwargs["fetch_fn"] is None and kwargs["engine"] is None


def _scheduled_backfill(tmp_path, monkeypatch, *, mode, plan_switch, connected=()):
    """Run the backfill as the nightly schedule does (``user_triggered=False``) with a fetch owed, the person's
    engine choice ``mode`` and their "Scheduled runs may use my plan" switch (``None`` = never set, which reads as
    on since ruling 4c). Returns the connections probed, the resolved copy and the driver's kwargs."""
    from api.services import sleep_run_prefs
    from api.services.connections.registry import get_registry

    memory = _empty_memory(tmp_path)
    scan = link_enrichment._Scan(fetch=[link_enrichment._Candidate(Path("x"), "media-x", "X", "https://x.example", "", "", "2026")])
    calls = _spy(monkeypatch, scan=scan)
    asked: list[str] = []

    async def probe(_registry, connection_id):
        asked.append(connection_id)
        return connection_id in connected

    monkeypatch.setattr(engine_select, "_connected", probe)
    monkeypatch.setenv("CICADA_ALLOW_CONNECTOR_FETCH", "1")
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    # A REAL Settings (not a SimpleNamespace) so `resolve_settings` takes the
    # `model_copy` path; `memory_path` is a computed property over
    # `memory_root`, which only the env alias sets (config.py:33-41).
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_LLM_MODE", mode)
    settings = Settings()
    if plan_switch is not None:
        sleep_run_prefs.write(get_registry(settings), scheduled_use_plan=plan_switch)
    asyncio.run(sleep_cycle._backfill_links_safely(memory, settings, user_triggered=False))
    (_, resolved, kwargs), = calls
    assert kwargs["fetch_fn"] is link_enrichment.default_fetch
    assert kwargs["summarize_fn"] is link_enrichment._summarize_excerpt
    return asked, resolved, kwargs


def test_scheduled_cycle_with_the_plan_switch_off_keeps_the_chosen_key_without_probing(tmp_path, monkeypatch):
    """Ruling 4: with the person's switch off a scheduled cycle never touches a plan — the key they chose reads,
    and nothing is probed on the way."""
    asked, resolved, kwargs = _scheduled_backfill(tmp_path, monkeypatch, mode="byok", plan_switch=False,
                                                  connected={"claude-plan", "chatgpt-plan"})
    assert asked == []
    assert resolved.llm_mode == "byok" and kwargs["engine"] == "litellm"


def test_scheduled_auto_cycle_with_the_plan_switch_off_probes_no_plan_and_never_a_key(tmp_path, monkeypatch):
    """Rulings 4 + 31: Auto on a schedule the switch closes asks only whether the local model runs — never a plan —
    and with none running it has no engine rather than a metered key nobody chose."""
    asked, resolved, kwargs = _scheduled_backfill(tmp_path, monkeypatch, mode="auto", plan_switch=False,
                                                  connected={"claude-plan", "chatgpt-plan"})
    assert asked == [engine_select.OLLAMA_CONNECTION_ID]
    assert resolved.llm_mode == "auto" and kwargs["engine"] == engine_select.NO_ENGINE_LABEL
    assert resolved.no_engine_reason


def test_scheduled_auto_cycle_reads_on_the_plan_by_default(tmp_path, monkeypatch):
    """Ruling 4c: a switch never set reads as on, so a scheduled Auto resolves as a run the person starts — the
    Claude plan first (a cache-first sign-in check, never a model call)."""
    asked, resolved, kwargs = _scheduled_backfill(tmp_path, monkeypatch, mode="auto", plan_switch=None,
                                                  connected={"claude-plan"})
    assert asked == [engine_select.CLAUDE_CONNECTION_ID]
    assert resolved.llm_mode == "agent" and kwargs["engine"] == "claude-cli"


def test_connector_gate_off_disables_only_the_fetch_tier(tmp_path, monkeypatch):
    """CICADA_ALLOW_CONNECTOR_FETCH=off (what the suite sets): no default fetch
    on the unattended tail — reuse + recon still run."""
    memory = _empty_memory(tmp_path)
    scan = link_enrichment._Scan(fetch=[link_enrichment._Candidate(Path("x"), "media-x", "X", "https://x.example", "", "", "2026")])
    calls = _spy(monkeypatch, scan=scan)
    monkeypatch.setattr(engine_select, "resolve_settings", _passthrough)
    asyncio.run(sleep_cycle._backfill_links_safely(memory, _settings(memory), user_triggered=True))
    (_, _, kwargs), = calls
    assert kwargs["fetch_fn"] is None and kwargs["summarize_fn"] is None and kwargs["engine"] == "litellm"


async def _passthrough(settings, *, user_triggered=True):
    return settings, "test"


def test_backfill_is_skipped_once_the_cycle_has_written_and_not_committed(monkeypatch):
    """Same H1 risk window as the connector/feed polls: the backfill commits
    with commit_paths (scoped), but its writes would still land on a dirty
    tree the next `_finalize` sweeps with `git add -A`."""
    calls = _spy(monkeypatch)
    _quiet_peers(monkeypatch)

    async def dirty(_path):
        return " M entities/x.md\n"

    monkeypatch.setattr(git_service, "porcelain_status", dirty)
    sleep_cycle._state.write_started = True
    try:
        asyncio.run(sleep_cycle._run_engine_independent_tail(
            Path("/nonexistent"), _settings(Path("/nonexistent")), sleep_cycle._StageOutcome(committed=False)))
    finally:
        sleep_cycle._state.write_started = False
    assert calls == []


def test_a_raising_backfill_never_fails_the_cycle(tmp_path, monkeypatch):
    memory = _empty_memory(tmp_path)
    _quiet_peers(monkeypatch)

    # `scan_backfill` is synchronous — a sync fake so the step really sees the
    # RuntimeError (an async fake would hand back an un-awaited coroutine).
    def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(link_enrichment, "scan_backfill", boom)
    asyncio.run(sleep_cycle.run(_settings(memory), "cycle-boom"))
    assert sleep_cycle.get_sleep_state().status == "idle"
    assert sleep_cycle.get_sleep_state().error is None


def test_kill_switch_and_zero_cap_skip_the_step(tmp_path, monkeypatch):
    memory = _empty_memory(tmp_path)
    calls = _spy(monkeypatch)
    asyncio.run(sleep_cycle._backfill_links_safely(memory, _settings(memory, link_enrich_enabled=False), user_triggered=True))
    asyncio.run(sleep_cycle._backfill_links_safely(memory, _settings(memory, link_enrich_backfill_per_cycle=0), user_triggered=True))
    assert calls == []


def test_nothing_owed_never_calls_the_driver_or_touches_cicada_home(tmp_path, monkeypatch):
    """A bank with no media page owed anything (the state of every existing
    tail test's tmp bank) must not even enter the driver: no commit attempt,
    and no progress marker under `cicada_home()` — conftest does not isolate
    CICADA_HOME, so this is what keeps those suites out of the real ~/.cicada."""
    memory = _empty_memory(tmp_path)
    calls = _spy(monkeypatch, scan=link_enrichment._Scan())
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    asyncio.run(sleep_cycle._backfill_links_safely(memory, _settings(memory), user_triggered=True))
    assert calls == []
    assert not (tmp_path / "home" / "link_enrich").exists()
