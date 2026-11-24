"""G246 (ruling 81): one small page for each list of saved posts and each folder (`list_pages`).

The page is written by one module, born when the list's first item arrives and not before, and holds what the list IS and
nothing that can go stale: its count, newest day and rows are read from the saves each time the page is served. It is not
a saved item (no stream, no hub, no file or link count, never quiet, merged, asked about or given facts), it is a graph node
only while it holds something, and every earned post is joined to its list on read. All of it behind `saved_posts.HIDE_POSTS`:
dark, nothing is written. Synthetic names and words only; the bank is a real git repo, the saves are written the way the
ingest leaves them.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from _synthetic_bank import _bank
from api.services import (bank_index, channel_items, demo_guard, entity_merge, entity_resolver, graph_builder, hub_builder,
                          inbox_service, list_pages, markdown_parser, media_kinds, page_blocks, page_join, quiet_pages,
                          replica_guard, saved_posts, save_folders, source_overview, source_streams, write_admission)

POST = "https://x.com/alex_example/status/{n}"
NEWEST = "2026-11-12"


@pytest.fixture(autouse=True)
def _reset(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(exist_ok=True)
    bank_index.invalidate()
    graph_builder.reset_cache()
    yield
    bank_index.invalidate()
    graph_builder.reset_cache()


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(saved_posts, "HIDE_POSTS", True)


@pytest.fixture
def bank(tmp_path):
    return _bank(tmp_path)


def git(bank, *args):
    return subprocess.run(["git", "-C", str(bank), *args], check=True, capture_output=True, text=True).stdout


def commits(bank):
    return int(git(bank, "rev-list", "--count", "HEAD").strip())


def lists(bank):
    return sorted(p.stem for p in (bank / "entities").glob("list-*.md"))


def save(bank, n, *, origin="x-bookmarks", folder="Bookmarks", folders=(), url=None, day="2026-11-01", named=False,
         site_origin=None, **extra):
    """A saved post the way the ingest leaves it: a media page, its url-index row and its episode."""
    slug = f"{origin}-{n}"
    page, episode = f"media-{slug}", f"ep_{day}_{n:03d}{origin[0]}"
    link = url or POST.format(n=1000000 + n)
    fm = {"name": f"A post {n}", "type": "media", "status": "active", "origin": origin, "folder": folder,
          "created": day, "media": {"url": link, "media_type": "url"}, "source_episodes": [episode], **extra}
    markdown_parser.write(bank / "entities" / f"{page}.md", fm, "## Summary\nA short post.\n")
    ep = {"id": episode, "timestamp": f"{day}T08:00:00+00:00", "origin": origin, "url": link, "media_entity_id": page,
          "folder": folder, "source": "url", "processed": True, "processed_by": "history-index"}
    if folders:
        ep["save_folders"] = {site_origin or origin: list(folders)}
    if named:
        ep[saved_posts.NAMED_KEY] = {"why": "said its title", "at": "2026-11-05T09:00:00+00:00"}
    markdown_parser.write(bank / "episodes" / f"{episode}.md", ep, "A short post.")
    index_path = bank / "sources" / "url_index.json"
    index_path.parent.mkdir(exist_ok=True)
    index = json.loads(index_path.read_text()) if index_path.exists() else {}
    index[f"h-{slug}"] = {"media_entity_id": page, "url": link, "title": f"A post {n}", "saved_at": f"{day}T10:00:00+00:00",
                          "episode_id": episode, "content_saved_at": f"{day}T10:00:00+00:00"}
    index_path.write_text(json.dumps(index), encoding="utf-8")
    bank_index.invalidate()
    return page, episode


def settle(bank):
    git(bank, "add", "-A")
    subprocess.run(["git", "-C", str(bank), "commit", "-qm", "saves", "--allow-empty"], check=True, capture_output=True)
    bank_index.invalidate()


def page_of(bank, pid):
    return markdown_parser.parse(bank / "entities" / f"{pid}.md")


# ---------------------------------------------------------------------------------------------- ships dark


def test_dark_nothing_is_written_and_nothing_is_drawn(bank):
    save(bank, 1)
    settle(bank)
    before = commits(bank)
    assert saved_posts.HIDE_POSTS is False
    assert list_pages.sync(bank) == {"created": 0, "updated": 0, "retired": 0, "pending": 0}
    assert list_pages.start_sync(bank) is False
    assert lists(bank) == [] and commits(bank) == before
    assert list_pages.state(bank).drawn == {} and list_pages.stamp(bank) == ""
    assert not any(n.media_kind == "list" for n in graph_builder.build_graph(bank).nodes)


# ---------------------------------------------------------------------------------------------- born with its first item


def test_a_list_is_born_when_its_first_item_arrives_and_not_before(bank, on):
    assert list_pages.sync(bank)["created"] == 0 and lists(bank) == []
    save(bank, 1)
    out = list_pages.sync(bank)
    assert out["created"] == 1 and lists(bank) == ["list-x-bookmarks"]
    save(bank, 2, origin="x-likes", folder="Likes")
    save(bank, 3, origin="instagram-saved", folder="Saved", url="https://www.instagram.com/p/Cabc12345/")
    assert list_pages.sync(bank)["created"] == 2
    assert lists(bank) == ["list-instagram-saved", "list-x-bookmarks", "list-x-likes"]


def test_a_list_of_works_and_a_browsers_folder_get_no_page(bank, on):
    save(bank, 1, origin="youtube-playlist", folder="Watch later", url="https://www.youtube.com/watch?v=abcdefghijk")
    save(bank, 2, origin="chrome-bookmark", folder="Reading", url="https://example.com/a")
    save(bank, 3, origin="spotify-saved", folder="Library", url="https://open.spotify.com/track/1234567890abcdef")
    list_pages.sync(bank)
    assert lists(bank) == []


def test_the_page_holds_what_the_list_is_and_nothing_that_goes_stale(bank, on):
    save(bank, 1, day="2026-11-01")
    save(bank, 2, day=NEWEST)
    list_pages.sync(bank)
    parsed = page_of(bank, "list-x-bookmarks")
    fm = parsed.frontmatter
    assert fm["type"] == "media" and fm["media"] == {"kind": "list", "media_type": "list"} and "url" not in fm["media"]
    assert fm["origin"] == "list" and fm["name"] == "X: Bookmarks" and fm["status"] == "active"
    assert fm["tags"] == [] and fm["related"] == [] and fm["source_episodes"] == [] and fm["decay_class"] == "evergreen"
    assert fm["list"] == {"site": "x", "stream": "x.bookmarks", "folder": None, "source": "x-bookmarks",
                          "label": "Bookmarks", "named": "X: Bookmarks", "said": "Posts you bookmarked on X."}
    assert parsed.body.strip() == "## Summary\nPosts you bookmarked on X."   # the heading the app lifts as the row's line
    text = (bank / "entities" / "list-x-bookmarks.md").read_text()
    assert not any(word in text for word in ("A post 1", "A post 2", "2026-11-12", "status/1000001")), \
        "no row, no count and no newest day on the page"
    assert not "list-x-bookmarks".startswith("media-"), "inject_media_edges and link_enrichment glob media-*.md"


def test_a_second_sync_writes_and_commits_nothing_and_the_first_is_one_commit_by_cicada(bank, on):
    save(bank, 1)
    save(bank, 2, origin="x-likes", folder="Likes")
    settle(bank)
    before = commits(bank)
    list_pages.sync(bank)
    assert commits(bank) == before + 1
    message = git(bank, "log", "-1", "--format=%B")
    assert "Cicada-Author: cicada" in message and "sync/list_pages" in message
    assert list_pages.sync(bank) == {"created": 0, "updated": 0, "retired": 0, "pending": 0}
    assert commits(bank) == before + 1


def test_each_folder_gets_a_page_when_a_save_is_filed_in_it_and_an_empty_one_none(bank, on):
    save(bank, 1, folders=["Design ideas"])
    save(bank, 2, folders=["design ideas"])           # the same folder in another case
    save(bank, 3)
    out = list_pages.sync(bank)
    assert out["created"] == 2
    folder_pages = [p for p in lists(bank) if "--" in p]
    assert len(folder_pages) == 1 and folder_pages[0].startswith("list-x-bookmarks--design-ideas-")
    fm = page_of(bank, folder_pages[0]).frontmatter
    assert fm["name"] == "X: Bookmarks, Design ideas" and fm["list"]["folder"] == "Design ideas"
    assert "Design ideas" in page_of(bank, folder_pages[0]).body
    assert list_pages.page_id("x.bookmarks", "design ideas") == folder_pages[0]
    assert list_pages.page_id("x.bookmarks", "design-ideas") != folder_pages[0], "slugs that alike never share an id"


# ---------------------------------------------------------------------------------------------- what the page is not


def test_a_list_page_is_not_a_saved_item_a_member_a_hub_a_file_or_a_link(bank, on):
    save(bank, 1)
    save(bank, 2, origin="x-likes", folder="Likes")
    before = {sid: s["count"] for sid, s in
              {s["id"]: s for s in source_streams.build(bank, channels=[])["sources"][0]["streams"]}.items()}
    list_pages.sync(bank)
    bank_index.invalidate()
    mem = source_streams.members(bank)
    page = "list-x-bookmarks"
    assert all(page not in held for held in mem.members.values()) and page not in mem.streams_of
    after = {s["id"]: s["count"] for s in source_streams.build(bank, channels=[])["sources"][0]["streams"]}
    assert after["x.bookmarks"] == before["x.bookmarks"] == 1
    rows = channel_items.items(bank, "x", limit=50, stream="x.bookmarks")["items"]
    assert [r["id"] for r in rows] == ["media-x-bookmarks-1"]
    fm = page_of(bank, page).frontmatter
    assert not source_overview.is_files_media(fm)
    assert not saved_posts.is_post(fm)
    assert hub_builder._load_active_entities(bank / "entities")[0] and \
        page not in {m["id"] for m in hub_builder._load_active_entities(bank / "entities")[0]}
    assert "tags" in fm and fm["tags"] == []


def test_a_list_page_is_never_quiet_never_merged_never_asked_about_and_no_one_s_name(bank, on):
    save(bank, 1)
    list_pages.sync(bank)
    page = "list-x-bookmarks"
    assert not quiet_pages.page_is_quiet(bank, page) and not quiet_pages.page_is_dimmed(bank, page)
    assert inbox_service._subject_quiet(bank, page) is True, "a question about it is held, never served"
    with pytest.raises(ValueError):
        entity_merge.merge_entities(bank, page, "alpha-project")
    with pytest.raises(ValueError):
        entity_merge.merge_entities(bank, "alpha-project", page)
    with pytest.raises(page_join.JoinError):
        page_join.merge(bank, "alpha-project", page)
    existing = [{"id": page, "frontmatter": page_of(bank, page).frontmatter}]
    assert entity_resolver._is_file_page(existing[0]), "Stage 1 treats its name as no one's: a mention never joins it"


def test_an_archived_or_dropped_page_keeps_its_key_and_is_never_made_again_or_woken(bank, on):
    save(bank, 1)
    list_pages.sync(bank)
    parsed = page_of(bank, "list-x-bookmarks")
    parsed.frontmatter["status"] = "archived"
    markdown_parser.write(bank / "entities" / "list-x-bookmarks.md", parsed.frontmatter, parsed.body)
    bank_index.invalidate()
    assert list_pages.sync(bank)["created"] == 0
    assert page_of(bank, "list-x-bookmarks").frontmatter["status"] == "archived"
    assert "list-x-bookmarks" not in list_pages.state(bank).drawn


def test_a_name_the_person_gave_stands_and_the_lists_own_name_follows_a_change(bank, on, monkeypatch):
    save(bank, 1)
    save(bank, 2, origin="x-likes", folder="Likes")
    list_pages.sync(bank)
    renamed = page_of(bank, "list-x-likes")
    renamed.frontmatter["name"] = "The things I liked"
    markdown_parser.write(bank / "entities" / "list-x-likes.md", renamed.frontmatter, renamed.body)
    real = list_pages._name
    monkeypatch.setattr(list_pages, "_name", lambda site, label, folder: real(site, label, folder).replace("X:", "X —"))
    bank_index.invalidate()
    out = list_pages.sync(bank)
    assert out["updated"] == 1
    assert page_of(bank, "list-x-bookmarks").frontmatter["name"] == "X — Bookmarks"
    assert page_of(bank, "list-x-likes").frontmatter["name"] == "The things I liked"


# ---------------------------------------------------------------------------------------------- the lifecycle of a source


def test_removing_a_source_retires_its_pages_in_one_undoable_commit(bank, on):
    save(bank, 1)
    save(bank, 2, origin="x-likes", folder="Likes")
    save(bank, 3, origin="instagram-saved", folder="Saved", url="https://www.instagram.com/p/Cabc12345/")
    list_pages.sync(bank)
    settle(bank)
    before = commits(bank)
    assert list_pages.retire_source(bank, "x") == 2
    assert commits(bank) == before + 1 and "Cicada-Author: user" in git(bank, "log", "-1", "--format=%B")
    for pid in ("list-x-bookmarks", "list-x-likes"):
        fm = page_of(bank, pid).frontmatter
        assert fm["status"] == "archived" and fm["retired_by"] == "source-removed"
    assert page_of(bank, "list-instagram-saved").frontmatter["status"] == "active"
    assert list_pages.sync(bank)["created"] == 0, "never made again"
    git(bank, "revert", "--no-edit", "HEAD")
    bank_index.invalidate()
    assert page_of(bank, "list-x-bookmarks").frontmatter["status"] == "active", "undoable"


def test_a_list_that_left_the_table_retires_itself(bank, on):
    save(bank, 1)
    list_pages.sync(bank)
    parsed = page_of(bank, "list-x-bookmarks")
    parsed.frontmatter["list"]["stream"] = "x.gone"
    markdown_parser.write(bank / "entities" / "list-x-bookmarks.md", parsed.frontmatter, parsed.body)
    bank_index.invalidate()
    assert list_pages.sync(bank)["retired"] == 1
    assert page_of(bank, "list-x-bookmarks").frontmatter["status"] == "archived"


def test_turning_a_list_off_keeps_its_page(bank, on):
    from api.services import reading_settings

    save(bank, 1)
    list_pages.sync(bank)
    reading_settings.update(agent_enabled_=True, acknowledge=True)
    list_pages.sync(bank)
    assert "list-x-bookmarks" in lists(bank) and "list-x-bookmarks" in list_pages.state(bank).drawn


# ---------------------------------------------------------------------------------------------- the rails


def test_a_demo_bank_and_a_replica_refuse_the_write(bank, on, monkeypatch):
    save(bank, 1)
    with monkeypatch.context() as m:
        m.setattr(demo_guard, "is_demo", lambda mp: True)
        assert list_pages.sync(bank)["created"] == 0 and list_pages.start_sync(bank) is False
    with monkeypatch.context() as m:
        m.setattr(replica_guard, "blocks", lambda: True)
        assert list_pages.sync(bank)["created"] == 0 and list_pages.start_sync(bank) is False
    assert lists(bank) == []
    assert list_pages.sync(bank)["created"] == 1


def test_sleep_holding_the_pages_loses_nothing_and_a_retry_is_armed(bank, on, monkeypatch):
    save(bank, 1)
    with monkeypatch.context() as sleeping:
        sleeping.setattr(write_admission, "holding", lambda: True)
        with pytest.raises(write_admission.SleepHolding):
            list_pages.sync(bank)
        armed = []
        sleeping.setattr(list_pages.threading, "Timer",
                         lambda delay, fn, args=(): armed.append(delay) or type("T", (), {
                             "daemon": False, "start": lambda s: None, "is_alive": lambda s: False})())
        list_pages._run(bank, list_pages._Runner())
    assert armed == [list_pages.RETRY_S]
    assert lists(bank) == []
    assert list_pages.sync(bank)["created"] == 1


def test_the_same_bank_on_two_machines_gives_the_same_pages(tmp_path, on):
    first = _bank(tmp_path / "a")
    save(first, 1, day="2026-11-03", folders=["Trips"])
    save(first, 2, origin="x-likes", folder="Likes", day="2026-11-04")
    settle(first)
    second = tmp_path / "b" / "memory"
    shutil.copytree(first, second)
    bank_index.invalidate()
    list_pages.sync(first)
    bank_index.invalidate()
    list_pages.sync(second)
    names = lists(first)
    assert names == lists(second) and len(names) == 3
    for pid in names:
        assert (first / "entities" / f"{pid}.md").read_text() == (second / "entities" / f"{pid}.md").read_text()


# ---------------------------------------------------------------------------------------------- what is read, never stored


def test_the_count_the_newest_day_and_the_rows_are_read_each_time_and_the_tree_stays_clean(bank, on):
    save(bank, 1, day="2026-11-01")
    list_pages.sync(bank)
    settle(bank)
    page = page_of(bank, "list-x-bookmarks")
    first = list_pages.block(bank, "list-x-bookmarks", page.frontmatter)
    assert first["count"] == 1 and first["newest"] == "2026-11-01" and first["stream"] == "x.bookmarks"
    save(bank, 2, day=NEWEST)
    again = list_pages.block(bank, "list-x-bookmarks", page.frontmatter)
    assert again["count"] == 2 and again["newest"] == NEWEST
    assert [r["title"] for r in again["recent"]] == ["A post 2", "A post 1"], "newest first"
    assert list_pages.sync(bank)["updated"] == 0
    assert git(bank, "status", "--porcelain", "--", "entities/list-x-bookmarks.md").strip() == "", "no read rewrites it"


def test_at_most_five_rows_ride_the_block_and_the_count_says_all(bank, on):
    for n in range(1, 9):
        save(bank, n, day=f"2026-11-{n:02d}")
    list_pages.sync(bank)
    block = list_pages.block(bank, "list-x-bookmarks", page_of(bank, "list-x-bookmarks").frontmatter)
    assert block["count"] == 8 and len(block["recent"]) == 5
    assert [r["title"] for r in block["recent"]][:2] == ["A post 8", "A post 7"]
    assert block["lastReadAt"] is None, "this Mac never read the list: no per-Mac number on the page or invented"


def test_a_folders_reason_is_read_now_and_shows_only_on_its_page(bank, on):
    save(bank, 1, folders=["Trips"])
    list_pages.sync(bank)
    folder_page = next(p for p in lists(bank) if "--" in p)
    fm = page_of(bank, folder_page).frontmatter
    assert list_pages.block(bank, folder_page, fm)["why"] is None
    path = bank / save_folders.STORE
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({"version": 1, "folders": {"x-bookmarks": {"Trips": {
        "reasons": ["inspiration"], "text": "ideas for next spring", "at": "2026-11-10T10:00:00Z"}}}}))
    block = list_pages.block(bank, folder_page, fm)
    assert block["why"] == {"text": "ideas for next spring", "at": "2026-11-10"}
    assert "ideas for next spring" not in (bank / "entities" / f"{folder_page}.md").read_text()
    whole = list_pages.block(bank, "list-x-bookmarks", page_of(bank, "list-x-bookmarks").frontmatter)
    assert whole["why"] is None


def test_an_empty_or_renamed_folder_is_not_drawn_and_leaves_no_orphan_node(bank, on):
    page, episode = save(bank, 1, folders=["Trips"])
    list_pages.sync(bank)
    folder_page = next(p for p in lists(bank) if "--" in p)
    assert folder_page in list_pages.state(bank).drawn
    assert folder_page in {n.id for n in graph_builder.build_graph(bank).nodes}
    # the site renamed the folder: the save is filed under the new name, and the old one holds nothing
    save_folders.file_save(bank, episode, "x-bookmarks", add=["Journeys"], remove=["Trips"])
    bank_index.invalidate()
    assert folder_page not in list_pages.state(bank).drawn
    graph_builder.reset_cache()
    nodes = {n.id for n in graph_builder.build_graph(bank).nodes}
    assert folder_page not in nodes and "list-x-bookmarks" in nodes
    assert list_pages.sync(bank)["created"] == 1, "the new name's page is born; the old one is left, undrawn"


def test_a_list_page_is_the_same_dict_for_the_card_and_for_the_blocks_an_agent_is_given(bank, on):
    save(bank, 1)
    list_pages.sync(bank)
    page = page_of(bank, "list-x-bookmarks")
    built = page_blocks.build(bank, "list-x-bookmarks", fm=page.frontmatter, claims=[], relevance=None)
    kinds = page_blocks.wanted("blocks", remote=False)
    assert "list" in kinds, "the agent doors' `include` names it (both schemas advertise it)"
    again = page_blocks.for_page(bank, "list-x-bookmarks", kinds)
    assert built["list"] is not None and built["list"] == again["list"]
    assert "list" in built["order"] and "list" in again["order"]
    text = page_blocks.words(again, kinds)
    assert "1 saved" in text and "A post 1" in text and "never stored on the page" in text
    assert "list" in page_blocks.INCLUDE and "list" in page_blocks.REMOTE_INCLUDE
    served = page_blocks.for_caller(again, kinds, verbatim=True)
    assert "list" in served["order"] and served["list"] == built["list"]


def test_a_caller_without_sources_gets_no_words_of_what_was_saved(bank, on):
    save(bank, 1)
    list_pages.sync(bank)
    page = page_of(bank, "list-x-bookmarks")
    blocks = page_blocks.build(bank, "list-x-bookmarks", fm=page.frontmatter, claims=[], relevance=None)
    kinds = page_blocks.wanted("blocks", remote=True)
    masked = page_blocks.for_caller(blocks, kinds, verbatim=False)
    assert masked["list"]["count"] == 1 and masked["list"]["recent"] == [] and masked["list"]["why"] is None
    assert masked["list"]["recentWithheld"] is True
    assert "A post 1" not in page_blocks.words(masked, kinds, verbatim=False)
    open_ = page_blocks.for_caller(blocks, kinds, verbatim=True)
    assert open_["list"]["recent"][0]["title"] == "A post 1"


# ---------------------------------------------------------------------------------------------- the graph


def graph(bank):
    graph_builder.reset_cache()
    return graph_builder.build_graph(bank)


def test_each_non_empty_list_is_one_node_with_its_count_and_its_sources_mark(bank, on):
    for n in range(1, 4):
        save(bank, n)
    list_pages.sync(bank)
    g = graph(bank)
    nodes = {n.id: n for n in g.nodes}
    assert "list-x-bookmarks" in nodes and not any(i.startswith("media-") for i in nodes), "posts are rows"
    node = nodes["list-x-bookmarks"]
    assert node.media_kind == "list" and node.origin == "x-bookmarks" and node.member_count == 3 and not node.quiet
    assert node.type == "media" and node.name == "X: Bookmarks"


def test_a_list_page_is_no_node_before_it_holds_anything_or_while_dark(bank, monkeypatch):
    save(bank, 1)
    monkeypatch.setattr(saved_posts, "HIDE_POSTS", True)
    list_pages.sync(bank)
    assert "list-x-bookmarks" in {n.id for n in graph(bank).nodes}
    monkeypatch.setattr(saved_posts, "HIDE_POSTS", False)
    assert "list-x-bookmarks" not in {n.id for n in graph(bank).nodes}, "dark, a stray page file draws nothing"


def test_every_earned_post_is_joined_to_its_list_and_every_folder_page_to_its_lists_page(bank, on):
    earned, _ = save(bank, 1, folders=["Trips"], named=True)
    plain, _ = save(bank, 2, folders=["Trips"])
    other, _ = save(bank, 3, origin="x-likes", folder="Likes", named=True)
    list_pages.sync(bank)
    g = graph(bank)
    ids = {n.id for n in g.nodes}
    assert earned in ids and other in ids and plain not in ids
    folder_page = next(p for p in lists(bank) if "--" in p)
    pairs = {(l.source, l.target) for l in g.links if l.kind == "source"}
    assert (earned, "list-x-bookmarks") in pairs and (earned, folder_page) in pairs
    assert (other, "list-x-likes") in pairs and (other, "list-x-bookmarks") not in pairs
    assert (folder_page, "list-x-bookmarks") in pairs
    assert not any(plain in (l.source, l.target) for l in g.links)
    assert {l.label for l in g.links if l.kind == "source" and l.source == folder_page} == {"part of"}


def test_a_list_with_no_earned_post_is_a_lone_dot_on_purpose(bank, on):
    save(bank, 1)
    list_pages.sync(bank)
    g = graph(bank)
    assert not [l for l in g.links if "list-x-bookmarks" in (l.source, l.target)]


def test_the_graph_cache_moves_with_a_lists_count(bank, on):
    save(bank, 1)
    list_pages.sync(bank)
    first = {n.id: n for n in graph_builder.build_graph(bank).nodes}["list-x-bookmarks"]
    save(bank, 2)
    second = {n.id: n for n in graph_builder.build_graph(bank).nodes}["list-x-bookmarks"]
    assert (first.member_count, second.member_count) == (1, 2)
    assert first.content_hash != second.content_hash, "the app's diff sees the count move"


def test_the_graph_build_leaves_the_tree_clean_and_a_list_takes_no_hub_slot_or_meaning(bank, on):
    save(bank, 1)
    list_pages.sync(bank)
    settle(bank)
    graph(bank)
    assert git(bank, "status", "--porcelain").strip() == ""
    assert "list-x-bookmarks" in list_pages.drawn_ids(bank)


def test_a_list_page_reads_as_a_media_kind_the_app_lists(bank, on):
    save(bank, 1)
    list_pages.sync(bank)
    fm = page_of(bank, "list-x-bookmarks").frontmatter
    assert media_kinds.kind_of(fm) == "list" and media_kinds.origin_of(fm) == "x-bookmarks"


# ---------------------------------------------------------------------------------------------- the routes


@pytest.fixture
def client(bank, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    try:
        with TestClient(main.app) as c:
            yield c
    finally:
        config.get_settings.cache_clear()


def test_the_card_of_a_list_page_carries_its_media_block_and_its_list_block(bank, on, client):
    for n in range(1, 4):
        save(bank, n, day=f"2026-11-0{n}")
    list_pages.sync(bank)
    body = client.get("/entities/list-x-bookmarks").json()
    assert body["type"] == "media" and body["name"] == "X: Bookmarks" and body["quiet"] is False
    assert body["media"]["kind"] == "list" and body["media"]["url"] == ""
    block = body["blocks"]["list"]
    assert block["count"] == 3 and block["newest"] == "2026-11-03" and block["stream"] == "x.bookmarks"
    assert block["channel"] == "x" and block["source"] == "x-bookmarks" and block["folder"] is None
    assert [r["title"] for r in block["recent"]] == ["A post 3", "A post 2", "A post 1"]
    assert "list" in body["blocks"]["order"]
    assert body["markdownContent"].strip() == "## Summary\nPosts you bookmarked on X."


def test_the_card_moves_with_a_new_save_and_no_file_changes(bank, on, client):
    save(bank, 1)
    list_pages.sync(bank)
    first = client.get("/entities/list-x-bookmarks")
    save(bank, 2)
    bank_index.invalidate()
    again = client.get("/entities/list-x-bookmarks", headers={"if-none-match": first.headers["etag"]})
    assert again.status_code == 200 and again.json()["blocks"]["list"]["count"] == 2


def test_the_graph_route_draws_the_list_once_the_flip_is_on_and_not_before(bank, monkeypatch, client):
    save(bank, 1)
    monkeypatch.setattr(saved_posts, "HIDE_POSTS", True)
    list_pages.sync(bank)
    nodes = {n["id"]: n for n in client.get("/graph").json()["nodes"]}
    assert nodes["list-x-bookmarks"]["mediaKind"] == "list" and nodes["list-x-bookmarks"]["memberCount"] == 1
    assert nodes["list-x-bookmarks"]["origin"] == "x-bookmarks"
    monkeypatch.setattr(saved_posts, "HIDE_POSTS", False)
    assert "list-x-bookmarks" not in {n["id"] for n in client.get("/graph").json()["nodes"]}


def test_reading_the_streams_asks_for_the_pages_and_makes_them_only_after_the_flip(bank, monkeypatch, client):
    save(bank, 1)
    asked = []
    monkeypatch.setattr(list_pages, "start_sync", lambda mp, delay_s=0.0: asked.append(delay_s) or True)
    assert client.get("/sources/streams").status_code == 200
    assert asked == [list_pages.SETTLE_S]
    assert lists(bank) == [], "the route writes nothing itself"


# ---------------------------------------------------------------------------------------------- the wire, pinned on both sides

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "list_block.json"


def test_the_list_block_matches_the_shared_fixture(bank, on):
    """`ListPageCardTests.swift` decodes this same file: the one wire a card and an agent's blocks share."""
    import os

    from api.models.schemas import PageBlocks

    save(bank, 1, day="2026-11-01", folders=["Trips"])
    save(bank, 2, day="2026-11-04", folders=["Trips"])
    save(bank, 3, day="2026-11-09")
    list_pages.sync(bank)
    path = bank / save_folders.STORE
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({"version": 1, "folders": {"x-bookmarks": {"Trips": {
        "reasons": [], "text": "ideas for next spring", "at": "2026-11-10T10:00:00Z"}}}}))
    folder_page = next(p for p in lists(bank) if "--" in p)
    blocks = {}
    for pid in ("list-x-bookmarks", folder_page):
        built = page_blocks.build(bank, pid, fm=page_of(bank, pid).frontmatter, claims=[], relevance=None)
        blocks[pid.split("--")[0] + ("-folder" if "--" in pid else "")] = built["list"]
        PageBlocks(**built)    # the wire model accepts it
    if os.environ.get("CICADA_REGEN_FIXTURES"):
        FIXTURE.write_text(json.dumps({"_comment": "Shared by test_list_pages.py and ListPageCardTests.swift: the `list` "
                                       "block of GET /entities/{id} (list_pages.block). Regenerate with "
                                       "CICADA_REGEN_FIXTURES=1.", "lists": blocks}, indent=2) + "\n")
    assert blocks == json.loads(FIXTURE.read_text())["lists"]


def test_a_rename_never_replaces_words_the_person_wrote(bank, on, monkeypatch):
    save(bank, 1)
    save(bank, 2, origin="x-likes", folder="Likes")
    list_pages.sync(bank)
    mine = page_of(bank, "list-x-likes")
    markdown_parser.write(bank / "entities" / "list-x-likes.md", mine.frontmatter, "What I like to keep.\n")
    real = list_pages._name
    monkeypatch.setattr(list_pages, "_name", lambda site, label, folder: real(site, label, folder).replace("X:", "X —"))
    bank_index.invalidate()
    assert list_pages.sync(bank)["updated"] == 2
    assert page_of(bank, "list-x-likes").body.strip() == "What I like to keep."
    assert page_of(bank, "list-x-likes").frontmatter["name"] == "X — Likes"
    assert page_of(bank, "list-x-bookmarks").body.strip() == "## Summary\nPosts you bookmarked on X."


def test_a_pages_body_is_its_sentence_under_summary_so_its_row_keeps_its_line(bank, on):
    """Seen on the scratch app: a bare sentence was no `## Summary`, so a row lost its line once its page was opened.
    A page an earlier build wrote bare is still renamed in place (the sentence this writer wrote is replaced)."""
    save(bank, 1)
    list_pages.sync(bank)
    assert page_of(bank, "list-x-bookmarks").body.startswith("## Summary\n")
    path = bank / "entities" / "list-x-bookmarks.md"
    old = page_of(bank, "list-x-bookmarks")
    markdown_parser.write(path, old.frontmatter, "Posts you bookmarked on X.\n")       # the shape before this change
    bank_index.invalidate()
    list_pages.sync(bank)
    assert page_of(bank, "list-x-bookmarks").body.strip() == "Posts you bookmarked on X."   # unchanged: no rename, no rewrite
