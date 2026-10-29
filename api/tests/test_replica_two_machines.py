"""G132 phase 1 B, end to end: a home and a computer that keeps a copy, two real backends on two loopback ports.

The HOME publishes its log (ruling 51a/d/e). The REPLICA (``CICADA_REPLICA_OF`` = the home, a device token the home
issued) copies the bank, follows it, answers reads from its copy, and sends its writes to the home. Shown: the first
copy lands as its own bank under the home's id and every other bank on that computer is left as it was; a save made
on the replica lands at the home and the replica reads it back; the queue, the inbox and the Sleep frame are the
home's at the same seq; "Sleep now" pressed on the replica is the home's; with the home down, recall still answers
from the copy and a write queues, and it lands once the home is back; a revoked device stops at once. Synthetic data
and placeholder names only; nothing leaves loopback.
"""
from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from test_headless_two_machines import PY, REPO, Backend, Mcp, _base_env


class Machine(Backend):
    def __init__(self, root: Path, name: str, **extra):
        super().__init__(root, name)
        self.extra = extra

    @property
    def env(self) -> dict:
        return {**super().env, **self.extra}

    @property
    def token(self) -> str:
        return (self.cicada_home / "api_token").read_text().strip()

    def call(self, method: str, path: str, body=None, token: str | None = None, timeout: float = 15):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"{self.url}{path}", data=data, method=method, headers={
            "Authorization": f"Bearer {token or self.token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                return resp.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                return exc.code, json.loads(raw) if raw else None
            except ValueError:
                return exc.code, None


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True).stdout


def _wait(predicate, timeout: float = 30.0, every: float = 0.2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        got = predicate()
        if got:
            return got
        time.sleep(every)
    return predicate()


def _other_bank(root: Path) -> Path:
    """A bank this computer already had, before it kept a copy: it must stay as it was, and inactive."""
    bank = root / "banks" / "notes-here"
    (bank / "entities").mkdir(parents=True)
    (bank / "entities" / "gamma-example.md").write_text("---\nname: Gamma Example\ntype: concept\n---\nhere\n")
    for args in (["init", "-q"], ["config", "user.email", "t@example.com"], ["config", "user.name", "t"],
                 ["add", "."], ["commit", "-q", "-m", "seed"]):
        _git(bank, *args)
    (root / "banks.yaml").write_text("active: notes-here\nbanks:\n  notes-here:\n    legacy: false\n"
                                     "    id: 0123456789abcdef0123456789abcdef\n")
    return bank


@pytest.fixture
def pair(tmp_path):
    home = Machine(tmp_path, "home", CICADA_SYNC_PUBLISH="on")
    replica = Machine(tmp_path, "replica")
    try:
        home.start()
        status, made = home.call("POST", "/devices", {"name": "laptop"})
        assert status in (200, 201), made
        replica.extra = {"CICADA_REPLICA_OF": home.url}
        (replica.cicada_home / "device_token").write_text(made["token"] + "\n")
        other = _other_bank(replica.memory)
        other_head = _git(other, "rev-parse", "HEAD").strip()
        replica.start()
        yield home, replica, made, other, other_head
    finally:
        replica.stop()
        home.stop()


def _home_head(home: Machine) -> int:
    return home.call("GET", "/sync/log?since=0&limit=1")[1]["head"]["seq"]


def _caught_up(home: Machine, replica: Machine):
    def ok():
        _s, body = replica.call("GET", "/sync/replica")
        r = (body or {}).get("replica") or {}
        return r if r.get("status") == "following" and r.get("seq") == _home_head(home) else None

    return _wait(ok, 60)


def _mcp_env(replica: Machine) -> dict:
    return {**_base_env(replica.home, replica.cicada_home), "CICADA_PORT": str(replica.port),
            "CICADA_REPLICA_OF": replica.extra["CICADA_REPLICA_OF"], "CICADA_MEMORY_PATH": str(replica.memory)}


def test_a_computer_keeps_a_copy_reads_it_and_writes_through_the_home(pair):
    home, replica, made, other, other_head = pair
    state = _caught_up(home, replica)
    assert state, replica.log.read_text()[-3000:]

    # The first copy: its own bank, under the home's id; the bank this computer had is untouched and inactive.
    registry = (replica.memory / "banks.yaml").read_text()
    home_id = home.call("GET", "/sync/status")[1]["bankId"]
    assert home_id in registry and "replica: true" in registry and "active: notes-here" not in registry
    assert _git(other, "rev-parse", "HEAD").strip() == other_head and not _git(other, "status", "--porcelain")
    copy = replica.bank
    assert copy != other and _git(copy, "rev-parse", "HEAD").strip() == _git(home.bank, "rev-parse", "HEAD").strip()

    # A save on the replica lands at the home, once, and the replica reads it back (read-your-writes).
    mcp = Mcp(_mcp_env(replica))
    try:
        mcp.ask("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                               "clientInfo": {"name": "claude-code", "version": "1"}})
        text, is_error = mcp.tool("cicada_save_episode", content="decided the alpha-project launch plan",
                                  title="Alpha plan")
        assert not is_error and "Episode saved as ep_" in text, text
        ep = text.split("Episode saved as ", 1)[1].split(".", 1)[0]
        assert (home.bank / "episodes" / f"{ep}.md").exists()
        assert (copy / "episodes" / f"{ep}.md").exists()
        assert _git(copy, "status", "--porcelain") == ""          # the copy never commits or dirties itself

        # The queue, the inbox and the Sleep frame are the home's at the same seq.
        _caught_up(home, replica)
        h, r = home.call("GET", "/sync/status")[1], replica.call("GET", "/sync/status")[1]
        assert r["seq"] == h["seq"] and r["queue"] == h["queue"] and ep in r["queue"]["waiting"]
        assert set(r["sleep"]) >= {"status", "unprocessedCount", "writing"} and "outbox" in r
        assert replica.call("GET", "/inbox")[1] == home.call("GET", "/inbox")[1]

        # "Sleep now" on the replica is the home's (never refused as a copy's, never run here).
        status, body = replica.call("POST", "/sleep/trigger", {})
        assert not (status == 409 and (body or {}).get("code") == "replica_read_only"), body
        # A bank lifecycle act is refused on a copy.
        status, body = replica.call("POST", "/banks", {"name": "another"})
        assert status == 409 and body["code"] == "replica_read_only"

        # The home goes away: recall still answers from the copy, and a write queues for the home.
        home.stop()
        text, is_error = mcp.tool("cicada_recall", query="alpha-project launch plan")
        assert not is_error and ep in text, text
        text, is_error = mcp.tool("cicada_save_episode", content="decided the beta-example budget", title="Beta")
        assert not is_error and "Queued for the home" in text, text
        assert replica.call("GET", "/sync/replica")[1]["outbox"]["waiting"] == 1
        # It lands once the home is back (the follower flushes what waits, in order).
        home.start()
        assert _wait(lambda: any("beta-example budget" in p.read_text() for p in home.episodes()), 60)
        assert _wait(lambda: replica.call("GET", "/sync/replica")[1]["outbox"]["waiting"] == 0, 30)

        # A revoked device stops at once: its next request is refused and it says so.
        device_id = made["token"].split("_")[2]
        assert home.call("DELETE", f"/devices/{device_id}")[0] == 200
        mcp.tool("cicada_save_episode", content="decided the gamma-example timing", title="Gamma")
        assert _wait(lambda: replica.call("GET", "/sync/replica")[1]["replica"]["status"] == "revoked", 30)
        assert not any("gamma-example timing" in p.read_text() for p in home.episodes())
    finally:
        mcp.proc.terminate()
        mcp.proc.wait(timeout=10)


def test_the_person_keeps_a_copy_with_a_pairing_code_and_a_restart(tmp_path):
    """The app's path: on the home, "Pair a device" (a computer's code); on the other computer, the home's address and
    that code (`PUT /sync/replica`), then a restart of its own backend — which comes back as a replica and copies."""
    home = Machine(tmp_path, "home", CICADA_SYNC_PUBLISH="on")
    home.start()
    other = Machine(tmp_path, "other")
    other.start()
    try:
        status, pairing = home.call("POST", "/devices/pairing", {"kind": "full", "url": home.url})
        assert status == 201, pairing
        assert other.call("GET", "/sync/replica")[1]["mode"] == "local"
        status, body = other.call("PUT", "/sync/replica", {"home": home.url, "code": "not-the-code"})
        assert status == 400                                             # nothing written on a wrong code
        assert not (other.cicada_home / "replica_of").exists()
        status, body = other.call("PUT", "/sync/replica", {"home": home.url, "code": pairing["code"]})
        assert status == 200 and body["restart"] is True, body
        token = (other.cicada_home / "device_token").read_text().strip()
        assert token.startswith("cic_dev_") and oct((other.cicada_home / "replica_of").stat().st_mode & 0o777) == "0o600"
        assert other.call("POST", "/sync/replica/restart")[1] == {"restarting": True}

        def following():
            try:
                body = other.call("GET", "/sync/replica", timeout=2)[1] or {}
            except Exception:  # noqa: BLE001 — the backend is coming back up
                return None
            return body if (body.get("replica") or {}).get("status") == "following" else None

        state = _wait(following, 60)
        assert state and state["mode"] == "replica", other.log.read_text()[-2000:]
        assert other.call("POST", "/banks", {"name": "x"})[1]["code"] == "replica_read_only"
    finally:
        other.stop()
        home.stop()
