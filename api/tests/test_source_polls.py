"""G245 track C1: feeds, calendar feeds and the tier-1 connectors poll on the backend's own job, not only in Sleep's
tail. Hermetic: no network, no model, no real bank. Every URL and name is a placeholder."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from api.services import (calendar_registry, demo_guard, feed_registry, media_ingestor, sleep_cycle, source_polls,
                          sync_state, write_admission)
from api.services.connectors import ADAPTERS, base
from api.services.media_ingestor import RawItem

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>Feed A</title><link>https://a.example.com</link>
<item><title>First</title><link>https://a.example.com/first</link><description>x</description></item>
</channel></rss>"""
ICS = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:evt-1@example.com
DTSTART:20990101T100000Z
DTEND:20990101T110000Z
SUMMARY:A meeting
END:VEVENT
END:VCALENDAR
"""


@pytest.fixture
def bank(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True)
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(sleep_cycle, "is_writing", lambda: False)
    source_polls.reset_for_tests()

    async def offline(url, client, from_bookmark_file=False):
        return media_ingestor.MediaMeta(title=media_ingestor._fallback_title(url), description="",
                                        site=media_ingestor._site_of(url), media_type="url")

    async def no_commit(memory_path, count, paths=None):
        return None

    monkeypatch.setattr(media_ingestor, "enrich", offline)
    monkeypatch.setattr(media_ingestor, "_commit_media", no_commit)
    yield memory
    source_polls.reset_for_tests()


def _run(coro):
    return asyncio.run(coro)


def _fake_connectors(monkeypatch, calls, *, connected=("reddit",)):
    for cid, adapter in ADAPTERS.items():
        async def fake(memory_path, *, _cid=cid, **kw):
            calls.append((_cid, base.INGEST_ADMISSION.get() is not None))
            return {"status": "ok", "new": 0, "seen": 0, "error": None}

        monkeypatch.setattr(adapter, "sync", fake)
        monkeypatch.setattr(adapter, "is_connected", lambda _c=cid: _c in connected)


# --- the connectors --------------------------------------------------------------------------------------------------


def test_the_job_polls_a_connected_tier_one_connector_and_never_a_tier_two_one(bank, monkeypatch):
    calls: list = []
    _fake_connectors(monkeypatch, calls, connected=tuple(ADAPTERS))      # every connector connected
    out = _run(source_polls.scheduled_poll(bank))
    tier_one = [cid for cid, a in ADAPTERS.items() if getattr(a, "TIER", 1) != 2]
    assert sorted(c for c, _ in calls) == sorted(tier_one)
    assert all(admitted for _, admitted in calls), "each poll's ingest runs through the admitted transaction"
    assert set(out["connectors"]) == set(tier_one)


def test_nothing_connected_polls_nothing_and_stamps_nothing(bank, monkeypatch):
    calls: list = []
    _fake_connectors(monkeypatch, calls, connected=())
    _run(source_polls.scheduled_poll(bank))
    assert calls == [] and not source_polls.polled_lately(bank, source_polls.CONNECTORS)


def test_the_job_polls_nothing_while_sleep_holds_the_pages(bank, monkeypatch):
    calls: list = []
    _fake_connectors(monkeypatch, calls)
    monkeypatch.setattr(sleep_cycle, "is_writing", lambda: True)
    assert _run(source_polls.scheduled_poll(bank)) == {"skipped": "sleep is reading"}
    assert calls == []


def test_a_demo_bank_is_never_polled(bank, monkeypatch):
    calls: list = []
    _fake_connectors(monkeypatch, calls)
    monkeypatch.setattr(demo_guard, "is_demo", lambda path: True)
    assert "skipped" in _run(source_polls.scheduled_poll(bank))
    assert calls == []


def test_a_replica_or_a_moving_home_polls_nothing(bank, monkeypatch):
    from api.services import home_move, replica_guard

    calls: list = []
    _fake_connectors(monkeypatch, calls)
    monkeypatch.setattr(replica_guard, "blocks", lambda: True)
    assert "skipped" in _run(source_polls.scheduled_poll(bank))
    monkeypatch.setattr(replica_guard, "blocks", lambda: False)
    monkeypatch.setattr(home_move, "writes_closed", lambda: True)
    assert "skipped" in _run(source_polls.scheduled_poll(bank))
    assert calls == []


def test_a_connector_poll_is_gated_by_the_connector_switch_and_says_so_on_its_row(bank, monkeypatch):
    monkeypatch.setenv("CICADA_ALLOW_CONNECTOR_FETCH", "off")

    async def fetch(fn):
        raise AssertionError("no fetch behind a closed gate")

    monkeypatch.setattr(ADAPTERS["reddit"], "is_connected", lambda: True)
    monkeypatch.setattr(ADAPTERS["reddit"], "sync",
                        lambda mp, **kw: base.run_sync("reddit", mp, fetch, is_connected=lambda: True, **kw))
    for cid, a in ADAPTERS.items():
        if cid != "reddit":
            monkeypatch.setattr(a, "is_connected", lambda: False)
    _run(source_polls.scheduled_poll(bank))
    assert sync_state.read_sync_state(bank)["reddit"]["last_skip_reason"] == "network fetch disabled"


def test_a_second_run_inside_the_floor_does_not_poll_a_kind_again(bank, monkeypatch):
    calls: list = []
    _fake_connectors(monkeypatch, calls)
    _run(source_polls.scheduled_poll(bank))
    _run(source_polls.scheduled_poll(bank))
    assert len(calls) == 1
    assert source_polls.polled_lately(bank, source_polls.CONNECTORS)


def test_sleeps_tail_leaves_a_kind_the_job_polled_lately_alone(bank, monkeypatch):
    calls: list = []
    _fake_connectors(monkeypatch, calls)
    _run(source_polls.scheduled_poll(bank))
    calls.clear()
    _run(sleep_cycle._poll_connectors_safely(bank))
    assert calls == []
    source_polls.reset_for_tests()
    _run(sleep_cycle._poll_connectors_safely(bank))
    assert calls, "with no recent job poll the tail polls as before"


def test_an_ingest_that_meets_sleep_after_its_fetch_saves_nothing_and_keeps_its_cursor(bank, monkeypatch):
    state = {"writing": False}
    monkeypatch.setattr(sleep_cycle, "is_writing", lambda: state["writing"])
    items = [RawItem(url="https://example.com/a", origin="acme")]

    async def fetch(fn):
        state["writing"] = True            # Sleep opens its window while the fetch is in flight
        return items, {"cursor": "abc"}

    token = base.INGEST_ADMISSION.set(source_polls.admitted_ingest)
    try:
        result = _run(base.run_sync("acme", bank, fetch, is_connected=lambda: True, http_fn=lambda *a, **k: None))
    finally:
        base.INGEST_ADMISSION.reset(token)
    assert result["status"] == "skipped"
    assert not list((bank / "episodes").glob("*.md"))
    assert "acme" not in sync_state.read_sync_state(bank) or "cursor" not in sync_state.read_sync_state(bank)["acme"]
    assert sync_state.read_sync_state(bank)["acme"]["last_skip_reason"] == base.WAITED_FOR_SLEEP
    assert write_admission.holders(bank) == 0


def test_an_admitted_ingest_saves_and_records_like_the_plain_one(bank):
    items = [RawItem(url="https://example.com/a", origin="acme")]

    async def fetch(fn):
        return items, {"cursor": "abc"}

    token = base.INGEST_ADMISSION.set(source_polls.admitted_ingest)
    try:
        result = _run(base.run_sync("acme", bank, fetch, is_connected=lambda: True, http_fn=lambda *a, **k: None))
    finally:
        base.INGEST_ADMISSION.reset(token)
    assert result == {"status": "ok", "reason": None, "new": 1, "seen": 1, "error": None}
    assert sync_state.read_sync_state(bank)["acme"]["cursor"] == "abc"


# --- feeds and calendars ---------------------------------------------------------------------------------------------


def _no_connectors(monkeypatch):
    for a in ADAPTERS.values():
        monkeypatch.setattr(a, "is_connected", lambda: False)


def test_feeds_and_calendars_are_polled_with_the_feed_gate_open_and_not_without_it(bank, monkeypatch):
    _no_connectors(monkeypatch)
    feed_registry.subscribe_feed(bank, "https://a.example.com/feed.xml")
    calendar_registry.subscribe_calendar(bank, "https://cal.example.com/c.ics")
    fetched: list[str] = []

    async def fetch(url):
        fetched.append(url)
        return ICS if url.endswith(".ics") else RSS

    monkeypatch.setattr(feed_registry, "_default_fetch", fetch)
    monkeypatch.setattr(calendar_registry, "_default_fetch", fetch)

    monkeypatch.delenv("CICADA_ALLOW_FEED_FETCH", raising=False)
    out = _run(source_polls.scheduled_poll(bank))
    assert out["feeds"] == {"skipped": "feed fetch is off"} and out["calendars"] == {"skipped": "feed fetch is off"}
    assert fetched == []

    monkeypatch.setenv("CICADA_ALLOW_FEED_FETCH", "1")
    out = _run(source_polls.scheduled_poll(bank))
    assert sorted(fetched) == ["https://a.example.com/feed.xml", "https://cal.example.com/c.ics"]
    assert out["feeds"]["polled"] == 1 and out["feeds"]["new"] == 1
    assert out["calendars"]["polled"] == 1
    assert (bank / "feeds.yaml").exists() and feed_registry.list_feeds(bank)[0]["last_polled"]


def test_a_feed_that_fails_is_recorded_by_the_registry_and_never_stops_the_job(bank, monkeypatch):
    _no_connectors(monkeypatch)
    monkeypatch.setenv("CICADA_ALLOW_FEED_FETCH", "1")
    feed_registry.subscribe_feed(bank, "https://a.example.com/feed.xml")
    feed_registry.subscribe_feed(bank, "https://b.example.com/feed.xml")

    async def fetch(url):
        if "a.example" in url:
            raise RuntimeError("down")
        return RSS

    monkeypatch.setattr(feed_registry, "_default_fetch", fetch)
    out = _run(source_polls.scheduled_poll(bank))
    assert out["feeds"]["polled"] == 2 and out["feeds"]["new"] == 1
    problems = {f["url"]: f.get("last_problem") for f in feed_registry.list_feeds(bank)}
    assert problems["https://a.example.com/feed.xml"] and not problems["https://b.example.com/feed.xml"]


def test_a_feed_poll_that_meets_sleep_after_its_fetch_writes_nothing(bank, monkeypatch):
    _no_connectors(monkeypatch)
    monkeypatch.setenv("CICADA_ALLOW_FEED_FETCH", "1")
    feed_registry.subscribe_feed(bank, "https://a.example.com/feed.xml")
    state = {"writing": False}
    monkeypatch.setattr(sleep_cycle, "is_writing", lambda: state["writing"])

    async def fetch(url):
        state["writing"] = True
        return RSS

    monkeypatch.setattr(feed_registry, "_default_fetch", fetch)
    out = _run(source_polls.scheduled_poll(bank))
    assert out["feeds"] == {"skipped": "sleep is reading"}
    assert not list((bank / "episodes").glob("*.md"))
    assert not source_polls.polled_lately(bank, source_polls.FEEDS)
    assert write_admission.holders(bank) == 0


def test_the_job_is_registered_beside_the_tier_two_job():
    import ast
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "main.py").read_text()
    ast.parse(text)
    assert 'id="source-polls"' in text and "source_polls.scheduled_poll" in text
    assert source_polls.SCHEDULE_HOURS <= 6


# --- the catch-up with nothing to read -------------------------------------------------------------------------------


def _tail_rig(bank, monkeypatch):
    seen: list[str] = []
    for name in ("_refresh_state_safely", "_expire_claims_safely", "_propose_followups_safely",
                 "_catchup_questions_safely", "_link_sources_safely", "_rematch_linkedin_safely",
                 "_rematch_contacts_safely", "_where_to_check_safely", "_sensitive_review_safely",
                 "_site_sources_safely", "_source_refresh_safely", "_poll_connectors_safely",
                 "_poll_feeds_and_calendars_safely", "_resolve_papers_safely", "_replay_wispr_todos_safely",
                 "_warm_logos_safely", "_embed_indexed_episodes_safely", "_refresh_questions_safely",
                 "_commit_graph_safely", "_index_without_model_safely", "_flush_pending_commits_safely"):
        async def step(*a, _n=name, **k):
            seen.append(_n)

        monkeypatch.setattr(sleep_cycle, name, step)
    for name in ("_same_name_review_safely", "_in_short_safely", "_media_read_safely", "_web_check_safely",
                 "_web_context_safely", "_backfill_links_safely"):
        async def model_step(*a, _n=name, **k):
            seen.append(_n)

        monkeypatch.setattr(sleep_cycle, name, model_step)

    async def resolve_books(memory_path, settings):
        seen.append(f"_resolve_books_safely(settings={'None' if settings is None else 'set'})")

    monkeypatch.setattr(sleep_cycle, "_resolve_books_safely", resolve_books)

    async def window(memory_path):
        return True

    monkeypatch.setattr(sleep_cycle, "_open_window", window)
    return seen


def test_an_engine_free_tail_runs_the_polls_and_upkeep_and_asks_no_model(bank, monkeypatch):
    seen = _tail_rig(bank, monkeypatch)
    settings = SimpleNamespace(memory_path=bank)
    _run(sleep_cycle.run(settings, "cycle-quiet", user_triggered=False, tail_only=True, engine_free=True))
    assert "_poll_connectors_safely" in seen and "_poll_feeds_and_calendars_safely" in seen
    assert "_expire_claims_safely" in seen and "_resolve_books_safely(settings=None)" in seen
    for model_step in ("_same_name_review_safely", "_in_short_safely", "_media_read_safely", "_web_check_safely",
                       "_web_context_safely", "_backfill_links_safely"):
        assert model_step not in seen
    assert sleep_cycle.get_sleep_state().status == "idle"


def test_a_paused_runs_upkeep_still_runs_its_model_steps_as_before(bank, monkeypatch):
    seen = _tail_rig(bank, monkeypatch)
    settings = SimpleNamespace(memory_path=bank)
    _run(sleep_cycle.run(settings, "cycle-paused", user_triggered=False, tail_only=True))
    assert "_in_short_safely" in seen and "_resolve_books_safely(settings=set)" in seen


def test_an_engine_free_run_records_no_sleep_run(bank, monkeypatch):
    from api.services import sleep_runs

    _tail_rig(bank, monkeypatch)
    assert sleep_runs.all_runs(bank) == {}
    _run(sleep_cycle.run(SimpleNamespace(memory_path=bank), "cycle-quiet", user_triggered=False, tail_only=True,
                         engine_free=True))
    assert sleep_runs.all_runs(bank) == {}
