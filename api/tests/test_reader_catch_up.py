"""G229 — the app says what its readers are catching up on after it was closed; the bank says what came in.

Every client reads one answer from `GET /devices/status` (each machine's `catchUp`): which readers are reading, which
finished, which failed and the fix in the reader's own words, what came in while the app was closed (a harness capture
the backend took while nobody looked) and since it opened. Synthetic banks only."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import agent_seen, device_status, device_tokens, markdown_parser, reader_catch_up

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
AWAY = NOW - timedelta(hours=5)
OPENED = NOW - timedelta(seconds=30)


@pytest.fixture
def env(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "cicada"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_TELEMETRY", "off")
    monkeypatch.setenv("CICADA_API_AUTH", "off")
    monkeypatch.setattr(device_status, "_NAME", "studio-example")
    agent_seen.reset()
    reader_catch_up.reset()
    config.get_settings.cache_clear()
    yield memory
    reader_catch_up.reset()
    config.get_settings.cache_clear()


def _episode(memory: Path, eid: str, at: datetime, *, processed: bool = False, device: str | None = None) -> None:
    fm = {"id": eid, "timestamp": "2026-11-03T07:00:00Z", "processed": processed, "source": "claude-code"}
    if device:
        fm["device"] = device
    path = memory / "episodes" / f"{eid}.md"
    markdown_parser.write(path, fm, "user: hello\n")
    os.utime(path, (at.timestamp(), at.timestamp()))


READERS = [
    {"channel": "messages", "label": "Messages", "state": "reading", "fix": "never sent for a reading row"},
    {"channel": "calendar-local", "label": "Calendar", "state": "done"},
    {"channel": "notes", "label": "Notes", "state": "failed",
     "fix": "Notes couldn't be read. Allow Cicada under System Settings → Privacy & Security → Automation → Notes."},
]


def test_what_came_in_while_away_and_since_opening_are_counted_from_the_bank(env):
    _episode(env, "2026-11-03-001", NOW - timedelta(days=2))            # before the app closed: not "while away"
    _episode(env, "2026-11-03-002", AWAY + timedelta(hours=1))          # a harness capture while the app was closed
    _episode(env, "2026-11-03-003", AWAY + timedelta(hours=2))
    _episode(env, "2026-11-03-004", AWAY + timedelta(hours=3), processed=True)   # a scheduled read took it in
    _episode(env, "2026-11-03-005", OPENED + timedelta(seconds=5))      # a reader's post during the catch-up
    reader_catch_up.report(None, env, session="s1", opened_at=OPENED, away_since=AWAY, readers=READERS, done=False,
                           now=NOW)
    view = reader_catch_up.view(None, env, now=NOW)
    assert (view["state"], view["arrived"], view["new"]) == ("reading", 2, 1)
    assert [(r["label"], r["state"]) for r in view["readers"]] == [
        ("Messages", "reading"), ("Calendar", "done"), ("Notes", "failed")]
    assert view["readers"][0]["fix"] is None, "only a failed reader carries its fix"
    assert "Privacy & Security" in view["readers"][2]["fix"]
    assert view["awaySince"] == "2026-11-03T07:00:00Z"


def test_a_first_launch_has_no_away_window(env):
    _episode(env, "2026-11-03-001", AWAY)
    reader_catch_up.report(None, env, session="s1", opened_at=OPENED, away_since=None, readers=[], done=False, now=NOW)
    assert reader_catch_up.view(None, env, now=NOW)["arrived"] is None
    reader_catch_up.report(None, env, session="s2", opened_at=OPENED, away_since=NOW + timedelta(minutes=1),
                           readers=[], done=False, now=NOW)
    assert reader_catch_up.view(None, env, now=NOW)["arrived"] is None, "an away time after the open is no window"


def test_done_freezes_the_counts_and_stays_done_within_the_session(env):
    _episode(env, "2026-11-03-001", OPENED + timedelta(seconds=1))
    reader_catch_up.report(None, env, session="s1", opened_at=OPENED, away_since=AWAY, readers=READERS, done=True,
                           now=NOW)
    first = reader_catch_up.view(None, env, now=NOW)
    assert (first["state"], first["new"], first["doneAt"]) == ("done", 1, "2026-11-03T12:00:00Z")
    _episode(env, "2026-11-03-002", NOW + timedelta(seconds=10))        # a capture after the catch-up ended
    later = NOW + timedelta(minutes=1)
    reader_catch_up.report(None, env, session="s1", opened_at=OPENED, away_since=AWAY,
                           readers=[{"channel": "messages", "label": "Messages", "state": "reading"}], done=False,
                           now=later)
    again = reader_catch_up.view(None, env, now=later)
    assert (again["state"], again["new"]) == ("done", 1), "the app's later reading is not this catch-up"
    assert [(r["label"], r["state"]) for r in again["readers"]] == [("Calendar", "done"), ("Notes", "failed")], \
        "a finished catch-up has nothing still reading"
    # A new launch is a new catch-up.
    reader_catch_up.report(None, env, session="s2", opened_at=later, away_since=NOW, readers=[], done=False, now=later)
    assert reader_catch_up.view(None, env, now=later)["state"] == "reading"


def test_a_silent_reading_report_and_an_old_finish_are_dropped(env):
    reader_catch_up.report(None, env, session="s1", opened_at=OPENED, away_since=AWAY, readers=READERS, done=False,
                           now=NOW)
    assert reader_catch_up.view(None, env, now=NOW + timedelta(seconds=reader_catch_up.READING_TTL_S - 1))
    assert reader_catch_up.view(None, env, now=NOW + timedelta(seconds=reader_catch_up.READING_TTL_S + 1)) is None
    reader_catch_up.report(None, env, session="s2", opened_at=NOW, away_since=AWAY, readers=[], done=True, now=NOW)
    assert reader_catch_up.view(None, env, now=NOW + timedelta(seconds=reader_catch_up.SHOWN_AFTER_DONE_S - 1))
    assert reader_catch_up.view(None, env, now=NOW + timedelta(seconds=reader_catch_up.SHOWN_AFTER_DONE_S + 1)) is None


def test_the_app_reports_and_every_client_reads_it_on_the_machine_row(env):
    client = TestClient(main.app)
    now = datetime.now(timezone.utc)
    _episode(env, "2026-11-03-001", now - timedelta(hours=1))
    body = {"session": "launch-1", "openedAt": (now - timedelta(seconds=5)).isoformat(),
            "awaySince": (now - timedelta(hours=3)).isoformat(), "readers": READERS, "done": False}
    answer = client.put("/sources/catch-up", json=body)
    assert answer.status_code == 200
    assert (answer.json()["catchUp"]["state"], answer.json()["catchUp"]["arrived"]) == ("reading", 1)
    rows = client.get("/devices/status").json()["devices"]
    assert rows[0]["name"] == "studio-example" and rows[0]["catchUp"]["readers"][0]["label"] == "Messages"
    assert client.put("/sources/catch-up", json={**body, "readers": [{**READERS[0], "state": "lost"}]}).status_code == 422


def test_a_device_reports_its_own_catch_up(env):
    laptop, _ = device_tokens.store().create("laptop-example")
    reader_catch_up.report(laptop.id, env, session="s1", opened_at=OPENED, away_since=AWAY, readers=READERS[:1],
                           done=False, now=NOW)
    rows = device_status.snapshot(env, now=NOW)["devices"]
    assert rows[0]["catchUp"] is None
    assert rows[1]["name"] == "laptop-example" and rows[1]["catchUp"]["state"] == "reading"


def test_another_bank_never_sees_this_ones_catch_up(env, tmp_path):
    other = tmp_path / "other"
    (other / "episodes").mkdir(parents=True)
    reader_catch_up.report(None, env, session="s1", opened_at=OPENED, away_since=AWAY, readers=[], done=False, now=NOW)
    assert reader_catch_up.view(None, other, now=NOW) is None
