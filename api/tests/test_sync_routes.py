"""G132 ruling 51f — the ordered route list (T3 Code's model): first that answers wins, a route that did not answer is
skipped for a minute and then tried first again, a network change re-checks every route at once, nothing answering
is a queue, and the ledger learns which route was used as enums only."""
from __future__ import annotations

import json
import os
import stat

import pytest

from api.services import sync_routes
from api.services.sync_routes import Book, NoAnswer, Route, drive

LAN = Route("lan", "door", "192.168.1.20", 50001)
TAIL = Route("tailnet", "door", "100.70.1.2", 50001)
CONF = Route("configured", "http", base="https://home.example.ts.net:8443")
RELAY = Route("relay", "relay")


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "cicada"))
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    rows = []
    from api.services import telemetry

    monkeypatch.setattr(telemetry, "record", lambda ev: rows.append(ev))
    return rows


def _attempt(up: set, log: list):
    def attempt(route):
        log.append(route.kind)
        if route.kind in up:
            return route.kind
        raise NoAnswer("unreachable")
    return attempt


def test_the_order_is_lan_tailnet_configured_then_the_relay():
    assert [r.kind for r in sync_routes.order([RELAY, CONF, TAIL, LAN, LAN])] == ["lan", "tailnet", "configured",
                                                                                  "relay"]


def test_first_that_answers_wins_and_an_earlier_route_is_rechecked_every_minute(ledger):
    clock = Clock()
    book, log = Book(clock=clock), []
    routes = [LAN, TAIL, CONF]
    assert drive(book, routes, _attempt({"configured"}, log)) == "configured"     # away from home
    assert log == ["lan", "tailnet", "configured"]
    log.clear()
    clock.t += 30
    assert drive(book, routes, _attempt({"configured", "lan"}, log)) == "configured"
    assert log == ["configured"]                                                  # down routes skipped for a minute
    log.clear()
    clock.t += sync_routes.DOWN_S
    assert drive(book, routes, _attempt({"configured", "lan"}, log)) == "lan"     # moved back as soon as it answers
    assert log == ["lan"] and book.active_kind == "lan"
    moves = [e.refs for e in ledger if e.refs.get("event") == "moved"]
    assert [m["route"] for m in moves] == ["configured", "lan"] and moves[1]["before"] == "configured"


def test_a_network_change_rechecks_every_route_at_once(ledger):
    clock = Clock()
    nets = {"fp": "A"}
    book, log = Book(clock=clock, fingerprint=lambda: nets["fp"]), []
    routes = [LAN, CONF]
    drive(book, routes, _attempt({"configured"}, log))
    log.clear()
    nets["fp"] = "B"                                                              # joined another Wi-Fi
    clock.t += sync_routes.FINGERPRINT_S
    assert drive(book, routes, _attempt({"lan", "configured"}, log)) == "lan"
    assert log == ["lan"]
    # The app's word works the same, with no wait for the fingerprint.
    drive(book, routes, _attempt({"configured"}, log))
    book.note_network_change()
    log.clear()
    assert drive(book, routes, _attempt({"lan"}, log)) == "lan" and log == ["lan"]


def test_nothing_answering_is_a_queue_said_once(ledger):
    book = Book(clock=Clock())
    with pytest.raises(NoAnswer) as exc:
        drive(book, [LAN, CONF], _attempt(set(), []))
    assert exc.value.kind == "unreachable" and book.queued
    with pytest.raises(NoAnswer):
        drive(book, [LAN, CONF], _attempt(set(), []))
    queued = [e for e in ledger if e.refs.get("event") == "queued"]
    assert len(queued) == 1 and queued[0].refs["route"] == "none"


def test_a_request_that_may_have_landed_says_timeout():
    def attempt(route):
        raise NoAnswer("timeout" if route.kind == "lan" else "unreachable")
    with pytest.raises(NoAnswer) as exc:
        drive(Book(clock=Clock()), [LAN, CONF], attempt)
    assert exc.value.kind == "timeout"


def test_the_ledger_holds_enums_and_never_an_address(ledger):
    clock = Clock()
    book = Book(clock=clock)
    drive(book, [LAN, TAIL, CONF], _attempt({"tailnet"}, []))
    with pytest.raises(NoAnswer):
        drive(book, [LAN, TAIL, CONF], _attempt(set(), []))
    raw = json.dumps([e.refs for e in ledger])
    for leak in ("192.168", "100.70", "example", "50001", "https"):
        assert leak not in raw
    allowed = set(sync_routes.KINDS) | {"none", "device", "moved", "queued"} | set(sync_routes.CARRIER_ENUM.values())
    assert all(set(v for v in e.refs.values()) <= allowed for e in ledger)


def test_a_lan_route_is_dialed_only_when_this_backend_may_and_tailnet_only_on_a_tailnet():
    info = {"port": 50001, "key": "k", "lan": ["192.168.1.20", "8.8.8.8"], "tailnet": ["100.70.1.2"]}
    found = [{"host": "127.0.0.1", "port": 50002, "at": __import__("time").time()}]
    kinds = lambda rs: [(r.kind, r.host) for r in rs]   # noqa: E731
    assert kinds(sync_routes.door_routes(info, found, lan_ok=False, tailnet_ok=False)) == [("lan", "127.0.0.1")]
    assert kinds(sync_routes.door_routes(info, found, lan_ok=True, tailnet_ok=True)) == [
        ("lan", "127.0.0.1"), ("lan", "192.168.1.20"), ("tailnet", "100.70.1.2")]
    stale = [{"host": "127.0.0.1", "port": 50002, "at": 0}]
    assert sync_routes.door_routes(None, stale, lan_ok=True, tailnet_ok=True) == []


def test_udp_comes_first_and_the_tcp_fallback_only_where_a_door_holds_one():
    """Ruling 51f (owner 2026-11-03): the door is UDP; its TCP fallback is a route below it, listed only for a door
    whose ``t`` says it answers on TCP — and a door from before UDP (no ``t``) is TCP only."""
    now = __import__("time").time()
    both = {"port": 50001, "key": "k", "lan": ["192.168.1.20"], "tailnet": ["100.70.1.2"], "t": ["udp", "tcp"]}
    got = sync_routes.order(sync_routes.door_routes(both, lan_ok=True, tailnet_ok=True))
    assert [(r.kind, r.carrier) for r in got] == [("lan", "door"), ("lan", "door-tcp"), ("tailnet", "door"),
                                                  ("tailnet", "door-tcp")]
    assert all(r.is_door for r in got)
    udp = {**both, "t": ["udp"]}
    assert [r.carrier for r in sync_routes.door_routes(udp, lan_ok=True, tailnet_ok=False)] == ["door"]
    old = {k: v for k, v in both.items() if k != "t"}
    assert [r.carrier for r in sync_routes.door_routes(old, lan_ok=True, tailnet_ok=False)] == ["door-tcp"]
    assert sync_routes._clean_door({**both, "t": ["quic", 3]})["t"] == ["tcp"]          # noqa: SLF001
    found = [{"host": "127.0.0.1", "port": 50002, "at": now},                            # found before UDP: TCP
             {"host": "127.0.0.1", "port": 50003, "carrier": "door", "at": now}]
    assert [(r.port, r.carrier) for r in sync_routes.order(sync_routes.door_routes(None, found, lan_ok=True,
                                                                                   tailnet_ok=False))] == [
        (50003, "door"), (50002, "door-tcp")]


def test_lan_dialing_follows_the_setting(monkeypatch):
    assert sync_routes.may_dial_lan({"CICADA_SYNC_LAN_DIAL": "on"}) is True
    assert sync_routes.may_dial_lan({"CICADA_SYNC_LAN_DIAL": "off"}) is False


def test_learned_routes_keep_only_private_addresses_in_a_private_file(ledger, tmp_path):
    sync_routes.learn("dev1", {"port": 50001, "key": "k" * 43, "lan": ["192.168.1.20", "203.0.113.9"],
                               "tailnet": ["100.70.1.2", "8.8.8.8"], "extra": "dropped"})
    sync_routes.learn("dev2", {"port": 0})
    path = tmp_path / "cicada" / "sync" / "routes.json"
    data = json.loads(path.read_text())
    assert data["learned"]["dev1"]["lan"] == ["192.168.1.20"] and data["learned"]["dev1"]["tailnet"] == ["100.70.1.2"]
    assert "extra" not in data["learned"]["dev1"] and "dev2" not in data["learned"]
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
