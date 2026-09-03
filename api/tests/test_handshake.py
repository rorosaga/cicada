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
    assert "at most one question per turn" in text and "cicada_resolve_inbox(id, skip=true)" in text
    assert "Recommended option when the item shows them" in text and "Cause" in text and "normalization" in text
    assert handshake.CONTRACT_VERSION == 2, "item 2 changed — the on-disk cache key must move with it"
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
