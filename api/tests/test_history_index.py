"""Watch history and export saves are indexed, not consolidated (owner ruling 2026-10-18; G71, G94).

A watched day, a month's summary and a save from a platform's saved list are read without a model: capture writes
them already read (``processed_by: index``), Sleep retires the ones an older bank queued before a drain freezes its
ids, no model batch ever sees one, and a channel page gains a derived line that is never a mention. Synthetic banks,
placeholder titles and channels only."""
from __future__ import annotations

import asyncio
import json
import subprocess
import time
from datetime import date

import pytest

from _synthetic_bank import _bank, _entity
from drain_harness import git, install, seed_bank, settings

from api.services import (bank_index, change_timeline, history_index, markdown_parser, media_ingestor, sleep_cycle,
                          sleep_progress, watch_history)
from api.services.media_ingestor import MediaMeta, PreparedItem, RawItem

VID = ["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc", "ddddddddddd"]


@pytest.fixture(autouse=True)
def utc(monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    bank_index.invalidate()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.fixture(autouse=True)
def _idle_state():
    s = sleep_cycle.get_sleep_state()
    s.status, s.drain, s.drain_run, s.cancel_requested = "idle", None, False, False
    yield
    s.status, s.drain, s.drain_run, s.cancel_requested = "idle", None, False, False


def _w(vid, *, at=None, day=None, title="A talk", channel="alice-example"):
    return watch_history.make(f"https://www.youtube.com/watch?v={vid}", at=at, day=day, title=title,
                              channel=channel, door="takeout")


def _episodes(memory) -> dict[str, markdown_parser.ParsedFile]:
    return {p.stem: markdown_parser.parse(p) for p in sorted((memory / "episodes").glob("*.md"))}


def _by_source(memory, prefix: str) -> dict[str, markdown_parser.ParsedFile]:
    return {str(e.frontmatter.get("source_id")): e for e in _episodes(memory).values()
            if str(e.frontmatter.get("source_id") or "").startswith(prefix)}


# --- the one predicate -----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("fm, kind", [
    ({"source": "watch-history", "source_id": "watch-history:youtube:2026-09-01"}, "history"),
    ({"source": "watch-history-month", "source_id": "watch-history-month:youtube:2026-09"}, "month"),
    ({"source": "youtube", "origin": "youtube-playlist", "folder": "Watch later"}, "list"),
    ({"source": "youtube", "origin": "youtube-playlist", "folder": "Talks to keep"}, "list"),
    ({"source": "instagram", "origin": "instagram-saved"}, "list"),
    ({"source": "web", "origin": "tiktok-saved"}, "list"),
    ({"source": "web", "origin": "x-likes", "folder": "Likes"}, "list"),
    ({"source": "web", "origin": "linkedin-saved"}, "list"),
    ({"source": "web", "origin": "reddit-saved", "folder": "Saved posts"}, "list"),
    ({"source": "web", "origin": "x-bookmarks", "folder": "Bookmarks"}, "list"),
    # A connector poll shares the origin, never the export reader's folder: read as today.
    ({"source": "web", "origin": "reddit-saved", "folder": "r/example"}, None),
    ({"source": "web", "origin": "x-bookmarks"}, None),
    # A browser bookmark, a single save, a conversation: read as today.
    ({"source": "web", "origin": "chrome-bookmark"}, None),
    ({"source": "web", "origin": "saved-link"}, None),
    ({"source": "mcp", "session_id": "ses_x"}, None),
    # A list save carrying the person's own words is read.
    ({"source": "youtube", "origin": "youtube-playlist", "has_note": True}, None),
])
def test_what_is_index_only(fm, kind):
    assert history_index.kind(fm) == kind
    assert history_index.waits_for_model({**fm, "processed": False}) is (kind is None)
    assert history_index.waits_for_model({**fm, "processed": True}) is False


def test_no_list_door_carries_the_persons_words():
    """The invariant the predicate rests on: an export or list parser never sets a note or a reason."""
    from api.services import saved_exports

    csv = "Video ID,Playlist Video Creation Timestamp\naaaaaaaaaaa,2026-09-01T10:00:00+00:00\n".encode()
    items = media_ingestor.parse_youtube_playlist_csv(csv, "Watch later-videos.csv")
    items += media_ingestor.parse_reddit_saved_csv(b"id,permalink\n1,/r/x/comments/1/a/\n", "saved_posts.csv")
    items += saved_exports.parse_x_archive_js(
        b'window.YTD.like.part0 = [{"like": {"tweetId": "123", "fullText": "words"}}]', "like")
    assert items and all(not i.note and not i.reason for i in items)
    assert all(history_index.kind({"origin": i.origin, "folder": i.folder}) == "list" for i in items)


# --- capture: written already read ------------------------------------------------------------------------------------


def test_a_watched_day_and_its_month_land_read_by_the_index(tmp_path):
    memory = _bank(tmp_path)
    result = watch_history.record(memory, [
        _w(VID[0], at="2026-09-01T09:00:00Z", title="Bridges, part one"),
        _w(VID[1], at="2026-09-01T10:00:00Z", title="Knots", channel="bob-example"),
        _w(VID[0], at="2026-09-09T20:00:00Z", title="Bridges, part one"),          # another week, another day
        _w(VID[2], at="2026-10-02T08:00:00Z", title="Ropes"),
    ])
    days = _by_source(memory, "watch-history:")
    months = _by_source(memory, "watch-history-month:")
    assert len(days) == 3 and set(months) == {"watch-history-month:youtube:2026-09",
                                              "watch-history-month:youtube:2026-10"}
    for e in [*days.values(), *months.values()]:
        assert e.frontmatter["processed"] is True and e.frontmatter["processed_by"] == "index"
    sept = months["watch-history-month:youtube:2026-09"]
    assert sept.frontmatter["source"] == "watch-history-month" and sept.frontmatter["videos"] == 3
    assert sept.frontmatter["id"].startswith("ep_2026-09-09_")
    body = sept.body
    assert body.startswith("# Watched on YouTube · September 2026")
    assert "3 videos watched on YouTube over 2 days in September 2026 (2 different)" in body
    assert "## Channels watched most\n- alice-example — 2 videos on 2 days\n- bob-example — 1 video on 1 day" in body
    assert "## Came back to across weeks\n- alice-example — in 2 different weeks" in body
    assert "## Watched on more than one day\n- Bridges, part one — alice-example · 2 days: 2026-09-01, 2026-09-09" in body
    assert "- 2026-09-01 Tuesday · 2 videos" in body
    assert sorted(result.paths) == sorted({f"episodes/{p.name}" for p in (memory / "episodes").glob("ep_2026-*")
                                           if p.stem not in ("ep_2026-09-01_001", "ep_2026-09-02_001")})
    # Nothing new waits for a model: only the fixture's own conversation does.
    assert [e["id"] for e in sleep_cycle._get_unprocessed_episodes(memory)] == ["ep_2026-09-01_001"]
    # A re-read writes nothing, the summary included.
    again = watch_history.record(memory, [_w(VID[2], at="2026-10-02T08:00:00Z", title="Ropes")])
    assert again.paths == []


def test_the_month_summary_is_the_same_whichever_order_the_days_arrive(tmp_path):
    a, b = _bank(tmp_path / "a"), _bank(tmp_path / "b")
    one = _w(VID[0], at="2026-09-01T09:00:00Z")
    two = _w(VID[1], at="2026-09-20T09:00:00Z", channel="bob-example")
    watch_history.record(a, [one])
    watch_history.record(a, [two])
    watch_history.record(b, [two, one])
    key = "watch-history-month:youtube:2026-09"
    assert _by_source(a, key)[key].body == _by_source(b, key)[key].body


def test_a_list_save_lands_read_and_a_single_save_or_a_noted_one_waits(tmp_path):
    memory = _bank(tmp_path)
    idx: dict = {}

    def save(url, origin, **kw):
        item = RawItem(url=url, title="A video", folder=kw.pop("folder", None), origin=origin, **kw)
        meta = MediaMeta(title="A video", description="", site="youtube.com", media_type="youtube")
        res = media_ingestor.write_prepared(PreparedItem(item, meta), memory, idx)
        return markdown_parser.parse(memory / "episodes" / f"{res.episode_id}.md").frontmatter

    listed = save(f"https://www.youtube.com/watch?v={VID[0]}", "youtube-playlist", folder="Watch later")
    assert (listed["processed"], listed["processed_by"]) == (True, "index")
    single = save(f"https://www.youtube.com/watch?v={VID[1]}", "saved-link")
    assert single["processed"] is False and "processed_by" not in single
    noted = save(f"https://www.youtube.com/watch?v={VID[2]}", "youtube-playlist", note="watch for the ending")
    assert noted["processed"] is False and noted["has_note"] is True
    assert history_index.waits_for_model(noted) is True
    # The media page is written either way: the save stays in Saved with its metadata.
    assert len(list((memory / "entities").glob("media-*.md"))) == 3


# --- an older bank: Sleep retires what it queued ----------------------------------------------------------------------


def _legacy(memory):
    """What a bank that imported before the ruling holds: a watched day, a playlist save and a Reddit export save,
    all queued; a Reddit connector save and a conversation, queued and read by the model as before."""
    def ep(eid, fm, body="- 09:00 · A talk — alice-example"):
        markdown_parser.write(memory / "episodes" / f"{eid}.md",
                              {"id": eid, "timestamp": f"{eid[3:13]}T09:00:00+00:00", "processed": False, **fm},
                              body)
    rows = [{"url": f"https://www.youtube.com/watch?v={VID[0]}", "title": "A talk", "channel": "alice-example",
             "times": ["2026-08-03T09:00:00+00:00"], "via": ["takeout"], "seen": ["2026-08-03T09:00:00+00:00"]}]
    ep("ep_2026-08-03_001", {"source": "watch-history", "origin": "youtube-history",
                             "source_id": "watch-history:youtube:2026-08-03", "platform": "youtube",
                             "watched_on": "2026-08-03", "videos": 1, "watched": rows})
    ep("ep_2026-08-04_001", {"source": "youtube", "origin": "youtube-playlist", "folder": "Watch later"})
    ep("ep_2026-08-04_002", {"source": "web", "origin": "reddit-saved", "folder": "Saved posts"})
    ep("ep_2026-08-04_003", {"source": "web", "origin": "reddit-saved", "folder": "r/example"})


def test_the_dry_run_counts_and_writes_nothing(tmp_path, capsys):
    from api.scripts import history_index_dry_run

    memory = _bank(tmp_path)
    _legacy(memory)
    git(memory, "add", "-A")
    git(memory, "commit", "-q", "-m", "legacy import")
    before = git(memory, "status", "--porcelain")
    assert history_index_dry_run.main(["--bank", str(memory)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["waiting"] == 5 and out["for_model"] == 2 and out["index_only_queued"] == 3
    assert out["index_only_by_kind"] == {"history": 1, "list": 2}
    assert out["index_only_by_origin"] == {"reddit-saved": 1, "youtube-history": 1, "youtube-playlist": 1}
    assert (out["months_in_history"], out["month_summaries"]) == (1, 0)
    assert git(memory, "status", "--porcelain") == before
    assert history_index_dry_run.main(["--bank", str(tmp_path / "nowhere")]) == 2


def test_waiting_counts_never_include_index_only_episodes(tmp_path):
    memory = _bank(tmp_path)
    _legacy(memory)
    want = {"ep_2026-09-01_001", "ep_2026-08-04_003"}
    assert {e["id"] for e in sleep_cycle._get_unprocessed_episodes(memory)} == want
    assert set(sleep_progress.unprocessed_ids(memory)) == want
    from datetime import datetime

    from api.services import sleep_debt, sleep_paused

    assert sleep_debt._scan_queue(memory, datetime.now())[0] == 2
    assert sleep_paused.remaining_ids(memory, {"frozen_ids": ["ep_2026-08-03_001", "ep_2026-08-04_003"]}) == [
        "ep_2026-08-04_003"]


def test_retire_marks_read_under_the_lock_and_skips_a_dirty_file(tmp_path):
    memory = _bank(tmp_path)
    _legacy(memory)
    out = history_index.retire(memory, skip=frozenset({"episodes/ep_2026-08-04_002.md"}))
    assert sorted(out.paths) == ["episodes/ep_2026-08-03_001.md", "episodes/ep_2026-08-04_001.md"]
    assert out.skipped_dirty == 1 and dict(out.by_kind) == {"history": 1, "list": 1}
    eps = _episodes(memory)
    assert eps["ep_2026-08-03_001"].frontmatter["processed_by"] == "index"
    assert eps["ep_2026-08-04_002"].frontmatter["processed"] is False      # left for its own writer's commit
    assert eps["ep_2026-08-04_003"].frontmatter["processed"] is False      # the connector's save: the model's
    assert eps["ep_2026-08-03_001"].body == "- 09:00 · A talk — alice-example"


def test_a_drain_never_hands_an_index_only_episode_to_the_model(tmp_path, monkeypatch):
    rig = install(monkeypatch)
    memory = seed_bank(tmp_path, ["ep_2026-09-01_000", "ep_2026-09-01_001"], extra=_legacy)
    asyncio.run(sleep_cycle.run(settings(memory, sleep_max_episodes_per_cycle=25), "sleep_hist",
                                user_triggered=True, drain=True))
    read = [i for batch in rig.extract_batches for i in batch]
    assert sorted(read) == ["ep_2026-08-04_003", "ep_2026-09-01_000", "ep_2026-09-01_001"]
    eps = _episodes(memory)
    for eid in ("ep_2026-08-03_001", "ep_2026-08-04_001", "ep_2026-08-04_002"):
        assert eps[eid].frontmatter["processed"] is True and eps[eid].frontmatter["processed_by"] == "index"
    month = _by_source(memory, "watch-history-month:")
    assert list(month) == ["watch-history-month:youtube:2026-08"]
    assert month["watch-history-month:youtube:2026-08"].frontmatter["processed_by"] == "index"
    # Its own commit, under Cicada's name, no engine trailer; the drain's progress never counted them.
    log = git(memory, "log", "--format=%s%n%b%x00")
    entry = next(c for c in log.split("\x00") if c.strip().startswith("Indexed without a model"))
    assert "Cicada-Author: cicada" in entry and "Cicada-Engine" not in entry
    assert "episodes/ep_2026-08-03_001.md: indexed (source: n/a, trigger: sleep/index)" in entry
    ds = sleep_cycle.get_sleep_state().drain
    assert ds is not None and ds.frozen == 3
    assert git(memory, "status", "--porcelain").strip() == ""


# --- found by lookup -------------------------------------------------------------------------------------------------


def test_the_timeline_counts_what_was_watched_on_its_day(tmp_path):
    memory = _bank(tmp_path)
    watch_history.record(memory, [_w(VID[0], at="2026-09-01T09:00:00Z"), _w(VID[1], at="2026-09-01T10:00:00Z")])
    days = change_timeline.collect(memory, date(2026, 8, 30), date(2026, 9, 3), git_log=lambda *a: "")
    sept1 = next(d for d in days if d.day == date(2026, 9, 1))
    assert sept1.watched == {"youtube": 2}
    assert "youtube-history" not in sept1.captured
    text = change_timeline.render(days, date(2026, 8, 30), date(2026, 9, 3))
    assert "- Watched 2 video(s) on YouTube" in text


def test_a_channel_page_gains_a_derived_line_and_nothing_is_written(tmp_path):
    from api.services import mcp_tools

    memory = _bank(tmp_path)
    _entity(memory, "alice-channel", name="Alice Channel", type="company", aliases=["alice-example"])
    page = (memory / "entities" / "alice-channel.md").read_bytes()
    watch_history.record(memory, [_w(VID[0], at="2026-09-01T09:00:00Z"), _w(VID[1], at="2026-09-20T09:00:00Z")])
    line = watch_history.channel_line(memory, ["Alice Channel", "ALICE-example "])
    assert line.startswith("**Watch history:** 2 videos from a YouTube channel named alice-example, on 2 days, "
                           "2026-09-01 to 2026-09-20")
    assert "not a mention" in line
    assert watch_history.channel_line(memory, ["alice"]) is None                 # never fuzzy
    ctx = mcp_tools.ToolContext(memory_path=lambda: memory, session_id="ses_h", harness="claude-code")
    text = str(mcp_tools.recall_detail(ctx, "alice-channel"))
    assert "**Watch history:** 2 videos" in text
    assert (memory / "entities" / "alice-channel.md").read_bytes() == page
    assert "**Watch history:**" not in str(mcp_tools.recall_detail(ctx, "bob-example"))


def test_the_tail_embeds_indexed_episodes_written_after_the_vector_index(tmp_path, monkeypatch):
    import os

    from api.services import vector_index

    calls: list[str] = []
    monkeypatch.setattr(vector_index.SqliteVecIndexer, "index_episodes", lambda self: calls.append("episodes") or 0)
    memory = _bank(tmp_path)
    asyncio.run(sleep_cycle._embed_indexed_episodes_safely(memory))
    assert calls == []                                          # no vector index yet: its first sync is Sleep's
    db = memory / vector_index.INDEX_DB_FILE
    db.write_bytes(b"")
    os.utime(db, ns=(1, 1))
    watch_history.record(memory, [_w(VID[0], at="2026-09-01T09:00:00Z")])
    bank_index.invalidate()
    asyncio.run(sleep_cycle._embed_indexed_episodes_safely(memory))
    assert calls == ["episodes"]
    os.utime(db, None)                                          # synced since: nothing newer, nothing to do
    asyncio.run(sleep_cycle._embed_indexed_episodes_safely(memory))
    assert calls == ["episodes"]


def test_a_question_about_watching_is_looked_up_without_a_model(tmp_path):
    memory = _bank(tmp_path)
    watch_history.record(memory, [
        _w(VID[0], at="2026-09-01T09:14:00Z", title="Bridge design, part one"),
        _w(VID[1], at="2026-09-20T18:00:00Z", title="Knots for climbers", channel="bob-example"),
        _w(VID[0], at="2026-10-03T07:00:00Z", title="Bridge design, part one"),
    ])
    lines = watch_history.lookup(memory, "When did I watch the bridge design video?")
    assert len(lines) == 2 and lines[0].startswith("2026-09-01 09:14 · Bridge design, part one — alice-example")
    assert lines[1].startswith("2026-10-03 07:00 ·") and lines[0].endswith("]")
    month = watch_history.lookup(memory, "What was I watching in September 2026?")
    assert month[0].startswith("[ep_2026-09-20_") and "# Watched on YouTube · September 2026" in month[0]
    assert any("bob-example — 1 video on 1 day" in ln for ln in month)
    assert watch_history.lookup(memory, "What was I watching in March 2025?") == []
    assert watch_history.lookup(memory, "what did i watch") == []          # nothing to match on
    assert watch_history.is_about_watching("which channels did I watch") is True
    assert watch_history.is_about_watching("which database did we pick") is False


def test_ask_answers_from_the_watch_history_when_no_page_does(tmp_path):
    from api.services import ask_service

    memory = _bank(tmp_path)
    watch_history.record(memory, [_w(VID[0], at="2026-09-01T09:14:00Z", title="Bridge design, part one")])
    prompts: list[str] = []

    def llm(prompt):
        prompts.append(prompt)
        return json.dumps({"answer": "On 2026-09-01.", "confidence": 0.8,
                           "used_entities": ["ep_2026-09-01_002"], "gaps": []})

    out = ask_service.answer_query(memory, "When did I watch bridge design?", retrieve_fn=lambda q, k: [],
                                   llm_fn=llm, no_engine=False)
    assert out["answer"] == "On 2026-09-01." and out["citations"] == []
    assert "WATCH HISTORY" in prompts[0] and "Bridge design, part one — alice-example" in prompts[0]
    # A caller that may not see the record's own text, or a question that is not about watching: a plain gap.
    gap = ask_service.answer_query(memory, "When did I watch bridge design?", retrieve_fn=lambda q, k: [],
                                   llm_fn=llm, no_engine=False, source_words=False)
    other = ask_service.answer_query(memory, "Which bridge design did we pick?", retrieve_fn=lambda q, k: [],
                                     llm_fn=llm, no_engine=False)
    assert gap["confidence"] == other["confidence"] == 0.05 and len(prompts) == 1


# --- the person's words reach a list save later (review of #340) -------------------------------------------------------


@pytest.mark.parametrize("extra", [{"saved_why": {"reasons": ["design"], "at": "2026-10-18T09:00:00Z"}},
                                   {"saved_why_earlier": [{"reasons": ["design"]}]}, {"has_note": True}])
def test_a_list_save_with_the_persons_words_is_never_index_only(extra):
    fm = {"source": "youtube", "origin": "youtube-playlist", "folder": "Watch later", **extra}
    assert history_index.kind(fm) is None
    assert history_index.waits_for_model({**fm, "processed": False}) is True


def _listed_save(memory, vid=VID[0]):
    idx = media_ingestor.load_url_index(memory)
    url = f"https://www.youtube.com/watch?v={vid}"
    item = RawItem(url=url, title="A video", folder="Watch later", origin="youtube-playlist")
    meta = MediaMeta(title="A video", description="", site="youtube.com", media_type="youtube")
    res = media_ingestor.write_prepared(PreparedItem(item, meta), memory, idx)
    media_ingestor.save_url_index(memory, idx)
    return url, memory / "episodes" / f"{res.episode_id}.md"


def test_why_it_was_saved_sends_an_indexed_list_save_back_to_the_model(tmp_path):
    """The person bookmarks a video already in their imported Watch later, then answers "what made you save this?"."""
    from api.services import saved_why

    memory = _bank(tmp_path)
    url, path = _listed_save(memory)
    assert markdown_parser.parse(path).frontmatter["processed_by"] == "index"
    saved_why.attach(memory, url=url, answer=saved_why.Answer(reasons=("design",), project=None, project_name=None,
                                                              text="the way the bridge is drawn"))
    parsed = markdown_parser.parse(path)
    fm = parsed.frontmatter
    assert fm["processed"] is False and "processed_by" not in fm and "## Why it was saved" in parsed.body
    assert history_index.waits_for_model(fm) is True
    bank_index.invalidate()
    assert history_index.retire(memory).paths == []                        # never flipped back to the index
    assert path.stem in {e["id"] for e in sleep_cycle._get_unprocessed_episodes(memory)}


def test_a_telegram_reason_on_a_repeat_save_sends_an_indexed_list_save_back_to_the_model(tmp_path):
    from api.services import telegram_capture

    memory = _bank(tmp_path)
    _, path = _listed_save(memory)
    telegram_capture._append_saved_because_section_if_absent(memory, path.stem, "for the knot at minute three")
    parsed = markdown_parser.parse(path)
    assert "## Saved because\nfor the knot at minute three" in parsed.body
    assert parsed.frontmatter["processed"] is False and parsed.frontmatter["has_note"] is True
    assert "processed_by" not in parsed.frontmatter
    bank_index.invalidate()
    assert history_index.retire(memory).paths == []
    assert path.stem in {e["id"] for e in sleep_cycle._get_unprocessed_episodes(memory)}


def test_retire_returns_a_queued_list_save_whose_body_holds_the_persons_words(tmp_path):
    """An older writer put the person's section on a queued list save without stamping it: retire never flips it to
    the index — it stamps it theirs, and it waits for the model."""
    memory = _bank(tmp_path)
    eid = "ep_2026-08-04_001"
    markdown_parser.write(memory / "episodes" / f"{eid}.md",
                          {"id": eid, "timestamp": "2026-08-04T09:00:00+00:00", "processed": False,
                           "source": "youtube", "origin": "youtube-playlist", "folder": "Watch later"},
                          "# A video\n\n## Saved because\nfor the ending")
    out = history_index.retire(memory)
    assert out.paths == [f"episodes/{eid}.md"] and out.returned == 1 and not out.by_kind
    fm = markdown_parser.parse(memory / "episodes" / f"{eid}.md").frontmatter
    assert fm["processed"] is False and fm["has_note"] is True and "processed_by" not in fm
    bank_index.invalidate()
    assert eid in {e["id"] for e in sleep_cycle._get_unprocessed_episodes(memory)}
