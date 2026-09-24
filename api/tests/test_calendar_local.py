"""G142 (round 4 D2, C6): Apple Calendar through EventKit — the backend half.
The app posts a rolling window; each event is one episode through the G20
stager, scrubbed, edited in place, tombstoned when it vanishes, committed once
per sync as the person. Synthetic events on example.com only."""
from __future__ import annotations

import subprocess

import pytest
from fastapi.testclient import TestClient

from _synthetic_bank import _bank
from api import config, main
from api.services import bank_index, calendar_local, demo_guard, markdown_parser, source_overview

WORK = {"id": "cal-work", "title": "Work", "account": "example.com"}
HOME = {"id": "cal-home", "title": "Home"}
WINDOW = {"from": "2026-09-01T00:00:00+00:00", "to": "2026-10-01T00:00:00+00:00"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield TestClient(main.app), memory
    config.get_settings.cache_clear()


def _event(eid, title="Alpha review", start="2026-09-24T10:00:00+02:00", cal="cal-work", **kw):
    return {"id": eid, "calendarId": cal, "title": title, "start": start, "end": "2026-09-24T11:00:00+02:00",
            "allDay": False, **kw}


def _post(c, events, calendars=(WORK, HOME), window=WINDOW):
    return c.post("/sources/calendar-local/sync",
                  json={"window": window, "calendars": list(calendars), "events": events})


def _episodes(memory):
    out = {}
    for path in sorted((memory / "episodes").glob("*.md")):
        parsed = markdown_parser.parse(path)
        sid = str(parsed.frontmatter.get("source_id") or "")
        if sid.startswith("calendar-local:"):
            out[sid] = parsed
    return out


def _head(memory):
    return subprocess.run(["git", "-C", str(memory), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()


def test_a_first_sync_stages_one_episode_per_event_and_commits_once_as_the_person(client):
    c, memory = client
    r = _post(c, [_event("E1|2026-09-24T08:00:00Z", attendees=["bob-example", "carol-example"],
                         organizer="bob-example", location="Room 4")])
    assert r.status_code == 200, r.text
    assert r.json() == {"created": 1, "updated": 0, "unchanged": 0, "tombstoned": 0, "bank": memory.name}
    [(sid, ep)] = _episodes(memory).items()
    assert sid == "calendar-local:E1|2026-09-24T08:00:00Z"
    fm = ep.frontmatter
    assert (fm["origin"], fm["source"], fm["processed"], fm["calendar_id"]) == (
        "calendar-local", "calendar-local", False, "cal-work")
    assert fm["event_start"] == "2026-09-24T10:00:00+02:00"
    assert ep.body.startswith("# Alpha review\n\n**Start:** 2026-09-24T10:00:00+02:00")
    assert "**Calendar:** Work (example.com)" in ep.body
    assert "**Attendees:** bob-example, carol-example" in ep.body and "**Location:** Room 4" in ep.body
    log = subprocess.run(["git", "-C", str(memory), "log", "-1", "--format=%B"], capture_output=True, text=True,
                         check=True).stdout
    assert log.startswith("Calendar sync") and "capture/calendar" in log and "Cicada-Author: user" in log


def test_the_same_window_again_changes_nothing_and_commits_nothing(client):
    c, memory = client
    _post(c, [_event("E1")])
    before = _head(memory)
    assert _post(c, [_event("E1")]).json()["unchanged"] == 1
    assert _head(memory) == before


def test_an_edit_rewrites_in_place_and_requeues(client):
    c, memory = client
    _post(c, [_event("E1")])
    [before] = _episodes(memory).values()
    assert _post(c, [_event("E1", title="Alpha review (moved)")]).json()["updated"] == 1
    [after] = _episodes(memory).values()
    assert after.frontmatter["id"] == before.frontmatter["id"] and after.frontmatter["processed"] is False
    assert after.body.startswith("# Alpha review (moved)")


def test_only_an_event_gone_from_a_named_calendar_inside_the_window_is_tombstoned(client):
    c, memory = client
    _post(c, [_event("E1"), _event("E2", start="2026-09-25T10:00:00+02:00"),
              _event("E3", cal="cal-elsewhere"), _event("E4", start="2026-12-24T10:00:00+01:00")],
          calendars=(WORK, HOME, {"id": "cal-elsewhere", "title": "Elsewhere"}))
    r = _post(c, [], calendars=(WORK, HOME))
    assert r.json()["tombstoned"] == 2
    eps = _episodes(memory)
    assert len(eps) == 4, "a tombstone keeps the file"
    gone = {sid for sid, ep in eps.items() if ep.frontmatter.get("source_deleted_at")}
    assert gone == {"calendar-local:E1", "calendar-local:E2"}
    assert _post(c, [_event("E1")], calendars=(WORK, HOME)).json()["updated"] == 1   # it came back (R-F1)
    assert not _episodes(memory)["calendar-local:E1"].frontmatter.get("source_deleted_at")


def test_notes_are_scrubbed_before_they_are_cut_and_a_link_loses_its_query(client):
    c, memory = client
    secret = "sk-" + "Z" * 24
    # Words, not one long run: a 1,990-character run of one letter is itself scrubbed as a
    # base64-like run, which would hide the ordering this test is about. Checked: cutting
    # first leaves "sk-ZZZZZZ" behind; scrubbing first leaves nothing.
    notes = "note " * 398 + secret + " tail"
    _post(c, [_event("E1", notes=notes, url="https://meet.example.com/j/123?pwd=abc123#frag",
                     attendees=[f"guest-{i}@example.com" for i in range(60)])])
    body = next(iter(_episodes(memory).values())).body
    assert "sk-" not in body, "a secret straddling the cut is redacted whole (R4B-13)"
    assert len(body.split("## Notes\n", 1)[1]) <= calendar_local.NOTES_CAP
    assert "**Link:** https://meet.example.com/j/123\n" in body and "pwd" not in body
    assert "(+10 more)" in body and "guest-59@" not in body


@pytest.mark.parametrize("window", [
    {"from": "2026-09-01T00:00:00", "to": "2026-10-01T00:00:00+00:00"},       # no offset
    {"from": "2026-10-01T00:00:00+00:00", "to": "2026-09-01T00:00:00+00:00"},  # out of order
])
def test_a_window_the_backend_cannot_trust_is_refused(client, window):
    c, memory = client
    assert _post(c, [_event("E1")], window=window).status_code == 422
    assert _episodes(memory) == {}


def test_too_many_events_is_refused(client, monkeypatch):
    c, memory = client
    monkeypatch.setattr(calendar_local, "MAX_EVENTS", 2)
    assert _post(c, [_event("E1"), _event("E2"), _event("E3")]).status_code == 413
    assert _episodes(memory) == {}


def test_a_demo_bank_is_refused_and_nothing_is_written(client, monkeypatch):
    c, memory = client
    monkeypatch.setattr(demo_guard, "is_demo", lambda path: True)
    assert _post(c, [_event("E1")]).status_code == 409
    assert _episodes(memory) == {}


def test_the_channel_is_offered_before_the_first_sync_and_counts_after(client):
    c, _ = client

    def row():
        return next(ch for ch in c.get("/sources/channels").json()["channels"] if ch["id"] == "calendar-local")

    assert (row()["label"], row()["connected"], row()["actions"]) == ("Apple Calendar", False, ["sync", "manage"])
    _post(c, [_event("E1"), _event("E2")])
    assert (row()["connected"], row()["count"], row()["countNoun"]) == (True, 2, "event")
    assert "calendar-local" in {spec.id for spec in source_overview.CATALOG}
