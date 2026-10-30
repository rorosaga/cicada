"""G132 phase 3b — pairing a computer over the relay, through the routes the app's Settings → Devices calls, between
two real backends and a relay on loopback.

* **Scanned** — the home's QR (v2: the code, the relay, a random slot, the home's public keys); the new computer posts
  it, the home's screen names it, the person confirms there; the new computer keeps a copy, bootstrapped over the
  relay alone (the home has no direct address).
* **Typed** — the new computer types the code and the relay's address; both screens show the same six digits; only
  after the person confirms on both does the welcome go and get accepted.
* **Two devices answered** — a second request on the same code voids it, and neither is added.
"""
from __future__ import annotations

import json

import pytest

from _synthetic_bank import _entity
from test_replica_two_machines import Machine, _git, _wait
from test_sync_relay_three_machines import RelayThread


def _publish(m: Machine) -> None:
    (m.cicada_home / "sync").mkdir(parents=True, exist_ok=True)
    (m.cicada_home / "sync" / "settings.json").write_text(json.dumps({"publish": True}))


def _relay_ready(m: Machine) -> bool:
    try:
        r = m.call("GET", "/sync/transport")[1]["relay"]
    except Exception:  # noqa: BLE001
        return False
    return bool(r.get("running") and r.get("connected"))


@pytest.fixture
def two(tmp_path):
    relay = RelayThread(tmp_path / "relay.db")
    home = Machine(tmp_path, "home", CICADA_SYNC_RELAY=relay.url)
    new = Machine(tmp_path, "new")
    try:
        _publish(home)
        (home.memory / "entities").mkdir(parents=True, exist_ok=True)
        _entity(home.memory, "alpha-project", type="project", confidence=0.9)
        home.start()
        assert _wait(lambda: _relay_ready(home), 30), home.log.read_text()[-3000:]
        new.start()
        yield relay, home, new
    finally:
        new.stop()
        home.stop()
        relay.stop()


def _head(m: Machine) -> str:
    return _git(m.bank, "rev-parse", "HEAD").strip()


def test_a_computer_scans_the_qr_and_keeps_a_copy_over_the_relay(two):
    relay, home, new = two
    status, made = home.call("POST", "/devices/pairing/relay")
    assert status == 201, made
    qr = made["qr"]
    assert qr["v"] == 2 and qr["relay"] == relay.url and set(qr["home"]) == {"ed", "x"} and "url" not in qr
    status, join = new.call("POST", "/sync/relay/join", {"qr": qr})
    assert status == 202, join

    def answered():
        s = home.call("GET", f"/devices/pairing/relay/{made['session']['id']}")[1]["session"]
        return s if s["state"] == "confirm" else None

    session = _wait(answered, 30)
    assert session and session["name"] and session["sas"] is None and session["typed"] is False
    status, done = home.call("POST", f"/devices/pairing/relay/{made['session']['id']}/confirm")
    assert status == 200 and done["session"]["state"] == "done", done
    # The new computer starts again as a copy and makes its first copy over the relay alone.
    assert _wait(lambda: (new.cicada_home / "replica_of").exists(), 30)
    assert (new.cicada_home / "replica_of").read_text().strip() == "https://home.relay.invalid"
    for name in ("device_token", "replica_of", "sync/relay.json", "sync/relay-state.json"):
        assert (new.cicada_home / name).stat().st_mode & 0o777 == 0o600, name

    def copied():
        try:
            return new.call("GET", "/sync/replica")[1]["mode"] == "replica" and _head(new) == _head(home)
        except Exception:  # noqa: BLE001
            return False

    assert _wait(copied, 90), new.log.read_text()[-4000:]
    stats = new.call("GET", "/sync/transport")[1]
    assert stats["requests"]["relay"] >= 2 and stats["requests"]["direct"] == 0, stats
    # The code was spent through the device store: the device is a full one, with its relay keys on its row.
    devices = home.call("GET", "/devices")[1]["devices"]
    assert any(d["kind"] == "full" for d in devices)


def test_typed_code_shows_the_same_six_digits_and_needs_both_confirmations(two):
    relay, home, new = two
    made = home.call("POST", "/devices/pairing/relay")[1]
    status, join = new.call("POST", "/sync/relay/join", {"code": made["code"], "relay": relay.url})
    assert status == 202, join
    here = _wait(lambda: (lambda j: j if j.get("state") == "confirm" else None)(
        new.call("GET", "/sync/relay/join")[1]), 30)
    there = _wait(lambda: (lambda s: s if s["state"] == "confirm" else None)(
        home.call("GET", f"/devices/pairing/relay/{made['session']['id']}")[1]["session"]), 30)
    assert here and there and here["sas"] == there["sas"] and len(here["sas"].replace(" ", "")) == 6
    assert new.call("POST", "/sync/relay/join/confirm")[0] == 200
    assert home.call("POST", f"/devices/pairing/relay/{made['session']['id']}/confirm")[1]["session"]["state"] \
        == "done"
    assert _wait(lambda: (new.cicada_home / "replica_of").exists(), 30), new.log.read_text()[-3000:]


def test_two_devices_answering_one_code_void_it(two, tmp_path):
    relay, home, new = two
    other = Machine(tmp_path, "other")
    other.start()
    try:
        made = home.call("POST", "/devices/pairing/relay")[1]
        assert new.call("POST", "/sync/relay/join", {"qr": made["qr"]})[0] == 202
        _wait(lambda: home.call("GET", f"/devices/pairing/relay/{made['session']['id']}")[1]["session"]["state"]
              == "confirm", 30)
        assert other.call("POST", "/sync/relay/join", {"code": made["code"], "relay": relay.url})[0] == 202
        s = _wait(lambda: (lambda s: s if s["state"] == "void" else None)(
            home.call("GET", f"/devices/pairing/relay/{made['session']['id']}")[1]["session"]), 30)
        assert s and s["text"].startswith("Two devices answered this code")
        status, body = home.call("POST", f"/devices/pairing/relay/{made['session']['id']}/confirm")
        assert status == 409
        assert not (new.cicada_home / "replica_of").exists() and not (other.cicada_home / "replica_of").exists()
    finally:
        other.stop()
