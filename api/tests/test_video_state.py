"""G162 V1 — what Cicada honestly knows about each saved video: the set-union state (spec §4.2),
its fidelity, the set of videos the Feed shows, and the record's new arguments. Synthetic banks;
nothing reaches the network."""
from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from _stdio_server import stdio_server
from _synthetic_bank import _bank
from _video_fixtures import add_video, add_watch_episode, bank_with_videos, url_of
from api import config, main
from api.services import bank_index, markdown_parser, media_ingestor, mcp_tools, video_state
from api.services.claims import parse_claims

FIXTURES = Path(__file__).parent / "fixtures"
STATE_CASES = json.loads((FIXTURES / "video_state.json").read_text(encoding="utf-8"))
KIND_CASES = json.loads((FIXTURES / "video_kind.json").read_text(encoding="utf-8"))


@pytest.fixture
def client(tmp_path, monkeypatch):
    memory, keys = bank_with_videos(tmp_path, 3)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    try:
        yield TestClient(main.app), memory, keys
    finally:
        config.get_settings.cache_clear()


def _items(c):
    return {i["key"]: i for i in c.get("/videos/state").json()["items"]}


# --- A1: the union table --------------------------------------------------------------------


@pytest.mark.parametrize("case", STATE_CASES["cases"], ids=lambda c: c["name"])
def test_union_table(case, tmp_path):
    """Every row of `video_state.json`, through the real reader over real episode files."""
    memory = _bank(tmp_path)
    key = add_video(memory, "u1")
    for n, basis in enumerate(case["episodes"], 1):
        add_watch_episode(memory, url_of("u1"), basis=basis, n=n)
    records = video_state.watch_records(memory)
    assert video_state.state_of(records.get(key, [])) == case["state"], case["name"]


def test_the_pure_rule_agrees_with_the_table():
    for case in STATE_CASES["cases"]:
        facts = set()
        for basis in case["episodes"]:
            facts |= video_state.basis_facts({"watch_basis": basis})
        assert video_state.derive(facts) == case["state"], case["name"]


def test_a_legacy_record_reads_recorded_not_watched(client):
    c, memory, keys = client
    add_watch_episode(memory, url_of("00"), basis=None)
    item = _items(c)[keys[0]]
    assert item["state"] == "recorded" and "basis" not in item and item["fidelity"] == "approximate"


# --- A7: fidelity, and the shape tag ------------------------------------------------------------


@pytest.mark.parametrize("case", STATE_CASES["fidelity"], ids=lambda c: str(c["engine"]))
def test_fidelity_by_engine(case):
    """`video_link`, `other` and an absent engine read approximate; the retired name `gemini_url` is
    not an engine, so it reads as absent."""
    assert video_state.fidelity(case["engine"]) == case["fidelity"]


def test_the_engine_set_names_no_provider():
    assert set(video_state.ENGINES) == {"captions", "video_link", "local_frames", "speech_to_text", "browser",
                                        "other"}


def test_the_video_shape_moves_both_provenance_etags(client, monkeypatch):
    c, memory, keys = client
    ep = add_watch_episode(memory, url_of("00"), basis="transcript", engine="captions")
    tags = [c.get(f"/episodes/{ep}/text").headers["ETag"], c.get(f"/episodes/{ep}/citations").headers["ETag"]]
    monkeypatch.setattr(video_state, "VIDEO_SHAPE", "video-999")
    after = [c.get(f"/episodes/{ep}/text").headers["ETag"], c.get(f"/episodes/{ep}/citations").headers["ETag"]]
    assert all(a != b for a, b in zip(tags, after))


def test_the_episode_text_carries_watch_and_media_fidelity(client):
    c, memory, keys = client
    ep = "ep_2026-09-28_001"
    add_watch_episode(memory, url_of("00"), basis="frames", engine="video_link")
    markdown_parser.write(memory / "episodes" / f"{ep}.md",
                          {**markdown_parser.parse(memory / "episodes" / f"{ep}.md").frontmatter},
                          "assistant: A summary.\n\nvideo [4:05]: a quote")
    bank_index.invalidate(memory)
    body = c.get(f"/episodes/{ep}/text").json()
    assert body["watch"] == {"basis": "frames", "engine": "video_link", "fidelity": "approximate",
                             "authorModel": None, "authorEffort": None}
    media = [t for t in body["turns"] if t["role"] == "media"]
    assert media and all(t["fidelity"] == "approximate" for t in media)
    assert all(t["fidelity"] is None for t in body["turns"] if t["role"] != "media")


def test_a_non_watch_episode_has_no_watch_block(client):
    c, memory, keys = client
    add_watch_episode(memory, url_of("00"), source="chatgpt")
    assert c.get("/episodes/ep_2026-09-28_001/text").json()["watch"] is None


def test_the_second_axis_is_derived_never_stored(client):
    """`readBySleep`: true only for processed_by sleep, false when unprocessed, absent when an agent
    flipped `processed` (Cicada cannot tell what that meant)."""
    c, memory, keys = client
    add_watch_episode(memory, url_of("00"), basis="transcript", processed=False)
    add_watch_episode(memory, url_of("01"), basis="transcript", processed=True, processed_by="sleep", n=2)
    add_watch_episode(memory, url_of("02"), basis="transcript", processed=True, processed_by="agent", n=3)
    items = _items(c)
    assert items[keys[0]]["readBySleep"] is False
    assert items[keys[1]]["readBySleep"] is True
    assert "readBySleep" not in items[keys[2]]
    assert items[keys[0]]["recordedBy"] == "claude-code" and items[keys[0]]["recordedAt"] == "2026-09-28T14:31:07Z"


# --- A9, L3: identity is the url key, and only watch episodes count -----------------------------------------------


def test_same_title_distinct_keys(tmp_path):
    """Two saved videos with one title share a media entity id slug rule but never a key: a record on
    one never shows on the other."""
    memory = _bank(tmp_path)
    a = add_video(memory, "twin-a", title="Same Title", url="https://www.youtube.com/watch?v=aaaaaaaaaaa")
    b = add_video(memory, "twin-b", title="Same Title", url="https://www.youtube.com/watch?v=bbbbbbbbbbb")
    add_watch_episode(memory, "https://www.youtube.com/watch?v=aaaaaaaaaaa", basis="both")
    saved = video_state.saved_videos(memory)
    assert a != b and set(saved) == {a, b}
    records = video_state.watch_records(memory)
    assert video_state.state_of(records.get(a, [])) == "watched_and_transcript"
    assert video_state.state_of(records.get(b, [])) == "none"


def test_non_watch_episode_with_same_url_is_ignored(tmp_path):
    """Saved-media episodes carry the same `url` and `media_entity_id`; only `source: video-watch` counts."""
    memory = _bank(tmp_path)
    key = add_video(memory, "m1")
    add_watch_episode(memory, url_of("m1"), basis="both", source="youtube")
    add_watch_episode(memory, url_of("m1"), basis="both", source="video-watch", n=2)  # counts
    assert len(video_state.watch_records(memory)[key]) == 1


def test_an_episode_with_no_link_counts_for_nothing(tmp_path):
    memory = _bank(tmp_path)
    key = add_video(memory, "m2")
    add_watch_episode(memory, "", basis="both")
    assert video_state.watch_records(memory).get(key) is None


def test_a_link_variant_unifies_by_url_hash(tmp_path):
    memory = _bank(tmp_path)
    key = add_video(memory, "v1", url="https://www.youtube.com/watch?v=abcdefghijk")
    add_watch_episode(memory, "https://youtu.be/abcdefghijk", basis="transcript")
    assert video_state.state_of(video_state.watch_records(memory)[key]) == "transcript"


# --- P10 / N-1: the set is the Feed's --------------------------------------------------------------------


@pytest.mark.parametrize("case", KIND_CASES["cases"], ids=lambda c: c["url"][:60] + str(c["kind"]))
def test_the_kind_fixture(case):
    assert video_state.is_video_page(case["mediaType"], case["url"], case["kind"]) is case["video"]


def test_set_equals_feed_videos(tmp_path, monkeypatch):
    """`saved_videos` equals the `/sources` items the Feed's video rule selects — alias rows, archived,
    dropped and junk pages included in what both skip."""
    memory = _bank(tmp_path)
    add_video(memory, "yt")
    add_video(memory, "vimeo", url="https://vimeo.com/123456789", media_type="url")
    add_video(memory, "paper", url="https://arxiv.org/abs/2303.04137", media_type="url", kind="paper")
    add_video(memory, "article", url="https://example.com/a", media_type="url")
    add_video(memory, "archived", status="archived")
    add_video(memory, "junk", enrichment_status="junk")
    add_video(memory, "alias", alias_of="whatever", url="https://www.youtube.com/watch?v=zzzzzzzzzzz")
    add_video(memory, "mp4", url="https://example.com/v/demo.mp4", media_type="video")
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    try:
        feed = TestClient(main.app).get("/sources").json()["items"]
    finally:
        config.get_settings.cache_clear()
    feed_videos = {media_ingestor.url_hash(i["url"]) for i in feed
                   if video_state.is_video_page(i["mediaType"], i["url"], i.get("kind"))}
    assert set(video_state.saved_videos(memory)) == feed_videos
    assert len(feed_videos) == 3  # yt, vimeo and the direct file; a paper, a link, an alias, a junk page: no
