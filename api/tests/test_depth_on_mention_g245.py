"""G245 (ruling 78 (e), owner 2026-11-24): depth on mention. A save from a platform's list stays light — indexed, read by no
model — until the person talks about it: their own located words wake it for one normal Sleep read, and the same mention
leaves an ASK for their own agent (a provider video on the video queue, a walled post on the reading queue), marked as
coming from a mention, honoured only while agent reading and that save's list are on, at most 5 a day.

Synthetic banks under tmp_path, a scratch ``$CICADA_HOME``, placeholder handles and example.com links; nothing real is
read and nothing is fetched or started."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from _reading_fixtures import reading, record  # noqa: F401 — `reading` is a fixture
from api.services import (bank_index, history_index, markdown_parser, media_ingestor, mention_asks, reading_asks,
                          reading_queue, reading_settings, saved_mentions, source_streams, video_queue, video_state)
from api.services.media_ingestor import MediaMeta, PreparedItem, RawItem

AT = "2026-11-24T10:00:00+00:00"
T0 = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)
POST_A = "https://x.com/alice_example/status/1000000000000000001"
POST_B = "https://x.com/bob_example/status/1000000000000000002"
IG_A = "https://www.instagram.com/p/AbCdE12345/"
VIDEO_A = "https://www.youtube.com/watch?v=aaaaaaaaaaa"
VIDEO_B = "https://www.youtube.com/watch?v=bbbbbbbbbbb"
PUBLIC_LIKE = "https://blog.bob-example.org/post/1"


@pytest.fixture(autouse=True)
def _fresh():
    bank_index.invalidate()
    yield
    bank_index.invalidate()


def _on(*keys):
    reading_settings.update(saved_lists_={k: True for k in keys})


def _yt_on(*names):
    reading_settings.update(youtube_lists_={n: True for n in names})


def _list_save(memory, url, title, *, origin, folder, media_type="bookmark", bulk=True):
    """A save as a bulk door writes it: waiting its turn in the pile (``bulk=False``: waiting for tonight)."""
    idx = media_ingestor.load_url_index(memory)
    item = RawItem(url=url, title=title, origin=origin, folder=folder, defer_enrich=True)
    # The words the list showed (a post's text, a video's description): a save with none has nothing to read (ruling 80).
    meta = MediaMeta(title=title, description="What the list showed of it", site="example.com", media_type=media_type)
    res = media_ingestor.write_prepared(PreparedItem(item, meta), memory, idx, bulk=bulk)
    media_ingestor.save_url_index(memory, idx)
    bank_index.invalidate()
    return res.episode_id


def _x_like(memory, url=POST_A, title="Notes on vector indexes at laptop scale"):
    return _list_save(memory, url, title, origin="x-likes", folder="Likes")


def _video(memory, url=VIDEO_A, title="A talk about retrieval", folder="Watch later"):
    return _list_save(memory, url, title, origin="youtube-playlist", folder=folder, media_type="youtube")


def _fm(memory, episode_id):
    return markdown_parser.parse(memory / "episodes" / f"{episode_id}.md").frontmatter


def _conversation(memory, eid, body):
    fm = {"id": eid, "timestamp": AT, "processed": False, "source": "claude-code", "harness": "claude-code",
          "session_id": f"ses_{eid}", "title": "A conversation"}
    path = memory / "episodes" / f"{eid}.md"
    markdown_parser.write(path, fm, body)
    bank_index.invalidate()
    return {"id": eid, "content": body, "origin": "claude-code", "filepath": path, "words_of": None, "gaps": ()}


def _say(memory, text, eid="ep_2026-11-24_901"):
    return _conversation(memory, eid, f"user: {text}")


def _hash(url):
    return media_ingestor.url_hash(url)


# --- (1) the wake: a list save, the person's own words only -------------------------------------------------------------


def test_a_list_save_in_the_pile_is_never_read_until_its_turn_or_named(reading):
    _, memory = reading
    ep = _x_like(memory)
    fm = _fm(memory, ep)
    assert history_index.kind(fm) == "list" and fm["processed_by"] == history_index.INDEXED_BY
    assert saved_mentions.wake_mentioned(memory, [_say(memory, "I like cats and dogs")], at=AT) == []
    assert history_index.kind(_fm(memory, ep)) == "list" and not history_index.waits_for_model(_fm(memory, ep))


def test_the_person_naming_a_list_saves_link_wakes_it_for_one_real_read(reading):
    _, memory = reading
    ep = _x_like(memory)
    said = _say(memory, f"have a look at {POST_A} again")
    assert saved_mentions.wake_mentioned(memory, [said], at=AT) == [f"episodes/{ep}.md"]
    fm = _fm(memory, ep)
    assert fm["read_asked"] == {"why": saved_mentions.WHY_LINK, "at": AT}
    assert history_index.kind(fm) is None and history_index.waits_for_model(fm) and history_index.owes_a_read(fm)
    # It is woken once: a second mention changes nothing.
    assert saved_mentions.wake_mentioned(memory, [said], at="2026-11-25T10:00:00+00:00") == []
    assert _fm(memory, ep)["read_asked"]["at"] == AT


def test_the_person_saying_a_list_saves_whole_title_wakes_it(reading):
    _, memory = reading
    ep = _x_like(memory)
    said = _say(memory, "I keep thinking about notes on vector indexes at laptop scale")
    assert saved_mentions.wake_mentioned(memory, [said], at=AT) == [f"episodes/{ep}.md"]
    assert _fm(memory, ep)["read_asked"]["why"] == saved_mentions.WHY_TITLE


def test_an_agents_reply_or_a_lit_page_never_wakes_a_list_save(reading):
    _, memory = reading
    ep = _x_like(memory)
    agent = _conversation(memory, "ep_2026-11-24_902", f"user: what is next\n\nassistant: you saved {POST_A}")
    assert saved_mentions.wake_mentioned(memory, [agent], at=AT) == []
    # WHY_LIT is refused for a list save by the one writer, whatever calls it.
    assert history_index.wake(memory, ep, saved_mentions.WHY_LIT, AT) is None
    assert history_index.kind(_fm(memory, ep)) == "list"
    assert saved_mentions.wake_lit(memory, at=AT) == []


@pytest.mark.parametrize(("origin", "folder"), [("github-owned", ""), ("reddit-saved", "Joined communities")])
def test_a_record_that_is_no_save_is_never_woken(reading, origin, folder):
    _, memory = reading
    ep = _list_save(memory, "https://example.com/r/1", "Alpha project repository notes", origin=origin, folder=folder)
    assert history_index.kind(_fm(memory, ep)) == "list"
    said = _say(memory, "tell me about https://example.com/r/1 and alpha project repository notes")
    assert saved_mentions.wake_mentioned(memory, [said], at=AT) == []


def test_the_wake_keeps_its_bound_of_five_a_conversation_over_list_saves(reading):
    _, memory = reading
    urls = [f"https://x.com/alice_example/status/10000000000000001{i:02d}" for i in range(8)]
    for i, url in enumerate(urls):
        _x_like(memory, url, f"Distinct title number {i} words here")
    said = _say(memory, " ".join(urls))
    paths = saved_mentions.wake_mentioned(memory, [said], at=AT)
    woken = [p for p in paths if "read_asked" in _fm(memory, p.split("/")[-1][:-3])]
    assert len(woken) == saved_mentions.MAX_WAKES_PER_CONVERSATION == 5
    assert len(paths) == 8   # every post named is marked (G246): the cap bounds reads, not the mark


def test_a_save_with_a_reason_from_a_list_is_read_as_before(reading):
    _, memory = reading
    ep = _x_like(memory)
    fm = _fm(memory, ep)
    fm["has_note"] = True
    assert history_index.kind(fm) is None


# --- (2) the ask --------------------------------------------------------------------------------------------------------


def _mentioned(memory, url, **kw):
    return saved_mentions.wake_mentioned(memory, [_say(memory, f"look at {url}")], at=AT, **kw)


def test_a_mentioned_walled_post_leaves_a_reading_ask_marked_as_a_mention(reading):
    server, memory = reading
    _on("x-likes")
    _x_like(memory)
    _mentioned(memory, POST_A)
    [row] = reading_asks.all_rows(memory)
    assert (row["origin"], row["list"], row["state"], row["host_class"]) == ("mention", "x-likes", "waiting", "walled")
    assert row["url_hash"] == _hash(POST_A) and "http" not in json.dumps(row)
    [entry] = reading_queue.entries(memory)
    assert (entry.origin, entry.url) == ("mention", POST_A)
    text = server.handle_tool("cicada_reading_queue", {})
    assert "the person talked about this" in text and "nobody asked" in text and "asked 2026" not in text
    assert reading_queue.count_waiting(memory) >= 1


def test_a_mentioned_provider_video_goes_on_the_video_queue_as_a_transcript_job(reading):
    server, memory = reading
    _yt_on("watch_later")
    _video(memory)
    _mentioned(memory, VIDEO_A)
    rows, _ = video_queue.view(memory)
    [row] = rows
    assert (row["key"], row["want"], row["state"], row["origin"], row["list"]) == (
        _hash(VIDEO_A), "transcript", "queued", "mention", "youtube:watch_later")
    assert reading_asks.all_rows(memory) == []                    # one ask, on one queue
    out = server.handle_tool("cicada_video_claim", {})
    assert "the person talked about this" in out and "Leased 1 video" in out
    item = next(i for i in video_state.build(memory, video_queue.view(memory)[0], None)["items"]
                if i["key"] == _hash(VIDEO_A))
    assert item["origin"] == "mention" and item["queueState"] == "claimed"


REDDIT_A = "https://www.reddit.com/r/example/comments/abc123/a_post_about_vector_stores/"


@pytest.mark.parametrize("origin, folder, url, key", [
    ("x-bookmarks", "", POST_A, "x"),                       # a bookmark filed in no folder: the most common save
    ("x-bookmarks", "Bookmarks", POST_A, "x"),              # the export's own folder
    ("reddit-saved", "r/example", REDDIT_A, "reddit"),      # the connector files a save under its community
    ("instagram-saved", "A collection of mine", IG_A, "instagram"),
])
def test_every_list_save_the_person_names_leaves_the_same_ask_whatever_its_folder(reading, origin, folder, url, key):
    """The class: a save on a list whose switch is on gets its ask when the person's own words name it — whichever way the
    index reads its record (a bare save, a list save, a woken one)."""
    _, memory = reading
    _on(key)
    ep = _list_save(memory, url, "Notes on vector indexes at laptop scale", origin=origin, folder=folder)
    assert _mentioned(memory, url) == [f"episodes/{ep}.md"]
    [row] = reading_asks.all_rows(memory)
    assert (row["origin"], row["list"], row["state"]) == ("mention", key, "waiting") and row["url_hash"] == _hash(url)
    assert mention_asks.asked_today(memory) == 1
    # Said again, it is never a second ask; a list that is off leaves none.
    _mentioned(memory, url)
    assert len(reading_asks.all_rows(memory)) == 1


def test_a_save_in_no_folder_that_nobody_named_or_whose_list_is_off_gets_nothing(reading):
    _, memory = reading
    _on("x")
    _list_save(memory, POST_A, "Notes on vector indexes at laptop scale", origin="x-bookmarks", folder="")
    saved_mentions.wake_mentioned(memory, [_say(memory, "nothing about any save")], at=AT)
    assert reading_asks.all_rows(memory) == []
    reading_settings.update(saved_lists_={"x": False})
    _mentioned(memory, POST_A)
    assert reading_asks.all_rows(memory) == []
    # A bookmark of a browser is no list of a site: named, it wakes, and asks nothing.
    _on("x")
    _list_save(memory, POST_B, "Another quite different title words", origin="chrome-bookmark", folder="Bookmarks")
    _mentioned(memory, POST_B)
    assert reading_asks.all_rows(memory) == []


def test_a_mention_leaves_no_ask_while_agent_reading_or_that_list_is_off(reading):
    _, memory = reading
    _x_like(memory)
    _mentioned(memory, POST_A)                                     # no list on at all
    assert reading_asks.all_rows(memory) == []
    _on("x")                                                       # another list of the same site is not this list
    _x_like(memory, POST_B, "Another quite different title words")
    _mentioned(memory, POST_B)
    assert reading_asks.all_rows(memory) == []
    reading_settings.update(agent_enabled_=False)
    _on("x-likes")
    _x_like(memory, IG_A, "Third distinct title for tests")
    assert mention_asks.offer(memory, {"e": {"url": POST_A, "origin": "x-likes", "folder": "Likes"}}) == []


def test_a_mention_of_a_public_page_or_a_list_never_registered_leaves_no_ask_but_still_wakes(reading):
    _, memory = reading
    _on("x-likes")
    ep = _x_like(memory, PUBLIC_LIKE, "A public page title with words")
    assert _mentioned(memory, PUBLIC_LIKE) == [f"episodes/{ep}.md"]
    assert reading_asks.all_rows(memory) == [] and video_queue.view(memory)[0] == []
    assert mention_asks.list_key("someone-elses-list", "Anything") is None


def test_a_list_save_nobody_mentioned_is_never_asked_about_or_read(reading):
    _, memory = reading
    _on("x-likes")
    ep = _x_like(memory)
    saved_mentions.wake_mentioned(memory, [_say(memory, "nothing about any save")], at=AT)
    assert reading_asks.all_rows(memory) == [] and history_index.kind(_fm(memory, ep)) == "list"
    assert not history_index.waits_for_model(_fm(memory, ep))


def test_an_ask_is_left_even_when_the_wake_was_spent_before_and_never_twice(reading):
    server, memory = reading
    ep = _x_like(memory)
    _mentioned(memory, POST_A)                                     # agent reading on, but the list is off: woken, no ask
    assert history_index.owes_a_read(_fm(memory, ep)) and reading_asks.all_rows(memory) == []
    _on("x-likes")
    _mentioned(memory, POST_A)                                     # the list is on now: the ask follows
    assert len(reading_asks.all_rows(memory)) == 1
    reading_asks.drop(memory, _hash(POST_A))                       # the person removes it ...
    _mentioned(memory, POST_A)                                     # ... and it is never offered again
    assert reading_asks.all_rows(memory) == []


def test_at_most_five_asks_a_day_across_both_queues_and_the_count_is_stored(reading):
    _, memory = reading
    _on("x-likes")
    _yt_on("watch_later")
    saves = {}
    for i in range(4):
        url = f"https://x.com/alice_example/status/20000000000000000{i:02d}"
        _x_like(memory, url, f"Post {i}")
        saves[f"x{i}"] = {"url": url, "origin": "x-likes", "folder": "Likes"}
    for letter in "cde":
        url = f"https://www.youtube.com/watch?v={letter * 11}"
        _video(memory, url, f"Video {letter}")
        saves[f"v{letter}"] = {"url": url, "origin": "youtube-playlist", "folder": "Watch later"}
    made = mention_asks.offer(memory, saves, now=T0)
    assert len(made) == mention_asks.DAILY_CAP == 5
    assert len(reading_asks.all_rows(memory)) + len(video_queue.view(memory)[0]) == 5
    assert mention_asks.offer(memory, saves, now=T0 + timedelta(hours=3)) == []     # the day's five are spent
    assert mention_asks.asked_today(memory, T0) == 5
    state = json.loads(mention_asks._path(memory).read_text())
    assert state["day"] == "2026-11-24" and state["count"] == 5 and len(state["offered"]) == 5
    assert "http" not in json.dumps(state) and not (memory / "mention_asks").exists()   # ids only, outside the bank
    assert len(mention_asks.offer(memory, saves, now=T0 + timedelta(days=1))) == 2   # tomorrow the rest, once each


def test_the_waiting_bound_stops_more_asks(reading, monkeypatch):
    _, memory = reading
    _on("x-likes")
    monkeypatch.setattr(mention_asks, "MAX_WAITING", 1)
    saves = {}
    for i in range(3):
        url = f"https://x.com/alice_example/status/30000000000000000{i:02d}"
        _x_like(memory, url, f"Post {i}")
        saves[f"x{i}"] = {"url": url, "origin": "x-likes", "folder": "Likes"}
    assert len(mention_asks.offer(memory, saves, now=T0)) == 1
    assert mention_asks.offer(memory, saves, now=T0 + timedelta(days=1)) == []


def test_a_waiting_mention_ask_never_expires_but_an_answered_one_ages_out_like_any(reading):
    _, memory = reading
    _on("x-likes")
    reading_asks.mention(memory, _hash(POST_A), host="x.com", host_class="walled", list_key="x-likes", now=T0)
    later = T0 + timedelta(days=90)
    assert len(reading_asks.all_rows(memory, now=later)) == 1
    assert reading_asks.expiry_state(memory, now=later) == (0, None)
    reading_asks.record_outcome(memory, _hash(POST_A), "blocked", now=later)
    [row] = reading_asks.all_rows(memory, now=later + timedelta(days=1))
    assert (row["state"], row["origin"], row["list"]) == ("blocked", "mention", "x-likes")   # keeps its mark
    assert reading_asks.all_rows(memory, now=later + timedelta(days=8)) == []


# --- honoured only while on: it leaves, it is never planted, the person undoes it ---------------------------------------


def test_turning_agent_reading_or_the_list_off_dequeues_the_ask_and_it_stays_gone(reading):
    server, memory = reading
    _on("x-likes")
    _yt_on("watch_later")
    _x_like(memory)
    _video(memory)
    mention_asks.offer(memory, {"a": {"url": POST_A, "origin": "x-likes", "folder": "Likes"},
                                "b": {"url": VIDEO_A, "origin": "youtube-playlist", "folder": "Watch later"}}, now=T0)
    assert reading_queue.entries(memory) and video_queue.view(memory)[0]
    reading_settings.update(saved_lists_={"x-likes": False})
    assert reading_queue.entries(memory) == [] and reading_asks.waiting(memory) != []   # hidden at once ...
    assert reading_queue.authorizes(memory, POST_A) is None
    assert "not on the person's reading list" in record(server, POST_A)
    assert mention_asks.sweep(memory) == 1                                                # ... removed by the sweep
    _on("x-likes")
    assert reading_asks.all_rows(memory) == [], "turning it back on never brings an old ask back"
    reading_settings.update(agent_enabled_=False)
    assert video_queue.view(memory)[0] == [] and server.handle_tool("cicada_video_claim", {}).startswith("Nothing")
    assert mention_asks.sweep(memory) == 1
    reading_settings.update(agent_enabled_=True)
    assert video_queue.view(memory)[0] == []


def test_a_leased_mention_ask_goes_with_its_switch_and_never_comes_back(reading):
    """An agent holds the lease when the person turns the list off: the ask is gone for good (as the person's own Remove
    takes a leased row), not hidden until the lease lapses and brought back by turning the switch on."""
    server, memory = reading
    _yt_on("watch_later")
    _video(memory)
    mention_asks.offer(memory, {"b": {"url": VIDEO_A, "origin": "youtube-playlist", "folder": "Watch later"}}, now=T0)
    assert "Leased 1 video" in server.handle_tool("cicada_video_claim", {})
    reading_settings.update(youtube_lists_={"watch_later": False})
    assert mention_asks.sweep(memory) == 1
    _yt_on("watch_later")
    assert video_queue.view(memory, T0 + timedelta(days=1))[0] == []
    assert video_queue._cached(memory)[0] == [], "stored rows too, not only the view"
    # The agent that held the lease records what it watched all the same: nothing breaks, the record is kept.
    assert server.handle_tool("cicada_video_claim", {}).startswith("Nothing")


def test_a_hidden_ask_is_never_counted_and_a_switch_turned_on_never_revives_one(reading, tmp_path):
    from fastapi.testclient import TestClient

    from api import config, main

    _, memory = reading
    import os
    os.environ["CICADA_MEMORY_PATH"] = str(memory)
    config.get_settings.cache_clear()
    try:
        client = TestClient(main.app)
        _on("x-likes")
        reading_asks.mention(memory, _hash(POST_A), host="x.com", host_class="walled", list_key="x-likes", now=T0)
        assert reading_asks.counts(memory)["waiting"] == 1
        # The switch goes off by a path that never swept (a sweep that failed, a file edited by hand): hidden, stored.
        reading_settings.update(saved_lists_={"x-likes": False})
        assert reading_asks.all_rows(memory) != []
        assert reading_asks.counts(memory) == {state: 0 for state in reading_asks.STATES}
        assert client.get("/reading/asks").json()["counts"]["waiting"] == 0
        assert reading_queue.counts(memory)[0] == 0
        # Turning it on through the route takes the hidden ask first: it is not honoured the instant the switch is on.
        assert client.put("/reading/settings", json={"savedLists": {"x-likes": True}}).status_code == 200
        assert reading_asks.all_rows(memory) == [] and reading_asks.counts(memory)["waiting"] == 0
        assert client.get("/reading/asks").json()["asks"] == []
    finally:
        os.environ.pop("CICADA_MEMORY_PATH", None)
        config.get_settings.cache_clear()


def test_an_agent_cannot_plant_a_mention_ask_and_a_mention_ask_authorizes_only_while_honoured(reading):
    server, memory = reading
    # Nothing an agent can call carries an origin onto a row but ``site``, and a planted outcome on a link nobody asked
    # about is refused.
    assert reading_asks.record_outcome(memory, _hash(POST_A), "read", host="x.com", host_class="walled", create=True,
                                       origin="mention") is not None
    [row] = reading_asks.all_rows(memory)
    assert "origin" not in row and "list" not in row
    reading_asks.drop(memory, _hash(POST_A))
    assert reading_queue.authorizes(memory, POST_B) is None
    out = record(server, POST_B, "read")
    assert "not on the person's reading list" in out
    # A mention row authorizes while honoured, and only then.
    _on("x-likes")
    reading_asks.mention(memory, _hash(POST_B), host="x.com", host_class="walled", list_key="x-likes", now=T0)
    assert reading_queue.authorizes(memory, POST_B)[0] == "ask"
    reading_settings.update(saved_lists_={"x-likes": False})
    assert reading_queue.authorizes(memory, POST_B) is None
    # The backend alone writes the mark: a crafted key is no row at all.
    assert reading_asks.mention(memory, _hash(IG_A), host="x.com", host_class="walled", list_key="../etc") is None
    assert video_queue.offer_mention(memory, _hash(VIDEO_A), "Bad Key") is False


def test_an_honoured_mention_ask_can_be_recorded_and_the_answer_keeps_its_mark(reading):
    server, memory = reading
    from _reading_fixtures import save

    _on("linkedin")
    url = "https://www.linkedin.com/feed/update/urn:li:activity:7000000000000000001/"
    save(memory, url, origin="linkedin-saved")
    reading_asks.mention(memory, _hash(url), host="linkedin.com", host_class="walled", list_key="linkedin", now=T0)
    out = record(server, url, "read")
    assert "Recorded your read" in out, out
    [row] = reading_asks.all_rows(memory)
    assert (row["state"], row["origin"]) == ("read", "mention")


def test_the_person_can_see_and_remove_it_where_their_own_asks_are_listed(reading, tmp_path):
    from fastapi.testclient import TestClient

    from api import config, main

    _, memory = reading
    import os
    os.environ["CICADA_MEMORY_PATH"] = str(memory)
    config.get_settings.cache_clear()
    try:
        client = TestClient(main.app)
        _on("x-likes")
        _yt_on("watch_later")
        _x_like(memory)
        _video(memory)
        mention_asks.offer(memory, {"a": {"url": POST_A, "origin": "x-likes", "folder": "Likes"},
                                    "b": {"url": VIDEO_A, "origin": "youtube-playlist", "folder": "Watch later"}}, now=T0)
        asks = client.get("/reading/asks").json()["asks"]
        assert [(a["origin"], a["state"]) for a in asks] == [("mention", "waiting")]
        item = next(i for i in client.get("/videos/state").json()["items"] if i["key"] == _hash(VIDEO_A))
        assert item["origin"] == "mention" and item["queueState"] == "queued"
        # Turning the list off through the settings route removes the ask for good, not just from view.
        assert client.put("/reading/settings", json={"savedLists": {"x-likes": False}}).status_code == 200
        assert reading_asks.all_rows(memory) == []
        _on("x-likes")
        assert reading_asks.all_rows(memory) == []
        _x_like(memory, POST_B, "Another quite different title words")
        mention_asks.offer(memory, {"a": {"url": POST_B, "origin": "x-likes", "folder": "Likes"}}, now=T0 + timedelta(days=1))
        assert client.get("/reading/asks").json()["asks"][0]["origin"] == "mention"
        assert client.delete(f"/reading/asks/{_hash(POST_B)}").json() == {"removed": True}
        assert client.delete(f"/videos/queue/{_hash(VIDEO_A)}").status_code in (200, 204)
        assert client.get("/reading/asks").json()["asks"] == []
        assert all("origin" not in i for i in client.get("/videos/state").json()["items"])
    finally:
        os.environ.pop("CICADA_MEMORY_PATH", None)
        config.get_settings.cache_clear()


def test_the_persons_own_ask_on_the_same_link_takes_the_mark_away(reading):
    _, memory = reading
    _on("x-likes")
    _yt_on("watch_later")
    _video(memory)
    mention_asks.offer(memory, {"b": {"url": VIDEO_A, "origin": "youtube-playlist", "folder": "Watch later"}}, now=T0)
    video_queue.put(memory, _hash(VIDEO_A), "watch")
    [row] = video_queue.view(memory)[0]
    assert "origin" not in row and row["want"] == "watch"
    reading_asks.mention(memory, _hash(POST_A), host="x.com", host_class="walled", list_key="x-likes", now=T0)
    reading_asks.ask(memory, _hash(POST_A), host="x.com", host_class="walled")
    assert "origin" not in reading_asks.get(memory, _hash(POST_A))


def test_a_link_with_a_row_already_gets_no_second_ask_and_a_read_link_none(reading):
    _, memory = reading
    _on("x-likes")
    _x_like(memory)
    reading_asks.ask(memory, _hash(POST_A), host="x.com", host_class="walled")
    assert mention_asks.offer(memory, {"a": {"url": POST_A, "origin": "x-likes", "folder": "Likes"}}, now=T0) == []
    assert mention_asks.asked_today(memory, T0) == 0


# --- (3) depth on the items rows ------------------------------------------------------------------------------------------


def _depth(memory, url):
    rows = [{"id": "media-a", "kind": "media", "_url": url, "_episode": "ep_x"}]
    pages = {"media-a": {"origin": "x-likes"}}
    return source_streams.row_fields(memory, rows, pages, lambda row: None)["media-a"]["depth"]


def test_depth_says_kept_asked_read_or_watched_by_what_the_record_holds(reading):
    _, memory = reading
    _on("x-likes")
    assert _depth(memory, POST_A) == "kept"
    reading_asks.mention(memory, _hash(POST_A), host="x.com", host_class="walled", list_key="x-likes", now=T0)
    assert _depth(memory, POST_A) == "asked"
    reading_settings.update(saved_lists_={"x-likes": False})
    assert _depth(memory, POST_A) == "kept", "a row an off switch hides is not asked"
    _on("x-likes")
    for source, want in (("page-read", "read"), ("video-watch", "watched")):
        url = f"https://x.com/alice_example/status/{source.replace('-', '')}"
        bank_index.invalidate()
        markdown_parser.write(memory / "episodes" / f"ep_2026-11-24_{want}.md",
                              {"id": f"ep_2026-11-24_{want}", "source": source, "url": url, "timestamp": AT,
                               "processed": True}, "body")
        bank_index.invalidate()
        assert _depth(memory, url) == want
    # Watched outranks an ask still waiting; an ask outranks a read only Sleep made.
    reading_asks.mention(memory, _hash(POST_B), host="x.com", host_class="walled", list_key="x-likes", now=T0)
    assert _depth(memory, POST_B) == "asked"
