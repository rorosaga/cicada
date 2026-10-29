"""G132 phase 1 B — a copy sends its home ONLY the device token the home issued for it (fail closed).

`CICADA_API_TOKEN` can hold this computer's own master token, and the master token lives in `$CICADA_HOME/api_token`:
neither ever reaches the home. Every door that talks to the home is exercised — the follower's requests, its events
stream, the outbox's tool and REST transactions, the app's forwarded write and `GET /sleep/status`, the tool door's
write, the hooks' capture target — set up by environment and by file. Without a device token nothing is sent at all and
the copy says so. Synthetic only; the "home" is a fake opener that records every request."""
from __future__ import annotations

import io
import json
import urllib.error

import pytest
from fastapi.testclient import TestClient

from api.services import replica, runtime_layout, tx_outbox

MASTER = "master-secret-AAAAAAAAAAAAAAAAAAAAAAAA"
DEVICE = "cic_dev_abcd1234_devicesecretBBBBBBBBBBBBBBBB"
HOME = "https://home.example.ts.net"


class _Resp(io.BytesIO):
    status = 200
    headers = {"Content-Type": "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeHome:
    """Records every request a copy would send to its home and answers 200 {}."""

    def __init__(self):
        self.sent: list[dict] = []

    def open(self, req, timeout=None):
        self.sent.append({"url": req.full_url, "headers": {k.lower(): v for k, v in req.header_items()},
                          "data": req.data or b""})
        if req.full_url.endswith("/sync/events"):
            replica._STOP.set()              # one connection is enough for the test
            raise urllib.error.URLError("closed")
        return _Resp(json.dumps({"text": "ok", "code": None, "seq": 1}).encode())


@pytest.fixture(params=["env", "file"])
def copy_machine(request, tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    (home / "api_token").write_text(MASTER + "\n")
    (home / "device_token").write_text(DEVICE + "\n")
    monkeypatch.setenv("CICADA_HOME", str(home))
    monkeypatch.setenv("CICADA_API_TOKEN", MASTER)          # the common local setting: the master token in the env
    if request.param == "env":
        monkeypatch.setenv("CICADA_REPLICA_OF", HOME)
    else:
        monkeypatch.delenv("CICADA_REPLICA_OF", raising=False)
        (home / "replica_of").write_text(HOME + "\n")
    fake = FakeHome()
    monkeypatch.setattr(runtime_layout, "opener", lambda: fake)
    monkeypatch.setattr(replica, "_STOP", __import__("threading").Event())
    return home, fake


def _assert_only_the_device_token(fake: FakeHome):
    assert fake.sent, "nothing was sent"
    for req in fake.sent:
        blob = json.dumps(req["headers"]) + req["data"].decode("utf-8", "replace")
        assert MASTER not in blob, req["url"]
        assert req["headers"].get("authorization") == f"Bearer {DEVICE}", req["url"]


def test_every_door_to_the_home_sends_the_device_token_and_never_the_master(copy_machine, tmp_path, monkeypatch):
    home, fake = copy_machine
    assert runtime_layout.is_replica() and runtime_layout.replica_token() == DEVICE
    replica.request("GET", "/sync/status")
    replica.send(tx_outbox.tool_entry("cicada_save_episode", {"content": "placeholder"}, bank_id="b" * 32,
                                      base_seq=1, caller={}, surface="mcp", options={}))
    replica.send(tx_outbox.rest_entry("POST", "/capture/note", "", b'{"text": "placeholder"}', "application/json",
                                      bank_id="b" * 32, base_seq=1))
    replica._events_reader()
    from api.hooks import hook_client

    base, token, problem = hook_client.target(dict(__import__("os").environ))
    assert (base, token, problem) == (HOME, DEVICE, None)
    # The app's doors on this computer: the tool door's write and a forwarded REST write and /sleep/status.
    from _synthetic_bank import _bank
    from api import config
    from api.services import replica_guard

    with replica_guard.applying():          # the copy's files, as the follower would have written them
        bank = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    monkeypatch.setenv("CICADA_API_AUTH", "on")
    monkeypatch.setattr(replica, "start", lambda: None)
    monkeypatch.setattr(replica, "wait_for_seq", lambda *a, **k: True)
    config.get_settings.cache_clear()
    from api.main import app

    with TestClient(app) as client:
        local = {"Authorization": f"Bearer {MASTER}"}
        assert client.post("/tools/call", headers=local, json={
            "tool": "cicada_save_episode", "arguments": {"content": "placeholder"}}).status_code == 200
        assert client.post("/inbox/inbox-001/resolve", headers=local, json={"option_key": "keep"}).status_code == 200
        assert client.get("/sleep/status", headers=local).status_code == 200
    config.get_settings.cache_clear()
    urls = [r["url"] for r in fake.sent]
    assert any(u.endswith("/tools/call") for u in urls) and any(u.endswith("/inbox/inbox-001/resolve") for u in urls)
    assert any(u.endswith("/sleep/status") for u in urls) and any(u.endswith("/sync/events") for u in urls)
    _assert_only_the_device_token(fake)


def test_without_a_device_token_nothing_is_sent_and_the_copy_says_so(copy_machine):
    home, fake = copy_machine
    (home / "device_token").unlink()
    assert runtime_layout.replica_token() == ""
    with pytest.raises(replica.NoDeviceToken):
        replica.request("GET", "/sync/status")
    assert replica.send(tx_outbox.tool_entry("cicada_save_episode", {}, bank_id=None, base_seq=None, caller={},
                                             surface="mcp", options={})) == (None, None)
    from api.hooks import hook_client

    _base, token, problem = hook_client.target(dict(__import__("os").environ))
    assert token == "" and problem
    import threading

    reader = threading.Thread(target=replica._events_reader, daemon=True)
    reader.start()                                          # it finds no token, says so, and waits
    __import__("time").sleep(0.3)
    replica._STOP.set()
    reader.join(5)
    assert fake.sent == []
    assert replica.state()["status"] == "no_token" and "Pair it again" in replica.state()["text"]


def test_a_master_token_saved_as_the_device_token_is_refused(copy_machine):
    home, fake = copy_machine
    (home / "device_token").write_text(MASTER + "\n")      # a token that is not a device token: never sent
    assert runtime_layout.replica_token() == ""
    with pytest.raises(replica.NoDeviceToken):
        replica.request("GET", "/sync/status")
    assert fake.sent == []
