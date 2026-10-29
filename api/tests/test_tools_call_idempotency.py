"""G132 phase 1 — idempotent writes over the tool door (ruling 51a): a mutating call with an `Idempotency-Key` is applied
once and a resend replays the first answer; the key is scoped by device and bank id and lives 8 days (other routes keep
a day); a refusal or an error runs again; the reply carries the home's `seq` once the write committed; `base_seq` is
recorded, never enforced. Synthetic banks only."""
from __future__ import annotations

import sqlite3

from _sync_home import auth, device_token, home  # noqa: F401 — the fixture
from api.services import idempotency, sync_log, sync_publish, tool_door

SAVE = {"tool": "cicada_save_episode", "arguments": {"content": "decided to ship alpha", "title": "Ship"},
        "caller": {"harness": "claude-code", "session_id": "11111111-2222-4333-8444-555555555555"}}


def _episodes(bank):
    return sorted(p.name for p in (bank / "episodes").glob("ep_*.md"))


def test_a_resend_replays_the_first_answer_and_writes_once(home):  # noqa: F811
    client, master, bank = home
    token = device_token(client, master)
    before = _episodes(bank)
    headers = {**auth(token), "Idempotency-Key": "outbox-0001"}
    first = client.post("/tools/call", json={**SAVE, "base_seq": 1}, headers=headers)
    assert first.status_code == 200 and first.json()["error"] is None, first.text
    written = _episodes(bank)
    assert len(written) == len(before) + 1
    again = client.post("/tools/call", json={**SAVE, "base_seq": 1}, headers=headers)
    assert again.json() == first.json() and _episodes(bank) == written
    # The reply names the home's head once the write committed.
    assert isinstance(first.json()["seq"], int) and first.json()["seq"] <= sync_log.update(bank).seq
    # base_seq is recorded beside the seq it landed on, never enforced.
    db = sqlite3.connect(sync_publish.bank_dir(bank) / sync_log.DB_FILE)
    assert db.execute("SELECT base_seq, head_seq FROM bases").fetchone() == (1, first.json()["seq"])
    # Without a key the call runs as before (here the tool's own dedup of the same words answers it).
    plain = client.post("/tools/call", json=SAVE, headers=auth(token))
    assert plain.status_code == 200 and plain.json()["error"] is None


def test_the_scope_is_the_device_and_the_bank(home):  # noqa: F811
    client, master, bank = home
    a = device_token(client, master, "laptop")
    b = device_token(client, master, "desktop")
    start = len(_episodes(bank))
    for i, token in enumerate((a, b)):
        body = {**SAVE, "arguments": {**SAVE["arguments"], "content": f"decided to ship alpha, take {i}"}}
        r = client.post("/tools/call", json=body, headers={**auth(token), "Idempotency-Key": "same-key"})
        assert r.status_code == 200
    assert len(_episodes(bank)) == start + 2          # one key, two devices: two writes
    db = sqlite3.connect(idempotency._path())          # noqa: SLF001
    scopes = [row[0] for row in db.execute("SELECT scope FROM keys WHERE route='/tools/call:cicada_save_episode'")]
    assert len(scopes) == 2 and all("|bank:" in s and not s.endswith("|bank:-") for s in scopes)


def test_a_refused_call_runs_again(home, monkeypatch):  # noqa: F811
    client, master, _bank = home
    real = tool_door.run
    calls = []

    def flaky(tool, arguments, **kw):
        calls.append(tool)
        if len(calls) == 1:
            return tool_door.Answer(text="Sleep holds the pages; try again in a moment.", code="sleep_writing")
        if len(calls) == 2:
            return tool_door.Answer(text="", error="that didn't work (OSError).")
        return real(tool, arguments, **kw)

    monkeypatch.setattr(tool_door, "run", flaky)
    headers = {**auth(master), "Idempotency-Key": "retry-me"}
    assert client.post("/tools/call", json=SAVE, headers=headers).json()["code"] == "sleep_writing"
    assert client.post("/tools/call", json=SAVE, headers=headers).json()["error"]
    done = client.post("/tools/call", json=SAVE, headers=headers).json()
    assert done["error"] is None and done["code"] is None
    assert client.post("/tools/call", json=SAVE, headers=headers).json() == done and len(calls) == 3


def test_a_read_is_never_keyed(home):  # noqa: F811
    client, master, _bank = home
    r = client.post("/tools/call", json={"tool": "cicada_pending", "arguments": {}},
                    headers={**auth(master), "Idempotency-Key": "read-key"})
    assert r.status_code == 200 and "seq" not in r.json()
    with idempotency._db() as db:                      # noqa: SLF001
        assert db.execute("SELECT count(*) FROM keys WHERE route LIKE '/tools/call:%'").fetchone() == (0,)


def test_tool_and_capture_keys_live_eight_days_and_other_routes_a_day(tmp_path, monkeypatch):
    import asyncio

    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    day = 24 * 3600

    async def ok():
        return 200, {"ok": True}

    async def seed(route, at):
        await idempotency.run_once("device:x|bank:y", route, "k", ok, now=lambda: at)

    asyncio.run(seed("/tools/call:cicada_save_episode", 0))
    asyncio.run(seed("/capture/note", 0))
    asyncio.run(seed("/elsewhere", 0))
    seen = []

    async def again():
        seen.append(1)
        return 200, {"ok": True}

    # Two days later a short route's key is gone; the tool's and the capture's are not (review of #566).
    asyncio.run(idempotency.run_once("device:x|bank:y", "/elsewhere", "k", again, now=lambda: 2 * day))
    assert seen == [1]
    _, _, replayed = asyncio.run(idempotency.run_once(
        "device:x|bank:y", "/tools/call:cicada_save_episode", "k", again, now=lambda: 2 * day))
    assert replayed and seen == [1]
    _, _, replayed = asyncio.run(idempotency.run_once("device:x|bank:y", "/capture/note", "k", again,
                                                      now=lambda: 2 * day))
    assert replayed and seen == [1]
    _, _, replayed = asyncio.run(idempotency.run_once(
        "device:x|bank:y", "/tools/call:cicada_save_episode", "k", again, now=lambda: 8 * day + 1))
    assert not replayed
    assert idempotency.ttl_for("/tools/call:x") == 8 * day and idempotency.ttl_for("/sources/save") == 8 * day \
        and idempotency.ttl_for("/elsewhere") == day
