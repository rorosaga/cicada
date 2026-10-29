"""G132 phase 2, end to end: moving the home between three real backends on three loopback ports.

ALPHA holds the memory and publishes it; BRAVO and CHARLIE keep copies (``replica_of`` + the device token ALPHA
issued). Shown, synthetic data and placeholder names only, nothing leaves loopback:

* **the move** — ALPHA → BRAVO: ALPHA closes to writes, commits the signed record as its last commit, BRAVO promotes
  itself, ALPHA follows BRAVO; CHARLIE, which was off with a transaction waiting, finds the new home by itself and the
  transaction lands there (it carried the bank's id, not an address); every history only fast-forwarded;
* **a crash on each side mid-hand-off** — the target killed right after the move started, then the old home killed
  while it waits: both come back and finish the one hand-off, and only one of them ever admits;
* **a take-over with the lag shown** — the home is lost, CHARLIE (which missed a commit) takes over on the person's OK,
  BRAVO finds it and sets aside the commit CHARLIE never received;
* **the old home comes back** — it sees the newer record, stops ordering, follows CHARLIE, sets aside what it made after
  the take-over point (never merged), and offers it back as transactions: the calls it admitted and the episodes —
  each applied once, and counted in words.
"""
from __future__ import annotations

import json
import signal
import subprocess
import time
from pathlib import Path

import pytest

from _synthetic_bank import _entity
from test_replica_two_machines import Machine, _git, _wait


def _machine(root: Path, name: str, **extra) -> Machine:
    m = Machine(root, name, CICADA_SYNC_PEER_AFTER_S="2", **extra)
    m.extra["CICADA_DEVICE_URL"] = m.url
    return m


def _publish(m: Machine) -> None:
    (m.cicada_home / "sync").mkdir(parents=True, exist_ok=True)
    (m.cicada_home / "sync" / "settings.json").write_text(json.dumps({"publish": True}))


def _follow(m: Machine, home: Machine, token: str) -> None:
    (m.cicada_home / "device_token").write_text(token + "\n")
    (m.cicada_home / "replica_of").write_text(home.url + "\n")


def _home(m: Machine) -> dict:
    return m.call("GET", "/sync/home")[1] or {}


def _head(m: Machine) -> str:
    return _git(m.bank, "rev-parse", "HEAD").strip()


def _record(m: Machine) -> dict:
    return json.loads((m.bank / "_home.json").read_text())


def _role(m: Machine) -> str | None:
    try:
        return _home(m).get("role")
    except Exception:  # noqa: BLE001 — restarting
        return None


def _following(m: Machine, home: Machine) -> bool:
    try:
        body = m.call("GET", "/sync/replica")[1] or {}
    except Exception:  # noqa: BLE001
        return False
    r = body.get("replica") or {}
    if body.get("mode") != "replica" or r.get("status") != "following":
        return False
    try:
        return _head(m) == _head(home)
    except Exception:  # noqa: BLE001
        return False


def _tool(m: Machine, tool: str, **arguments) -> dict:
    status, body = m.call("POST", "/tools/call", {"tool": tool, "arguments": arguments,
                                                  "caller": {"harness": "claude-code"}}, timeout=60)
    assert status == 200 and not body.get("error") and body.get("code") in (None, "queued_for_home"), (status, body)
    return body


def _device_id(token: str) -> str:
    return token.split("_")[2]


@pytest.fixture
def trio(tmp_path):
    alpha, bravo, charlie = (_machine(tmp_path, n) for n in ("alpha", "bravo", "charlie"))
    machines = (alpha, bravo, charlie)
    try:
        _publish(alpha)
        (alpha.memory / "entities").mkdir(parents=True, exist_ok=True)
        _entity(alpha.memory, "alpha-project", type="project", confidence=0.9)
        alpha.start()
        tokens = {}
        for m, name in ((bravo, "bravo-laptop"), (charlie, "charlie-desk")):
            status, made = alpha.call("POST", "/devices", {"name": name})
            assert status in (200, 201), made
            tokens[m] = made["token"]
            _follow(m, alpha, made["token"])
            m.start()
        for m in (bravo, charlie):
            assert _wait(lambda m=m: _following(m, alpha), 60), m.log.read_text()[-3000:]
        # Each copy has told the home where it is reached (its address, its signing key, how far it is).
        assert _wait(lambda: sum(1 for d in _home(alpha).get("devices", []) if d.get("canBeHome")) == 2, 30), \
            json.dumps(_home(alpha)) + bravo.log.read_text()[-3000:]
        # One commit, so each copy catches up once more and takes the registry with both of them in it.
        _tool(alpha, "cicada_add_backlog_item", project="alpha-project", title="Setup example item",
              description="placeholder")
        for m, other in ((bravo, charlie), (charlie, bravo)):
            other_id = _device_id(tokens[other])
            assert _wait(lambda m=m, o=other_id: any(d["id"] == o and d.get("canBeHome")
                                                      for d in _home(m).get("devices", [])), 30), _home(m)
        yield alpha, bravo, charlie, tokens
    finally:
        for m in machines:
            m.stop()


def _kill(m: Machine) -> None:
    if m.proc is not None:
        m.proc.send_signal(signal.SIGKILL)
        m.proc.wait(timeout=10)
        m.proc = None


def test_the_home_moves_and_every_device_follows(trio):
    alpha, bravo, charlie, tokens = trio
    bravo_id, charlie_id = _device_id(tokens[bravo]), _device_id(tokens[charlie])
    before = _head(alpha)

    # The Sleep page on ALPHA names ALPHA as the device that consolidates, and every other device with its lag.
    page = _home(alpha)
    assert page["shared"] and page["role"] == "home" and page["home"]["me"] and page["term"] == 0
    assert {d["id"] for d in page["devices"]} == {bravo_id, charlie_id}
    assert all(d["behind"] is not None and d["online"] for d in page["devices"]), page

    # CHARLIE is off, with a write waiting in its outbox for "the home" — the bank's id, never an address.
    charlie.stop()
    from api.services import tx_outbox

    bank_id = page["bankId"]
    entry = tx_outbox.tool_entry("cicada_save_episode", {"content": "decided the echo-example venue",
                                                         "title": "Echo"},
                                 bank_id=bank_id, base_seq=0, caller={"harness": "claude-code"}, surface="mcp",
                                 options={})
    assert tx_outbox.keep(entry, home=charlie.cicada_home)

    # The move, pressed on ALPHA's Sleep page.
    started = time.monotonic()
    status, body = alpha.call("POST", "/sync/home/move", {"device": bravo_id})
    assert status == 202, body
    assert _wait(lambda: _role(bravo) == "home", 60), bravo.log.read_text()[-3000:]
    took = time.monotonic() - started
    assert _wait(lambda: _following(alpha, bravo), 60), alpha.log.read_text()[-3000:]

    # The record is the old home's last commit, signed by it, naming BRAVO; every history only grew.
    rec = _record(bravo)
    assert rec["term"] == 1 and rec["kind"] == "move" and rec["to"]["device"] == bravo_id and rec["sig"]
    record_commit = _git(bravo.bank, "log", "-1", "--format=%H", "--", "_home.json").strip()
    assert _git(bravo.bank, "merge-base", "--is-ancestor", before, record_commit) == ""
    assert "trigger: sync/handoff" in _git(bravo.bank, "log", "-1", "--format=%B", record_commit)
    # The copy never commits: its head is always in the new home's history. The new home may commit in between (its
    # primer, refreshed and committed alone when a copy reads its status — review of #569's flake): the copy then
    # catches up to it.
    copy_head, home_head = _head(alpha), _head(bravo)
    between = _git(bravo.bank, "log", "--format=%s", f"{copy_head}..{home_head}")
    ancestor = subprocess.run(["git", "merge-base", "--is-ancestor", copy_head, home_head], cwd=str(bravo.bank))
    assert ancestor.returncode == 0, between                               # the copy made no commit of its own
    assert _wait(lambda: _head(alpha) == _head(bravo), 30), between
    assert _git(alpha.bank, "status", "--porcelain", "--untracked-files=no") == ""
    assert (alpha.cicada_home / "replica_of").read_text().strip() == bravo.url
    assert not (bravo.cicada_home / "replica_of").exists()
    assert _home(bravo)["home"]["me"] and _home(alpha)["role"] == "replica"

    # A write on ALPHA, now a copy, is the new home's; BRAVO accepts ALPHA's and CHARLIE's tokens (the registry moved).
    _tool(alpha, "cicada_save_episode", content="decided the foxtrot-example date", title="Foxtrot")
    assert _wait(lambda: any("foxtrot-example date" in p.read_text() for p in bravo.episodes()), 30)

    # CHARLIE comes back pointed at ALPHA: it finds the new home by itself, and its waiting write lands there once.
    charlie.start()
    assert _wait(lambda: (charlie.cicada_home / "replica_of").read_text().strip() == bravo.url, 60), \
        charlie.log.read_text()[-3000:]
    assert _wait(lambda: _following(charlie, bravo), 60)
    assert _wait(lambda: sum("echo-example venue" in p.read_text() for p in bravo.episodes()) == 1, 30)
    assert _wait(lambda: not tx_outbox.entries(home=charlie.cicada_home), 30)
    print(f"\nhand-off took {took:.2f} s (request to the new home admitting)")


def test_a_crash_on_either_side_mid_hand_off_finishes_one_hand_off(trio):
    alpha, bravo, charlie, tokens = trio
    bravo_id = _device_id(tokens[bravo])
    status, body = alpha.call("POST", "/sync/home/move", {"device": bravo_id})
    assert status == 202, body
    _kill(bravo)                                       # the target dies as the move starts
    # ALPHA commits the record and waits for BRAVO; it admits nothing meanwhile.
    assert _wait(lambda: _home(alpha).get("role") == "left", 30), alpha.log.read_text()[-3000:]
    status, refused = alpha.call("POST", "/sources/save", {"url": "https://example.com/a"})
    assert status == 503 and refused["code"] == "home_moving", refused
    _kill(alpha)                                       # and then the old home dies while it waits
    alpha.start()
    assert _home(alpha).get("role") == "left"          # it comes back closed: the record names BRAVO
    bravo.start()
    assert _wait(lambda: _role(bravo) == "home", 60), bravo.log.read_text()[-3000:]
    assert _wait(lambda: _following(alpha, bravo), 60), alpha.log.read_text()[-3000:]
    assert _wait(lambda: _following(charlie, bravo), 60), charlie.log.read_text()[-3000:]
    assert _record(bravo)["term"] == 1


def test_take_over_a_lost_home_and_the_old_home_comes_back(trio):
    alpha, bravo, charlie, tokens = trio
    charlie_id = _device_id(tokens[charlie])
    charlie.stop()                                     # CHARLIE misses what follows
    item = _tool(alpha, "cicada_add_backlog_item", project="alpha-project", title="Golf example item",
                 description="placeholder")
    assert not item.get("error"), item
    assert _wait(lambda: _following(bravo, alpha), 30)
    fork = _head(alpha)
    # A note saved on ALPHA itself stays uncommitted until Sleep (G135's rule) — then ALPHA is lost.
    _tool(alpha, "cicada_save_episode", content="decided the hotel-example budget", title="Hotel")
    alpha.stop()
    charlie.start()

    # Before the person confirms, CHARLIE says how far behind the last home it saw it is.
    preview = charlie.call("GET", "/sync/home/take-over")[1]
    assert preview["possible"] and isinstance(preview["behind"], int), preview
    assert "behind the last home it saw" in preview["text"]
    status, body = charlie.call("POST", "/sync/home/take-over", {"behind": preview["behind"] + 5, "confirm": True})
    assert status == 409 and body["code"] == "changed"
    status, body = charlie.call("POST", "/sync/home/take-over", {"behind": preview["behind"], "confirm": True})
    assert status == 200 and body["took"], body
    assert _wait(lambda: _role(charlie) == "home", 60), charlie.log.read_text()[-3000:]
    rec = _record(charlie)
    assert rec["kind"] == "take-over" and rec["term"] == 1 and rec["to"]["device"] == charlie_id

    # BRAVO, following the lost home, finds CHARLIE; the commit CHARLIE never received is set aside, never merged.
    assert _wait(lambda: _following(bravo, charlie), 90), bravo.log.read_text()[-4000:]
    aside = _home(bravo)["setAside"]
    assert aside["commits"] == 1 and "kept aside here, never merged" in aside["text"], aside
    assert _git(bravo.bank, "rev-parse", aside["ref"]).strip() == fork

    # The old home comes back, with that note still uncommitted.
    alpha.start()
    assert _wait(lambda: _following(alpha, charlie), 90), alpha.log.read_text()[-4000:]
    aside = _home(alpha)["setAside"]
    assert aside["wasHome"] and aside["commits"] >= 1 and aside["calls"] >= 1, aside
    assert "kept aside here, never merged" in aside["text"] and "were sent to" in aside["text"]
    assert _git(alpha.bank, "merge-base", "--is-ancestor", fork, aside["ref"]) == ""
    # What it admitted after the take-over point is offered back and applied once at the new home.
    assert _wait(lambda: any("Golf example item" in p.read_text()
                             for p in (charlie.bank / "backlog").rglob("*.md")), 60)
    assert sum("Golf example item" in p.read_text() for p in (charlie.bank / "backlog").rglob("*.md")) == 1
    # The note arrives twice — as the call that saved it and as the episode — and is written once.
    assert _wait(lambda: sum("hotel-example budget" in p.read_text() for p in charlie.episodes()) == 1, 60)
    time.sleep(2)
    assert sum("hotel-example budget" in p.read_text() for p in charlie.episodes()) == 1
    assert _wait(lambda: _head(alpha) == _head(charlie), 30)
