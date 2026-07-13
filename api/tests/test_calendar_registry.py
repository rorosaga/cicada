"""Hermetic tests for ICS/webcal calendar subscriptions + polling (calendar_registry).

Covers:
- ``subscribe_calendar`` idempotency (dedup on the normalized URL, ``webcal://``
  -> ``https://`` normalization, tag merge on re-subscribe), ``list_calendars``,
  ``unsubscribe_calendar``;
- ``parse_ics`` — folded lines, TZID resolution, a date-only all-day event,
  ingestion-window filtering, RRULE presence noted but not expanded, a
  malformed document degrading to ``[]``;
- ``ingest_ics`` — one episode per event, dedup keyed on UID+DTSTART(+SEQUENCE)
  so an edited (SEQUENCE-bumped) event re-ingests while an unchanged one never
  duplicates;
- ``poll_calendars`` with an injected ``fetch_fn`` — same shape as
  ``feed_registry.poll_feeds`` (network gate, per-calendar error isolation,
  ``last_polled`` stamping);
- the four ``/sources/calendars*`` + ``/sources/poll-calendars`` endpoints via
  ``TestClient``.

Every test builds its own ``tmp_path`` workspace; no test ever performs a real
network call — ``fetch_fn`` is always injected or the network gate is
deliberately left closed. ``now`` is always pinned explicitly for
``parse_ics`` so window-filtering assertions never depend on wall-clock time.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from api.services import calendar_registry


def run(coro):
    return asyncio.run(coro)


def _memory(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True, exist_ok=True)
    return memory


NOW = datetime(2026, 7, 13, 12, 0, 0)  # pinned "today" for window-filtering tests


ICS_BASIC = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//Test//EN
BEGIN:VTIMEZONE
TZID:America/New_York
BEGIN:STANDARD
DTSTART:19701101T020000
TZOFFSETFROM:-0400
TZOFFSETTO:-0500
TZNAME:EST
END:STANDARD
BEGIN:DAYLIGHT
DTSTART:19700308T020000
TZOFFSETFROM:-0500
TZOFFSETTO:-0400
TZNAME:EDT
END:DAYLIGHT
END:VTIMEZONE
BEGIN:VEVENT
UID:event-1@example.com
DTSTAMP:20260701T120000Z
DTSTART;TZID=America/New_York:20260715T090000
DTEND;TZID=America/New_York:20260715T100000
SUMMARY:Team sync
LOCATION:Zoom
DESCRIPTION:Weekly team sync meeting
END:VEVENT
END:VCALENDAR
"""

ICS_FOLDED = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//Test//EN
BEGIN:VEVENT
UID:event-folded@example.com
DTSTAMP:20260701T120000Z
DTSTART:20260716T090000Z
DTEND:20260716T100000Z
SUMMARY:This is a very long event summary that gets folded across multiple
  physical lines per RFC 5545 line folding rules to make sure unfolding work
  s correctly
DESCRIPTION:Another folded field spanning
 two lines of continuation text
END:VEVENT
END:VCALENDAR
"""

ICS_ALL_DAY = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//Test//EN
BEGIN:VEVENT
UID:event-allday@example.com
DTSTAMP:20260701T120000Z
DTSTART;VALUE=DATE:20260720
DTEND;VALUE=DATE:20260721
SUMMARY:Company Offsite
END:VEVENT
END:VCALENDAR
"""

ICS_OUT_OF_WINDOW = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//Test//EN
BEGIN:VEVENT
UID:event-too-old@example.com
DTSTAMP:20240701T120000Z
DTSTART:20240101T090000Z
DTEND:20240101T100000Z
SUMMARY:Ancient event
END:VEVENT
BEGIN:VEVENT
UID:event-too-future@example.com
DTSTAMP:20260701T120000Z
DTSTART:20300101T090000Z
DTEND:20300101T100000Z
SUMMARY:Distant future event
END:VEVENT
BEGIN:VEVENT
UID:event-in-window@example.com
DTSTAMP:20260701T120000Z
DTSTART:20260715T090000Z
DTEND:20260715T100000Z
SUMMARY:In-window event
END:VEVENT
END:VCALENDAR
"""

ICS_RECURRING = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//Test//EN
BEGIN:VEVENT
UID:event-recurring@example.com
DTSTAMP:20260701T120000Z
DTSTART:20260715T090000Z
DTEND:20260715T100000Z
SUMMARY:Weekly standup
RRULE:FREQ=WEEKLY;COUNT=10
END:VEVENT
END:VCALENDAR
"""

ICS_TWO_EVENTS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//Test//EN
BEGIN:VEVENT
UID:event-a@example.com
DTSTAMP:20260701T120000Z
DTSTART:20260715T090000Z
DTEND:20260715T100000Z
SUMMARY:Event A
END:VEVENT
BEGIN:VEVENT
UID:event-b@example.com
DTSTAMP:20260701T120000Z
DTSTART:20260716T090000Z
DTEND:20260716T100000Z
SUMMARY:Event B
END:VEVENT
END:VCALENDAR
"""

ICS_TWO_EVENTS_PLUS_ONE = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//Test//EN
BEGIN:VEVENT
UID:event-a@example.com
DTSTAMP:20260701T120000Z
DTSTART:20260715T090000Z
DTEND:20260715T100000Z
SUMMARY:Event A
END:VEVENT
BEGIN:VEVENT
UID:event-b@example.com
DTSTAMP:20260701T120000Z
DTSTART:20260716T090000Z
DTEND:20260716T100000Z
SUMMARY:Event B
END:VEVENT
BEGIN:VEVENT
UID:event-c@example.com
DTSTAMP:20260701T120000Z
DTSTART:20260717T090000Z
DTEND:20260717T100000Z
SUMMARY:Event C — brand new
END:VEVENT
END:VCALENDAR
"""

ICS_EDITED_EVENT_V1 = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//Test//EN
BEGIN:VEVENT
UID:event-edit@example.com
DTSTAMP:20260701T120000Z
DTSTART:20260715T090000Z
DTEND:20260715T100000Z
SEQUENCE:0
SUMMARY:Original title
END:VEVENT
END:VCALENDAR
"""

ICS_EDITED_EVENT_V2 = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//Test//EN
BEGIN:VEVENT
UID:event-edit@example.com
DTSTAMP:20260702T120000Z
DTSTART:20260715T090000Z
DTEND:20260715T110000Z
SEQUENCE:1
SUMMARY:Updated title
END:VEVENT
END:VCALENDAR
"""

NOT_ICS = "this is not an ICS document at all <<<"


# --- subscribe / list / unsubscribe -----------------------------------------


def test_subscribe_calendar_creates_record(tmp_path):
    memory = _memory(tmp_path)
    record = calendar_registry.subscribe_calendar(
        memory, "https://a.example.com/cal.ics", tags=["work"]
    )
    assert record["url"] == "https://a.example.com/cal.ics"
    assert record["tags"] == ["work"]
    assert record["added"]
    assert record["last_polled"] is None

    calendars = calendar_registry.list_calendars(memory)
    assert len(calendars) == 1


def test_subscribe_calendar_normalizes_webcal_to_https(tmp_path):
    memory = _memory(tmp_path)
    record = calendar_registry.subscribe_calendar(memory, "webcal://a.example.com/cal.ics")
    assert record["url"] == "https://a.example.com/cal.ics"


def test_subscribe_calendar_dedups_webcal_and_https_variants(tmp_path):
    memory = _memory(tmp_path)
    calendar_registry.subscribe_calendar(memory, "https://a.example.com/cal.ics")
    calendar_registry.subscribe_calendar(memory, "webcal://a.example.com/cal.ics")

    calendars = calendar_registry.list_calendars(memory)
    assert len(calendars) == 1


def test_subscribe_calendar_merges_tags_on_resubscribe(tmp_path):
    memory = _memory(tmp_path)
    calendar_registry.subscribe_calendar(memory, "https://a.example.com/cal.ics", tags=["work"])
    record = calendar_registry.subscribe_calendar(
        memory, "https://a.example.com/cal.ics", tags=["personal"]
    )
    assert set(record["tags"]) == {"work", "personal"}
    assert len(calendar_registry.list_calendars(memory)) == 1


def test_list_calendars_empty_when_no_registry(tmp_path):
    memory = _memory(tmp_path)
    assert calendar_registry.list_calendars(memory) == []


def test_unsubscribe_calendar_removes_record(tmp_path):
    memory = _memory(tmp_path)
    calendar_registry.subscribe_calendar(memory, "https://a.example.com/cal.ics")
    calendar_registry.subscribe_calendar(memory, "https://b.example.com/cal.ics")

    assert calendar_registry.unsubscribe_calendar(memory, "https://a.example.com/cal.ics") is True
    calendars = calendar_registry.list_calendars(memory)
    assert len(calendars) == 1
    assert calendars[0]["url"] == "https://b.example.com/cal.ics"


def test_unsubscribe_calendar_returns_false_when_not_found(tmp_path):
    memory = _memory(tmp_path)
    assert calendar_registry.unsubscribe_calendar(memory, "https://nope.example.com/cal.ics") is False


def test_calendar_registry_survives_corrupt_yaml(tmp_path):
    memory = _memory(tmp_path)
    (memory / calendar_registry.CALENDARS_FILENAME).write_text(
        "{not: valid: yaml: [", encoding="utf-8"
    )
    assert calendar_registry.list_calendars(memory) == []


# --- parse_ics ---------------------------------------------------------------


def test_parse_ics_basic_event_with_tzid(tmp_path):
    events = calendar_registry.parse_ics(ICS_BASIC, now=NOW)
    assert len(events) == 1
    ev = events[0]
    assert ev.uid == "event-1@example.com"
    assert ev.summary == "Team sync"
    assert ev.location == "Zoom"
    assert ev.description == "Weekly team sync meeting"
    assert ev.all_day is False
    # TZID-resolved DTSTART carries an offset (America/New_York in July = EDT, -04:00).
    assert "2026-07-15T09:00:00" in ev.dtstart_iso
    assert "-04:00" in ev.dtstart_iso or "+00:00" not in ev.dtstart_iso


def test_parse_ics_unfolds_folded_lines(tmp_path):
    events = calendar_registry.parse_ics(ICS_FOLDED, now=NOW)
    assert len(events) == 1
    ev = events[0]
    assert "folded across multiple" in ev.summary
    assert "physical lines" in ev.summary
    assert "correctly" in ev.summary
    assert "Another folded field spanning" in ev.description
    assert "two lines" in ev.description


def test_parse_ics_date_only_all_day_event(tmp_path):
    events = calendar_registry.parse_ics(ICS_ALL_DAY, now=NOW)
    assert len(events) == 1
    ev = events[0]
    assert ev.all_day is True
    assert ev.dtstart_iso == "2026-07-20"
    assert ev.dtend_iso == "2026-07-21"


def test_parse_ics_window_filtering(tmp_path):
    events = calendar_registry.parse_ics(ICS_OUT_OF_WINDOW, now=NOW)
    uids = {e.uid for e in events}
    assert uids == {"event-in-window@example.com"}


def test_parse_ics_notes_recurring_flag_without_expanding(tmp_path):
    events = calendar_registry.parse_ics(ICS_RECURRING, now=NOW)
    assert len(events) == 1
    assert events[0].recurring is True


def test_parse_ics_non_recurring_flag_false(tmp_path):
    events = calendar_registry.parse_ics(ICS_BASIC, now=NOW)
    assert events[0].recurring is False


def test_parse_ics_malformed_returns_empty(tmp_path):
    assert calendar_registry.parse_ics(NOT_ICS, now=NOW) == []
    assert calendar_registry.parse_ics("", now=NOW) == []


# --- ingest_ics: episode writing + dedup ------------------------------------


def test_ingest_ics_writes_one_episode_per_event(tmp_path):
    memory = _memory(tmp_path)
    created, duplicates = calendar_registry.ingest_ics(
        ICS_TWO_EVENTS, memory, "https://a.example.com/cal.ics", commit=False
    )
    assert created == 2
    assert duplicates == 0

    episodes = list((memory / "episodes").glob("ep_*.md"))
    assert len(episodes) == 2

    from api.services import markdown_parser

    parsed = [markdown_parser.parse(p) for p in episodes]
    titles = {p.frontmatter["title"] for p in parsed}
    assert titles == {"Event A", "Event B"}
    for p in parsed:
        assert p.frontmatter["origin"] == "calendar"
        assert p.frontmatter["source"] == "calendar"
        assert p.frontmatter["processed"] is False
        assert p.frontmatter["calendar_url"] == "https://a.example.com/cal.ics"


def test_ingest_ics_unchanged_event_skipped_on_second_call(tmp_path):
    memory = _memory(tmp_path)
    calendar_registry.ingest_ics(
        ICS_TWO_EVENTS, memory, "https://a.example.com/cal.ics", commit=False
    )
    created, duplicates = calendar_registry.ingest_ics(
        ICS_TWO_EVENTS, memory, "https://a.example.com/cal.ics", commit=False
    )
    assert created == 0
    assert duplicates == 2

    episodes = list((memory / "episodes").glob("ep_*.md"))
    assert len(episodes) == 2  # no new episodes on the repeat


def test_ingest_ics_only_new_event_ingests_on_second_poll(tmp_path):
    memory = _memory(tmp_path)
    calendar_registry.ingest_ics(
        ICS_TWO_EVENTS, memory, "https://a.example.com/cal.ics", commit=False
    )
    created, duplicates = calendar_registry.ingest_ics(
        ICS_TWO_EVENTS_PLUS_ONE, memory, "https://a.example.com/cal.ics", commit=False
    )
    assert created == 1
    assert duplicates == 2

    episodes = list((memory / "episodes").glob("ep_*.md"))
    assert len(episodes) == 3


def test_ingest_ics_edited_event_sequence_bump_reingests(tmp_path):
    memory = _memory(tmp_path)
    created1, _ = calendar_registry.ingest_ics(
        ICS_EDITED_EVENT_V1, memory, "https://a.example.com/cal.ics", commit=False
    )
    assert created1 == 1

    created2, duplicates2 = calendar_registry.ingest_ics(
        ICS_EDITED_EVENT_V2, memory, "https://a.example.com/cal.ics", commit=False
    )
    assert created2 == 1  # SEQUENCE bumped -> re-ingested as a fresh episode
    assert duplicates2 == 0

    episodes = list((memory / "episodes").glob("ep_*.md"))
    assert len(episodes) == 2

    from api.services import markdown_parser

    titles = {markdown_parser.parse(p).frontmatter["title"] for p in episodes}
    assert titles == {"Original title", "Updated title"}


# --- poll_calendars: injected fetch_fn --------------------------------------


def test_poll_calendars_ingests_new_events_via_injected_fetch(tmp_path, monkeypatch):
    memory = _memory(tmp_path)
    calendar_registry.subscribe_calendar(memory, "https://a.example.com/cal.ics")

    calls = []

    def fetch_fn(url):
        calls.append(url)
        return ICS_TWO_EVENTS

    result = run(calendar_registry.poll_calendars(memory, fetch_fn=fetch_fn))

    assert calls == ["https://a.example.com/cal.ics"]
    assert result["polled"] == 1
    assert result["new"] == 2
    assert result["per_calendar"] == [
        {"url": "https://a.example.com/cal.ics", "status": "ok", "new": 2, "duplicates": 0}
    ]

    calendars = calendar_registry.list_calendars(memory)
    assert calendars[0]["last_polled"] is not None

    episodes = list((memory / "episodes").glob("ep_*.md"))
    assert len(episodes) == 2


def test_poll_calendars_only_ingests_new_events_on_second_poll(tmp_path):
    memory = _memory(tmp_path)
    calendar_registry.subscribe_calendar(memory, "https://a.example.com/cal.ics")

    run(calendar_registry.poll_calendars(memory, fetch_fn=lambda url: ICS_TWO_EVENTS))
    result = run(
        calendar_registry.poll_calendars(memory, fetch_fn=lambda url: ICS_TWO_EVENTS_PLUS_ONE)
    )

    assert result["polled"] == 1
    assert result["new"] == 1
    assert result["per_calendar"][0]["duplicates"] == 2

    episodes = list((memory / "episodes").glob("ep_*.md"))
    assert len(episodes) == 3


def test_poll_calendars_polls_multiple_subscriptions(tmp_path):
    memory = _memory(tmp_path)
    calendar_registry.subscribe_calendar(memory, "https://a.example.com/cal.ics")
    calendar_registry.subscribe_calendar(memory, "https://b.example.com/cal.ics")

    ics_by_url = {
        "https://a.example.com/cal.ics": ICS_TWO_EVENTS,
        "https://b.example.com/cal.ics": ICS_ALL_DAY,
    }
    result = run(calendar_registry.poll_calendars(memory, fetch_fn=lambda url: ics_by_url[url]))

    assert result["polled"] == 2
    assert result["new"] == 3  # 2 from A + 1 all-day from B


def test_poll_calendars_no_subscriptions_is_noop(tmp_path):
    memory = _memory(tmp_path)
    result = run(calendar_registry.poll_calendars(memory, fetch_fn=lambda url: ICS_TWO_EVENTS))
    assert result == {"polled": 0, "new": 0, "per_calendar": []}


def test_poll_calendars_skips_when_no_fetch_and_gate_closed(tmp_path, monkeypatch):
    monkeypatch.delenv("CICADA_ALLOW_FEED_FETCH", raising=False)
    memory = _memory(tmp_path)
    calendar_registry.subscribe_calendar(memory, "https://a.example.com/cal.ics")
    calendar_registry.subscribe_calendar(memory, "https://b.example.com/cal.ics")

    result = run(calendar_registry.poll_calendars(memory))

    assert result == {"polled": 0, "new": 0, "skipped_no_network": 2, "per_calendar": []}
    calendars = calendar_registry.list_calendars(memory)
    assert all(c["last_polled"] is None for c in calendars)


# --- poll_calendars: malformed / unreachable calendar never raises ---------


def test_poll_calendars_records_malformed_calendar_without_raising(tmp_path):
    memory = _memory(tmp_path)
    calendar_registry.subscribe_calendar(memory, "https://a.example.com/cal.ics")
    calendar_registry.subscribe_calendar(memory, "https://bad.example.com/cal.ics")

    def fetch_fn(url):
        return NOT_ICS if "bad" in url else ICS_TWO_EVENTS

    result = run(calendar_registry.poll_calendars(memory, fetch_fn=fetch_fn))

    assert result["polled"] == 2
    statuses = {c["url"]: c["status"] for c in result["per_calendar"]}
    assert statuses["https://a.example.com/cal.ics"] == "ok"
    assert statuses["https://bad.example.com/cal.ics"] == "ok"  # parses to [] -> (0, 0), not an error


def test_poll_calendars_records_unreachable_calendar_error_and_continues(tmp_path):
    memory = _memory(tmp_path)
    calendar_registry.subscribe_calendar(memory, "https://unreachable.example.com/cal.ics")
    calendar_registry.subscribe_calendar(memory, "https://a.example.com/cal.ics")

    def fetch_fn(url):
        if "unreachable" in url:
            raise ConnectionError("could not connect")
        return ICS_TWO_EVENTS

    result = run(calendar_registry.poll_calendars(memory, fetch_fn=fetch_fn))

    assert result["polled"] == 2
    assert result["new"] == 2
    statuses = {c["url"]: c["status"] for c in result["per_calendar"]}
    assert statuses["https://unreachable.example.com/cal.ics"] == "error"
    assert statuses["https://a.example.com/cal.ics"] == "ok"

    calendars = {c["url"]: c for c in calendar_registry.list_calendars(memory)}
    assert calendars["https://unreachable.example.com/cal.ics"]["last_polled"] is not None


# --- endpoints ---------------------------------------------------------------


def _make_client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main

    memory = _memory(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.delenv("CICADA_ALLOW_FEED_FETCH", raising=False)
    config.get_settings.cache_clear()
    return TestClient(main.app), memory


def test_endpoint_subscribe_and_list(tmp_path, monkeypatch):
    client, memory = _make_client(tmp_path, monkeypatch)

    resp = client.post(
        "/sources/calendars", json={"url": "https://a.example.com/cal.ics", "tags": ["work"]}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["url"] == "https://a.example.com/cal.ics"

    resp2 = client.get("/sources/calendars")
    assert resp2.status_code == 200
    body = resp2.json()
    assert body["total"] == 1
    assert body["calendars"][0]["url"] == "https://a.example.com/cal.ics"


def test_endpoint_subscribe_accepts_webcal_and_normalizes(tmp_path, monkeypatch):
    client, _ = _make_client(tmp_path, monkeypatch)
    resp = client.post("/sources/calendars", json={"url": "webcal://a.example.com/cal.ics"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["url"] == "https://a.example.com/cal.ics"


def test_endpoint_subscribe_rejects_bad_url(tmp_path, monkeypatch):
    client, _ = _make_client(tmp_path, monkeypatch)
    resp = client.post("/sources/calendars", json={"url": "not-a-url"})
    assert resp.status_code == 422


def test_endpoint_subscribe_is_idempotent(tmp_path, monkeypatch):
    client, _ = _make_client(tmp_path, monkeypatch)
    client.post("/sources/calendars", json={"url": "https://a.example.com/cal.ics"})
    client.post("/sources/calendars", json={"url": "https://a.example.com/cal.ics"})

    resp = client.get("/sources/calendars")
    assert resp.json()["total"] == 1


def test_endpoint_unsubscribe(tmp_path, monkeypatch):
    client, _ = _make_client(tmp_path, monkeypatch)
    client.post("/sources/calendars", json={"url": "https://a.example.com/cal.ics"})

    resp = client.request("DELETE", "/sources/calendars", json={"url": "https://a.example.com/cal.ics"})
    assert resp.status_code == 200, resp.text

    resp2 = client.get("/sources/calendars")
    assert resp2.json()["total"] == 0


def test_endpoint_unsubscribe_missing_returns_404(tmp_path, monkeypatch):
    client, _ = _make_client(tmp_path, monkeypatch)
    resp = client.request("DELETE", "/sources/calendars", json={"url": "https://nope.example.com/cal.ics"})
    assert resp.status_code == 404


def test_endpoint_poll_calendars_no_network_by_default(tmp_path, monkeypatch):
    client, _ = _make_client(tmp_path, monkeypatch)
    client.post("/sources/calendars", json={"url": "https://a.example.com/cal.ics"})

    resp = client.post("/sources/poll-calendars")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["polled"] == 0
    assert body["skipped_no_network"] == 1


def test_endpoint_poll_calendars_no_subscriptions(tmp_path, monkeypatch):
    client, _ = _make_client(tmp_path, monkeypatch)
    resp = client.post("/sources/poll-calendars")
    assert resp.status_code == 200
    assert resp.json() == {"polled": 0, "new": 0, "per_calendar": []}
