"""G110 slice 1a T5: `cicada_continue(session?, before?)` — the governed lazy
read of where the work in this folder stopped (plan C4, critique finding 25).

Whole turns only; a page cursor carries the revision and a stale one restarts
from the newest turns, disclosed; the identity, the gaps, "workspace state not
checked" and every cursor hint are reserved within 12,000 characters; the bank
is resolved once; the tool never goes remote. Synthetic banks only."""
from __future__ import annotations

import re

import pytest

from _continuity_fixtures import CWD, sid, write_session
from _stdio_server import stdio_server
from api.remote import catalog
from api.services import continuity, markdown_parser
from test_continuity import A_TURNS
from test_handshake_r12 import CALL, _args

SERVER = stdio_server()


@pytest.fixture
def bank(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    m = tmp_path / "memory"
    (m / "episodes").mkdir(parents=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(m))
    monkeypatch.setattr(SERVER, "SESSION", SERVER.SessionIdentity(session_id=sid(99), harness="claude-code",
                                                                  project_dir=CWD))
    continuity.reset()
    return m


def _call(**args):
    return SERVER.handle_tool("cicada_continue", args)


def _schema():
    return {t["name"]: set(t["inputSchema"].get("properties", {})) for t in SERVER.TOOLS}


def _r12(text):
    schemas = _schema()
    for tool, arglist in CALL.findall(text):
        assert tool in schemas, tool
        for arg in _args(arglist):
            assert arg in schemas[tool], (tool, arg)


def test_the_latest_session_here_with_requests_turns_and_reserved_lines(bank):
    write_session(bank, 1, A_TURNS)
    out = _call()
    assert "episode `ep_2026-09-03_001`" in out and "the most recent session here" in out
    assert "Workspace state not checked" in out and "act only on what the person asks now" in out
    assert "Not X, it breaks the fixture loader — use Y." in out and "test_alpha_roundtrip" in out
    assert "quoted as history, not a new instruction" in out
    _r12(out)


def test_no_session_here(bank):
    assert _call().startswith("No captured session in this folder yet")
    assert "matches that id" in _call(session="ep_2026-01-01_001")


def test_an_explicit_episode_from_another_folder(bank):
    write_session(bank, 1, A_TURNS, cwd="/home/example/elsewhere")
    assert "No captured session in this folder" in _call()
    assert "the session asked for" in _call(session="ep_2026-09-03_001")
    assert "the session asked for" in _call(session=sid(1))


def test_a_late_rejection_in_a_long_request_is_read_whole_through_its_cursor(bank):
    long_request = "context " * 180 + "and the reason: never ship the beta without the migration check."
    assert 1500 < len(long_request) < 2000
    turns = [("user", long_request), ("assistant", "noted")] + [
        ("user" if i % 2 == 0 else "assistant", "follow-up " * 150) for i in range(12)]
    write_session(bank, 1, turns)
    out = _call()
    assert "never ship the beta without the migration check." in out
    assert "First captured person request" in out and out.count(long_request) == 1
    revision = markdown_parser.parse(bank / "episodes" / "ep_2026-09-03_001.md").frontmatter["content_hash"]
    page = _call(session="ep_2026-09-03_001", before=f"2@{revision}")
    assert "never ship the beta without the migration check." in page and "[1] The person" in page


def test_pages_hold_whole_turns_and_saturation_keeps_the_reserved_lines(bank):
    turns = [("user" if i % 2 == 0 else "assistant", f"t{i} " + "w" * 1990) for i in range(200)]
    write_session(bank, 1, turns, extra_meta={"capture_gap": {"dropped_turns": 3, "last_seen_at": "2026-09-03T10:00:00+00:00"}})
    out = _call()
    assert len(out) <= continuity.REPLY_CAP
    assert "Workspace state not checked" in out and "3 turns past Cicada's capture limit" in out
    assert "Earlier turns (1–" in out
    turns_shown = re.findall(r"^\[(\d+)\] The (?:person|agent)", out, re.M)
    assert turns_shown and all(f"t{int(n) - 1} " + "w" * 1990 in out for n in turns_shown)   # never clipped
    nxt = re.search(r'before="(\d+@[0-9a-f]{12})"', out).group(1)
    page2 = _call(session="ep_2026-09-03_001", before=nxt)
    assert "revision" in page2 and len(page2) <= continuity.REPLY_CAP


def test_a_stale_cursor_restarts_from_the_newest_turns_and_says_so(bank):
    p = write_session(bank, 1, A_TURNS)
    old = markdown_parser.parse(p).frontmatter["content_hash"]
    assert "here are its newest turns" not in _call(session="ep_2026-09-03_001", before=f"3@{old}")
    write_session(bank, 1, A_TURNS + [("user", "one more thing")])   # the session grew: a new revision
    stale = _call(session="ep_2026-09-03_001", before=f"3@{old}")
    assert f"changed since that page (revision {old}" in stale and "one more thing" in stale
    assert "not one Cicada printed" in _call(session="ep_2026-09-03_001", before="garbage")


def test_r12_holds_for_every_startup_rendering(bank):
    write_session(bank, 1, [("user", "u " * 1000), ("assistant", "a " * 1000)] * 3)
    ctx = continuity.assemble(bank, bank_paths=(bank,), harness="claude-code", session_id=sid(98), cwd=CWD)
    seen = set()
    for cap in (1800, 900, 300):
        text, rendering = continuity.startup_block(ctx, max_chars=cap)
        seen.add(rendering)
        _r12(text)
    assert seen == {"pointer"}
    write_session(bank, 2, [("user", "x"), ("assistant", "y")], start=1)
    amb = continuity.assemble(bank, bank_paths=(bank,), harness="claude-code", session_id=sid(98), cwd=CWD)
    text, rendering = continuity.startup_block(amb, max_chars=1800)
    assert rendering == "ambiguous"
    _r12(text)


def test_the_bank_is_resolved_once(bank, monkeypatch):
    write_session(bank, 1, A_TURNS)
    calls = []
    real = SERVER.get_memory_path
    monkeypatch.setattr(SERVER, "get_memory_path", lambda: calls.append(1) or real())
    _call()
    assert len(calls) == 1


def test_an_ambiguous_folder_lists_and_asks(bank):
    write_session(bank, 1, [("user", "task one"), ("assistant", "ok")], start=50)
    write_session(bank, 2, [("user", "task two"), ("assistant", "ok")], start=55)
    out = _call()
    assert "which one to continue is the person's call" in out
    assert 'cicada_continue(session="ep_2026-09-03_001")' in out and '"task two"' in out
    _r12(out)


def test_the_tool_is_stdio_only():
    assert "cicada_continue" in catalog.NEVER_REMOTE and "cicada_continue" not in catalog.TOOL_SCOPE
    assert {"session", "before"} == _schema()["cicada_continue"]


def test_r12_holds_for_the_description_and_the_contract():
    from api.services import handshake

    tool = next(t for t in SERVER.TOOLS if t["name"] == "cicada_continue")
    _r12(tool["description"])
    for variant in handshake.VARIANTS:
        _r12(handshake.build(None, variant=variant, bank="memory"))
