"""Ruling 34, follow-up to #403 — Sleep dates a conversation by the person's day, and a relayed one by the app's zone.

#403 made episode ids and the two id readers follow ruling 34; Sleep's own dating still took a conversation's day from
the first ten characters of its UTC ``timestamp`` (``source_dates.episode_day``, ``entity_extractor._claim_date``, a
page's ``created``/``last_referenced``), so words said at 00:27 in Madrid (22:27 UTC the day before) were dated a day
early. One reading rule now (``episode_ids.local_day``); the decay arithmetic is untouched, only the day it starts from.

Synthetic stamps and a scratch bank only; the machine zone is pinned per test with ``TZ``.
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from _synthetic_bank import _bank
from api import config
from api.config import Settings
from api.services import (conflict_resolver, entity_extractor, episode_ids, link_enrichment, markdown_parser,
                          providers, relay_capture, source_dates, wispr_flow)

#: 00:27 on the 22nd in Madrid (CEST, UTC+2) is 22:27 UTC on the 21st.
AFTER_MIDNIGHT = "2026-10-21T22:27:00Z"
OLD_UTC_ID = "ep_2026-10-21_001"   # what a hook minted for it before ruling 34


def _zone(monkeypatch, name: str):
    monkeypatch.setenv("TZ", name)
    time.tzset()


@pytest.fixture
def madrid(monkeypatch):
    _zone(monkeypatch, "Europe/Madrid")
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.fixture
def utc_server(monkeypatch):
    _zone(monkeypatch, "UTC")
    yield
    monkeypatch.undo()
    time.tzset()


# --------------------------------------------------------------------------- #
# The one reading rule
# --------------------------------------------------------------------------- #


def test_the_reading_rule_takes_the_persons_day(madrid):
    assert episode_ids.local_day(AFTER_MIDNIGHT) == date(2026, 10, 22)
    assert episode_ids.local_day("2026-10-21T22:27:00+00:00") == date(2026, 10, 22)
    assert episode_ids.local_day(datetime(2026, 10, 21, 22, 27, tzinfo=timezone.utc)) == date(2026, 10, 22)
    assert episode_ids.local_day("2026-10-21T12:00:00Z") == date(2026, 10, 21), "midday: the same day either way"


def test_old_episodes_without_an_offset_keep_their_meaning(madrid):
    """A legacy naive stamp was this machine's local time; a bare day is already a day; junk is no day."""
    assert episode_ids.local_day("2026-10-22T00:27:00") == date(2026, 10, 22)
    assert episode_ids.local_day("2026-10-22") == date(2026, 10, 22)
    assert episode_ids.local_day(date(2026, 10, 22)) == date(2026, 10, 22)
    assert episode_ids.local_day("t") is None and episode_ids.local_day(None) is None
    assert episode_ids.local_day("2026-02-30") is None


def test_the_day_follows_daylight_saving_at_each_instant(madrid):
    """Madrid leaves summer time at 03:00 CEST on 2026-10-25 (01:00 UTC): the same 22:30 UTC is 00:30 the next
    day before the change and 23:30 the same day after it. Spring forward (2026-03-29) the other way."""
    assert episode_ids.local_day("2026-10-24T22:30:00Z") == date(2026, 10, 25)   # CEST, +2
    assert episode_ids.local_day("2026-10-25T22:30:00Z") == date(2026, 10, 25)   # CET, +1: still the 25th
    assert episode_ids.local_day("2026-10-25T23:30:00Z") == date(2026, 10, 26)
    assert episode_ids.local_day("2026-03-28T23:30:00Z") == date(2026, 3, 29)    # CET, +1
    assert episode_ids.local_day("2026-03-29T22:30:00Z") == date(2026, 3, 30)    # CEST, +2


def test_the_readers_that_had_their_own_copy_now_share_it(madrid):
    from api.services import ask_sources, change_timeline

    for stamp in (AFTER_MIDNIGHT, "2026-10-22T00:27:00", "2026-10-22", "junk"):
        assert ask_sources.local_day(stamp) == change_timeline._local_day(stamp) == episode_ids.local_day(stamp)


# --------------------------------------------------------------------------- #
# Sleep's extraction context
# --------------------------------------------------------------------------- #


def _resp(content: str):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


async def _no_sleep(*_a, **_k):
    return None


def _extract(episodes, reply, today):
    seen: list[str] = []

    async def fake(**kw):
        seen.append(kw["messages"][1]["content"])
        return _resp(reply)

    with patch.object(providers, "resolve_llm_fn", lambda *a, **k: fake), \
            patch.object(entity_extractor.asyncio, "sleep", _no_sleep):
        out = asyncio.run(entity_extractor.extract([dict(e) for e in episodes], Settings(_env_file=None), today=today))
    return out, seen


def test_a_conversation_just_after_local_midnight_is_dated_its_local_day_by_extraction(madrid):
    episode = {"id": OLD_UTC_ID, "timestamp": AFTER_MIDNIGHT, "origin": "claude-code",
               "content": "user: Alpha Co moved its office to the harbour.\nassistant: Noted."}
    reply = json.dumps({"entities": [{"name": "Alpha Co", "type": "organization", "confidence": 0.8}],
                        "relationships": [{"source": "Alpha Co", "target": "Harbour", "label": "located_in"}]})
    out, seen = _extract([episode], reply, date(2026, 10, 22))
    assert seen and "this conversation is dated 2026-10-22; today is 2026-10-22" in seen[0]
    assert "took place today" in seen[0]
    entity = next(e for e in out[0]["entities"] if e["name"] == "Alpha Co")
    assert entity["source_episode_day"] == "2026-10-22"
    assert source_dates.episode_day(episode) == date(2026, 10, 22)


def test_a_claim_is_valid_from_the_local_day(madrid):
    assert entity_extractor._claim_date(AFTER_MIDNIGHT, OLD_UTC_ID) == "2026-10-22"
    assert entity_extractor._claim_date(None, OLD_UTC_ID) == "2026-10-21", "no stamp: the id's day, as before"
    assert entity_extractor._claim_date("t", "ep_2025-03-01_004") == "2025-03-01"
    assert entity_extractor._claim_date(None, "not-an-episode") == ""


def test_a_pages_created_and_last_mention_take_the_local_day(madrid):
    """Where decay counts from — only the day attribution changes, never the arithmetic."""
    change = {"source_episodes": [OLD_UTC_ID, "ep_2026-10-20_001"],
              "source_episode_timestamps": [AFTER_MIDNIGHT, "2026-10-20T10:00:00Z"],
              "source_episode_timestamp": AFTER_MIDNIGHT}
    assert conflict_resolver._latest_change_date(change) == "2026-10-22"
    assert conflict_resolver._earliest_change_date(change) == "2026-10-20"
    assert conflict_resolver._new_mention_day(change, known=set(), untimed=frozenset()) == "2026-10-22"
    assert conflict_resolver._change_dates(change) == ["2026-10-20", "2026-10-22"]
    legacy = {"source_episode_timestamps": ["2026-10-22T00:27:00"]}   # naive local, no offset: unchanged
    assert conflict_resolver._latest_change_date(legacy) == "2026-10-22"


def test_a_recommends_claim_is_dated_a_day_never_an_id_prefix(tmp_path, madrid):
    bank = _bank(tmp_path)
    markdown_parser.write(bank / "episodes" / f"{OLD_UTC_ID}.md",
                          {"id": OLD_UTC_ID, "timestamp": "2026-10-21T22:27:00+00:00"}, "**user:** hi\n")
    assert link_enrichment._said_on(bank, OLD_UTC_ID) == "2026-10-22"
    assert link_enrichment._said_on(bank, "ep_2026-10-19_003") == "2026-10-19", "no file: the id's day"
    assert link_enrichment._said_on(bank, "") == ""


def test_a_staged_source_mints_its_id_on_the_local_day(madrid):
    draft = wispr_flow.note_draft({"id": "n1", "content": "a note about alpha-project", "title": "n",
                                   "createdAt": "2026-10-21T22:27:00Z", "isDeleted": 0})
    assert draft is not None and draft.original_date == "2026-10-22"


# --------------------------------------------------------------------------- #
# The relay (ruling 32): ChatGPT's zone hint, claude.ai's none
# --------------------------------------------------------------------------- #


def test_the_zone_hint_is_read_from_the_meta_and_only_the_zone():
    at = datetime(2026, 10, 21, 22, 27, tzinfo=timezone.utc)
    assert episode_ids.zone_offset_minutes("Europe/Madrid", at) == 120
    assert episode_ids.zone_offset_minutes("Europe/Madrid", datetime(2026, 10, 26, tzinfo=timezone.utc)) == 60
    assert episode_ids.zone_offset_minutes("America/New_York", at) == -240
    assert episode_ids.zone_offset_minutes("Not/AZone") is None and episode_ids.zone_offset_minutes(None) is None
    assert episode_ids.zone_offset_minutes("../../etc/passwd") is None
    assert relay_capture.offset_from_meta({"openai/userLocation": {"timezone": "Asia/Tokyo", "city": "x"}}) == 540
    assert relay_capture.offset_from_meta({"openai/userLocation": "Asia/Tokyo"}) is None
    assert relay_capture.offset_from_meta({}) is None and relay_capture.offset_from_meta(None) is None


@pytest.fixture
def remote_world(tmp_path, monkeypatch):
    from api.remote import store
    from api.remote.runtime import RemoteRuntime

    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    # The conversation's first turn is at 22:27 UTC on the 21st: 07:27 on the 22nd in Tokyo (no daylight saving).
    monkeypatch.setattr(episode_ids, "utc_now_iso", lambda: "2026-10-21T22:27:00+00:00")
    db = store.ConnectorStore(tmp_path / "remote" / "connectors.db")
    runtime = RemoteRuntime(post=lambda p, d: {"status": "resolved"}, sleep_running=lambda: False)
    yield db, runtime, memory
    config.get_settings.cache_clear()


H = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json",
     "Mcp-Protocol-Version": "2025-11-25"}


def _relay(db, runtime, app, meta=None):
    from api.remote import app as remote_app

    _, token = db.create(app=app, label="", scopes=["record"], expires_in_days=30)
    params = {"name": "cicada_capture_turns", "arguments": {"message": "Plan the alpha-project launch checklist."}}
    if meta is not None:
        params["_meta"] = meta
    with TestClient(remote_app.build_app(db, runtime=runtime)) as c:
        resp = c.post(f"/c/{token}/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params},
                      headers=H)
    assert resp.json()["result"]["isError"] is False, resp.json()


def _relayed_ids(memory):
    return sorted(p.stem for p in (memory / "episodes").glob("ep_*.md")
                  if isinstance(markdown_parser.parse(p).frontmatter.get("relay"), dict))


def test_a_relayed_turn_with_chatgpts_zone_hint_takes_the_persons_day(remote_world, utc_server):
    db, runtime, memory = remote_world
    _relay(db, runtime, "chatgpt", {"openai/userLocation": {"timezone": "Asia/Tokyo", "city": "x"}})
    assert _relayed_ids(memory) == ["ep_2026-10-22_001"]


def test_a_relayed_turn_without_a_hint_takes_the_servers_zone(remote_world, utc_server):
    """claude.ai sends no zone, and a model's guess is never asked for: the id takes this server's day, as before."""
    db, runtime, memory = remote_world
    _relay(db, runtime, "claude")
    assert _relayed_ids(memory) == ["ep_2026-10-21_001"]
