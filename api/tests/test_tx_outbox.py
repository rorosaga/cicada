"""G132 phase 1 B — the transaction outbox (ruling 51a): kept on disk (0700/0600), sent oldest first and in order,
hook_spool's keep / drop / hold rules, a rejected transaction recorded (never its arguments), and an entry expires
before the home's 8-day key does. Synthetic only."""
from __future__ import annotations

import os
import stat

import pytest

from api.services import idempotency, tx_outbox


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


def _tool(name="cicada_save_episode", **kw):
    return tx_outbox.tool_entry(name, {"content": "placeholder words"}, bank_id="b" * 32, base_seq=3,
                                caller={"harness": "claude-code"}, surface="mcp", options={}, **kw)


def test_order_holds_and_entries_survive_a_restart(home):
    sent = []
    away = lambda e: (None, None)    # noqa: E731
    for i in range(3):
        verdict, _s, _b = tx_outbox.submit(_tool(key=f"k{i}"), away, home=home)
        assert verdict in ("queued", "wait")
    folder = tx_outbox.folder(home)
    assert stat.S_IMODE(os.stat(folder).st_mode) == 0o700
    assert all(stat.S_IMODE(os.stat(p).st_mode) == 0o600 for p in tx_outbox.entries(home))
    # "A restart": nothing in memory, only the folder; the home is back.
    decided = tx_outbox.flush(lambda e: (sent.append(e["id"]) or 200, {"text": "ok"}), home=home)
    assert sent == ["k0", "k1", "k2"] and all(v[0] == "landed" for v in decided.values())
    assert tx_outbox.entries(home) == []


def test_keep_drop_hold_and_rejected(home):
    answers = {"wait": (503, {}), "drop": (422, {"detail": "bad"}), "hold": (409, {"code": "bank_mismatch"}),
               "rejected": (409, {"code": "already_resolved"}), "sleep": (409, {"code": "sleep_writing"}),
               "tool-sleep": (200, {"code": "sleep_writing", "text": "later"}), "revoked": (401, {})}
    for name, (status, body) in answers.items():
        assert tx_outbox.verdict(_tool(), status, body) == {
            "wait": "wait", "drop": "drop", "hold": "hold", "rejected": "rejected", "sleep": "wait",
            "tool-sleep": "wait", "revoked": "wait"}[name]
    # A wait stops the flush so order holds; a hold steps aside; a rejection leaves with its reason, no arguments.
    for k in ("a", "b", "c"):
        tx_outbox.submit(_tool(key=k), lambda e: (None, None), home=home)
    plan = {"a": (409, {"code": "bank_mismatch"}), "b": (409, {"code": "already_resolved"}), "c": (503, {})}
    decided = tx_outbox.flush(lambda e: plan[e["id"]], home=home)
    assert [decided[k][0] for k in ("a", "b", "c")] == ["hold", "rejected", "wait"]
    left = [p.name for p in tx_outbox.entries(home)]
    assert len(left) == 2
    rows = tx_outbox.rejected(home)
    assert rows[-1]["id"] == "b" and rows[-1]["what"] == "cicada_save_episode" and "placeholder" not in str(rows)
    counts = tx_outbox.counts(home)
    assert counts["held"] == 1 and counts["waiting"] == 1 and counts["rejected"] == 1


def test_an_entry_the_home_may_have_seen_expires_before_the_homes_key(home):
    assert tx_outbox.EXPIRE_S < idempotency.TOOLS_TTL_S
    # Sent, and its answer lost: the home may hold its key, so it expires a day before the key does — listed, never
    # silently lost.
    tx_outbox.submit(_tool(key="old"), lambda e: (None, {"_noAnswer": "timeout"}), home=home)
    sent = []
    decided = tx_outbox.flush(lambda e: (sent.append(1) or 200, {}), home=home,
                              now=lambda: __import__("time").time() + tx_outbox.EXPIRE_S + 1)
    assert decided["old"][0] == "expired" and sent == [] and tx_outbox.counts(home)["expired"] == 1
    assert tx_outbox.rejected(home)[-1]["code"] == "expired_may_have_landed"


def test_an_entry_that_never_reached_the_home_never_expires(home):
    """Ruling 51f D1: "we sync when a machine is on" — a write that never reached the home waits however long."""
    tx_outbox.submit(_tool(key="never"), lambda e: (None, {"_noAnswer": "unreachable"}), home=home)
    tx_outbox.submit(_tool(key="notoken"), lambda e: (None, None), home=home)
    far = __import__("time").time() + 90 * 86_400
    assert tx_outbox.flush(lambda e: (None, {"_noAnswer": "unreachable"}), home=home, now=lambda: far)["never"][0] \
        == "wait"
    sent = []
    decided = tx_outbox.flush(lambda e: (sent.append(e["id"]) or 200, {}), home=home, now=lambda: far)
    assert decided["never"][0] == "landed" and decided["notoken"][0] == "landed" and sent == ["never", "notoken"]
    assert tx_outbox.counts(home)["expired"] == 0


def test_an_entry_from_before_the_rule_keeps_the_old_one(home):
    entry = {**_tool(key="legacy"), "v": 1, "attempts": 2}
    tx_outbox.keep(entry, home=home)
    decided = tx_outbox.flush(lambda e: (200, {}), home=home,
                              now=lambda: __import__("time").time() + tx_outbox.EXPIRE_S + 1)
    assert decided["legacy"][0] == "expired"


def test_a_rest_entry_keeps_its_bytes_and_a_capture_too_large_is_refused(home):
    entry = tx_outbox.rest_entry("POST", "/capture/note", "", b'{"text": "placeholder"}', "application/json",
                                 bank_id="b" * 32, base_seq=1)
    got = []
    tx_outbox.submit(entry, lambda e: (got.append(e) or 200, {"status": "created"}), home=home)
    import base64

    assert base64.b64decode(got[0]["body"]) == b'{"text": "placeholder"}'
    with pytest.raises(ValueError):
        tx_outbox.rest_entry("POST", "/capture/file", "", b"x" * (tx_outbox.MAX_BODY_BYTES + 1), None,
                             bank_id=None, base_seq=None)


#: Capture routes whose posts are made idempotent by their own content (a session's id, a source's item ids, a reader's
#: snapshot): a resend days later is the same write, whatever the key. Every other capture route is keyed.
SAME_BY_CONTENT = {
    "POST /capture/agent-memory", "POST /capture/local-source/wispr-flow", "POST /capture/session",
    # G132 phase 2: an offered episode is written once — its session or its words already here answers `already`.
    "POST /capture/offered",
    "POST /capture/telegram", "POST /capture/turn", "POST /sources/upload", "POST /sources/calendar-local/sync",
    "POST /sources/contacts-local/sync", "POST /sources/folders/{folder_id}/sync", "POST /sources/messages/sync",
    "POST /sources/reminders-local/sync", "POST /sources/sync-bookmarks", "POST /sources/sync-notes",
    # G39: one episode per book, staged by its asset id — a resend is the same edit in place.
    "POST /sources/apple-books/sync",
    # Ruling 61: a cover is stored by its bytes' hash under its asset id — a resend answers `unchanged`.
    "POST /sources/apple-books/covers",
    "POST /sources/sync-safari-tabs", "POST /sources/tab-groups/sync", "POST /sources/traces/sync",
    "POST /sources/watch-history/sync", "POST /sources/whatsapp/sync", "POST /files/media",
    "POST /files/{file_id}/frames",
}


def test_every_capture_route_keeps_its_key_longer_than_an_outbox_entry_waits():
    """Review of #566: a capture a copy queued may be sent again up to EXPIRE_S later with the same key; the home must
    still know that key then, or the capture is saved twice."""
    import inspect

    from fastapi.routing import APIRoute

    from api.main import app
    from api.services import replica_routes

    endpoints = {f"{m} {r.path}": r.endpoint for r in app.routes if isinstance(r, APIRoute) for m in r.methods}
    captures = {k for k, v in replica_routes.ROUTES.items() if v == replica_routes.CAPTURE}
    assert captures, "no capture routes"
    for route in sorted(captures):
        if "idempotency.run_once" in inspect.getsource(endpoints[route]):
            path = route.split(" ", 1)[1]
            assert idempotency.ttl_for(path) >= tx_outbox.EXPIRE_S + 24 * 3600, route
        else:
            assert route in SAME_BY_CONTENT, f"{route}: key it (8 days) or name how a resend stays one write"
    assert {r for r in captures if r not in SAME_BY_CONTENT} == {
        "POST /capture/note", "POST /capture/file", "POST /capture/isbn", "POST /sources/save"}


def test_a_full_outbox_says_so_in_words_and_drops_nothing_that_waits(home, monkeypatch):
    """Ruling 51f: nothing unsent expires, so the outbox is bounded by bytes too — and a write that does not fit is
    refused in words, never queued in words and lost in fact."""
    away = lambda e: (None, {"_noAnswer": "unreachable"})   # noqa: E731
    tx_outbox.submit(_tool(key="first"), away, home=home)
    monkeypatch.setattr(tx_outbox, "MAX_TOTAL_BYTES", 1)
    verdict, status, body = tx_outbox.submit(_tool(key="second"), away, home=home)
    assert verdict == "full" and status is None and body["code"] == "queue_full"
    assert "full" in body["text"] and "Nothing that waits was dropped" in body["text"]
    assert [p.name.endswith("-first.json") for p in tx_outbox.entries(home)] == [True]
    assert tx_outbox.counts(home)["refusedFull"] == 1
    assert tx_outbox.counts(home)["full"] is True, "the Devices page reads the full state from counts"
    monkeypatch.setattr(tx_outbox, "MAX_TOTAL_BYTES", 256 * 1024 * 1024)
    assert tx_outbox.counts(home)["full"] is True, "a small one would fit, but the last write was not kept"
    tx_outbox.submit(_tool(key="fits"), away, home=home)
    assert tx_outbox.counts(home)["full"] is False, "a write kept again: no longer full (refusedFull stays a counter)"
    monkeypatch.setattr(tx_outbox, "MAX_TOTAL_BYTES", 1)
    assert tx_outbox.keep(_tool(key="third"), home=home) is False
    verdict, _s, _b = tx_outbox.submit(_tool(key="fourth"), away, home=home)
    assert verdict == "full" and tx_outbox.counts(home)["full"] is True
    monkeypatch.setattr(tx_outbox, "MAX_TOTAL_BYTES", 256 * 1024 * 1024)
    for p in tx_outbox.entries(home):
        p.unlink()
    assert tx_outbox.counts(home)["full"] is False, "the queue drained below where it was refused"


def test_the_tool_door_tells_a_full_queue_in_words(monkeypatch):
    import asyncio

    from api.routers import tools
    from api.services import replica

    monkeypatch.setattr(tx_outbox, "submit", lambda entry, send, **kw: ("full", None, {"code": "queue_full",
                                                                                     "text": "queue is full"}))
    monkeypatch.setattr(replica, "seq", lambda: 3)

    class _Req:
        headers = {}

    got = asyncio.run(tools._to_home(tools.ToolCallRequest(tool="cicada_save_episode", arguments={}), _Req(), None))
    assert got["code"] == "queue_full" and got["error"] == "queue is full" and got["code"] != "queued_for_home"
