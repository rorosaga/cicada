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


def test_an_entry_expires_before_the_homes_key(home):
    assert tx_outbox.EXPIRE_S < idempotency.TOOLS_TTL_S
    tx_outbox.submit(_tool(key="old"), lambda e: (None, None), home=home)
    sent = []
    decided = tx_outbox.flush(lambda e: (sent.append(1) or 200, {}), home=home,
                              now=lambda: __import__("time").time() + tx_outbox.EXPIRE_S + 1)
    assert decided["old"][0] == "expired" and sent == [] and tx_outbox.counts(home)["expired"] == 1


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
