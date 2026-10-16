"""G181 phase 3 — the Mac app as a server's client, the Devices page, and where memory came from.

Backend halves only (the Swift side is `HeadlessAppTests`): a device may read `GET /devices` (marked `current`) and
still never issue or revoke; a new episode written while serving a device's request records `device`; Sleep's run
credits nothing to the device that started it; the device rides the Saved rows, the provenance conversations and the
Reader's document; the app's `$CICADA_HOME/api_base` makes the hooks, the stdio MCP server and the CLI clients exactly
as `CICADA_API_BASE` does, and the stdlib restatement in `hook_client` answers the same. Synthetic banks and
placeholder names only; nothing reaches the network.
"""
from __future__ import annotations

import inspect
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.hooks import hook_client
from api.services import (
    bank_index, device_context, episode_ids, markdown_parser, provenance, runtime_layout, sleep_cycle,
)
from api.services.claims import Claim, Evidence, write_claims


@pytest.fixture
def server(tmp_path, monkeypatch):
    """A backend app with auth ON, a scaffolded synthetic root, and its own CICADA_HOME."""
    from api import config
    from api.main import app
    from api.services.auth import get_token

    root = tmp_path / "server-memory"
    root.mkdir()
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "server-home"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(root))
    monkeypatch.setenv("CICADA_API_AUTH", "on")
    monkeypatch.delenv("CICADA_API_TOKEN", raising=False)
    config.get_settings.cache_clear()
    master = get_token()
    with TestClient(app) as client:
        yield client, master, root
    config.get_settings.cache_clear()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _turn(session: str) -> dict:
    return {"harness": "cursor", "session_id": session,
            "messages": [{"speaker": "user", "text": "Plan the alpha-project launch for next week."}]}


def _episode_fm(client, master, episode_id: str) -> dict:
    from api import config

    memory = config.get_settings().memory_path
    return markdown_parser.parse(memory / "episodes" / f"{episode_id}.md").frontmatter


# --- the Devices page's read --------------------------------------------------------------------------------------

def test_a_device_reads_the_list_marked_as_itself_and_still_cannot_issue_or_revoke(server):
    client, master, _root = server
    laptop = client.post("/devices", json={"name": "laptop"}, headers=_auth(master)).json()
    desk = client.post("/devices", json={"name": "desk"}, headers=_auth(master)).json()
    listed = client.get("/devices", headers=_auth(laptop["token"]))
    assert listed.status_code == 200
    rows = {d["name"]: d for d in listed.json()["devices"]}
    assert rows["laptop"]["current"] is True and rows["desk"]["current"] is False
    # ids, names and times only: never a token or a hash
    assert set(rows["laptop"]) == {"id", "name", "createdAt", "revokedAt", "lastUsedAt", "useCount", "active",
                                   "current"}
    assert rows["laptop"]["lastUsedAt"]                       # the read itself was a use: last seen is now
    assert client.post("/devices", json={"name": "x"}, headers=_auth(laptop["token"])).status_code == 403
    assert client.delete(f"/devices/{desk['device']['id']}", headers=_auth(laptop["token"])).status_code == 403
    assert all(d["current"] is False for d in client.get("/devices", headers=_auth(master)).json()["devices"])


# --- where memory came from ---------------------------------------------------------------------------------------

def test_an_episode_a_device_posts_records_the_device_and_the_server_s_own_records_none(server):
    client, master, _root = server
    made = client.post("/devices", json={"name": "laptop"}, headers=_auth(master)).json()
    from_device = client.post("/capture/turn", json=_turn("sess-device-1"), headers=_auth(made["token"]))
    assert from_device.status_code == 200, from_device.text
    from_server = client.post("/capture/turn", json=_turn("sess-server-1"), headers=_auth(master))
    assert from_server.status_code == 200
    assert _episode_fm(client, master, from_device.json()["episodeId"]).get("device") == made["device"]["id"]
    assert "device" not in _episode_fm(client, master, from_server.json()["episodeId"])


def test_the_binding_never_outlives_its_request_and_a_writer_s_own_device_wins(tmp_path):
    episodes = tmp_path / "episodes"
    episodes.mkdir()
    device_context.bind("abcd1234")
    try:
        first = episode_ids.create_episode(episodes, {"id": "ep_2026-10-16_001", "title": "t"}, "user: hi")
        second = episode_ids.create_episode(episodes, {"id": "ep_2026-10-16_002", "device": "zzzz9999"}, "user: hi")
    finally:
        device_context.clear()
    third = episode_ids.create_episode(episodes, {"id": "ep_2026-10-16_003"}, "user: hi")
    fm = {i: markdown_parser.parse(episodes / f"{i}.md").frontmatter for i in (first, second, third)}
    assert fm[first]["device"] == "abcd1234"
    assert fm[second]["device"] == "zzzz9999"
    assert "device" not in fm[third]


def test_sleep_credits_nothing_to_the_device_that_started_it():
    """A client's click starts Sleep inside its own request (BackgroundTasks); the run clears the binding before it
    writes anything."""
    src = inspect.getsource(sleep_cycle.run)
    assert src.index("device_context.clear()") < src.index('_state.status = "running"')


def _built(memory: Path) -> Path:
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir()
    text = "user: alpha-project moves to the new server next week."
    markdown_parser.write(memory / "episodes" / "ep_2026-10-16_001.md",
                          {"id": "ep_2026-10-16_001", "timestamp": "2026-10-16T10:00:00+00:00", "title": "Move",
                           "session_id": "s-1", "harness": "claude-code", "device": "abcd1234"}, text)
    markdown_parser.write(memory / "episodes" / "ep_2026-10-15_001.md",
                          {"id": "ep_2026-10-15_001", "timestamp": "2026-10-15T10:00:00+00:00", "title": "Earlier"},
                          "user: alpha-project needs a server.")
    from api.services import evidence

    start = text.index("alpha-project moves")
    claims = [
        Claim(id="clm_1", text="alpha-project moves servers", subject="alpha-project", authored_by="user",
              recorded_at="2026-10-16", source_episodes=["ep_2026-10-16_001"],
              evidence=[Evidence(episode="ep_2026-10-16_001", start=start, end=start + 19, kind="user",
                                 hash=evidence.body_hash(text))]),
        Claim(id="clm_2", text="alpha-project needs a server", subject="alpha-project", authored_by="user",
              recorded_at="2026-10-15", source_episodes=["ep_2026-10-15_001"]),
    ]
    page = memory / "entities" / "alpha-project.md"
    markdown_parser.write(page, {"name": "Alpha Project", "type": "project", "status": "active",
                                 "source_episodes": ["ep_2026-10-15_001", "ep_2026-10-16_001"]},
                          write_claims("# Alpha Project\n", claims))
    bank_index.invalidate()
    return page


def test_provenance_and_the_reader_say_which_device_a_conversation_came_from(tmp_path):
    memory = tmp_path / "memory"
    page = _built(memory)
    rows = {r.episode_id: r for r in provenance.entity_provenance(memory, page).conversations}
    assert rows["ep_2026-10-16_001"].device == "abcd1234"
    assert rows["ep_2026-10-15_001"].device is None
    doc = provenance.episode_document(memory, "ep_2026-10-16_001")
    assert doc.device == "abcd1234" and doc.model_dump(by_alias=True)["device"] == "abcd1234"
    assert provenance.episode_document(memory, "ep_2026-10-15_001").device is None


def test_a_saved_row_says_which_device_saved_it(server):
    """The Saved row reads the device from its save's episode (the one `url_index` names) — no new index."""
    client, master, _root = server
    from api import config
    from api.services import media_ingestor

    memory = config.get_settings().memory_path
    rows = []
    for n, (url, device) in enumerate([("https://example.com/alpha-guide", "abcd1234"),
                                       ("https://example.com/beta-guide", None)], start=1):
        ep = f"ep_2026-10-16_00{n}"
        fm = {"id": ep, "timestamp": "2026-10-16T10:00:00+00:00", "title": url, "source": "url", "origin": "manual"}
        if device:
            fm["device"] = device
        markdown_parser.write(memory / "episodes" / f"{ep}.md", fm, f"Saved {url}")
        entity = f"media-guide-{n}"
        markdown_parser.write(memory / "entities" / f"{entity}.md",
                              {"name": url, "type": "media", "status": "active", "origin": "manual"}, "## Summary\nx\n")
        rows.append((media_ingestor.url_hash(url), {"media_entity_id": entity, "url": url, "title": url,
                                                     "media_type": "url", "saved_at": "2026-10-16",
                                                     "episode_id": ep}))
    media_ingestor.save_url_index(memory, dict(rows))
    bank_index.invalidate()
    got = client.get("/sources", headers=_auth(master))
    assert got.status_code == 200, got.text
    by_url = {r["url"]: r.get("device") for r in got.json()["items"]}
    assert by_url == {"https://example.com/alpha-guide": "abcd1234", "https://example.com/beta-guide": None}


# --- the app's server setting reaches every client on the Mac --------------------------------------------------------

def test_the_app_s_api_base_file_makes_this_machine_a_client(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    env = {"CICADA_HOME": str(home)}
    assert runtime_layout.is_client(env) is False
    (home / "api_base").write_text("https://cicada.example.ts.net/\n")
    assert runtime_layout.is_client(env) and runtime_layout.backend_url(env) == "https://cicada.example.ts.net"
    # the environment still wins over the app's file
    assert runtime_layout.backend_url({**env, "CICADA_API_BASE": "http://127.0.0.1:18000"}) == "http://127.0.0.1:18000"
    (home / "api_base").write_text("http://cicada.example.ts.net\n")
    assert runtime_layout.is_client(env)                      # a bad address is still "not this machine's bank"
    with pytest.raises(ValueError):
        runtime_layout.backend_url(env)


def test_a_bare_environment_never_reaches_the_person_s_home(tmp_path, monkeypatch):
    fake_home = tmp_path / "person"
    (fake_home / ".cicada").mkdir(parents=True)
    (fake_home / ".cicada" / "api_base").write_text("https://cicada.example.ts.net\n")
    monkeypatch.setenv("HOME", str(fake_home))
    assert runtime_layout.is_client({}) is False
    assert hook_client.is_client({}) is False


@pytest.mark.parametrize("env_base, file_base, with_home", [
    (None, None, True), (None, "https://cicada.example.ts.net", True),
    ("https://a.example.ts.net", "https://b.example.ts.net", True), (None, "https://cicada.example.ts.net", False),
    ("", "http://127.0.0.1:18000", True),
])
def test_the_hooks_stdlib_rule_matches_the_layout(tmp_path, env_base, file_base, with_home):
    home = tmp_path / "home"
    home.mkdir()
    if file_base is not None:
        (home / "api_base").write_text(file_base + "\n")
    env = {"CICADA_HOME": str(home)} if with_home else {}
    if env_base is not None:
        env["CICADA_API_BASE"] = env_base
    assert hook_client.raw_base(env) == runtime_layout._raw_base(env)
    assert hook_client.is_client(env) == runtime_layout.is_client(env)


def test_the_real_environment_reads_the_file(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    (home / "api_base").write_text("https://cicada.example.ts.net\n")
    monkeypatch.setenv("CICADA_HOME", str(home))
    monkeypatch.delenv("CICADA_API_BASE", raising=False)
    assert runtime_layout.is_client(os.environ) and hook_client.is_client(os.environ)
    from api import cli

    assert cli._client_mode(os.environ)
