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
    assert handshake.CONTRACT_VERSION == 4, "G140 named its tools (3), then bridge lines joined the capabilities (G138)"
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


# --- G140 Q-R13/Q-R14: standing and current, identity and timezone -----------

from _synthetic_bank import _entity  # noqa: E402
from api.remote import catalog  # noqa: E402


def test_the_now_view_splits_standing_from_current(tmp_path):
    memory = _bank(tmp_path)
    _entity(memory, "local-first", type="concept", decay_class="durable", confidence=0.9)
    _entity(memory, "exam-week", type="concept", decay_class="volatile", last_referenced="2026-09-02")
    state_dictionary.refresh(memory, _settings(memory, observer_owner="bob-example"), force=True,
                             today=TODAY, now=NOW, repo_resolver=_ok_repo)
    state = state_dictionary.read_state(memory)
    text = handshake.build(state, variant="generic", bank="memory", tz="Europe/Madrid")
    standing, current = text.split("### Standing — changes rarely", 1)[1].split("### Current — in motion", 1)
    assert "`bob-example` — Bob Example is a synthetic fixture" in standing
    assert "Their timezone: Europe/Madrid." in standing
    assert "How to work with me: Prefers concise summaries over long reports." in standing
    assert "`local-first`" in standing and "`exam-week`" in current and "`alpha-project`" in current
    assert len(text) // 4 <= handshake.MAX_TOKENS
    remote = handshake.build_remote(state, tools=catalog.tool_names_for(catalog.DEFAULT_SCOPES), bank="memory",
                                    tz="Europe/Madrid")
    assert "### Standing" in remote and "Europe/Madrid" in remote and len(remote) // 4 <= handshake.MAX_TOKENS


def test_a_v1_state_file_still_renders():
    state = {"type": "state", "generated_at": NOW.isoformat(), "bank": "memory", "engine": {}, "sleep": {},
             "inbox": {}, "projects": [], "people": [], "conversations": [],
             "preferences": [{"id": "p", "name": "P", "one_liner": "Short replies."}]}
    text = handshake.build(state, variant="generic", bank="memory")
    assert "How to work with me: Short replies." in text and "### Current — in motion" in text


def test_the_primer_gives_up_current_rows_before_the_working_agreements():
    big = [{"id": f"x-{i}", "name": "N" * 60, "one_liner": "o" * 110} for i in range(80)]
    state = {"type": "state", "generated_at": NOW.isoformat(), "bank": "memory", "engine": {}, "sleep": {},
             "inbox": {}, "projects": [{"id": "alpha-project", "name": "Alpha Project", "one_liner": "Alpha."}],
             "people": big, "focus": big, "standing": big,
             "conversations": [{"id": f"c{i}", "harness": "codex", "title": "T" * 60} for i in range(80)],
             "preferences": [{"id": "ask-first", "name": "Ask First", "one_liner": "Ask before acting."}]}
    text = handshake.build(state, variant="generic", bank="memory")
    assert len(text) // 4 <= handshake.MAX_TOKENS
    assert "How to work with me: Ask before acting." in text and "`alpha-project`" in text
    assert "People recently in play" not in text and "In focus" not in text


def test_the_timezone_is_per_request_never_persisted_and_moves_the_cache(tmp_path, monkeypatch):
    memory = _with_state(tmp_path)
    monkeypatch.setattr(handshake, "local_timezone", lambda: "Europe/Madrid")
    a, _ = handshake.load_or_build(memory, "claude-code", cache_dir=tmp_path / "c")
    monkeypatch.setattr(handshake, "local_timezone", lambda: "America/Lima")
    b, meta = handshake.load_or_build(memory, "claude-code", cache_dir=tmp_path / "c")
    assert "Europe/Madrid" in a and "America/Lima" in b and meta["cached"] is False
    assert "Madrid" not in (memory / "_state.md").read_text(encoding="utf-8")


def test_the_contract_names_the_new_tools():
    text = handshake.build(None, variant="generic", bank="memory")
    for needle in ("cicada_timeline(since)", "cicada_record_watch(url, summary, excerpts=[{t, quote}])",
                   "`expected_end`", "cicada_retract_claim(subject, claim_id, reason)",
                   "cicada_recall_detail(entity_id)"):
        assert needle in text, needle
    remote = handshake.build_remote(None, tools=frozenset(catalog.TOOL_SCOPE), bank="memory")
    assert "cicada_retract_claim" in remote and "deletes or rewrites" not in remote


def test_a_record_only_remote_primer_carries_nothing_about_the_person():
    """G140 final review: a connection granted only ``record`` was told "Save
    notes, links and facts" — not the person's summary, timezone, working
    agreements, long-standing pages or what is in focus. The owner id stays
    (a write needs a subject); every describing row needs a ``read`` tool."""
    state = {"type": "state", "generated_at": NOW.isoformat(), "bank": "memory", "engine": {}, "sleep": {},
             "inbox": {}, "owner_id": "bob-example", "owner_one_liner": "Builds robots in a small lab.",
             "projects": [{"id": "alpha-project", "name": "Alpha Project", "one_liner": "Alpha."}],
             "people": [], "conversations": [],
             "focus": [{"id": "focus-page", "name": "Focus Page"}],
             "standing": [{"id": "lasting-page", "name": "Lasting Page"}],
             "preferences": [{"id": "ask-first", "name": "Ask First", "one_liner": "Ask before acting."}]}
    personal = ("Builds robots", "Europe/Madrid", "How to work with me", "Ask before acting",
                "Long-standing", "lasting-page", "In focus", "focus-page")
    record_only = catalog.tool_names_for(frozenset({"record"}))
    for st in (state, None):
        text = handshake.build_remote(st, tools=record_only, bank="memory", tz="Europe/Madrid")
        for needle in personal:
            assert needle not in text, needle
    assert "`bob-example`" in handshake.build_remote(state, tools=record_only, bank="memory", tz="Europe/Madrid")
    with_read = handshake.build_remote(state, tools=catalog.tool_names_for(frozenset({"record", "read"})),
                                       bank="memory", tz="Europe/Madrid")
    for needle in personal:
        assert needle in with_read, needle
