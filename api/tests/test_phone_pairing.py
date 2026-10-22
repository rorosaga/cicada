"""G212 (owner 2026-10-22): a phone pairs as a capture-only device, the QR carries this machine's tailnet serve of the
backend when the person's own `tailscale serve` gives one, a phone's thought is the person's own words, and a resend
with the same `Idempotency-Key` writes nothing twice. Synthetic bank, placeholder names, no network, and never the
real tailscale CLI."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from _synthetic_bank import _bank
from api.remote import reach
from api.services import device_tokens, markdown_parser


@pytest.fixture
def server(tmp_path, monkeypatch):
    from api import config
    from api.main import app

    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_API_AUTH", "on")
    monkeypatch.delenv("CICADA_API_TOKEN", raising=False)
    monkeypatch.setattr(reach, "tailnet_backend", lambda port, **kw: reach.TailnetBackend("missing", None))
    config.get_settings.cache_clear()
    from api.services.auth import get_token

    master = get_token()
    with TestClient(app) as client:
        yield client, master, memory
    config.get_settings.cache_clear()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _pair(client, master, kind=None, name="Example Phone"):
    body = {"kind": kind} if kind else {}
    made = client.post("/devices/pairing", json=body, headers=_auth(master)).json()
    paired = client.post("/pair", json={"code": made["code"], "name": name}).json()
    return made, paired["device"], paired["token"]


def _episodes(memory):
    return {p.stem: markdown_parser.parse(p).frontmatter for p in (memory / "episodes").glob("ep_*.md")}


# --- the capture-only kind --------------------------------------------------------------------------------------------

def test_a_phone_pairs_as_capture_only_by_default_and_reaches_only_its_routes(server):
    client, master, _ = server
    made, device, token = _pair(client, master)
    assert made["kind"] == "capture" and device["kind"] == "capture"
    assert set(made["qr"]) == {"v", "url", "code"}          # the payload the phone app decodes, unchanged
    for method, path in (("GET", "/graph"), ("GET", "/devices"), ("GET", "/devices/status"), ("GET", "/status"),
                         ("POST", "/tools/call"), ("POST", "/ask"), ("GET", "/agent-api/tokens")):
        assert client.request(method, path, headers=_auth(token), json={}).status_code == 403, path
    assert client.get("/capture/mine", headers=_auth(token)).status_code == 200
    health = client.get("/healthz", headers=_auth(token)).json()
    assert health["status"] == "ok" and health.get("memoryPath") is None   # the open answer, never the path


def test_a_computer_paired_as_full_and_a_device_added_by_hand_keep_every_route(server):
    client, master, _ = server
    _, device, token = _pair(client, master, kind="full", name="laptop")
    assert device["kind"] == "full" and client.get("/graph", headers=_auth(token)).status_code == 200
    added = client.post("/devices", json={"name": "server-b"}, headers=_auth(master)).json()
    assert added["device"]["kind"] == "full"
    assert client.post("/devices/pairing", json={"kind": "root"}, headers=_auth(master)).status_code == 422


def test_an_old_store_reads_every_device_and_code_as_full(tmp_path):
    import sqlite3

    path = tmp_path / "devices.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE devices (id TEXT PRIMARY KEY, name TEXT NOT NULL, token_hash TEXT NOT NULL, "
               "created_at TEXT NOT NULL, revoked_at TEXT, last_used_at TEXT, use_count INTEGER NOT NULL DEFAULT 0)")
    db.execute("INSERT INTO devices VALUES ('abcd1234', 'laptop', 'x', '2026-10-01T00:00:00+00:00', NULL, NULL, 0)")
    db.execute("CREATE TABLE pairings (id TEXT PRIMARY KEY, code_hash TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, "
               "expires_at TEXT NOT NULL, used_at TEXT, cancelled_at TEXT, device_id TEXT)")
    db.commit()
    db.close()
    store = device_tokens.DeviceStore(path)
    assert store.get("abcd1234").kind == "full"
    pairing, code = store.create_pairing(kind="capture")
    assert store.redeem(code, "Phone")[0].kind == "capture"


# --- the tailnet address in the QR -------------------------------------------------------------------------------------

SERVED = {"TCP": {"8443": {"HTTPS": True}},
          "Web": {"mac.example.ts.net:8443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8000"}}},
                  "mac.example.ts.net:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8765"}}}},
          "AllowFunnel": {"mac.example.ts.net:443": True}}


def test_a_tailnet_serve_of_the_backend_port_is_the_url_and_a_funnelled_one_never_is():
    assert reach.serve_url_for_port(SERVED, 8000) == ("https://mac.example.ts.net:8443", False)
    assert reach.serve_url_for_port(SERVED, 8765) == (None, True)          # the listener's funnel: not the backend
    funnelled = json.loads(json.dumps(SERVED))
    funnelled["AllowFunnel"]["mac.example.ts.net:8443"] = True
    assert reach.serve_url_for_port(funnelled, 8000) == (None, True)
    assert reach.serve_url_for_port({"Web": "nope"}, 8000) == (None, False)


def test_tailnet_backend_reads_the_serve_config_once_bounded_and_read_only():
    seen = []

    def run(argv, **kw):
        seen.append((argv, kw.get("timeout")))
        return type("Done", (), {"returncode": 0, "stdout": json.dumps(SERVED)})()

    found = reach.tailnet_backend(8000, which=lambda n: "/usr/bin/tailscale" if n == "tailscale" else None,
                                  run=run, exists=lambda p: False)
    assert found == reach.TailnetBackend("running", "https://mac.example.ts.net:8443", False)
    assert seen == [(["/usr/bin/tailscale", "funnel", "status", "--json"], 2.0)]
    assert reach.tailnet_backend(8000, which=lambda n: None, exists=lambda p: False).tailscale == "missing"


def test_the_pairing_fills_the_url_from_the_serve_and_says_what_to_run_without_one(server, monkeypatch):
    client, master, _ = server
    monkeypatch.setattr(reach, "tailnet_backend",
                        lambda port, **kw: reach.TailnetBackend("running", "https://mac.example.ts.net:8443"))
    made = client.post("/devices/pairing", json={}, headers=_auth(master)).json()
    assert made["qr"]["url"] == "https://mac.example.ts.net:8443" and made["reach"]["serveCommand"] is None
    monkeypatch.setattr(reach, "tailnet_backend", lambda port, **kw: reach.TailnetBackend("running", None, True))
    made = client.post("/devices/pairing", json={}, headers=_auth(master)).json()
    assert made["qr"]["url"] is None and made["reach"]["public"] is True
    assert made["reach"]["serveCommand"].startswith("tailscale serve --bg --https=8443 ")
    given = client.post("/devices/pairing", json={"url": "https://other.example.ts.net"}, headers=_auth(master)).json()
    assert given["qr"]["url"] == "https://other.example.ts.net" and given["reach"] is None


# --- a thought in the person's own words, and Idempotency-Key ---------------------------------------------------------

def test_a_phone_s_thought_is_the_person_s_own_words_with_its_device(server):
    client, master, memory = server
    _, device, token = _pair(client, master)
    sent = client.post("/capture/note", json={"text": "Try the alpha-project idea on Friday.", "title": "Idea"},
                       headers={**_auth(token), "Idempotency-Key": "phone-item-1"})
    assert sent.status_code == 200 and sent.json()["status"] == "created"
    fm = _episodes(memory)[sent.json()["episodeId"]]
    assert fm["origin"] == "phone" and fm["device"] == device["id"] and fm["processed"] is False
    body = (memory / "episodes" / f"{sent.json()['episodeId']}.md").read_text()
    assert "user: Try the alpha-project idea on Friday." in body
    mine = client.get("/capture/mine", headers=_auth(token)).json()["captures"]
    assert [c["id"] for c in mine] == [sent.json()["episodeId"]] and "body" not in json.dumps(mine)


def test_a_resent_note_with_the_same_key_writes_nothing_twice(server):
    client, master, memory = server
    _, _, token = _pair(client, master)
    headers = {**_auth(token), "Idempotency-Key": "phone-item-2"}
    first = client.post("/capture/note", json={"text": "One thought."}, headers=headers).json()
    before = set(_episodes(memory))
    again = client.post("/capture/note", json={"text": "One thought."}, headers=headers).json()
    assert again == first and set(_episodes(memory)) == before
    # Without a key the words are the identity: the same words twice are one episode.
    a = client.post("/capture/note", json={"text": "Same words."}, headers=_auth(token)).json()
    b = client.post("/capture/note", json={"text": "Same words."}, headers=_auth(token)).json()
    assert a["episodeId"] == b["episodeId"]


def test_a_resent_link_with_a_note_writes_no_second_note(server, monkeypatch):
    """The measured gap: a link with a note, resent after the server saved it, wrote one extra "Note on …"."""
    from api.services import media_ingestor

    async def offline_prepare(item, memory_path, client, idx):   # no network: the title is the URL's own
        return await real_prepare(item, memory_path, None, idx)

    real_prepare = media_ingestor.prepare_one
    monkeypatch.setattr(media_ingestor, "prepare_one", offline_prepare)
    monkeypatch.setattr(media_ingestor, "fetch_metadata", None, raising=False)
    client, master, memory = server
    _, device, token = _pair(client, master)
    headers = {**_auth(token), "Idempotency-Key": "phone-item-3"}
    body = {"url": "https://example.com/alpha-notes", "note": "for alpha"}
    first = client.post("/sources/save", json=body, headers=headers)
    assert first.status_code == 200, first.text
    before = set(_episodes(memory))
    again = client.post("/sources/save", json=body, headers=headers)
    assert again.status_code == 200 and again.json() == first.json()
    assert set(_episodes(memory)) == before
    assert any(fm.get("device") == device["id"] for fm in _episodes(memory).values())


def test_keys_are_per_sender_and_live_outside_the_bank(server, tmp_path):
    client, master, memory = server
    _, _, token = _pair(client, master)
    _, _, other = _pair(client, master, name="Other Phone")
    one = client.post("/capture/note", json={"text": "A."}, headers={**_auth(token), "Idempotency-Key": "k-1"}).json()
    two = client.post("/capture/note", json={"text": "B."}, headers={**_auth(other), "Idempotency-Key": "k-1"}).json()
    assert one["episodeId"] != two["episodeId"]
    assert (tmp_path / "home" / "idempotency" / "keys.db").exists()
    assert not any("idempotency" in str(p) for p in memory.rglob("*"))
