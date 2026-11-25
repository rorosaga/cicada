"""Owner 2026-11-25: one bubble per list of saved things in the graph (`graph_bubbles`).

`list_pages.groups` (the Sources work's) decides what sits inside each list and what earned a place outside; these tests
stand in for it with the agreed shape and check how the graph shapes that answer: top-level lists only, folders as rings,
members that are nodes, one bubble per page, a floor, the earned pages outside, the cache and the ETag moving with it."""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.routers import graph as graph_router
from api.services import bank_index, graph_bubbles, graph_builder, list_pages, logo_service, markdown_parser


@dataclass
class Info:
    key: str
    name: str
    inside: tuple = ()
    parent: str | None = None
    folder: str | None = None
    label: str = "Saved"
    site: str = "x"
    mark: str = "x-bookmarks"
    kind_noun: str = "posts"
    has_page: bool = False


@dataclass
class Groups:
    lists: dict = field(default_factory=dict)
    of_page: dict = field(default_factory=dict)
    earned_of: dict = field(default_factory=dict)
    stamp: str = "s1"


VIDEOS = [f"video-{i:02d}" for i in range(10)]
POSTS = [f"post-{i:02d}" for i in range(8)]


def _groups() -> Groups:
    g = Groups()
    g.lists["youtube-playlists"] = Info("youtube-playlists", "YouTube: Playlists", tuple(VIDEOS), site="youtube",
                                        mark="youtube-playlist", kind_noun="videos", label="Playlists")
    g.lists["youtube-playlists-a"] = Info("youtube-playlists-a", "Alpha", tuple(VIDEOS[:6]), parent="youtube-playlists",
                                          folder="Alpha")
    g.lists["youtube-playlists-b"] = Info("youtube-playlists-b", "Beta", tuple(VIDEOS[4:]), parent="youtube-playlists",
                                          folder="Beta")
    g.lists["x-bookmarks"] = Info("x-bookmarks", "X: Bookmarks", tuple(POSTS))
    g.lists["x-likes"] = Info("x-likes", "X: Likes", ("post-00", "post-01", "post-02"), mark="x-likes")
    for v in VIDEOS:
        g.of_page[v] = tuple(k for k in ("youtube-playlists-a", "youtube-playlists-b", "youtube-playlists")
                             if v in g.lists[k].inside)
    for p in POSTS:
        g.of_page[p] = tuple(k for k in ("x-likes", "x-bookmarks") if p in g.lists[k].inside)
    g.earned_of["talked-video"] = ("youtube-playlists",)
    return g


@pytest.fixture
def bank(tmp_path, monkeypatch):
    memory = tmp_path / "banks" / "work"
    (memory / "entities").mkdir(parents=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    for eid in [*VIDEOS, *POSTS, "talked-video"]:
        markdown_parser.write(memory / "entities" / f"{eid}.md",
                              {"name": eid, "type": "media", "media": {"url": f"https://example.com/{eid}"}},
                              "## Summary\nA save.\n")
    markdown_parser.write(memory / "entities" / "bob-example.md", {"name": "Bob Example", "type": "person"}, "A person.\n")
    monkeypatch.setattr(logo_service, "cached_ids", lambda bank: set())
    monkeypatch.setattr(logo_service, "missed_ids", lambda bank: {})
    state = {"groups": _groups()}
    monkeypatch.setattr(list_pages, "groups", lambda memory_path: state["groups"], raising=False)
    config.get_settings.cache_clear()
    bank_index.invalidate()
    graph_builder.reset_cache()
    yield memory, state
    config.get_settings.cache_clear()
    bank_index.invalidate()
    graph_builder.reset_cache()


def _bubbles(memory, **kw):
    return {b.key: b for b in graph_builder.build_graph(memory, **kw).bubbles}


def test_a_list_is_one_bubble_and_every_page_stays_a_node(bank):
    memory, _ = bank
    g = graph_builder.build_graph(memory)
    ids = {n.id for n in g.nodes}
    assert set(VIDEOS) | set(POSTS) <= ids                 # nothing removed: every saved thing keeps its page
    assert not any(i.startswith(graph_bubbles.PREFIX) for i in ids)   # a bubble is never a node
    bubbles = {b.key: b for b in g.bubbles}
    assert set(bubbles) == {"youtube-playlists", "x-bookmarks"}   # folders are no bubble; x-likes is under the floor
    yt = bubbles["youtube-playlists"]
    assert yt.id == "list:youtube-playlists" and yt.count == 10 and yt.kind_noun == "videos"
    assert yt.mark == "youtube-playlist" and yt.page_id is None
    assert yt.members == VIDEOS                            # the list's own order (newest first)


def test_a_folder_is_a_ring_and_a_page_sits_in_one_folder(bank):
    memory, _ = bank
    yt = _bubbles(memory)["youtube-playlists"]
    folders = {f.key: f.members for f in yt.folders}
    assert folders["youtube-playlists-a"] == VIDEOS[:6]
    assert folders["youtube-playlists-b"] == VIDEOS[6:]   # the two shared with Alpha sit in Alpha only
    assert [f.name for f in yt.folders] == ["Alpha", "Beta"]


def test_a_page_on_two_lists_sits_in_the_first(bank):
    memory, state = bank
    state["groups"].lists["x-likes"].inside = tuple(POSTS)        # big enough to be a bubble now
    for p in POSTS:
        state["groups"].of_page[p] = ("x-likes", "x-bookmarks")
    graph_builder.reset_cache()
    state["groups"].stamp = "s2"
    bubbles = _bubbles(memory)
    assert bubbles["x-likes"].members == POSTS             # of_page names x-likes first
    assert "x-bookmarks" not in bubbles                    # nothing left inside it


def test_the_earned_page_is_outside_and_named_on_its_bubble(bank):
    memory, _ = bank
    yt = _bubbles(memory)["youtube-playlists"]
    assert yt.outside == ["talked-video"] and "talked-video" not in yt.members


def test_a_list_with_a_page_names_it(bank):
    memory, state = bank
    state["groups"].lists["x-bookmarks"].has_page = True
    markdown_parser.write(memory / "entities" / "x-bookmarks.md",
                          {"name": "X: Bookmarks", "type": "media", "media": {"kind": "list"}}, "A list.\n")
    bank_index.invalidate()
    assert _bubbles(memory)["x-bookmarks"].page_id == "x-bookmarks"


def test_a_filter_keeps_only_members_that_are_still_nodes(bank):
    memory, _ = bank
    assert _bubbles(memory, types={"person"}) == {}
    assert set(_bubbles(memory, types={"media"})) == {"youtube-playlists", "x-bookmarks"}


def test_no_grouping_means_no_bubbles_and_a_failure_costs_nothing(bank, monkeypatch):
    memory, _ = bank

    def boom(memory_path):
        raise RuntimeError("broken")

    monkeypatch.setattr(list_pages, "groups", boom, raising=False)
    graph_builder.reset_cache()
    g = graph_builder.build_graph(memory)
    assert g.bubbles == [] and len(g.nodes) == len(VIDEOS) + len(POSTS) + 2
    assert graph_bubbles.stamp(memory) == ""


def test_the_cache_and_the_etag_move_with_the_grouping(bank):
    memory, state = bank
    with TestClient(main.app) as c:
        first = c.get("/graph")
        etag = first.headers["etag"]
        assert {b["key"] for b in first.json()["bubbles"]} == {"youtube-playlists", "x-bookmarks"}
        assert c.get("/graph", headers={"If-None-Match": etag}).status_code == 304
        state["groups"].lists["x-bookmarks"].inside = tuple(POSTS[:3])
        state["groups"].stamp = "s2"
        second = c.get("/graph", headers={"If-None-Match": etag})
        assert second.status_code == 200 and second.headers["etag"] != etag
        assert {b["key"] for b in second.json()["bubbles"]} == {"youtube-playlists"}
    assert "+bubbles" in graph_router.NODE_SHAPE and graph_router.NODE_SHAPE.endswith("+source-links")
