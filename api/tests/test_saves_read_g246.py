"""Every save is read (ruling 80, owner 2026-11-24, G246): "if i save it already has a reason."

A save he makes singly waits for Sleep tonight and is read after every conversation; one that arrives in bulk, one received
long after it was saved and every save a bank already kept wait their turn in a pile, a fixed number released a day,
newest first. A night that ends at a line he set with only such saves left is a finished night, not a pause. A save with
nothing to read is said so. Synthetic banks, placeholder titles and example.com links only.
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from _synthetic_bank import _bank
from drain_harness import git, install, is_processed, seed_bank, settings

from api.config import Settings
from api.services import (authorship, bank_index, entity_extractor, history_index, markdown_parser, media_ingestor,
                          mention_asks, owner_identity, providers, saved_lookup, saved_mentions, saved_order,
                          saved_reading, search_index, sleep_cycle, sleep_debt, sleep_paused, sleep_scheduler)
from api.services.connections import registry as registry_module
from api.services.agent_stream import RateLimitSignal
from api.services.media_ingestor import MediaMeta, PreparedItem, RawItem

AT = "2026-11-24T10:00:00+00:00"
TODAY = date.today().isoformat()
WORDS = "A page about the thing it is titled"


@pytest.fixture(autouse=True)
def _fresh():
    bank_index.invalidate()
    s = sleep_cycle.get_sleep_state()
    s.status, s.drain, s.drain_run, s.cancel_requested = "idle", None, False, False
    registry_module.reset_registry()
    yield
    s.status, s.drain, s.drain_run, s.cancel_requested = "idle", None, False, False
    registry_module.reset_registry()


@pytest.fixture
def legacy(monkeypatch):
    monkeypatch.setattr(history_index, "SAVES_READ", False)


def _save(memory, url, title, *, origin="chrome-bookmark", idx=None, description=WORDS, bulk=False,
          media_type="bookmark", **kw):
    item = RawItem(url=url, title=title, origin=origin, **kw)
    meta = MediaMeta(title=title, description=description, site="example.com", media_type=media_type)
    res = media_ingestor.write_prepared(PreparedItem(item, meta), memory, idx if idx is not None else {}, bulk=bulk)
    bank_index.invalidate()
    return res.episode_id, res.media_entity_id


def _fm(memory, episode_id):
    return markdown_parser.parse(memory / "episodes" / f"{episode_id}.md").frontmatter


def _state(memory, episode_id):
    return history_index.save_state(_fm(memory, episode_id))


# ---- where capture puts a save ---------------------------------------------------------------------------------------


def test_a_save_made_singly_waits_for_sleep_tonight_and_is_in_no_pile(tmp_path):
    memory = _bank(tmp_path)
    ep, page = _save(memory, "https://example.com/a", "A bookmark title")
    fm = _fm(memory, ep)
    assert fm["processed"] is False and "processed_by" not in fm
    assert history_index.save_state(fm) == "waiting" and history_index.kind(fm) is None
    assert history_index.waits_for_model(fm) and not history_index.is_index_only(fm)
    assert (memory / "entities" / f"{page}.md").exists()   # the page is written either way


def test_a_bulk_save_waits_its_turn_in_the_pile_whatever_its_date(tmp_path):
    memory = _bank(tmp_path)
    ep, _ = _save(memory, "https://example.com/a", "A bookmark title", bulk=True)
    fm = _fm(memory, ep)
    assert (fm["processed"], fm["processed_by"]) == (True, "index")
    assert history_index.save_state(fm) == "pile" and history_index.kind(fm) == "saved"
    assert not history_index.waits_for_model(fm)


def test_a_save_received_long_after_it_was_saved_waits_its_turn(tmp_path):
    memory = _bank(tmp_path)
    old = (date.today() - timedelta(days=history_index.LATE_DAYS + 10)).isoformat()
    recent = (date.today() - timedelta(days=history_index.LATE_DAYS - 10)).isoformat()
    a, _ = _save(memory, "https://example.com/old", "An old bookmark", added=old)
    b, _ = _save(memory, "https://example.com/recent", "A recent bookmark", added=recent)
    assert _state(memory, a) == "pile" and _state(memory, b) == "waiting"


def test_a_save_with_his_own_note_or_reason_waits_for_tonight_even_in_a_bulk(tmp_path):
    memory = _bank(tmp_path)
    idx: dict = {}
    why, _ = _save(memory, "https://example.com/b", "Saved with a reason", idx=idx, reason="for the layout", bulk=True)
    note, _ = _save(memory, "https://example.com/c", "Saved with a note", idx=idx, note="check later", bulk=True)
    for eid in (why, note):
        assert _fm(memory, eid)["processed"] is False and _fm(memory, eid)["has_note"] is True
        assert history_index.waits_for_model(_fm(memory, eid))


def test_a_title_and_a_link_on_a_walled_site_has_nothing_to_read_in_a_bulk_or_alone(tmp_path):
    memory = _bank(tmp_path)
    idx: dict = {}
    for n, bulk in enumerate((False, True)):
        ep, _ = _save(memory, f"https://x.com/alpha_user/status/10000000000000000{n}", "Post by @alpha_user", idx=idx,
                      origin="x-bookmarks", folder="Bookmarks", description="", bulk=bulk)
        fm = _fm(memory, ep)
        assert (fm["processed"], fm["processed_by"]) == (True, history_index.NO_WORDS_BY)
        assert history_index.save_state(fm) == "no-words" and history_index.kind(fm) is None
        assert not history_index.waits_for_model(fm) and history_index.not_read(fm)


def test_a_title_only_save_of_a_public_link_takes_its_turn_like_any_save(tmp_path):
    memory = _bank(tmp_path)
    ep, _ = _save(memory, "https://example.com/public", "A public page", description="")
    assert _state(memory, ep) == "waiting"
    pile, _ = _save(memory, "https://example.com/public-2", "Another public page", description="", bulk=True)
    assert _state(memory, pile) == "pile"


@pytest.mark.parametrize("origin, folder, media_type, url", [
    ("github-owned", None, "bookmark", "https://github.com/alpha-org/alpha-project"),
    ("reddit-saved", "Joined communities", "bookmark", "https://www.reddit.com/r/alpha_sub/"),
    ("safari-tab", "A device", "bookmark", "https://example.com/open-tab"),
])
def test_a_record_another_service_keeps_is_index_only_whatever_its_door(tmp_path, origin, folder, media_type, url):
    memory = _bank(tmp_path)
    ep, _ = _save(memory, url, "A record", origin=origin, folder=folder, media_type=media_type)
    fm = _fm(memory, ep)
    assert fm["processed_by"] == "index" and history_index.is_record(fm) and history_index.save_state(fm) == "record"
    assert history_index.is_index_only(fm) and not history_index.not_read(fm)
    # Never released, never woken.
    assert history_index.take_turns(memory).paths == []
    assert history_index.wake(memory, ep, saved_mentions.WHY_LINK, AT) is None


def test_a_feed_item_is_read_as_the_code_reads_it_today(tmp_path):
    memory = _bank(tmp_path)
    item = RawItem(url="https://example.com/feed/1", title="A feed post", origin="rss")
    meta = MediaMeta(title="A feed post", description=WORDS, site="example.com", media_type="article")
    res = media_ingestor.write_prepared(PreparedItem(item, meta), memory, {})
    fm = _fm(memory, res.episode_id)
    assert fm["processed"] is False and history_index.save_state(fm) is None and history_index.waits_for_model(fm)


def _items(n: int, tag: str = "a") -> list[RawItem]:
    return [RawItem(url=f"https://example.com/{tag}/{i}", title=f"Item {i}", origin="chrome-bookmark",
                    defer_enrich=True, preview=WORDS) for i in range(n)]


def _states(memory) -> set[str | None]:
    return {st for f in bank_index.files(memory, "episodes") if (st := history_index.save_state(f.frontmatter))}


def test_a_door_with_more_than_a_few_new_saves_is_a_bulk_and_a_small_one_is_not(tmp_path):
    memory = _bank(tmp_path)
    created, _ = asyncio.run(media_ingestor.ingest_batch(_items(history_index.BULK_ITEMS), memory))
    bank_index.invalidate()
    assert created == history_index.BULK_ITEMS and _states(memory) == {"waiting"}
    memory2 = _bank(tmp_path / "second")
    asyncio.run(media_ingestor.ingest_batch(_items(history_index.BULK_ITEMS + 1), memory2))
    bank_index.invalidate()
    assert _states(memory2) == {"pile"}


def test_an_archive_is_one_bulk_however_its_slices_fall(tmp_path, monkeypatch):
    monkeypatch.setattr(media_ingestor, "MAX_BATCH", 4)
    memory = _bank(tmp_path)
    asyncio.run(media_ingestor.ingest_chunked(_items(history_index.BULK_ITEMS + 3), memory))   # slices of 4, 4, 4, 1
    bank_index.invalidate()
    assert _states(memory) == {"pile"}


def test_a_repeat_read_of_a_list_adds_a_few_and_they_wait_for_tonight(tmp_path):
    memory = _bank(tmp_path)
    idx: dict = {}
    rows = [{"url": f"https://example.com/l/{i}"} for i in range(30)]
    assert media_ingestor.is_bulk(rows, idx)
    for r in rows[:28]:
        _save(memory, r["url"], "Seen", idx=idx, bulk=True)
    # Two rows are new: not a bulk.
    assert not media_ingestor.is_bulk(rows, idx)


def test_the_kill_switch_writes_every_save_index_only_again(tmp_path, legacy):
    memory = _bank(tmp_path)
    ep, _ = _save(memory, "https://example.com/a", "A bookmark title")
    assert _fm(memory, ep)["processed_by"] == "index" and history_index.kind(_fm(memory, ep)) == "saved"
    assert history_index.take_turns(memory).paths == []


# ---- a bank written by today's dev code ------------------------------------------------------------------------------


def test_every_save_a_bank_already_kept_joins_the_pile_with_nothing_else_done(tmp_path, monkeypatch):
    """Dev's capture is the kill switch's: every save stored ``processed: true, processed_by: index``. Nothing is migrated."""
    memory = _bank(tmp_path)
    ids = []
    with monkeypatch.context() as m:
        m.setattr(history_index, "SAVES_READ", False)
        idx: dict = {}
        for n in range(6):
            ids.append(_save(memory, f"https://example.com/k/{n}", f"Kept bookmark {n}", idx=idx,
                             added=(date.today() - timedelta(days=n + 1)).isoformat())[0])
        ids.append(_save(memory, "https://x.com/alpha_user/status/1", "Kept post", origin="x-likes", folder="Likes",
                         idx=idx)[0])
    for eid in ids:
        assert (_fm(memory, eid)["processed"], _fm(memory, eid)["processed_by"]) == (True, "index")
        assert history_index.save_state(_fm(memory, eid)) == "pile"
    assert history_index.turns_due(memory)
    out = history_index.take_turns(memory, per_day=3)
    assert len(out.released) == 3 and out.pile == 7
    for rel in out.released:
        fm = markdown_parser.parse(memory / rel).frontmatter
        assert fm["processed"] is False and "processed_by" not in fm and fm[history_index.TURN_KEY] == TODAY


# ---- the day's number ------------------------------------------------------------------------------------------------


def _pile(memory, n, *, origin="chrome-bookmark", start=0, **kw):
    idx: dict = {}
    out = []
    for i in range(start, start + n):
        out.append(_save(memory, f"https://example.com/p/{origin}/{i}", f"Pile {i}", origin=origin, idx=idx, bulk=True,
                         added=(date.today() - timedelta(days=i % 20 + 1)).isoformat(), **kw)[0])
    return out


def test_take_turns_releases_the_days_number_newest_first_and_only_once_a_day(tmp_path):
    memory = _bank(tmp_path)
    idx: dict = {}
    days = [10, 3, 8, 1, 6, 2]
    ids = [_save(memory, f"https://example.com/d/{d}", f"Dated {d}", idx=idx, bulk=True,
                 added=(date.today() - timedelta(days=d)).isoformat())[0] for d in days]
    first = history_index.take_turns(memory, per_day=3)
    newest = {ids[i] for i in sorted(range(len(days)), key=lambda i: days[i])[:3]}
    assert {p.split("/")[1][:-3] for p in first.released} == newest and first.budget == 3
    bank_index.invalidate()
    again = history_index.take_turns(memory, per_day=3)      # the same day: spent
    assert again.paths == [] and again.budget == 0
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    nxt = history_index.take_turns(memory, per_day=3, today=tomorrow)
    assert len(nxt.released) == 3 and not ({p.split("/")[1][:-3] for p in nxt.released} & newest)


def test_take_turns_skips_a_dirty_file_a_removed_save_and_costs_no_turn_for_nothing_to_read(tmp_path):
    memory = _bank(tmp_path)
    idx: dict = {}
    dirty, _ = _save(memory, "https://example.com/dirty", "Dirty", idx=idx, bulk=True)
    gone, _ = _save(memory, "https://example.com/gone", "Gone", idx=idx, bulk=True)
    parsed = markdown_parser.parse(memory / "episodes" / f"{gone}.md")
    parsed.frontmatter["source_deleted_at"] = AT
    markdown_parser.write(memory / "episodes" / f"{gone}.md", parsed.frontmatter, parsed.body)
    # An older bank's title-only post of a walled site, stored as the index read it.
    empty, _ = _save(memory, "https://x.com/alpha_user/status/9", "Post by @alpha_user", idx=idx, origin="x-likes",
                     folder="Likes", description="", bulk=True)
    parsed = markdown_parser.parse(memory / "episodes" / f"{empty}.md")
    parsed.frontmatter["processed_by"] = "index"
    markdown_parser.write(memory / "episodes" / f"{empty}.md", parsed.frontmatter, parsed.body)
    ok, _ = _save(memory, "https://example.com/ok", "Ok", idx=idx, bulk=True)
    bank_index.invalidate()
    out = history_index.take_turns(memory, skip=frozenset({f"episodes/{dirty}.md"}), per_day=2)
    assert out.released == [f"episodes/{ok}.md"] and out.skipped_dirty == 1
    assert out.emptied == [f"episodes/{empty}.md"] and _state(memory, empty) == "no-words"
    assert _fm(memory, dirty)["processed_by"] == "index" and _fm(memory, gone)["processed_by"] == "index"


def test_a_bulk_list_leaves_sleep_debt_at_most_the_days_number_and_nothing_more_waits_that_day(tmp_path, monkeypatch):
    monkeypatch.setattr(history_index, "SAVES_PER_DAY", 20)
    memory = _bank(tmp_path)
    created, _ = asyncio.run(media_ingestor.ingest_chunked(_items(150, "bulk"), memory))
    bank_index.invalidate()
    assert created == 150
    base = sleep_debt._scan_queue(memory, datetime.now())[0]   # whatever else the bank holds (a conversation)
    assert not any(history_index.waits_for_model(f.frontmatter) for f in bank_index.files(memory, "episodes")
                   if history_index.save_shaped(f.frontmatter)), "a bulk read leaves no save waiting"
    out = history_index.take_turns(memory)
    bank_index.invalidate()
    assert len(out.released) == 20 and sleep_debt._scan_queue(memory, datetime.now())[0] == base + 20
    # Read or not, the number is spent: a second run the same day releases nothing, so no run chains on the pile.
    assert history_index.take_turns(memory).paths == [] and not history_index.turns_due(memory)


def test_a_run_that_only_tidies_releases_nothing(tmp_path, monkeypatch):
    memory = seed_bank(tmp_path, [], extra=lambda m: None)
    _pile(memory, 4)
    git(memory, "add", "-A")
    git(memory, "commit", "-q", "-m", "pile")
    asyncio.run(sleep_cycle._index_without_model_safely(memory, tail_only=True))
    bank_index.invalidate()
    assert _states(memory) == {"pile"}
    asyncio.run(sleep_cycle._index_without_model_safely(memory))
    bank_index.invalidate()
    assert "waiting" in _states(memory)


def test_a_failed_commit_puts_the_release_back(tmp_path, monkeypatch):
    memory = seed_bank(tmp_path, [], extra=lambda m: None)
    _pile(memory, 3)
    git(memory, "add", "-A")
    git(memory, "commit", "-q", "-m", "pile")

    async def refuse(*_a, **_k):
        raise RuntimeError("no commit")

    monkeypatch.setattr("api.services.git_service.commit_paths", refuse)
    asyncio.run(sleep_cycle._index_without_model_safely(memory))
    bank_index.invalidate()
    assert _states(memory) == {"pile"}


def test_the_release_is_a_cicada_commit_that_says_queued(tmp_path):
    memory = seed_bank(tmp_path, [], extra=lambda m: None)
    ids = _pile(memory, 2)
    git(memory, "add", "-A")
    git(memory, "commit", "-q", "-m", "pile")
    asyncio.run(sleep_cycle._index_without_model_safely(memory))
    log = git(memory, "log", "-1", "--format=%s%n%b")
    assert log.startswith("Indexed without a model") and "Cicada-Author: cicada" in log and "Cicada-Engine" not in log
    assert all(f"episodes/{i}.md: queued (source: n/a, trigger: sleep/index)" in log for i in ids)
    assert git(memory, "status", "--porcelain").strip() == ""


def test_the_revert_puts_a_days_unread_release_back_and_keeps_the_day_spent(tmp_path):
    memory = _bank(tmp_path)
    ids = _pile(memory, 3)
    out = history_index.take_turns(memory, per_day=2)
    bank_index.invalidate()
    unread = history_index.released_unread(memory, TODAY)
    assert sorted(unread) == sorted(p.split("/")[1][:-3] for p in out.released)
    back = history_index.return_to_pile(memory, unread)
    assert len(back) == 2
    for eid in unread:
        fm = _fm(memory, eid)
        assert (fm["processed"], fm["processed_by"], fm[history_index.TURN_KEY]) == (True, "index", TODAY)
    bank_index.invalidate()
    assert history_index.take_turns(memory, per_day=2).paths == [], "the day's number stays spent"
    assert ids  # the third never left


def test_the_pile_report_counts_by_origin_and_never_names_a_save(tmp_path):
    memory = _bank(tmp_path)
    _pile(memory, 4, origin="chrome-bookmark")
    idx: dict = {}
    _save(memory, "https://x.com/alpha_user/status/5", "Post", origin="x-likes", folder="Likes", idx=idx, bulk=True)
    empty, _ = _save(memory, "https://x.com/alpha_user/status/6", "Post two", origin="x-likes", folder="Likes", idx=idx,
                     description="", bulk=True)
    parsed = markdown_parser.parse(memory / "episodes" / f"{empty}.md")
    parsed.frontmatter["processed_by"] = "index"
    markdown_parser.write(memory / "episodes" / f"{empty}.md", parsed.frontmatter, parsed.body)
    bank_index.invalidate()
    report = history_index.pile_report(memory)
    assert report["pile"] == 6 and report["pile_nothing_to_read"] == 1 and report["pile_readable"] == 5
    assert report["released_tonight"] == 5 and report["released_tonight_by_origin"] == {"chrome-bookmark": 4, "x-likes": 1}
    assert report["nights_for_the_pile"] == 1 and "example.com" not in json.dumps(report)


# ---- the order ------------------------------------------------------------------------------------------------------


def _put(memory, eid, **fm):
    base = {"id": eid, "timestamp": AT, "processed": False}
    base.update(fm)
    markdown_parser.write(memory / "episodes" / f"{eid}.md", base, fm.pop("_body", "# A title\n\n## Description\nwords"))


def _waiting_save(memory, eid, *, origin="chrome-bookmark", day="2026-11-20", **fm):
    base = {"id": eid, "timestamp": f"{day}T10:00:00+00:00", "processed": False, "source": "bookmark", "origin": origin,
            "url": f"https://example.com/{eid}", "media_entity_id": f"media-{eid}", "title": f"Title {eid}",
            "saved_at": day}
    base.update(fm)
    markdown_parser.write(memory / "episodes" / f"{eid}.md", base, "# A title\n\n## Description\nwords")


def test_conversations_come_first_then_the_saves_he_talked_about_then_the_rest_grouped_by_origin(tmp_path):
    memory = _bank(tmp_path)
    for eid, day in (("ep_2026-11-01_001", "2026-11-01"), ("ep_2026-11-02_001", "2026-11-02")):
        markdown_parser.write(memory / "episodes" / f"{eid}.md",
                              {"id": eid, "timestamp": f"{day}T10:00:00+00:00", "processed": False, "source": "claude-code",
                               "session_id": f"ses_{eid}"}, "user: hello")
    _waiting_save(memory, "ep_2026-11-10_001", origin="chrome-bookmark", day="2026-11-10")
    _waiting_save(memory, "ep_2026-11-12_001", origin="x-likes", folder="Likes", day="2026-11-12")
    _waiting_save(memory, "ep_2026-11-11_001", origin="chrome-bookmark", day="2026-11-11")
    _waiting_save(memory, "ep_2026-11-05_001", origin="chrome-bookmark", day="2026-11-05",
                  read_asked={"why": "said-the-link", "at": AT})
    _waiting_save(memory, "ep_2026-11-06_001", origin="chrome-bookmark", day="2026-11-06", saved_why={"text": "design"})
    # State that is no queue at all: a record, a save with nothing to read, a pile save.
    bank_index.invalidate()
    ids = ["ep_2026-11-01_001", "ep_2026-11-05_001", "ep_2026-11-06_001", "ep_2026-11-10_001", "ep_2026-11-02_001",
           "ep_2026-11-11_001", "ep_2026-11-12_001"]
    ordered, background = saved_order.order(memory, ids)
    assert ordered == ["ep_2026-11-01_001", "ep_2026-11-02_001",                       # conversations, oldest first
                       "ep_2026-11-06_001", "ep_2026-11-05_001",                       # talked about / with his words, newest first
                       "ep_2026-11-12_001",                                            # the origin with the newest save
                       "ep_2026-11-11_001", "ep_2026-11-10_001"]                       # then the other, newest first
    assert sorted(ordered) == sorted(ids), "nothing is cut"
    assert background == {"ep_2026-11-10_001", "ep_2026-11-11_001", "ep_2026-11-12_001"}


def test_sleep_reads_conversations_then_talked_about_saves_then_the_rest_and_decays_before_the_saves(tmp_path, monkeypatch):
    rig = install(monkeypatch)

    def extra(memory):
        for i in range(3):
            eid = f"ep_2026-11-0{i + 1}_001"
            markdown_parser.write(memory / "episodes" / f"{eid}.md",
                                  {"id": eid, "timestamp": f"2026-11-0{i + 1}T10:00:00+00:00", "processed": False,
                                   "source": "mcp", "session_id": f"ses_{eid}"}, "user: a conversation")
        _waiting_save(memory, "ep_2026-11-20_001", day="2026-11-20")
        _waiting_save(memory, "ep_2026-11-21_001", day="2026-11-21", read_asked={"why": "said-the-link", "at": AT})
        _waiting_save(memory, "ep_2026-11-19_001", day="2026-11-19", origin="x-likes", folder="Likes")

    memory = seed_bank(tmp_path, [], extra=extra)
    cfg = settings(memory, sleep_max_episodes_per_cycle=1)   # one to a batch: the batches are the order
    asyncio.run(sleep_cycle.run(cfg, "sleep_order", user_triggered=True, drain=True))
    read = [i for b in rig.extract_batches for i in b]
    assert read == ["ep_2026-11-01_001", "ep_2026-11-02_001", "ep_2026-11-03_001",
                    "ep_2026-11-21_001", "ep_2026-11-20_001", "ep_2026-11-19_001"]
    # Decay and the page reads ran with the batch that left only background saves behind it (the one he talked about), before them.
    assert [c.get("decay", True) for c in rig.prune_calls] == [False, False, False, True, False, False]
    assert rig.link_calls == 1
    assert git(memory, "status", "--porcelain").strip() == ""


def test_a_conversation_that_names_a_waiting_save_moves_it_to_the_front_of_the_saves_and_leaves_the_ask(tmp_path, monkeypatch):
    rig = install(monkeypatch)
    asked: list = []
    monkeypatch.setattr(mention_asks, "offer", lambda memory_path, found: asked.append(dict(found)))

    def extra(memory):
        markdown_parser.write(memory / "episodes" / "ep_2026-11-01_001.md",
                              {"id": "ep_2026-11-01_001", "timestamp": "2026-11-01T10:00:00+00:00", "processed": False,
                               "source": "claude-code", "session_id": "ses_one"},
                              "user: I keep coming back to https://x.com/alpha_user/status/777")
        _waiting_save(memory, "ep_2026-11-21_001", day="2026-11-21")
        _waiting_save(memory, "ep_2026-11-22_001", day="2026-11-22")
        _waiting_save(memory, "ep_2026-11-10_001", day="2026-11-10", origin="x-bookmarks", folder="Bookmarks",
                      url="https://x.com/alpha_user/status/777")

    memory = seed_bank(tmp_path, [], extra=extra)
    asyncio.run(sleep_cycle.run(settings(memory, sleep_max_episodes_per_cycle=1), "sleep_front", user_triggered=True,
                                drain=True))
    read = [i for b in rig.extract_batches for i in b]
    assert read == ["ep_2026-11-01_001", "ep_2026-11-10_001", "ep_2026-11-22_001", "ep_2026-11-21_001"]
    assert asked and "ep_2026-11-10_001" in asked[0]


# ---- a night that ends at a line he set ----------------------------------------------------------------------------


def _future() -> int:
    return int(time.time()) + 3600


def _signal(util):
    return RateLimitSignal(status="allowed", limit_type="five_hour", utilization=util, resets_at=_future())


def _reserve(pct):
    from api.services import sleep_run_prefs

    sleep_run_prefs.write(registry_module.get_registry(Settings()), reserve_pct=pct)


def _release(memory, eid, day="2026-11-20", **fm):
    _waiting_save(memory, eid, day=day, **{history_index.TURN_KEY: TODAY, **fm})


def _run(memory, cid="sleep_line", cap=2):
    cfg = Settings(CICADA_MEMORY_PATH=memory, sleep_max_episodes_per_cycle=cap, link_enrich_enabled=False)
    asyncio.run(sleep_cycle.run(cfg, cid, user_triggered=False, drain=True))
    return sleep_cycle.get_sleep_state()


def test_a_line_reached_with_only_background_saves_left_finishes_the_night_and_blocks_no_other(tmp_path, monkeypatch):
    rig = install(monkeypatch, engine_label="claude-cli")
    _reserve(10)

    def extra(memory):
        for i in (1, 2):
            eid = f"ep_2026-11-0{i}_001"
            markdown_parser.write(memory / "episodes" / f"{eid}.md",
                                  {"id": eid, "timestamp": f"2026-11-0{i}T10:00:00+00:00", "processed": False,
                                   "source": "mcp", "session_id": f"ses_{eid}"}, "user: a conversation")
        for n in range(4):
            _release(memory, f"ep_2026-11-2{n}_001", day=f"2026-11-2{n}")

    memory = seed_bank(tmp_path, [], extra=extra)
    rig.after_read = lambda ep: sleep_cycle.get_sleep_state().drain.guard.observe_signals([_signal(0.99)]) \
        if ep["id"] == "ep_2026-11-22_001" else None   # the window is full once the first save of the batch is read
    state = _run(memory)
    ds = state.drain
    # Both conversations and the first save are filed; the rest of the day's release goes back to the pile.
    assert [is_processed(memory, i) for i in ("ep_2026-11-01_001", "ep_2026-11-02_001", "ep_2026-11-22_001")] == [True] * 3
    assert ds.stop is None, "a finished night, not a pause"
    back = [f"ep_2026-11-2{n}_001" for n in (0, 1, 3)]
    for eid in back:
        fm = markdown_parser.parse(memory / "episodes" / f"{eid}.md").frontmatter
        assert (fm["processed"], fm["processed_by"], fm[history_index.TURN_KEY]) == (True, "index", TODAY)
        assert history_index.save_state(fm) == "pile"
    # No pause record: tomorrow's run is not blocked, through the scheduler's own predicate and its replace rule.
    assert sleep_paused.get_paused(memory) is None and not sleep_scheduler._paused_for_the_person(memory)
    assert "links" not in rig.tail, "a night that stopped at its line reads no page"
    assert git(memory, "status", "--porcelain").strip() == ""
    # The day's number stays spent: no second release today.
    assert history_index.take_turns(memory).paths == []


def test_a_line_reached_with_a_conversation_left_pauses_as_it_always_did(tmp_path, monkeypatch):
    rig = install(monkeypatch, engine_label="claude-cli")
    _reserve(10)

    def extra(memory):
        for i in range(1, 5):
            eid = f"ep_2026-11-0{i}_001"
            markdown_parser.write(memory / "episodes" / f"{eid}.md",
                                  {"id": eid, "timestamp": f"2026-11-0{i}T10:00:00+00:00", "processed": False,
                                   "source": "mcp", "session_id": f"ses_{eid}"}, "user: a conversation")
        _release(memory, "ep_2026-11-20_001")

    memory = seed_bank(tmp_path, [], extra=extra)
    rig.after_read = lambda ep: sleep_cycle.get_sleep_state().drain.guard.observe_signals([_signal(0.99)]) \
        if ep["id"] == "ep_2026-11-01_001" else None
    state = _run(memory)
    assert state.drain.stop.reason == "reserve"
    rec = sleep_paused.get_paused(memory)
    assert rec["reason"] == "reserve" and rec["started_by"] == "schedule"
    assert sleep_scheduler._paused_for_the_person(memory) and not sleep_paused.schedule_may_replace(rec)
    # The save is still queued: nothing was put back, because a conversation was left.
    assert not is_processed(memory, "ep_2026-11-20_001")


def test_a_plan_window_reached_with_only_background_saves_left_finishes_the_night_too(tmp_path, monkeypatch):
    from api.services import agent_engine, engine_errors

    rig = install(monkeypatch)

    def extra(memory):
        markdown_parser.write(memory / "episodes" / "ep_2026-11-01_001.md",
                              {"id": "ep_2026-11-01_001", "timestamp": "2026-11-01T10:00:00+00:00", "processed": False,
                               "source": "mcp", "session_id": "ses_one"}, "user: a conversation")
        for n in range(4):
            _release(memory, f"ep_2026-11-2{n}_001", day=f"2026-11-2{n}")

    memory = seed_bank(tmp_path, [], extra=extra)
    from api.services import entity_resolver
    real = entity_resolver.resolve
    calls = {"n": 0}

    async def resolve_then_throttle(extracted, existing, settings_, cancel_check=None, **kw):
        calls["n"] += 1
        if calls["n"] == 2:
            agent_engine.trip_breaker("the plan's window is full", resets_at=1790000000)
            raise engine_errors.EngineThrottled("throttled", resets_at=1790000000)
        return await real(extracted, existing, settings_, cancel_check=cancel_check, **kw)

    monkeypatch.setattr("api.services.entity_resolver.resolve", resolve_then_throttle)
    state = _run(memory, cap=1)
    assert state.drain.stop is None, "every conversation was filed: a limit reached inside the saves is a finished night"
    assert is_processed(memory, "ep_2026-11-01_001") and sleep_paused.get_paused(memory) is None
    assert not sleep_scheduler._paused_for_the_person(memory)
    unread = [f"ep_2026-11-2{n}_001" for n in range(4) if not is_processed(memory, f"ep_2026-11-2{n}_001")]
    assert unread == []   # the tripped save is put back in the pile, which is processed: true, by the index
    assert any(history_index.in_pile(_fm(memory, f"ep_2026-11-2{n}_001")) for n in range(4))
    assert rig.tail.count("links") == 0


def test_a_plan_window_with_a_conversation_left_is_a_pause_the_scheduler_will_not_replace(tmp_path, monkeypatch):
    from api.services import agent_engine, engine_errors

    install(monkeypatch)

    def extra(memory):
        for i in range(1, 4):
            eid = f"ep_2026-11-0{i}_001"
            markdown_parser.write(memory / "episodes" / f"{eid}.md",
                                  {"id": eid, "timestamp": f"2026-11-0{i}T10:00:00+00:00", "processed": False,
                                   "source": "mcp", "session_id": f"ses_{eid}"}, "user: a conversation")
        _release(memory, "ep_2026-11-20_001")

    memory = seed_bank(tmp_path, [], extra=extra)
    from api.services import entity_resolver
    real = entity_resolver.resolve
    calls = {"n": 0}

    async def resolve_then_throttle(extracted, existing, settings_, cancel_check=None, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            agent_engine.trip_breaker("the plan's window is full", resets_at=int(time.time()) + 3600)
            raise engine_errors.EngineThrottled("throttled", resets_at=int(time.time()) + 3600)
        return await real(extracted, existing, settings_, cancel_check=cancel_check, **kw)

    monkeypatch.setattr("api.services.entity_resolver.resolve", resolve_then_throttle)
    state = _run(memory, cap=1)
    assert state.drain.stop.reason == "plan_limit"
    rec = sleep_paused.get_paused(memory)
    assert rec["reason"] in ("plan_window", "plan_weekly") and not sleep_paused.schedule_may_replace(rec)


# ---- what Stage 1 reads ---------------------------------------------------------------------------------------------


def _resp(content: str):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def _extract(episode: dict):
    seen: list[str] = []

    async def fake(**kw):
        seen.append(kw["messages"][1]["content"])
        return _resp(json.dumps({"entities": [], "relationships": []}))

    async def no_sleep(*_a, **_k):
        return None

    with patch.object(providers, "resolve_llm_fn", lambda *a, **k: fake), \
            patch.object(entity_extractor.asyncio, "sleep", no_sleep), \
            patch.object(owner_identity, "owner_name", lambda *a, **k: "Alpha Owner"):
        out = asyncio.run(entity_extractor.extract([dict(episode)], Settings(_env_file=None), today=date(2026, 11, 24)))
    return out, seen


def _episode(body: str, **extra) -> dict:
    fm = {"id": "ep_2026-11-20_001", "source": "bookmark", "origin": "chrome-bookmark", "url": "https://example.com/a",
          "media_entity_id": "media-a", "timestamp": "2026-11-20T10:00:00+00:00", **extra}
    return {"id": fm["id"], "content": body, "timestamp": fm["timestamp"], "origin": fm["origin"], "source": fm["source"],
            "url": fm["url"], authorship.KEY: authorship.of(fm), **extra}


TITLE_ONLY = "# A page\n\n**Source:** bookmark\n**URL:** https://example.com/a\n**Site:** example.com\n**Saved:** 2026-11-20"


def test_a_save_that_holds_a_title_and_a_link_is_sent_to_no_model_and_filed_with_nothing():
    out, seen = _extract(_episode(TITLE_ONLY))
    assert seen == [] and [r["entities"] for r in out] == [[]] and out[0]["episode_id"] == "ep_2026-11-20_001"


def test_a_save_with_words_is_read_and_so_is_one_with_a_folders_reason_and_a_tab_group():
    _, seen = _extract(_episode(TITLE_ONLY + "\n\n## Description\nA page about a thing."))
    assert len(seen) == 1
    _, seen = _extract(_episode(TITLE_ONLY, readable_by_folder={"at": AT, "folders": ["Design"]}))
    assert len(seen) == 1
    _, seen = _extract(_episode("# Tab group: A\n\n- A tab — https://example.com/a", source="tab-group"))
    assert len(seen) == 1


# ---- talking about a save --------------------------------------------------------------------------------------------


def _list_save(memory, url, title, *, origin="x-bookmarks", folder="Bookmarks", **kw):
    return _save(memory, url, title, origin=origin, folder=folder, media_type="bookmark", **kw)[0]


def test_talking_about_a_save_wakes_the_pile_moves_a_waiting_one_and_leaves_only_the_ask_for_the_rest(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    idx: dict = {}
    urls = {k: f"https://x.com/alpha_user/status/{n}" for n, k in enumerate(("waiting", "pile", "read", "empty"), start=1)}
    ids = {
        "waiting": _list_save(memory, urls["waiting"], "Waiting post", idx=idx),
        "pile": _list_save(memory, urls["pile"], "Pile post", idx=idx, bulk=True),
        "read": _list_save(memory, urls["read"], "Read post", idx=idx),
        "empty": _list_save(memory, urls["empty"], "Empty post", idx=idx, description=""),
    }
    parsed = markdown_parser.parse(memory / "episodes" / f"{ids['read']}.md")
    parsed.frontmatter.update(processed=True, processed_by="sleep")
    markdown_parser.write(memory / "episodes" / f"{ids['read']}.md", parsed.frontmatter, parsed.body)
    bank_index.invalidate()
    assert {k: _state(memory, v) for k, v in ids.items()} == {"waiting": "waiting", "pile": "pile", "read": "read",
                                                              "empty": "no-words"}
    asked: list = []
    monkeypatch.setattr(mention_asks, "offer", lambda memory_path, found: asked.append(dict(found)))
    said = {"id": "ep_2026-11-24_901", "content": "user: look at " + " ".join(urls.values()), "origin": "claude-code",
            "filepath": memory / "episodes" / "x.md", "gaps": ()}
    paths = saved_mentions.wake_mentioned(memory, [said], at=AT)
    bank_index.invalidate()
    # Every one is MARKED as named (G246 Track M: the mark that keeps a post's page); only the first two are woken.
    assert sorted(paths) == sorted(f"episodes/{i}.md" for i in ids.values())
    waiting, pile = _fm(memory, ids["waiting"]), _fm(memory, ids["pile"])
    assert waiting["read_asked"]["why"] == saved_mentions.WHY_LINK and waiting["processed"] is False
    assert pile["read_asked"]["why"] == saved_mentions.WHY_LINK and pile["processed"] is False and "processed_by" not in pile
    assert saved_order.classify(waiting) == saved_order.TALKED and saved_order.classify(pile) == saved_order.TALKED
    assert _state(memory, ids["read"]) == "read" and "read_asked" not in _fm(memory, ids["read"])
    assert (_fm(memory, ids["empty"])["processed_by"], "read_asked" in _fm(memory, ids["empty"])) == ("no-words", False)
    assert all(_fm(memory, i)["named"]["why"] == saved_mentions.WHY_LINK for i in ids.values())
    # Every one of them still leaves the ask for his own agent: it never depended on the save being unread.
    assert set(asked[0]) == set(ids.values())


# ---- found, whatever its state ---------------------------------------------------------------------------------------


def test_every_state_of_a_save_is_found_by_its_words_and_says_whether_anyone_read_it(tmp_path):
    memory = _bank(tmp_path)
    idx: dict = {}
    a, pa = _save(memory, "https://example.com/waiting", "Quokka habitat restoration guide", idx=idx)
    b, pb = _save(memory, "https://example.com/pile", "Lichen taxonomy field handbook", idx=idx, bulk=True)
    c, pc = _save(memory, "https://example.com/empty", "Basalt column geology notes", idx=idx, description="", media_type="youtube")
    d, pd = _save(memory, "https://example.com/read", "Zeppelin mooring mast history", idx=idx)
    parsed = markdown_parser.parse(memory / "episodes" / f"{d}.md")
    parsed.frontmatter.update(processed=True, processed_by="sleep")
    markdown_parser.write(memory / "episodes" / f"{d}.md", parsed.frontmatter, parsed.body)
    bank_index.invalidate()
    search_index.refresh(memory)
    states = {a: "waiting", b: "pile", c: "no-words", d: "read"}
    assert {k: _state(memory, k) for k in states} == states
    for query, page, unread in (("quokka habitat restoration", pa, True), ("lichen taxonomy field", pb, True),
                                ("basalt column geology", pc, True), ("zeppelin mooring mast", pd, False)):
        hits = saved_lookup.find(memory, query, min_shared=1)
        assert [h.page for h in hits] == [page], query
        assert hits[0].read is not unread, query
    # A tab group waiting for tonight is found as one in the pile is.
    from api.services import tab_groups

    tab_groups.sync(memory, {"browser": "chrome", "profile": "Default", "groups": [
        {"title": "Espresso research", "color": "blue", "saved_guid": "g1",
         "tabs": [{"title": "Grind size notes", "url": "https://example.com/espresso/grind"}]}]})
    bank_index.invalidate()
    search_index.refresh(memory)
    assert [h.episode for h in saved_lookup.find(memory, "espresso grind research", episodes=True)]


# ---- the two scripts ------------------------------------------------------------------------------------------------


def test_the_dry_run_prints_counts_by_origin_and_writes_nothing(tmp_path, capsys):
    from api.scripts import history_index_dry_run

    memory = _bank(tmp_path)
    _pile(memory, 3, origin="chrome-bookmark")
    _save(memory, "https://example.com/single", "A single save")
    before = {p: p.read_bytes() for p in (memory / "episodes").glob("*.md")}
    assert history_index_dry_run.main(["--bank", str(memory)]) == 0
    out = capsys.readouterr().out
    saves = json.loads(out)["saves"]
    assert saves["per_day"] == history_index.SAVES_PER_DAY and saves["saves_by_state"] == {"pile": 3, "waiting": 1}
    assert saves["released_tonight"] == 3 and saves["released_tonight_by_origin"] == {"chrome-bookmark": 3}
    assert saves["nights_for_the_pile"] == 1 and "example.com" not in out and "Pile 0" not in out
    assert {p: p.read_bytes() for p in (memory / "episodes").glob("*.md")} == before


def test_the_night_report_has_ids_and_enums_and_never_a_title_or_a_word(tmp_path, capsys):
    from api.scripts import saves_night_report

    memory = _bank(tmp_path)
    ids = _pile(memory, 2)
    history_index.take_turns(memory, per_day=1)
    bank_index.invalidate()
    single, _ = _save(memory, "https://example.com/single-report", "A report title")
    assert saves_night_report.main(["--bank", str(memory), "--day", TODAY]) == 0
    out = capsys.readouterr().out
    report = json.loads(out)
    rows = {r["episode"]: r for r in report["saves"]}
    assert report["totals"]["saves"] == 2 and report["totals"]["by_reach"] == {"pile": 1, "single": 1}
    released = [i for i in ids if rows.get(i, {}).get("reached") == "pile"]
    assert len(released) == 1 and rows[single]["reached"] == "single" and rows[single]["state"] == "waiting"
    assert report["totals"]["on_the_owners_page"] == 0
    assert "A report title" not in out and "example.com" not in out and "Pile" not in out
    assert saves_night_report.main(["--bank", str(tmp_path / "nowhere")]) == 2
