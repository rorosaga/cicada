"""G132 phase 3b, end to end: one transport, direct first, the relay as fallback — three real backends and a relay, all
on loopback.

ALPHA holds the memory and publishes it; BRAVO and CHARLIE keep copies. Each copy reaches ALPHA **directly** through a
small TCP forwarder the test can cut (``Wire``: up, down, or "forward the request, then drop the answer"), and through
a relay running in this process (``cicada_relay``, a SQLite mailbox on a temporary file). Shown, with synthetic data
and placeholder names only:

* **direct** — while the wire is up, every catch-up and write goes direct, and the relay carries nothing but its
  pushes;
* **relay only** — the wire cut, a home commit reaches the copy as a pushed delta, and a write made on the copy lands
  at the home once, carried by the relay;
* **direct dies mid-stream** — the wire forwards a write and drops the answer: the same write (same key) goes over the
  relay and is applied once;
* **the home asleep** — CHARLIE off, ALPHA commits and then stops; CHARLIE starts with no direct path and catches up
  from the relay's mailbox alone;
* **a move over the relay** — no device has a direct address: ALPHA hands the home to BRAVO, the relay group follows
  (``Home.hand_off`` and the group record), ALPHA and CHARLIE follow BRAVO over the relay;
* **revoke** — the device leaves the group: a new epoch, the relay closes its socket.
"""
from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from pathlib import Path

import pytest

from _relay import Config, Relay
from _synthetic_bank import _entity
from test_replica_two_machines import Machine, _git, _wait


class RelayThread:
    """The relay on its own loop in a thread, on a free loopback port."""

    def __init__(self, db: Path):
        self.db = db
        self.loop = asyncio.new_event_loop()
        self.relay = None
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        assert self.ready.wait(10)

    def _run(self):
        asyncio.set_event_loop(self.loop)

        async def main():
            self.relay = await Relay(Config(host="127.0.0.1", port=0, db_path=str(self.db),
                                            purge_interval_s=3600)).start()
            self.ready.set()

        self.loop.run_until_complete(main())
        self.loop.run_forever()

    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self.relay.port}"

    def stop(self):
        fut = asyncio.run_coroutine_threadsafe(self.relay.stop(), self.loop)
        fut.result(10)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(10)


class Wire:
    """A TCP forwarder: ``up`` forwards both ways; ``down`` refuses every connection; ``cut_answers`` forwards the
    request to the home and drops its answer (the request may have landed: the client must not apply it twice)."""

    def __init__(self, target_port: int):
        self.target = target_port
        self.mode = "up"
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(64)
        self.port = self.sock.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.live: list[socket.socket] = []
        self.stopped = False
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while not self.stopped:
            try:
                client, _ = self.sock.accept()
            except OSError:
                return
            if self.mode == "down":
                client.close()
                continue
            try:
                upstream = socket.create_connection(("127.0.0.1", self.target), timeout=5)
            except OSError:
                client.close()
                continue
            self.live += [client, upstream]
            mode = self.mode
            threading.Thread(target=self._pipe, args=(client, upstream, False), daemon=True).start()
            threading.Thread(target=self._pipe, args=(upstream, client, mode == "cut_answers"), daemon=True).start()

    def _pipe(self, src, dst, drop):
        try:
            while True:
                data = src.recv(65536)
                if not data:
                    break
                if drop:
                    continue
                dst.sendall(data)
        except OSError:
            pass
        finally:
            for s in (src, dst):
                try:
                    s.close()
                except OSError:
                    pass

    def down(self):
        self.mode = "down"
        for s in self.live:
            try:
                s.close()
            except OSError:
                pass
        self.live.clear()

    def up(self):
        self.mode = "up"

    def stop(self):
        self.stopped = True
        self.down()
        self.sock.close()


def _publish(m: Machine) -> None:
    (m.cicada_home / "sync").mkdir(parents=True, exist_ok=True)
    (m.cicada_home / "sync" / "settings.json").write_text(json.dumps({"publish": True}))


def _follow(m: Machine, base: str, token: str) -> None:
    (m.cicada_home / "device_token").write_text(token + "\n")
    (m.cicada_home / "replica_of").write_text(base + "\n")


def _head(m: Machine) -> str:
    return _git(m.bank, "rev-parse", "HEAD").strip()


def _transport(m: Machine) -> dict:
    try:
        return m.call("GET", "/sync/transport")[1] or {}
    except Exception:  # noqa: BLE001 — restarting
        return {}


def _relay_ready(m: Machine, members: int | None = None) -> bool:
    r = (_transport(m).get("relay") or {})
    return bool(r.get("running") and r.get("connected") and (members is None or r.get("members") == members))


def _following(m: Machine, home: Machine) -> bool:
    try:
        body = m.call("GET", "/sync/replica")[1] or {}
        return body.get("mode") == "replica" and _head(m) == _head(home)
    except Exception:  # noqa: BLE001
        return False


def _tool(m: Machine, tool: str, **arguments) -> dict:
    status, body = m.call("POST", "/tools/call", {"tool": tool, "arguments": arguments,
                                                  "caller": {"harness": "claude-code"}}, timeout=90)
    assert status == 200 and not body.get("error"), (status, body)
    return body


def _items(m: Machine, title: str) -> int:
    folder = m.bank / "backlog"
    return sum(1 for p in folder.rglob("*.md") if title in p.read_text()) if folder.exists() else 0


@pytest.fixture
def trio(tmp_path):
    relay = RelayThread(tmp_path / "relay.db")
    alpha = Machine(tmp_path, "alpha", CICADA_SYNC_RELAY=relay.url, CICADA_SYNC_PEER_AFTER_S="2")
    bravo = Machine(tmp_path, "bravo", CICADA_SYNC_RELAY=relay.url, CICADA_SYNC_PEER_AFTER_S="2")
    charlie = Machine(tmp_path, "charlie", CICADA_SYNC_RELAY=relay.url, CICADA_SYNC_PEER_AFTER_S="2")
    machines = (alpha, bravo, charlie)
    wires = {}
    try:
        _publish(alpha)
        (alpha.memory / "entities").mkdir(parents=True, exist_ok=True)
        _entity(alpha.memory, "alpha-project", type="project", confidence=0.9)
        alpha.start()
        assert _wait(lambda: _relay_ready(alpha), 30), alpha.log.read_text()[-3000:]
        tokens = {}
        for m, name in ((bravo, "bravo-laptop"), (charlie, "charlie-desk")):
            status, made = alpha.call("POST", "/devices", {"name": name})
            assert status in (200, 201), made
            tokens[m] = made["token"]
            wires[m] = Wire(alpha.port)
            _follow(m, wires[m].url, made["token"])
            m.start()
        for m in (bravo, charlie):
            assert _wait(lambda m=m: _following(m, alpha), 60), m.log.read_text()[-3000:]
            assert _wait(lambda m=m: _relay_ready(m), 30), m.log.read_text()[-3000:]
        assert _wait(lambda: _relay_ready(alpha, members=3), 30), _transport(alpha)
        yield relay, alpha, bravo, charlie, wires, tokens
    finally:
        for m in machines:
            m.stop()
        for w in wires.values():
            w.stop()
        relay.stop()


def test_direct_first_then_the_relay_then_once_across_both(trio):
    relay, alpha, bravo, charlie, wires, _tokens = trio
    # 1. Direct: a commit at the home reaches the copy; the copy's write lands; the requests went direct.
    _tool(alpha, "cicada_add_backlog_item", project="alpha-project", title="Direct example item", description="x")
    assert _wait(lambda: _following(bravo, alpha), 30)
    _tool(bravo, "cicada_add_backlog_item", project="alpha-project", title="From bravo direct", description="x")
    assert _wait(lambda: _items(alpha, "From bravo direct") == 1, 30)
    stats = _transport(bravo)
    assert stats["requests"]["direct"] > 0 and stats["last"] == "direct", stats

    # 2. Relay only: the wire is cut. A home commit arrives as a pushed delta; a write on the copy lands once.
    wires[bravo].down()
    _tool(alpha, "cicada_add_backlog_item", project="alpha-project", title="Over the relay item", description="x")
    assert _wait(lambda: _following(bravo, alpha), 60), bravo.log.read_text()[-3000:]
    _tool(bravo, "cicada_add_backlog_item", project="alpha-project", title="From bravo by relay", description="x")
    assert _wait(lambda: _items(alpha, "From bravo by relay") == 1, 60), bravo.log.read_text()[-3000:]
    assert _wait(lambda: _following(bravo, alpha), 60)
    stats = _transport(bravo)
    assert stats["requests"]["relay"] > 0 and stats["fallbacks"] >= 1, stats
    assert stats["relay"]["deltasPushed"] == 0                         # only the home pushes
    assert _transport(alpha)["relay"]["deltasPushed"] >= 1

    # 3. Direct dies mid-stream: the request is forwarded, the answer dropped. The same write (the same key) goes over
    # the relay, and the home applies it once.
    wires[bravo].mode = "cut_answers"
    _tool(bravo, "cicada_add_backlog_item", project="alpha-project", title="Cut mid stream", description="x")
    assert _wait(lambda: _items(alpha, "Cut mid stream") >= 1, 60), bravo.log.read_text()[-3000:]
    time.sleep(3)
    assert _items(alpha, "Cut mid stream") == 1
    out = bravo.call("GET", "/sync/replica")[1]["outbox"]
    assert out["waiting"] == 0 and out["rejected"] == 0, out

    # No plaintext at the relay: the synthetic titles never appear in its database.
    raw = b"".join(p.read_bytes() for p in Path(relay.db).parent.glob("relay.db*"))
    assert b"Cut mid stream" not in raw and b"From bravo by relay" not in raw and b"alpha-project" not in raw


def test_a_sleeping_home_is_caught_up_from_the_mailbox(trio):
    _relay, alpha, bravo, charlie, wires, _tokens = trio
    charlie.stop()
    for i in range(6):                                                   # more than the coalescing threshold
        _tool(alpha, "cicada_add_backlog_item", project="alpha-project", title=f"While away {i}", description="x")
    want = _head(alpha)
    assert _wait(lambda: _transport(alpha)["relay"].get("pushedHead") == want, 30), _transport(alpha)
    alpha.stop()                                                          # the home is asleep
    wires[charlie].down()                                                 # and no direct path exists
    charlie.start()
    assert _wait(lambda: _head(charlie) == want, 90), charlie.log.read_text()[-4000:]
    stats = _transport(charlie)
    assert stats["requests"]["relay"] >= 1 and stats["relay"]["waiting"] == 0, stats


def test_revoke_takes_a_device_out_of_the_group(trio):
    _relay, alpha, bravo, charlie, wires, tokens = trio
    charlie_id = tokens[charlie].split("_")[2]
    status, body = alpha.call("DELETE", f"/devices/{charlie_id}")
    assert status == 200 and "cannot take back the copy it already holds" in body["text"]
    assert _wait(lambda: (_transport(alpha).get("relay") or {}).get("members") == 2, 30), _transport(alpha)
    assert _wait(lambda: (_transport(charlie).get("relay") or {}).get("revoked") is True
                 or not (_transport(charlie).get("relay") or {}).get("running"), 30), _transport(charlie)
    wires[charlie].down()
    _tool(alpha, "cicada_add_backlog_item", project="alpha-project", title="After the revoke", description="x")
    time.sleep(4)
    assert _items(charlie, "After the revoke") == 0                       # nothing new reaches it
    assert _wait(lambda: _following(bravo, alpha), 30)                   # the others go on


@pytest.fixture
def trio_relay_only(tmp_path):
    """No device has a direct address for the others to use: every device-to-device ask is over the relay."""
    relay = RelayThread(tmp_path / "relay.db")
    names = ("alpha", "bravo", "charlie")
    machines = [Machine(tmp_path, n, CICADA_SYNC_RELAY=relay.url, CICADA_SYNC_PEER_AFTER_S="2") for n in names]
    alpha, bravo, charlie = machines
    wires = {}
    try:
        _publish(alpha)
        (alpha.memory / "entities").mkdir(parents=True, exist_ok=True)
        _entity(alpha.memory, "alpha-project", type="project", confidence=0.9)
        alpha.start()
        assert _wait(lambda: _relay_ready(alpha), 30)
        tokens = {}
        for m, name in ((bravo, "bravo-laptop"), (charlie, "charlie-desk")):
            made = alpha.call("POST", "/devices", {"name": name})[1]
            tokens[m] = made["token"]
            wires[m] = Wire(alpha.port)
            _follow(m, wires[m].url, made["token"])
            m.start()
        for m in (bravo, charlie):
            assert _wait(lambda m=m: _following(m, alpha) and _relay_ready(m), 60), m.log.read_text()[-3000:]
        _tool(alpha, "cicada_add_backlog_item", project="alpha-project", title="Setup item", description="x")
        for m in (bravo, charlie):
            assert _wait(lambda m=m: _following(m, alpha), 30)
            wires[m].down()                                              # from here: the relay only
        yield relay, alpha, bravo, charlie, wires, tokens
    finally:
        for m in machines:
            m.stop()
        for w in wires.values():
            w.stop()
        relay.stop()


def test_the_home_moves_over_the_relay(trio_relay_only):
    _relay, alpha, bravo, charlie, _wires, tokens = trio_relay_only
    bravo_id = tokens[bravo].split("_")[2]
    page = alpha.call("GET", "/sync/home")[1]
    assert any(d["id"] == bravo_id for d in page["devices"]), page
    status, body = alpha.call("POST", "/sync/home/move", {"device": bravo_id})
    assert status in (200, 202), body

    def bravo_home():
        try:
            return bravo.call("GET", "/sync/home")[1].get("role") == "home"
        except Exception:  # noqa: BLE001
            return False

    assert _wait(bravo_home, 120), bravo.log.read_text()[-5000:] + alpha.log.read_text()[-3000:]
    assert _wait(lambda: (_transport(bravo).get("relay") or {}).get("role") == "home", 60), _transport(bravo)
    # The old home follows the new one, and so does CHARLIE — all over the relay.
    _tool(bravo, "cicada_add_backlog_item", project="alpha-project", title="Made on the new home", description="x")
    for m in (alpha, charlie):
        assert _wait(lambda m=m: _items(m, "Made on the new home") == 1, 120), json.dumps(_transport(m))
    rec = json.loads((bravo.bank / "_home.json").read_text())
    assert rec["to"]["device"] == bravo_id and rec["kind"] == "move"
