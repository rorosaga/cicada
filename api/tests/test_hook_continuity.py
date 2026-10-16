"""G110 slice 1a T4: SessionStart tells a new session where the last one in its
folder stopped, inside one budgeted note (plan C4).

The route resolves the capture bank once per request; a bounded registry
transaction runs BEFORE any assembly (a prompt's arrival is recorded even when
its answer times out); the whole `additionalContext` is measured as the final
string; the ledger carries enums only. Synthetic banks only."""
from __future__ import annotations

import fcntl
import os
import time

import pytest
from fastapi.testclient import TestClient

from _continuity_fixtures import CWD, sid, write_session
from api import config, main
from api.services import (
    bank_registry, continuity, continuity_sessions, handshake, hook_recall, recall_text, telemetry,
)
from test_continuity import A_TURNS
from test_hook_recall import bank  # noqa: F401 — the G149 synthetic bank

URL = "/capture/hook-context"
ME = sid(77)


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    hook_recall.reset()
    continuity.reset()
    yield
    hook_recall.reset()
    continuity.reset()
    config.get_settings.cache_clear()


@pytest.fixture
def client(bank, monkeypatch):  # noqa: F811
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    return TestClient(main.app)


def _start(client, *, source="clear", session=ME, cwd=CWD):
    return client.post(URL, json={"event": "session_start", "harness": "claude-code", "session_id": session,
                                  "cwd": cwd, "source": source}).json()


def _row(bank, session=ME):  # noqa: F811
    return continuity_sessions.get(bank, "claude-code", session, bank_paths=(bank,))


@pytest.mark.parametrize("source", ["startup", "clear"])
def test_a_new_session_hears_where_the_last_one_here_stopped(client, bank, source):  # noqa: F811
    write_session(bank, 1, A_TURNS)
    data = _start(client, source=source)
    note = data["additionalContext"]
    assert note.startswith(recall_text.PRIMER_HEADER) and recall_text.is_injection(note)
    assert "### Where the last session in this folder stopped" in note
    assert "Not X, it breaks the fixture loader" not in note and "Workspace state not checked" in note
    assert "previous work" in note
    assert len(note) // 4 <= handshake.MAX_TOKENS
    row = _row(bank)
    assert row["continues"] == "ep_2026-09-03_001" and row["started_at"]
    assert row["cwd_hash"] == continuity_sessions.cwd_hash(CWD)


@pytest.mark.parametrize("source", ["resume", "compact", "fork", None])
def test_resume_compact_and_fork_carry_their_own_history(client, bank, source):  # noqa: F811
    write_session(bank, 1, A_TURNS)
    note = _start(client, source=source)["additionalContext"]
    assert "Where the last session" not in note
    row = _row(bank)
    assert row["started_at"] and "continues" not in row


def test_an_unknown_source_answers_200_and_is_treated_as_unknown(client, bank):  # noqa: F811
    write_session(bank, 1, A_TURNS)
    r = client.post(URL, json={"event": "session_start", "harness": "claude-code", "session_id": ME,
                               "cwd": CWD, "source": ["not", "a", "string"]})
    assert r.status_code == 200 and "Where the last session" not in r.json()["additionalContext"]   # unknown: closed
    r = client.post(URL, json={"event": "session_start", "harness": "claude-code", "session_id": sid(78),
                               "cwd": CWD, "source": "x" * 40})
    assert r.status_code == 200


def test_another_folder_hears_nothing_and_a_question_records_no_continues(client, bank):  # noqa: F811
    write_session(bank, 1, A_TURNS)
    assert "Where the last session" not in _start(client, cwd="/home/example/beta")["additionalContext"]
    write_session(bank, 2, [("user", "another task"), ("assistant", "ok")], start=2)
    note = _start(client, session=sid(79))["additionalContext"]
    assert "### Recent sessions in this folder" in note
    assert "continues" not in _row(bank, sid(79))


def test_a_timed_out_prompt_still_records_its_arrival(client, bank, monkeypatch):  # noqa: F811
    real = hook_recall.prompt_context

    def slow(*a, **k):
        time.sleep(0.3)
        return real(*a, **k)

    monkeypatch.setattr(hook_recall, "PROMPT_BUDGET_S", 0.1)
    monkeypatch.setattr(hook_recall, "prompt_context", slow)
    data = client.post(URL, json={"event": "user_prompt_submit", "harness": "claude-code", "session_id": ME,
                                  "cwd": CWD, "prompt": "alpha project?"}).json()
    assert data["reason"] == "timeout"
    assert _row(bank)["last_prompt_at"]


def test_a_held_registry_lock_never_costs_the_answer(client, bank, monkeypatch):  # noqa: F811
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    write_session(bank, 1, A_TURNS)
    continuity_sessions.apply(bank, bank_paths=(bank,), harness="claude-code", session_id=sid(5),
                              events={"started_at": "2026-10-01T00:00:00+00:00"}, deadline=None)
    home = continuity_sessions.continuity_home((bank,))
    fd = os.open(home / f"{continuity_sessions.bank_file_id(bank)}.lock", os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        data = _start(client)
        # Server-side latency: TestClient's per-request loop also waits for the
        # worker thread at shutdown, which a long-lived server never does.
        assert data["latencyMs"] <= hook_recall.PRIMER_BUDGET_S * 1000 + 50
    finally:
        os.close(fd)
    assert "Where the last session" in data["additionalContext"]
    row = [e for e in telemetry.read_events() if e.kind == telemetry.HOOK_RECALL_KIND][-1]
    assert row.refs["registry"] == "busy" and row.refs["continuity"] == "latest"
    assert row.refs["rendering"] == "pointer"


def test_a_slow_registry_still_answers_within_the_budget(client, bank, monkeypatch):  # noqa: F811
    real = continuity_sessions._write

    def slow(path, rows):
        time.sleep(1.2)
        real(path, rows)

    monkeypatch.setattr(continuity_sessions, "_write", slow)
    data = _start(client)
    assert data["latencyMs"] <= hook_recall.PRIMER_BUDGET_S * 1000 + 50
    assert data["reason"] == "timeout"
    time.sleep(1.5)                               # the late write lands, monotonically
    assert _row(bank)["started_at"]


def test_the_capture_bank_is_resolved_once_per_request(client, bank, monkeypatch):  # noqa: F811
    calls = []
    real = bank_registry.capture_bank
    monkeypatch.setattr(bank_registry, "capture_bank", lambda root: calls.append(root) or real(root))
    write_session(bank, 1, A_TURNS)
    _start(client)
    assert len(calls) == 1


def test_the_ledger_row_carries_enums_only(client, bank, monkeypatch):  # noqa: F811
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    write_session(bank, 1, A_TURNS)
    _start(client)
    row = [e for e in telemetry.read_events() if e.kind == telemetry.HOOK_RECALL_KIND][-1]
    assert row.refs["continuity"] == "latest" and row.refs["registry"] == "ok"
    raw = row.to_json()
    assert "fixture loader" not in raw and "/home/example" not in raw and "ep_2026" not in raw


# --- the compositor ------------------------------------------------------------


def _block_for(room):
    if 200 <= room:
        return "B" * 200, "pointer"
    return "", "none"


LIMIT = handshake.MAX_TOKENS * 4 + 3
HEADER = recall_text.PRIMER_HEADER


def _primer_leaving(room: int, reading: str | None) -> str:
    """A primer that leaves exactly ``room`` characters for the block."""
    fixed = len(HEADER) + 2 + 2 + (len(reading) + 2 if reading else 0)
    return "P" * (LIMIT - fixed - room)


@pytest.mark.parametrize("room, reading, expected, reading_kept", [
    (1600, "R" * 300, "pointer", True),
    (800, "R" * 300, "pointer", True),
    (250, "R" * 300, "pointer", True),
    (100, "R" * 300, "pointer", False),
    (-100, "R" * 300, "pointer", False),       # defer reading to preserve the history hint
    (250, None, "pointer", False),
])
def test_the_whole_note_is_measured_and_degrades_in_order(room, reading, expected, reading_kept):
    text, rendering, kept = recall_text.compose_note(HEADER, _primer_leaving(room, reading),
                                                     block_for=_block_for, reading=reading,
                                                     max_tokens=handshake.MAX_TOKENS)
    assert len(text) // 4 <= handshake.MAX_TOKENS
    assert rendering == expected and kept == reading_kept


def test_an_oversized_primer_falls_back_to_a_pointer_note():
    text, rendering, kept = recall_text.compose_note(recall_text.PRIMER_HEADER, "P" * 9000, block_for=_block_for,
                                                     reading="R", max_tokens=handshake.MAX_TOKENS)
    assert text == recall_text.PRIMER_HEADER + "\n\n" + recall_text.PRIMER_FALLBACK + "\n\n" + "B" * 200
    assert rendering == "pointer" and not kept


def test_a_dropped_reading_sentence_is_heard_on_the_first_prompt(bank, monkeypatch):  # noqa: F811
    write_session(bank, 1, A_TURNS)
    monkeypatch.setattr(hook_recall, "reading_line_for",
                        lambda *a, **k: ("R" * 400, (3, 1)))
    monkeypatch.setattr(handshake, "load_or_build", lambda *a, **k: ("P" * 7000, {}))
    inj = hook_recall.session_start_note(bank, harness="claude-code", session_id=ME, cwd=CWD, source="clear",
                                         bank_paths=(bank,), deadline=time.monotonic() + 1)
    assert "R" * 400 not in inj.text and len(inj.text) // 4 <= handshake.MAX_TOKENS
    assert hook_recall.READING_SEEN.told(ME) == 0


def test_the_real_primer_with_a_block_and_reading_fits(bank, monkeypatch):  # noqa: F811
    write_session(bank, 1, [("user", "u " * 1000), ("assistant", "a " * 1000)] * 3)
    monkeypatch.setattr(hook_recall, "reading_line_for", lambda *a, **k: (recall_text.reading_line(12), (12, 3)))
    inj = hook_recall.session_start_note(bank, harness="claude-code", session_id=ME, cwd=CWD, source="clear",
                                         bank_paths=(bank,), deadline=time.monotonic() + 1)
    assert len(inj.text) // 4 <= handshake.MAX_TOKENS and inj.rendering == "pointer"
    assert recall_text.reading_line(12) in inj.text
