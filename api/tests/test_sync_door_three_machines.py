"""G132 ruling 51f, end to end: three real backends on loopback, the route list and the home-network door.

ALPHA holds the memory and publishes it; BRAVO and CHARLIE keep copies, paired through the configured address (a
``Wire`` the test can cut, standing in for the person's tailnet address). Each door stays on loopback and is reached
only through UDP forwarders the test owns (``UdpWire``; a path that goes away goes silent, as a real one does) —
``door_a`` (the home network) and ``door_b`` (another network, where the home answers at another address) — handed to
a copy the way the app's Bonjour does (``POST /sync/discovered``). Shown, with
synthetic data and placeholder names only:

* the door is preferred over the configured address, carries every catch-up and write with no token on it, and its
  watch tells the copy of a commit at once;
* **a network switch** — the home network goes away, the copy queues (its write waits; it reads its own copy), the
  home answers on another network at another address: the copy moves there with nothing re-paired and fetches only
  the commits it missed; its queued write lands once;
* **move back** — the copy leaves for the configured address when the door goes and comes back to the door as soon
  as it answers again, at the app's word;
* the ledger records which route, as enums only.
"""
from __future__ import annotations

import json
import os
import subprocess
import time

import pytest

from _synthetic_bank import _entity
from _udp_wire import UdpWire
from test_replica_two_machines import Machine, _git, _wait
from test_sync_relay_three_machines import Wire, _follow, _following, _head, _items, _publish, _tool, _transport


class CountingWire(Wire):
    """A ``Wire`` that counts the bytes it carried back to the client (the home's answers)."""

    def __init__(self, target_port: int):
        self.carried = 0
        super().__init__(target_port)

    def _pipe(self, src, dst, drop):
        is_answer = src not in self.live[::2]           # live is [client, upstream, ...]: upstream sockets are odd
        try:
            while True:
                data = src.recv(65536)
                if not data:
                    break
                if drop:
                    continue
                if is_answer:
                    self.carried += len(data)
                dst.sendall(data)
        except OSError:
            pass
        finally:
            for s in (src, dst):
                try:
                    s.close()
                except OSError:
                    pass


def _routes(m: Machine) -> dict:
    try:
        return m.call("GET", "/sync/routes")[1] or {}
    except Exception:  # noqa: BLE001
        return {}


def _active(m: Machine) -> str | None:
    return (_routes(m).get("toHome") or {}).get("active")


def _door_port(m: Machine) -> int:
    return m.call("GET", "/sync/discovery")[1]["advertise"]["port"]


def _found(m: Machine, *wires) -> int:
    status, body = m.call("POST", "/sync/discovered", {"doors": [{"host": "127.0.0.1", "port": w.port} for w in wires],
                                                       "lanAllowed": True})
    assert status == 200, body
    return body["doors"]


def _network(m: Machine, event: str = "changed") -> None:
    assert m.call("POST", "/sync/network", {"event": event})[0] == 200


def _has_home_door(m: Machine) -> bool:
    mirror = list(m.cicada_home.glob("sync/*/devices.json"))
    return any(any(r.get("is_self") and r.get("door") for r in json.loads(p.read_text())["devices"]) for p in mirror)


@pytest.fixture
def trio(tmp_path):
    alpha = Machine(tmp_path, "alpha")
    bravo = Machine(tmp_path, "bravo")
    charlie = Machine(tmp_path, "charlie")
    machines = (alpha, bravo, charlie)
    wires = {}
    try:
        _publish(alpha)
        (alpha.memory / "entities").mkdir(parents=True, exist_ok=True)
        _entity(alpha.memory, "alpha-project", type="project", confidence=0.9)
        alpha.start()
        for i in range(60):           # some history, so "only what it missed" is measured against a real full copy
            _tool(alpha, "cicada_add_backlog_item", project="alpha-project", title=f"History {i}",
                  description=os.urandom(1500).hex())
        tokens = {}
        for m, name in ((bravo, "bravo-laptop"), (charlie, "charlie-desk")):
            status, made = alpha.call("POST", "/devices", {"name": name})
            assert status in (200, 201), made
            tokens[m] = made["token"]
            wires[m] = CountingWire(alpha.port)
            _follow(m, wires[m].url, made["token"])
            m.start()
        for m in (bravo, charlie):
            assert _wait(lambda m=m: _following(m, alpha), 60), m.log.read_text()[-3000:]
            assert _wait(lambda m=m: _has_home_door(m), 90), m.log.read_text()[-3000:]
        port = _door_port(alpha)
        wires["door_a"] = UdpWire(port)            # the door is UDP: its paths are datagram forwarders
        wires["door_b"] = UdpWire(port)
        yield alpha, bravo, charlie, wires, tokens
    finally:
        for m in machines:
            m.stop()
        for w in wires.values():
            w.stop()


def test_the_door_is_preferred_carries_everything_and_survives_a_network_switch(trio):
    alpha, bravo, charlie, wires, tokens = trio
    devices_before = len(alpha.call("GET", "/devices")[1]["devices"])
    token_before = (bravo.cicada_home / "device_token").read_text()

    # 1. At home: the app finds the door on this network; the copy moves to it at once.
    assert _found(bravo, wires["door_a"]) == 1
    _tool(alpha, "cicada_add_backlog_item", project="alpha-project", title="Seen at home", description="x")
    assert _wait(lambda: _following(bravo, alpha) and _active(bravo) == "lan", 30), _routes(bravo)
    # The configured address goes away: the door alone carries catch-ups (told by its watch) and writes.
    wires[bravo].down()
    timings = []
    for i in range(5):
        _tool(alpha, "cicada_add_backlog_item", project="alpha-project", title=f"Door item {i}", description="x")
        want, started = _head(alpha), time.perf_counter()
        assert _wait(lambda: _head(bravo) == want, 30, every=0.02), bravo.log.read_text()[-3000:]
        timings.append((time.perf_counter() - started) * 1000)
    _tool(bravo, "cicada_add_backlog_item", project="alpha-project", title="From bravo by the door", description="x")
    assert _wait(lambda: _items(alpha, "From bravo by the door") == 1, 30)
    stats = _transport(bravo)
    assert stats["requests"]["door"] > 0 and stats["lastRoute"] == "lan", stats
    print(f"\nfast-forward over the door (n=5): {sorted(round(t) for t in timings)} ms")

    # 2. The network switch: the home network is gone. The copy queues; its reads are its own copy's.
    wires["door_a"].down()
    _network(bravo)
    before = _head(bravo)
    for i in range(5):
        _tool(alpha, "cicada_add_backlog_item", project="alpha-project", title=f"Missed {i}", description="x")
    status, body = bravo.call("POST", "/tools/call", {"tool": "cicada_add_backlog_item", "arguments": {
        "project": "alpha-project", "title": "Queued between networks", "description": "x"},
        "caller": {"harness": "claude-code"}}, timeout=90)
    assert status == 200 and (body.get("code") == "queued_for_home" or body.get("data", {}).get("queued")), body
    assert _wait(lambda: _active(bravo) is None and (_routes(bravo).get("toHome") or {}).get("queued"), 30), \
        _routes(bravo)
    assert _head(bravo) == before
    assert bravo.call("GET", "/sync/replica")[1]["outbox"]["waiting"] >= 1

    # The home answers on the other network, at another address: the app finds it there.
    full = subprocess.run(["git", "bundle", "create", "-", "--all"], cwd=alpha.bank, capture_output=True).stdout
    started = time.perf_counter()
    assert _found(bravo, wires["door_b"]) == 1
    assert _wait(lambda: _head(bravo) == _head(alpha), 60, every=0.02), bravo.log.read_text()[-3000:]
    caught_up_ms = (time.perf_counter() - started) * 1000
    assert _wait(lambda: _items(alpha, "Queued between networks") == 1, 30), bravo.log.read_text()[-3000:]
    time.sleep(2)
    assert _items(alpha, "Queued between networks") == 1                              # once
    assert bravo.call("GET", "/sync/replica")[1]["outbox"]["waiting"] == 0
    # Nothing re-paired: the same token, the same device list, the same copy (only what it missed was fetched).
    assert (bravo.cicada_home / "device_token").read_text() == token_before
    assert len(alpha.call("GET", "/devices")[1]["devices"]) == devices_before
    assert _git(bravo.bank, "merge-base", "--is-ancestor", before, "HEAD") == ""
    carried = wires["door_b"].carried
    print(f"caught up on the new network in {caught_up_ms:.0f} ms; {carried} bytes over it, a full bundle is "
          f"{len(full)} bytes")
    assert carried < len(full) / 2, (carried, len(full))

    # 3. Move back: the configured address is up again; the door stays first. The door goes: the copy leaves for the
    # configured address within one request. The door is back: at the app's word the copy returns to it.
    wires[bravo].up()
    wires["door_b"].down()
    _network(bravo)
    _tool(alpha, "cicada_add_backlog_item", project="alpha-project", title="Over the configured address",
          description="x")
    assert _wait(lambda: _following(bravo, alpha) and _active(bravo) == "configured", 60), _routes(bravo)
    wires["door_b"].up()
    started = time.perf_counter()
    _network(bravo, "returned")
    _tool(alpha, "cicada_add_backlog_item", project="alpha-project", title="Back on the door", description="x")
    assert _wait(lambda: _following(bravo, alpha) and _active(bravo) == "lan", 30, every=0.02), _routes(bravo)
    print(f"moved back to the door {(time.perf_counter() - started) * 1000:.0f} ms after the app's word")

    # CHARLIE never had a door route: it followed over the configured address all along.
    assert _wait(lambda: _following(charlie, alpha), 30)
    assert _transport(charlie)["requests"]["door"] == 0

    # The ledger: which route, as enums only — never an address or a port.
    rows = [json.loads(line) for p in (bravo.cicada_home / "telemetry").glob("*.jsonl")
            for line in p.read_text().splitlines()]
    routes = [r for r in rows if r.get("kind") == "sync_route"]
    assert {r["refs"]["route"] for r in routes} >= {"lan", "none", "configured"}, routes
    raw = json.dumps(routes)
    assert "127.0.0.1" not in raw and str(wires["door_b"].port) not in raw and str(alpha.port) not in raw
    served = [json.loads(line) for p in (alpha.cicada_home / "telemetry").glob("*.jsonl")
              for line in p.read_text().splitlines()]
    assert any(r.get("kind") == "sync_route" and r["refs"]["side"] == "door" for r in served)


def test_a_revoked_copy_is_refused_at_the_door(trio):
    alpha, bravo, _charlie, wires, tokens = trio
    assert _found(bravo, wires["door_a"]) == 1
    wires[bravo].down()
    _tool(alpha, "cicada_add_backlog_item", project="alpha-project", title="Before the revoke", description="x")
    assert _wait(lambda: _following(bravo, alpha), 30)
    bravo_id = tokens[bravo].split("_")[2]
    assert alpha.call("DELETE", f"/devices/{bravo_id}")[0] == 200
    _tool(alpha, "cicada_add_backlog_item", project="alpha-project", title="After the revoke", description="x")
    time.sleep(6)
    assert _items(bravo, "After the revoke") == 0
    # Its sessions were closed at the revoke, and its key is dropped at the door like any stranger's: the door tells
    # an unproven key nothing, so over the door alone a revoked copy sees its home as unreachable, never a 401.
    assert _wait(lambda: bravo.call("GET", "/sync/replica")[1]["replica"]["status"] in ("offline", "revoked"), 30)
    assert _wait(lambda: (_routes(bravo).get("toHome") or {}).get("queued") is True, 30), _routes(bravo)
    assert (_routes(alpha).get("door") or {}).get("dropped", 0) >= 1
