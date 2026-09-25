"""Round 4 C8 — GET /agents/live: which agents are connected, and when Cicada last
saw them (R-AG5, R-AG6). Temp HOME, temp CICADA_HOME, synthetic ledger rows and
connectors; no CLI is ever run and ~/Library / ~/.claude.json are never read."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.hooks import registry as hook_registry
from api.remote import store as remote_store
from api.services import agent_live, agent_wiring, telemetry

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "agent_catalog.json").read_text())
REPO = Path("/opt/example-person/code/cicada")
PY = f"{REPO}/api/.venv/bin/python"
NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def homes(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "cicada"))
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    agent_live._TAIL.reset()
    home = tmp_path / "home"
    home.mkdir()
    return home


def _handshake(ts: str, *, harness="unknown", client=None, delivery="initialize"):
    telemetry.record(telemetry.UsageEvent(
        kind="handshake", ts=ts, stage="handshake", connection=None, engine=None, model=None, bank="alpha",
        billing="free", invocations=1,
        refs={"delivery": delivery, "variant": "generic", "harness": harness, "client_name": client}))


def _snapshot(home):
    return {r["id"]: r for r in agent_live.snapshot(home=home, now=NOW, python=PY, repo=REPO)["agents"]}


def test_the_ids_are_the_shared_catalog():
    assert list(agent_live.LIVE_AGENTS) == FIXTURE["live"]
    assert list(agent_live.FEATURED) == FIXTURE["featured"]
    for harness in FIXTURE["setup"]:
        assert agent_wiring.setup(harness, home=Path("/nonexistent"), memory_root=Path("/M/memory"),
                                  repo=REPO, python=PY) is not None, harness


@pytest.mark.parametrize("harness,client,expected", [
    ("claude-code", None, "claude-code"), ("unknown", "claude-code", "claude-code"),
    ("unknown", "claude-ai", "claude"), ("unknown", "codex-mcp-client", "codex"),
    ("unknown", "cursor-vscode", "cursor"), ("unknown", "opencode", "opencode"),
    ("unknown", "OpenClaw Gateway", "openclaw"), ("unknown", "Hermes Agent", "hermes"),
    ("unknown", "gemini-cli-mcp-client", "gemini-cli"), ("unknown", "grok", "grok"),
    ("unknown", "mystery-client", None), ("unknown", None, None), (None, "", None),
])
def test_agent_for_prefers_the_harness_then_the_product_name(harness, client, expected):
    assert agent_live.agent_for(harness, client) == expected


@pytest.mark.parametrize("config,mcp,remote,expected", [
    ("on", None, None, (True, "config", None)),
    ("on", "2026-09-24T10:00:00Z", None, (True, "mcp", "2026-09-24T10:00:00Z")),
    ("off", "2026-09-24T10:00:00Z", None, (False, None, "2026-09-24T10:00:00Z")),
    ("unknown", "2026-09-24T10:00:00Z", None, (True, "mcp", "2026-09-24T10:00:00Z")),
    (None, "2026-09-24T10:00:00Z", None, (True, "mcp", "2026-09-24T10:00:00Z")),
    (None, None, "2026-09-24T11:00:00Z", (True, "remote", "2026-09-24T11:00:00Z")),
    ("off", "2026-09-24T10:00:00Z", "2026-09-24T11:00:00Z", (True, "remote", "2026-09-24T11:00:00Z")),
    ("on", "2026-09-24T11:00:00Z", "2026-09-24T10:00:00Z", (True, "mcp", "2026-09-24T11:00:00Z")),
    (None, None, None, (False, None, None)),
])
def test_one_rule_decides_connected_via_and_last_seen(config, mcp, remote, expected):
    r = agent_live.row("opencode", config=config, mcp_ts=mcp, remote_ts=remote)
    assert (r["connected"], r["via"], r["last_seen_at"]) == expected


def test_a_local_handshake_lights_its_agent_and_a_remote_one_does_not(homes):
    _handshake("2026-09-24T10:00:00.000Z", client="opencode")
    _handshake("2026-09-24T10:05:00.000Z", harness="claude-code")
    _handshake("2026-09-24T10:06:00.000Z", harness="grok", delivery="remote")   # covered by the store, R-AG5
    rows = _snapshot(homes)
    assert rows["claude-code"]["via"] == "mcp" and rows["claude-code"]["last_seen_at"] == "2026-09-24T10:05:00Z"
    assert rows["opencode"]["connected"] is True and rows["opencode"]["via"] == "mcp"
    assert rows["grok"]["connected"] is False


def test_a_config_that_no_longer_names_cicada_outranks_an_old_handshake(homes):
    _handshake("2026-09-20T10:00:00.000Z", client="opencode")
    cfg = homes / ".config/opencode/opencode.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"mcp": {}}), encoding="utf-8")
    row = _snapshot(homes)["opencode"]
    assert (row["connected"], row["via"], row["last_seen_at"]) == (False, None, "2026-09-20T10:00:00Z")


def test_claude_code_s_config_signal_is_the_stop_hook_only(homes):
    (homes / ".claude.json").write_text(json.dumps({"mcpServers": {"cicada": {}}}), encoding="utf-8")
    assert _snapshot(homes)["claude-code"]["connected"] is False           # ~/.claude.json is never read
    hook_registry.install(homes / ".claude/settings.json", event="Stop",
                          command=agent_wiring.hook_command(PY, REPO, "claude-code"))
    assert _snapshot(homes)["claude-code"] == {"id": "claude-code", "connected": True,
                                               "last_seen_at": None, "via": "config"}


def test_claude_desktop_s_library_config_is_never_read(homes):
    lib = homes / "Library/Application Support/Claude/claude_desktop_config.json"
    lib.parent.mkdir(parents=True)
    lib.write_text(json.dumps({"mcpServers": {"cicada": {}}}), encoding="utf-8")
    assert _snapshot(homes)["claude"]["connected"] is False


def test_a_used_active_connector_lights_its_app_and_a_revoked_one_does_not(homes):
    store = remote_store.ConnectorStore()
    grok, _ = store.create(app="grok", label=None, scopes=["search"], expires_in_days=30, now=NOW)
    chat, _ = store.create(app="chatgpt", label=None, scopes=["search"], expires_in_days=30, now=NOW)
    store.touch(grok.id, client="grok", now=datetime(2026, 9, 24, 11, 0, tzinfo=timezone.utc))
    store.touch(chat.id, now=datetime(2026, 9, 24, 11, 0, tzinfo=timezone.utc))
    store.revoke(chat.id, now=datetime(2026, 9, 24, 11, 30, tzinfo=timezone.utc))
    rows = _snapshot(homes)
    assert (rows["grok"]["connected"], rows["grok"]["via"], rows["grok"]["last_seen_at"]) == \
        (True, "remote", "2026-09-24T11:00:00Z")
    assert rows["chatgpt"]["connected"] is False


def test_telemetry_off_leaves_config_and_remote(homes, monkeypatch):
    _handshake("2026-09-24T10:00:00.000Z", client="opencode")
    monkeypatch.setenv("CICADA_TELEMETRY", "off")
    agent_live._TAIL.reset()
    assert _snapshot(homes)["opencode"]["connected"] is False


def test_the_tail_reads_only_what_was_appended(homes, monkeypatch):
    _handshake("2026-09-24T10:00:00.000Z", client="opencode")
    opened: list[str] = []
    real_open = Path.open

    def counting_open(self, *a, **k):
        if self.name.startswith("events-"):
            opened.append(self.name)
        return real_open(self, *a, **k)

    monkeypatch.setattr(Path, "open", counting_open)
    _snapshot(homes)
    assert opened == ["events-2026-09.jsonl"]
    opened.clear()
    _snapshot(homes)
    assert opened == [], "nothing appended, nothing re-read"
    _handshake("2026-09-24T10:10:00.000Z", client="hermes")
    rows = _snapshot(homes)
    assert opened == ["events-2026-09.jsonl"] and rows["hermes"]["via"] == "mcp"


def test_a_half_written_line_waits_for_its_newline(homes):
    path = telemetry.ledger_file("2026-09", kind="handshake")
    line = json.dumps({"kind": "handshake", "ts": "2026-09-24T10:00:00.000Z",
                       "refs": {"delivery": "initialize", "client_name": "openclaw"}}, separators=(",", ":"))
    path.write_text(line, encoding="utf-8")                                  # no newline yet
    assert _snapshot(homes)["openclaw"]["connected"] is False
    with path.open("a", encoding="utf-8") as fh:
        fh.write("\n")
    assert _snapshot(homes)["openclaw"]["via"] == "mcp"


def test_only_the_newest_two_months_are_read(homes):
    _handshake("2026-07-01T10:00:00.000Z", client="hermes")
    _handshake("2026-08-01T10:00:00.000Z", client="opencode")
    _handshake("2026-09-01T10:00:00.000Z", client="openclaw")
    rows = _snapshot(homes)
    assert rows["hermes"]["connected"] is False
    assert rows["opencode"]["connected"] is True and rows["openclaw"]["connected"] is True


def test_the_route_is_camel_case_and_never_runs_a_cli(homes, monkeypatch):
    from api.services.connections import base

    async def boom(*a, **k):
        raise AssertionError("/agents/live must never run a CLI")

    monkeypatch.setattr(base, "run_cli", boom)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: homes))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(homes.parent / "memory"))
    (homes.parent / "memory").mkdir()
    config.get_settings.cache_clear()
    try:
        body = TestClient(main.app).get("/agents/live").json()
    finally:
        config.get_settings.cache_clear()
    assert [a["id"] for a in body["agents"]] == FIXTURE["live"]
    assert set(body["agents"][0]) == {"id", "connected", "lastSeenAt", "via"}


def test_no_path_under_library_or_claude_json_is_named():
    source = Path(agent_live.__file__).read_text(encoding="utf-8")
    assert "Library" not in source and ".claude.json" not in source and "projects" not in source
