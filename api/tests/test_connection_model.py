"""G217 (the connection model), G205 (agent requests), G212 (devices), G50/G215 (keys checked before saving).

Temp HOME, temp CICADA_HOME, a synthetic bank; no CLI is run, no network is used (the key check is patched), and no
key reaches a log, a file other than secrets.env, or an answer beyond its last four characters."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import (agent_catalog, agent_live, agent_requests, agent_seen, agent_wiring, device_status,
                          device_tokens, inbox_service, markdown_parser, sync_service)
from api.services.connections import key_check, registry, secrets

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "agent_catalog.json").read_text())
#: The shared logo set's slugs (~/cicada-redesign-2026-10-22/logos/manifest.json, 2026-10-22), agent and model-host
#: rows. A logo the table names must be one of these, or None for the monogram.
LOGO_SLUGS = {"claude", "openai", "gemini", "grok", "meta", "cursor", "opencode", "hermes", "openclaw", "poke", "zed",
              "vscode", "devin", "cline", "goose", "kiro", "warp", "amp", "instinct", "openrouter", "fireworks",
              "deepinfra", "together", "groq", "mistral"}
NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (memory / "inbox").mkdir()
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "cicada"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_TELEMETRY", "off")
    monkeypatch.setenv("CICADA_API_AUTH", "off")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    for p in ("OPENAI_API_KEY", "XAI_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(p, raising=False)
    agent_seen.reset()
    agent_live._TAIL.reset()
    config.get_settings.cache_clear()
    registry.reset_registry()
    yield {"home": home, "memory": memory, "tmp": tmp_path}
    config.get_settings.cache_clear()
    registry.reset_registry()


# --- G217: one table ------------------------------------------------------------------------------------------------


def test_the_app_pills_come_from_the_table_in_the_apps_order():
    assert list(agent_catalog.LIVE_PILLS) == FIXTURE["live"]
    assert list(agent_catalog.FEATURED) == FIXTURE["featured"]
    assert all(agent_catalog.way(i) is not None for i in agent_catalog.LIVE_PILLS)
    assert agent_live.LIVE_AGENTS == agent_catalog.LIVE_PILLS


def test_one_umbrella_per_provider_and_one_mark_each():
    ids = [u.id for u in agent_catalog.UMBRELLAS]
    assert len(ids) == len(set(ids))
    logos = [u.logo for u in agent_catalog.UMBRELLAS if u.logo]
    assert len(logos) == len(set(logos)), "a mark is drawn for one umbrella only (owner 2026-10-22)"
    assert set(logos) <= LOGO_SLUGS
    by_id = {u.id: u for u in agent_catalog.UMBRELLAS}
    assert [w.id for w in by_id["anthropic"].ways] == ["claude-code", "claude"]
    assert [w.id for w in by_id["openai"].ways] == ["codex", "chatgpt", "dots"]
    assert {i.connection for i in by_id["openai"].intelligence} == {"chatgpt-plan", "byok-openai"}
    assert [w.id for w in by_id["xai"].ways] == ["grok-build", "grok", "grok-bot"]
    assert by_id["instinct"].ways[0].connects == ("messages", "rest")


def test_every_setup_id_and_every_key_card_the_table_names_exists(env):
    from api.services.connections import byok

    for w in agent_catalog.WAYS:
        for harness in w.setup:
            assert agent_wiring.setup(harness, home=env["home"], memory_root=env["memory"],
                                      python="/usr/bin/python3") is not None, harness
        assert set(w.connects) <= set(agent_catalog.CONNECTS), w.id
    cards = {p.connection_id for p in byok.PROVIDERS} | {"claude-plan", "chatgpt-plan", "ollama"}
    for u in agent_catalog.UMBRELLAS:
        for i in u.intelligence:
            assert i.connection in cards, i.connection
    assert {p.connection_id for p in byok.PROVIDERS} <= {i.connection for u in agent_catalog.UMBRELLAS
                                                         for i in u.intelligence}


def test_the_skills_agents_derive_from_the_table():
    assert [a.id for a in agent_wiring.AGENTS] == ["claude-code", "codex", "cursor", "opencode", "hermes",
                                                   "openclaw", "gemini-cli"]
    codex = next(a for a in agent_wiring.AGENTS if a.id == "codex")
    assert (codex.label, codex.skills, codex.reads) == ("Codex", ".codex/skills", (".agents/skills",))


@pytest.mark.parametrize("client,expected", [
    ("claude-code", "claude-code"), ("Claude Code", "claude-code"), ("claude-ai", "claude"),
    ("codex-mcp-client", "codex"), ("cursor-vscode", "cursor"), ("Visual Studio Code", "vscode"),
    ("zed", "zed"), ("Windsurf", "windsurf"), ("Grok Build", "grok-build"), ("grok", "grok"),
    ("goose", "goose"), ("amp", "amp"), ("example-client", "other"), ("authorized-tool", "other"),
    ("smoke-test", None), ("", None),
])
def test_client_names_match_whole_words_in_table_order(client, expected):
    assert agent_catalog.way_for_client(client) == expected


def test_providers_route_serves_the_table(env):
    body = TestClient(main.app).get("/providers").json()
    assert body["pills"] == FIXTURE["live"]
    google = next(u for u in body["providers"] if u["id"] == "google")
    assert google["logo"] == "gemini" and google["later"] == ["Google Cloud (Vertex)"]
    assert "billing" in google["intelligence"][0]["note"]
    assert set(google["ways"][0]) == {"id", "label", "connects", "tier", "clients", "setup", "remoteApp", "pill",
                                      "note"}


# --- G217: last seen without telemetry -------------------------------------------------------------------------------


def test_a_stdio_sighting_survives_telemetry_off(env):
    assert agent_seen.stamp_agent("opencode", via="mcp")
    rows = {r["id"]: r for r in agent_live.snapshot(home=env["home"], python="/x", repo=Path("/r"))["agents"]}
    assert rows["opencode"]["connected"] and rows["opencode"]["via"] == "mcp"
    assert rows["opencode"]["last_seen_at"]


def test_a_tier_two_agent_reports_itself_and_lights_another_agent(env):
    agent_seen.stamp_agent("zed", via="mcp")
    rows = {r["id"]: r for r in agent_live.snapshot(home=env["home"], python="/x", repo=Path("/r"))["agents"]}
    assert rows["zed"]["connected"] and rows["other"]["connected"]
    assert rows["other"]["last_seen_at"] == rows["zed"]["last_seen_at"]


def test_a_stamp_is_throttled_and_holds_names_and_times_only(env):
    assert agent_seen.stamp_agent("codex", via="tool", device="abcd1234")
    assert not agent_seen.stamp_agent("codex", via="tool", device="abcd1234")   # within the minute
    assert not agent_seen.stamp_agent("codex", via="bogus")
    (row,) = agent_seen.agents()
    assert set(row) == {"agent", "device", "via", "firstSeen", "lastSeen", "calls"}
    assert row["device"] == "abcd1234" and row["calls"] == 1
    assert oct(agent_seen.path().stat().st_mode & 0o777) == "0o600"
    assert str(agent_seen.path()).startswith(os.environ["CICADA_HOME"])


def test_reading_never_creates_the_store(env):
    assert agent_seen.agents() == [] and agent_seen.devices() == {}
    assert not agent_seen.path().exists()


def test_the_mcp_server_stamps_on_initialize(env, monkeypatch):
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location("cicada_mcp_server_g217", Path(__file__).resolve().parents[2]
                                                  / "mcp" / "server.py")
    server = importlib.util.module_from_spec(spec)
    sys.modules["cicada_mcp_server_g217"] = server
    spec.loader.exec_module(server)
    monkeypatch.setattr(server, "_handshake_text", lambda **k: "primer")
    monkeypatch.setattr(server, "_warm_reading_queue", lambda: None)
    import dataclasses

    monkeypatch.setattr(server, "SESSION", dataclasses.replace(server.SESSION, harness="unknown"))
    server.initialize_result({"clientInfo": {"name": "Hermes Agent", "version": "1"}})
    assert [r["agent"] for r in agent_seen.agents()] == ["hermes"]


@pytest.mark.parametrize("peer,headers,device,expected", [
    ("127.0.0.1", {}, False, "local"), ("127.0.0.1", {}, True, "ssh"),
    ("127.0.0.1", {"Tailscale-User-Login": "x@example.com"}, True, "tailscale"),
    ("100.101.102.103", {}, True, "tailscale"), ("192.168.1.20", {}, True, "lan"), (None, {}, True, "ssh"),
])
def test_how_a_device_arrived_is_read_from_the_request(peer, headers, device, expected):
    assert agent_seen.how_from_request(peer=peer, headers=headers, device=device) == expected


# --- G212: devices ---------------------------------------------------------------------------------------------------


def _episode(memory: Path, eid: str, *, device: str | None = None, processed: bool = False) -> None:
    fm = {"id": eid, "timestamp": "2026-10-22T10:00:00Z", "processed": processed, "source": "claude-code"}
    if device:
        fm["device"] = device
    markdown_parser.write(memory / "episodes" / f"{eid}.md", fm, "user: hello\n")


def test_devices_by_their_own_names_with_how_and_queue(env, monkeypatch):
    monkeypatch.setattr(device_status, "_NAME", "studio-example")
    laptop, _ = device_tokens.store().create("laptop-example")
    gone, _ = device_tokens.store().create("old-example")
    device_tokens.store().revoke(gone.id)
    _episode(env["memory"], "2026-10-22-001")
    _episode(env["memory"], "2026-10-22-002", device=laptop.id)
    _episode(env["memory"], "2026-10-22-003", device=laptop.id)
    _episode(env["memory"], "2026-10-22-004", device=laptop.id, processed=True)
    agent_seen.stamp_device(laptop.id, "tailscale")
    body = TestClient(main.app).get("/devices/status").json()
    this, other = body["devices"]
    assert (this["name"], this["role"], this["connected"], this["how"], this["queue"]) == (
        "studio-example", "server", True, "local", 1)
    assert (other["name"], other["how"], other["queue"], other["connected"]) == ("laptop-example", "tailscale", 2, True)
    assert "my mac" not in json.dumps(body).lower()


def test_a_device_quiet_past_the_window_reads_not_connected(env):
    laptop, _ = device_tokens.store().create("laptop-example")
    later = datetime.now(timezone.utc) + timedelta(seconds=device_status.CONNECTED_WITHIN_S + 60)
    agent_seen.stamp_device(laptop.id, "ssh")
    rows = device_status.snapshot(env["memory"], now=later)["devices"]
    assert rows[1]["connected"] is False and rows[1]["how"] == "ssh"


# --- G205: agent requests --------------------------------------------------------------------------------------------


def test_a_request_is_filed_once_and_served_above_the_questions(env):
    markdown_parser.write(env["memory"] / "inbox" / "inbox-001.md",
                          {"kind": "clarification", "required_input": "freetext", "status": "pending",
                           "priority": 0.9, "entity_id": "alpha", "title": "Who?", "created_date": "2026-10-01"}, "B")
    first = agent_requests.ask(env["memory"], agent="claude-code", site="www.Example.com",
                               reason="to read the post you talked about")
    again = agent_requests.ask(env["memory"], agent="claude-code", site="example.com",
                               reason="to read the post you talked about")
    assert first["id"] == again["id"] and first["site"] == "example.com"
    items = TestClient(main.app).get("/inbox").json()
    assert [i["kind"] for i in items] == ["agent_request", "clarification"]
    req = items[0]["request"]
    assert (req["agentName"], req["umbrella"], req["logo"]) == ("Claude Code", "anthropic", "claude")
    assert req["notification"]["body"] == ("Claude Code is asking you to sign in to example.com, to read the post "
                                           "you talked about.")
    assert [o["key"] for o in items[0]["options"]] == ["done", "dismiss"]
    total, by_kind = inbox_service.served_counts(env["memory"])
    assert total == 2 and by_kind["agent_request"] == 1


def test_a_request_moves_the_inbox_stamp_and_a_bank_without_one_keeps_its_own(env):
    before = sync_service.components(env["memory"])["inbox"]
    assert ":r" not in before
    agent_requests.ask(env["memory"], agent="codex", site="example.com")
    assert sync_service.components(env["memory"])["inbox"] != before


def test_signing_in_resolves_it_and_lifts_the_sites_pause(env, monkeypatch):
    from api.services import reading_queue

    lifted = []
    monkeypatch.setattr(reading_queue, "resume_site", lambda memory, site: lifted.append(site) or 1)
    row = agent_requests.ask(env["memory"], agent="hermes", site="news.example.com")
    client = TestClient(main.app)
    assert client.post(f"/inbox/{row['id']}/resolve", json={"action": "resolve", "optionKey": "maybe"}).status_code == 400
    ok = client.post(f"/inbox/{row['id']}/resolve", json={"action": "resolve", "optionKey": "done"})
    assert ok.status_code == 200 and ok.json()["action"] == "done"
    assert len(lifted) == 1 and lifted[0].endswith("example.com")
    assert agent_requests.open_requests(env["memory"]) == []
    assert client.post(f"/inbox/{row['id']}/resolve", json={"action": "resolve", "optionKey": "done"}).status_code == 404
    assert not any((env["memory"] / "inbox").glob("*.md"))   # never a bank write


def test_an_agent_cannot_answer_a_request_for_the_person(env):
    row = agent_requests.ask(env["memory"], agent="codex", site="example.com")
    resp = TestClient(main.app).post(f"/inbox/{row['id']}/resolve",
                                     json={"action": "resolve", "optionKey": "done", "via": "agent"})
    assert resp.status_code == 403
    from api.services import mcp_tools

    assert "agent_request" in mcp_tools.APP_ONLY_INBOX_KINDS
    assert not mcp_tools.nudge_visible({"kind": "agent_request"}, wanted=None, today="2026-10-22")


def test_the_rest_door_files_a_request_and_refuses_a_non_host(env):
    client = TestClient(main.app)
    made = client.post("/agent-requests", json={"site": "example.com", "reason": "to read a thread",
                                                "agent": "not-in-the-table"})
    assert made.status_code == 201 and made.json()["agentName"] == "An agent"
    assert client.post("/agent-requests", json={"site": "https://example.com/a?b"}).status_code == 422
    assert client.post("/agent-requests", json={"site": "example.com", "kind": "pay"}).status_code == 422


def test_a_login_wall_in_a_read_files_a_request_naming_the_agent(env):
    from api.services import mcp_tools

    class Ctx:
        harness, client_name = "unknown", "opencode"

    mcp_tools._ask_person_to_sign_in(Ctx(), env["memory"], "example.com", None, url_hash="h1",
                                     fallback="to read the page you asked it to read")
    (row,) = agent_requests.open_requests(env["memory"])
    assert (row["agent"], row["reason"], row["url_hash"]) == ("opencode", "to read the page you asked it to read", "h1")


def test_requests_expire_and_never_show_in_a_demo_bank(env):
    agent_requests.ask(env["memory"], agent="codex", site="example.com",
                       now=datetime.now(timezone.utc) - timedelta(days=agent_requests.EXPIRES_AFTER_DAYS + 1))
    assert agent_requests.open_requests(env["memory"]) == []
    agent_requests.ask(env["memory"], agent="codex", site="example.com")
    assert len(inbox_service.agent_request_items(env["memory"])) == 1
    from api.services import demo_guard

    demo_guard.manifest_path(env["memory"]).write_text(f"kind: {demo_guard.DEMO_KIND}\n")
    assert inbox_service.agent_request_items(env["memory"]) == []


# --- G50/G215: a key is checked before it is saved --------------------------------------------------------------------


def _check(result: str, models=None):
    async def fake(_provider, _key):
        return key_check.KeyCheck(result, frozenset(models) if models else None)
    return fake


def test_a_refused_key_is_never_saved(env, monkeypatch):
    monkeypatch.setattr(key_check, "check", _check("refused"))
    resp = TestClient(main.app).put("/connections/byok-xai/key", json={"key": "xai-example-0000-wxyz"})
    assert resp.status_code == 422 and "refused by xAI" in resp.json()["detail"]
    assert not secrets.secrets_path().exists() or "XAI_API_KEY" not in secrets.secrets_path().read_text()
    assert "xai-example" not in resp.text


def test_an_unreachable_provider_offers_save_without_checking(env, monkeypatch):
    monkeypatch.setattr(key_check, "check", _check("unreachable"))
    client = TestClient(main.app)
    assert client.put("/connections/byok-gemini/key", json={"key": "AIza-example-key-1234"}).status_code == 503
    saved = client.put("/connections/byok-gemini/key", json={"key": "AIza-example-key-1234", "check": False})
    body = saved.json()
    assert saved.status_code == 200 and body["connected"] and body["verifiedAt"] is None
    assert body["keyHint"] == "…1234" and body["keyStore"] == "file"
    assert "AIza-example" not in saved.text


def test_an_accepted_key_shows_its_last_four_and_when_it_was_checked(env, monkeypatch):
    monkeypatch.setattr(key_check, "check", _check("ok", ["gpt-5.4-mini"]))
    client = TestClient(main.app)
    body = client.put("/connections/byok-openai/key", json={"key": "sk-example-abcdef-9876"}).json()
    assert body["keyHint"] == "…9876" and body["verifiedAt"]
    assert "sk-example" not in json.dumps(client.get("/connections").json())
    gone = client.delete("/connections/byok-openai/key").json()
    assert gone["connected"] is False and secrets.verified_at("OPENAI_API_KEY") is None


def test_the_check_reads_model_lists_of_both_shapes():
    assert key_check._model_ids({"data": [{"id": "grok-4.3"}]}) == frozenset({"grok-4.3"})
    assert key_check._model_ids({"models": [{"name": "models/gemini-flash-latest"}]}) == frozenset(
        {"gemini-flash-latest"})
    assert key_check._model_ids({"x": 1}) is None
    assert key_check.default_listed(frozenset({"grok-4.20-0309-non-reasoning"}),
                                    "xai/grok-4.20-0309-non-reasoning") is True
    assert key_check.default_listed(None, "xai/x") is None


def test_every_key_card_has_a_probe_on_its_own_providers_host():
    from urllib.parse import urlparse

    from api.services.connections import byok

    for p in byok.PROVIDERS:
        probe = key_check.PROBES[p.id]
        assert urlparse(probe.url).scheme == "https", p.id


def test_the_gemini_card_warns_about_the_free_tier_before_a_key(env):
    import asyncio

    from api.services.connections import byok

    status = asyncio.run(byok.ByokAdapter("gemini").status())
    assert "free tier" in status.detail and status.terms_note


def test_a_bad_key_is_refused_by_each_providers_own_status(monkeypatch):
    """Measured 2026-10-22 with a made-up key: 401 everywhere but xAI and Gemini, which answer 400."""
    import asyncio

    import httpx

    real = httpx.AsyncClient

    def answer(status):
        transport = httpx.MockTransport(lambda request: httpx.Response(status, json={}))

        def client(*a, **k):
            k.pop("event_hooks", None)
            return real(*a, transport=transport, **k)
        return client

    for provider, status, expected in (("xai", 400, "refused"), ("gemini", 400, "refused"),
                                       ("openai", 400, "unreachable"), ("openai", 401, "refused"),
                                       ("deepinfra", 401, "refused"), ("together", 503, "unreachable")):
        monkeypatch.setattr(httpx, "AsyncClient", answer(status))
        assert asyncio.run(key_check._http_check(provider, "fake")).result == expected, (provider, status)
