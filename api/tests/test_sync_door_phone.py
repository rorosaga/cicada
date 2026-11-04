"""G132 ruling 51f, the phone as it is for now (owner 2026-11-03: "for now, the phone i mainly want it as a way to
capture, so wether im outside, same wifi or wherever, i can send stuff to the same queue to get digested").

A real home backend (a Mac that shares nothing but this phone: it does not publish a log) and a phone-shaped client
(``_phone_like``): a capture-only device bound to its own key, no copy and no follower, its captures in a durable
outbox and the same route list a computer runs. Shown, with synthetic data and placeholder names only:

* pairing in the same room goes through the door with what the QR carries — the code and a one-time secret — and
  hands back the device's id, never a token; the door opens only once there is something to share;
* captures land in the home's episode queue through the door, as the phone's own words (``origin: phone``), and a
  capture-only device reaches nothing else;
* **the home asleep** — the Mac is off: captures wait in the phone's outbox, a month later still (an unsent capture
  never expires);
* **awake on another network** — the home answers at another address: the phone finds it, nothing is re-paired, and
  every waiting capture lands exactly once, even when an answer is lost on the way and the capture is sent again.
"""
from __future__ import annotations

import time

import pytest

from _phone_like import PhoneKey, PhoneLike
from _udp_wire import UdpWire
from test_replica_two_machines import Machine, _wait
from api.services import sync_door


def _notes(home: Machine, text: str) -> int:
    folder = home.bank / "episodes"
    return sum(1 for p in folder.glob("ep_*.md") if text in p.read_text()) if folder.exists() else 0


@pytest.fixture
def home_and_phone(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_TELEMETRY", "off")
    home = Machine(tmp_path, "mac")
    wires = []
    try:
        home.start()
        # Nothing shared yet: no door.
        assert home.call("GET", "/sync/discovery")[0] == 404
        status, made = home.call("POST", "/devices/pairing", {"kind": "capture"})
        assert status == 201 and made["qr"] == {"v": 1, "url": made["qr"]["url"], "code": made["code"]}
        door = made["door"]
        assert door and door["home"] and door["key"] and door["pair"] and door["port"], made
        assert door["lan"] == [] and door["tailnet"] == []           # the suite's door is on loopback only
        assert door["t"] == ["udp"]                                    # the door is UDP; no TCP fallback held
        here = UdpWire(door["port"])                                   # the home network, as Bonjour resolves it
        wires.append(here)
        key = PhoneKey()
        target = sync_door.Target(door["home"], sync_door._b64d(door["key"]), door["sign"])   # noqa: SLF001
        stranger = sync_door.Identity("", key.jwk, key.sign)
        with pytest.raises(sync_door.Unreachable):                     # without the QR's secret: dropped
            sync_door.connect("127.0.0.1", here.port, target, stranger)
        device = sync_door.pair("127.0.0.1", here.port, target, stranger,
                                secret=sync_door._b64d(door["pair"]), code=made["code"], name="Example phone")
        assert device["kind"] == "capture" and device["keyBound"] is True and "token" not in str(device)
        with pytest.raises(sync_door.Unreachable):                     # the secret is spent
            sync_door.pair("127.0.0.1", here.port, target, stranger, secret=sync_door._b64d(door["pair"]),
                           code=made["code"], name="Again")
        phone = PhoneLike(tmp_path / "phone", device["id"], key, door)
        phone.find("127.0.0.1", here.port)
        yield home, phone, wires
    finally:
        home.stop()
        for w in wires:
            w.stop()


def test_captures_reach_the_queue_wait_while_the_home_sleeps_and_land_once_elsewhere(home_and_phone):
    home, phone, wires = home_and_phone
    here = wires[0]
    devices = len(home.call("GET", "/devices")[1]["devices"])

    # Same Wi-Fi: a capture lands at once, as the phone's own words.
    started = time.perf_counter()
    verdict, status, body = phone.capture("Placeholder note from the same network")
    first_ms = (time.perf_counter() - started) * 1000
    assert verdict == "landed" and status == 200 and body["status"] == "created", (verdict, status, body)
    assert _wait(lambda: _notes(home, "Placeholder note from the same network") == 1, 10)
    ep = next(p for p in (home.bank / "episodes").glob("ep_*.md") if "same network" in p.read_text()).read_text()
    assert "origin: phone" in ep
    # A capture-only device reaches nothing else through the door.
    status, _h, _b = sync_door.request("127.0.0.1", here.port, phone.target, phone.identity, "GET",
                                       "/sync/log?since=0", pool=phone.pool)
    assert status == 403
    status, _h, _b = sync_door.request("127.0.0.1", here.port, phone.target, phone.identity, "GET", "/state",
                                       pool=phone.pool)
    assert status == 403

    # The home asleep: three captures wait in the phone's outbox.
    home.stop()
    phone.network_changed()
    for i in range(3):
        verdict, _s, _b = phone.capture(f"Placeholder note while away {i}")
        assert verdict in ("wait", "queued")             # kept: the first waits, the others behind it
    assert phone.waiting() == 3
    month = time.time() + 30 * 86_400
    phone.flush(now=lambda: month)                                     # a month later: still waiting, none expired
    assert phone.waiting() == 3

    # Awake on another network, at another address: the phone finds it there. Nothing is re-paired.
    here.down()
    home.start()
    there = UdpWire(here.target)                  # the same door, reached at another address
    wires.append(there)
    phone.network_changed()
    phone.find("127.0.0.1", there.port)
    # The first answer is lost on the way back: the capture is sent again by the next flush, and kept once.
    there.mode = "cut_answers"
    phone.flush()
    there.mode = "up"
    phone.network_changed()
    started = time.perf_counter()
    decided = phone.flush()
    landed_ms = (time.perf_counter() - started) * 1000
    assert all(v[0] == "landed" for v in decided.values()) and phone.waiting() == 0, decided
    for i in range(3):
        assert _wait(lambda i=i: _notes(home, f"Placeholder note while away {i}") == 1, 10)
    time.sleep(1)
    assert all(_notes(home, f"Placeholder note while away {i}") == 1 for i in range(3))
    assert len(home.call("GET", "/devices")[1]["devices"]) == devices
    print(f"\nphone: first capture {first_ms:.0f} ms; three waiting captures landed {landed_ms:.0f} ms after the home "
          f"answered on the new network")
